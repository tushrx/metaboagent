"""
Phase 9 — citation verification.

Verifies that cited IDs (PMIDs, KEGG reaction/compound IDs, EC numbers)
appearing in a final agent answer actually exist in the indexed corpus.

Design goals (codex_plan.md §9, small module, not a full engine):

- Pure post-processing: takes a finished answer string, returns a
  machine-readable ``list[Citation]``. No agent-loop coupling.
- Cheap verification: uses ``collection.get(ids=[...])`` against ChromaDB
  directly (no embedding, no semantic search). An EC number additionally
  falls back to a substring scan on the ``ec_numbers`` metadata field of
  the ``kegg_reactions`` collection when the enzyme row is missing.
- Injectable lookups: each citation type has a ``Callable[[str], bool]``
  existence check that tests can override without touching ChromaDB.
- Honest statuses:
    * ``VERIFIED``   — looked up and the ID was found.
    * ``UNRESOLVED`` — looked up and the ID was NOT found (likely
      hallucinated, or outside the current corpus).
    * ``INFERRED``   — the citation shape is known (e.g., an EC number
      like ``1.1.1.1``) but no lookup backend is configured for that type.
      Callers should treat it as "plausible but unchecked".

ID shapes and matching:
- PMID: 6–9 digit integer, indexed under ``pubmed:{PMID}`` in the
  ``literature`` collection.
- KEGG reaction: ``R\\d{5}`` → ``kegg_rxn:R#####`` in ``kegg_reactions``.
- KEGG compound: ``C\\d{5}`` → ``kegg_cpd:C#####`` in ``kegg_compounds``.
- EC number: ``d+.d+.d+.d+`` → ``kegg_enzyme:{EC}`` in ``literature``. If
  missing (sub-sub-class heterogeneity / incomplete KEGG snapshot), a
  secondary check scans ``ec_numbers`` metadata across ``kegg_reactions``.

The module is the only Phase-9 behavioral surface. Consumers like
``ui/app.py`` reuse its extraction regexes and ``verify_text()`` to
annotate citation chips; the agent itself is untouched.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger(__name__)


# ---------- enums ----------
class CitationStatus(str, Enum):
    VERIFIED = "verified"
    UNRESOLVED = "unresolved"
    INFERRED = "inferred"


class CitationType(str, Enum):
    PMID = "pmid"
    KEGG_REACTION = "kegg_reaction"
    KEGG_COMPOUND = "kegg_compound"
    EC_NUMBER = "ec_number"


# ---------- extraction regexes ----------
# NOTE: mirror (and are intentionally compatible with) the patterns in
# ui/app.py so that inline chip rendering and verification share ground truth.
_PMID_RE = re.compile(r"\b(?:PMID[:\s]*)(\d{6,9})\b", re.IGNORECASE)
_KEGG_RXN_RE = re.compile(r"\bR\d{5}\b")
_KEGG_CPD_RE = re.compile(r"\bC\d{5}\b")
_EC_RE = re.compile(r"\b(?:EC\s*)?(\d+\.\d+\.\d+\.\d+)\b")


# ---------- data class ----------
@dataclass(frozen=True)
class Citation:
    """A single citation found in an answer, plus its verification state.

    ``value`` is the canonical form (EC numbers stripped of ``"EC "``
    prefix; PMIDs as plain digits; KEGG IDs uppercased).
    ``source`` records *where* the verifier found the match (e.g.
    ``"kegg_reactions"``, ``"literature"``, ``"ec_numbers.metadata"``), or
    is empty for UNRESOLVED / INFERRED entries.
    """

    cite_type: CitationType
    value: str
    status: CitationStatus
    source: str = ""
    note: str = ""

    # Stable machine-readable representation.
    def as_dict(self) -> dict:
        d = asdict(self)
        d["cite_type"] = self.cite_type.value
        d["status"] = self.status.value
        return d


# ---------- extraction ----------
def extract_citations(text: str) -> list[Citation]:
    """Regex-extract every citation-shaped token from ``text``.

    Returns ``Citation`` rows with ``status=INFERRED`` (no lookup yet).
    De-duplicated per (cite_type, value); order is stable: PMID, KEGG
    reaction, KEGG compound, EC number, each block sorted lexically.
    """
    if not text:
        return []

    found: dict[tuple[CitationType, str], Citation] = {}

    for pmid in _PMID_RE.findall(text):
        key = (CitationType.PMID, pmid)
        found.setdefault(key, Citation(
            cite_type=CitationType.PMID, value=pmid,
            status=CitationStatus.INFERRED,
        ))
    for rid in _KEGG_RXN_RE.findall(text):
        rid_u = rid.upper()
        key = (CitationType.KEGG_REACTION, rid_u)
        found.setdefault(key, Citation(
            cite_type=CitationType.KEGG_REACTION, value=rid_u,
            status=CitationStatus.INFERRED,
        ))
    for cid in _KEGG_CPD_RE.findall(text):
        cid_u = cid.upper()
        key = (CitationType.KEGG_COMPOUND, cid_u)
        found.setdefault(key, Citation(
            cite_type=CitationType.KEGG_COMPOUND, value=cid_u,
            status=CitationStatus.INFERRED,
        ))
    for ec in _EC_RE.findall(text):
        key = (CitationType.EC_NUMBER, ec)
        found.setdefault(key, Citation(
            cite_type=CitationType.EC_NUMBER, value=ec,
            status=CitationStatus.INFERRED,
        ))

    # Ordered output: PMID → KEGG_REACTION → KEGG_COMPOUND → EC_NUMBER,
    # values sorted inside each bucket for deterministic tests.
    order = [
        CitationType.PMID,
        CitationType.KEGG_REACTION,
        CitationType.KEGG_COMPOUND,
        CitationType.EC_NUMBER,
    ]
    out: list[Citation] = []
    for kind in order:
        hits = [c for (t, _), c in found.items() if t is kind]
        out.extend(sorted(hits, key=lambda c: c.value))
    return out


# ---------- verifier ----------
# A lookup returns (found: bool, source_label: str). ``source_label`` is
# used only when found==True; it is embedded in the Citation.source field.
Lookup = Callable[[str], tuple[bool, str]]


class CitationVerifier:
    """Verifies citation tokens against pluggable existence backends.

    Each citation type has its own ``Lookup``. If a lookup is absent for a
    given type, that type's citations are marked ``INFERRED`` (plausible
    shape, not checked). This makes it trivial to run the verifier with a
    subset of backends — e.g. tests inject only a PMID lookup, or the UI
    runs with everything disabled but the regex shape check.

    Callers:
    - ``verify(citations)`` — use pre-extracted citations (typical when you
      already called ``extract_citations`` for UI rendering).
    - ``verify_text(text)`` — extract + verify in one shot.
    """

    def __init__(
        self,
        *,
        pmid_lookup: Optional[Lookup] = None,
        reaction_lookup: Optional[Lookup] = None,
        compound_lookup: Optional[Lookup] = None,
        ec_lookup: Optional[Lookup] = None,
    ) -> None:
        self._lookups: dict[CitationType, Optional[Lookup]] = {
            CitationType.PMID: pmid_lookup,
            CitationType.KEGG_REACTION: reaction_lookup,
            CitationType.KEGG_COMPOUND: compound_lookup,
            CitationType.EC_NUMBER: ec_lookup,
        }

    def verify(self, citations: Iterable[Citation]) -> list[Citation]:
        out: list[Citation] = []
        for c in citations:
            out.append(self._verify_one(c))
        return out

    def verify_text(self, text: str) -> list[Citation]:
        return self.verify(extract_citations(text))

    def _verify_one(self, c: Citation) -> Citation:
        lookup = self._lookups.get(c.cite_type)
        if lookup is None:
            # No backend → best we can say is "shape looks right".
            return Citation(
                cite_type=c.cite_type, value=c.value,
                status=CitationStatus.INFERRED,
                source="", note="no lookup backend configured",
            )
        try:
            found, source = lookup(c.value)
        except Exception as exc:  # noqa: BLE001
            log.warning("Citation lookup failed for %s %s: %s",
                        c.cite_type.value, c.value, exc)
            return Citation(
                cite_type=c.cite_type, value=c.value,
                status=CitationStatus.UNRESOLVED,
                source="", note=f"lookup error: {exc}",
            )
        if found:
            return Citation(
                cite_type=c.cite_type, value=c.value,
                status=CitationStatus.VERIFIED,
                source=source, note="",
            )
        return Citation(
            cite_type=c.cite_type, value=c.value,
            status=CitationStatus.UNRESOLVED,
            source="", note="id not found in indexed corpus",
        )


# ---------- default Chroma-backed lookups ----------
def _chroma_id_probe(coll, namespaced_id: str) -> bool:
    """Check whether a namespaced id exists in a ChromaDB collection.

    ``coll.get(ids=[id])`` is ``O(1)`` and returns an empty result set
    when the id is unknown, so we don't need any embedding work.
    """
    try:
        res = coll.get(ids=[namespaced_id])
    except Exception as exc:  # noqa: BLE001
        log.warning("Chroma .get failed on %s: %s", namespaced_id, exc)
        return False
    ids = res.get("ids") if isinstance(res, dict) else None
    return bool(ids)


def _build_ec_index(coll) -> frozenset[str]:
    """Load every distinct EC token from ``kegg_reactions.ec_numbers``.

    The ``ec_numbers`` metadata is comma-joined (vectorstore.indexer
    ``_flatten_metadata``), and Chroma ``where`` can't substring-match
    list-valued fields. We pull all reaction rows once and scan client-
    side; subsequent EC lookups are O(1) against the resulting set.
    """
    try:
        res = coll.get(where={"type": "reaction"}, limit=5000,
                       include=["metadatas"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Chroma ec-fallback .get failed: %s", exc)
        return frozenset()
    metas = res.get("metadatas") or [] if isinstance(res, dict) else []
    tokens: set[str] = set()
    for m in metas:
        raw = (m or {}).get("ec_numbers", "")
        if not isinstance(raw, str):
            raw = str(raw)
        for t in raw.split(","):
            t = t.strip()
            if t:
                tokens.add(t)
    return frozenset(tokens)


def default_chroma_verifier() -> CitationVerifier:
    """Build a verifier backed by the live ChromaDB collections.

    Safe to call even before the collections are populated — each lookup
    returns ``(False, "")`` on empty/missing collections.
    """
    # Local import to avoid pulling chroma at module import time (tests
    # shouldn't need it).
    from config import (
        COLLECTION_COMPOUNDS,
        COLLECTION_LITERATURE,
        COLLECTION_REACTIONS,
    )
    from vectorstore.chroma_setup import get_client, get_or_create_collection

    client = get_client()
    rxn_coll = get_or_create_collection(client, COLLECTION_REACTIONS)
    cpd_coll = get_or_create_collection(client, COLLECTION_COMPOUNDS)
    lit_coll = get_or_create_collection(client, COLLECTION_LITERATURE)

    def pmid_lookup(pmid: str) -> tuple[bool, str]:
        return (_chroma_id_probe(lit_coll, f"pubmed:{pmid}"),
                "literature")

    def reaction_lookup(rid: str) -> tuple[bool, str]:
        return (_chroma_id_probe(rxn_coll, f"kegg_rxn:{rid}"),
                "kegg_reactions")

    def compound_lookup(cid: str) -> tuple[bool, str]:
        return (_chroma_id_probe(cpd_coll, f"kegg_cpd:{cid}"),
                "kegg_compounds")

    # Build the EC-fallback index once at verifier construction. Previous
    # behaviour rescanned ~5000 reaction metadatas per EC citation, i.e.
    # O(N × rows) per answer. We now pay that cost once and reuse it.
    _ec_index_cache: dict[str, frozenset[str]] = {}

    def _ec_index() -> frozenset[str]:
        idx = _ec_index_cache.get("reactions")
        if idx is None:
            idx = _build_ec_index(rxn_coll)
            _ec_index_cache["reactions"] = idx
        return idx

    def ec_lookup(ec: str) -> tuple[bool, str]:
        # Primary: direct enzyme row in the literature collection.
        if _chroma_id_probe(lit_coll, f"kegg_enzyme:{ec}"):
            return True, "literature"
        # Fallback: cached EC token set scanned once per verifier.
        if ec.strip() in _ec_index():
            return True, "ec_numbers.metadata"
        return False, ""

    return CitationVerifier(
        pmid_lookup=pmid_lookup,
        reaction_lookup=reaction_lookup,
        compound_lookup=compound_lookup,
        ec_lookup=ec_lookup,
    )


# ---------- convenience aggregation ----------
@dataclass
class CitationReport:
    """Summary of a verified citation set — handy for UI badges."""
    citations: list[Citation] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in CitationStatus}
        for c in self.citations:
            out[c.status.value] += 1
        return out

    def by_type(self, kind: CitationType) -> list[Citation]:
        return [c for c in self.citations if c.cite_type is kind]

    def as_dict(self) -> dict:
        return {
            "counts": self.counts,
            "citations": [c.as_dict() for c in self.citations],
        }


def build_report(text: str, verifier: CitationVerifier) -> CitationReport:
    return CitationReport(citations=verifier.verify_text(text))


__all__ = [
    "Citation",
    "CitationReport",
    "CitationStatus",
    "CitationType",
    "CitationVerifier",
    "build_report",
    "default_chroma_verifier",
    "extract_citations",
]
