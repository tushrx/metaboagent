# MetaboAgent: Measuring Where an Evidence-Grounded Co-Scientist Fails — Two Findings on Vision OCSR and Reaction Citation

## Abstract

Metabolic-engineering literature triage and pathway design are expert-gated. An evidence-grounded language-model agent could lower the floor — but only if its failure modes are measured before deployment. We built MetaboAgent, a Gemma 4 family agent (E4B router, 26B planner, optional 31B "deep mode") over a 54k-document PubMed/KEGG/UniProt corpus with a 15-tool registry and a multimodal structure-parsing entry point. We then measured it. This writeup reports two findings the eval harness produced. **Finding 1:** general-purpose vision LLMs do not substitute for specialised optical chemical-structure recognition — Gemma 4 E4B reached 5% strict accuracy on a 20-structure benchmark. **Finding 2:** existence-only citation verification — checking whether a cited reaction ID is real — hides approximately 93% real-but-wrong reaction IDs that a substrate-relevance check catches. To our knowledge the second gap has not been measured systematically in prior agent benchmarks; we provide a reproducible methodology, a baseline measurement, and an open eval harness. The codebase is Apache 2.0 and runs on a single L40-class GPU.

## Motivation

Antimalarial production is the canonical metabolic-engineering case study: the semisynthetic artemisinin route through engineered amorphadiene biosynthesis remains a textbook example of how heterologous pathway engineering supplies medicines that are otherwise plant-extraction-bound. India carries a substantial share of global malaria burden and hosts much of the world's generic-pharma capacity, which makes pathway-engineering tooling a public-health-relevant capability rather than a purely industrial one. Adjacent to that, bio-manufactured replacements for petrochemicals and overharvested natural products — vanillin, taxadiene, lycopene, isoprenoids more broadly — are studied with the same toolchain under different optimisation targets, and the climate framing flows from the same workflow. We treat health as the primary impact lens and climate as a closely coupled secondary one.

The bottleneck for the practitioner here is not synthesis chemistry. It is literature triage and pathway design. Researchers spend disproportionate time reading PubMed, walking KEGG, cross-referencing UniProt for enzyme candidates, and translating findings into actionable design steps. A language-model agent that can read the corpus and cite primary literature is plausibly useful — but only if its claims are verifiable. If the agent fabricates reaction IDs or misreads chemical structures, it actively harms research workflows.

This writeup makes two contributions, in order of unexpectedness:

1. A **methodological finding about reaction-citation correctness** (Section 5.2 — the headline).
2. A **scoped capability finding about vision OCSR** (Section 5.1).

We built the agent so we could measure it. The agent is necessary infrastructure for the findings; the findings are what we publish.

## MetaboAgent: Brief Description

**Model strategy.** We use the Gemma 4 family heterogeneously rather than picking a single size. **E4B** (~16 GB, one L40) handles routing, tool-calling, and multimodal calls. **26B MoE** (~2 L40s, tensor-parallel = 2) handles multi-step pathway synthesis and mechanistic reasoning. **31B dense** is available as an optional "deep mode" but is not in the default routing path. One vLLM process per model, distinct ports. The rationale and exact flag set live in [`CLAUDE.md`](../CLAUDE.md) §3; routing policy is in [`agent/router.py`](../agent/router.py).

**Retrieval layer.** Three ChromaDB collections — PubMed, KEGG, and UniProt — totalling roughly 54k documents, embedded with PubMedBERT on a dedicated GPU pinned via `EMBEDDING_DEVICE` to avoid contention with vLLM's CUDA allocator. Live-fetch tools (PubMed, KEGG, UniProt, web) are available but disabled in `DEMO_MODE=1` for offline reproducibility.

**Tool registry.** Fifteen tools: PubMed/KEGG/UniProt search and detail fetchers, KEGG pathway and reaction lookups, BLAST, compound resolvers, plus the multimodal `parse_structure_image` entry point. Each tool exposes an OpenAI-style schema; the agent uses Gemma 4's native function calling, not a hand-written ReAct parser. The agent loop in [`agent/core.py`](../agent/core.py) caps iterations at 6 and emits a streaming event protocol (`thinking`, `tool_call`, `tool_result`, `token`, `final_answer`).

**Verification.** The agent performs **existence verification** of cited identifiers (KEGG reactions, KEGG compounds, UniProt accessions) at runtime. The **substrate-relevance verifier** described in Finding 2 was added in Phase 8.3.B and currently runs in eval-only mode; integrating it into the runtime self-verification loop is deferred and called out in Section 7.

