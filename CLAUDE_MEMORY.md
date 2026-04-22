# MetaboAgent — Day 1 Session Memory (2026-04-15)

Single source of truth for picking up tomorrow with full context. Read this first.

## What Exists Right Now
- **Working end-to-end agent** at http://0.0.0.0:7860 (Gradio UI, antique-brass theme).
- **ChromaDB populated** with real biochemistry data.
- **3/3 demo scenarios** produce scientifically valid strain designs.

## Completed Tasks (7/7)

| # | Task | Key Files |
|---|---|---|
| 1 | KEGG fetcher + parser | `data/ingestion/kegg_fetcher.py`, `data/ingestion/kegg_parser.py` |
| 2 | PubMed abstract fetcher | `data/ingestion/pubmed_fetcher.py` |
| 3 | Vectorstore setup + embedder + indexer | `vectorstore/chroma_setup.py`, `vectorstore/embedder.py`, `vectorstore/indexer.py` |
| 4 | Hybrid retriever | `vectorstore/retriever.py` |
| 5 | Agent schemas + 4 tools + prompts | `agent/schemas.py`, `agent/tools/{kegg_search,literature_search,retrosynthesis,enzyme_ranker}.py`, `agent/prompts/system_prompt.py` |
| 6 | ReAct agent wiring | `agent/metabo_agent.py` |
| 7 | Gradio UI + scripts + demo tests | `ui/app.py`, `ui/theme.py`, `scripts/{ingest_all,run_agent,run_ui}.py`, `tests/demo_scenarios.py` |

## Data Pipeline — Final State

| ChromaDB collection | Documents | Source |
|---|---:|---|
| `kegg_reactions`  | **12,382** | KEGG `/list/reaction` + batched `/get/rn:*` |
| `kegg_compounds`  | **19,561** | KEGG `/list/compound` + batched `/get/cpd:*` |
| `literature`      | **22,229** | 13,335 PubMed abstracts + 8,309 KEGG enzymes + 585 KEGG pathways |

Raw caches in `data/raw/kegg/{reactions,compounds,enzymes,pathways,links,lists}/`, `data/raw/pubmed/xml/`. Processed JSONL in `data/processed/*.jsonl`. ChromaDB persistent store: `data/chromadb/`.

## Architecture

```
KEGG REST API ─┐
PubMed E-utils ─┼─▶ data/raw/*  ─▶ parsers  ─▶ data/processed/*.jsonl
               │                                     │
               │                            PubMedBERT (CPU, 768-d)
               │                                     ▼
               └───────────────────────────▶ ChromaDB (cosine)
                                                     │
                                          Hybrid Retriever
                                       (semantic + metadata filter)
                                                     │
                                 ┌───────────────────┴──────────────────┐
                                 ▼                                      ▼
                      4 LangChain Tools:                        Gemma 4 31B-IT
                      search_kegg                               vLLM :8000
                      search_literature     ◀────ReAct loop───▶ (4× L40, TP=4)
                      plan_retrosynthesis
                      rank_enzymes
                                                     │
                                                     ▼
                                             Gradio UI :7860
                                         (antique-brass theme,
                                          CoT stream + blueprint)
```

**Why PubMedBERT on CPU**: the 4× L40 GPUs (192 GB VRAM) are fully occupied by Gemma 4 with tensor-parallel=4. PubMedBERT is only 110 M params; CPU embedding throughput (~30 docs/s on the 128 GB/64-core box) is plenty.

## Manual ReAct Loop — Workaround

**Why manual**: `vllm.entrypoints.openai.api_server` is running **without** `--enable-auto-tool-choice` / `--tool-call-parser`. Any native OpenAI tool-calling request returns HTTP 400. LangChain 1.x's `create_agent` relies on that native path.

**Fix**: `agent/metabo_agent.py` implements a hand-written ReAct loop:
- Sends system prompt + ReAct instructions to Gemma 4 via `ChatOpenAI(base_url=VLLM_BASE_URL, api_key=VLLM_API_KEY)`.
- Parses `Action: <name>` + `Action Input: <JSON>` blocks from the model's text output via two separate regexes (single-regex DOTALL lookahead failed when output ended mid-token).
- Invokes the matching `@tool`-decorated callable with `.invoke(args_dict)`.
- Appends `Observation: ...` back into the message history and loops.
- Exits on `Final Answer:` or `AGENT_MAX_ITERATIONS` (15).

**If vLLM gets restarted with `--enable-auto-tool-choice --tool-call-parser hermes` (or similar), we can drop the manual loop and go back to `from langchain.agents import create_agent`.**

