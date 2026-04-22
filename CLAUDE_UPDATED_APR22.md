# CLAUDE.md — MetaboAgent v2 (Gemma 4 Good Hackathon)

> **Read this file in full before writing or editing any code.** It is the source of truth for architecture, constraints, conventions, and the submission plan. If anything here conflicts with a past decision in the repo, this file wins.

---

## 0. TL;DR for Claude Code

You are helping rebuild **MetaboAgent**, a specialist agent for biochemistry, metabolic pathway engineering, microbiology, and chemistry, for submission to the **Gemma 4 Good Hackathon** (Kaggle × Google DeepMind, deadline **May 18, 2026**).

- **Model family:** Gemma 4 (hackathon requirement). Use **multiple sizes for different jobs**, not one monolith.
- **Preserve:** the ChromaDB corpus (54k docs across 3 collections), the 15 tool implementations, the PubMedBERT embedder setup.
- **Replace:** the manual ReAct loop → Gemma 4 native function calling. The Gradio UI → a cleaner, streaming UI with multimodal input. The two-phase prompt → schema-driven prompts.
- **Add:** multimodal input (chemical structure images, pathway diagrams, paper figures), real token streaming, demo-safe offline mode, evaluation harness.
- **Delete:** the fake typing animation, the 600+ lines of unused CSS, the dead advanced-mode renderers (unless wired into a toggle).
- **Don't touch until asked:** ChromaDB collections, tool function bodies (only their registration changes), the embedder weights cache.

---

## 1. Hackathon context (non-negotiable constraints)

- **Must use ≥1 Gemma 4 model.** We will use the full family strategically.
- **Submission deadline:** May 18, 2026, 23:59 UTC.
- **Required deliverables:**
  1. Working demo (publicly reachable URL — Kaggle Space, HF Space, or equivalent)
  2. Public code repository (this one, Apache 2.0 licensed)
  3. Technical write-up (`docs/writeup.md`)
  4. 2–3 minute demo video
- **Judging dimensions:** Social impact · Technical execution · Reproducibility · Communication. Every architectural decision below is justified against at least one of these.
- **Impact framing (working pitch, refine before submission):**
  > "MetaboAgent is an evidence-grounded co-scientist for metabolic pathway engineering — helping researchers design microbial production routes for medicines and sustainable chemicals (antimalarials, anticancer compounds, bio-based fragrances and fuels) faster and more cheaply. Runs from a single workstation GPU to a 4-GPU server. Apache 2.0."
  >
  > This frames the project across **health** (antimalarials, anticancer) and **climate** (bio-based replacements for petrochemicals and overharvested natural products) — two of the hackathon's three priority themes.

---

## 2. Hardware assumptions

If any of these are wrong, update this section before continuing.

- **Server:** 4× NVIDIA L40 (48 GB VRAM each, 192 GB total), assumed ~128 GB system RAM, local NVMe.
- **OS / runtime:** Linux, CUDA 12.x, Python 3.11+.
- **Network:** stable for development; **assume unreliable for the demo** and build a `DEMO_MODE=1` that works fully offline against the local ChromaDB.

We will **not** use all 4 L40s for one model. Tensor-parallel=4 on a 31B dense model is what made the current setup slow relative to possible — each L40 has plenty of headroom for smaller Gemma 4 variants, and splitting work across models is a better fit for an agent with heterogeneous subtasks.

---

## 3. Model strategy — "right model for the job"

Gemma 4 ships in four sizes, all Apache 2.0, all with native function calling:

| Size        | Role in MetaboAgent                 | Serving                         | GPU budget          |
|-------------|-------------------------------------|---------------------------------|---------------------|
| **E4B**     | **Default router + tool-caller**    | vLLM, bf16, one L40             | ~1 L40 (≤16 GB)     |
| **26B MoE** | **Planner / deep reasoner**         | vLLM, bf16, two L40s (TP=2)     | ~2 L40              |
| **31B dense** | Optional "max rigor" mode          | vLLM, bf16, two L40s (TP=2) OR FP8 on two L40s | ~2 L40 |
| **E2B**     | Not used at runtime; reserved for edge demo | — | — |

