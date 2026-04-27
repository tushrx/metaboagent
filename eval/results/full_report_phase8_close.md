# MetaboAgent — Eval Report

- Generated: **20260427T080053Z**
- Repo SHA: **59b086c**
- Total runtime: **703.2s**
- Run index: `eval/results/eval_run_index_20260427T080053Z.json`

## Executive Summary

| Eval | Score | Source |
| --- | --- | --- |
| Demo mode behavior | 5/5 | `eval/results/demo_mode_run_1_20260427T080115Z.json` |
| Pathway hallucination | 0.0% surface · 100.0% semantic | `eval/results/pathway_hallucination_variance_3run.json` |
| Answer quality (3-run median) | 29/32 (90.6%) | `eval/results/answer_quality_variance_3run.json` |
| Structure extraction | 1/20 (5.0%) | `eval/results/structure_extraction_run_1_20260427T081235Z.json` |

## Demo Mode (eval_demo_mode)

**Score:** 5/5 passed.

| Category | Passed | Total |
| --- | ---: | ---: |
| live_with_fallback | 3 | 3 |
| live_no_fallback | 1 | 1 |
| no_tool | 1 | 1 |

_Source: `eval/results/demo_mode_run_1_20260427T080115Z.json`_


## Pathway Hallucination (eval_pathway_hallucination)

**Surface-level (existence verification — IDs that exist in KEGG):**

- R-IDs extracted across 3 runs: **5**
- R-IDs flagged as nonexistent: **0 (0.0%)**

**Semantic-level (substrate-relevance verification — IDs that match the cited chemistry):**

- R-IDs eligible (existence-verified + step context): **5**
- `fully_matches` (substrate AND product align): **0**
- `neither` (real ID, unrelated chemistry): **4**
- `substrate_only` / `product_only`: **1** / **0**
- **Real-but-wrong rate: 5/5 = 100.0%** (band: `>30%`)

Existence-checking would have passed all eligible IDs as 'verified'; substrate-relevance flags the gap. See `docs/phase8-finding.md` for the methodological argument.

### Per-prompt R-ID counts and verdicts

| Prompt | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| lycopene_ecoli | — | 3 R-IDs · 0✓ 2✗ 0?  | — |
| vanillin_ferulic | — | 1 R-IDs · 0✓ 1✗ 0?  | 1 R-IDs · 0✓ 1✗ 0?  |

Legend: `R-IDs · ✓ fully_matches · ✗ neither · ? rid_invalid`

_Source: `eval/results/pathway_hallucination_variance_3run.json`_


## Answer Quality (eval_answer_quality)

**3-run aggregate:** median **29/32 (90.6%)**, range 81.2%–96.9%, totals per run [26, 29, 31].

Methodology and judge details: `docs/eval-methodology.md`.

### By question type

| Question type | Per-run scores | Max | Stable across runs |
| --- | --- | ---: | :---: |
| mechanism | [8, 8, 10] | 10 | no |
| pathway_design | [7, 10, 10] | 11 | no |
| comparison | [6, 6, 6] | 6 | yes |
| lookup | [5, 5, 5] | 5 | yes |

### Per-question

| Question | Type | Scores per run | Fabrication check |
| --- | --- | --- | :---: |
| Q1_acetyl_coa_tca | mechanism | [3, 4, 5]/5 | fail ([True, False, True]) |
| Q2_nadh_etc | mechanism | [5, 4, 5]/5 | pass ([True, True, True]) |
| Q3_resveratrol_ecoli | pathway_design | [6, 6, 6]/6 | pass ([True, True, True]) |
| Q4_lycopene_bottleneck | pathway_design | [1, 4, 4]/5 | pass ([True, True, True]) |
| Q5_mep_vs_mva | comparison | [6, 6, 6]/6 | pass ([True, True, True]) |
| Q6_kegg_c00022 | lookup | [5, 5, 5]/5 | pass ([True, True, True]) |

_Source: `eval/results/answer_quality_variance_3run.json`_


## Structure Extraction (eval_structure_extraction)

**Overall:** 1/20 correct (5.0%) on the 20-structure test set.

Honest framing: this is a **research finding**, not a product feature. The E4B vision encoder is a baseline; production use would route image → SMILES through DECIMER or a domain-tuned model.

### Bucket distribution

| Bucket | Count | % |
| --- | ---: | ---: |
| PASS_STRICT | 1 | 5.0% |
| PASS_INCHI | 0 | 0.0% |
| PARTIAL | 14 | 70.0% |
| FAIL | 5 | 25.0% |

### By difficulty

| Difficulty | Total | Correct | Bucket distribution |
| --- | ---: | ---: | --- |
| simple | 5 | 1 | PASS_STRICT=1, PARTIAL=4 |
| medium | 8 | 0 | PARTIAL=6, FAIL=2 |
| hard | 5 | 0 | PARTIAL=3, FAIL=2 |
| very_hard | 2 | 0 | PARTIAL=1, FAIL=1 |

_Source: `eval/results/structure_extraction_run_1_20260427T081235Z.json`_

## Reproducibility

Run all evals: `python -m eval all --report`

Individual eval scripts under `eval/eval_*.py`. Test infrastructure under `tests/`.

Required environment: `DEMO_MODE=1`, `PYTHONPATH=<repo root>`, `EMBEDDING_DEVICE=cuda:3` (or any GPU not occupied by vLLM — see `docs/troubleshooting.md`).
