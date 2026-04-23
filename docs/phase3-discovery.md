# Phase 3.0 — Discovery

Investigation only. No code changes. Scope: map the existing agent, inventory the 15 tools, classify what to reuse vs. rewrite, extract what's worth preserving from the old agent, and sanity-check that the new stack (langchain-openai bind_tools against vLLM) actually works before we cut.

---

## Task 1 — Agent loop map (`agent/metabo_agent.py`, 521 lines)

### a. Flow (entry → termination)

```
run(agent, query, history)        [line 395]
  messages = [SystemMessage(SYSTEM_PROMPT + _REACT_INSTRUCTIONS)]   (396, field default on AgentBundle line 234)
  messages += _build_history_messages(history)                      (397 → 371)
  messages += [HumanMessage(query)]                                 (398)
  for i in range(max_iters):                                        (405, max_iters from config AGENT_MAX_ITERATIONS)
    resp  = agent.llm.invoke(messages, stop=["\nObservation:"])    (407)  ← ONLY llm call
    text  = resp.content
    if Final Answer match:  break                                   (413–416 via _FINAL_RE line 207)
    parsed = _parse_action(text)                                    (418 → 210)
    if not parsed:  append nag "call a tool or Final Answer"        (419–423)
    if _call_signature() already in successful_sigs: skip+nag       (426–435)
    observation = _invoke_tool(tools, name, args_text)              (437 → 280)
    truncate to 4000 chars                                          (438)
    append AIMessage(text) + HumanMessage(Observation+memo)         (444–449)
  return {"answer": final or text, "steps": ..., "transcript": ...}
```

`stream()` at line 454 has the same body but `yield`s events (`thought`, `tool`, `final`) instead of collecting. **It does not token-stream** — still calls `.invoke()`, not `.stream()`, and yields one event per ReAct iteration (the full chunk of LLM text at once).

### b. `llm.invoke()` / `llm.stream()` call sites

| Line | Caller | Args | How output is used |
|---|---|---|---|
| 407 | `run()` | `messages`, `stop=["\nObservation:"]` | `.content` → regex-parsed for `Action:` / `Final Answer:` |
| 467 | `stream()` | same | same |

`llm.stream()` is never called anywhere in the repo. Genuine token streaming doesn't exist today.

### c. Parsers

| Symbol | Line | Input | Output | Failure mode |
|---|---|---|---|---|
| `_ACTION_NAME_RE` | 205 | LLM text | match or None | silent None → nag reply |
| `_ACTION_INPUT_RE` | 206 | LLM text after `Action:` | match or None | silent None → nag reply |
| `_FINAL_RE` | 207 | LLM text | match or None | if no match, loop continues |
| `_parse_action()` | 210–225 | LLM text | `(tool, args_text)` or `None` | **soft-fail**: no raise, just returns None, loop nags model |
| `_coerce_args()` | 291–306 | raw text after `Action Input:` | `dict` | **silent last-ditch**: if JSON decode fails twice, wraps whole text as `{"query": text}` — this is the footgun the original diagnostic flagged; the model gets whatever structure it happens to produce, and the tool sees a bogus `{"query": "..."}` call |

Known brittleness already paid for:
- ` ```json\n{...} ``` ` fences — handled (lines 292–295)
- Trailing `Observation:` / `Thought:` / `Final Answer:` bleed-through — handled (221–224)
- Markdown-y prose where model writes `Action Input: search for aspirin` instead of JSON — falls into `{"query": "search for aspirin"}` silently and the tool behaves unpredictably

### d. Prompt sizes

| Piece | Lines | Words | Est. tokens (×1.3) |
|---|---|---|---|
| `SYSTEM_PROMPT` (`agent/prompts/system_prompt.py`) | 177 file / ~150 content | 790 | ~1,027 |
| `_REACT_INSTRUCTIONS` (`metabo_agent.py` 55–167) | 113 | ~800 | ~1,040 |
| **Combined sent every turn** | **~263** | **~1,590** | **~2,067** |

