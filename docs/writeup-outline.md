# MetaboAgent — Hackathon Writeup Outline

**Framing:** research-note tone, methodological findings as headline contribution. The agent is the platform; the findings are what we publish.

**Track:** Health primary (antimalarial pathway design, India public-health context), climate secondary (bio-manufacturing of fragrances/fuels).

**Target length:** 1500–2500 words, Markdown.

**Voice:** first-person plural ("we measured"), precise technical language, no marketing words, every numerical claim traceable to a JSON artefact under `eval/results/`.

---

## 1. Title + Abstract (~150 words)

- **Working title:** "MetaboAgent: Measuring Where an Evidence-Grounded Co-Scientist Fails — Two Findings on Vision OCSR and Reaction Citation"
- **Abstract bullets:**
  - One-sentence problem: metabolic-engineering literature triage and pathway design is expert-gated and slow; an evidence-grounded LLM agent could lower the floor — but only if its failure modes are measured before deployment.
  - One-sentence platform description: MetaboAgent is a Gemma 4 family agent (E4B router, 26B planner, optional 31B) over a 54k-doc PubMed/KEGG/UniProt corpus, with a 15-tool registry and a multimodal structure-parsing entry.
  - Two-sentence findings teaser: (1) general-purpose vision LLMs do not substitute for specialised OCSR — Gemma 4 E4B reaches 5% strict accuracy on a 20-structure benchmark; (2) existence-only citation verification hides ~93% real-but-wrong reaction IDs that a substrate-relevance check catches.
  - Closing: both findings are reproducible from the released eval harness; the codebase is Apache 2.0 and runs on a single L40-class GPU.

## 2. Motivation (~250 words)

- **Health framing first.** Antimalarial production (artemisinin, semisynthetic route via amorphadiene) is the canonical metabolic-engineering case study; India carries a substantial share of global malaria burden and hosts much of the world's generic-pharma capacity. Cite this as the primary impact lens.
- **Climate framing second.** Bio-manufactured replacements for petrochemicals and overharvested natural products (vanillin, taxadiene, lycopene) — same toolchain, different optimisation target.
- **The bottleneck is not synthesis chemistry — it's literature triage and pathway design.** Researchers spend disproportionate time reading PubMed, walking KEGG, cross-referencing UniProt for enzyme candidates, and translating findings into actionable design steps.
- **An LLM agent that can read the corpus and cite primary literature is plausibly useful here — but only if its claims are verifiable.** If the agent fabricates reaction IDs or misreads chemical structures, it actively harms research workflows.
- **This writeup makes two contributions, in order of unexpectedness:**
  1. A methodological finding about reaction-citation correctness (Section 5.2, the headline).
  2. A scoped capability finding about vision OCSR (Section 5.1).
- **Position framing:** we built the agent so we could measure it. The agent is necessary infrastructure for the findings; the findings are what we publish.

## 3. MetaboAgent: Brief Description (~300 words)

- **Model strategy.** Gemma 4 family used heterogeneously: E4B (~16 GB, one L40) for routing, tool-calling, and multimodal calls; 26B MoE (~2 L40s, TP=2) for multi-step pathway synthesis; 31B dense available as an optional "deep mode". One vLLM process per model, distinct ports. Cite `CLAUDE.md` §3 and `config.py`.
- **Retrieval layer.** Three ChromaDB collections (PubMed, KEGG, UniProt — 54k documents total), embedded with PubMedBERT on a dedicated GPU. Live-fetch tools available but disabled in `DEMO_MODE=1`.
- **Tool registry.** 15 tools (PubMed/KEGG/UniProt search, KEGG pathway/reaction lookup, BLAST, compound resolvers, plus the multimodal `parse_structure_image`). Each tool exposes an OpenAI-style schema; the agent uses Gemma 4's native function calling, not a manual ReAct parser.
- **Agent loop.** Schema-driven function calling, max 6 iterations, sliding-window history. Streaming events: `thinking`, `tool_call`, `tool_result`, `token`, `final_answer`. Cite `agent/core.py`.
- **Verification.** Existence verification of cited identifiers at runtime (KEGG/UniProt). The substrate-relevance verifier added in Phase 8.3.B runs in eval-only mode pre-submission; runtime integration is deferred (Section 7).
- **Demo-safe mode.** `DEMO_MODE=1` + `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` runs end-to-end against the indexed corpus; the four live-fetch tools return clear demo-stub responses.
- **What this section deliberately does *not* do:** sell the agent. The agent is the measurement platform. Architecture diagram (or brief ASCII version reproducing `CLAUDE.md` §4) goes here as visual reference.
- **Note for draft:** `docs/architecture.md` does NOT exist — do not link to it. Reference `CLAUDE.md` and `agent/core.py` instead.

