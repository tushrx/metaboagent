"""End-to-end smoke tests for agent.core.run_agent against a LIVE vLLM on :8001.

Integration, not unit. Skips the entire class if the E4B endpoint is not
reachable so that CI/dev machines without a running vLLM see skips, not
failures.

Each scenario runs twice back-to-back; the first/second latency ratio is
a crude prefix-cache signal printed to stdout alongside the full event
sequences (for eyeball review in CI output).

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_agent_e2e -v
"""
from __future__ import annotations

import os
import re
import time
import unittest
import urllib.error
import urllib.request
from typing import Iterable

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from langchain_core.messages import HumanMessage

from agent.core import run_agent
from config import PRIMARY_LLM_BASE_URL

_REACHABILITY_TIMEOUT = 3.0
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_METABOLIC_TERMS = (
    "glycolysis", "citrate", "acetyl", "lactate", "tca",
    "citric acid", "krebs", "fermentation", "gluconeogenesis",
    "oxaloacetate", "alanine",
)


def _e4b_reachable() -> bool:
    url = PRIMARY_LLM_BASE_URL.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=_REACHABILITY_TIMEOUT) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


async def _collect_events(prompt: str) -> list[dict]:
    events: list[dict] = []
    async for ev in run_agent(
        [HumanMessage(content=prompt)],
        tier="default",
        max_iterations=6,
        temperature=0.0,
    ):
        events.append(ev)
    return events


def _print_sequence(label: str, events: Iterable[dict]) -> None:
    print(f"\n--- {label} ---")
    for i, ev in enumerate(events):
        t = ev["type"]
        if t == "token":
            print(f"  [{i:03d}] token: {ev.get('content')!r}")
        elif t == "tool_call":
            print(f"  [{i:03d}] tool_call: name={ev.get('name')} "
                  f"args={ev.get('args')} id={ev.get('id')}")
        elif t == "tool_result":
            body = str(ev.get("content"))[:300]
            print(f"  [{i:03d}] tool_result: id={ev.get('id')} content={body!r}")
        elif t == "tool_error":
            print(f"  [{i:03d}] tool_error: id={ev.get('id')} "
                  f"name={ev.get('name')} message={ev.get('message')}")
        elif t == "final_answer":
            body = (ev.get("content") or "")[:400]
            print(f"  [{i:03d}] final_answer: {body!r}")
        elif t == "done":
            print(f"  [{i:03d}] done: usage={ev.get('usage')}")
        elif t == "error":
            print(f"  [{i:03d}] error: where={ev.get('where')} "
                  f"message={ev.get('message')}")
        else:
            print(f"  [{i:03d}] {t}: {ev!r}")


async def _run_twice(prompt: str, scenario: str):
    t_a = time.perf_counter()
    events_a = await _collect_events(prompt)
    lat_a = time.perf_counter() - t_a
    _print_sequence(f"{scenario} run_a ({lat_a:.2f}s)", events_a)

    t_b = time.perf_counter()
    events_b = await _collect_events(prompt)
    lat_b = time.perf_counter() - t_b
    _print_sequence(f"{scenario} run_b ({lat_b:.2f}s)", events_b)

    ratio = lat_a / lat_b if lat_b > 0 else float("inf")
    print(f"{scenario} latency a={lat_a:.2f}s b={lat_b:.2f}s ratio(a/b)={ratio:.2f}x")
    return (events_a, lat_a), (events_b, lat_b)