**Default routing rule:**
- Quick-turn tool calls, summarization, reformatting, function-call generation → **E4B**
- Multi-step pathway design, mechanistic reasoning, final plan synthesis → **26B MoE**
- User explicitly requests "deep mode" OR plan complexity exceeds threshold → **31B dense**

Multimodal image input (chemical structures, pathway diagrams) is handled by **E4B** (or whichever sizes are confirmed multimodal at integration time — verify at implementation; fall back to E4B if ambiguous).

**vLLM launch flags (every model):**
```
--enable-prefix-caching
--enable-auto-tool-choice
--tool-call-parser <gemma-4-appropriate parser; verify at impl time>
--gpu-memory-utilization 0.90
--max-num-seqs 16
--dtype bfloat16
--trust-remote-code
```

One vLLM process per model on distinct ports:
- E4B → `:8001`
- 26B MoE → `:8002`
- 31B dense → `:8003` (only started when needed)

Ports and model names live in `config.py` — never hard-coded elsewhere.

---

## 4. Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│  UI (Next.js or Gradio 6, single-page chat with multimodal input) │
│    - streams tokens over SSE                                       │
│    - renders tool-call cards, evidence panel, pathway diagram      │
└────────────────────────────┬──────────────────────────────────────┘
                             │ SSE / REST
                             ▼
┌───────────────────────────────────────────────────────────────────┐
│  FastAPI backend  (app/server.py)                                  │
│    /chat           POST  → SSE stream of agent events              │
│    /health         GET                                             │
│    /tools          GET   → catalog for UI introspection            │
└────────────────────────────┬──────────────────────────────────────┘
                             ▼
┌───────────────────────────────────────────────────────────────────┐
│  Agent core  (agent/core.py)                                       │
│    - Router: picks E4B vs 26B vs 31B per turn                      │
│    - Native Gemma 4 function calling loop (no ReAct parser)        │
│    - Bounded message history (sliding window + summary)            │
│    - Emits structured events: token, tool_call, tool_result,       │
│      thinking, final_answer, error                                 │
└────────────┬───────────────────────┬──────────────────────────────┘
             ▼                       ▼
