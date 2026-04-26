"""
@tool fetch_sabio_rk — SABIO-RK enzyme kinetics lookup.

SABIO-RK's REST endpoint returns TSV (not JSON) for kineticLaws. We parse the
TSV server-side into a compact JSON summary with Km, kcat, Ki values plus
organism and publication reference.

Endpoint:
  https://sabiork.h-its.org/sabioRestWebServices/searchKineticLaws/tsv
  ?q=ECNumber:<ec> AND Organism:"<org>"&fields[]=EntryID&fields[]=KMvalue&...

No API key / auth required.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Optional

from langchain_core.tools import tool

from agent.tools._demo import is_demo_mode, stub as demo_stub
from agent.tools._http import get_text, make_session
from vectorstore.live_indexer import VectorDocument, index_documents, pick_collection

log = logging.getLogger(__name__)

_BASE = "https://sabiork.h-its.org/sabioRestWebServices/searchKineticLaws/tsv"
_FIELDS = [
    "EntryID", "ECNumber", "Organism", "Substrate", "Product",
    "Enzymename", "Parameter", "PubMedID",
]

_session = make_session(extra_headers={"Accept": "text/tab-separated-values,*/*"})


def _build_query(ec: str, organism: Optional[str]) -> str:
    parts = [f"ECNumber:{ec.strip()}"]
    if organism:
        org = organism.strip().replace('"', "")
        parts.append(f'Organism:"{org}"')
    return " AND ".join(parts)


@tool(parse_docstring=True)
def fetch_sabio_rk(ec_number: str, organism: str = "", max_results: int = 15) -> str:
    """Fetch enzyme kinetic parameters (Km, kcat, Ki, etc.) from SABIO-RK.

    Args:
        ec_number: EC number without prefix, e.g. "2.5.1.29". Required.
        organism: Optional organism filter (e.g. "Escherichia coli").
        max_results: Cap on rows returned (default 15).

    Returns:
        JSON string with kinetic-law entries: entry_id, enzyme name,
        substrate, product, organism, parameter (e.g. "kcat" or "Km"),
        value + unit, and linked PMID. Indexed into the literature collection
        for future semantic search.
    """
    ec = (ec_number or "").strip()
    if not ec:
        return json.dumps({"error": "ec_number required"})
    if is_demo_mode():
        return demo_stub("fetch_sabio_rk", fallback="search_literature",
                         ec_number=ec, organism=organism, max_results=int(max_results))

    params = {
        "q": _build_query(ec, organism or None),
        "fields[]": _FIELDS,
    }
    # SABIO-RK expects repeated 'fields[]' — requests handles lists correctly.
    text = get_text(_session, _BASE, params=params)
    if not text:
        return json.dumps({"ec_number": ec, "organism": organism,
                           "entries": [], "note": "no SABIO-RK response"})

    # The endpoint emits TSV with a header row.
    entries = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    for i, row in enumerate(reader):
        if i >= max_results:
            break
        entries.append({
            "entry_id": row.get("EntryID"),
            "ec_number": row.get("ECNumber"),
            "organism": row.get("Organism"),
            "enzyme": row.get("Enzymename"),
            "substrate": row.get("Substrate"),
            "product": row.get("Product"),
            "parameter": row.get("Parameter"),
            "pmid": row.get("PubMedID"),
        })

    result = {
        "ec_number": ec,
        "organism": organism,
        "count": len(entries),
        "entries": entries,
    }

    # Auto-index a combined summary doc.
    if entries:
        text_summary = _compose_doc_text(ec, organism, entries)
        index_documents([VectorDocument(
            id=f"EC_{ec.replace('.', '_')}_{(organism or 'any').replace(' ', '_')[:30]}",
            source="sabio_rk",
            collection=pick_collection("sabio_rk"),
            doc_text=text_summary,
            metadata={
                "ec_number": ec,
                "organism": organism or "",
                "entry_count": len(entries),
                "pmids": sorted({e["pmid"] for e in entries if e.get("pmid")}),
            },
        )])

    return json.dumps(result, ensure_ascii=False)


def _compose_doc_text(ec: str, organism: str, entries: list[dict]) -> str:
    lines = [f"SABIO-RK kinetics for EC {ec}" + (f" in {organism}" if organism else ""),
             f"{len(entries)} kinetic-law entries."]
    for e in entries[:12]:
        lines.append(
            f"- {e.get('parameter', '?')}: enzyme={e.get('enzyme')}, "
            f"substrate={e.get('substrate')}, product={e.get('product')}, "
            f"organism={e.get('organism')}, PMID={e.get('pmid') or 'n/a'}"
        )
    return "\n".join(lines)
