# Gemma 4 — Observed Quirks

Known model-compliance issues observed during MetaboAgent development on
`google/gemma-4-E4B-it` (Phase 2/3 agent core). Each item: what the model
does, what the prompt says, our workaround.

## 1. LaTeX arrow substitution in prose

**Says:** emits `$\rightarrow$` (LaTeX) or bare `\rightarrow` in pathway
step lines, e.g. `Step 1: Acetyl-CoA $\rightarrow$ Acetoacetyl-CoA`.

**Prompt says:** "Use the plain Unicode arrow → (or ASCII -> if your tool
set can't produce Unicode). Do NOT substitute LaTeX (`$\rightarrow$`),
HTML (`&rarr;`), or emoji arrows — the parser keys on → / -> and nothing
else." (agent/prompts/__init__.py, pathway-rendering section.)

**Workaround:** two layers, both needed.
- Downstream: input-normalization layer in `ui/web/lib/pathway.ts`
  (`normalizeArrows`) maps `$\rightarrow$`, `\rightarrow`, `&rarr;`,
  `⟶`, `➡` → `→` before the `STEP_RE` regex runs. This is pre-parser
  character substitution, **not** parser permissiveness; the regex still
  only accepts `→ / -> / -->`.
- Upstream: the system prompt now explicitly forbids the three common
  substitutions.

Prompt adherence is partial — the model continued emitting
`$\rightarrow$` in testing even with the explicit forbid. The
normalizer is the actual fix; the prompt clause is belt-and-braces in
case a future model iteration listens.

## 2. PMID placeholder hallucination

**Says:** emits literal `PMID:xxxxxxx` (string of x's, or sometimes
digit-zeros) when it doesn't have a real citation for a pathway step.
Example: `Enzyme: Thiolase (E. coli) PMID:xxxxxxx`.

**Prompt says:** "Never invent KEGG IDs, EC numbers, or PMIDs — omit
rather than fabricate." (prompts/__init__.py, citation section.)

**Workaround:** downstream strip of the placeholder pattern in the
pathway parser (`scrubPmid`, `ui/web/lib/pathway.ts`). The enzyme line
is scrubbed of both the placeholder *and* any real PMIDs *after* the
real PMID is captured into `step.pmid`, so the enzyme-name regex can
match the organism parens cleanly. Prompt adherence here is partial —
the model still emits the placeholder sometimes.

## 3. Template-filling bias (UNSOLVED, to address in Phase 7/8)

When the prompt shows an output shape with slots for IDs — e.g.,
`Reaction: <KEGG R-id>   EC <x.x.x.x>` — the model tends to **fill
those slots with plausible-looking IDs rather than omitting the slot
when it doesn't have data**. Observed most clearly in pathway design
outputs: the mevalonate route emitted `R00010..R00014`, none of which
are the real KEGG reaction IDs for that pathway. The model treats the
slot as a required field to populate, not an optional anchor.

**Workaround:** none yet. Candidate fixes:

- **(a)** Stronger prompt examples showing omission — a "bad" example
  where slots are filled without evidence, and a "good" example where
  the step lists only what was actually looked up.
- **(b)** Mandatory tool-call-before-emission for design queries.
  Enforce in the agent loop: if the final_answer contains
  `Reaction: R\d{5}`, the agent must have called `fetch_kegg_live` or
  `search_kegg` for that ID earlier in the same turn. Otherwise strip
  the ID before emission.
- **(c)** Post-generation validator that verifies cited R/EC IDs
  against KEGG, marking unverified ones with a visible caveat.

To be decided when building Phase 7 (DEMO_MODE — which needs offline
fallback content anyway) or Phase 8 (eval harness — where false IDs
are an eval-metric problem). **This is currently the single biggest
accuracy risk for demo day.**
