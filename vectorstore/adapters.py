"""
Thin adapters that make existing retrieval code fit the ``agent.rag`` contracts.

These wrappers do **not** duplicate network logic. For live sources (UniProt,
PubChem, live KEGG, live PubMed) the adapter invokes the already-decorated
``@tool`` function via ``.invoke({...})`` and parses its JSON response into
typed ``EntityCandidate`` / ``Evidence`` objects. That way:

- Tools remain the single source of truth for API calls + auto-indexing.
- Any future refactor of a tool's internals propagates here for free.
- Tests can monkey-patch the tool function with a fake JSON producer.

Tier policy (see ``interfaces.ResolutionTier`` for semantics):

============== ================================================== =========
Adapter        Behavior                                            Tier
============== ================================================== =========
KeggIndexed*   semantic search over indexed Chroma collections    INFERRED
KeggLive       direct KEGG GET by canonical id                     EXACT
PubChem        numeric CID                                         EXACT
               name → CID resolution (PubChem fuzzy)               APPROXIMATE
UniProt        EC pattern                                          EXACT
               free-text protein name                              APPROXIMATE
Literature*    semantic search over ``literature`` collection     INFERRED
============== ================================================== =========

Confidence defaults (0.0–1.0, caller can override):
    EXACT        0.95
    APPROXIMATE  0.70
    INFERRED     retrieval cosine score, clamped to [0, 1]
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from agent.entities import (
    EntityCandidate,
    EntityKind,
    Enzyme,
    Evidence,
    Molecule,
    Paper,
    Reaction,
    ResolutionTier,
)
from vectorstore.retriever import RetrievedDoc, Retriever, get_retriever

log = logging.getLogger(__name__)

_EC_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_KEGG_CPD_RE = re.compile(r"^C\d{5}$")
_KEGG_RXN_RE = re.compile(r"^R\d{5}$")

_DEFAULT_CONFIDENCE = {
    ResolutionTier.EXACT: 0.95,
    ResolutionTier.APPROXIMATE: 0.70,
    ResolutionTier.INFERRED: 0.5,    # placeholder; replaced by retrieval score
}


def _confidence(tier: ResolutionTier, score: Optional[float] = None) -> float:
    if tier is ResolutionTier.INFERRED and score is not None:
        return max(0.0, min(1.0, float(score)))
    return _DEFAULT_CONFIDENCE[tier]


def _split_csv(val: Any) -> tuple[str, ...]:
    if not val:
        return ()
    if isinstance(val, (list, tuple)):
        return tuple(str(x).strip() for x in val if str(x).strip())
    return tuple(t.strip() for t in str(val).split(",") if t.strip())


# ---------- KEGG indexed (Chroma) ----------
class KeggIndexedResolver:
    """Resolve molecules/reactions against the indexed KEGG Chroma collections.

    This is a *semantic-similarity* resolver — it never promises an exact
    match. All candidates are tagged INFERRED. Phase 5's molecule resolver is
    expected to supersede this with tier-aware KEGG ID + synonym lookup.
    """

    name = "kegg_indexed"
    supported_kinds = (EntityKind.MOLECULE, EntityKind.REACTION)

    def __init__(self, retriever: Optional[Retriever] = None):
        self._retriever = retriever

    def _r(self) -> Retriever:
        if self._retriever is None:
            self._retriever = get_retriever()
        return self._retriever

    def resolve(self, query: str, kind: EntityKind, *, limit: int = 5) -> list[EntityCandidate]:
        q = (query or "").strip()
        if not q or kind not in self.supported_kinds:
            return []

        if kind is EntityKind.MOLECULE:
            hits = self._r().search_compounds(q, top_k=limit)
            return [self._molecule_candidate(d, q) for d in hits]
        hits = self._r().search_reactions(q, top_k=limit)
        return [self._reaction_candidate(d, q) for d in hits]

    def _molecule_candidate(self, d: RetrievedDoc, query: str) -> EntityCandidate:
        m = d.metadata
        mol = Molecule(
            canonical_id=str(m.get("kegg_id") or d.id),
            source="kegg",
            name=m.get("primary_name") or m.get("name"),
            synonyms=_split_csv(m.get("names")),
            formula=m.get("formula") or None,
            molecular_weight=_safe_float(m.get("molecular_weight")),
            url=f"https://www.kegg.jp/entry/{m.get('kegg_id') or d.id}",
            extras={"pathway_ids": m.get("pathway_ids") or ""},
        )
        return EntityCandidate(
            entity=mol,
            kind=EntityKind.MOLECULE,
            tier=ResolutionTier.INFERRED,
            confidence=_confidence(ResolutionTier.INFERRED, d.score),
            provenance=self.name,
            query=query,
        )

    def _reaction_candidate(self, d: RetrievedDoc, query: str) -> EntityCandidate:
        m = d.metadata
        rxn = Reaction(
            reaction_id=str(m.get("kegg_id") or d.id),
            source="kegg",
            equation=m.get("equation"),
            ec_numbers=_split_csv(m.get("ec_numbers")),
            substrates=_split_csv(m.get("substrates")),
            products=_split_csv(m.get("products")),
            pathway_ids=_split_csv(m.get("pathway_ids")),
            url=f"https://www.kegg.jp/entry/{m.get('kegg_id') or d.id}",
        )
        return EntityCandidate(
            entity=rxn,
            kind=EntityKind.REACTION,
            tier=ResolutionTier.INFERRED,
            confidence=_confidence(ResolutionTier.INFERRED, d.score),
            provenance=self.name,
            query=query,
        )


# ---------- KEGG live (REST by canonical id) ----------
class KeggLiveResolver:
    """Exact-id KEGG REST lookup. Wraps the ``fetch_kegg_live`` @tool.

    Use this when a caller already has a KEGG ID (e.g., from PubChem's xrefs
    or a prior KEGG search). For free-text queries, prefer KeggIndexedResolver.
    """

    name = "kegg_live"
    supported_kinds = (EntityKind.MOLECULE, EntityKind.REACTION, EntityKind.ENZYME)

    def resolve(self, query: str, kind: EntityKind, *, limit: int = 5) -> list[EntityCandidate]:
        q = (query or "").strip()
        if not q or kind not in self.supported_kinds:
            return []
        # TODO(phase7): respect DEMO_MODE
        payload = _invoke_tool("fetch_kegg_live", {"entity_id": q})
        if not payload or payload.get("note") or payload.get("error"):
            return []

        if kind is EntityKind.MOLECULE and _looks_like_compound(q):
            entity = Molecule(
                canonical_id=payload.get("kegg_id", q),
                source="kegg",
                name=payload.get("name"),
                formula=payload.get("formula"),
                url=payload.get("url"),
            )
            return [self._candidate(entity, EntityKind.MOLECULE, q)]

        if kind is EntityKind.REACTION and _looks_like_reaction(q):
            entity = Reaction(
                reaction_id=payload.get("kegg_id", q),
                source="kegg",
                equation=payload.get("equation"),
                ec_numbers=_split_csv(payload.get("enzymes")),
                pathway_ids=_split_csv(payload.get("pathways")),
                url=payload.get("url"),
            )
            return [self._candidate(entity, EntityKind.REACTION, q)]

        if kind is EntityKind.ENZYME and _EC_RE.match(_strip_ec_prefix(q)):
            entity = Enzyme(
                ec_number=payload.get("kegg_id", q).removeprefix("ec:"),
                recommended_name=payload.get("name"),
                source="kegg",
                url=payload.get("url"),
            )
            return [self._candidate(entity, EntityKind.ENZYME, q)]

        return []

    def _candidate(self, entity, kind: EntityKind, query: str) -> EntityCandidate:
        return EntityCandidate(
            entity=entity,
            kind=kind,
            tier=ResolutionTier.EXACT,
            confidence=_confidence(ResolutionTier.EXACT),
            provenance=self.name,
            query=query,
        )


# ---------- PubChem ----------
class PubChemResolver:
    """Resolve molecules against PubChem. Wraps the ``fetch_pubchem`` @tool.

    A numeric CID is treated as EXACT; a free-text name goes through
    PubChem's name→CID service which is fuzzy, so those are APPROXIMATE.
    """

    name = "pubchem"
    supported_kinds = (EntityKind.MOLECULE,)

    def resolve(self, query: str, kind: EntityKind, *, limit: int = 5) -> list[EntityCandidate]:
        q = (query or "").strip()
        if not q or kind is not EntityKind.MOLECULE:
            return []
        # TODO(phase7): respect DEMO_MODE
        payload = _invoke_tool("fetch_pubchem", {"compound_name_or_cid": q})
        if not payload or payload.get("error"):
            return []
        cid = payload.get("cid")
        if cid is None:
            return []

        tier = ResolutionTier.EXACT if q.isdigit() else ResolutionTier.APPROXIMATE
        mol = Molecule(
            canonical_id=f"CID:{cid}",
            source="pubchem",
            name=payload.get("iupac_name") or q,
            synonyms=tuple(payload.get("synonyms") or ()),
            formula=payload.get("molecular_formula"),
            molecular_weight=_safe_float(payload.get("molecular_weight")),
            smiles=payload.get("canonical_smiles"),
            url=payload.get("url"),
        )
        return [EntityCandidate(
            entity=mol,
            kind=EntityKind.MOLECULE,
            tier=tier,
            confidence=_confidence(tier),
            provenance=self.name,
            query=q,
        )]


# ---------- UniProt ----------
class UniProtResolver:
    """Resolve enzymes/proteins via UniProt. Wraps the ``fetch_uniprot`` @tool.

    EC-number queries are tagged EXACT (ec: field is a strict filter in
    UniProt's query DSL). Free-text protein-name queries are APPROXIMATE.
    """

    name = "uniprot"
    supported_kinds = (EntityKind.ENZYME,)

    def resolve(self, query: str, kind: EntityKind, *, limit: int = 5) -> list[EntityCandidate]:
        q = (query or "").strip()
        if not q or kind is not EntityKind.ENZYME:
            return []
        # TODO(phase7): respect DEMO_MODE
        payload = _invoke_tool("fetch_uniprot",
                               {"protein_name_or_ec": q, "organism": ""})
        if not payload or payload.get("error"):
            return []
        hits = payload.get("hits") or []
        if not hits:
            return []

        tier = ResolutionTier.EXACT if _EC_RE.match(q) else ResolutionTier.APPROXIMATE
        out: list[EntityCandidate] = []
        for h in hits[:limit]:
            ec_list = h.get("ec_numbers") or []
            enzyme = Enzyme(
                ec_number=ec_list[0] if ec_list else (q if _EC_RE.match(q) else None),
                recommended_name=h.get("protein_name"),
                uniprot_accession=h.get("accession"),
                gene_names=tuple(h.get("gene_names") or ()),
                organism=h.get("organism"),
                sequence_length=h.get("sequence_length"),
                source="uniprot",
                url=h.get("url"),
            )
            out.append(EntityCandidate(
                entity=enzyme,
                kind=EntityKind.ENZYME,
                tier=tier,
                confidence=_confidence(tier),
                provenance=self.name,
                query=q,
            ))
        return out


# ---------- Literature retriever (indexed) ----------
class LiteratureRetriever:
    """Structured retrieval over the indexed ``literature`` Chroma collection."""

    name = "literature_indexed"
    supported_kinds = (EntityKind.PAPER,)

    def __init__(self, retriever: Optional[Retriever] = None):
        self._retriever = retriever

    def _r(self) -> Retriever:
        if self._retriever is None:
            self._retriever = get_retriever()
        return self._retriever

    def retrieve(
        self,
        query: str,
        *,
        kind: Optional[EntityKind] = None,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = 5,
    ) -> list[Evidence]:
        q = (query or "").strip()
        if not q:
            return []
        if kind is not None and kind not in self.supported_kinds:
            return []
        filters = filters or {}
        hits = self._r().search_literature(
            q,
            source=filters.get("source"),
            mesh_term=filters.get("mesh_term"),
            top_k=top_k,
        )
        return [self._evidence(d) for d in hits]

    def _evidence(self, d: RetrievedDoc) -> Evidence:
        m = d.metadata or {}
        paper = Paper(
            pmid=str(m.get("pmid") or d.id),
            title=m.get("title"),
            year=str(m.get("year") or "") or None,
            journal=m.get("journal") or None,
            mesh_terms=_split_csv(m.get("mesh_terms")),
            snippet=_snippet(d.text),
            source=m.get("source") or "pubmed",
            url=(f"https://pubmed.ncbi.nlm.nih.gov/{m['pmid']}/"
                 if m.get("pmid") else None),
        )
        return Evidence(
            text=d.text or "",
            score=float(d.score),
            source="literature",
            doc_id=d.id,
            subject=paper,
            metadata=m,
        )


class KeggIndexedRetriever:
    """Structured retrieval (Evidence) over KEGG reactions + compounds."""

    name = "kegg_indexed_retriever"
    supported_kinds = (EntityKind.MOLECULE, EntityKind.REACTION)

    def __init__(self, retriever: Optional[Retriever] = None):
        self._retriever = retriever

    def _r(self) -> Retriever:
        if self._retriever is None:
            self._retriever = get_retriever()
        return self._retriever

    def retrieve(
        self,
        query: str,
        *,
        kind: Optional[EntityKind] = None,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = 5,
    ) -> list[Evidence]:
        q = (query or "").strip()
        if not q:
            return []
        filters = filters or {}
        evidence: list[Evidence] = []
        if kind in (None, EntityKind.REACTION):
            for d in self._r().search_reactions(
                q,
                ec_number=filters.get("ec_number"),
                pathway_id=filters.get("pathway_id"),
                compound_id=filters.get("compound_id"),
                top_k=top_k,
            ):
                evidence.append(Evidence(
                    text=d.text or "",
                    score=float(d.score),
                    source="kegg_reactions",
                    doc_id=d.id,
                    metadata=d.metadata,
                ))
        if kind in (None, EntityKind.MOLECULE):
            for d in self._r().search_compounds(
                q,
                compound_id=filters.get("compound_id"),
                top_k=top_k,
            ):
                evidence.append(Evidence(
                    text=d.text or "",
                    score=float(d.score),
                    source="kegg_compounds",
                    doc_id=d.id,
                    metadata=d.metadata,
                ))
        return evidence


# ---------- helpers ----------
def _invoke_tool(tool_name: str, args: dict) -> Optional[dict]:
    """Invoke one of our @tool-decorated functions and parse the JSON reply.

    Tools are imported lazily to avoid pulling heavy deps (requests sessions,
    XML parsers) at ``agent.rag`` import time.
    """
    try:
        if tool_name == "fetch_kegg_live":
            from agent.tools.fetch_kegg_live import fetch_kegg_live as fn
        elif tool_name == "fetch_pubchem":
            from agent.tools.fetch_pubchem import fetch_pubchem as fn
        elif tool_name == "fetch_uniprot":
            from agent.tools.fetch_uniprot import fetch_uniprot as fn
        elif tool_name == "fetch_pubmed_live":
            from agent.tools.fetch_pubmed_live import fetch_pubmed_live as fn
        else:
            log.warning("rag.adapters: unknown tool %r", tool_name)
            return None
    except Exception as e:  # noqa: BLE001
        log.warning("rag.adapters: failed to import %s (%s)", tool_name, e)
        return None

    try:
        raw = fn.invoke(args)
    except Exception as e:  # noqa: BLE001
        log.warning("rag.adapters: %s.invoke(%r) raised %s", tool_name, args, e)
        return None

    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        log.warning("rag.adapters: %s returned non-JSON payload", tool_name)
        return None


def _safe_float(val) -> Optional[float]:
    if val in (None, "", "n/a"):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _snippet(text: str, limit: int = 400) -> Optional[str]:
    if not text:
        return None
    s = text.strip().replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def _looks_like_compound(q: str) -> bool:
    raw = q.split(":")[-1].upper()
    return bool(_KEGG_CPD_RE.match(raw))


def _looks_like_reaction(q: str) -> bool:
    raw = q.split(":")[-1].upper()
    return bool(_KEGG_RXN_RE.match(raw))


def _strip_ec_prefix(q: str) -> str:
    """Remove a leading ``ec:`` / ``EC ``/ ``EC:`` prefix before matching.

    Uses string ``removeprefix`` (substring-aware) rather than ``lstrip``
    (character-set-based and silently mis-strips shared letters).
    """
    s = q.strip()
    # Case-insensitive prefixes.
    for prefix in ("ec:", "EC:", "EC ", "ec "):
        if s.lower().startswith(prefix.lower()):
            return s[len(prefix):].strip()
    return s
