"""
LangChain tool: search_literature — semantic search over the literature collection.
"""
from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from agent.tools.kegg_search import _get_retriever


@tool(parse_docstring=True)
def search_literature(
    query: str,
    max_results: int = 5,
    mesh_term: Optional[str] = None,
) -> str:
    """Semantic search over indexed PubMed abstracts and KEGG pathway descriptions.

    Use this for FOUNDATIONAL or HISTORICAL literature questions:
    - "classic papers on", "original discovery of", "seminal work"
    - "history of", "first paper on", "who first showed"
    - Mechanism/concept questions citing established evidence
    - Follow-up searches over abstracts that fetch_pubmed_live indexed earlier
      in this same conversation

    For "what does the literature say" / "papers on Y" / general literature
    questions, prefer fetch_pubmed_live — those queries usually expect
    current work.

    Args:
        query: free-text query (e.g., "heterologous lycopene production in E. coli").
        max_results: number of hits to return.
        mesh_term: optional exact MeSH-term filter. Pass null to skip.

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