With a 32 k `max_model_len` the headroom is fine, but ~2 k tokens of boilerplate on every turn is waste once tool descriptions move into JSON schemas. CLAUDE.md §6 Phase-3 target is ≤40 lines total system prompt; current is ~6.5× that.

### e. Entry-point signatures

```python
run(agent: AgentBundle, query: str, history: list[dict] | None = None) -> dict
    # → {"answer": str, "steps": list[dict], "transcript": str}

stream(agent: AgentBundle, query: str, history: list[dict] | None = None) -> Iterable[dict]
    # yields {"type": "thought"|"tool"|"final", "content"|"tool"|"input"|"output": ...}
```

`stream()`'s event shape is **inconsistent** with CLAUDE.md §4 event protocol (`token`, `tool_call`, `tool_result`, `thinking`, `final_answer`, `error`, `done`). The new loop must emit the §4 schema, not the current one.

### f. Error handling

| Where | Behavior | Verdict |
|---|---|---|
| `_invoke_tool` 280–288 | `except Exception` → return `"ERROR: tool '{name}' failed: {e}"` | Swallows types, no `error` event emitted to UI. The ERROR string is then fed back to the LLM as the next observation, which can cause the model to repeat the call (depending on `successful_sigs`) or confabulate. |
| `_coerce_args` 291–306 | Swallows `json.JSONDecodeError` twice, falls back to `{"query": text}` | Silent. The "ERROR: unknown tool" branch at line 282 is the only place a bad name surfaces; bad args just become a weird query. |
| `_call_signature` 309–316 | Swallows `Exception` in JSON canonicalization, falls back to raw text | Benign — canonicalization is best-effort. |
| `_coerce_chat_content` 319–345 | None-safe, list/dict/str variants all handled | Clean. |
| Outer loop | No try/except. If `llm.invoke` raises, it bubbles. | Clean. |

No `log.exception()` anywhere in the ReAct path — errors vanish into the return string.

### g. Termination

- `AGENT_MAX_ITERATIONS` (config) — hard cap, `for i in range(...)`. If it's hit, `run()` returns `{"answer": final or text, ...}` — "final or text" means **on timeout the user gets the last pre-Final-Answer blob of model text, which usually includes "Action: xxx" ReAct cruft**. That's user-facing bug #1 to fix in the rewrite.
- `Final Answer:` detected via `_FINAL_RE` → `break` (413–416).
- Repeat-call suppression: `successful_sigs` blocks identical re-calls with nag-message but does **not** terminate.
- No termination on N consecutive errors. Model could burn the iteration budget on a single broken tool.

---

## Task 2 — Tool inventory

**Total SLOC across 15 tool files:** 2,237 lines. All 15 are `@tool`-decorated (`from langchain_core.tools import tool`). `agent/tools/__init__.py` is 0 bytes. `agent/tools/_http.py` (68 lines) provides a single shared session with tenacity retries (`stop_after_attempt(3)`, `wait_exponential(0.5..4)`, 25 s timeout, 404 = no-retry `None`).

