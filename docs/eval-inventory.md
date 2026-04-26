# Eval Inventory & Gap Analysis (Phase 8.1)

Snapshot of every eval entrypoint, scenario set, and result file in the
repo as of 2026-04-26 (commits up to `bdbfa4c` on `v2-rebuild`). Used to
plan the 8.2 unification and 8.3 answer-quality rubric.

---

## 1. Eval entrypoints

| Script | Phase | What it measures | Live backend | Runtime (5 scenarios) | Output shape |
|---|---|---|---|---|---|
| `eval/eval_demo_mode.py` | 7.2.5 | DEMO_MODE behavioral correctness — fallback invoked after live-fetch stub; honest admission when no fallback exists; zero tool calls when none needed. | E4B (`:8001`); `DEMO_MODE=1` env required (script refuses otherwise). In-process call to `run_agent`. | ~17s wall (5 prompts) | `{summary: {total, passed, failed, by_category}, rows: [{id, prompt, category, passed, tool_calls, iterations, duration_ms, final_answer, notes}]}` |
| `eval/eval_pathway_hallucination.py` | 6.5 | Two-turn pathway design: how often KEGG R-IDs / EC numbers in Phase-2 answers fail to verify against `rest.kegg.jp`. Also tracks plan-block emission, step-convention adherence, silent-giveup vs. declared-insufficient-evidence. | E4B (`:8001`). Network out to `rest.kegg.jp` for ID verification (400 ms between calls). In-process `run_agent`. | ~100–130s wall (5 prompts × 2 turns + KEGG verification) | `{timestamp_utc, kind, flow, tier, phase1_stats, phase2_stats, pathway_accuracy, per_prompt: [...]}` |
| `eval/eval_structure_extraction.py` | 6.4 | `parse_structure_image` accuracy bucketed into PASS_STRICT / PASS_INCHI / PARTIAL / FAIL on 20 PubChem PNGs. Tool invoked directly — agent loop bypassed. | E4B (`:8001`) for the multimodal call inside the tool. | Untracked in result JSON (no `duration_ms` field per row). 20 multimodal calls — historically ~3–5 min. | `{timestamp_utc, model, summary: {overall, overall_n, by_difficulty}, rows: [{cid, name, difficulty, image, ground_truth_smiles, ground_truth_inchi_key, extracted, verdict}]}` |
| `eval/diagnose_phase1_failures.py` | 6.5.b | Read-only diagnosis of two specific Phase-1 failures (`artemisinic_yeast`, `glucose_shikimate`) across `default` and `deep` tiers. Captures finish-reason, stop-token, usage shape per iteration. | E4B (`:8001`) and 26B MoE (`:8002`). In-process `run_agent` with monkey-patch on `_stream_llm`. | One-shot diagnostic (job done — kept for archaeology, not regression). | `{timestamp_utc, max_iterations, prompts: {...}}` |
| `tests/test_agent_e2e.py` | 3.6 | End-to-end smoke under `unittest`: 3 scenarios × 2 runs, asserting tool invocation, citation markers (PMID/DOI/year), KEGG-anchor terms in final answers, and hard latency budgets (5s / 15s). | E4B (`:8001`) — class is skipped if `/v1/models` 3s reachability check fails. In-process `run_agent`. | ~30–60s wall depending on cache warmth (each scenario is run twice for prefix-cache observation). | unittest pass/fail; full event sequences printed to stdout for eyeball review. No JSON file. |

Supporting tests (not evals, but worth listing):
- `tests/test_eval_pathway_hallucination.py` — unit cover for the `STEP_LINE_RE`, `_extract_plan_ids`, and `_classify_no_ids_reason` regexes inside the pathway eval. Ensures the parsing layer doesn't silently regress.
- `tests/demo_scenarios.py` — three hard-coded showcase scenarios (artemisinic acid, taxadiene, vanillin) — mostly a documentation artifact; not invoked by any test runner.

---

## 2. Scenario directories