┌──────────────────────┐   ┌────────────────────────────────────────┐
│ Tools  (agent/tools/)│   │ Retrieval  (vectorstore/)               │
│ (keep all 15)        │   │ - ChromaDB (3 collections, 54k docs)    │
│ + new: parse_smiles, │   │ - PubMedBERT embedder on GPU, singleton │
│   parse_structure_img│   │ - Reranker (optional, off by default)   │
└──────────────────────┘   └────────────────────────────────────────┘
```

### Event protocol (agent → UI)
Every agent emits a stream of JSON lines. Keep this schema stable; UI depends on it.

```json
{"type": "thinking",    "content": "Considering two routes..."}
{"type": "tool_call",   "name": "pubmed_search", "args": {...}, "id": "tc_1"}
{"type": "tool_result", "id": "tc_1", "ok": true, "content": {...}}
{"type": "token",       "content": "The"}   // only during final-answer streaming
{"type": "final_answer","content": "...full markdown..."}
{"type": "error",       "where": "tool:kegg_search", "message": "..."}
{"type": "done",        "usage": {"tokens_in": 0, "tokens_out": 0, "ms": 0}}
```

---

## 5. Repository layout

```
/
├── CLAUDE.md                 ← this file
├── README.md                 ← user-facing, kept in sync with CLAUDE.md §1
├── LICENSE                   ← Apache 2.0
├── pyproject.toml
├── config.py                 ← all env-bound settings, no hardcoded URLs/models
├── app/
│   ├── server.py             ← FastAPI, SSE endpoint
│   └── schemas.py            ← Pydantic event + tool schemas
├── agent/
│   ├── core.py               ← main loop, native tool calling, streaming
│   ├── router.py             ← model selection policy
│   ├── prompts.py            ← ≤40 lines total of system prompt, per model
│   ├── history.py            ← sliding-window + summarizer
│   └── tools/                ← 15 existing tools, now exposing OpenAI tool schemas
├── vectorstore/
│   ├── retriever.py          ← singleton, GPU-backed embedder
│   ├── live_indexer.py       ← shares the same embedder
│   └── data/                 ← chroma persistence (gitignored)
├── multimodal/
│   ├── structure_parser.py   ← SMILES + image-of-structure → canonical SMILES
│   └── pathway_parser.py     ← diagram image → structured pathway JSON
├── ui/
│   ├── web/                  ← Next.js app (preferred) OR gradio_app.py
│   └── static/
├── eval/
│   ├── scenarios/            ← JSON files for demo tasks (artemisinin, taxadiene,
│   │                           vanillin, + 2 new health/climate scenarios)
│   └── run_eval.py           ← regression harness, compares against golden outputs
├── scripts/
│   ├── serve_e4b.sh          ← starts vLLM for E4B on :8001
│   ├── serve_26b.sh          ← starts vLLM for 26B MoE on :8002
│   ├── serve_31b.sh          ← starts vLLM for 31B on :8003 (optional)
│   ├── run_dev.sh            ← starts backend + UI
│   └── run_demo.sh           ← DEMO_MODE=1, HF_HUB_OFFLINE=1, all live fetches off
├── docs/
│   ├── writeup.md            ← hackathon technical writeup (judged artifact)
│   ├── architecture.md       ← deeper than CLAUDE.md §4 if needed
│   ├── rollback.md           ← vLLM launch commands + git SHAs for safe reverts
│   └── video-script.md       ← 2–3 min demo video shot list
└── logs/                     ← gitignored runtime logs
```

---

## 6. Development phases

Execute phases in order. **Do not begin a phase until the previous one is committed, tested, and reported.**

### Phase 0 — Snapshot & scaffold (safety first)
1. Branch: `git checkout -b v2-rebuild` off current `main`.
2. Record `git rev-parse HEAD` and the current vLLM launch command into `docs/rollback.md`.
3. Create the directory skeleton in §5. Empty `__init__.py` files where needed.
4. Move `config.py` to the root if not already; parameterize every URL, port, and model name via environment variables with sensible defaults.
5. **Verify with `curl http://localhost:8000/v1/models`** that the currently running model matches what `config.py` claims. Report the exact model id string.

