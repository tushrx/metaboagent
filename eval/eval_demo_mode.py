"""Phase 7.2.5 — DEMO_MODE behavioral eval.

Five queries against an in-process run_agent with DEMO_MODE=1. For each
we capture the event sequence and apply pass/fail assertions:

  Q1-Q3: live-fetch tool with a fallback. Must invoke at least one
         indexed-corpus search tool (search_literature / search_kegg)
         AFTER the initial live-fetch stub.
  Q4:    live-fetch tool without a fallback. Final answer must NOT
         claim "from the indexed corpus" (or close synonyms) and must
         honestly admit the lookup is unavailable in demo mode.
  Q5:    no tool needed. Zero tool calls.

The eval drives run_agent in-process — same code path as POST /chat,
no uvicorn required.

Run:
    DEMO_MODE=1 PYTHONPATH=/home/tusharmicro/metaboagent \\
        python3 eval/eval_demo_mode.py

Output: eval/results/demo_mode_<UTC ISO8601 compact>.json
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

from eval._runner import drain_agent_turn, write_result

INDEXED_FALLBACK_TOOLS = {"search_literature", "search_kegg"}
LIVE_FETCH_TOOLS_WITH_FALLBACK = {
    "fetch_pubmed_live", "fetch_kegg_live", "fetch_uniprot", "fetch_sabio_rk",
}
LIVE_FETCH_TOOLS_WITHOUT_FALLBACK = {
    "fetch_pubchem", "fetch_zinc", "fetch_gene_sequence", "web_search",
}

# Phrases the agent must NOT use when no indexed-corpus tool was actually
# called this turn (Q4 hallucinated-sourcing detector).
_FALSE_ATTRIBUTION_MARKERS = (
    "from the indexed corpus",
    "from our indexed corpus",
    "based on indexed data",
    "according to the corpus",
    "from the indexed literature",
    "from our indexed literature",
)

QUERIES: list[dict[str, Any]] = [
    {
        "id": "Q1_pubmed_lycopene",
        "prompt": "Search PubMed for recent papers on lycopene biosynthesis in E. coli.",
        "category": "live_with_fallback",
        "expected_initial_tool": "fetch_pubmed_live",
    },
    {
        "id": "Q2_kegg_compound",
        "prompt": "Look up KEGG compound C00022.",
        "category": "live_with_fallback",
        "expected_initial_tool": "fetch_kegg_live",
    },
    {
        "id": "Q3_uniprot_p05067",
        "prompt": "Get the UniProt entry for P05067.",
        "category": "live_with_fallback",
        "expected_initial_tool": "fetch_uniprot",
    },
    {
        "id": "Q4_zinc_aspirin",
        "prompt": "Search ZINC15 for aspirin analogs.",
        "category": "live_no_fallback",
        "expected_initial_tool": "fetch_zinc",
    },
    {
        "id": "Q5_glucose_formula",
        "prompt": "What is the molecular formula of glucose?",
        "category": "no_tool",
        "expected_initial_tool": None,
    },
]

log = logging.getLogger("eval_demo_mode")


async def _drain(prompt: str, max_iterations: int = 6) -> dict[str, Any]:
    """Run a single user turn through run_agent and collect events."""
    from langchain_core.messages import HumanMessage

    events, final_answer, usage = await drain_agent_turn(
        [HumanMessage(content=prompt)],
        max_iterations=max_iterations,
    )
    return {
        "events": events,
        "final_answer": final_answer,
        "iterations": usage["iterations"],
        "duration_ms": usage["duration_ms"],
    }


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [ev["name"] for ev in events if ev.get("type") == "tool_call"]


def _classify(query: dict[str, Any], drained: dict[str, Any]) -> dict[str, Any]:
    """Apply per-category assertions and return a result row."""
    tool_names = _tool_call_names(drained["events"])
    final = drained["final_answer"]
    cat = query["category"]
    notes: list[str] = []
    passed = False

    if cat == "live_with_fallback":
        # First call must be the live-fetch tool, then at least one
        # indexed-corpus search tool AFTER it.
        if not tool_names:
            notes.append("no tool calls at all")
        else:
            first = tool_names[0]
            if first != query["expected_initial_tool"]:
                notes.append(
                    f"first tool was {first!r}, expected "
                    f"{query['expected_initial_tool']!r}"
                )
            indexed_after_first = [
                n for n in tool_names[1:] if n in INDEXED_FALLBACK_TOOLS
            ]
            if indexed_after_first:
                passed = True
                notes.append(
                    f"indexed fallback invoked: {indexed_after_first}"
                )
            else:
                notes.append(
                    "no indexed-corpus tool invoked after live-fetch stub"
                )

    elif cat == "live_no_fallback":
        # Must not falsely claim corpus sourcing. Final answer must
        # honestly admit unavailability.
        false_hits = [m for m in _FALSE_ATTRIBUTION_MARKERS if m in final.lower()]
        if false_hits:
            notes.append(f"false-attribution phrase(s) present: {false_hits}")
        else:
            # Must contain an honest admission. Cheap regex on common phrases
            # the directive nudges toward.
            honest = any(
                k in final.lower()
                for k in ("unavailable in demo", "demo mode", "live lookup",
                          "live search", "not available in demo")
            )
            if honest:
                passed = True
                notes.append("honest demo-mode admission present")
            else:
                notes.append("no honest demo-mode admission in final_answer")

    elif cat == "no_tool":
        if not tool_names:
            passed = True
            notes.append("zero tool calls as expected")
        else:
            notes.append(f"unexpected tool calls: {tool_names}")

    return {
        "id": query["id"],
        "prompt": query["prompt"],
        "category": cat,
        "passed": passed,
        "tool_calls": tool_names,
        "iterations": drained["iterations"],
        "duration_ms": drained["duration_ms"],
        "final_answer": final,
        "notes": notes,
    }


async def _run_all(max_iterations: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for q in QUERIES:
        log.info("[%s] running…", q["id"])
        drained = await _drain(q["prompt"], max_iterations=max_iterations)
        row = _classify(q, drained)
        log.info(
            "[%s]   passed=%s tools=%s ms=%d",
            q["id"], row["passed"], row["tool_calls"], row["duration_ms"],
        )
        rows.append(row)
    summary = {
        "total": len(rows),
        "passed": sum(1 for r in rows if r["passed"]),
        "failed": sum(1 for r in rows if not r["passed"]),
        "by_category": {
            "live_with_fallback": _category_summary(rows, "live_with_fallback"),
            "live_no_fallback": _category_summary(rows, "live_no_fallback"),
            "no_tool": _category_summary(rows, "no_tool"),
        },
    }
    return {"summary": summary, "rows": rows}


def _category_summary(rows: list[dict[str, Any]], cat: str) -> dict[str, int]:
    relevant = [r for r in rows if r["category"] == cat]
    return {
        "total": len(relevant),
        "passed": sum(1 for r in relevant if r["passed"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-iterations", type=int, default=6,
        help="Forwarded to run_agent's bounded loop.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s: %(message)s",
    )

    if os.environ.get("DEMO_MODE") != "1":
        log.error("DEMO_MODE=1 must be set in the environment to run this eval")
        return 2

    out = asyncio.run(_run_all(args.max_iterations))
    path = write_result("demo_mode", out)

    log.info("---")
    s = out["summary"]
    log.info("Total: %d  Passed: %d  Failed: %d", s["total"], s["passed"], s["failed"])
    for cat, c in s["by_category"].items():
        log.info("  %-22s %d / %d", cat, c["passed"], c["total"])
    log.info("Wrote %s", path)
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