| Path | Owner | Count | Used by |
|---|---|---|---|
| `eval/scenarios/pathway_design/prompts.json` | 6.5 | 5 prompts (`mevalonate_ecoli`, `artemisinic_yeast`, `vanillin_ferulic`, `lycopene_ecoli`, `resveratrol_ecoli`) | `eval_pathway_hallucination.py`, `diagnose_phase1_failures.py` |
| `eval/scenarios/structures/` | 6.4 | 20 PNGs + `ground_truth.json` (5 simple / 8 medium / 5 hard / 2 very_hard) | `eval_structure_extraction.py` |
| `eval/scenarios/demo_queries.json` | 7.3 | 15 queries (5 pathway_design, 5 lookup, 5 freeform) | `scripts/warm_demo_cache.py` (cache-warming, not an eval) |
| `eval/scenarios/README.md` | 8 (anticipatory) | — | Promises a `{prompt, image?, rubric[], max_tokens, max_iterations}` schema that does not yet exist. |

The five pathway prompts in §1 also overlap by name with five of the demo-cache queries (`mevalonate_ecoli`, `artemisinic_yeast`, etc.) — same prompts, different consumer.

---

## 3. Latest results snapshot

`eval/results/` holds 10 JSON files (~225 KB total). Most recent run per harness:

