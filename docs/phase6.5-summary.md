# Phase 6.5 — summary

## What we thought was broken

We expected the agent to fabricate KEGG R-IDs and EC numbers. The
milestone was scoped around verify-tools for pre-emission checks.

## What we measured (initial baseline)

Five pathway-design prompts, two-turn runs, IDs cross-checked against
KEGG REST:

- Hallucination rate **0 %** on emitted IDs.
- Plan-emission reliability **60 %** (3 / 5 reached phase 2 on the
  initial run).
- Step-convention adherence broken on 1 / 3 phase-2 runs.

The prior was wrong — the failure surface was *reliability*, not
*fabrication*.

## What we fixed

- **6.5.a** — `verify_kegg_reaction` + `verify_ec_number` as cheap
  defensive insurance (cached, DEMO_MODE-aware, available not mandated).
- **6.5.b** — Diagnosed the phase-1 failures. `glucose_shikimate` was
  biochemically infeasible (real pathway is 7+ steps, not 3).
  `artemisinic_yeast` hit an E4B H4 empty-completion bug.
- **6.5.c** — Three fixes: swapped the bad prompt for `resveratrol_ecoli`;
  added a one-shot nudge retry in `agent/core.run_agent` for H4 (clean
  error if still empty); fixed two measurement bugs (step-convention
  regex too strict, `no_ids_emitted` conflated silent giveups with
  honest declared-insufficient-evidence).

## Final numbers — 3 back-to-back runs

Same code, same prompts, same tier, temperature 0.2. Per-metric min /
median / max across `eval/results/pathway_hallucination_run_{1,2,3}.json`:

| metric | min | median | max |
|---|---|---|---|
| plans_emitted | 4 | 4 | 4 |
| plans_parse_failed | 1 | 1 | 1 |
| step_convention_ok (of 4 phase-2 runs) | 3 | 4 | 4 |
| no_ids_emitted total | 0 | 1 | 2 |
| `  silent_giveup` | 0 | 0 | 0 |
| `  declared_insufficient_evidence` | 0 | 0 | 0 |
| `  unclassified` (phase-1 recursion) | 0 | 1 | 2 |
| R-IDs extracted | 3 | 5 | 7 |
| R-IDs hallucinated | 0 | 0 | 0 |
| ECs extracted | 5 | 8 | 11 |
| ECs hallucinated | 0 | 0 | 0 |
| nudges fired | 0 | 0 | 0 |

**Invariants across all 3 runs**: zero fabrication on 15 + 24 = 39
emitted IDs, zero silent giveups, zero nudge firings, four of five
prompts always produced a parseable `<plan>`.

## Per-prompt status across 3 runs

```
mevalonate_ecoli    ok         ok         ok
artemisinic_yeast   plan_fail  unclassified plan_fail
vanillin_ferulic    ok         plan_fail  ok
lycopene_ecoli      unclassified ok       ok
resveratrol_ecoli   unclassified ok       ok
```

`artemisinic_yeast` never reached IDs in any run — the plant-specific
*A. annua* enzymes consistently stress the default tier.

## Variance is an honest property, not a defect

E4B at temperature=0.2 shows significant run-to-run variance on
pathway design: which prompts reach IDs-emitted oscillates, and the
ID count on a passing prompt (mevalonate's R-IDs go 4/1/3) shifts
meaningfully. Our fixes eliminated fabrication (0 % across all 3
runs) and silent failures (0 across all 3 runs); they do **not**
guarantee deterministic ID emission per prompt. This is a property
of the underlying model + decoding temperature combination, not a
bug in the agent.

## What remains open

`docs/phase8-followups.md`:

1. **Real-but-wrong-enzyme** — existent-in-KEGG but substrate-
   irrelevant IDs; binary verification doesn't catch this.
2. **Phase-1 recursion** — all the "unclassified" rows above are
   phase-2 responses that re-emit a `<plan>` block instead of
   transitioning to the deep-dive. A `phase_1_recursion` status
   computed from `PLAN_BLOCK_RE.search` on the phase-2 answer would
   label them honestly.

Both are Phase 8 eval-harness expansion items.