@unittest.skipUnless(
    _e4b_reachable(),
    f"E4B vLLM not reachable at {PRIMARY_LLM_BASE_URL}",
)
class AgentE2ETests(unittest.IsolatedAsyncioTestCase):
    # ---- scenario 1: no tool needed ---------------------------------------
    async def test_scenario_1_no_tool_needed(self):
        prompt = "What is the molecular formula of aspirin?"
        (events_a, lat_a), (events_b, lat_b) = await _run_twice(prompt, "scenario_1")

        for label, events, latency in (
            ("run_a", events_a, lat_a),
            ("run_b", events_b, lat_b),
        ):
            with self.subTest(run=label):
                types = [e["type"] for e in events]
                self.assertIn("final_answer", types)
                self.assertEqual(types[-1], "done")
                tool_calls = [e for e in events if e["type"] == "tool_call"]
                self.assertEqual(
                    len(tool_calls), 0,
                    f"unexpected tool_calls: {[t['name'] for t in tool_calls]}",
                )
                final = next(e for e in events if e["type"] == "final_answer")
                content = (final.get("content") or "").lower()
                compact = content.replace(" ", "")
                self.assertTrue(
                    "c9h8o4" in compact or "aspirin" in content,
                    f"final_answer missing anchors; got: {content[:200]!r}",
                )
                self.assertLess(latency, 5.0, f"{label} exceeded 5s budget")

    # ---- scenario 2: single tool call -------------------------------------
    async def test_scenario_2_pubmed_tool(self):
        prompt = ("Find recent PubMed papers about artemisinin biosynthesis "
                  "in yeast.")
        (events_a, lat_a), (events_b, lat_b) = await _run_twice(prompt, "scenario_2")

        for label, events, latency in (
            ("run_a", events_a, lat_a),
            ("run_b", events_b, lat_b),
        ):
            with self.subTest(run=label):
                tool_calls = [e for e in events if e["type"] == "tool_call"]
                self.assertGreaterEqual(
                    len(tool_calls), 1,
                    "expected at least one tool_call",
                )
                pubmed_calls = [
                    e for e in tool_calls
                    if "pubmed" in e.get("name", "").lower()
                    or "literature" in e.get("name", "").lower()
                ]
                self.assertGreaterEqual(
                    len(pubmed_calls), 1,
                    f"expected pubmed/literature call, got "
                    f"{[e['name'] for e in tool_calls]}",
                )

                call_ids = {e["id"] for e in tool_calls}
                result_ids = {
                    e["id"] for e in events
                    if e["type"] in ("tool_result", "tool_error")
                }
                self.assertTrue(
                    call_ids.issubset(result_ids),
                    f"unmatched tool_call ids: {call_ids - result_ids}",
                )

                successes = [e for e in events if e["type"] == "tool_result"]
                self.assertGreaterEqual(len(successes), 1,
                                        "no successful tool_result")

                final = next(
                    (e for e in events if e["type"] == "final_answer"), None,
                )
                self.assertIsNotNone(final, "no final_answer")
                content = final.get("content") or ""
                low = content.lower()
                has_citation = (
                    "pmid" in low
                    or "doi" in low
                    or bool(_YEAR_RE.search(content))
                )
                self.assertTrue(
                    has_citation,
                    f"final lacks citation markers: {content[:300]!r}",
                )
                self.assertLess(latency, 15.0, f"{label} exceeded 15s budget")

    # ---- scenario 3: kegg lookup ------------------------------------------
    async def test_scenario_3_kegg_lookup(self):
        prompt = "Look up KEGG compound C00022 (pyruvate) and summarize."
        (events_a, lat_a), (events_b, lat_b) = await _run_twice(prompt, "scenario_3")

        for label, events, latency in (
            ("run_a", events_a, lat_a),
            ("run_b", events_b, lat_b),
        ):
            with self.subTest(run=label):
                tool_calls = [e for e in events if e["type"] == "tool_call"]
                kegg_calls = [
                    e for e in tool_calls
                    if "kegg" in e.get("name", "").lower()
                ]
                self.assertGreaterEqual(
                    len(kegg_calls), 1,
                    f"expected at least one kegg tool_call, got "
                    f"{[e['name'] for e in tool_calls]}",
                )
                results = [e for e in events if e["type"] == "tool_result"]
                self.assertGreaterEqual(len(results), 1,
                                        "no tool_result for kegg call")
                for r in results:
                    self.assertTrue(r.get("content"), f"empty tool_result: {r}")

                final = next(
                    (e for e in events if e["type"] == "final_answer"), None,
                )
                self.assertIsNotNone(final, "no final_answer")
                content = (final.get("content") or "").lower()
                self.assertIn(
                    "pyruvate", content,
                    f"final missing 'pyruvate': {content[:300]!r}",
                )
                self.assertTrue(
                    any(term in content for term in _METABOLIC_TERMS),
                    f"final lacks metabolic anchor term: {content[:300]!r}",
                )
                self.assertLess(latency, 15.0, f"{label} exceeded 15s budget")


if __name__ == "__main__":
    unittest.main()
