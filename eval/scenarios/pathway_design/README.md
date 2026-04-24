# Pathway design — baseline hallucination measurement

## What this directory is

Five short design prompts used as the control measurement before
Phase 6.5 (verify tools + prompt hardening). Each prompt asks the
agent to produce a pathway with KEGG reaction IDs and EC numbers —
the exact surface where fabrication would be dangerous. Eval driver:
`eval/eval_pathway_hallucination.py`. Results land in
`eval/results/pathway_hallucination_baseline_*.json`.

## Why two turns

The agent's system prompt splits pathway questions into
Phase 1 ("propose 3-4 approaches, no IDs yet") and Phase 2
("deep-dive with numbered pathway steps" once the user picks an
option). Single-turn prompts never reach Phase 2, so any naive
single-turn measurement reports 0 IDs and 0 hallucinations
vacuously. The eval therefore drives both turns: turn 1 collects
the `<plan>` block, turn 2 sends the first plan ID back as the
follow-up, and Phase 2's final answer is the measurement surface.

## Baseline numbers (5 prompts, 2026-04-24)

| metric | value |
|---|---|
| plans emitted in phase 1 | 3 / 5 |
| phase-2 runs | 3 |
| phase-2 runs with zero IDs emitted | 1 / 3 |
| R-IDs extracted | 4 |
| R-IDs verified in KEGG | 4 / 4 |
| EC numbers extracted | 4 |
| EC numbers verified in KEGG | 4 / 4 |
| **overall hallucination rate** | **0.0 %** |

Per prompt:

| id | status | followup | R-IDs (verified) | ECs (verified) |
|---|---|---|---|---|
| `mevalonate_ecoli` | ok | A | 3 / 3 | 3 / 3 |
| `artemisinic_yeast` | `plan_parse_failed` | — | — | — |
| `vanillin_ferulic` | ok | A | 1 / 1 | 1 / 1 |
| `lycopene_ecoli` | `no_ids_emitted` | A | 0 | 0 |
| `glucose_shikimate` | `plan_parse_failed` | — | — | — |

## How this reshaped Phase 6.5

The prior going into the eval was that the agent would fabricate
plausible-looking KEGG R-IDs and EC numbers, and Phase 6.5's job
was to add verify tools that the agent would consult before
emitting an ID. The measurement disconfirms that prior: every ID
that got emitted was real, and all eight independently verified in
KEGG. The failure surface is elsewhere:

- **Phase-1 reliability (2 / 5):** `artemisinic_yeast` returned an
  empty final answer; `glucose_shikimate` answered in prose without
  a `<plan>` block. Neither reached the measurement surface.
- **Phase-2 step-convention adherence (1 / 3):** `lycopene_ecoli`
  went through phase 2 but produced a narrative description
  (headers like "Target Molecule:", "Host Chassis:") instead of
  the mandated `Step N: substrate → product  Reaction: R...  EC ...`
  shape. No R-IDs or ECs emitted to verify.

Rescoped Phase 6.5:

- **6.5.a — verify tools as insurance, not primary fix.**
  `verify_kegg_reaction` and `verify_ec_number` are still worth
  building because the cost is low and they guard against
  regression on larger eval sets. They are available in the tool
  registry, not mandated by prompt.
- **6.5.b — diagnose phase-1 failures before patching them.**
  `glucose_shikimate`'s refusal may be correct behaviour (the
  prompt asks for a 3-step route that does not exist); distinguish
  "bad prompt" from "bad agent" before writing any code.
- **6.5.c — patch the phase-2 step convention.** Targeted prompt
  tightening with a concrete example block; re-run the two already-
  passing prompts to confirm no regression.

Headline framing: the agent on this 5-prompt sample is **accurate
when it answers (0 % hallucinations) but unreliable in reaching the
answering step (60 % reliability end-to-end).**

## Reproducing

```bash
PYTHONPATH=. python3 eval/eval_pathway_hallucination.py
```

Default tier, max 8 iterations per turn, 400 ms between KEGG
verification calls. Writes
`eval/results/pathway_hallucination_baseline_<timestamp>.json`.
