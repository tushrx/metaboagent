# Phase 6.5 — summary

## What we thought was broken

We expected the agent to fabricate KEGG R-IDs and EC numbers. The
milestone was scoped around verify-tools for pre-emission checks.

## What we measured

Five pathway-design prompts, two-turn runs, IDs cross-checked against
KEGG REST:

- Hallucination rate **0 %** on emitted IDs.
- Plan-emission reliability **60 %** (3 / 5 reached phase 2).
- Step-convention adherence broken on 1 / 3 phase-2 runs.

The prior was wrong — the failure surface was *reliability*, not
*fabrication*.

## What we fixed

- **6.5.a** — `verify_kegg_reaction` + `verify_ec_number` as cheap
  defensive insurance (cached, DEMO_MODE-aware, available not mandated).
- **6.5.b** — Diagnosed the phase-1 failures: `glucose_shikimate` was
  biochemically infeasible (7+ steps, not 3). `artemisinic_yeast` hit
  an E4B H4 empty-completion bug — after a tool call the model
  sometimes emits an `AIMessage` with zero content and zero tool_calls.
- **6.5.c** — Three fixes: swapped the bad prompt for `resveratrol_ecoli`;
  added a one-shot nudge retry in `agent/core.run_agent` for H4 (clean
  error if still empty); fixed two measurement bugs (step-convention
  regex too strict, `no_ids_emitted` conflated silent giveups with
  honest declared-insufficient-evidence).

## Final numbers (all fixes active)

`eval/results/pathway_hallucination_final_20260424T175858Z.json`:
0/1 R-IDs hallucinated, 0/0 ECs, plan parse 4/5, step convention 3/4
phase-2 runs, `no_ids_emitted` = 3 total (silent 0, declared 2,
unclassified 1), nudges fired 0.

**The silent-giveup bucket is empty.** Every missing-IDs outcome is
either an honest refusal or a preamble-style near-miss.

## Variance note

Two clean runs (post-H4 and final) with identical code and
temperature=0.2 diverged substantially on which prompts reached
IDs-emitted. E4B is genuinely noisy on this surface. Our fixes
guarantee 0 % fabrication and 0 silent giveups, not deterministic
IDs-per-prompt.

## What remains open

`docs/phase8-followups.md`: real-but-wrong-enzyme (existent-in-KEGG but
pathway-irrelevant IDs). Binary existence verification does not guard
against this; Phase 8's eval harness expansion owns it.
