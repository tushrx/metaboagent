"""Phase 7.3 — warm the demo cache.

Reads ``eval/scenarios/demo_queries.json``, POSTs each query at a
*non*-DEMO_MODE backend, captures every (tool_call, tool_result) pair
plus the final_answer, and writes the per-query cache files under
``data/demo_cache/<id>/``:

    request.json       the prompt + metadata as it was sent
    tool_calls.json    list of {tool_name, args, result} pairs in call order
    final_answer.txt   the assistant's final answer (text only)

For two-phase pathway-design queries (``phase2_followup`` set), the
warmer drives a second turn so the deep-dive's tool calls also land in
the cache. The agent's loop is bounded the same way the eval is.

The script REFUSES to run if the backend reports ``demo_mode: true``
on /health — warming with stubbed live tools is meaningless.

Run:
    python3 scripts/warm_demo_cache.py
    python3 scripts/warm_demo_cache.py --skip-existing
    python3 scripts/warm_demo_cache.py --query-id mevalonate_ecoli
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = REPO_ROOT / "eval/scenarios/demo_queries.json"
CACHE_ROOT = REPO_ROOT / "data/demo_cache"

DEFAULT_BACKEND = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT_S = 240.0  # one query — generous to cover deep-dive turns
DEFAULT_MAX_ITERATIONS = 6

log = logging.getLogger("warm_demo_cache")


def _load_queries() -> list[dict[str, Any]]:
    with SCENARIOS_PATH.open() as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{SCENARIOS_PATH} must be a JSON array")
    return data


def _refuse_if_demo_mode(backend_url: str) -> None:
    """Warming uses live tools — running against a DEMO_MODE backend
    would just cache stubs back into the cache. Hard fail."""
    r = httpx.get(f"{backend_url}/health", timeout=10.0)
    r.raise_for_status()
    body = r.json()
    if body.get("demo_mode") is True:
        raise SystemExit(
            f"Refusing to warm against {backend_url} — /health reports "
            f"demo_mode: true. Restart the backend WITHOUT DEMO_MODE=1."
        )


def _stream_chat(
    backend_url: str,
    messages: list[dict[str, Any]],
    *,
    tier: str = "default",
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[list[dict[str, Any]], str]:
    """Drive POST /chat as SSE and return (events, final_answer)."""
    payload = {
        "messages": messages,
        "tier": tier,
        "max_iterations": max_iterations,
        "temperature": 0.2,
    }
    events: list[dict[str, Any]] = []
    final_answer = ""
    with httpx.stream(
        "POST",
        f"{backend_url}/chat",
        json=payload,
        timeout=timeout_s,
    ) as r:
        r.raise_for_status()
        for raw in r.iter_lines():
            if not raw or not raw.startswith("data: "):
                continue
            try:
                ev = json.loads(raw[len("data: "):])
            except json.JSONDecodeError:
                log.warning("dropping unparseable SSE line: %r", raw[:120])
                continue
            if ev.get("type") == "token":
                continue
            events.append(ev)
            if ev.get("type") == "final_answer":
                final_answer = ev.get("content") or ""
    return events, final_answer


def _pair_tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk the event log, pair each tool_call with the matching
    tool_result by id, and emit cache entries in call order."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for ev in events:
        t = ev.get("type")
        if t == "tool_call":
            tid = ev.get("id")
            if not tid:
                continue
            order.append(tid)
            by_id[tid] = {
                "tool_name": ev.get("name"),
                "args": ev.get("args") or {},
                "result": None,
            }
        elif t == "tool_result":
            tid = ev.get("id")
            if tid in by_id:
                content = ev.get("content")
                # tool result content is a JSON string on the wire
                by_id[tid]["result"] = content
    out: list[dict[str, Any]] = []
    for tid in order:
        entry = by_id.get(tid)
        if entry is None or entry["result"] is None:
            # tool errored before producing a result — skip; the cache
            # is for replayable successes only.
            continue
        out.append(entry)
    return out


def _warm_one(
    backend_url: str,
    q: dict[str, Any],
    *,
    max_iterations: int,
    timeout_s: float,
) -> dict[str, Any]:
    pid = q["id"]
    out_dir = CACHE_ROOT / pid
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("[%s] phase 1: %s", pid, q["prompt"])
    t0 = time.perf_counter()
    messages = [{"role": "user", "content": q["prompt"]}]
    events1, final1 = _stream_chat(
        backend_url, messages, tier=q.get("expected_tier", "default"),
        max_iterations=max_iterations, timeout_s=timeout_s,
    )
    pairs = _pair_tool_calls(events1)
    final_answer_combined = final1

    followup = q.get("phase2_followup")
    if followup:
        log.info("[%s] phase 2: follow-up %r", pid, followup)
        # Re-send the full conversation: the original prompt, the
        # phase-1 final_answer as the assistant turn, and the follow-up.
        messages2 = [
            {"role": "user", "content": q["prompt"]},
            {"role": "assistant", "content": final1},
            {"role": "user", "content": followup},
        ]
        events2, final2 = _stream_chat(
            backend_url, messages2, tier=q.get("expected_tier", "default"),
            max_iterations=max_iterations, timeout_s=timeout_s,
        )
        pairs.extend(_pair_tool_calls(events2))
        # Concatenate so the cached final_answer.txt covers both turns.
        final_answer_combined = (
            f"{final1}\n\n--- phase 2 (followup={followup!r}) ---\n\n{final2}"
        )

    elapsed = time.perf_counter() - t0
    request_obj = {
        "id": pid,
        "category": q.get("category"),
        "prompt": q["prompt"],
        "phase2_followup": followup,
        "expected_tier": q.get("expected_tier", "default"),
        "warmed_seconds": round(elapsed, 2),
    }

    (out_dir / "request.json").write_text(
        json.dumps(request_obj, indent=2, ensure_ascii=False)
    )
    (out_dir / "tool_calls.json").write_text(
        json.dumps(pairs, indent=2, ensure_ascii=False)
    )
    (out_dir / "final_answer.txt").write_text(final_answer_combined)

    return {
        "id": pid,
        "tool_calls": len(pairs),
        "elapsed_s": round(elapsed, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--query-id", help="Warm only this query id (for iterating).",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS,
    )
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s: %(message)s",
    )

    _refuse_if_demo_mode(args.backend_url)
    queries = _load_queries()
    if args.query_id:
        queries = [q for q in queries if q["id"] == args.query_id]
        if not queries:
            log.error("no query with id %r", args.query_id)
            return 2

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    t_start = time.perf_counter()
    for q in queries:
        out_dir = CACHE_ROOT / q["id"]
        if args.skip_existing and (out_dir / "tool_calls.json").exists():
            log.info("[%s] skip (cache exists)", q["id"])
            continue
        try:
            row = _warm_one(
                args.backend_url, q,
                max_iterations=args.max_iterations,
                timeout_s=args.timeout_s,
            )
            log.info(
                "[%s]  done: %d tool calls cached in %.2fs",
                q["id"], row["tool_calls"], row["elapsed_s"],
            )
            summaries.append(row)
        except Exception as e:  # noqa: BLE001
            log.error("[%s] FAILED: %s", q["id"], e)
            summaries.append({"id": q["id"], "error": str(e)})

    total = time.perf_counter() - t_start
    total_calls = sum(s.get("tool_calls", 0) for s in summaries)
    log.info(
        "---\nWarmed %d queries with %d total cached tool calls in %.1fs",
        len(summaries), total_calls, total,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
