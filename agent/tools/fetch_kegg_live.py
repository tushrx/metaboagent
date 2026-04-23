"""
@tool fetch_kegg_live — direct KEGG REST lookup for any entity on demand.

The indexed collections cover reactions/compounds/enzymes/pathways at
ingestion time. This tool is for *any* KEGG entity (including newer ones or
organism-specific entries not in our snapshot). It auto-indexes results.

Supported entity id prefixes:
    rn:RNNNNN / RNNNNN           → reaction
    cpd:CNNNNN / CNNNNN          → compound
    ec:N.N.N.N / N.N.N.N / EC N…  → enzyme
    path:mapNNNNN / mapNNNNN     → reference pathway
    <org>NNNNN (e.g. eco00010)   → organism-specific pathway
"""
from __future__ import annotations

import json
import logging
import re

from langchain_core.tools import tool

from agent.tools._http import get_text, make_session
from config import COLLECTION_COMPOUNDS, COLLECTION_LITERATURE, COLLECTION_REACTIONS
from data.ingestion.kegg_parser import parse_entry
from vectorstore.live_indexer import VectorDocument, index_documents

log = logging.getLogger(__name__)

_BASE = "https://rest.kegg.jp/get"
_session = make_session(extra_headers={"Accept": "text/plain,*/*"})

# Entity-kind detection.
_PREFIX_COMPOUND = re.compile(r"^(?:cpd:)?C\d{5}$")
_PREFIX_REACTION = re.compile(r"^(?:rn:)?R\d{5}$")
_PREFIX_ENZYME = re.compile(r"^(?:ec:)?(?:EC\s*)?\d+\.\d+\.\d+\.\d+$", re.IGNORECASE)
_PREFIX_PATHWAY = re.compile(r"^(?:path:)?(?:map|[a-z]{2,4})\d{5}$")


def _classify(entity_id: str) -> tuple[str, str, str]:
    """Return (kind, canonical_id_for_kegg_get, collection_name)."""
    q = entity_id.strip()
    if _PREFIX_COMPOUND.match(q):
        raw = q.split(":")[-1]
        return "compound", f"cpd:{raw}", COLLECTION_COMPOUNDS
    if _PREFIX_REACTION.match(q):
        raw = q.split(":")[-1]
        return "reaction", f"rn:{raw}", COLLECTION_REACTIONS
    if _PREFIX_ENZYME.match(q):
        # Strip optional "EC " or "ec:" and keep the dot-number.
        ec = re.sub(r"(?i)^(ec:|EC\s*)", "", q)
        return "enzyme", f"ec:{ec}", COLLECTION_LITERATURE
    if _PREFIX_PATHWAY.match(q):
        raw = q.split(":")[-1]
        return "pathway", f"path:{raw}", COLLECTION_LITERATURE
    # Unknown — try as-is.
    return "unknown", q, COLLECTION_LITERATURE


@tool(parse_docstring=True)
def fetch_kegg_live(entity_id: str) -> str:
    """Fetch any KEGG entity (reaction, compound, enzyme, pathway) on demand.

    Args:
        entity_id: KEGG ID. Accepted forms include reactions like "R00024" or "rn:R00024", compounds like "C05432" or "cpd:C05432", enzymes like "1.3.99.31" or "EC 1.3.99.31" or "ec:1.3.99.31", reference pathways like "map00900" or "path:map00900", and organism-specific pathways like "eco00010".

    Returns:
        JSON string with the canonical id, detected kind, parsed sections
        (name, formula/equation, pathway links, etc.), and the raw KEGG URL.
        The parsed document is auto-indexed into the matching collection.
    """
    q = (entity_id or "").strip()
    if not q:
        return json.dumps({"error": "empty id"})
    kind, canonical, collection = _classify(q)

    text = get_text(_session, f"{_BASE}/{canonical}")
    if not text:
        return json.dumps({"query": q, "kind": kind, "note": "no KEGG entry"})

    sections = parse_entry(text)
    # Normalize: emit a compact summary.
    summary = {
        "query": q,
        "kind": kind,
        "kegg_id": canonical,
        "name": " ; ".join(sections.get("NAME", []))[:300] or None,
        "url": f"https://www.kegg.jp/entry/{canonical}",
    }
    if kind == "reaction":
        summary["equation"] = " ".join(sections.get("EQUATION", []))
        summary["enzymes"] = " ".join(sections.get("ENZYME", []))
        summary["pathways"] = " ".join(sections.get("PATHWAY", []))[:600]
    elif kind == "compound":
        summary["formula"] = " ".join(sections.get("FORMULA", []))
        summary["exact_mass"] = " ".join(sections.get("EXACT_MASS", []))
        summary["pathways"] = " ".join(sections.get("PATHWAY", []))[:600]
    elif kind == "enzyme":
        summary["sysname"] = " ".join(sections.get("SYSNAME", []))
        summary["reaction"] = " ".join(sections.get("REACTION", []))[:600]
        summary["organisms"] = " ".join(sections.get("ORGANISM", []))[:600]
    elif kind == "pathway":
        summary["description"] = " ".join(sections.get("DESCRIPTION", []))[:800]
        summary["classes"] = " ".join(sections.get("CLASS", []))
    # Attach raw section count for debugging.
    summary["section_count"] = len(sections)

    # Build embedding text.
    doc_lines = [f"KEGG {kind} {canonical}: {summary.get('name') or q}"]
    for k, v in summary.items():
        if k in {"query", "kind", "kegg_id", "name", "url", "section_count"} or not v:
            continue
        doc_lines.append(f"{k}: {v}")
    doc_lines.append(summary["url"])
    index_documents([VectorDocument(
        id=canonical.replace(":", "_"),
        source="kegg_live",
        collection=collection,
        doc_text="\n".join(doc_lines),
        metadata={
            "kegg_id": canonical,
            "kind": kind,
            "name": summary.get("name") or "",
        },
    )])

    return json.dumps(summary, ensure_ascii=False)
