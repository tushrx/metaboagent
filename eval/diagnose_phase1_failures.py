"""Phase 6.5.b diagnosis — why do artemisinic_yeast and glucose_shikimate
fail to emit a <plan> block on turn 1?

Runs each of the two failing prompts against both tier=default (E4B)
and tier=deep (26B MoE), capturing:

  - Every visible event from run_agent (tool_call / tool_result /
    tool_error / final_answer / done / error) — with tokens dropped to
    keep the JSON small.
  - Per-iteration response_metadata from the underlying LLM (finish
    reason, stop token, usage shape), via a monkey-patch on
    agent.core._stream_llm that leaves production code untouched.
  - Total wallclock time and iterations.

Output: eval/results/phase1_diagnosis_<ts>.json + a text report on
stdout organised to rule out H1-H5 per prompt × tier.

No fixes are attempted. Read-only investigation.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = REPO_ROOT / "eval/scenarios/pathway_design/prompts.json"
RESULTS_DIR = REPO_ROOT / "eval/results"

# Prompts we're diagnosing. Hard-coded rather than taking --ids: this
# file exists to diagnose these specific failures.
TARGET_IDS = ("artemisinic_yeast", "glucose_shikimate")
TIERS = ("default", "deep")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("diagnose")


def _summarise_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Shorten long string args (like image_data_base64) for the report."""
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > 120:
            out[k] = f"<{len(v)} chars>"
        else:
            out[k] = v
    return out


async def _run_one(prompt_text: str, tier: str, max_iterations: int) -> dict[str, Any]:
    from agent import core as agent_core
    from agent.core import run_agent
    from langchain_core.messages import HumanMessage

    captured_meta: list[dict[str, Any]] = []
    original_stream = agent_core._stream_llm

    async def wrapped(llm, messages):
        async for kind, payload in original_stream(llm, messages):
            if kind == "final":
                meta_raw = getattr(payload, "response_metadata", None) or {}
                # Shallow-copy, keep only the judgable fields so we don't
                # spam the JSON with vendor telemetry.
                slim: dict[str, Any] = {}
                for key in (
                    "finish_reason",
                    "stop_reason",
                    "model_name",
                    "system_fingerprint",
                    "token_usage",
                ):
                    if key in meta_raw:
                        slim[key] = meta_raw[key]
                # LangChain sometimes exposes finish_reason under response_metadata
                # and sometimes under additional_kwargs — grab both.
                add_kw = getattr(payload, "additional_kwargs", None) or {}
                if "finish_reason" in add_kw and "finish_reason" not in slim:
                    slim["finish_reason"] = add_kw["finish_reason"]
                captured_meta.append(slim)
            yield kind, payload

    agent_core._stream_llm = wrapped  # type: ignore[assignment]
    events: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    try:
        async for ev in run_agent(
            [HumanMessage(content=prompt_text)],
            tier=tier,
            max_iterations=max_iterations,
        ):
            if ev.get("type") == "token":
                continue
            # Shorten long arg strings on tool_calls.
            if ev.get("type") == "tool_call":
                ev = {**ev, "args": _summarise_args(ev.get("name", ""), ev.get("args") or {})}
            events.append(ev)
    finally:
        agent_core._stream_llm = original_stream  # type: ignore[assignment]
    wallclock_ms = int(round((time.perf_counter() - t0) * 1000))

    # Pull final_answer + done + any error events out for the summary view.
    final_answer = ""
    done_usage: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    tool_errors: list[dict[str, Any]] = []
    for ev in events:
        t = ev.get("type")
        if t == "final_answer":
            final_answer = ev.get("content") or ""
        elif t == "done":
            done_usage = ev.get("usage") or {}
        elif t == "error":
            errors.append({"where": ev.get("where"), "message": ev.get("message")})
        elif t == "tool_call":
            tool_calls.append({
                "id": ev.get("id"),
                "name": ev.get("name"),
                "args": ev.get("args"),
            })
        elif t == "tool_error":
            tool_errors.append({
                "id": ev.get("id"),
                "name": ev.get("name"),
                "message": ev.get("message"),
            })

    return {
        "tier": tier,
        "wallclock_ms": wallclock_ms,
        "iterations": done_usage.get("iterations", 0),
        "tool_call_count": done_usage.get("tool_calls", 0),
        "final_answer_len": len(final_answer),
        "final_answer_tail": final_answer[-400:] if final_answer else "",
        "final_answer_full": final_answer,
        "errors": errors,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "iteration_metadata": captured_meta,
        "events": events,
    }