### Phase 1 — Retrieval preserved, embedder fixed
1. Make `Retriever` a real singleton (one instance process-wide).
2. Move PubMedBERT embedder to `cuda:0` (`device="cuda"` in `SentenceTransformer` init). Verify VRAM with `nvidia-smi` — should add ≤1 GB.
3. `vectorstore/live_indexer.py` imports and reuses the Retriever's embedder — no second load.
4. Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` **only after** confirming weights are cached in `~/.cache/huggingface`.
5. Unit test: `pytest eval/test_retrieval.py` — queries return ≥1 doc per collection.

### Phase 2 — vLLM: E4B first, then 26B MoE
1. Create `scripts/serve_e4b.sh` with the flags in §3. Start on `:8001`. Validate with a tool-calling curl (see §8 for test payload).
2. Create `scripts/serve_26b.sh` on `:8002`. Validate the same way.
3. Leave the current `:8000` 31B service running — do not restart it yet. We will swap after the new agent works against E4B.
4. Populate `docs/rollback.md` with both new launch commands.

### Phase 3 — Agent core rewrite
1. Delete: `_parse_action`, `_coerce_args`, `_ACTION_INPUT_RE`, `_REACT_INSTRUCTIONS`, and the fake typing animation.
2. Port every tool in `agent/tools/` to expose an OpenAI-style tool schema (name, description, parameters JSON schema, return type). Use the `@tool` decorator pattern — one file per tool, schema declared at top.
3. Implement `agent/core.py`:
   - Accepts `messages`, yields events per §4 schema.
   - Uses `ChatOpenAI(...).bind_tools(tools).stream(...)` against the selected model's port.
   - Handles `tool_calls` in returned chunks, executes tools, appends `ToolMessage`, loops.
   - Max 6 iterations (was 15). Document the tradeoff in a code comment.
4. Implement `agent/router.py` with the rule in §3. Start with a simple heuristic; don't over-engineer.
5. Implement `agent/history.py`: keep last 2 user turns + last 2 assistant turns verbatim; older turns → one-line summary.
6. System prompt in `agent/prompts.py`: ≤40 lines. Tool docs live in the tool schemas, not the system prompt.

### Phase 4 — FastAPI + SSE
1. `app/server.py`: `/chat` streams agent events as SSE. Unit test with `httpx.AsyncClient`.
2. CORS permissive for `localhost` + the eventual demo domain.
3. `/health` returns status for each vLLM endpoint.

### Phase 5 — UI rebuild
**Decision point:** Next.js (cleaner, judge-friendly) vs staying on Gradio (faster to ship).
- **Recommended: Next.js.** 3–4 days of work, but the default-styled Next.js chat with streaming, tool-call cards, and image upload will massively outclass the current Gradio UI in demo-video quality.
- **Fallback: Gradio** — keep `ui/gradio_app.py`, but delete the 1200 unused CSS lines and the dead renderers first.

UI must surface:
- Token-by-token streaming of final answers
- Collapsible tool-call cards (name, args, duration, result summary)
- Evidence panel with citations linking to PubMed/KEGG/UniProt
- Pathway diagram render (reuse the existing pathway flowchart renderer if salvageable; otherwise use a Mermaid or Cytoscape.js block)
- Image upload zone for multimodal input
- "Deep mode" toggle (routes to 31B/26B)
- "Offline demo" indicator when `DEMO_MODE=1`

### Phase 6 — Multimodal
1. `multimodal/structure_parser.py`:
   - Text SMILES → validate with RDKit, return canonical SMILES + 2D depiction PNG.
   - Image of a chemical structure → use a Gemma 4 multimodal call: "Extract the SMILES for this molecule." Return canonical SMILES. Fall back to OSRA or DECIMER if Gemma 4's accuracy is poor on a test set (build a 20-structure test set in `eval/scenarios/structures/`).
2. `multimodal/pathway_parser.py`:
   - Image of a pathway diagram → Gemma 4 multimodal call that returns structured JSON: `{nodes: [{id, name, smiles?}], edges: [{from, to, enzyme?, ec?}]}`.
   - Post-process: validate node names against ChromaDB, flag unknown entities for the user.
3. Expose both as tools: `parse_structure_image`, `parse_pathway_image`. UI wires image uploads to these.

### Phase 7 — Demo-safe mode
1. `DEMO_MODE=1` env flag disables: `fetch_pubmed_live`, `fetch_kegg_live`, `fetch_uniprot`, `web_search`. They return a clear stub: `{"demo_mode": true, "message": "live fetch disabled; using indexed corpus"}`.
2. Pre-warm ChromaDB queries for the demo scenarios at server startup.
3. `scripts/run_demo.sh` sets `DEMO_MODE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, starts backend + UI.

### Phase 8 — Evaluation harness
1. Build `eval/scenarios/` with ≥5 scenarios covering biochem / metabolic eng / microbiology / chemistry / a multimodal case.
2. Each scenario: input prompt (optionally + image), golden-output rubric (not exact string match — rubric of required facts the answer must contain), max tokens, max iterations.
3. `eval/run_eval.py` runs all scenarios against current agent, writes `eval/results/<git-sha>.json` with per-scenario pass/fail + timings.
4. Run before every merge to `main`.

### Phase 9 — Submission artifacts
1. `docs/writeup.md` — see §10 for outline.
2. `docs/video-script.md` — 2–3 min, shot list + narration.
3. Record video, upload unlisted to YouTube or Loom.
4. `README.md` — quickstart in ≤10 commands, link to demo, link to video, link to writeup.
5. Publish demo to a public URL (Kaggle Space / HF Space / a provisioned box).
6. Final `git tag v1.0-submission` and submit on Kaggle.

---

## 7. Conventions Claude Code must follow

