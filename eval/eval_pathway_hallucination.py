"""Phase 6.5-pre baseline: how often does the agent fabricate KEGG
R-IDs and EC numbers when it reaches the deep-dive step of a pathway
design conversation?

The agent's system prompt splits pathway questions into Phase 1
(propose <plan>...</plan> with 3-4 approaches, no IDs yet) and
Phase 2 (deep-dive after the user picks, numbered pathway steps with
R-IDs + EC numbers). Hallucinated IDs live in Phase 2 output, so a
single-turn eval measures nothing — we drive both turns.

Flow per prompt:
  1. Turn 1: run_agent on the original user message.
     Collect final_answer + usage.
  2. Parse <plan>...</plan> from turn 1; extract plan IDs (A/B/C or
     1/2/3). If missing, mark plan_parse_failed and skip.
  3. Turn 2: run_agent on
        [Human(original), AI(phase1_final_answer), Human(first_plan_id)]
     Collect final_answer + usage.
  4. Extract R-IDs (``R\\d{5}``) and EC numbers
     (``EC\\s?\\d+\\.\\d+\\.\\d+\\.\\d+``) from Phase 2 answer.
  5. Verify each against KEGG REST with 400 ms sleep (KEGG allows
     ~3 rps anonymous).
  6. Aggregate.

We call run_agent in-process rather than POST /chat — it's the same
code path and avoids needing a live uvicorn.

Output: eval/results/pathway_hallucination_baseline_<ts>.json
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = REPO_ROOT / "eval/scenarios/pathway_design/prompts.json"
RESULTS_DIR = REPO_ROOT / "eval/results"

KEGG_BASE = "https://rest.kegg.jp"
KEGG_SLEEP_S = 0.4   # ~2.5 rps, under KEGG's 3 rps anonymous ceiling
KEGG_TIMEOUT_S = 10.0

RID_RE = re.compile(r"\bR\d{5}\b")
EC_RE = re.compile(r"\bEC\s?(\d+\.\d+\.\d+\.\d+)\b")
PLAN_BLOCK_RE = re.compile(r"<plan>\s*(.*?)\s*</plan>", re.DOTALL | re.IGNORECASE)
# A pathway step opener. Accepts the canonical "Step 1:" shape plus the
# markdown numbered-list styles the model sometimes drifts into:
#   Step 1:          (canonical from the system prompt)
#   **Step 1:**      (bold-wrapped canonical)
#   1.               (markdown ordered list)
#   1)               (paren-style list)
#   **1.**           (bold-wrapped numbered)
# Anchored to line start with optional leading whitespace. The closing
# punctuation ([.):]) guards against false positives like "1 gram" or
# "Figure 1." (the latter doesn't start with a digit at line anchor).
STEP_LINE_RE = re.compile(
    r"(?im)^\s*(?:\*\*)?\s*(?:Step\s+)?(\d+)[.):]"
)
# Marker for Phase 6.5.c's nudge thinking event.
_NUDGE_MARKER = "Empty completion detected"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval_pathway")


def _extract_ids(text: str) -> tuple[list[str], list[str]]:
    rids: list[str] = []
    ecs: list[str] = []
    seen_r: set[str] = set()
    seen_e: set[str] = set()
    for m in RID_RE.finditer(text):
        rid = m.group(0)
        if rid not in seen_r:
            seen_r.add(rid)
            rids.append(rid)
    for m in EC_RE.finditer(text):
        ec = m.group(1)
        if ec not in seen_e:
            seen_e.add(ec)
            ecs.append(ec)
    return rids, ecs


def _extract_plan_ids(text: str) -> list[str] | None:
    """Return list of plan IDs from a <plan>...</plan> block, or None
    if no parseable plan block is present.

    Empty list (plan block present but no IDs) also returns None so
    the caller treats it as plan_parse_failed.
    """
    m = PLAN_BLOCK_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    # Tolerate stray prose before/after the JSON array inside the block.
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        arr = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list):
        return None
    ids: list[str] = []
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("id")
        if isinstance(pid, (str, int)) and str(pid).strip():
            ids.append(str(pid).strip())
    return ids or None


def _context_snippet(text: str, needle: str, window: int = 80) -> str:
    i = text.find(needle)
    if i < 0:
        return ""
    lo = max(0, i - window)
    hi = min(len(text), i + len(needle) + window)
    return text[lo:hi].replace("\n", " ").strip()


def _verify_kegg_id(client: httpx.Client, kind: str, raw: str) -> bool:
    if kind == "rid":
        path = f"{KEGG_BASE}/get/{raw}"
    elif kind == "ec":
        path = f"{KEGG_BASE}/get/ec:{raw}"
    else:
        raise ValueError(f"unknown kind: {kind}")
    try:
        r = client.get(path, timeout=KEGG_TIMEOUT_S)
    except httpx.HTTPError as e:
        log.warning("  KEGG request failed for %s %s: %s", kind, raw, e)
        return False
    if r.status_code == 200 and r.text.strip():
        return True
    if r.status_code == 404:
        return False
    log.warning("  unexpected KEGG status %d for %s %s", r.status_code, kind, raw)
    return False


async def _drain_turn(messages_payload: list[Any], max_iterations: int) -> dict[str, Any]:
    """Run one agent turn and collect the stream. messages_payload is a
    list of langchain BaseMessage objects."""
    from agent.core import run_agent

    events: list[dict] = []
    final_answer = ""
    tokens_in = 0
    tokens_out = 0
    duration_ms = 0
    iterations = 0
    t0 = time.perf_counter()
    async for ev in run_agent(
        messages_payload,
        tier="default",
        max_iterations=max_iterations,
    ):
        if ev.get("type") == "token":
            continue  # keep JSON compact; we already get final_answer
        events.append(ev)
        if ev.get("type") == "final_answer":
            final_answer = ev.get("content") or ""
        if ev.get("type") == "done":
            usage = ev.get("usage") or {}
            tokens_in = usage.get("tokens_in", 0) or 0
            tokens_out = usage.get("tokens_out", 0) or 0
            duration_ms = usage.get("ms", 0) or 0
            iterations = usage.get("iterations", 0) or 0
    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    # run_agent reports its own ms; fall back to wallclock if zero.
    if not duration_ms:
        duration_ms = elapsed_ms
    nudge_count = sum(
        1 for ev in events
        if ev.get("type") == "thinking"
        and _NUDGE_MARKER in (ev.get("content") or "")
    )
    return {
        "events": events,
        "final_answer": final_answer,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "duration_ms": duration_ms,
        "iterations": iterations,
        "nudge_count": nudge_count,
    }


async def _run_one(prompt_spec: dict, max_iterations: int) -> dict[str, Any]:
    """Two-turn eval for a single prompt."""
    from langchain_core.messages import AIMessage, HumanMessage

    pid = prompt_spec["id"]
    user_prompt = prompt_spec["prompt"]

    log.info("[%s] turn 1: sending original prompt…", pid)
    phase1 = await _drain_turn([HumanMessage(content=user_prompt)], max_iterations)
    log.info(
        "[%s]   phase1 done: iters=%d tokens=%d/%d ms=%d",
        pid, phase1["iterations"],
        phase1["tokens_in"], phase1["tokens_out"], phase1["duration_ms"],
    )

    plan_ids = _extract_plan_ids(phase1["final_answer"])
    row: dict[str, Any] = {
        "id": pid,
        "prompt": user_prompt,
        "phase1_final_answer": phase1["final_answer"],
        "phase1_tokens_in": phase1["tokens_in"],
        "phase1_tokens_out": phase1["tokens_out"],
        "phase1_duration_ms": phase1["duration_ms"],
        "phase1_iterations": phase1["iterations"],
        "phase1_plan_ids": plan_ids or [],
        "followup_sent": None,
        "phase2_final_answer": None,
        "phase2_tokens_in": 0,
        "phase2_tokens_out": 0,
        "phase2_duration_ms": 0,
        "phase2_iterations": 0,
        "phase1_nudge_count": phase1.get("nudge_count", 0),
        "phase2_nudge_count": 0,
        "step_convention_ok": False,
        "rids": [],
        "ecs": [],
        "status": "ok",  # ok | plan_parse_failed | no_ids_emitted
    }

    if not plan_ids:
        log.warning("[%s]   no parseable <plan> block — skipping phase 2", pid)
        row["status"] = "plan_parse_failed"
        return row

    followup = plan_ids[0]
    row["followup_sent"] = followup
    log.info("[%s] turn 2: sending follow-up %r…", pid, followup)

    phase2_messages = [
        HumanMessage(content=user_prompt),
        AIMessage(content=phase1["final_answer"]),
        HumanMessage(content=followup),
    ]
    phase2 = await _drain_turn(phase2_messages, max_iterations)
    log.info(
        "[%s]   phase2 done: iters=%d tokens=%d/%d ms=%d",
        pid, phase2["iterations"],
        phase2["tokens_in"], phase2["tokens_out"], phase2["duration_ms"],
    )

    row["phase2_final_answer"] = phase2["final_answer"]
    row["phase2_tokens_in"] = phase2["tokens_in"]
    row["phase2_tokens_out"] = phase2["tokens_out"]
    row["phase2_duration_ms"] = phase2["duration_ms"]
    row["phase2_iterations"] = phase2["iterations"]
    row["phase2_nudge_count"] = phase2.get("nudge_count", 0)
    row["step_convention_ok"] = bool(
        STEP_LINE_RE.search(phase2["final_answer"] or "")
    )

    rids, ecs = _extract_ids(phase2["final_answer"])
    log.info("[%s]   phase2 extracted: %d R-IDs, %d ECs", pid, len(rids), len(ecs))

    if not rids and not ecs:
        row["status"] = "no_ids_emitted"
        log.warning("[%s]   phase2 emitted zero R-IDs/ECs — pathway convention skipped", pid)
        return row

    final = phase2["final_answer"]
    rid_rows: list[dict] = []
    ec_rows: list[dict] = []
    with httpx.Client(headers={"User-Agent": "MetaboAgent-eval/1.0"}) as client:
        for rid in rids:
            exists = _verify_kegg_id(client, "rid", rid)
            rid_rows.append({
                "id": rid,
                "verified": exists,
                "context": _context_snippet(final, rid),
            })
            time.sleep(KEGG_SLEEP_S)
        for ec in ecs:
            exists = _verify_kegg_id(client, "ec", ec)
            ec_rows.append({
                "id": ec,
                "verified": exists,
                "context": _context_snippet(final, f"EC {ec}")
                           or _context_snippet(final, f"EC{ec}")
                           or _context_snippet(final, ec),
            })
            time.sleep(KEGG_SLEEP_S)
    row["rids"] = rid_rows
    row["ecs"] = ec_rows
    r_bad = sum(1 for r in rid_rows if not r["verified"])
    e_bad = sum(1 for e in ec_rows if not e["verified"])
    log.info(
        "[%s]   verified: rids %d hallucinated of %d; ecs %d hallucinated of %d",
        pid, r_bad, len(rid_rows), e_bad, len(ec_rows),
    )
    return row


def _aggregate(per_prompt: list[dict]) -> dict[str, Any]:
    p1_tokens_in = sum(r["phase1_tokens_in"] for r in per_prompt)
    p1_tokens_out = sum(r["phase1_tokens_out"] for r in per_prompt)
    p1_durs = [r["phase1_duration_ms"] for r in per_prompt if r["phase1_duration_ms"]]
    p1_avg_ms = int(round(sum(p1_durs) / len(p1_durs))) if p1_durs else 0
    plans_emitted = sum(1 for r in per_prompt if r["phase1_plan_ids"])
    plans_parse_failed = sum(1 for r in per_prompt if r["status"] == "plan_parse_failed")

    p2_eligible = [r for r in per_prompt if r["phase2_final_answer"] is not None]
    p2_tokens_in = sum(r["phase2_tokens_in"] for r in p2_eligible)
    p2_tokens_out = sum(r["phase2_tokens_out"] for r in p2_eligible)
    p2_durs = [r["phase2_duration_ms"] for r in p2_eligible if r["phase2_duration_ms"]]
    p2_avg_ms = int(round(sum(p2_durs) / len(p2_durs))) if p2_durs else 0
    no_ids_emitted = sum(1 for r in per_prompt if r["status"] == "no_ids_emitted")

    total_r = sum(len(r["rids"]) for r in per_prompt)
    total_r_bad = sum(1 for r in per_prompt for x in r["rids"] if not x["verified"])
    total_e = sum(len(r["ecs"]) for r in per_prompt)
    total_e_bad = sum(1 for r in per_prompt for x in r["ecs"] if not x["verified"])

    total_nudges = sum(
        r.get("phase1_nudge_count", 0) + r.get("phase2_nudge_count", 0)
        for r in per_prompt
    )
    prompts_with_nudge = sum(
        1 for r in per_prompt
        if (r.get("phase1_nudge_count", 0) + r.get("phase2_nudge_count", 0)) > 0
    )
    step_convention_ok = sum(1 for r in per_prompt if r.get("step_convention_ok"))

    return {
        "phase1_stats": {
            "total_tokens_in": p1_tokens_in,
            "total_tokens_out": p1_tokens_out,
            "avg_duration_ms": p1_avg_ms,
            "plans_emitted": plans_emitted,
            "plans_parse_failed": plans_parse_failed,
        },
        "phase2_stats": {
            "total_tokens_in": p2_tokens_in,
            "total_tokens_out": p2_tokens_out,
            "avg_duration_ms": p2_avg_ms,
            "phase2_runs": len(p2_eligible),
            "no_ids_emitted": no_ids_emitted,
            "step_convention_ok": step_convention_ok,
        },
        "pathway_accuracy": {
            "total_rids_extracted": total_r,
            "total_rids_hallucinated": total_r_bad,
            "rid_hallucination_rate_pct": round(100.0 * total_r_bad / total_r, 1) if total_r else 0.0,
            "total_ecs_extracted": total_e,
            "total_ecs_hallucinated": total_e_bad,
            "ec_hallucination_rate_pct": round(100.0 * total_e_bad / total_e, 1) if total_e else 0.0,
        },
        "nudge_stats": {
            "total_nudges_fired": total_nudges,
            "prompts_with_nudge": prompts_with_nudge,
        },
    }


def _threshold_band(rate: float) -> str:
    if rate < 10.0:
        return "<10%  (Phase 6.5 may be unnecessary — re-evaluate)"
    if rate <= 40.0:
        return "10-40%  (Phase 6.5 as planned: verify tools + prompt tighten + validator)"
    return ">40%  (Phase 6.5 plus aggressive validator — strip unverified IDs from final_answer)"


def _print_summary(agg: dict, per_prompt: list[dict]) -> None:
    pa = agg["pathway_accuracy"]
    p1 = agg["phase1_stats"]
    p2 = agg["phase2_stats"]

    print()
    print("=" * 72)
    print("Pathway hallucination — two-turn baseline")
    print("=" * 72)
    print(
        f"Phase 1: tokens in/out={p1['total_tokens_in']}/{p1['total_tokens_out']}  "
        f"avg_ms={p1['avg_duration_ms']}  plans_emitted={p1['plans_emitted']}  "
        f"plans_parse_failed={p1['plans_parse_failed']}"
    )
    print(
        f"Phase 2: tokens in/out={p2['total_tokens_in']}/{p2['total_tokens_out']}  "
        f"avg_ms={p2['avg_duration_ms']}  runs={p2['phase2_runs']}  "
        f"no_ids_emitted={p2['no_ids_emitted']}"
    )
    print()
    print(
        f"R-IDs:  {pa['total_rids_hallucinated']}/{pa['total_rids_extracted']} "
        f"hallucinated ({pa['rid_hallucination_rate_pct']}%)"
    )
    print(
        f"ECs:    {pa['total_ecs_hallucinated']}/{pa['total_ecs_extracted']} "
        f"hallucinated ({pa['ec_hallucination_rate_pct']}%)"
    )
    overall_rate = 0.0
    total = pa["total_rids_extracted"] + pa["total_ecs_extracted"]
    if total:
        overall_rate = round(
            100.0 * (pa["total_rids_hallucinated"] + pa["total_ecs_hallucinated"]) / total,
            1,
        )
    print(f"Overall: {overall_rate}%   →  band: {_threshold_band(overall_rate)}")
    ns = agg.get("nudge_stats", {})
    print(
        f"Nudges fired: {ns.get('total_nudges_fired', 0)}"
        f"  (across {ns.get('prompts_with_nudge', 0)} prompt(s))"
    )
    print(
        f"Step convention adherence: {agg['phase2_stats'].get('step_convention_ok', 0)}"
        f" / {agg['phase2_stats'].get('phase2_runs', 0)} phase-2 runs"
    )
    print()
    print("Per prompt:")
    for row in per_prompt:
        r_bad = sum(1 for r in row["rids"] if not r["verified"])
        e_bad = sum(1 for e in row["ecs"] if not e["verified"])
        nudge_tot = row.get("phase1_nudge_count", 0) + row.get("phase2_nudge_count", 0)
        step_ok = "Y" if row.get("step_convention_ok") else "N"
        print(
            f"  {row['id']:<22} status={row['status']:<20}"
            f" step={step_ok}"
            f" nudges={nudge_tot}"
            f" rids={r_bad}/{len(row['rids'])}"
            f" ecs={e_bad}/{len(row['ecs'])}"
        )

    bad_rids: list[dict] = []
    bad_ecs: list[dict] = []
    for row in per_prompt:
        for r in row["rids"]:
            if not r["verified"] and len(bad_rids) < 3:
                bad_rids.append({"prompt": row["id"], **r})
        for e in row["ecs"]:
            if not e["verified"] and len(bad_ecs) < 3:
                bad_ecs.append({"prompt": row["id"], **e})
    if bad_rids:
        print()
        print("Example hallucinated R-IDs:")
        for r in bad_rids:
            print(f"  {r['id']}  ({r['prompt']}): {r['context'][:140]!r}")
    if bad_ecs:
        print()
        print("Example hallucinated ECs:")
        for e in bad_ecs:
            print(f"  EC {e['id']}  ({e['prompt']}): {e['context'][:140]!r}")


async def _run_all(prompts: list[dict], max_iterations: int) -> list[dict]:
    per_prompt: list[dict] = []
    for i, spec in enumerate(prompts, 1):
        log.info("=== [%d/%d] %s ===", i, len(prompts), spec["id"])
        per_prompt.append(await _run_one(spec, max_iterations))
    return per_prompt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids", type=str, default=None,
        help="comma-separated prompt IDs to run (default: all)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=8,
        help="agent loop cap per turn (default 8)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="explicit output path; default eval/results/pathway_hallucination_baseline_<ts>.json",
    )
    args = parser.parse_args()

    if not PROMPTS_PATH.is_file():
        log.error("prompts.json not found at %s", PROMPTS_PATH)
        return 1
    prompts = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        prompts = [p for p in prompts if p["id"] in wanted]
        if not prompts:
            log.error("no prompts match --ids=%s", args.ids)
            return 1

    per_prompt = asyncio.run(_run_all(prompts, args.max_iterations))
    agg = _aggregate(per_prompt)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.output) if args.output else RESULTS_DIR / f"pathway_hallucination_baseline_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "timestamp_utc": ts,
                "kind": "pathway_hallucination_baseline",
                "flow": "two_turn",
                "tier": "default",
                "phase1_stats": agg["phase1_stats"],
                "phase2_stats": agg["phase2_stats"],
                "pathway_accuracy": agg["pathway_accuracy"],
                "per_prompt": per_prompt,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    log.info("wrote %s", out_path)
    _print_summary(agg, per_prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