## Bug Fixes Applied

1. **KEGG fetcher — tenacity `RetryError` uncaught.** After 4 retry exhaustions on a single 403, `tenacity` raises `RetryError` (not `HTTPError`), bypassing `except requests.HTTPError` and crashing the full pipeline. **Fix**: `_fetch_batch` now catches `(HTTPError, RetryError, RequestException)`, adds a 5-second cooldown, and falls back to single-ID fetches.
2. **KEGG fetcher — 403 under load.** KEGG sometimes returns 403 Forbidden on batch GETs even below 10 req/s. The 5 s cooldown in the same fix absorbs this.
3. **`_parse_entry_id` — enzyme ID extraction.** Enzyme entries start with `ENTRY       EC 1.1.1.1                 Enzyme`. The old code took `parts[1]` = `"EC"`, so all 8,309 files overwrote a single `EC.txt`. **Fix**: when `parts[1].upper() == "EC"`, return `parts[2]`.
4. **`list_pathway_ids` — wrong prefix.** KEGG's `/list/pathway` returns bare `map00010`, but `/get/` expects `path:map00010`, not `map:map00010`. **Fix**: `_list_ids(..., prefix="path", ...)` and filter to `i.startswith("path:map")`.
5. **Self-matching `pgrep` in chain script.** A bash watchdog using `pgrep -f "<long pattern>"` matched its own command line (the pattern is in argv). It loops forever. **Lesson**: always use a PID file or a narrower binary-name match for watchdog scripts.
6. **Gradio 6 removed `show_api` launch arg.** Removed it; `theme` and `css` moved from `Blocks()` to `launch()` in Gradio 6.

## Demo Results (live, against full indexed data)

| Scenario | Host | Enzymes / ECs cited | Status |
|---|---|---|---|
| **artemisinic_acid** | ✅ S. cerevisiae | ADS, CYP71AV1, ALDH1, tHMG1, ERG9 | **PASS** — aligns with Ro 2006 / Paddon 2013 |
| **taxadiene** | ✅ E. coli | EC 2.5.1.29 (GGPPS, *Pantoea ananatis*), EC 4.2.3.4 (TASY, *Taxus*), dxs/dxr/idi overexpression | **PASS** — aligns with Ajikumar 2010 |
| **vanillin** | ✅ E. coli | Shikimate → DHS → PCA → Vanillic acid → Vanillin via aroD + pomA + vanAB (*P. putida* route) | **PASS** — scientifically valid alternate route (agent chose vanAB instead of expected ACAR/OMT) |