- **`demo_mode_20260426T061730Z.json`** — 5/5 passed, all categories green (7.2.5 close).
- **`pathway_hallucination_final_20260424T175858Z.json`** — 4/5 plans emitted; 4 phase-2 runs; 1 R-ID extracted (verified); 0 ECs extracted (after the prompt was tightened to require explicit verification, the agent strips IDs it can't confirm). Hallucination rate 0.0%.
- **`structure_extraction_20260424T142209Z.json`** — 1 PASS_STRICT, 0 PASS_INCHI, 13 PARTIAL, 6 FAIL out of 20. By tier: simple 1/5 strict (4 PARTIAL); medium 0/8 strict (5 PARTIAL, 3 FAIL); hard 0/5 strict (3 PARTIAL, 2 FAIL); very_hard 0/2 strict.

The pathway-hallucination directory has six historical runs (`baseline`, `post_h4`, `final`, `run_1..3`) — these are the before/after artifacts of the 6.5 prompt iteration. Worth keeping; not worth re-generating routinely.

---

## 4. Duplication

**Three pieces of code are reimplemented across evals:**

1. **The "drain a `run_agent` turn into events" loop.** `_drain_turn` in `eval_pathway_hallucination.py` (lines 194–239) and `_drain` in `eval_demo_mode.py` (lines 94–124) are 90% identical: both `async for` over `run_agent`, drop `token` events, capture `final_answer` / `iterations` / `tokens_in/out` / `duration_ms`, fall back to wall-clock when `usage.ms` is zero. The pathway version also counts nudge events; that is the only meaningful divergence.
2. **Result-file writing.** Three different inline implementations of "make `eval/results/`, build a UTC compact timestamp, dump JSON with `indent=2`" — `_write_results` in demo_mode, `out_path.write_text(...)` in pathway and structure extraction.
3. **`run_agent` event-sequence pretty-printing.** `_print_sequence` in `tests/test_agent_e2e.py` reimplements the same thing the test harness in `agent/core.py` already serializes for SSE — just for human-readable test stdout. Low priority to consolidate.

`diagnose_phase1_failures.py` is a finished diagnostic — its job is done, the findings shaped Phase 6.5.c. Keep for archaeology, do not run in any regression.

---

## 5. Gaps

The gap the user already flagged (and 8.3 will fill):

**G1 — Answer-quality rubric eval.** Today every eval scores either *behavior* (did the right tool get called?) or *exact-string* properties (did this regex match? does the canonical SMILES equal the ground truth?). Nothing measures whether the agent's free-text answer correctly *covers* the key facts a domain expert would expect. The `eval/scenarios/README.md` promised exactly this schema (`{prompt, rubric[], …}`) but no scenarios or runner have been written.

Other gaps I noticed:

**G2 — Retrieval-quality eval.** `vectorstore/` holds 54k docs across three collections. We never measure whether a known query returns its expected document inside top-k, so silent regressions (re-indexing with the wrong embedder, drift after `live_indexer` writes) would not surface until an end-to-end eval failed for opaque reasons. A per-collection top-k recall@k probe with a small hand-labelled set (~20 queries) would be cheap and catches a class of bugs the current evals can't.

**G3 — Tool coverage holes.** Of 15+ tools, only six are exercised by an eval today: `fetch_kegg_live`, `fetch_pubmed_live`, `fetch_uniprot`, `fetch_zinc`, `parse_structure_image`, `search_kegg`. Untested in any harness: `fetch_sabio_rk`, `fetch_pubchem`, `fetch_gene_sequence`, `web_search`, `parse_pathway_image`, `verify_kegg_reaction`, `verify_ec_number`, `search_literature` (only indirectly via fallback), and the molecule/organism resolvers. Not all of these need their own eval, but the rubric eval in 8.3 should be designed to *naturally* exercise the long tail — by including scenarios that need kinetic params, gene sequences, ZINC vendors, and pathway diagrams.

**G4 — Substrate-relevance verification (already flagged).** The `verify_kegg_reaction` tool checks an ID *exists*. It does not check the reaction's substrate matches the substrate the agent claimed. A real KEGG R-ID stitched into the wrong step is the next-most-dangerous failure surface after fabricated IDs, and the current eval would call that a pass. (Per CLAUDE.md §11 and the 7.2.5 close, this is on the Phase-8 follow-up list.)

**G5 — Multimodal end-to-end.** `parse_structure_image` is tested in isolation. There is no eval that uploads a structure image to `/chat`, checks the agent extracts SMILES *and then* uses it to drive a downstream tool call. This is exactly the demo-video moment we want to lock down; right now it depends on hand-tested scripts.

**G6 — Router eval.** `agent/router.py` picks `default` / `deep` / `max_rigor` per turn. There is no regression that confirms the heuristic still routes a "design a pathway" prompt to `deep` after future prompt changes. Low impact today (the heuristic is simple) but easy to add and worth having.

**G7 — Single-shot, no historical view.** Each result lands in a timestamped JSON; there is no leaderboard, no trend, no `eval/results/latest.json` symlink. Reading whether things are improving requires manually diffing files. Not strictly a gap in *coverage* but a gap in *usability* that 8.4 should address.

---

## 6. Recommendation for 8.2 unification

**Goal:** shared infrastructure where it pays off, leave specialized scoring alone, set up 8.3 (answer quality) cleanly. Concretely:

```
eval/
├── _runner.py                      ← NEW
│     drain_agent_turn(messages, tier, max_iterations) -> {events, final_answer, ...}
│     write_result(kind, payload)   -> Path  (single timestamped writer)
│     timestamp_utc()               -> str
├── _kegg_verify.py                 ← NEW (extracted from eval_pathway_hallucination)
│     verify_kegg_id(kind, raw)     -> bool   (httpx, KEGG_SLEEP_S)
├── eval_demo_mode.py               ← refactor: use _runner.drain_agent_turn + _runner.write_result
├── eval_pathway_hallucination.py   ← refactor: same
├── eval_structure_extraction.py    ← refactor: switch to _runner.write_result; drain not used
├── eval_answer_quality.py          ← NEW (8.3): scenarios with rubric[]; scoring layer; writes via _runner.write_result
├── run_all.py                      ← NEW (8.4 candidate): runs each registered eval, emits a consolidated digest
└── scenarios/
    ├── pathway_design/
    ├── structures/
    ├── demo_queries.json
    └── answer_quality/             ← NEW (8.3): {id, prompt, rubric: [{must_contain: "..."}], max_iterations, tier}
```

**Why this shape:**
- `_runner.py` is the smallest possible shared layer — just the two pieces that are actually duplicated 3×. Anything bigger (a shared "Eval base class") would force the structure-extraction harness into a turn-draining mold that doesn't fit it.
- KEGG verification belongs in its own file, not deep inside `eval_pathway_hallucination.py`, because 8.3's substrate-relevance work (G4) will want to reuse the rate-limited HTTP client.
- The `answer_quality` directory mirrors the existing `pathway_design` shape so the 8.3 author has an obvious template.
- `run_all.py` deferred to 8.4 (or whichever later milestone owns CI integration) — for 8.2 the goal is to deduplicate the existing harness without changing its behavior.

**What I would NOT consolidate:**
- The structure-extraction scoring (PASS_STRICT/PASS_INCHI/PARTIAL/FAIL) is purpose-built for that domain. Don't try to unify it with rubric scoring.
- `tests/test_agent_e2e.py` stays under `tests/` — it's a unittest hook, runs in the same suite as everything else, and a duplicate copy under `eval/` would invite drift.
- The pathway eval's two-turn driver. Demo-mode and answer-quality are single-turn; pathway is two-turn by nature; squashing them into one shape would make every consumer pay for the rare case.

**Validation plan for 8.2:** after refactor, re-run `eval_demo_mode` and `eval_pathway_hallucination`; results must be byte-identical (modulo the timestamp field) to the most recent baseline JSONs already in `eval/results/`. That confirms the consolidation is purely structural.
