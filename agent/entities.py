"""
Typed entity contracts for MetaboAgent.

Everything in this file is a *shape*, not an implementation. Concrete
resolvers live in ``agent.resolvers`` (molecule, organism); retrieval
adapters live in ``vectorstore.adapters`` and ``vectorstore.hybrid``.

Pydantic output schemas for the agent's final blueprint live in
``agent.schemas`` — keep them separate. This module is the retrieval-layer
type vocabulary used by tools and resolvers to pass structured candidates
around without going through JSON.

Why dataclasses + Protocols instead of a framework?
- Callers can construct entities directly in tests or scripts with zero setup.
- ``Protocol`` lets new resolvers ship without inheriting from a shared base —
  duck typing, checked by mypy if anyone cares.
- JSON-returning @tool functions remain the agent-facing surface; these types
  are what the *internal* code passes around.

Design notes:
- Every candidate carries a ``tier`` (EXACT/APPROXIMATE/INFERRED) — separating
  "KEGG told me so" from "the embedding model thinks these are similar".
- Every Evidence hit carries its ``source`` and the raw ``score`` from the
  retriever. Composite ranking lives in ``vectorstore.hybrid``; the type
  layer stays agnostic so new retrievers plug in without changes here.
- Entity dataclasses capture the union of fields we can currently surface
  from KEGG / UniProt / PubChem / PubMed. Any field we don't know is ``None``
  or empty — we never fabricate values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, Union, runtime_checkable


# ---------- enums ----------
class ResolutionTier(str, Enum):
    """How certain the resolver is that this candidate matches the query.

    The ordering is meaningful: EXACT < APPROXIMATE < INFERRED when sorted
    alphabetically, so we keep a ``rank()`` helper for callers that want
    tier-first ordering (lowest rank = best).
    """
    EXACT = "exact"               # canonical-id or accession match
    APPROXIMATE = "approximate"   # fuzzy/synonym match, still human-reviewable
    INFERRED = "inferred"         # semantic-similarity only, lowest trust

    def rank(self) -> int:
        return _TIER_RANK[self]


_TIER_RANK = {
    ResolutionTier.EXACT: 0,
    ResolutionTier.APPROXIMATE: 1,
    ResolutionTier.INFERRED: 2,
}


class EntityKind(str, Enum):
    """Scientific entity kinds the resolver layer currently supports.

    Organism is present as a marker so Phase 6 can drop in a chassis/organism
    resolver without breaking callers. Other future kinds (Pathway, Gene,
    Construct, Rule) can be appended.
    """
    MOLECULE = "molecule"
    ENZYME = "enzyme"
    REACTION = "reaction"
    PAPER = "paper"
    ORGANISM = "organism"


# ---------- typed entities ----------
@dataclass(frozen=True)
class Molecule:
    """A chemical compound identified by a canonical source+id pair.

    ``canonical_id`` is the string the *issuing source* uses (KEGG "C05432",
    PubChem "CID:446925", ChEBI "CHEBI:15756"). We preserve the source prefix
    so merge logic in Phase 5 can decide how to unify across catalogs.

    ``cross_refs`` carries known identifier mappings to *other* databases, as
    a tuple of ``(db, id)`` pairs — immutable so ``Molecule`` stays hashable.
    Use :meth:`cross_refs_dict` for convenient dict access. This is how the
    molecule resolver stitches "KEGG C05432" and "PubChem CID:446925" into a
    single canonical record.
    """
    canonical_id: str
    source: str                               # "kegg" | "pubchem" | "chebi" | ...
    name: Optional[str] = None
    synonyms: tuple[str, ...] = ()
    formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    smiles: Optional[str] = None
    inchi: Optional[str] = None
    inchikey: Optional[str] = None
    url: Optional[str] = None
    cross_refs: tuple[tuple[str, str], ...] = ()
    extras: dict = field(default_factory=dict, compare=False)

    def cross_refs_dict(self) -> dict[str, str]:
        """Flat ``{db: id}`` view of :attr:`cross_refs`. Later keys win."""
        return dict(self.cross_refs)


@dataclass(frozen=True)
class Enzyme:
    """An enzyme (EC-classified activity) and — optionally — a specific
    protein realizing it.

    Splitting EC from UniProt accession is deliberate: the same EC can be
    realized by many proteins, and a protein may cover several EC numbers.
    Use ``ec_number`` when you want the catalytic activity, ``uniprot_accession``
    when you want the concrete sequence/annotation.
    """
    ec_number: Optional[str] = None
    recommended_name: Optional[str] = None
    uniprot_accession: Optional[str] = None
    gene_names: tuple[str, ...] = ()
    organism: Optional[str] = None
    sequence_length: Optional[int] = None
    source: str = ""
    url: Optional[str] = None
    extras: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Reaction:
    """A biochemical reaction — KEGG-style by default."""
    reaction_id: str                            # e.g. "R02003"
    source: str = "kegg"
    equation: Optional[str] = None
    ec_numbers: tuple[str, ...] = ()
    substrates: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    pathway_ids: tuple[str, ...] = ()
    url: Optional[str] = None
    extras: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Paper:
    """A literature reference. PMID is the primary key when available."""
    pmid: Optional[str] = None
    doi: Optional[str] = None
    title: Optional[str] = None
    year: Optional[str] = None
    journal: Optional[str] = None
    mesh_terms: tuple[str, ...] = ()
    snippet: Optional[str] = None
    source: str = "pubmed"
    url: Optional[str] = None
    extras: dict = field(default_factory=dict, compare=False)


class MatchType(str, Enum):
    """How specifically a query resolved to an :class:`Organism`.

    Distinct from :class:`ResolutionTier` (which is resolver-agnostic) because
    organism resolution has domain-specific fallback semantics (strain →
    species → chassis). Downstream tools can log both: e.g. *"resolved with
    match_type=exact_species, tier=exact"* means we nailed the species but
    the caller asked at species-level, not strain-level.
    """
    EXACT_STRAIN = "exact_strain"
    EXACT_SPECIES = "exact_species"
    CHASSIS_GENERALIZED = "chassis_generalized"
    INFERRED = "inferred"


@dataclass(frozen=True)
class Organism:
    """A microbial organism — strain, species, or generalized chassis.

    Designed to be a superset of the legacy ``CHASSIS_ORGANISMS`` record
    structure. For the five Day-1 chassis, fields map to the existing dict
    values verbatim:

    - ``canonical_id`` ← chassis key (``"ecoli"``)
    - ``scientific_name`` ← ``CHASSIS_ORGANISMS[k]["name"]``
    - ``kegg_org`` ← ``CHASSIS_ORGANISMS[k]["kegg_org"]``
    - ``native_pathways`` ← ``CHASSIS_ORGANISMS[k]["native_pathways"]``
    - ``genetic_tools`` / ``growth_rate`` ← same

    Carries :attr:`match_type` so tools that want to warn the user "we
    fell back to E. coli because you typed 'bacteria'" can do so without
    recomputing resolver state.
    """
    canonical_id: str
    source: str = "chassis_db"          # "chassis_db" | "ncbi_taxonomy" | ...

    # Names (denormalized so tools can fetch any form without joins)
    scientific_name: Optional[str] = None      # "Escherichia coli K-12 MG1655"
    species: Optional[str] = None              # "Escherichia coli"
    strain: Optional[str] = None               # "K-12 MG1655"
    common_name: Optional[str] = None          # "E. coli"
    aliases: tuple[str, ...] = ()              # user-facing aliases

    # External identifiers
    kegg_org: Optional[str] = None             # e.g. "eco"
    taxonomy_id: Optional[str] = None          # NCBI taxonomy id, string form

    # Chassis metadata (only populated for known chassis records)
    native_pathways: tuple[str, ...] = ()
    genetic_tools: Optional[str] = None
    growth_rate: Optional[str] = None

    # Resolution metadata
    match_type: MatchType = MatchType.INFERRED

    # Future-proofing
    cross_refs: tuple[tuple[str, str], ...] = ()
    url: Optional[str] = None
    extras: dict = field(default_factory=dict, compare=False)

    def cross_refs_dict(self) -> dict[str, str]:
        return dict(self.cross_refs)

    def as_chassis_dict(self) -> dict:
        """Legacy view — compatible with ``config.CHASSIS_ORGANISMS[key]``.

        Returned keys match the historical dict shape (``name``,
        ``kegg_org``, ``native_pathways``, ``genetic_tools``, ``growth_rate``)
        so tools migrating from the raw dict can drop this in:

            # old:
            meta = CHASSIS_ORGANISMS[host_key]
            # new (via resolver):
            meta = organism.as_chassis_dict()
        """
        return {
            "name": self.scientific_name,
            "kegg_org": self.kegg_org,
            "native_pathways": list(self.native_pathways),
            "genetic_tools": self.genetic_tools,
            "growth_rate": self.growth_rate,
        }


# Union of entity types; keep this in sync with ``EntityKind``.
Entity = Union[Molecule, Enzyme, Reaction, Paper, Organism]


# ---------- candidate + evidence ----------
@dataclass(frozen=True)
class EntityCandidate:
    """Output of an ``EntityResolver.resolve()`` call.

    Wraps one entity with the tier the resolver assigned and a 0-1 confidence
    (what the resolver believes, not a cross-resolver normalized score). The
    ``provenance`` field names the resolver that produced the candidate so
    HybridRetriever can dedupe and log.
    """
    entity: Entity
    kind: EntityKind
    tier: ResolutionTier
    confidence: float                           # 0.0 – 1.0
    provenance: str                             # resolver identifier
    query: Optional[str] = None                 # the input string, for audit
    extras: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Evidence:
    """A single retrieved piece of supporting context.

    ``subject`` is the typed entity the evidence is *about* when the retriever
    can infer one (e.g., a UniProt hit knows the enzyme). When the retriever
    returns free-form text (PubMed abstracts, pathway descriptions),
    ``subject`` stays None and the caller relies on ``text`` + ``metadata``.
    """
    text: str
    score: float                                # retriever-native score
    source: str                                 # "kegg_reactions" | "pubmed" | ...
    doc_id: str = ""
    subject: Optional[Entity] = None
    metadata: dict = field(default_factory=dict, compare=False)


# ---------- Protocols ----------
@runtime_checkable
class EntityResolver(Protocol):
    """Contract for "given a user string, return candidate entities".

    Implementations must:
    - Be safe to call from any thread (no shared mutable state).
    - Never raise on a normal empty result — return ``[]`` with an explanatory
      log line if helpful.
    - Never block indefinitely — defer to the underlying transport's timeout.
    - Tag every candidate with a ``provenance`` equal to ``self.name``.
    """

    name: str                                   # short stable identifier
    supported_kinds: tuple[EntityKind, ...]     # which EntityKinds resolve()

    def resolve(
        self,
        query: str,
        kind: EntityKind,
        *,
        limit: int = 5,
    ) -> list[EntityCandidate]:
        """Return up to ``limit`` candidate matches for ``query``.

        If ``kind`` is not in ``supported_kinds``, implementations should
        return ``[]`` rather than raise — HybridRetriever treats that as
        "this resolver has nothing to say" and moves on.
        """
        ...


@runtime_checkable
class StructuredRetriever(Protocol):
    """Contract for "given a query (+optional typed anchor), return Evidence".

    Distinct from EntityResolver: retrievers return *context*, not *identity*.
    The same retriever may be fed either a free-form query string or a
    resolved entity (e.g., "give me all literature about UniProt P12345").
    """

    name: str
    supported_kinds: tuple[EntityKind, ...]

    def retrieve(
        self,
        query: str,
        *,
        kind: Optional[EntityKind] = None,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = 5,
    ) -> list[Evidence]:
        ...
