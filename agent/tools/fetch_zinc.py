"""
@tool fetch_zinc — ZINC15 substance / catalog lookup.

ZINC (https://zinc15.docking.org/) is a free database of commercially
available compounds for virtual screening. Useful when the agent needs a
*purchasable* version of a target compound (vendor, catalog id, SMILES).

Endpoints used
  /substances/{zinc_id}.json       — direct ZINC-id lookup
  /substances.json?name-contains=X — substance name substring search

The name-search endpoint returns a list of substances matching the term; we
pick the top hit and fetch its full record for SMILES / MW / vendor info.

ZINC IDs look like ``ZINC000000016978`` (15 digits). Shorter numeric IDs are
padded to that length automatically.
"""
from __future__ import annotations

import json
import logging
import re

from langchain_core.tools import tool

from agent.tools._demo import is_demo_mode, stub as demo_stub
from agent.tools._http import get_json, make_session
from vectorstore.live_indexer import VectorDocument, index_documents, pick_collection

log = logging.getLogger(__name__)

_BASE = "https://zinc15.docking.org"
_ZINC_RE = re.compile(r"^ZINC\d{1,15}$", re.IGNORECASE)
_session = make_session()


def _normalize_zinc_id(q: str) -> str | None:
    """Accept 'ZINC000000016978', 'zinc16978', or bare '16978'. Return canonical form."""
    q = q.strip()
    if _ZINC_RE.match(q):
        digits = re.sub(r"^ZINC", "", q, flags=re.IGNORECASE)
        return f"ZINC{int(digits):012d}"
    if q.isdigit():
        return f"ZINC{int(q):012d}"
    return None


def _search_by_name(name: str) -> list[dict]:
    """Return up to 10 ZINC substance dicts matching a name substring."""
    data = get_json(_session, f"{_BASE}/substances.json", params={
        "name-contains": name, "count": 10,
    })
    if not isinstance(data, list):
        return []
    return data


def _fetch_substance(zinc_id: str) -> dict | None:
    data = get_json(_session, f"{_BASE}/substances/{zinc_id}.json")
    if isinstance(data, dict):
        return data
    return None


def _short_record(rec: dict) -> dict:
    zid = rec.get("zinc_id") or rec.get("id")
    return {
        "zinc_id": zid,
        "name": rec.get("preferred_name") or rec.get("name"),
        "smiles": rec.get("smiles"),
        "inchi": rec.get("inchi"),
        "mw": rec.get("mwt"),
        "logp": rec.get("logp"),
        "rb": rec.get("rb"),  # rotatable bonds
        "hba": rec.get("hba"),
        "hbd": rec.get("hbd"),
        "purchasable": rec.get("purchasable"),
        "num_vendors": rec.get("num_vendors"),
        "url": f"https://zinc15.docking.org/substances/{zid}/" if zid else None,
    }


@tool(parse_docstring=True)
def fetch_zinc(compound_name_or_zinc_id: str) -> str:
    """Look up a compound in ZINC15 (commercial availability + vendor info).

    Args:
        compound_name_or_zinc_id: Either a ZINC id (e.g. "ZINC000000016978"
            or bare "16978") or a free-text compound name to search.

    Returns:
        JSON string with the top-matching substance: ZINC id, preferred name,
        SMILES/InChI, physicochemical properties (MW, logP, rotatable bonds,
        H-bond donors/acceptors), purchasability flag, number of vendors, and
        a link to the ZINC page. Auto-indexed into the compounds collection.
    """
    q = (compound_name_or_zinc_id or "").strip()
    if not q:
        return json.dumps({"error": "empty query"})
    if is_demo_mode():
        return demo_stub("fetch_zinc", compound_name_or_zinc_id=q)

    canonical = _normalize_zinc_id(q)
    if canonical:
        rec = _fetch_substance(canonical)
        if not rec:
            return json.dumps({"query": q, "error": "ZINC id not found"})
        hit = _short_record(rec)
    else:
        matches = _search_by_name(q)
        if not matches:
            return json.dumps({"query": q, "hits": [],
                               "note": "no ZINC substances matched"})
        # Use the top hit's full record if the list is sparse.
        top = matches[0]
        zid = top.get("zinc_id") or top.get("id")
        full = _fetch_substance(zid) if zid else None
        hit = _short_record(full or top)

    # Auto-index into the compounds collection.
    if hit.get("zinc_id"):
        doc_text = _compose_doc_text(hit)
        index_documents([VectorDocument(
            id=hit["zinc_id"],
            source="zinc",
            collection=pick_collection("zinc"),
            doc_text=doc_text,
            metadata={
                "zinc_id": hit["zinc_id"],
                "name": hit.get("name") or "",
                "smiles": hit.get("smiles") or "",
                "mw": hit.get("mw") or "",
                "logp": hit.get("logp") or "",
                "purchasable": bool(hit.get("purchasable")),
                "num_vendors": hit.get("num_vendors") or 0,
            },
        )])

    return json.dumps({"query": q, "hit": hit}, ensure_ascii=False)


def _compose_doc_text(hit: dict) -> str:
    lines = [
        f"ZINC substance: {hit.get('name') or '(unnamed)'} "
        f"(ID {hit.get('zinc_id')})",
        f"SMILES: {hit.get('smiles') or 'n/a'}",
        f"MW: {hit.get('mw') or 'n/a'} g/mol, logP: {hit.get('logp')}, "
        f"rotatable bonds: {hit.get('rb')}, "
        f"H-bond donors/acceptors: {hit.get('hbd')}/{hit.get('hba')}",
    ]
    if hit.get("purchasable"):
        lines.append(f"Purchasable from {hit.get('num_vendors') or '?'} vendors")
    if hit.get("url"):
        lines.append(hit["url"])
    return "\n".join(lines)
