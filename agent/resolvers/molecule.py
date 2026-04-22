"""
Phase 5 — strong molecule entity resolution.

Resolves user strings (common names, synonyms, KEGG compound IDs, PubChem
CIDs, ChEBI IDs, InChI/InChIKey, molecular formulas) into **canonical**
``Molecule`` objects. Canonical here means "one merged record that carries
every identifier + synonym we found across sources", not "a blessed ID from
a single database".

Design goals (anchored in ``codex_rag_design.md`` §3, §11):

1. **Layered tiers, explicit strategies** — Tier 1 exact-ID lookups run
   before Tier 2 synonym/name searches before Tier 3 semantic fallback.
   Each tier is its own method so callers (and future phases) can reason
   about behavior per-tier.
2. **Provenance preserved** — every :class:`EntityCandidate` keeps the
   resolver that produced it (``provenance``) and its tier. Merged canonical
   molecules preserve the full cross-ref dict so downstream tools can see
   exactly which databases agreed.
3. **Extension points are obvious** — ChEBI is stubbed with a concrete
   Protocol-compatible class (:class:`ChEBIResolver`) so adding ChEBI REST
   later is a single-class edit with no caller changes.
4. **Phase 4 adapters reused** — KEGG + PubChem resolvers from
   ``agent.rag.adapters`` are composed in, not duplicated.
5. **No new @tool** — this is an internal resolver layer. The ReAct agent's
   existing ``search_kegg`` / ``fetch_pubchem`` / ``fetch_kegg_live`` tools
   remain unchanged. Downstream code that wants canonical molecules calls
   :meth:`MoleculeResolver.resolve_canonical` directly.

Anti-scope:
- No SMILES parsing (not relevant yet; detection is conservative).
- No organism/strain resolution (Phase 6).
- No graph traversal (later phase).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence

from vectorstore.adapters import (
    KeggIndexedResolver,
    KeggLiveResolver,
    PubChemResolver,
    _invoke_tool,
)
from agent.entities import (
    EntityCandidate,
    EntityKind,
    Molecule,
    ResolutionTier,
)
from agent.tools._http import get_json, make_session

log = logging.getLogger(__name__)


# ---------- input-form classification ----------
class InputForm(str, Enum):
    """What the user typed. Drives which Tier 1 lookups to attempt."""

    EMPTY = "empty"
    KEGG_COMPOUND = "kegg_compound"          # C05432 / cpd:C05432
    CHEBI_ID = "chebi_id"                    # CHEBI:15756
    PUBCHEM_CID = "pubchem_cid"              # CID:446925 / 446925 / pure digits
    INCHI = "inchi"                          # starts with "InChI="
    INCHIKEY = "inchikey"                    # 27-char hyphenated block-notation
    FORMULA = "formula"                      # e.g. C10H16O
    NAME = "name"                            # everything else (default)


_KEGG_COMPOUND_RE = re.compile(r"^(?:cpd:)?C\d{5}$", re.IGNORECASE)
_CHEBI_RE = re.compile(r"^CHEBI:?\s*\d+$", re.IGNORECASE)
_PUBCHEM_CID_RE = re.compile(r"^(?:CID[:\s]*)?(\d{2,})$", re.IGNORECASE)
_INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
# Conservative formula: starts capital letter, alternates element+count, has
# at least one digit, no separators or whitespace.
_FORMULA_RE = re.compile(
    r"^(?:[A-Z][a-z]?\d*){2,}$"  # at least 2 element tokens
)


def classify_input(query: str) -> InputForm:
    """Heuristic classifier — cheap, regex-only, no network."""
    if not query:
        return InputForm.EMPTY
    q = query.strip()
    if not q:
        return InputForm.EMPTY
    if _KEGG_COMPOUND_RE.match(q):
        return InputForm.KEGG_COMPOUND
    if _CHEBI_RE.match(q):
        return InputForm.CHEBI_ID
    if q.startswith("InChI="):
        return InputForm.INCHI
    if _INCHIKEY_RE.match(q):
        return InputForm.INCHIKEY
    # CID has to come before formula: "CID:446925" matches cid; pure digits too.
    m = _PUBCHEM_CID_RE.match(q)
    if m:
        return InputForm.PUBCHEM_CID
    if _FORMULA_RE.match(q) and any(ch.isdigit() for ch in q):
        return InputForm.FORMULA
    return InputForm.NAME


# ---------- ChEBI stub ----------
class ChEBIResolver:
    """ChEBI adapter — Phase 5 ships the *contract*, not the implementation.

    Returns ``[]`` today. The resolver module registers it so that a future
    swap-in (e.g., a class that hits
    ``https://www.ebi.ac.uk/ols4/api/ontologies/chebi/terms``) becomes a
    one-file change. The MoleculeResolver already plumbs its output through
    the same tier/merge pipeline.

    To implement:
    - ``resolve()`` for an EXACT ``CHEBI:15756`` lookup hits
      ``https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:15756`` (HTML),
      or the OLS4 JSON API for cleaner parsing.
    - For NAME queries, use
      ``/ols4/api/search?q=lycopene&ontology=chebi`` and tag candidates
      APPROXIMATE.
    - Cross-refs: ChEBI entries list KEGG + PubChem CIDs in their xref block,
      which feeds straight into :class:`Molecule.cross_refs`.
    """

    name = "chebi"
    supported_kinds = (EntityKind.MOLECULE,)
    enabled: bool = False

    def resolve(self, query: str, kind: EntityKind, *,
                limit: int = 5) -> list[EntityCandidate]:
        if not self.enabled:
            log.debug("ChEBIResolver.resolve: stub disabled; returning []")
            return []
        # Implementation placeholder — kept here so subclasses can override
        # just the network methods without rewriting the wrapper.
        return self._fetch(query, kind, limit=limit)

    def _fetch(self, query: str, kind: EntityKind,
               *, limit: int) -> list[EntityCandidate]:
        raise NotImplementedError(
            "ChEBI integration is stubbed in Phase 5. Subclass and override "
            "_fetch(), or wait for the dedicated ChEBI phase."
        )


# ---------- PubChem InChIKey helper ----------
_pubchem_session = make_session()
_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def _pubchem_cid_from_inchikey(inchikey: str) -> Optional[int]:
    """PubChem `/compound/inchikey/{key}/cids/JSON` lookup. None on miss."""
    url = f"{_PUBCHEM_BASE}/compound/inchikey/{inchikey}/cids/JSON"
    # TODO(phase7): respect DEMO_MODE
    data = get_json(_pubchem_session, url)
    if not data:
        return None
    cids = (data or {}).get("IdentifierList", {}).get("CID", [])
    return int(cids[0]) if cids else None


def _pubchem_cid_from_formula(formula: str) -> Optional[int]:
    """Best-effort: PubChem `/compound/fastformula/{F}/cids/JSON`."""
    url = f"{_PUBCHEM_BASE}/compound/fastformula/{formula}/cids/JSON"
    # TODO(phase7): respect DEMO_MODE
    data = get_json(_pubchem_session, url)
    if not data:
        return None
    cids = (data or {}).get("IdentifierList", {}).get("CID", [])
    return int(cids[0]) if cids else None


# ---------- MoleculeResolver ----------
@dataclass
class _ResolvedBundle:
    """Internal: gathers per-source hits before we merge them."""
    candidates: list[EntityCandidate] = field(default_factory=list)

    def add(self, cands: Sequence[EntityCandidate]) -> None:
        self.candidates.extend(cands)


class MoleculeResolver:
    """Phase 5 canonical molecule resolver.

    Tier strategy (see codex_rag_design.md §11):

    - **Tier 1 — EXACT**: route by :class:`InputForm`. Direct KEGG GET for
      ``C05432``, PubChem CID, ChEBI (stubbed), InChIKey → PubChem, formula →
      PubChem/KEGG. Candidates tagged :attr:`ResolutionTier.EXACT`.
    - **Tier 2 — APPROXIMATE / synonym**: for NAME inputs, run PubChem
      name→CID (fuzzy), KEGG indexed search, ChEBI name search (stub). These
      candidates carry :attr:`ResolutionTier.APPROXIMATE` or the adapter's
      own tier if the adapter is already stricter (e.g., PubChem digit CID).
    - **Tier 3 — INFERRED**: semantic fallback against the KEGG indexed
      Chroma collection. Last resort; low confidence.

    Separately, :meth:`resolve_canonical` returns a single merged
    :class:`Molecule` that unions synonyms + cross-refs across the matched
    candidates — that's the object downstream tools should consume.

    Thread-safety: sub-resolvers must be thread-safe. All members we add are
    stateless per-call except for any shared HTTP session, which is already
    wrapped by ``agent.tools._http``.
    """

    name = "molecule_resolver"
    supported_kinds = (EntityKind.MOLECULE,)

    def __init__(
        self,
        *,
        kegg_live: Optional[KeggLiveResolver] = None,
        kegg_indexed: Optional[KeggIndexedResolver] = None,
        pubchem: Optional[PubChemResolver] = None,
        chebi: Optional[ChEBIResolver] = None,
        inchikey_lookup=_pubchem_cid_from_inchikey,
        formula_lookup=_pubchem_cid_from_formula,
    ):
        self._kegg_live = kegg_live or KeggLiveResolver()
        self._kegg_indexed = kegg_indexed or KeggIndexedResolver()
        self._pubchem = pubchem or PubChemResolver()
        self._chebi = chebi or ChEBIResolver()
        self._inchikey_lookup = inchikey_lookup
        self._formula_lookup = formula_lookup

    # ---------- public API ----------
    def resolve(self, query: str, kind: EntityKind = EntityKind.MOLECULE,
                *, limit: int = 5) -> list[EntityCandidate]:
        """Return tier-ordered, deduped molecule candidates for ``query``.

        ``kind`` is accepted for EntityResolver-Protocol conformance; this
        resolver only handles :attr:`EntityKind.MOLECULE`. Other kinds
        short-circuit to ``[]``.
        """
        if kind is not EntityKind.MOLECULE:
            return []
        q = (query or "").strip()
        if not q:
            return []

        form = classify_input(q)
        bundle = _ResolvedBundle()

        self._tier1_exact(q, form, bundle)
        if not _any_tier(bundle.candidates, ResolutionTier.EXACT):
            self._tier2_synonym(q, form, bundle)
        if not bundle.candidates:
            self._tier3_inferred(q, bundle)

        merged = self._merge(bundle.candidates, query=q)
        return merged[:limit]

    def resolve_canonical(self, query: str) -> Optional[Molecule]:
        """Return the single best-merged :class:`Molecule`, or ``None``.

        Downstream tools should prefer this — it hides tier/candidate
        semantics and hands back one structured record with synonyms and
        cross-refs already stitched together.
        """
        cands = self.resolve(query, limit=3)
        if not cands:
            return None
        return cands[0].entity  # type: ignore[return-value]

    # ---------- Tier 1 — exact ID ----------
    def _tier1_exact(self, q: str, form: InputForm,
                     bundle: _ResolvedBundle) -> None:
        if form is InputForm.KEGG_COMPOUND:
            bundle.add(self._kegg_live.resolve(q, EntityKind.MOLECULE))

        elif form is InputForm.PUBCHEM_CID:
            # PubChem adapter already tags EXACT for digit queries.
            cid = _extract_cid(q)
            if cid:
                bundle.add(self._pubchem.resolve(str(cid), EntityKind.MOLECULE))

        elif form is InputForm.CHEBI_ID:
            bundle.add(self._chebi.resolve(q, EntityKind.MOLECULE))

        elif form is InputForm.INCHIKEY:
            cid = self._inchikey_lookup(q)
            if cid:
                hits = self._pubchem.resolve(str(cid), EntityKind.MOLECULE)
                # Upgrade adapter's tier — a PubChem hit via an exact
                # InChIKey match is structurally exact even though the
                # adapter itself only sees a numeric CID.
                bundle.add(_retag(hits, ResolutionTier.EXACT, inchikey=q))

        elif form is InputForm.INCHI:
            # We don't parse InChI — fall through to name-ish search.
            # If the caller produced an InChI, they can also produce the
            # InChIKey; point them there.
            log.debug("InChI string given; consider passing InChIKey instead.")

        elif form is InputForm.FORMULA:
            cid = self._formula_lookup(q)
            if cid:
                hits = self._pubchem.resolve(str(cid), EntityKind.MOLECULE)
                # Formula matches are ambiguous (many isomers). Tier down.
                bundle.add(_retag(hits, ResolutionTier.APPROXIMATE))

    # ---------- Tier 2 — synonym / name ----------
    def _tier2_synonym(self, q: str, form: InputForm,
                       bundle: _ResolvedBundle) -> None:
        if form in (InputForm.NAME, InputForm.FORMULA, InputForm.INCHI):
            # PubChem name→CID (adapter tags APPROXIMATE automatically).
            bundle.add(self._pubchem.resolve(q, EntityKind.MOLECULE))
            # ChEBI name search (stub is safe — returns []).
            bundle.add(self._chebi.resolve(q, EntityKind.MOLECULE))

        # A KEGG compound ID that didn't hit Tier 1 can still semantic-search
        # the indexed corpus — but only for NAME / FORMULA / INCHI.
        if form in (InputForm.NAME, InputForm.FORMULA):
            # Upgrade top inferred hits to APPROXIMATE when their metadata
            # name actually contains the query substring (a weak "synonym"
            # signal from the indexed KEGG metadata).
            raw = self._kegg_indexed.resolve(q, EntityKind.MOLECULE, limit=5)
            bundle.add(_promote_name_matches(raw, q))

    # ---------- Tier 3 — inferred semantic ----------
    def _tier3_inferred(self, q: str, bundle: _ResolvedBundle) -> None:
        bundle.add(self._kegg_indexed.resolve(q, EntityKind.MOLECULE, limit=5))

    # ---------- merge ----------
    def _merge(self, cands: list[EntityCandidate], *,
               query: str) -> list[EntityCandidate]:
        """Stitch candidates that refer to the same molecule into one record.

        Merge keys, in priority order:
        1. shared InChIKey (strongest — same structure)
        2. shared cross-ref (e.g., KEGG candidate lists pubchem_cid that
           matches a PubChem candidate's canonical_id)
        3. same ``(source, canonical_id)`` pair (duplicate from sub-resolver)

        When merging, we pick the best-tier candidate as the "primary" and
        enrich its :class:`Molecule` with the union of synonyms, cross-refs,
        and any missing fields from the other candidates.
        """
        if not cands:
            return []

        # Sort best-tier-first so the merge target is always the highest-tier.
        ordered = sorted(cands, key=_rank_key)

        groups: list[list[EntityCandidate]] = []
        assigned: dict[int, int] = {}  # id(candidate) -> group index
        xref_index: dict[tuple[str, str], int] = {}
        inchikey_index: dict[str, int] = {}

        for c in ordered:
            mol = c.entity
            if not isinstance(mol, Molecule):
                continue

            keys = _merge_keys(mol)
            target: Optional[int] = None
            # InChIKey first.
            if mol.inchikey and mol.inchikey in inchikey_index:
                target = inchikey_index[mol.inchikey]
            if target is None:
                for k in keys:
                    if k in xref_index:
                        target = xref_index[k]
                        break

            if target is None:
                groups.append([c])
                gi = len(groups) - 1
            else:
                groups[target].append(c)
                gi = target

            assigned[id(c)] = gi
            if mol.inchikey:
                inchikey_index.setdefault(mol.inchikey, gi)
            for k in keys:
                xref_index.setdefault(k, gi)

        merged_candidates: list[EntityCandidate] = []
        for group in groups:
            primary = group[0]
            if len(group) == 1:
                merged_candidates.append(primary)
                continue
            merged_mol = _merge_molecules([c.entity for c in group])  # type: ignore[arg-type]
            merged_candidates.append(EntityCandidate(
                entity=merged_mol,
                kind=EntityKind.MOLECULE,
                tier=primary.tier,
                confidence=max(c.confidence for c in group),
                provenance=f"{self.name}:{'+'.join(sorted({c.provenance for c in group}))}",
                query=query,
                extras={"merged_from": tuple(c.provenance for c in group)},
            ))
        merged_candidates.sort(key=_rank_key)
        return merged_candidates


# ---------- helpers ----------
def _extract_cid(q: str) -> Optional[int]:
    m = _PUBCHEM_CID_RE.match(q)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _any_tier(cands: list[EntityCandidate], tier: ResolutionTier) -> bool:
    return any(c.tier is tier for c in cands)


def _retag(cands: list[EntityCandidate], tier: ResolutionTier,
           *, inchikey: Optional[str] = None) -> list[EntityCandidate]:
    """Return copies of ``cands`` with a forced tier (and optional inchikey)."""
    out: list[EntityCandidate] = []
    for c in cands:
        mol = c.entity
        if isinstance(mol, Molecule) and inchikey and not mol.inchikey:
            mol = Molecule(
                canonical_id=mol.canonical_id,
                source=mol.source,
                name=mol.name,
                synonyms=mol.synonyms,
                formula=mol.formula,
                molecular_weight=mol.molecular_weight,
                smiles=mol.smiles,
                inchi=mol.inchi,
                inchikey=inchikey,
                url=mol.url,
                cross_refs=mol.cross_refs,
                extras=dict(mol.extras),
            )
        out.append(EntityCandidate(
            entity=mol,
            kind=c.kind,
            tier=tier,
            confidence=max(c.confidence, 0.9 if tier is ResolutionTier.EXACT else c.confidence),
            provenance=c.provenance,
            query=c.query,
            extras=dict(c.extras),
        ))
    return out


def _promote_name_matches(cands: list[EntityCandidate], query: str) -> list[EntityCandidate]:
    """Upgrade inferred hits whose name matches ``query`` (case-insensitive)."""
    ql = query.lower()
    out: list[EntityCandidate] = []
    for c in cands:
        mol = c.entity
        if not isinstance(mol, Molecule):
            out.append(c)
            continue
        names = [n.lower() for n in ((mol.name,) + mol.synonyms) if n]
        if any(ql == n or ql in n for n in names):
            out.append(EntityCandidate(
                entity=mol,
                kind=c.kind,
                tier=ResolutionTier.APPROXIMATE,
                confidence=max(c.confidence, 0.75),
                provenance=c.provenance,
                query=c.query,
                extras=dict(c.extras),
            ))
        else:
            out.append(c)
    return out


def _merge_keys(mol: Molecule) -> list[tuple[str, str]]:
    """All cross-ref keys that identify ``mol`` for merging."""
    keys: list[tuple[str, str]] = [(mol.source.lower(), mol.canonical_id)]
    for db, cid in mol.cross_refs:
        if db and cid:
            keys.append((db.lower(), str(cid)))
    return keys


def _merge_molecules(mols: Sequence[Molecule]) -> Molecule:
    """Combine multiple Molecules describing the same compound.

    Primary is the first mol (caller sorts best-first). We fill missing
    fields from the rest, dedupe synonyms, and merge cross_refs including
    each non-primary molecule's own (source, canonical_id) pair.
    """
    primary = mols[0]
    synonyms: list[str] = list(primary.synonyms)
    cross_refs: dict[str, str] = dict(primary.cross_refs)
    extras = dict(primary.extras)
    formula = primary.formula
    mw = primary.molecular_weight
    smiles = primary.smiles
    inchi = primary.inchi
    inchikey = primary.inchikey
    url = primary.url
    name = primary.name

    for m in mols[1:]:
        if name is None:
            name = m.name
        for s in m.synonyms:
            if s and s not in synonyms:
                synonyms.append(s)
        # Add m's own identity as a cross-ref.
        if m.source and m.canonical_id:
            cross_refs.setdefault(m.source, m.canonical_id)
        for db, cid in m.cross_refs:
            if db and cid:
                cross_refs.setdefault(db, cid)
        formula = formula or m.formula
        mw = mw if mw is not None else m.molecular_weight
        smiles = smiles or m.smiles
        inchi = inchi or m.inchi
        inchikey = inchikey or m.inchikey
        url = url or m.url
        for k, v in m.extras.items():
            extras.setdefault(k, v)

    return Molecule(
        canonical_id=primary.canonical_id,
        source=primary.source,
        name=name,
        synonyms=tuple(synonyms),
        formula=formula,
        molecular_weight=mw,
        smiles=smiles,
        inchi=inchi,
        inchikey=inchikey,
        url=url,
        cross_refs=tuple(sorted(cross_refs.items())),
        extras=extras,
    )


def _rank_key(c: EntityCandidate) -> tuple[int, float, str]:
    return (c.tier.rank(), -float(c.confidence), c.provenance)
