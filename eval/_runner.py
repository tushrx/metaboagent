"""Shared eval-runner glue (Phase 8.2 extraction).

Two pieces are duplicated 3× across the runtime evals:

  1. The "drain run_agent into events + final answer + usage" loop —
     present as `_drain` in eval_demo_mode and `_drain_turn` in
     eval_pathway_hallucination, with 90% identical bodies.
  2. The "make a UTC timestamp, mkdir eval/results, write JSON with
     indent=2" pattern — open-coded inline in three places.

This module owns those two pieces. It deliberately does NOT introduce
a base "Eval" class — each runtime eval has its own scoring shape, and
forcing them through a shared interface would buy nothing.

Anything LLM-related (router selection, tool registry) lives in
`agent/`; this file only orchestrates one turn at a time.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "eval/results"


def timestamp_utc() -> str:
    """Compact UTC timestamp suitable for result filenames (e.g. 20260426T082705Z)."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_result(
    eval_name: str,
    payload: Any,
    *,
    output_path: Path | None = None,
    ts: str | None = None,
) -> Path:
    """Persist an eval result as JSON.

    Default destination is ``eval/results/<eval_name>_<timestamp>.json``.
    Pass ``output_path`` to override (e.g. when the harness exposes a
    --output flag). Pass ``ts`` when the caller already minted a
    timestamp it embedded in the payload — the filename will reuse that
    string instead of generating a fresh one (keeps filename and
    payload field in lockstep).

    Always writes UTF-8, ``indent=2``, with a trailing newline so files
    are diff-friendly under git.
    """
    if output_path is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"{eval_name}_{ts or timestamp_utc()}.json"
    else:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


async def drain_agent_turn(
    messages: Iterable[Any],
    *,
    tier: str = "default",
    max_iterations: int = 6,
) -> tuple[list[dict[str, Any]], str, dict[str, int]]:
    """Run a single agent turn and collect everything an eval might want.

    Returns ``(events, final_answer, usage)`` where:
      events       — every non-token event yielded by ``run_agent``
      final_answer — content of the last ``final_answer`` event, "" if absent
      usage        — {tokens_in, tokens_out, iterations, duration_ms};
                     duration_ms falls back to wall-clock when the
                     ``done`` event reports zero (older agent versions)

    Token events are dropped on the way through — they are noise for
    every consumer we have today (evals score the structured stream, not
    the raw text stream).

    Imports of agent.core are deferred so that lightweight callers (e.g.
    a test that monkeypatches the function) can avoid pulling the whole
    agent stack.
    """
    from agent.core import run_agent  # local import — see docstring

    events: list[dict[str, Any]] = []
    final_answer = ""
    tokens_in = 0
    tokens_out = 0
    duration_ms = 0
    iterations = 0
    t0 = time.perf_counter()

    async for ev in run_agent(
        list(messages),
        tier=tier,
        max_iterations=max_iterations,
    ):
        if ev.get("type") == "token":
            continue
        events.append(ev)
        if ev.get("type") == "final_answer":
            final_answer = ev.get("content") or ""
        if ev.get("type") == "done":
            u = ev.get("usage") or {}
            tokens_in = u.get("tokens_in", 0) or 0
            tokens_out = u.get("tokens_out", 0) or 0
            duration_ms = u.get("ms", 0) or 0
            iterations = u.get("iterations", 0) or 0

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    usage = {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "iterations": iterations,
        "duration_ms": duration_ms or elapsed_ms,
    }
    return events, final_answer, usage