- **Small commits, one concern each.** Message format: `phase<N>: <what changed>`.
- **No silent fallbacks.** If a tool or model call fails, raise a structured error; the agent loop decides how to recover.
- **No hardcoded URLs, ports, model names, or paths.** All via `config.py`.
- **Type hints on every function.** Pydantic models for every external payload.
- **Logging:** structured JSON to `logs/<component>.jsonl`. No `print`.
- **Tests next to code.** Every file `foo.py` has `test_foo.py` alongside it with at least a smoke test.
- **No new dependencies without a note in `docs/decisions.md`** explaining why and what was considered instead.
- **Never commit:** `.env`, model weights, `vectorstore/data/`, `logs/`, `node_modules/`. Keep `.gitignore` honest.
- **When uncertain, stop and ask.** Especially about: model size choices, vLLM flags, UI framework switch, deleting code flagged as "unused."

---

## 8. Validation recipes

**Is vLLM serving Gemma 4 correctly?**
```bash
curl http://localhost:8001/v1/models
# expect the E4B model id
```

**Does tool calling work?**
```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<E4B model id>",
    "messages": [{"role":"user","content":"What is the molecular formula of aspirin?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_compound_formula",
        "description": "Return the molecular formula for a compound by name.",
        "parameters": {"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}
      }
    }],
    "tool_choice": "auto"
  }'
# expect a tool_calls array in the response
```

If the above returns tool_calls correctly, Phase 3 is unblocked. If not, escalate before rewriting the agent — the parser flag is wrong.

**Is prefix caching helping?** Send the same long prompt twice. Second response's `usage.prompt_tokens_cached` (or equivalent in vLLM's response) should be nonzero.

---

## 9. Known hazards and debts

- **"Gemma 4" model naming:** there may be multiple fine-tunes labeled `google/gemma-4-*` on Hugging Face. Pin exact model revisions in `config.py` using `revision="<sha>"` to avoid silent swaps.
- **Multimodal accuracy on chemical structures:** Gemma 4 may not be SOTA at SMILES extraction from images. Build the 20-structure test set early; if accuracy < 70%, add DECIMER as a fallback.
- **vLLM tool-call parser for Gemma 4:** verify the correct `--tool-call-parser` value at integration time. It may be a new Gemma-specific parser, not `hermes`. Check vLLM release notes for Gemma 4 support.
- **Demo network risk:** the demo venue's Wi-Fi is the single biggest demo-day failure mode. `run_demo.sh` must be tested on airplane mode before the event.
- **Judge watching the video, not the demo:** the video is the primary artifact most judges will see. Over-invest in video polish relative to feature count.

---

## 10. Writeup outline (`docs/writeup.md`)

Target length: 1500–2500 words. Structure:

1. **Problem** — metabolic engineering bottleneck: designing microbial production routes is slow, literature-heavy, and expert-gated. Concrete impact cases: artemisinin (antimalarial), taxol (anticancer), vanillin (bio-based fragrance), etc.
2. **Solution** — MetaboAgent: evidence-grounded assistant that plans pathways, cites primary literature, and parses structures/diagrams.
3. **Why Gemma 4** — function calling native, multimodal, Apache 2.0, full family lets us match model size to subtask, runs on a single workstation GPU (E4B) through to a small server (31B).
4. **Architecture** — router + tools + retrieval + multimodal. Diagrams. Link to `docs/architecture.md`.
5. **Technical innovations** — (a) model routing across the Gemma 4 family, (b) multimodal chemical structure and pathway parsing, (c) evidence-grounded tool layer against 54k-doc corpus, (d) demo-safe offline mode.
6. **Impact** — quantified where possible: research hours saved, accessibility for labs without dedicated computational-biology staff, Apache 2.0 enabling deployment in LMIC university labs.
7. **Reproducibility** — one-command startup, licensing, data sources.
8. **Limitations & future work** — honesty here scores well.
9. **Team, acknowledgments, license.**

---

## 11. What success looks like on May 18

- Avg turn time ≤ 5s (vs current 47s)
- First token visible to user ≤ 1s
- 5/5 scenarios pass the eval rubric
- Video is ≤3 min, shows one end-to-end health task + one multimodal moment + the deep-mode toggle
- Public demo URL reachable for judges
- Repo: clean, licensed, reproducible in ≤10 commands
- Writeup: reads like a product launch, not a lab report

---

## 12. Next action for Claude Code

Start at **Phase 0**. Report snapshot findings and the `curl /v1/models` output. Do not begin Phase 1 until the user approves Phase 0 in writing.