## 4. Measurement Methodology (~350 words)

- **Four runtime evals, ordered cheap → expensive.** Evidence: `eval/run_all.py` and the unified report `eval/results/full_report_phase8_close.md`.
  - `eval_demo_mode` — 5 prompts × 3 categories (live-with-fallback, live-no-fallback, no-tool). Pass/fail per prompt. Source: `eval/results/demo_mode_run_1_20260427T080115Z.json`.
  - `eval_pathway_hallucination` — 5 design prompts (artemisinin, taxadiene, mevalonate, vanillin/ferulic, resveratrol), 3 runs for variance. Surface metric: KEGG existence check on every emitted R-ID. Semantic metric: substrate-relevance check (does the cited R-ID's KEGG equation match the agent's claimed substrate→product step?). Source: `eval/results/pathway_hallucination_variance_3run.json`.
  - `eval_answer_quality` — 6 questions across mechanism / pathway-design / comparison / lookup. LLM-as-judge with rubric scoring (32-point max), 3 runs for variance. Includes a fabrication-check rubric point per question. Source: `eval/results/answer_quality_variance_3run.json`.
  - `eval_structure_extraction` — 20-structure benchmark from PubChem, tiered simple/medium/hard/very-hard. Scored in RDKit with four buckets (PASS_STRICT, PASS_INCHI, PARTIAL, FAIL). Source: `eval/results/structure_extraction_run_1_20260427T081235Z.json`.