| File | Exported tool | Inputs (required / optional-default) | Return | External dep | Wired? | Footguns for JSON Schema |
|---|---|---|---|---|---|---|
| `compare_synthesis_routes.py` | `compare_synthesis_routes` | `target:str` / `top_k:int=4` | JSON str (kegg_context, microbial_route, chemical_route, comparison_template) | ChromaDB | yes | clean |
| `design_expression_vector.py` | `design_expression_vector` | `target_gene:str` / `host:str="ecoli"`, `promoter_strength:str="med"` | JSON str (host_resolved, recommendation, plasmid_map_svg) | static catalog | yes | `host` and `promoter_strength` are free-form strings with silent fallback — should be `Literal` enums |
| `design_primers.py` | `design_primers` | `gene_sequence:str` / `tm_target:float=60`, `cloning_strategy:str="gibson"`, `re_enzyme:str="NdeI"`, `vector_upstream_flank:str=""`, `vector_downstream_flank:str=""` | JSON str (fwd/rev primer + Tm/GC%, orf_start/end, cloning meta) | BioPython | yes | 4 optional strings; `cloning_strategy` should be `Literal["gibson","restriction"]`; empty-string-as-absent-flank is ugly in JSON Schema |
| `enzyme_ranker.py` | `rank_enzymes` | `ec_number:str` / `host_organism:str="ecoli"`, `top_k:int=5` | JSON str (candidates w/ lit_evidence, host_compat, characterization_depth, organism_breadth, overall) | ChromaDB | yes | `host_organism` should be `Literal[...]` (CHASSIS_ORGANISMS enum) |
| `fetch_gene_sequence.py` | `fetch_gene_sequence` | `gene_or_accession:str` / `organism:str=""` | JSON str (accession, description, length, seq, truncated, url) | NCBI E-utils + ChromaDB indexer | yes | clean |
| `fetch_kegg_live.py` | `fetch_kegg_live` | `entity_id:str` | JSON str (kind, kegg_id, name, formula/eq/sysname, pathways/orgs, url) | KEGG REST + ChromaDB | yes | clean |
| `fetch_pubchem.py` | `fetch_pubchem` | `compound_name_or_cid:str` | JSON str (cid, iupac, formula, mw, SMILES, xlogp, HBD/A, RB, synonyms, url) | PubChem PUG + ChromaDB | yes | clean |
| `fetch_pubmed_live.py` | `fetch_pubmed_live` | `query:str` / `max_results:int=10` | JSON str (query, count, hits[pmid,title,snippet,journal,year,mesh,url]) | NCBI E-utils + ChromaDB | yes | clean |
| `fetch_sabio_rk.py` | `fetch_sabio_rk` | `ec_number:str` / `organism:str=""`, `max_results:int=15` | JSON str (ec, organism, count, entries[entry_id,enzyme,substrate,product,parameter,pmid]) | SABIO-RK TSV + ChromaDB | yes | clean |
| `fetch_uniprot.py` | `fetch_uniprot` | `protein_name_or_ec:str` / `organism:str=""` | JSON str (query, organism, hits[accession,name,gene_names,ec_numbers,seq_len,function,features,xrefs,url]) | UniProt REST + ChromaDB | yes | clean |
| `fetch_zinc.py` | `fetch_zinc` | `compound_name_or_zinc_id:str` | JSON str (zinc_id, name, smiles, inchi, mw, logp, rb, hba, hbd, purchasable, num_vendors, url) | ZINC15 REST + ChromaDB | yes | clean |
| `kegg_search.py` | `search_kegg` | `query:str` / `filter_type:str="none"`, `filter_value:Optional[str]=None`, `top_k:int=5` | JSON str (hits across kegg_reactions + kegg_compounds) | ChromaDB | yes | **`filter_type="none"` is a sentinel string** — classic footgun. Model must choose from `{"ec_number","compound_id","pathway_id","none"}` and pair with a `filter_value` string that is sometimes nullable. Clean schema: drop `filter_type`, let `filter_value` be typed as `{ec_number?,compound_id?,pathway_id?}` (discriminated) or just `Optional[EcNumber] \| Optional[CompoundId] \| Optional[PathwayId]`. |
| `literature_search.py` | `search_literature` | `query:str` / `max_results:int=5`, `mesh_term:str=""` | JSON str (hits[pmid,title,journal,year,source,score,snippet]) | ChromaDB | yes | empty-string-means-no-filter footgun on `mesh_term` — prefer `Optional[str]=None` |
| `retrosynthesis.py` | `plan_retrosynthesis` | `target_compound_id:str` / `host_organism:str="ecoli"` | JSON str (target, host, host_name, native_anchors, pathway, reached_native) | ChromaDB + hardcoded `_NATIVE_COMPOUND_HINTS` | yes | `host_organism` should be `Literal[...]`; `_NATIVE_COMPOUND_HINTS` is a coarse hardcoded list |
| `web_search.py` | `web_search` | `query:str` / `max_results:int=5` | JSON str (results[title,url,snippet]) or error JSON | DuckDuckGo (`ddgs` w/ `duckduckgo_search` fallback) | yes | clean |