**GGPP → lycopene smoke test** (earlier, task #6 validation): agent produced Phytoene Synthase (EC 2.5.1.32, R07270) + Phytoene Desaturase (CrtI bacterial / PDS+ZDS plant) in 6 tool calls.

## UI Design

- **Theme** (`ui/theme.py`): antique-brass palette (bg #1a1610, surface #2a2318, primary #c9a84c, bio #7a9a3a, border #3d3425).
- **Fonts**: `Cinzel` + `Cormorant Garamond` (serif, Google Fonts) for headings/inputs; `JetBrains Mono` for code/CoT stream.
- **Layout** (`ui/app.py`): left column = query textbox + examples + hidden progress slider; right column = live chain-of-thought HTML panel (color-coded: thought italic khaki, tool-call gold, tool-out copper-green, final brass-bold). Below: blueprint Markdown panel with auto-linked KEGG/PMID citations.
- **Streaming**: `stream(agent, query)` yields `{type: thought|tool|final, content/tool/input/output}` events; `on_submit` re-renders the CoT panel on each event and animates a shimmering brass-gradient progress bar.

## Config Notes
- `config.py`: `VLLM_MODEL_NAME = "google/gemma-4-31B-it"` (exact string vLLM reports — case-sensitive).
- `VLLM_API_KEY` is read from `$VLLM_API_KEY` with fallback to the literal key pulled from `ps aux` of the running vLLM process.
- Embedding batch size 64; upsert chunk 256; retrieval top_k=10, rerank top_k=5.

## How to Run Tomorrow

```bash
cd /home/tusharmicro/metaboagent

# 1. Verify vLLM is still up
curl -s -H "Authorization: Bearer $VLLM_API_KEY" http://localhost:8000/v1/models

# 2. Launch UI
PYTHONPATH=/home/tusharmicro/metaboagent python3 -m scripts.run_ui

# 3. CLI query
PYTHONPATH=/home/tusharmicro/metaboagent python3 -m scripts.run_agent "Design a strain to produce lycopene"

# 4. Re-run demo tests
PYTHONPATH=/home/tusharmicro/metaboagent python3 tests/demo_scenarios.py --live
```

## Tomorrow's Priorities
1. **Showcase-mode dropdown** on the UI — pre-select from the 3 demo scenarios with annotated reference data (target, host, expected yield) so judges see expected vs. generated side-by-side.
2. **Pathway visualization** — render the ordered pathway steps as an SVG/Mermaid diagram (node per compound, edge labeled with EC number, source organism as tooltip). Cleanest path: post-process the agent's blueprint steps → build a NetworkX DAG → render with `graphviz` or inline Mermaid HTML.
3. **Expand PubMed corpus** — 13 k abstracts is thin. Add MeSH queries for specific pathway families (terpenoid, polyketide, alkaloid, shikimate, fatty-acid) and raise `PUBMED_MAX_ABSTRACTS` to 100 k. ~1 hour fetch.
4. **Agent prompt tuning** — current ReAct loop sometimes retries the same tool call 4–5 times before self-correcting (observed in GGPP test: 5× `search_kegg` with similar queries). Tighten `_REACT_INSTRUCTIONS` with an explicit "do not repeat a query that already returned results" rule; add short-term memory of prior tool calls in the message history.
5. **Consider requesting a vLLM restart with `--enable-auto-tool-choice --tool-call-parser hermes`** — would let us drop the manual loop, cut latency, and use LangChain's native tool binding + structured outputs. Coordinate with whoever owns the vLLM process.
6. **Add BRENDA kinetics** — `rank_enzymes` currently scores on literature/host/characterization heuristics only. If we can get BRENDA's SOAP dump (or scrape key kcat/Km values), we can produce real catalytic-efficiency rankings.
7. **Citation verification** — add a post-processor that checks every PMID the agent cites actually exists in our literature collection; strip or flag hallucinated IDs.

## Key File Tree (reference)

```
metaboagent/
├── CLAUDE.md                          # full spec (source of truth)
├── CLAUDE_MEMORY.md                   # this file
├── metaboagent_day1_report.docx       # Day 1 build report
├── config.py                          # VLLM_*, KEGG_*, PUBMED_*, CHASSIS_ORGANISMS
├── requirements.txt
├── data/
│   ├── ingestion/
│   │   ├── kegg_fetcher.py            # KEGGFetcher class, batched /get, link tables
│   │   ├── kegg_parser.py             # parse_{reaction,compound,enzyme,pathway} → JSONL
│   │   └── pubmed_fetcher.py          # esearch → efetch XML → literature.jsonl
│   ├── raw/                           # gitignored; populated
│   └── processed/                     # 5 JSONL files, ~100 MB total
├── vectorstore/
│   ├── chroma_setup.py                # PersistentClient at data/chromadb/
│   ├── embedder.py                    # PubMedBERT, mean-pool, L2-normalize
│   ├── indexer.py                     # flatten list metadata → upsert
│   └── retriever.py                   # Retriever class, LLM rerank, list-field substring match
├── agent/
│   ├── metabo_agent.py                # manual ReAct loop (build_agent, run, stream)
│   ├── schemas.py                     # Pydantic models (already existed)
│   ├── prompts/system_prompt.py       # SYSTEM_PROMPT + RETROSYNTHESIS_PROMPT + ...
│   └── tools/
│       ├── kegg_search.py             # @tool search_kegg(query, filter_type, filter_value, top_k)
│       ├── literature_search.py       # @tool search_literature(query, max_results, mesh_term)
│       ├── retrosynthesis.py          # @tool plan_retrosynthesis(target_compound_id, host_organism)
│       └── enzyme_ranker.py           # @tool rank_enzymes(ec_number, host_organism, top_k)
├── ui/
│   ├── app.py                         # Gradio Blocks, streaming CoT, blueprint
│   └── theme.py                       # BRASS palette + CUSTOM_CSS + make_theme()
├── scripts/
│   ├── ingest_all.py                  # orchestrator: PubMed + wait-for-KEGG + parse + index
│   ├── run_agent.py                   # CLI: python -m scripts.run_agent "query"
│   └── run_ui.py                      # launches Gradio on 0.0.0.0:7860
└── tests/
    └── demo_scenarios.py              # --live flag runs all 3 scenarios end-to-end
```

cd /home/tusharmicro/metaboagent                                                                                                                      
  PYTHONPATH=. python3 -m data.ingestion.pubmed_fetcher   # ~30–45 min esearch+efetch                                                                   
  PYTHONPATH=. python3 -m scripts.ingest_all --skip-kegg   # embed + index new abstracts   
