"""Unified eval runner — `python -m eval ...`.

Orchestrates the four runtime evals (demo_mode, pathway_hallucination,
answer_quality, structure_extraction) so one command produces every
artefact the Phase 9 writeup will reference. Each eval still has its own
``eval/eval_*.py`` script — this module dispatches them via subprocess
(for failure isolation and clean resource cleanup) and, for the two evals
we measure with 3-run variance, aggregates the resulting JSON files into
a ``*_variance_3run.json`` summary.

Subcommands:
  all   — run every (or filtered) eval; optionally emit a Markdown report
  list  — print the available eval names

The runner expects ``DEMO_MODE=1`` and ``PYTHONPATH=<repo root>`` in the
caller's env (the same as the standalone scripts). Live-fetch evals that
require DEMO_MODE are skipped with a clear warning when it isn't set.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval._runner import REPO_ROOT, RESULTS_DIR, timestamp_utc
from eval._variance import (
    aggregate_answer_quality_variance,
    aggregate_pathway_hallucination_variance,
)

log = logging.getLogger(__name__)


@dataclass
class EvalSpec:
    name: str
    script: str           # filename under eval/
    variance_runs: int    # 1 = run once, 3 = run thrice and aggregate
    requires_demo: bool
    extra_args: list[str]
    result_prefix: str    # the <prefix>_<ts>.json the eval writes
    variance_aggregator: str | None = None  # name in eval._variance, or None


# Ordered cheap → expensive (Phase 8.4 spec §2).
EVALS: list[EvalSpec] = [
    EvalSpec(
        name="demo_mode",
        script="eval_demo_mode.py",
        variance_runs=1,
        requires_demo=True,
        extra_args=[],
        result_prefix="demo_mode",
    ),
    EvalSpec(
        name="pathway_hallucination",
        script="eval_pathway_hallucination.py",
        variance_runs=3,
        requires_demo=True,
        extra_args=["--max-iterations=8"],
        result_prefix="pathway_hallucination_baseline",
        variance_aggregator="pathway_hallucination",
    ),
    EvalSpec(
        name="answer_quality",
        script="eval_answer_quality.py",
        variance_runs=3,
        requires_demo=True,
        extra_args=[],
        result_prefix="answer_quality",
        variance_aggregator="answer_quality",
    ),
    EvalSpec(
        name="structure_extraction",
        script="eval_structure_extraction.py",
        variance_runs=1,
        requires_demo=False,
        extra_args=[],
        result_prefix="structure_extraction",
    ),
]


def _spec_by_name(name: str) -> EvalSpec | None:
    for s in EVALS:
        if s.name == name:
            return s
    return None


def _run_subprocess(cmd: list[str], log_path: Path, env: dict[str, str]) -> tuple[int, float]:
    """Run a subprocess, tee output to log_path, return (rc, elapsed_s)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with open(log_path, "w", encoding="utf-8") as f:
        rc = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, env=env)
    return rc, time.perf_counter() - t0


_TS_RE = re.compile(r"\b(2\d{3}[01]\d[0-3]\dT[0-2]\d[0-5]\d[0-5]\dZ)\b")


def _extract_result_path(log_path: Path, prefix: str) -> Path | None:
    """Find an ``eval/results/<prefix>_<ts>.json`` mention in the log."""
    if not log_path.is_file():
        return None
    txt = log_path.read_text(errors="replace")
    m = re.search(rf"({re.escape(prefix)}_[\dTZ]+\.json)", txt)
    if not m:
        return None
    p = RESULTS_DIR / m.group(1)
    return p if p.exists() else None


def _rename_for_run(path: Path, eval_name: str, run_idx: int, prefix: str) -> Path:
    """``<prefix>_<ts>.json`` → ``<eval_name>_run_<idx>_<ts>.json``.

    Preserves the timestamp tail so files sort chronologically. No-op if
    the expected source doesn't exist (caller has already logged a
    warning).
    """
    if not path.is_file():
        return path
    new_name = path.name.replace(prefix, f"{eval_name}_run_{run_idx}", 1)
    new_path = path.parent / new_name
    if path != new_path:
        path.rename(new_path)
    return new_path


