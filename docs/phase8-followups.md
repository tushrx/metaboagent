# Phase 8 follow-ups

Items discovered during later phases that were explicitly out of scope
but should be revisited when Phase 8 (evaluation harness expansion)
lands. Keep entries concise; link to the commit or JSON artefact that
produced the evidence.

## Real-but-wrong-enzyme (discovered during Phase 6.5 final re-baseline)

**Finding.** `mevalonate_ecoli`'s phase-2 output in the post-H4
re-baseline (`eval/results/pathway_hallucination_post_h4_20260424T174348Z.json`)
emitted three EC numbers — `3.1.1.1`, `3.1.1.2`, `3.5.1.1` — that all
exist in KEGG but are not mevalonate-pathway enzymes:

| EC emitted | Real enzyme | Correct mevalonate enzyme |
|---|---|---|
| 3.1.1.1 | acetylesterase | 2.3.1.9 (acetyl-CoA acetyltransferase / thiolase) |
| 3.1.1.2 | arylesterase | 2.3.3.10 (HMG-CoA synthase) |
| 3.5.1.1 | asparaginase | 1.1.1.34 (HMG-CoA reductase) |

Our binary KEGG lookup in `verify_ec_number` returned `exists=True` for
all three — because they do exist. The eval's hallucination rate was
therefore 0% despite the assignments being wrong for the substrate the
agent was citing them against.

**Implication.** `verify_kegg_reaction` and `verify_ec_number` confirm
*existence*, not *substrate relevance*. "Real but wrong" is a subtler
hallucination that our current verification layer does not catch, and
the zero-hallucination numbers headline obscures it.

**Candidate mitigations for Phase 8 (or later):**

1. **Cross-check emitted IDs against the step's substrate/product
   pair.** Each `Step N: A → B` line and each `Reaction: R…` /
   `EC …` line should be validated by fetching the KEGG reaction
   equation and asserting the named substrate and product are present
   (compound-id equivalence, not string match — we already have
   resolvers for this).
2. **Small enzyme-substrate plausibility reranker.** A lightweight
   model that scores `(EC number, substrate name)` pairs against
   indexed biochem literature — cheaper than a full biochemistry LLM,
   would catch the "cited a real but irrelevant EC" mode.
3. **Acknowledge as a known limit in the writeup.** A production
   system would require domain-specific QA; our Apache-2.0 demo is
   honest about what it does and does not check.

**Scope.** Not fixed in Phase 6.5. Expand the Phase 8 eval harness to
cover this before making stronger accuracy claims.

## Phase-1 recursion (discovered in the Phase 6.5 final re-baseline)

**Finding.** `resveratrol_ecoli` in the final re-baseline run classified
as `no_ids_emitted:unclassified`. Reading the phase-2 `final_answer`
verbatim reveals why: instead of emitting the phase-2 deep-dive
(numbered pathway, KEGG reactions, EC numbers), the agent emitted a
**second `<plan>` block** with three *meta-options* ("Tyrosine to
Resveratrol Pathway Search", "Compare Microbial vs Chemical Routes",
"Enzyme Ranking for Key Steps"), and closed with "Pick an approach and
I'll produce the full design." The preamble makes it explicit:

> "Since a single, complete, validated KEGG pathway for this specific
> heterologous route in *E. coli* is not immediately available, I will
> proceed with the structured design proposal (Phase 1) by focusing on
> the known enzymatic steps required for this transformation."

The agent received "A" as the second user turn but did not transition
from phase 1 to phase 2 — it re-emitted a phase-1 plan.

**Why the classifier labels this "unclassified".** It is long enough
to rule out `silent_giveup` (1,409 non-whitespace chars) but does not
contain our hedge markers ("evidence needed", "insufficient",
"database lookup", etc.). The phrase it does use, "not immediately
available," is not a substring of any existing marker. Adding a
broader marker would only re-label the symptom; the real failure is
structural, not linguistic.

**Candidate detectors for Phase 8:**

1. A `phase_1_recursion` status computed when the phase-2
   `final_answer` itself contains a parseable `<plan>` block. This is
   the most honest signal and costs one `PLAN_BLOCK_RE.search` call.
2. Upstream, check whether the agent's response to a single-letter
   follow-up ever contains step markers; if not, prompt-tighten the
   phase-1-to-phase-2 transition rule in the system prompt.

**Scope.** Not fixed in Phase 6.5 — the split logic is deliberately
left untouched per investigation guidance. Phase 8's eval harness
expansion owns this refinement alongside the real-but-wrong-enzyme
work above.

## Sharper variance bounds for substrate-relevance per-run rate

The 8.3.B baseline reports a pooled 93% real-but-wrong rate across 15 verified-eligible R-IDs from 3 runs. Per-run rates were not separately computed. Re-running the substrate-relevance verifier against the per-run R-IDs (from `pathway_hallucination_run_1/2/3.json`) would produce true per-run rates, allowing the writeup's reproducibility note to give a tighter range than the current 70-100% reader-expectation band. Estimated effort: ~1 hour. Deferred to post-submission.