### Tools that hit the live internet (DEMO_MODE stub targets in Phase 7)
`fetch_pubmed_live`, `fetch_kegg_live`, `fetch_pubchem`, `fetch_uniprot`, `fetch_sabio_rk`, `fetch_zinc`, `fetch_gene_sequence`, `web_search` — 8 of 15.

### Side-effect observation (worth flagging)
Every live fetcher also **indexes its result into ChromaDB** before returning. That's convenient ("follow-up searches find it") but makes the tool non-idempotent and couples the tool layer to storage. Not a bug — but the new `agent/core.py` should know that tool calls mutate the retriever's view, so prefix-caching assumptions about retriever state are wrong.

---

## Task 3 — Classification (reuse / schema-fix / refactor / blocked)

| Tool | Class | Justification |
|---|---|---|
| `compare_synthesis_routes` | **REUSE AS-IS** | Two clean inputs, JSON output. Just add schema. |
| `design_expression_vector` | **SCHEMA-FIX** | Input `host` / `promoter_strength` → `Literal` enums. Body stays. |
| `design_primers` | **SCHEMA-FIX** | `cloning_strategy` → `Literal["gibson","restriction"]`; empty-string flanks → `Optional[str]=None`. Body stays. |
| `enzyme_ranker` → `rank_enzymes` | **SCHEMA-FIX** | `host_organism` → `Literal[…CHASSIS_ORGANISMS…]`. Body stays. |
| `fetch_gene_sequence` | **REUSE AS-IS** | Signature fine; just schema. |
| `fetch_kegg_live` | **REUSE AS-IS** | Single string input, JSON out. |
| `fetch_pubchem` | **REUSE AS-IS** | Single string input, JSON out. |
| `fetch_pubmed_live` | **REUSE AS-IS** | Clean. |
| `fetch_sabio_rk` | **REUSE AS-IS** | Clean. |
| `fetch_uniprot` | **REUSE AS-IS** | Clean. |
| `fetch_zinc` | **REUSE AS-IS** | Clean. |
| `kegg_search` | **REFACTOR** | `filter_type="none"` sentinel is awkward and trains the model to remember to pass "none" explicitly. Reshape as `search_kegg(query, top_k, *, ec_number: Optional[str]=None, compound_id: Optional[str]=None, pathway_id: Optional[str]=None)` — at most one of the three filters set. Body stays; adapt the kwargs hand-off to `rxn_kwargs/cpd_kwargs`. |
| `literature_search` | **SCHEMA-FIX** | `mesh_term:str=""` → `Optional[str]=None`; coerce empty→None handling stays in body. |
| `retrosynthesis` → `plan_retrosynthesis` | **SCHEMA-FIX** | `host_organism` → `Literal`. |
| `web_search` | **REUSE AS-IS** | Clean. |

**Blocked: none.** No tool requires an upstream decision before porting.

### Grouping for Phase 3 port
- 9 tools are **REUSE AS-IS** — a morning's work to wrap each with an OpenAI tool schema.
- 5 tools are **SCHEMA-FIX** — same pattern, also fast.
- 1 tool is **REFACTOR** (`search_kegg`) — one afternoon.

### A note on `@tool`
Every tool is already decorated with LangChain's `@tool`, which gives them a `.invoke(dict)` method and automatically derives a schema from the type hints + docstring. With tightened `Literal`s and `Optional`s, **`llm.bind_tools([kegg_search, search_literature, ...])` should Just Work** without us hand-authoring OpenAI JSON schemas — LangChain converts `@tool` callables to the OpenAI schema internally. Worth confirming in Phase 3 kickoff; if it does, the SCHEMA-FIX group is really "just tighten type hints" and CLAUDE.md §6 Phase-3 step 2 ("expose an OpenAI-style tool schema") collapses to a very small change.

