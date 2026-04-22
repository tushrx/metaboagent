"""
@tool web_search — open-web search via DuckDuckGo (no API key required).

Returns a list of result dicts (title, url, snippet) the ReAct agent can read
and cite. Falls back gracefully when the network is unreachable or DDG throttles.
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

log = logging.getLogger(__name__)


def _run_ddg(query: str, max_results: int) -> list[dict]:
    """Prefer the newer ``ddgs`` package; fall back to the legacy one."""
    try:
        from ddgs import DDGS  # type: ignore
    except ImportError:  # pragma: no cover
        from duckduckgo_search import DDGS  # type: ignore

    with DDGS() as ddg:
        hits = list(ddg.text(query, max_results=max_results))
    return hits or []


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the open web (DuckDuckGo) for up-to-date scientific info.

    Use this when the indexed KEGG/PubMed corpus is thin, or when you need
    recent news, industrial process data, commercial strain reports, or
    general chemistry references beyond PubMed.

    Args:
        query: natural-language search query.
        max_results: number of hits to return (default 5, max 10).

    Returns:
        JSON string: list of {title, url, snippet} dicts.
    """
    max_results = max(1, min(int(max_results or 5), 10))
    try:
        hits = _run_ddg(query, max_results)
    except Exception as e:  # noqa: BLE001
        log.warning("web_search failed for %r: %s", query, e)
        return json.dumps({"error": f"web search unavailable: {e}", "results": []})

    results: list[dict] = []
    for h in hits:
        url = h.get("href") or h.get("url") or ""
        title = (h.get("title") or "").strip()
        snippet = (h.get("body") or h.get("snippet") or "").strip()
        if not (url and (title or snippet)):
            continue
        results.append({
            "title": title[:200],
            "url": url,
            "snippet": snippet[:400],
        })

    if not results:
        return json.dumps({"error": "no results", "results": []})
    return json.dumps({"query": query, "results": results}, ensure_ascii=False)
