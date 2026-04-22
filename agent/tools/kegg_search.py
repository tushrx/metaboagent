"""
LangChain tool: search_kegg — query KEGG reactions and compounds.

Wraps vectorstore.Retriever with optional metadata filters:
    filter_type in {"ec_number", "compound_id", "pathway_id", "none"}
Returns a compact JSON string so the LLM can reason over structured fields.
"""
from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from vectorstore.retriever import Retriever

_retriever: Retriever | None = None


def _get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def set_retriever(r: Retriever) -> None:
    """Allow the agent to inject a shared retriever instance (avoids reloading PubMedBERT)."""
    global _retriever
    _retriever = r


@tool
def search_kegg(
    query: str,
    filter_type: str = "none",
    filter_value: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """Search the KEGG reactions and compounds knowledge base.

    Args:
        query: natural-language query about a reaction, compound, or enzyme
            (e.g., "enzyme that converts GGPP to lycopene").
        filter_type: one of "ec_number", "compound_id", "pathway_id", "none".
        filter_value: exact value for the filter (e.g., "2.5.1.29", "C05432", "map00900").
        top_k: number of results to return from each collection.

    Returns:
        JSON string with a list of hits, each containing id, score, collection,
        and key metadata (EC numbers, pathway IDs, equation, etc.).
    """
    r = _get_retriever()

    rxn_kwargs: dict = {"top_k": top_k}
    cpd_kwargs: dict = {"top_k": top_k}
    if filter_type == "ec_number" and filter_value:
        rxn_kwargs["ec_number"] = filter_value
    elif filter_type == "compound_id" and filter_value:
        rxn_kwargs["compound_id"] = filter_value
        cpd_kwargs["compound_id"] = filter_value
    elif filter_type == "pathway_id" and filter_value:
        rxn_kwargs["pathway_id"] = filter_value

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

    return json.dumps({"query": query, "filter": {filter_type: filter_value}, "hits": hits},
                      ensure_ascii=False)