---

## Task 4 — Pieces worth carrying forward from `agent/metabo_agent.py`

Not direct copies — these are **ideas** and (for prompts) **content**. The new `agent/core.py` is otherwise a fresh rewrite.

| Piece | Lines | Why keep |
|---|---|---|
| `_prior_calls_memo` + `_call_signature` pattern | 175–203, 309–316 | "Do not repeat equivalent calls this turn" and the `successful_sigs` set are exactly the kind of de-dup you want with native function calling too — vLLM/Gemma can still make redundant calls. Reshape around `AIMessage.tool_calls` IDs instead of regex-parsed names. |
| Observation truncation constants | `PRIOR_CALLS_MAX=6`, `PRIOR_CALL_INPUT_CHARS=160`, `PRIOR_CALL_OUTPUT_CHARS=220`, 4 000-char obs cap at line 438 | Empirically tuned. Start the new loop with these values, revisit if context pressure changes. |
| `_clean_assistant_for_history` | 358–368 | Strips UI-only HTML (`<plan>`, `<plasmid-map>`, `<compare-table>`, `<details>`) from replayed assistant turns so the model doesn't see its own scaffold. **Still relevant in Phase 5 UI** if those tags persist in the event stream. |
| Two-phase "Propose then Deep-dive" pattern | `SYSTEM_PROMPT` lines ~45–90 | Domain-specific prompt design ("for 'make X' requests, output 3–4 candidate approaches as a `<plan>` block, wait for user to pick one"). **This is product insight**, not prompt fluff — preserve the intent verbatim in the new system prompt (tightened to ≤40 lines per CLAUDE.md §6). |
| Inline-citation style ("EC 1.3.99.31 KEGG R07093 PMID:12345678") | `SYSTEM_PROMPT` lines ~26–34 | Also product-level guidance; keep. |
| Pathway-step rendering convention (`Step 1: A → B` with EC/PMID sub-lines) | `SYSTEM_PROMPT` lines ~99–108 | The UI depends on this shape for reaction-scheme rendering. Transplant into the new system prompt. |
| Retry discipline rules 1–4 | `_REACT_INSTRUCTIONS` lines 155–167 | The "change keywords, not synonyms; after 2 failures emit Final Answer" behavioral spec is useful under native tool calling too. Keep in the new prompt (compressed). |
| `_coerce_chat_content` | 319–345 | Gradio 6 multimodal-content normalization — the new UI probably replaces this, but the logic (string / list / dict / None all valid) is the right sketch for the new UI's contract. |

### Intentional deletions (per CLAUDE.md §6 Phase 3 step 1)
- `_parse_action`, `_coerce_args`, `_ACTION_INPUT_RE`, `_ACTION_NAME_RE`, `_FINAL_RE` — native function calling replaces all of this.
- `_REACT_INSTRUCTIONS` (lines 55–167, ~1 k tokens) — replaced by tool schemas + a terse ≤40-line system prompt.
- Fake typing animation — none found in `metabo_agent.py`; it likely lives in `ui/app.py` and is a Phase 5 concern.

---

## Task 5 — Sanity checks

### a. Stack versions
| Package | Version |
|---|---|
| `langchain-openai` | **1.1.13** (`/home/tusharmicro/.local/lib/python3.12/site-packages`) |
| `langchain-core` | 1.2.29 |
| `openai` | 2.31.0 |
| Python | 3.12.3 |

`ChatOpenAI.bind_tools` sig: `(self, tools: Sequence[dict | type | Callable | BaseTool], *, tool_choice=None, strict=None, parallel_tool_calls=None, response_format=None, **kwargs) -> Runnable[LanguageModelInput, AIMessage]`.

Accepts bare dicts, Pydantic classes, callables, or `BaseTool` instances — so our existing `@tool`-decorated callables feed in directly.

