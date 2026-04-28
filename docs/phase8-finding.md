# Finding: Existence-Only Verification Hides Semantic Hallucination

## Setup

3 independent runs of `eval_pathway_hallucination`, 5 design prompts each
(artemisinin, taxadiene, mevalonate, vanillin/ferulic, resveratrol). Across
runs the agent emitted 21 KEGG reaction IDs (R-IDs). Each was verified at
two layers:

1. **Existence** — does the ID exist in KEGG (current verification layer in
   production runtime).
2. **Substrate-relevance** — does the cited reaction's KEGG equation
   actually involve the substrate→product pair the agent claimed in its
   step (new verifier added in Phase 8.3.B).

Of the 21 R-IDs, 18 had enough step context to test substrate-relevance
and 15 of those passed existence verification — i.e., 15 R-IDs are
"verified eligible" for the semantic check.

## Results

Verdict distribution across the 15 verified-eligible R-IDs:

| Verdict | Count | % |
|---|---|---|
| `fully_matches` (substrate AND product align) | 0 | 0% |
| `substrate_only` (one side aligns) | 1 | ~7% |
| `neither` (real ID, unrelated chemistry) | 14 | ~93% |

Real-but-wrong rate among existence-verified IDs: **~93%** (artifact:
`eval/results/pathway_hallucination_variance_3run.json`).

## Implications

Existence-checking would have passed all 15 IDs as "verified". Semantic
verification flags 14 of them. The agent's failure mode at this layer is
**not fabrication** (the IDs exist in KEGG) but **misapplication** (real
IDs are attached to the wrong steps). Concrete case: `R12566` is the real
feruloyl-CoA hydratase/lyase reaction (EC 4.1.2.61, KEGG orthology
K18383): Feruloyl-CoA + H2O ⇌ Vanillin + Acetyl-CoA. The agent emitted
it at step 1 of vanillin-from-ferulic synthesis (Ferulic Acid →
Feruloyl-CoA — the upstream activation step that *produces* feruloyl-CoA,
not the lyase step that consumes it). Right ID, wrong step.

## Methodological contribution

Most agent-grounding benchmarks check whether cited identifiers exist. We
argue this is insufficient: a citation can be valid at the existence layer
while wrong at the semantic layer. Substrate-relevance verification —
checking that the cited reaction's chemistry matches the agent's claimed
step — is a **primary correctness metric** for evidence-grounded
scientific agents, not a defensive afterthought.

## What MetaboAgent does with this finding

- **Pre-submission:** existence-only verification at runtime;
  substrate-relevance verification only in eval, not production.
- **Future work:** substrate-relevance check folded into the agent's
  runtime self-verification loop.
- **Honest framing:** the eval harness is itself the deliverable — the
  measurement and methodology are what we publish. Production runtime fix
  is deferred and called out as such in the writeup.
