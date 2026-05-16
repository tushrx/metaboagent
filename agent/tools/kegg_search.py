"""
LangChain tool: search_kegg — query KEGG reactions and compounds.

Wraps vectorstore.Retriever with an optional metadata filter. filter_type
is Optional[Literal["ec_number","compound_id","pathway_id"]]; junk strings
("none"/"null"/"") in filter_value are explicitly rejected (no silent
passthrough).
"""
from __future__ import annotations

import json
from typing import Literal, Optional

from langchain_core.tools import tool

from vectorstore.retriever import Retriever, get_retriever

_retriever: Retriever | None = None

KeggFilter = Literal["ec_number", "compound_id", "pathway_id"]
_FILTER_VALUE_REJECTIONS = frozenset({"none", "null", ""})


def _get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = get_retriever()
    return _retriever


def set_retriever(r: Retriever) -> None:
    """Allow the agent to inject a shared retriever instance (avoids reloading PubMedBERT)."""
    global _retriever
    _retriever = r


@tool(parse_docstring=True)
def search_kegg(
    query: str,
    filter_type: Optional[KeggFilter] = None,
    filter_value: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """Search the KEGG reactions and compounds knowledge base.

    Call this tool whenever the user wants KEGG reactions or compounds
    surfaced by topic ("enzyme that converts X to Y", "compounds in
    glycolysis") or when filtering by EC number, compound ID, or
    pathway ID. For a specific KEGG identifier the user already has in
    hand (C\\d+, R\\d+, K\\d+, map\\d+), use fetch_kegg_live instead to
    pull the full record. Prefer tool calls over memory when the user
    writes "look up", "fetch", or "search KEGG for".

    Args:
        query: natural-language query about a reaction, compound, or enzyme (e.g., "enzyme that converts GGPP to lycopene").
        filter_type: optional filter to narrow results. One of "ec_number" (e.g. "2.5.1.29"), "compound_id" (e.g. "C05432"), or "pathway_id" (e.g. "map00900"). Pass null for no filter.
        filter_value: exact value for the filter; must match filter_type. Pass null for no filter.
        top_k: number of results to return from each collection.

    Returns:
        JSON string with a list of hits, each containing id, score, collection,
        and key metadata (EC numbers, pathway IDs, equation, etc.).
    """
    r = _get_retriever()

    rxn_kwargs: dict = {"top_k": top_k}
    cpd_kwargs: dict = {"top_k": top_k}

    # TODO(phase later): reaction_id filter — requires retriever.py changes, out of scope for 3.2
    applied_filter: Optional[tuple[str, str]] = None
    if filter_type and filter_value:
        val = filter_value.strip()
        if val.lower() not in _FILTER_VALUE_REJECTIONS:
            if filter_type == "ec_number":
                rxn_kwargs["ec_number"] = val
            elif filter_type == "compound_id":
                rxn_kwargs["compound_id"] = val
                cpd_kwargs["compound_id"] = val
            elif filter_type == "pathway_id":
                rxn_kwargs["pathway_id"] = val
            applied_filter = (filter_type, val)

    rxns = r.search_reactions(query, **rxn_kwargs)
    cpds = r.search_compounds(query, **cpd_kwargs)

    hits = []
    for d in rxns:
        m = d.metadata
        hits.append({
            "collection": "kegg_reactions",
            "id": m.get("kegg_id", d.id),
            "score": round(d.score, 3),
            "name": m.get("name", ""),
            "equation": m.get("equation", ""),
            "ec_numbers": m.get("ec_numbers", ""),
            "pathway_ids": m.get("pathway_ids", ""),
        })
    for d in cpds:
        m = d.metadata
        hits.append({
            "collection": "kegg_compounds",
            "id": m.get("kegg_id", d.id),
            "score": round(d.score, 3),
            "name": m.get("primary_name", ""),
            "formula": m.get("formula", ""),
            "pathway_ids": m.get("pathway_ids", ""),
        })

    filter_report = (
        {applied_filter[0]: applied_filter[1]} if applied_filter else None
    )
    return json.dumps({"query": query, "filter": filter_report, "hits": hits},
                      ensure_ascii=False)