### b. bind_tools probe against :8001 (E4B)

Script: `/tmp/phase3_bindtools_test.py` (not committed — discovery probe). Uses `http://127.0.0.1:<port>/v1` explicitly (IPv4, per Phase 2's `::1`-refused lesson).

```
--- port 8001 / google/gemma-4-E4B-it ---
type(msg)         = AIMessage
msg.content       = ''
msg.tool_calls    = [{'name': 'get_compound_formula',
                       'args': {'name': 'aspirin'},
                       'id': 'chatcmpl-tool-8c7b866fa66e96f8',
                       'type': 'tool_call'}]
additional_kwargs tool_calls = None
msg.response_metadata.finish_reason = tool_calls
RESULT: OK
```

### c. bind_tools probe against :8002 (26B MoE)

```
--- port 8002 / google/gemma-4-26B-A4B-it ---
type(msg)         = AIMessage
msg.content       = ''
msg.tool_calls    = [{'name': 'get_compound_formula',
                       'args': {'name': 'aspirin'},
                       'id': 'chatcmpl-tool-a079ece08a7ebff6',
                       'type': 'tool_call'}]
additional_kwargs tool_calls = None
msg.response_metadata.finish_reason = tool_calls
RESULT: OK
```

### Verdict
LangChain's `bind_tools` correctly converts a bare OpenAI-style tool schema (dict) into whatever vLLM's chat-completions endpoint expects, vLLM's `gemma4` tool-call parser correctly emits `<|tool_call>...<tool_call|>` tokens, and langchain-openai 1.1.13 correctly surfaces them on `AIMessage.tool_calls`. **Phase 3 is unblocked at the LLM/serving boundary.** Proceed.

Minor note worth carrying into Phase 3: LangChain dumps the parsed call on `msg.tool_calls` (canonical field), *not* `msg.additional_kwargs.tool_calls` (OpenAI-raw field, returned `None` here). The new agent loop must read from `msg.tool_calls`.

---

## Open questions for "proceed to Phase 3 proper"

1. **Prompt compression target.** CLAUDE.md §6 step 6 says "System prompt in `agent/prompts.py`: ≤40 lines. Tool docs live in the tool schemas, not the system prompt." Confirm the ≤40 line target and I'll draft a replacement that preserves the two-phase flow + citation style + pathway-step convention from Task 4 but drops `_REACT_INSTRUCTIONS`.
2. **Router scope for Phase 3.** `archive/agent_router.py` exists but will be rewritten. Target for the initial router is the heuristic in CLAUDE.md §3 (E4B default; 26B for multi-step pathway / deep reasoning / final plan synthesis; 31B only if explicitly requested). Confirm this is the Phase-3 scope and not over-engineered.
3. **Should `search_kegg` stay one tool or split?** The REFACTOR recommendation above is "one tool, kwargs-per-filter, drop the `filter_type` sentinel." An alternative: split into `search_kegg_reactions` / `search_kegg_compounds` / `search_kegg_pathway` (three narrower tools). Pros of split: each has a trivial schema, less chance of the model mis-selecting a filter. Cons: larger tool catalog for the model to reason over. My lean is **one tool** because Gemma-4 handled all the Phase-2 smoke calls fine; the cost of 16 vs 18 tools on the model is negligible.
4. **`stream()` event schema divergence.** Current `{"type": "thought"|"tool"|"final"}` vs CLAUDE.md §4's `{"type": "thinking"|"tool_call"|"tool_result"|"token"|"final_answer"|"error"|"done"}`. Confirm we adopt §4 verbatim; I'll not try to preserve the old shape.

---

## What this document does NOT commit to

Nothing in this document installs dependencies, writes production code, deletes files, or changes behavior. The only artifact produced by Phase 3.0 is this markdown file itself. The `/tmp/phase3_bindtools_test.py` probe ran against the live :8001 / :8002 services but produced no persistent side effects (the tool call was parsed but the tool wasn't actually executed — no network calls, no ChromaDB writes).
