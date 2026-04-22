"""
Phase 6 — organism / chassis resolution.

Resolves user strings (chassis aliases, species names, strain names, KEGG
organism codes, common abbreviations) into :class:`Organism` records.

Preserves ``config.CHASSIS_ORGANISMS`` as the **source of truth** for the
five Day-1 hosts (E. coli, S. cerevisiae, C. glutamicum, B. subtilis, P.
putida). An in-module alias table augments that dict with the common human
forms (``"e. coli"``, ``"MG1655"``, ``"sce"``, ``"yeast"``, …) which the
legacy chassis dict never encoded.

Resolution levels (codex_rag_design.md §12):

    Tier 1 EXACT — strain-level hit
        e.g. ``"MG1655"``, ``"S288c"``, full scientific_name
        ResolutionTier.EXACT  +  MatchType.EXACT_STRAIN

    Tier 2 EXACT — species-level hit (strain unknown → chassis default
        strain returned, but flagged as species-level)
        e.g. ``"Escherichia coli"``, ``"Saccharomyces cerevisiae"``
        ResolutionTier.EXACT  +  MatchType.EXACT_SPECIES

    Tier 3 APPROXIMATE — chassis-generalized fallback
        e.g. ``"ecoli"`` (chassis key), ``"E. coli"`` (common form),
        ``"eco"`` (KEGG org code), ``"yeast"``
        ResolutionTier.APPROXIMATE  +  MatchType.CHASSIS_GENERALIZED

    (No match) — returns an empty list. We intentionally do **not** guess
        a chassis for unknown inputs; callers can decide whether to default.

Extension points:
- ``taxonomy_lookup`` — callable hook for future NCBI taxonomy ingestion.
  Default is ``None``; when provided, called with a normalized query string
  and expected to return ``Optional[Organism]`` with source="ncbi_taxonomy".
- ``chassis_map`` — override the canonical chassis dict (tests inject a
  minimal fixture; production uses ``config.CHASSIS_ORGANISMS``).

Anti-scope (per phase brief):
- No full NCBI taxonomy download.
- No strain-level genome ingestion.
- No rule engine (e.g., no "this strain is secretion-competent" tags).
- No modification of the legacy tools (``retrosynthesis._resolve_host_key`` /
  ``enzyme_ranker._kegg_org_code``). Resolver is opt-in.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional

from agent.entities import (
    EntityCandidate,
    EntityKind,
    MatchType,
    Organism,
    ResolutionTier,
)
from config import CHASSIS_ORGANISMS

log = logging.getLogger(__name__)


# ---------- alias metadata ----------
# Keyed by chassis key (same as ``config.CHASSIS_ORGANISMS`` keys). Everything
# here is *augmentation* — the chassis dict stays canonical for
# scientific_name/kegg_org/native_pathways.
_CHASSIS_ALIASES: dict[str, dict] = {
    "ecoli": {
        "species": "Escherichia coli",
        "strain": "K-12 MG1655",
        "common_names": ("E. coli", "e. coli", "e.coli", "coli"),
        "strain_aliases": ("MG1655", "K-12", "K12", "K-12 MG1655",
                           "K-12 substr. MG1655"),
        "taxonomy_id": "511145",
    },
    "scerevisiae": {
        "species": "Saccharomyces cerevisiae",
        "strain": "S288C",
        "common_names": ("S. cerevisiae", "s. cerevisiae", "yeast",
                         "baker's yeast", "brewer's yeast"),
        "strain_aliases": ("S288c", "S288C"),
        "taxonomy_id": "559292",
    },
    "cglutamicum": {
        "species": "Corynebacterium glutamicum",
        "strain": "ATCC 13032",
        "common_names": ("C. glutamicum", "c. glutamicum", "glutamicum"),
        "strain_aliases": ("ATCC 13032", "ATCC13032", "13032"),
        "taxonomy_id": "196627",
    },
    "bsubtilis": {
        "species": "Bacillus subtilis",
        "strain": "168",
        "common_names": ("B. subtilis", "b. subtilis", "subtilis"),
        "strain_aliases": ("168", "str. 168", "subsp. 168"),
        "taxonomy_id": "224308",
    },
    "pputida": {
        "species": "Pseudomonas putida",
        "strain": "KT2440",
        "common_names": ("P. putida", "p. putida", "putida"),
        "strain_aliases": ("KT2440", "KT 2440", "KT-2440"),
        "taxonomy_id": "160488",
    },
}


# ---------- normalization ----------
def _normalize(q: str) -> str:
    """Fold case, collapse whitespace, strip surrounding noise.

    We *keep* interior dots and hyphens (important for "K-12", "S. cerevisiae"
    match paths). For strain-alias matching we also compare a dot-stripped
    variant so ``"E. coli"`` and ``"E.coli"`` land on the same bucket.
    """
    s = (q or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _squash_dots(q: str) -> str:
    return _normalize(q).replace(".", "")


# ---------- input form classifier ----------
class _Form:
    KEGG_ORG = "kegg_org"               # "eco", "sce" — 3-4 lowercase letters
    TAXONOMY_ID = "taxonomy_id"         # pure digits
    OTHER = "other"                     # chassis key, alias, species, strain


_KEGG_ORG_RE = re.compile(r"^[a-z]{3,4}$")
_NUMERIC_RE = re.compile(r"^\d+$")


def _classify_form(q: str) -> str:
    if _NUMERIC_RE.match(q):
        return _Form.TAXONOMY_ID
    if _KEGG_ORG_RE.match(q):
        return _Form.KEGG_ORG
    return _Form.OTHER


# ---------- OrganismResolver ----------
@dataclass
class _ResolvedBundle:
    candidates: list[EntityCandidate] = field(default_factory=list)

    def add(self, cands: Iterable[EntityCandidate]) -> None:
        self.candidates.extend(cands)


class OrganismResolver:
    """Hierarchical chassis/organism resolution.

    Thread-safe for read-only use. Constructed once at startup; callers share
    a single instance. Sub-resolvers (taxonomy lookup) are injected.
    """

    name = "organism_resolver"
    supported_kinds = (EntityKind.ORGANISM,)

    def __init__(
        self,
        *,
        chassis_map: Optional[Mapping[str, Mapping[str, Any]]] = None,
        chassis_aliases: Optional[Mapping[str, Mapping[str, Any]]] = None,
        taxonomy_lookup: Optional[Callable[[str], Optional[Organism]]] = None,
    ):
        self._chassis_map = dict(chassis_map) if chassis_map is not None else dict(CHASSIS_ORGANISMS)
        self._aliases = dict(chassis_aliases) if chassis_aliases is not None else _CHASSIS_ALIASES
        self._taxonomy_lookup = taxonomy_lookup

        # Pre-compute lookup indices once at startup.
        # Each key maps to the chassis key (e.g., "ecoli").
        self._index_strain: dict[str, str] = {}
        self._index_species: dict[str, str] = {}
        self._index_generalized: dict[str, str] = {}
        self._build_indices()

    # ---------- index construction ----------
    def _build_indices(self) -> None:
        for key, chassis in self._chassis_map.items():
            aliases = self._aliases.get(key, {})
            scientific = chassis.get("name") or ""
            kegg_org = chassis.get("kegg_org") or ""
            species = aliases.get("species") or ""
            strain = aliases.get("strain") or ""
            strain_aliases = tuple(aliases.get("strain_aliases") or ())
            common_names = tuple(aliases.get("common_names") or ())
            tax_id = aliases.get("taxonomy_id")

            # --- Tier 1 (strain) ---
            # Full scientific name (chassis + strain) is strain-level.
            if scientific:
                self._index_strain[_normalize(scientific)] = key
                self._index_strain[_squash_dots(scientific)] = key
            for s in strain_aliases:
                self._index_strain[_normalize(s)] = key
                self._index_strain[_squash_dots(s)] = key
            if strain:
                self._index_strain[_normalize(strain)] = key
                self._index_strain[_squash_dots(strain)] = key
            if tax_id:
                self._index_strain[tax_id] = key

            # --- Tier 2 (species) ---
            if species:
                self._index_species[_normalize(species)] = key
                self._index_species[_squash_dots(species)] = key

            # --- Tier 3 (chassis/generalized) ---
            self._index_generalized[_normalize(key)] = key
            if kegg_org:
                self._index_generalized[_normalize(kegg_org)] = key
            for cn in common_names:
                self._index_generalized[_normalize(cn)] = key
                self._index_generalized[_squash_dots(cn)] = key

    # ---------- public API ----------
    def resolve(
        self,
        query: str,
        kind: EntityKind = EntityKind.ORGANISM,
        *,
        limit: int = 5,
    ) -> list[EntityCandidate]:
        if kind is not EntityKind.ORGANISM:
            return []
        q = (query or "").strip()
        if not q:
            return []

        norm = _normalize(q)
        squashed = _squash_dots(q)
        form = _classify_form(norm)
        bundle = _ResolvedBundle()

        # --- Tier 1: exact strain ---
        chassis_key = self._index_strain.get(norm) or self._index_strain.get(squashed)
        if chassis_key:
            bundle.add([self._candidate_for(
                chassis_key, MatchType.EXACT_STRAIN, query=q)])

        # --- Tier 2: exact species ---
        # Only run if Tier 1 missed — species-level is strictly coarser.
        if not bundle.candidates:
            chassis_key = self._index_species.get(norm) or self._index_species.get(squashed)
            if chassis_key:
                bundle.add([self._candidate_for(
                    chassis_key, MatchType.EXACT_SPECIES, query=q)])

        # --- Tier 3: chassis-generalized ---
        if not bundle.candidates:
            chassis_key = self._index_generalized.get(norm) or self._index_generalized.get(squashed)
            if not chassis_key and form == _Form.KEGG_ORG:
                # Fallback: scan chassis_map for exact kegg_org == norm.
                chassis_key = self._kegg_org_to_key(norm)
            if chassis_key:
                bundle.add([self._candidate_for(
                    chassis_key, MatchType.CHASSIS_GENERALIZED, query=q)])

        # --- Taxonomy lookup hook (future NCBI integration) ---
        # Only if nothing matched locally; the chassis_map has priority so
        # operating-environment-specific hacks can't override us.
        if not bundle.candidates and self._taxonomy_lookup is not None:
            try:
                hit = self._taxonomy_lookup(norm)
            except Exception as e:  # noqa: BLE001
                log.warning("organism_resolver: taxonomy_lookup raised %s", e)
                hit = None
            if hit is not None:
                bundle.add([EntityCandidate(
                    entity=hit,
                    kind=EntityKind.ORGANISM,
                    tier=_tier_for_match_type(hit.match_type),
                    confidence=_confidence_for_match_type(hit.match_type),
                    provenance=f"{self.name}:taxonomy",
                    query=q,
                )])

        return bundle.candidates[:limit]

    def resolve_canonical(self, query: str) -> Optional[Organism]:
        """Return the best-matching :class:`Organism` or ``None``."""
        cands = self.resolve(query, limit=1)
        if not cands:
            return None
        return cands[0].entity  # type: ignore[return-value]

    # ---------- compatibility shims ----------
    def to_chassis_key(self, query: str) -> Optional[str]:
        """Return the chassis key (``"ecoli"``, ``"scerevisiae"``, ...) or None.

        Preserves the spirit of ``retrosynthesis._resolve_host_key`` but
        returns ``None`` instead of echoing unknown strings. Callers that
        want legacy echo-on-miss behavior should ``return resolver.to_chassis_key(q) or q.lower()``.
        """
        org = self.resolve_canonical(query)
        return org.canonical_id if org else None

    def to_kegg_org(self, query: str) -> Optional[str]:
        """Return the KEGG organism code (``"eco"``, ``"sce"``, ...) or None."""
        org = self.resolve_canonical(query)
        return org.kegg_org if org else None

    # ---------- internals ----------
    def _candidate_for(self, chassis_key: str, match: MatchType,
                       *, query: str) -> EntityCandidate:
        org = self._build_organism(chassis_key, match)
        return EntityCandidate(
            entity=org,
            kind=EntityKind.ORGANISM,
            tier=_tier_for_match_type(match),
            confidence=_confidence_for_match_type(match),
            provenance=self.name,
            query=query,
        )

    def _build_organism(self, chassis_key: str, match: MatchType) -> Organism:
        chassis = self._chassis_map.get(chassis_key, {})
        aliases = self._aliases.get(chassis_key, {})

        common_names = tuple(aliases.get("common_names") or ())
        strain_aliases = tuple(aliases.get("strain_aliases") or ())

        # Aliases field: user-facing, deduped.
        all_aliases: list[str] = []
        for a in (chassis_key, *common_names, *strain_aliases):
            if a and a not in all_aliases:
                all_aliases.append(a)

        cross_refs: list[tuple[str, str]] = []
        if chassis.get("kegg_org"):
            cross_refs.append(("kegg", chassis["kegg_org"]))
        if aliases.get("taxonomy_id"):
            cross_refs.append(("ncbi_taxonomy", aliases["taxonomy_id"]))

        return Organism(
            canonical_id=chassis_key,
            source="chassis_db",
            scientific_name=chassis.get("name"),
            species=aliases.get("species"),
            strain=aliases.get("strain"),
            common_name=common_names[0] if common_names else None,
            aliases=tuple(all_aliases),
            kegg_org=chassis.get("kegg_org"),
            taxonomy_id=aliases.get("taxonomy_id"),
            native_pathways=tuple(chassis.get("native_pathways") or ()),
            genetic_tools=chassis.get("genetic_tools"),
            growth_rate=chassis.get("growth_rate"),
            match_type=match,
            cross_refs=tuple(cross_refs),
        )

    def _kegg_org_to_key(self, kegg_code: str) -> Optional[str]:
        for key, chassis in self._chassis_map.items():
            if (chassis.get("kegg_org") or "").lower() == kegg_code:
                return key
        return None


# ---------- MatchType → ResolutionTier / confidence ----------
def _tier_for_match_type(match: MatchType) -> ResolutionTier:
    if match in (MatchType.EXACT_STRAIN, MatchType.EXACT_SPECIES):
        return ResolutionTier.EXACT
    if match is MatchType.CHASSIS_GENERALIZED:
        return ResolutionTier.APPROXIMATE
    return ResolutionTier.INFERRED


def _confidence_for_match_type(match: MatchType) -> float:
    return {
        MatchType.EXACT_STRAIN: 0.95,
        MatchType.EXACT_SPECIES: 0.85,
        MatchType.CHASSIS_GENERALIZED: 0.70,
        MatchType.INFERRED: 0.40,
    }[match]


# ---------- default instance factory ----------
def default_organism_resolver() -> OrganismResolver:
    """Return a resolver backed by ``config.CHASSIS_ORGANISMS``.

    Use this from downstream tools that want organism resolution without
    constructing a resolver themselves. Safe to call multiple times — the
    object is cheap to build (no network, no file I/O).
    """
    return OrganismResolver()
