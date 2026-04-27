"""3-run variance aggregation for the multi-run evals.

The pathway-hallucination and answer-quality evals are each run three
times by ``eval/run_all.py`` to surface variance. This module turns those
three per-run JSON artefacts into a single ``*_variance_3run.json``
summary that the Markdown report generator reads.

Logic is identical to the ad-hoc /tmp/{ph,aq}_save_variance.py scripts
used in Phase 8.3.A/B; lifted here so the unified runner is the only
place that needs to know how to compute variance.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from eval._runner import REPO_ROOT, RESULTS_DIR


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


# ---- pathway hallucination -----------------------------------------------


def aggregate_pathway_hallucination_variance(run_paths: list[Path]) -> Path:
    """Read the 3 per-run JSONs and write the variance summary.

    Returns the summary file path.
    """
    runs = [(i + 1, p, json.loads(p.read_text())) for i, p in enumerate(run_paths)]
    per_run = []
    for n, path, d in runs:
        sr = d.get("rid_substrate_relevance", {})
        pa = d.get("pathway_accuracy", {})
        per_run.append({
            "run": n,
            "path": path.name,
            "timestamp_utc": d.get("timestamp_utc"),
            "phase1_plans_emitted": d.get("phase1_stats", {}).get("plans_emitted", 0),
            "phase1_plans_parse_failed": d.get("phase1_stats", {}).get("plans_parse_failed", 0),
            "phase2_runs": d.get("phase2_stats", {}).get("phase2_runs", 0),
            "rids_extracted": pa.get("total_rids_extracted", 0),
            "rids_hallucinated": pa.get("total_rids_hallucinated", 0),
            "ecs_extracted": pa.get("total_ecs_extracted", 0),
            "ecs_hallucinated": pa.get("total_ecs_hallucinated", 0),
            "rids_eligible": sr.get("rids_eligible_for_substrate_check", 0),
            "rids_no_step_context": sr.get("rids_no_step_context", 0),
            "rids_fully_matching": sr.get("rids_fully_matching", 0),
            "rids_substrate_only": sr.get("rids_substrate_only", 0),
            "rids_product_only": sr.get("rids_product_only", 0),
            "rids_neither": sr.get("rids_neither", 0),
            "rids_rid_invalid": sr.get("rids_rid_invalid", 0),
            "rids_real_but_wrong": sr.get("rids_real_but_wrong", 0),
            "rids_real_but_wrong_pct": sr.get("rids_real_but_wrong_pct", 0.0),
            "rids_fully_matching_pct": sr.get("rids_fully_matching_pct", 0.0),
            "rids_substrate_relevant_pct": sr.get("rids_substrate_relevant_pct", 0.0),
        })

    pool_full = sum(r["rids_fully_matching"] for r in per_run)
    pool_sub = sum(r["rids_substrate_only"] for r in per_run)
    pool_prod = sum(r["rids_product_only"] for r in per_run)
    pool_nei = sum(r["rids_neither"] for r in per_run)
    pool_inv = sum(r["rids_rid_invalid"] for r in per_run)
    pool_eligible = sum(r["rids_eligible"] for r in per_run)
    pool_existing_eligible = sum(
        d.get("rid_substrate_relevance", {}).get("rids_existence_verified_eligible", 0)
        for _, _, d in runs
    )
    pool_real_but_wrong = pool_existing_eligible - pool_full

    pooled = {
        "rids_eligible": pool_eligible,
        "rids_existence_verified_eligible": pool_existing_eligible,
        "rids_fully_matching": pool_full,
        "rids_substrate_only": pool_sub,
        "rids_product_only": pool_prod,
        "rids_neither": pool_nei,
        "rids_rid_invalid": pool_inv,
        "rids_real_but_wrong": pool_real_but_wrong,
        "rids_fully_matching_pct": _pct(pool_full, pool_eligible),
        "rids_real_but_wrong_pct": _pct(pool_real_but_wrong, pool_existing_eligible),
    }
    if pooled["rids_real_but_wrong_pct"] < 10.0:
        band = "<10%"
    elif pooled["rids_real_but_wrong_pct"] <= 30.0:
        band = "10-30%"
    else:
        band = ">30%"
    pooled["band"] = band

    per_rid_rows: list[dict[str, Any]] = []
    for n, _path, d in runs:
        for p in d.get("per_prompt", []):
            for rid_row in p.get("rids", []):
                per_rid_rows.append({
                    "run": n,
                    "prompt_id": p["id"],
                    "rid": rid_row["id"],
                    "verified": rid_row.get("verified"),
                    "verdict": rid_row.get("verdict"),
                    "claimed_substrates": rid_row.get("claimed_substrates", []),
                    "claimed_products": rid_row.get("claimed_products", []),
                    "kegg_substrates": rid_row.get("kegg_substrates", []),
                    "kegg_products": rid_row.get("kegg_products", []),
                })

    summary = {
        "kind": "pathway_hallucination_variance_3run",
        "n_runs": len(runs),
        "per_run": per_run,
        "pooled": pooled,
        "per_rid_detail": per_rid_rows,
    }
    out_path = RESULTS_DIR / "pathway_hallucination_variance_3run.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    return out_path


# ---- answer quality -------------------------------------------------------


def aggregate_answer_quality_variance(run_paths: list[Path]) -> Path:
    questions_path = REPO_ROOT / "eval/scenarios/answer_quality/questions.json"
    questions = json.loads(questions_path.read_text())
    qtype = {q["id"]: q["question_type"] for q in questions}
    rubric = {q["id"]: q["rubric"] for q in questions}

    runs = []
    for i, p in enumerate(run_paths):
        d = json.loads(p.read_text())
        d["_path"] = p.name
        runs.append(d)

    totals = [r["aggregate"]["total_score"] for r in runs]
    pcts = [r["aggregate"]["pct"] for r in runs]
    max_score = runs[0]["aggregate"]["max_score"]

    by_id: dict[str, list[dict]] = {}
    for r in runs:
        for pq in r["per_question"]:
            by_id.setdefault(pq["id"], []).append(pq)

    per_question = []
    for qid, pqs in by_id.items():
        rb = rubric[qid]
        n_points = len(rb)
        flips = []
        for j in range(n_points):
            vals = [pqs[i]["rubric_breakdown"][j] for i in range(len(pqs))]
            if len(set(vals)) > 1:
                flips.append({
                    "point_idx": j + 1,
                    "point": rb[j]["point"],
                    "values_per_run": vals,
                })
        fabrication_idx = n_points - 1
        fab_vals = [pqs[i]["rubric_breakdown"][fabrication_idx] for i in range(len(pqs))]
        per_question.append({
            "id": qid,
            "type": qtype[qid],
            "scores_per_run": [pq["score"] for pq in pqs],
            "max": pqs[0]["max"],
            "flips": flips,
            "fabrication_check_per_run": fab_vals,
            "fabrication_failed_in_any_run": not all(fab_vals),
        })

    by_type: dict[str, dict[str, Any]] = {}
    for r in runs:
        per_run_local: dict[str, tuple[int, int]] = {}
        for pq in r["per_question"]:
            t = qtype[pq["id"]]
            s, m = per_run_local.get(t, (0, 0))
            per_run_local[t] = (s + pq["score"], m + pq["max"])
        for t, (s, m) in per_run_local.items():
            by_type.setdefault(t, {"per_run_scores": [], "max": m})
            by_type[t]["per_run_scores"].append(s)
    for t, v in by_type.items():
        v["stable"] = len(set(v["per_run_scores"])) == 1

    summary = {
        "kind": "answer_quality_variance_3run",
        "judge_model": runs[0]["judge_model"],
        "n_questions": runs[0]["n_questions"],
        "max_score": max_score,
        "runs": [
            {"path": r["_path"], "timestamp_utc": r["timestamp_utc"],
             "total_score": r["aggregate"]["total_score"], "pct": r["aggregate"]["pct"]}
            for r in runs
        ],
        "aggregate": {
            "totals_per_run": totals,
            "pcts_per_run": pcts,
            "min": min(totals),
            "median": statistics.median(totals),
            "max": max(totals),
            "min_pct": min(pcts),
            "median_pct": statistics.median(pcts),
            "max_pct": max(pcts),
        },
        "by_question_type": by_type,
        "per_question": per_question,
    }
    out_path = RESULTS_DIR / "answer_quality_variance_3run.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    return out_path