- **Scoring choices that need defending in this section:**
  - Why rubric scoring over exact match for answer quality (open-ended scientific answers).
  - Why bucket scoring for structure extraction (RDKit canonicalisation drift vs. compound confusion).
  - Why the substrate-relevance verifier is a *primary* correctness metric, not a secondary defensive layer (cite `docs/phase8-finding.md`'s methodological argument).
- **Variance budget.** vLLM prefix caching collapsed cache-hot prompts into 40–90s/run on the L40 hardware; total runtime for the unified eval is ~12 minutes.
- **Reproducibility command.** `python -m eval all --report` from a `DEMO_MODE=1` shell with `EMBEDDING_DEVICE=cuda:3`. Cite `docs/troubleshooting.md` for the cuda:0 vLLM contention fix.

## 5. Findings (~600 words — centerpiece)

### 5.1 Finding 1 — Vision LLMs do not substitute for specialised OCSR (~250 words)

- **Setup.** 20-structure benchmark, ground truth = PubChem canonical SMILES re-canonicalised through RDKit. Direct vision call to Gemma 4 E4B via vLLM's OpenAI-compatible API.
- **Headline number.** **1/20 = 5% PASS_STRICT** accuracy. Bucket distribution: PASS_STRICT=1, PASS_INCHI=0, PARTIAL=14, FAIL=5 (with FAIL/PARTIAL boundary sensitive to vision-call timeout — extending from 90s to 300s flipped one erythromycin FAIL to PARTIAL but did not produce a correct answer; coenzyme B12 still timed out at 300s).
- **By tier.** Simple 1/5, medium 0/8, hard 0/5, very-hard 0/2.
- **Failure mode is not canonicalisation drift — it's compound confusion.** Aspirin → phenyl acetate (lost the carboxylic acid). Caffeine → diazepane with a pendant amide. Glucose → tetrose. The model produces chemistry-shaped output that is structurally valid but represents the wrong molecule.
- **Self-reported confidence does not correlate with accuracy.** Several PARTIAL bucket results carried `"confidence": "high"`. A downstream UI cannot use the confidence field as a filter.
- **Implication.** Specialised OCSR systems (DECIMER, OSRA, MolScribe) encode chemistry-notation prior knowledge that a general-purpose vision encoder does not. A production agent should integrate a specialised extractor; Gemma 4 vision can play an enrichment role (notes, ambiguity flags, higher-level pathway diagrams not requiring atom-level precision).
- **What MetaboAgent does with this finding (today).** The `parse_structure_image` tool is wired end-to-end. The UI marks it experimental and surfaces the model's RDKit-canonicalised SMILES alongside its self-reported confidence and notes. Cite `docs/multimodal-finding.md` for the full writeup.

### 5.2 Finding 2 — Existence-only citation verification hides semantic hallucination (~350 words — the headline)

- **Setup.** Three independent runs of `eval_pathway_hallucination`, 5 design prompts each. Across runs the agent emitted **21 KEGG reaction IDs (R-IDs)** in the 8.3.B baseline run; 18 had enough step context to test substrate-relevance, and **15 of those passed existence verification** (verified-eligible).
- **Two verification layers.**
  1. **Existence** — does the ID exist in KEGG (current production verification layer).
  2. **Substrate-relevance** — does the cited reaction's KEGG equation involve the substrate→product pair the agent claimed in its step (Phase 8.3.B verifier).
- **Verdict distribution across the 15 verified-eligible R-IDs:**
  - `fully_matches` (substrate AND product align): **0** (0%)
  - `substrate_only` (one side aligns): **1** (~7%)
  - `neither` (real ID, unrelated chemistry): **14** (~93%)
- **Headline:** real-but-wrong rate = **~93%** among existence-verified citations. Existence-checking would have passed all 15 as "verified". Cite `eval/results/pathway_hallucination_variance_3run.json` and `docs/phase8-finding.md`.
- **Worked example.** `R12566` is the real feruloyl-CoA hydrolase reaction (Feruloyl-CoA → Vanillin). The agent emitted it at step 1 of vanillin-from-ferulic synthesis (Ferulic Acid → Feruloyl-CoA — the activation step, not the hydrolase step). Right ID, wrong step. The chemistry of the cited reaction is unrelated to the chemistry of the claimed step, but the ID is real and the citation passes existence verification.
- **Methodological argument (the contribution).** Most agent-grounding benchmarks check whether cited identifiers exist. We argue this is insufficient: a citation can be valid at the existence layer while wrong at the semantic layer. **Substrate-relevance verification is a primary correctness metric for evidence-grounded scientific agents, not a defensive afterthought.** A reaction citation that exists but does not match the claimed chemistry is not a defensive edge case — it is a category of failure that existence-only metrics structurally cannot detect.
- **Reproducibility note.** Phase 8.4's unified eval reproduced the qualitative finding on a smaller sample (5/5 = 100% real-but-wrong on existence-verified IDs in `full_report_phase8_close.md`). The reduced R-ID volume is a confound from a separate phase-1 recursion bug (the agent emitted meta-options instead of step-by-step plans on most prompts; tracked in `docs/phase8-followups.md`). The 8.3.B baseline (n=15, 93%) is the more defensible measurement.

## 6. What Works Well (~250 words)

- **Demo-mode reliability.** 5/5 demo-mode scenarios pass — the offline corpus + tool-stub responses give a deterministic, network-free demo path. Source: `eval/results/demo_mode_run_1_20260427T080115Z.json`.
- **Answer quality on biochemistry questions.** 3-run aggregate **median 29/32 (90.6%)**, range 81.2%–96.9%. By question type:
  - `comparison`: 6/6 every run (stable)
  - `lookup`: 5/5 every run (stable)
  - `mechanism`: [8, 8, 10]/10 (Q1 fabrication check failed on 2/3 runs — this is the one place the agent is producing rubric-failing fabrications inside otherwise high-scoring answers, worth flagging)
  - `pathway_design`: [7, 10, 10]/11
  - Source: `eval/results/answer_quality_variance_3run.json`.
- **Surface fabrication is rare.** The KEGG R-IDs the agent does emit *exist* — the failure mode is misapplication, not invention. This is a non-trivial property and worth stating directly.
- **Latency profile.** vLLM prefix caching makes cache-hot prompts cheap (~40–90s for 3 runs of a multi-step design prompt on an L40); the documented avg-turn target (≤5s) is realistic for E4B-routed lookups.
- **Scope-honest framing of vision OCSR.** Rather than ship a known-broken capability silently, the agent surfaces the finding in the UI (experimental badge, RDKit-canonicalised output, confidence and notes visible). The user sees what the model said and can verify before trusting.

## 7. Limits and Future Work (~150 words)

- **Substrate-relevance verifier is eval-only.** Production runtime still uses existence-only verification. Folding the verifier into the agent's runtime self-verification loop is the obvious next step.
- **Phase-1 recursion bug.** On most pathway-design prompts in the unified Phase 8.4 run, the agent emitted meta-options instead of a step-by-step plan, suppressing R-ID volume. Tracked in `docs/phase8-followups.md`. Fixing this likely raises both the absolute R-ID count and the absolute number of detected real-but-wrong citations.
- **Vision OCSR.** Integrate DECIMER (or equivalent) as the primary structure extractor; A/B against the same 20-structure benchmark to publish a defensible comparison number.
- **Q1 mechanism fabrication.** The acetyl-CoA TCA mechanism question fails the fabrication-check rubric point on 2/3 runs at otherwise high overall scores. Investigate whether this is prompt-specific or a systematic pattern in mechanism-type questions.

## 8. Reproducibility (~100 words)

- **Repository.** Apache 2.0 licensed. Branch `v2-rebuild` at the submission tag.
- **One-command full eval.** `python -m eval all --report` from a `DEMO_MODE=1` shell.
- **Required env.** `PYTHONPATH=<repo root>`, `EMBEDDING_DEVICE=cuda:3` (or any GPU not held by vLLM — see `docs/troubleshooting.md`), `DEMO_MODE=1`.
- **Evidence files.** Every numerical claim in this writeup links to a JSON file under `eval/results/`; the unified report `eval/results/full_report_phase8_close.md` is the index.
- **Methodology details.** `docs/eval-methodology.md`. Findings: `docs/phase8-finding.md`, `docs/multimodal-finding.md`. Architecture: `CLAUDE.md`.
- **AI-assisted development disclosure** lives as a footnote at the end of the draft.

---

## Source-of-truth tracker for the draft

Every numerical claim must trace to one of:
- `eval/results/full_report_phase8_close.md` (overview)
- `eval/results/pathway_hallucination_variance_3run.json` (Finding 2 numbers, Phase 8.4 run)
- `eval/results/answer_quality_variance_3run.json` (Section 6 quality numbers)
- `eval/results/structure_extraction_run_1_20260427T081235Z.json` (Finding 1 numbers)
- `eval/results/demo_mode_run_1_20260427T080115Z.json` (demo-mode 5/5)
- `docs/phase8-finding.md` (8.3.B baseline numbers — preferred for the headline 93% claim)
- `docs/multimodal-finding.md` (Finding 1 detailed observations)

Files NOT to link (don't exist or out of scope):
- `docs/architecture.md` — not present in repo
- `docs/writeup.md` itself — that's what we're producing
