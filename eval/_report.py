"""Markdown report generator for the unified eval runner.

Reads the run_index emitted by ``eval/run_all.py`` plus the per-eval JSON
artefacts it points to, and produces a single Markdown document suitable
for dropping into the Phase 9 writeup.

Sections:
  1. Executive summary table
  2. Per-eval section (demo_mode, pathway_hallucination, answer_quality,
     structure_extraction)
  3. Reproducibility footer

Honest framing matters here: the report's job is to communicate what was
measured, not to spin numbers. Methodology / known-limit pointers are
linked rather than restated.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval._runner import REPO_ROOT


def _load(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text())


def _eval_row(run_index: dict[str, Any], name: str) -> dict[str, Any] | None:
    for r in run_index.get("evals", []):
        if r.get("name") == name:
            return r
    return None


def _rel(p: Path | str | None) -> str:
    """Repo-relative path string (or '—' if missing)."""
    if not p:
        return "—"
    pp = Path(p)
    try:
        return str(pp.relative_to(REPO_ROOT))
    except ValueError:
        return str(pp)


# ---- demo mode ------------------------------------------------------------


def _section_demo_mode(row: dict[str, Any] | None) -> tuple[str, str]:
    """Return (executive_cell, section_md)."""
    if not row or row.get("skipped"):
        return ("skipped", "## Demo Mode (eval_demo_mode)\n\n_Skipped this run._\n")
    runs = row.get("runs", [])
    if not runs or not runs[0].get("result_json"):
        return ("missing", "## Demo Mode (eval_demo_mode)\n\n_Result JSON missing._\n")
    data = _load(runs[0]["result_json"])
    s = data.get("summary", {})
    total = s.get("total", 0)
    passed = s.get("passed", 0)
    cells: list[str] = []
    cells.append(f"**Score:** {passed}/{total} passed")
    by_cat = s.get("by_category", {})
    rows_md = ["| Category | Passed | Total |", "| --- | ---: | ---: |"]
    for cat, c in by_cat.items():
        rows_md.append(f"| {cat} | {c.get('passed', 0)} | {c.get('total', 0)} |")
    body = "\n".join(rows_md)
    src = _rel(runs[0]["result_json"])
    md = (
        "## Demo Mode (eval_demo_mode)\n\n"
        f"{cells[0]}.\n\n"
        f"{body}\n\n"
        f"_Source: `{src}`_\n"
    )
    exec_cell = f"{passed}/{total}"
    return exec_cell, md


# ---- pathway hallucination -----------------------------------------------


def _section_pathway(row: dict[str, Any] | None) -> tuple[str, str]:
    if not row or row.get("skipped"):
        return ("skipped", "## Pathway Hallucination (eval_pathway_hallucination)\n\n_Skipped this run._\n")
    var_path = row.get("variance_summary")
    if not var_path:
        return ("missing", "## Pathway Hallucination (eval_pathway_hallucination)\n\n_Variance summary missing._\n")
    var = _load(var_path)
    pooled = var.get("pooled", {})
    per_run = var.get("per_run", [])

    # Surface metrics — averaged across runs for the headline.
    total_rids = sum(r.get("rids_extracted", 0) for r in per_run)
    total_hallucinated = sum(r.get("rids_hallucinated", 0) for r in per_run)
    surface_rate = (
        round(100.0 * total_hallucinated / total_rids, 1) if total_rids else 0.0
    )

    # Semantic metrics — pooled across runs.
    eligible = pooled.get("rids_existence_verified_eligible", 0)
    real_but_wrong = pooled.get("rids_real_but_wrong", 0)
    semantic_rate = pooled.get("rids_real_but_wrong_pct", 0.0)
    full_match = pooled.get("rids_fully_matching", 0)

    # Per-prompt grid built from per_rid_detail in the variance summary
    # (no need to re-open the underlying run JSONs).
    per_prompt_grid: dict[str, dict[int, dict[str, int]]] = {}
    for r in var.get("per_rid_detail", []):
        pid = r.get("prompt_id")
        run_n = r.get("run")
        cell = per_prompt_grid.setdefault(pid, {}).setdefault(run_n, {
            "rids": 0, "fully_matches": 0, "neither": 0, "rid_invalid": 0,
        })
        cell["rids"] += 1
        v = r.get("verdict")
        if v in cell:
            cell[v] += 1

    grid_lines = [
        "| Prompt | Run 1 | Run 2 | Run 3 |",
        "| --- | --- | --- | --- |",
    ]
    for pid in sorted(per_prompt_grid.keys()):
        row_parts = [pid]
        for n in (1, 2, 3):
            cell = per_prompt_grid[pid].get(n)
            if not cell:
                row_parts.append("—")
            else:
                row_parts.append(
                    f"{cell['rids']} R-IDs · "
                    f"{cell['fully_matches']}✓ "
                    f"{cell['neither']}✗ "
                    f"{cell['rid_invalid']}? "
                )
        grid_lines.append("| " + " | ".join(row_parts) + " |")

    md = [
        "## Pathway Hallucination (eval_pathway_hallucination)",
        "",
        "**Surface-level (existence verification — IDs that exist in KEGG):**",
        "",
        f"- R-IDs extracted across 3 runs: **{total_rids}**",
        f"- R-IDs flagged as nonexistent: **{total_hallucinated} ({surface_rate}%)**",
        "",
        "**Semantic-level (substrate-relevance verification — IDs that match the cited chemistry):**",
        "",
        f"- R-IDs eligible (existence-verified + step context): **{eligible}**",
        f"- `fully_matches` (substrate AND product align): **{full_match}**",
        f"- `neither` (real ID, unrelated chemistry): **{pooled.get('rids_neither', 0)}**",
        f"- `substrate_only` / `product_only`: **{pooled.get('rids_substrate_only', 0)}** / **{pooled.get('rids_product_only', 0)}**",
        f"- **Real-but-wrong rate: {real_but_wrong}/{eligible} = {semantic_rate}%** "
        f"(band: `{pooled.get('band', '?')}`)",
        "",
        "Existence-checking would have passed all eligible IDs as 'verified'; "
        "substrate-relevance flags the gap. See `docs/phase8-finding.md` for the "
        "methodological argument.",
        "",
        "### Per-prompt R-ID counts and verdicts",
        "",
        *grid_lines,
        "",
        "Legend: `R-IDs · ✓ fully_matches · ✗ neither · ? rid_invalid`",
        "",
        f"_Source: `{_rel(var_path)}`_",
        "",
    ]
    exec_cell = f"{surface_rate}% surface · {semantic_rate}% semantic"
    return exec_cell, "\n".join(md)


# ---- answer quality -------------------------------------------------------


def _section_answer_quality(row: dict[str, Any] | None) -> tuple[str, str]:
    if not row or row.get("skipped"):
        return ("skipped", "## Answer Quality (eval_answer_quality)\n\n_Skipped this run._\n")
    var_path = row.get("variance_summary")
    if not var_path:
        return ("missing", "## Answer Quality (eval_answer_quality)\n\n_Variance summary missing._\n")
    var = _load(var_path)
    agg = var.get("aggregate", {})
    max_score = var.get("max_score", 0)
    median = agg.get("median", 0)
    median_pct = agg.get("median_pct", 0.0)
    min_pct = agg.get("min_pct", 0.0)
    max_pct = agg.get("max_pct", 0.0)
    totals = agg.get("totals_per_run", [])

    by_type = var.get("by_question_type", {})
    type_rows = ["| Question type | Per-run scores | Max | Stable across runs |",
                 "| --- | --- | ---: | :---: |"]
    for t, v in by_type.items():
        scores = v.get("per_run_scores", [])
        stable = "yes" if v.get("stable") else "no"
        type_rows.append(f"| {t} | {scores} | {v.get('max', 0)} | {stable} |")

    pq_rows = ["| Question | Type | Scores per run | Fabrication check |",
               "| --- | --- | --- | :---: |"]
    for pq in var.get("per_question", []):
        scores = pq.get("scores_per_run", [])
        fab = pq.get("fabrication_check_per_run", [])
        fab_str = "fail" if pq.get("fabrication_failed_in_any_run") else "pass"
        pq_rows.append(f"| {pq.get('id')} | {pq.get('type')} | {scores}/{pq.get('max')} | {fab_str} ({fab}) |")

    md = [
        "## Answer Quality (eval_answer_quality)",
        "",
        f"**3-run aggregate:** median **{median}/{max_score} ({median_pct}%)**, "
        f"range {min_pct}%–{max_pct}%, totals per run {totals}.",
        "",
        "Methodology and judge details: `docs/eval-methodology.md`.",
        "",
        "### By question type",
        "",
        *type_rows,
        "",
        "### Per-question",
        "",
        *pq_rows,
        "",
        f"_Source: `{_rel(var_path)}`_",
        "",
    ]
    exec_cell = f"{median}/{max_score} ({median_pct}%)"
    return exec_cell, "\n".join(md)


# ---- structure extraction -------------------------------------------------


def _section_structure(row: dict[str, Any] | None) -> tuple[str, str]:
    if not row or row.get("skipped"):
        return ("skipped", "## Structure Extraction (eval_structure_extraction)\n\n_Skipped this run._\n")
    runs = row.get("runs", [])
    if not runs or not runs[0].get("result_json"):
        return ("missing", "## Structure Extraction (eval_structure_extraction)\n\n_Result JSON missing._\n")
    data = _load(runs[0]["result_json"])
    s = data.get("summary", {})
    overall = s.get("overall", {})
    n = s.get("overall_n", 0)
    # "Correct" = PASS_STRICT (canonical SMILES match) + PASS_INCHI (same
    # molecule, different SMILES form). PARTIAL/FAIL fall short.
    pass_strict = overall.get("PASS_STRICT", 0)
    pass_inchi = overall.get("PASS_INCHI", 0)
    correct = pass_strict + pass_inchi
    pct = round(100.0 * correct / n, 1) if n else 0.0

    bucket_lines = ["| Bucket | Count | % |", "| --- | ---: | ---: |"]
    for b, c in overall.items():
        b_pct = round(100.0 * c / n, 1) if n else 0.0
        bucket_lines.append(f"| {b} | {c} | {b_pct}% |")

    by_diff = s.get("by_difficulty", {})
    diff_lines = ["| Difficulty | Total | Correct | Bucket distribution |",
                  "| --- | ---: | ---: | --- |"]
    for d, row_d in by_diff.items():
        total_d = sum(row_d.values())
        correct_d = row_d.get("PASS_STRICT", 0) + row_d.get("PASS_INCHI", 0)
        dist = ", ".join(f"{k}={v}" for k, v in row_d.items() if v)
        diff_lines.append(f"| {d} | {total_d} | {correct_d} | {dist} |")

    md = [
        "## Structure Extraction (eval_structure_extraction)",
        "",
        f"**Overall:** {correct}/{n} correct ({pct}%) on the 20-structure test set.",
        "",
        "Honest framing: this is a **research finding**, not a product feature. "
        "The E4B vision encoder is a baseline; production use would route image "
        "→ SMILES through DECIMER or a domain-tuned model.",
        "",
        "### Bucket distribution",
        "",
        *bucket_lines,
        "",
        "### By difficulty",
        "",
        *diff_lines,
        "",
        f"_Source: `{_rel(runs[0]['result_json'])}`_",
        "",
    ]
    exec_cell = f"{correct}/{n} ({pct}%)"
    return exec_cell, "\n".join(md)


# ---- top-level ------------------------------------------------------------


def generate_report(run_index: dict[str, Any], out_path: Path,
                    *, index_path: Path | None = None) -> Path:
    sections = [
        ("Demo mode behavior", _section_demo_mode(_eval_row(run_index, "demo_mode"))),
        ("Pathway hallucination", _section_pathway(_eval_row(run_index, "pathway_hallucination"))),
        ("Answer quality (3-run median)", _section_answer_quality(_eval_row(run_index, "answer_quality"))),
        ("Structure extraction", _section_structure(_eval_row(run_index, "structure_extraction"))),
    ]

    summary_lines = [
        "| Eval | Score | Source |",
        "| --- | --- | --- |",
    ]
    for label, (exec_cell, _md) in sections:
        # find the row to grab a source pointer for the summary table
        source = "—"
        if label.startswith("Demo"):
            r = _eval_row(run_index, "demo_mode")
            if r and not r.get("skipped") and r.get("runs"):
                source = _rel(r["runs"][0].get("result_json"))
        elif label.startswith("Pathway"):
            r = _eval_row(run_index, "pathway_hallucination")
            if r:
                source = _rel(r.get("variance_summary"))
        elif label.startswith("Answer"):
            r = _eval_row(run_index, "answer_quality")
            if r:
                source = _rel(r.get("variance_summary"))
        elif label.startswith("Structure"):
            r = _eval_row(run_index, "structure_extraction")
            if r and not r.get("skipped") and r.get("runs"):
                source = _rel(r["runs"][0].get("result_json"))
        summary_lines.append(f"| {label} | {exec_cell} | `{source}` |")

    body_sections = "\n\n".join(md for _label, (_cell, md) in sections)

    md = [
        "# MetaboAgent — Eval Report",
        "",
        f"- Generated: **{run_index.get('timestamp_utc', '?')}**",
        f"- Repo SHA: **{run_index.get('git_sha', '?')}**",
        f"- Total runtime: **{run_index.get('elapsed_total_s', 0):.1f}s**",
        f"- Run index: `{_rel(index_path) if index_path else '—'}`",
        "",
        "## Executive Summary",
        "",
        *summary_lines,
        "",
        body_sections,
        "## Reproducibility",
        "",
        "Run all evals: `python -m eval all --report`",
        "",
        "Individual eval scripts under `eval/eval_*.py`. Test infrastructure under `tests/`.",
        "",
        "Required environment: `DEMO_MODE=1`, `PYTHONPATH=<repo root>`, "
        "`EMBEDDING_DEVICE=cuda:3` (or any GPU not occupied by vLLM — see "
        "`docs/troubleshooting.md`).",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(md), encoding="utf-8")
    return out_path