def _run_eval(spec: EvalSpec, log_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    """Run a single eval (1× or 3× per its variance_runs) and aggregate.

    Returns a row describing what happened: per-run paths, return codes,
    elapsed seconds, and the variance summary path when applicable.
    """
    if spec.requires_demo and env.get("DEMO_MODE") != "1":
        log.warning("skipping %s: DEMO_MODE=1 required", spec.name)
        return {"name": spec.name, "skipped": True, "reason": "DEMO_MODE!=1"}

    script_path = REPO_ROOT / "eval" / spec.script
    runs: list[dict[str, Any]] = []
    started = time.perf_counter()
    for i in range(1, spec.variance_runs + 1):
        log_path = log_dir / f"{spec.name}_run_{i}.log"
        cmd = [sys.executable, "-u", str(script_path), *spec.extra_args]
        log.info("[%s] run %d/%d → %s", spec.name, i, spec.variance_runs, log_path.name)
        rc, elapsed = _run_subprocess(cmd, log_path, env)
        out_path = _extract_result_path(log_path, spec.result_prefix)
        if out_path is None:
            log.warning("[%s] run %d: no result JSON parsed from log", spec.name, i)
        renamed = _rename_for_run(out_path, spec.name, i, spec.result_prefix) if out_path else None
        runs.append({
            "run_idx": i,
            "rc": rc,
            "elapsed_s": round(elapsed, 1),
            "log": str(log_path),
            "result_json": str(renamed) if renamed else None,
        })
        if rc != 0:
            log.warning("[%s] run %d exited rc=%s — see %s", spec.name, i, rc, log_path)

    row: dict[str, Any] = {
        "name": spec.name,
        "skipped": False,
        "variance_runs": spec.variance_runs,
        "elapsed_total_s": round(time.perf_counter() - started, 1),
        "runs": runs,
    }

    if spec.variance_aggregator and all(r["result_json"] for r in runs):
        try:
            if spec.variance_aggregator == "pathway_hallucination":
                summary_path = aggregate_pathway_hallucination_variance(
                    [Path(r["result_json"]) for r in runs]
                )
            elif spec.variance_aggregator == "answer_quality":
                summary_path = aggregate_answer_quality_variance(
                    [Path(r["result_json"]) for r in runs]
                )
            else:
                summary_path = None
            row["variance_summary"] = str(summary_path) if summary_path else None
        except Exception as e:
            log.exception("[%s] variance aggregation failed: %s", spec.name, e)
            row["variance_summary_error"] = str(e)

    return row


def _resolve_specs(only: list[str] | None, skip: list[str] | None) -> list[EvalSpec]:
    if only:
        out: list[EvalSpec] = []
        for n in only:
            s = _spec_by_name(n)
            if s is None:
                raise SystemExit(f"unknown eval: {n!r} (available: {[s.name for s in EVALS]})")
            out.append(s)
        return out
    skipset = set(skip or [])
    bad = skipset - {s.name for s in EVALS}
    if bad:
        raise SystemExit(f"unknown eval(s) in --skip: {sorted(bad)}")
    return [s for s in EVALS if s.name not in skipset]


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def cmd_all(args: argparse.Namespace) -> int:
    ts = timestamp_utc()
    log_dir = REPO_ROOT / f"logs/eval_runs/{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)

    specs = _resolve_specs(args.only, args.skip)
    log.info("running %d eval(s): %s", len(specs), [s.name for s in specs])

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO_ROOT))

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for spec in specs:
        rows.append(_run_eval(spec, log_dir, env))
    total_elapsed = round(time.perf_counter() - started, 1)

    run_index = {
        "kind": "eval_run_index",
        "timestamp_utc": ts,
        "git_sha": _git_sha(),
        "log_dir": str(log_dir),
        "elapsed_total_s": total_elapsed,
        "evals": rows,
    }
    index_path = RESULTS_DIR / f"eval_run_index_{ts}.json"
    index_path.write_text(json.dumps(run_index, indent=2) + "\n", encoding="utf-8")
    log.info("wrote run index → %s", index_path)

    if args.report:
        from eval._report import generate_report
        report_path = Path(args.output) if args.output else (
            RESULTS_DIR / f"full_report_{ts}.md"
        )
        generate_report(run_index, report_path, index_path=index_path)
        log.info("wrote report → %s", report_path)

    print()
    print(f"=== eval run {ts} done in {total_elapsed:.1f}s ===")
    for r in rows:
        if r.get("skipped"):
            print(f"  {r['name']:30s} SKIPPED ({r['reason']})")
            continue
        rcs = [run["rc"] for run in r["runs"]]
        ok = all(rc == 0 for rc in rcs)
        rc_str = ",".join(str(rc) for rc in rcs)
        print(f"  {r['name']:30s} {'PASS' if ok else 'FAIL'}  "
              f"runs={r['variance_runs']} rc=[{rc_str}] {r['elapsed_total_s']}s")
    return 0 if all(
        r.get("skipped") or all(run["rc"] == 0 for run in r["runs"])
        for r in rows
    ) else 1


def cmd_list(_args: argparse.Namespace) -> int:
    print("Available evals:")
    for s in EVALS:
        runs = "1× run" if s.variance_runs == 1 else f"{s.variance_runs}× runs (variance)"
        demo = " (DEMO_MODE)" if s.requires_demo else ""
        print(f"  {s.name:30s} {runs}{demo}")
    return 0


def cli(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_all = sub.add_parser("all", help="run every (or filtered) eval")
    p_all.add_argument("--report", action="store_true",
                       help="emit a Markdown report at the end")
    p_all.add_argument("--output", type=str, default=None,
                       help="explicit Markdown path (default eval/results/full_report_<ts>.md)")
    p_all.add_argument("--skip", action="append", default=[],
                       help="skip an eval by name; repeatable")
    p_all.add_argument("--only", action="append", default=[],
                       help="run only the given eval(s); repeatable")
    p_all.set_defaults(fn=cmd_all)

    p_list = sub.add_parser("list", help="print the available eval names")
    p_list.set_defaults(fn=cmd_list)

    ns = parser.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    sys.exit(cli())