**Demo-safe mode.** `DEMO_MODE=1` combined with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` runs the agent end-to-end against the indexed corpus. The four live-fetch tools return clear demo-stub responses rather than masquerading as live ones. This is what the public demo runs on.

We deliberately do not sell the agent here. The agent is the measurement platform. Its job is to make the findings reproducible.

## Measurement Methodology

We run four runtime evaluations, ordered cheap → expensive, dispatched by [`eval/run_all.py`](../eval/run_all.py) and indexed in the unified report at [`eval/results/full_report_phase8_close.md`](../eval/results/full_report_phase8_close.md).

**`eval_demo_mode`** — five prompts across three categories (live-with-fallback, live-no-fallback, no-tool). Pass/fail per prompt. Source: [`eval/results/demo_mode_run_1_20260427T080115Z.json`](../eval/results/demo_mode_run_1_20260427T080115Z.json).

**`eval_pathway_hallucination`** — five design prompts (artemisinin, taxadiene, mevalonate, vanillin-from-ferulic, resveratrol), three independent runs for variance. Two metrics. The **surface metric** runs an existence check on every emitted KEGG reaction ID. The **semantic metric** runs the substrate-relevance verifier — does the cited reaction's KEGG equation actually involve the substrate→product pair the agent claimed in its step? Source: [`eval/results/pathway_hallucination_variance_3run.json`](../eval/results/pathway_hallucination_variance_3run.json).

**`eval_answer_quality`** — six questions across mechanism, pathway-design, comparison, and lookup categories. LLM-as-judge with rubric scoring (32-point maximum), three runs. Each rubric includes a fabrication-check point so we can separate "answer is good in aggregate" from "answer fabricates a specific identifier or claim". Source: [`eval/results/answer_quality_variance_3run.json`](../eval/results/answer_quality_variance_3run.json).

**`eval_structure_extraction`** — a 20-structure benchmark sourced from PubChem and tiered by visual complexity (simple → very-hard). Scored in RDKit and bucketed: `PASS_STRICT` (canonical SMILES match), `PASS_INCHI` (InChIKey match — credits structurally equivalent representations differing by component ordering, protonation, or tautomer), `PARTIAL` (RDKit-valid SMILES of a different molecule), `FAIL` (no SMILES or RDKit rejection). Source: [`eval/results/structure_extraction_run_1_20260427T081235Z.json`](../eval/results/structure_extraction_run_1_20260427T081235Z.json).

Two scoring choices warrant defending. Answer-quality questions are open-ended scientific prose, so exact-match scoring would discard most useful comparisons; rubric scoring gives us per-point variance and a defensible fabrication-check. Structure-extraction uses bucket scoring rather than a single similarity score because the relevant distinction is between canonicalisation drift (the model wrote the same molecule a different way) and compound confusion (the model wrote a different molecule); a Tanimoto-style scalar collapses these.

vLLM's prefix caching makes the variance budget cheap: cache-hot prompts complete in 40–90 seconds per run on an L40, and the full unified eval finishes in roughly twelve minutes. The reproducibility command is `python -m eval all --report` from a `DEMO_MODE=1` shell with `EMBEDDING_DEVICE=cuda:3` (or any GPU not held by vLLM — see [`docs/troubleshooting.md`](troubleshooting.md) for the cuda:0 contention fix).

Methodology details and judge-prompt specifics are in [`docs/eval-methodology.md`](eval-methodology.md).

## Findings

### Finding 1 — Vision LLMs do not substitute for specialised OCSR

We benchmarked Gemma 4 E4B's vision capability against a 20-structure test set sourced from PubChem and tiered by visual complexity. Ground truth is the PubChem canonical SMILES re-canonicalised through RDKit, plus an RDKit-computed InChIKey per entry. The extraction call is direct vision input to Gemma 4 E4B via vLLM's OpenAI-compatible API, asking for JSON-only output with `smiles`, `confidence`, `alternative_smiles`, and `notes`.

Headline result: **1/20 = 5% PASS_STRICT accuracy**. Bucket distribution: `PASS_STRICT=1`, `PASS_INCHI=0`, `PARTIAL=14`, `FAIL=5`. By tier: simple 1/5, medium 0/8, hard 0/5, very-hard 0/2. Only ethanol (the trivial case) passed strict matching.

The failure mode is not canonicalisation drift — it is compound confusion. Aspirin was extracted as phenyl acetate (the ortho-carboxylic acid was dropped). Caffeine became a diazepane with a pendant amide. Glucose became a four-carbon tetrose. The model produces chemistry-shaped output that is structurally valid but represents the wrong molecule. Self-reported confidence does not correlate with accuracy — several PARTIAL-bucket results carried `"confidence": "high"`.

Specialised OCSR systems (DECIMER, OSRA, MolScribe) encode chemistry-notation prior knowledge that a general-purpose vision encoder does not. A production agent should integrate a specialised extractor as the primary SMILES path; Gemma 4 vision can play an enrichment role (notes, ambiguity flagging, higher-level pathway diagrams). Full writeup at [`docs/multimodal-finding.md`](multimodal-finding.md).

### Finding 2 — Existence-only citation verification hides semantic hallucination

This is the load-bearing contribution. We measured a gap between two verification layers that, to our knowledge, has not been quantified systematically in prior agent benchmarks: an evidence-grounded scientific agent can cite reaction identifiers that **exist in the public database** while the cited reaction's **chemistry is unrelated to the agent's claimed step**. We provide a reproducible methodology for measuring this gap, and a baseline measurement.

**Setup.** Three independent runs of `eval_pathway_hallucination` against the five design prompts. Across the three runs the agent emitted **21 KEGG reaction IDs (R-IDs)**. Of these, 18 had enough step context to test substrate-relevance, and **15 of those passed existence verification** — they are real KEGG R-IDs that, in the production runtime, would be marked "verified". This is the verified-eligible set.

**Two verification layers.**

1. **Existence verification** — does the ID exist in KEGG? This is the verification layer the agent runs at runtime today.
2. **Substrate-relevance verification** — does the cited reaction's KEGG equation actually involve the substrate→product pair the agent claimed in its step? Implemented as a Phase 8.3.B verifier that fetches the KEGG equation and matches its left-hand-side / right-hand-side compound IDs against the agent's claimed inputs and outputs.

**Verdict distribution across the 15 verified-eligible R-IDs.**

| Verdict | Count | % |
|---|---|---|
| `fully_matches` (substrate AND product align) | 0 | 0% |
| `substrate_only` (one side aligns) | 1 | ~7% |
| `neither` (real ID, unrelated chemistry) | 14 | ~93% |

**Real-but-wrong rate among existence-verified citations: ~93%.** Existence-checking would have passed all 15 IDs as "verified". Substrate-relevance checking flags 14 of them. Source artefact: [`eval/results/pathway_hallucination_variance_3run.json`](../eval/results/pathway_hallucination_variance_3run.json), interpretation in [`docs/phase8-finding.md`](phase8-finding.md).

**Worked example.** `R12566` is a real KEGG reaction — feruloyl-CoA hydratase/lyase (EC 4.1.2.61, orthology K18383), which catalyses Feruloyl-CoA + H₂O ⇌ Vanillin + Acetyl-CoA. The agent emitted `R12566` at step 1 of its vanillin-from-ferulic-acid synthesis (Ferulic Acid → Feruloyl-CoA, the upstream activation step that *produces* feruloyl-CoA, not the lyase step that *consumes* it). Right ID, wrong step. The chemistry of the cited reaction is unrelated to the chemistry of the claimed step — but the ID is real, and the citation passes existence verification. This is the failure pattern in microcosm.

**Methodological argument.** Most agent-grounding benchmarks check whether cited identifiers exist in the source database. We argue this is insufficient. A citation can be valid at the existence layer while wrong at the semantic layer, and existence-only metrics structurally cannot detect this. Substrate-relevance verification — checking that the cited reaction's chemistry matches the agent's claimed step — is a **primary correctness metric for evidence-grounded scientific agents, not a defensive afterthought**. The 93% rate we measure is not an outlier on a hostile prompt set; the prompts are standard pathway-design queries (artemisinin, taxadiene, mevalonate, vanillin, resveratrol).

**Differentiation from prior work.** Existing agent-hallucination benchmarks (HalluLens, tool-use hallucination evaluation, embodied-agent grounding) measure adjacent properties — whether a generated entity exists, whether a tool is invoked with valid parameters, whether claims are entailed by retrieved text. The 2025 survey on agent hallucinations[^survey] organises these into five categories (reasoning, execution, perception, memorization, communication); our failure pattern maps closest to "memorization hallucinations / sub-optimal retrieval", which the survey describes as content that "appears similar but lacks true relevance." None of these benchmarks isolate or quantify the specific case we measure here: the agent retrieves a real KEGG identifier whose semantic content does not match the chemistry claimed in the agent's own step. We provide a domain-specific reproducible methodology (the substrate-relevance verifier, in `agent/tools/_kegg_verify.py`) and a baseline measurement against five standard pathway-design prompts.

[^survey]: Liang et al., "LLM-based Agents Suffer from Hallucinations: A Survey of Taxonomy, Methods, and Directions," arXiv:2509.18970 (2025).

**Reproducibility note on the unified Phase 8.4 run.** The unified eval reproduced the qualitative finding on a smaller sample — 5/5 = 100% real-but-wrong on existence-verified IDs in [`eval/results/full_report_phase8_close.md`](../eval/results/full_report_phase8_close.md).[^1] The reduced R-ID volume (5 vs. 21) is a confound from a separate phase-1 recursion bug: on most pathway-design prompts in the 8.4 run the agent emitted meta-options ("here are three approaches you could take") instead of a step-by-step plan, suppressing R-ID emission. This bug is tracked in [`docs/phase8-followups.md`](phase8-followups.md). The 8.3.B baseline (n=15, 93%) is the more defensible measurement and is the headline number for this writeup.

[^1]: The 100% rate on the smaller 8.4 sample is consistent with the 8.3.B 93% baseline within sampling noise — what changed is the absolute R-ID count, not the per-ID failure rate.

## What Works Well

**Demo-mode reliability.** All five demo-mode scenarios pass — three live-with-fallback, one live-no-fallback, one no-tool. The offline corpus combined with explicit demo-stub responses on the four live-fetch tools gives a deterministic, network-free demo path. Source: [`eval/results/demo_mode_run_1_20260427T080115Z.json`](../eval/results/demo_mode_run_1_20260427T080115Z.json).

**Answer quality on biochemistry questions.** Three-run aggregate **median 29/32 (90.6%)**, range 81.2%–96.9%, totals per run [26, 29, 31]. By question type the picture is more nuanced than the median suggests:

| Question type | Per-run scores | Max | Stable across runs |
|---|---|---|---|
| `mechanism` | [8, 8, 10] | 10 | no |
| `pathway_design` | [7, 10, 10] | 11 | no |
| `comparison` | [6, 6, 6] | 6 | yes |
| `lookup` | [5, 5, 5] | 5 | yes |

Comparison and lookup are stable across runs; mechanism and pathway-design are not. The mechanism instability is concentrated in **Q1 (acetyl-CoA TCA cycle)**, which fails the fabrication-check rubric point on 2/3 runs at otherwise high overall scores. We flag this as a real failure mode rather than averaging it out: the agent produces high-rubric-score mechanistic answers that contain a fabricated specific claim. This is the pattern Finding 2 describes at the citation layer, surfacing here at the prose layer. Source: [`eval/results/answer_quality_variance_3run.json`](../eval/results/answer_quality_variance_3run.json).

**Surface fabrication is rare.** The KEGG R-IDs the agent emits *exist* — 0/21 hallucinated against existence verification across the 8.3.B baseline. The failure mode is misapplication, not invention. This is a non-trivial property of the system and worth stating directly, even though Finding 2 then explains why "doesn't fabricate" is a weaker guarantee than it appears.

**Latency profile.** vLLM prefix caching makes cache-hot prompts cheap (40–90 seconds for three runs of a multi-step design prompt on an L40), and routing E4B for lookups makes the average-turn target (≤5 seconds) realistic for the common case.

**Scope-honest framing of vision OCSR in the UI.** Rather than ship a known-broken capability silently, the agent surfaces the vision result with an experimental badge, the RDKit-canonicalised SMILES alongside the model's self-reported confidence, and the model's own caveat notes. The user sees what the model said, whether it hedged, and has enough information to verify before trusting.

## Limits and Future Work

The substrate-relevance verifier is **eval-only** today. Folding it into the agent's runtime self-verification loop is the obvious next step and would convert Finding 2 from a measurement into a fix. Production runtime currently uses existence-only verification, and the writeup's headline number is the gap that closing this loop would close.

The **phase-1 recursion bug** documented in [`docs/phase8-followups.md`](phase8-followups.md) suppressed R-ID volume in the unified 8.4 run. Fixing it likely raises both the absolute R-ID count and the absolute number of detected real-but-wrong citations; the per-ID rate is unlikely to move much.

**Vision OCSR**: integrate DECIMER (or equivalent) as the primary structure extractor and A/B against the same 20-structure benchmark to publish a defensible comparison number. Gemma 4 vision retains an enrichment role.

**Q1 mechanism fabrication-check failures** deserve dedicated investigation: prompt-specific or systematic across mechanism-type questions? Three runs is enough to flag the pattern, not enough to explain it.

## Reproducibility

The repository is Apache 2.0 licensed. One-command full eval: `python -m eval all --report` from a `DEMO_MODE=1` shell. Required environment: `PYTHONPATH=<repo root>`, `EMBEDDING_DEVICE=cuda:3` (or any GPU not held by vLLM — see [`docs/troubleshooting.md`](troubleshooting.md)), `DEMO_MODE=1`. Every numerical claim in this writeup links to a JSON file under [`eval/results/`](../eval/results/); the unified report [`eval/results/full_report_phase8_close.md`](../eval/results/full_report_phase8_close.md) is the index. Methodology details: [`docs/eval-methodology.md`](eval-methodology.md). Findings: [`docs/phase8-finding.md`](phase8-finding.md), [`docs/multimodal-finding.md`](multimodal-finding.md). Architecture: [`CLAUDE.md`](../CLAUDE.md) and [`agent/core.py`](../agent/core.py).

---

[^ai]: Implementation was assisted by Claude Code (Anthropic). Architecture decisions, measurement methodology, finding interpretation, and writing are the author's.
