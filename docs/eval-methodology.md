# Eval Methodology Notes

Companion to `docs/eval-inventory.md`. The inventory catalogs *what* each
eval measures; this file documents *how* the measurements are constructed
and what they can and cannot tell us. Add a section per eval whose scoring
involves judgment calls (LLM judges, rubrics, named verdict buckets).

---

## Answer-quality rubric eval (Phase 8.3.A)

### Score model

Six biochem questions × 4–6 rubric points each = 32 scoreable points.
Each rubric point is independently scored True/False by an LLM judge
against the agent's free-text answer; the question's score is the sum
of weighted True points (all weights are 1 in the current rubric).
The eval's headline number is `total_score / 32`.

### Judge

- **Model:** `google/gemma-4-26B-A4B-it` on `127.0.0.1:8002`
  (`config.DEEP_LLM_*`).
- **Temperature:** `0.0` for the judge call; the agent's tier picks its
  own temperature elsewhere. Even at 0 the judge is not deterministic in
  practice (vLLM continuous batching + GPU non-determinism); see the
  variance section below.
- **Output contract:** strict JSON, exactly one bool per rubric point,
  in order. The prompt forbids prose, markdown, and code fences. A
  permissive parser (regex-extract first `{...}`, tolerate fence prefix)
  takes one fail-soft pass before counting a row as `parse_failed`.

### Why a separate judge instead of regex / golden-string match

Rubric points like *"identifies precursor supply (IPP/DMAPP from MEP or
MVA pathway, or FPP/GGPP) as a key bottleneck"* admit dozens of valid
phrasings. A regex pinned to one phrasing rewards memorization, not
correctness, and an exact-string golden answer makes the agent
optimize for surface match rather than the underlying chemistry. An
independent judge model evaluating each point asks the question we
actually care about: *was this concept covered, anywhere in the
answer?*

### Judge prompt evolution

Two iterations landed in 8.3.A:

1. **First pass** (commit `4f2657c`) — default rubric phrasing, generic
   "score each point true/false" instruction. Run produced 26 / 32 (81.2%).
   Spot-check found the judge was over-strict on indirect references
   (e.g. Q3 marked the agent's `<plan>` block as False on enzyme-naming
   points because the enumeration appeared inside a Phase-1 plan rather
   than as a direct list). The penalty was for *answer style*, not for
   *whether the concept appeared*.
2. **Sharpened pass** (commit `1c842bc`) — added explicit per-point
   literal-coverage instruction: "*score each point only on whether its
   specific concept appears, anywhere in the text, including plans and
   preambles*." Pinned the fabrication-check (always the last rubric
   point) to placeholder-string detection only. Run produced 31 / 32
   (96.9%); Q3 went 1/6 → 6/6, Q4 stayed at 4/5 (a real gap, not a
   judge artifact).

### Known limitations

- **Literal-coverage is permissive by design.** A long, comprehensive,
  but shallow answer can score highly if it name-drops the right
  concepts without explaining them. Question types like `comparison`
  and `lookup` resist this — the rubric points already require multiple
  concepts in relation to each other.
- **The judge is itself an LLM.** It can flip on the same input
  (variance section below). Treat single-run percentages as point
  estimates, not truth.
- **Substrate-relevance is out of scope** for this eval. The
  fabrication-check rubric flags only obvious placeholder strings
  (`PMID: xxxxxxx`, `R0000`, `EC ?.?.?.?`, `PMID:N/A`). A real-looking
  but wrong KEGG ID *does* pass this check — that failure mode is the
  target of the substrate-relevance verifier (Phase 8.3.B, G4 in the
  inventory).
- **No cross-question consistency check.** Each question is scored in
  isolation. An answer that contradicts itself across questions in the
  same session would not be flagged.

### Variance — 3 back-to-back runs (sharpened judge)

Three sequential runs against the same prompts and judge prompt,
captured in `eval/results/answer_quality_variance_3run.json`:

| Run | Total | % |
|---|---|---|
| 1 | 30 / 32 | 93.8% |
| 2 | 31 / 32 | 96.9% |
| 3 | 30 / 32 | 93.8% |

**Headline (median):** **30 / 32 (93.8%)**. Range 93.8% – 96.9%.

Per question type:
- `comparison` (Q5): **stable** at 6/6 across all runs.
- `lookup` (Q6): **stable** at 5/5 across all runs.
- `mechanism` (Q1, Q2): varies 10/9/9 — driven by Q1 flips on the
  cofactors point (NADH/FADH2/CO2) and the fabrication-check.
- `pathway_design` (Q3, Q4): varies 9/11/10 — driven by Q3's
  4-coumarate-naming point flipping in run 1, and Q4's redox/strategy
  points flipping across runs.

Six rubric points flipped at least once across the three runs, all on
mechanism/pathway-design questions. The two comparison/lookup questions
are stable, suggesting the literal-coverage scoring is most sensitive
on multi-concept open-ended questions where small changes in the agent's
phrasing produce judge-visible coverage differences.

### Fabrication recurrence

The fabrication-check (always the last rubric point) flagged Q1 in
**1 of 3 runs** (run 3): the agent emitted `R00001` and `PMID:N/A` as
stand-in IDs for the citrate-synthase reaction. Other questions cleared
the fabrication check across all 3 runs. The single hit is real signal,
not judge noise — `R00001` matches the placeholder-string heuristic the
sharpened judge prompt explicitly checks for, and the same placeholder
appeared in the original pre-sharpening baseline (commit `6ad72e9`
notes). Fabrication-check sensitivity is roughly 1-in-18 question-runs
on this rubric, with all hits localized to Q1 (the simplest mechanism
question, where the agent appears most likely to over-volunteer cited
detail).

### Reproducing

```
DEMO_MODE=1 PYTHONPATH=/home/tusharmicro/metaboagent \
    python3 -u eval/eval_answer_quality.py
```

Requires E4B serving on `:8001` and 26B MoE serving on `:8002`. Outputs
land in `eval/results/answer_quality_<ts>.json` and
`answer_quality_judge_raw_<ts>.json`.