def _classify(run: dict[str, Any], max_iterations: int) -> list[str]:
    """Return a list of hypotheses the run is consistent with."""
    hits: list[str] = []
    if run["tool_errors"]:
        hits.append("H1 (tool errors)")
    if run["iterations"] >= max_iterations:
        hits.append("H2 (max_iterations hit)")
    text = run.get("final_answer_full") or ""
    body = text.lower()
    refusal_markers = (
        "cannot", "can not", "not feasible", "not possible",
        "does not exist", "incorrect premise", "mis-specified", "mis-stated",
        "seven-step", "7-step", "7 steps", "seven steps", "three-step",
        "not a valid", "unlikely",
    )
    if body and any(m in body for m in refusal_markers):
        hits.append("H3 (refusal / correction)")
    if not text.strip() and not run["errors"]:
        hits.append("H4 (empty completion)")
    for meta in run["iteration_metadata"]:
        fr = meta.get("finish_reason") or meta.get("stop_reason")
        if fr and fr not in ("stop", "tool_calls", None):
            hits.append(f"H5 (finish_reason={fr})")
            break
    return hits


def _print_report(all_runs: list[dict[str, Any]], max_iterations: int) -> None:
    print()
    print("=" * 78)
    print("Phase 6.5.b — Phase-1 failure diagnosis")
    print("=" * 78)
    for row in all_runs:
        pid = row["prompt_id"]
        for run in row["runs"]:
            tier = run["tier"]
            print()
            print(f"--- {pid} × tier={tier} -----------------------------------------")
            print(f"wallclock: {run['wallclock_ms']} ms")
            print(f"iterations: {run['iterations']}   tool_calls: {run['tool_call_count']}")
            print(f"final_answer length: {run['final_answer_len']} chars")
            print(f"tool calls made:")
            if run["tool_calls"]:
                for tc in run["tool_calls"]:
                    args_preview = json.dumps(tc["args"], ensure_ascii=False)[:160]
                    print(f"  - {tc['name']}({args_preview})")
            else:
                print("  (none)")
            if run["tool_errors"]:
                print(f"tool_errors:")
                for te in run["tool_errors"]:
                    print(f"  - {te['name']}: {te['message']!r}")
            else:
                print("tool_errors: (none)")
            if run["errors"]:
                print(f"agent errors:")
                for e in run["errors"]:
                    print(f"  - {e['where']}: {e['message']!r}")
            else:
                print("agent errors: (none)")
            if run["iteration_metadata"]:
                print("per-iteration metadata:")
                for i, m in enumerate(run["iteration_metadata"]):
                    print(f"  [{i}] {json.dumps(m, ensure_ascii=False)[:200]}")
            else:
                print("per-iteration metadata: (none captured)")
            if run["final_answer_full"]:
                print("final_answer tail (last 400 chars):")
                print("  " + run["final_answer_tail"].replace("\n", "\n  "))
            else:
                print("final_answer: EMPTY (literal repr below)")
                print(f"  {run['final_answer_full']!r}")
            hits = _classify(run, max_iterations)
            print(f"hypotheses consistent with this run: {hits or ['(none matched)']}")


async def _main(ids: list[str], tiers: list[str], max_iterations: int) -> int:
    prompts_raw = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    prompts = {p["id"]: p for p in prompts_raw}
    missing = [i for i in ids if i not in prompts]
    if missing:
        log.error("prompts not in prompts.json: %s", missing)
        return 1

    all_runs: list[dict[str, Any]] = []
    for pid in ids:
        spec = prompts[pid]
        row: dict[str, Any] = {"prompt_id": pid, "prompt": spec["prompt"], "runs": []}
        for tier in tiers:
            log.info("[%s × %s] starting…", pid, tier)
            run = await _run_one(spec["prompt"], tier, max_iterations)
            log.info(
                "[%s × %s] done: iters=%d tool_calls=%d final_len=%d errors=%d",
                pid, tier, run["iterations"], run["tool_call_count"],
                run["final_answer_len"], len(run["errors"]) + len(run["tool_errors"]),
            )
            row["runs"].append(run)
        all_runs.append(row)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"phase1_diagnosis_{ts}.json"
    # Strip the raw `events` list to keep the JSON small-ish; we still have
    # tool_calls/tool_errors/final_answer as the judgable fields.
    for row in all_runs:
        for run in row["runs"]:
            run.pop("events", None)
    out_path.write_text(
        json.dumps(
            {"timestamp_utc": ts, "max_iterations": max_iterations, "prompts": all_runs},
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    log.info("wrote %s", out_path)
    _print_report(all_runs, max_iterations)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids", type=str, default=",".join(TARGET_IDS),
        help="comma-separated prompt IDs (default: artemisinic_yeast,glucose_shikimate)",
    )
    parser.add_argument(
        "--tiers", type=str, default=",".join(TIERS),
        help="comma-separated tiers (default: default,deep)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=8,
        help="agent loop cap per turn (default 8)",
    )
    args = parser.parse_args()
    ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    tiers = [s.strip() for s in args.tiers.split(",") if s.strip()]
    return asyncio.run(_main(ids, tiers, args.max_iterations))


if __name__ == "__main__":
    sys.exit(main())
