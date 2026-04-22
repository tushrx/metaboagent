"""
Hybrid dispatcher — compose multiple resolvers/retrievers behind one surface.

Responsibilities (codex_rag_design.md §hybrid retrieval):

- Fan out a query across every registered ``EntityResolver`` whose
  ``supported_kinds`` includes the requested kind. Collect candidates.
- Tier-order results: EXACT first, APPROXIMATE next, INFERRED last. Within a
  tier, sort by ``confidence`` (descending) then stable-sort by provenance so
  the same query produces the same ordering across runs.
- Dedupe by ``(canonical_id, source)`` — if two resolvers return the same
  entity, keep the better-tier/higher-confidence one.
- Same shape for ``StructuredRetriever`` evidence, except we dedupe by
  ``(source, doc_id)``.

What this is *not*:
- A query planner (that's Phase 5+).
- A ranker that mixes recency / citation count / impact score. For Phase 4,
  "best tier, best confidence" is enough scaffolding.
- A concrete resolver. Anyone passing a Protocol-compatible object to
  ``register_resolver()`` gets plugged in — Phase 5's molecule resolver slots
  right here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from agent.entities import (
    EntityCandidate,
    EntityKind,
    EntityResolver,
    Evidence,
    StructuredRetriever,
)

log = logging.getLogger(__name__)


@dataclass
class HybridRetriever:
    """Composes resolvers + retrievers behind a unified query API."""

    resolvers: list[EntityResolver] = field(default_factory=list)
    retrievers: list[StructuredRetriever] = field(default_factory=list)

    # ---------- registration ----------
    def register_resolver(self, resolver: EntityResolver) -> None:
        if resolver not in self.resolvers:
            self.resolvers.append(resolver)

    def register_retriever(self, retriever: StructuredRetriever) -> None:
        if retriever not in self.retrievers:
            self.retrievers.append(retriever)

    # ---------- resolve ----------
    def resolve(
        self,
        query: str,
        kind: EntityKind,
        *,
        limit: int = 5,
        resolvers: Optional[Iterable[EntityResolver]] = None,
    ) -> list[EntityCandidate]:
        """Return up to ``limit`` deduped, tier-ordered candidates.

        ``resolvers`` overrides the registered set for a single call. Useful
        for tests and for callers that want to skip expensive live lookups.
        """
        q = (query or "").strip()
        if not q:
            return []

        active = list(resolvers) if resolvers is not None else list(self.resolvers)
        gathered: list[EntityCandidate] = []
        for r in active:
            if kind not in getattr(r, "supported_kinds", ()):
                continue
            try:
                gathered.extend(r.resolve(q, kind, limit=limit))
            except Exception as e:  # noqa: BLE001
                log.warning("rag.hybrid: %s.resolve(%r) raised %s",
                            getattr(r, "name", r), q, e)

        return _dedupe_and_sort_candidates(gathered)[:limit]

    # ---------- retrieve ----------
    def retrieve(
        self,
        query: str,
        *,
        kind: Optional[EntityKind] = None,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = 5,
        retrievers: Optional[Iterable[StructuredRetriever]] = None,
    ) -> list[Evidence]:
        """Return up to ``top_k`` deduped Evidence hits across retrievers."""
        q = (query or "").strip()
        if not q:
            return []

        active = list(retrievers) if retrievers is not None else list(self.retrievers)
        gathered: list[Evidence] = []
        for r in active:
            if kind is not None and kind not in getattr(r, "supported_kinds", ()):
                continue
            try:
                gathered.extend(r.retrieve(q, kind=kind, filters=filters, top_k=top_k))
            except Exception as e:  # noqa: BLE001
                log.warning("rag.hybrid: %s.retrieve(%r) raised %s",
                            getattr(r, "name", r), q, e)

        return _dedupe_and_sort_evidence(gathered)[:top_k]


# ---------- helpers ----------
def _candidate_key(c: EntityCandidate) -> tuple[str, str]:
    e = c.entity
    source = getattr(e, "source", "") or ""
    cid = (
        getattr(e, "canonical_id", None)
        or getattr(e, "reaction_id", None)
        or getattr(e, "uniprot_accession", None)
        or getattr(e, "ec_number", None)
        or getattr(e, "pmid", None)
        or ""
    )
    return (source, str(cid))


def _dedupe_and_sort_candidates(cands: list[EntityCandidate]) -> list[EntityCandidate]:
    """Best-tier + highest-confidence wins on duplicate (source, id)."""
    best: dict[tuple[str, str], EntityCandidate] = {}
    for c in cands:
        key = _candidate_key(c)
        if not key[1]:
            # No canonical id — keep as a unique item keyed by id(c) so it
            # survives dedup but doesn't collide.
            best[(key[0], f"_anon_{id(c)}")] = c
            continue
        existing = best.get(key)
        if existing is None or _candidate_rank(c) < _candidate_rank(existing):
            best[key] = c
    return sorted(best.values(), key=_candidate_rank)


def _candidate_rank(c: EntityCandidate) -> tuple[int, float, str]:
    """Sort key: lower is better. (tier_rank, -confidence, provenance)."""
    return (c.tier.rank(), -float(c.confidence), c.provenance)


def _evidence_key(e: Evidence) -> tuple[str, str]:
    return (e.source or "", e.doc_id or "")


def _dedupe_and_sort_evidence(items: list[Evidence]) -> list[Evidence]:
    best: dict[tuple[str, str], Evidence] = {}
    for ev in items:
        key = _evidence_key(ev)
        if not key[1]:
            best[(key[0], f"_anon_{id(ev)}")] = ev
            continue
        existing = best.get(key)
        if existing is None or ev.score > existing.score:
            best[key] = ev
    return sorted(best.values(), key=lambda e: -float(e.score))


# ---------- factory ----------
def default_hybrid_retriever() -> HybridRetriever:
    """Build a HybridRetriever wired with the Phase 4 thin adapters.

    Callers that want a working end-to-end RAG layer on Day 1's data can call
    this once and share the instance. Phase 5/6 will add more resolvers
    (molecule, organism, graph, …) to the same object.
    """
    from vectorstore.adapters import (
        KeggIndexedResolver,
        KeggIndexedRetriever,
        KeggLiveResolver,
        LiteratureRetriever,
        PubChemResolver,
        UniProtResolver,
    )

    hr = HybridRetriever()
    hr.register_resolver(KeggLiveResolver())
    hr.register_resolver(KeggIndexedResolver())
    hr.register_resolver(PubChemResolver())
    hr.register_resolver(UniProtResolver())
    hr.register_retriever(KeggIndexedRetriever())
    hr.register_retriever(LiteratureRetriever())
    return hr
