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
