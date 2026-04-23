"""
@tool compare_synthesis_routes — side-by-side microbial vs chemical synthesis.

Given a target compound (name or KEGG id), this tool pulls evidence from the
indexed literature + KEGG for both routes and returns a structured comparison
across standardized criteria. The ReAct agent uses this output to synthesize
the final user-facing comparison (the UI renders it via a ``<compare-table>``
block).

What the tool does NOT do
    It does *not* invent numbers. Yields, costs, and sustainability scores are
    left as "evidence-only" strings for the agent (or user) to inspect — the
    scaffold supplies context and citations, not made-up metrics.

Criteria compared
    feedstock, key_reagents_or_enzymes, typical_yield, step_count,
    process_conditions, waste_profile, scalability_notes, cost_drivers,
    sustainability, published_precedents.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from langchain_core.tools import tool

from agent.tools.kegg_search import _get_retriever

log = logging.getLogger(__name__)

# Query templates — we search literature twice with distinct intent-framings.
_MICROBIAL_QUERIES = [
    "biosynthesis {target} microbial production heterologous expression",
    "metabolic engineering {target} strain fermentation yield",
]
_CHEMICAL_QUERIES = [
    "total synthesis {target} chemical route catalyst",
    "industrial synthesis {target} process feedstock",
]


def _normalize_target(raw: str) -> tuple[str, Optional[str]]:
    """Return (display_name, kegg_id) from either a KEGG ID or free-text name."""
    s = (raw or "").strip()
    m = re.match(r"^(?:cpd:)?(C\d{5})$", s, re.IGNORECASE)
    if m:
        kegg_id = m.group(1).upper()
        return kegg_id, kegg_id
    return s, None


def _hits_for_queries(queries: list[str], target: str, top_k: int) -> list[dict]:
    r = _get_retriever()
    seen: dict[str, dict] = {}
    for template in queries:
        q = template.format(target=target)
        hits = r.search_literature(q, top_k=top_k)
        for h in hits:
            pmid = h.metadata.get("pmid") or h.id
            if pmid in seen:
                continue
            snippet = (h.text or "").strip().replace("\n", " ")
            if len(snippet) > 320:
                snippet = snippet[:320] + "…"
            seen[pmid] = {
                "pmid": pmid,
                "title": h.metadata.get("title") or "",
                "year": h.metadata.get("year") or "",
                "journal": h.metadata.get("journal") or "",
                "score": round(h.score, 3),
                "snippet": snippet,
            }
    # Best-scoring first, capped.
    return sorted(seen.values(), key=lambda d: d["score"], reverse=True)[:top_k]


def _kegg_context(target_kegg_id: Optional[str], display_name: str) -> dict:
    """Pull a compact KEGG context: compound entry + any associated reactions."""
    r = _get_retriever()
    ctx: dict = {"kegg_id": target_kegg_id, "pathways": [], "reactions": []}
    try:
        if target_kegg_id:
            comp_hits = r.search_compounds(
                f"compound {target_kegg_id} {display_name}", compound_id=target_kegg_id, top_k=2)
        else:
            comp_hits = r.search_compounds(display_name, top_k=2)
        for c in comp_hits[:1]:
            m = c.metadata
            ctx["compound_name"] = m.get("name") or display_name
            ctx["formula"] = m.get("formula") or ""
            ctx["pathways"] = _as_list(m.get("pathway_ids", ""))[:6]
            ctx["reactions"] = _as_list(m.get("reaction_ids", ""))[:8]
    except Exception as e:  # noqa: BLE001
        log.debug("kegg context lookup failed: %s", e)
    return ctx


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return v
    if not v:
        return []
    return [t.strip() for t in str(v).split(",") if t.strip()]


@tool(parse_docstring=True)
def compare_synthesis_routes(target: str, top_k: int = 4) -> str:
    """Build a side-by-side microbial-vs-chemical synthesis comparison scaffold.

    Args:
        target: Target compound — either a KEGG compound ID ("C05432") or a
            free-text name ("lycopene", "artemisinic acid").
        top_k: Literature hits per route to surface (default 4).

    Returns:
        JSON string with:
          - ``target``: display name + KEGG id if resolved
          - ``kegg_context``: pathways and reactions involving the target
          - ``microbial_route`` and ``chemical_route`` sections, each with a
            ``literature`` list (PMIDs + titles + snippets) and a
            ``comparison_criteria`` list of standardized columns the agent
            should populate when writing the final comparison table.
          - ``suggested_columns``: the canonical column order for the UI's
            ``<compare-table>`` block.

        The agent must synthesize numeric yields / costs / sustainability
        values from the evidence. The tool only supplies the scaffold and
        the raw literature snippets — no fabricated numbers.
    """
    t = (target or "").strip()
    if not t:
        return json.dumps({"error": "empty target"})

    display, kegg_id = _normalize_target(t)
    top_k = max(2, min(8, int(top_k)))

    microbial_hits = _hits_for_queries(_MICROBIAL_QUERIES, display, top_k)
    chemical_hits = _hits_for_queries(_CHEMICAL_QUERIES, display, top_k)
    kegg_ctx = _kegg_context(kegg_id, display)

    suggested_columns = [
        "feedstock",
        "key_reagents_or_enzymes",
        "typical_yield",
        "step_count",
        "process_conditions",
        "waste_profile",
        "scalability_notes",
        "cost_drivers",
        "sustainability",
    ]

    comparison_template = [
        {"criterion": c,
         "microbial": "<<populate from evidence>>",
         "chemical": "<<populate from evidence>>"}
        for c in suggested_columns
    ]

    return json.dumps({
        "target": {"name": display, "kegg_id": kegg_id},
        "kegg_context": kegg_ctx,
        "microbial_route": {
            "intent": "Fermentation / enzymatic biosynthesis in an engineered microbial host.",
            "literature": microbial_hits,
        },
        "chemical_route": {
            "intent": "Bench or industrial chemical synthesis via traditional organic chemistry.",
            "literature": chemical_hits,
        },
        "suggested_columns": suggested_columns,
        "comparison_template": comparison_template,
        "guidance": (
            "Populate each template cell using ONLY the supplied literature "
            "snippets, kegg_context, or prior fetch_pubchem/fetch_pubmed_live "
            "results. If evidence is missing for a cell, write 'insufficient "
            "evidence' instead of guessing. Cite PMIDs inline, e.g. [PMID 12345]."
        ),
    }, ensure_ascii=False)
