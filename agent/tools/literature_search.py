"""
LangChain tool: search_literature — semantic search over the literature collection.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.tools.kegg_search import _get_retriever


@tool
def search_literature(query: str, max_results: int = 5, mesh_term: str = "") -> str:
    """Semantic search over PubMed abstracts and KEGG pathway descriptions.

    Args:
        query: free-text query (e.g., "heterologous lycopene production in E. coli").
        max_results: number of hits to return.
        mesh_term: optional exact MeSH-term filter (e.g., "Metabolic Engineering").

    Returns:
        JSON string with list of {pmid, title, year, journal, snippet, score}.
    """
    r = _get_retriever()
    hits = r.search_literature(query, mesh_term=mesh_term or None, top_k=max_results)
    out = []
    for d in hits:
        m = d.metadata
        snippet = d.text.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        out.append({
            "pmid": m.get("pmid", d.id),
            "title": m.get("title", ""),
            "journal": m.get("journal", ""),
            "year": m.get("year", ""),
            "source": m.get("source", ""),
            "score": round(d.score, 3),
            "snippet": snippet,
        })
    return json.dumps({"query": query, "hits": out}, ensure_ascii=False)
