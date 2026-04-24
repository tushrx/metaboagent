# Rollback procedure

## Baseline

- **v2-rebuild starting git SHA:** `b92ea34f12fb191bea8fff631cc31b7fd9643070` (branch point from `main`, created 2026-04-22)
- **Baseline branch:** `main` — commit `b92ea34` is the first and currently only commit; reverting to it restores the Day-1 code state (with env-only API key, v2 directory scaffolding in place, and `agent/rag/` + `agent/router.py` in the gitignored `archive/`).

## Running vLLM at baseline

Currently serving on `:8000`, started with:

```bash
python3 -m vllm.entrypoints.openai.api_server \
  --model google/gemma-4-31B-it \
  --tensor-parallel-size 4 \
  --host 0.0.0.0 --port 8000 \
  --trust-remote-code \
  --max-model-len 32768 \
  --api-key "$PRIMARY_LLM_API_KEY"
```

Notable flags absent from this launch (required for native tool calling; Phase 2/3 will relaunch with them):

- `--enable-auto-tool-choice`
- `--tool-call-parser <gemma-4-appropriate parser>`
- `--enable-prefix-caching`
- `--gpu-memory-utilization 0.90`
- `--max-num-seqs 16`
- `--dtype bfloat16`

Model id reported by `GET /v1/models` at baseline: `google/gemma-4-31B-it` (max_model_len 32768).

## Revert procedure

If a v2 phase breaks the agent and we need to fall back to the Day-1 behavior:

1. **Stop any new vLLM processes** started on `:8001` / `:8002` / `:8003`:
   ```bash
   pkill -f "vllm.entrypoints.openai.api_server .*--port 800[123]" || true
   ```
2. **Confirm the Day-1 vLLM on `:8000` is still up** (it should not have been restarted yet; Phase 2 explicitly leaves it running):
   ```bash
   curl -s -H "Authorization: Bearer $PRIMARY_LLM_API_KEY" http://localhost:8000/v1/models
   ```
   If it has been stopped, relaunch with the command in the previous section.
3. **Reset the working tree to baseline:**
   ```bash
   git checkout main
   # or, to restore baseline on v2-rebuild directly:
   # git reset --hard b92ea34f12fb191bea8fff631cc31b7fd9643070
   ```
4. **Restore runtime env:** `cp .env.example .env` and set `PRIMARY_LLM_API_KEY` to the live vLLM key.
5. **Smoke test the Day-1 agent:**
   ```bash
   PYTHONPATH=/home/tusharmicro/metaboagent \
     python3 -m scripts.run_agent "Design a strain to produce lycopene"
   ```
   (Note: the baseline commit has broken imports in `ui/app.py`, `agent/metabo_agent.py`, `vectorstore/retriever.py`, and 4 tests because `agent/rag/` and `agent/router.py` were moved to `archive/`. To run the *original* working Day-1 agent, also restore those modules: `cp -r archive/agent_rag agent/rag && cp archive/agent_router.py agent/router.py`.)

## Rotate-the-key reminder

The API key `f9f9…08aae` was committed in plaintext to `config.py` before Phase 0. This repo had no git remote at the time, so it was never pushed, but:

- It has lived on a shared server since at least 2026-04-15.
- It is visible in the running vLLM process's `/proc/<pid>/cmdline`.

**Rotation is MANDATORY before the next vLLM restart.** Phase 2 relaunches vLLM (E4B on `:8001`, 26B MoE on `:8002`, with `--enable-auto-tool-choice`, etc.). That is the rotation window — do not start any new vLLM process with the old key. Procedure:

1. Generate a new key: `python3 -c "import secrets; print(secrets.token_hex(32))"`
2. Update `.env` (`PRIMARY_LLM_API_KEY=<new>`).
3. When launching the new vLLM processes in Phase 2, pass `--api-key "$PRIMARY_LLM_API_KEY"` (already using env substitution — do not paste the literal on the command line).
4. Leave the Day-1 `:8000` process running with the **old** key until Phase 2 validation is complete; kill it afterward (its argv is the last place the old key lives).
5. Verify with `curl -s -H "Authorization: Bearer $PRIMARY_LLM_API_KEY" http://localhost:8001/v1/models`.

---

## Known broken during rebuild

Baseline commit `b92ea34` intentionally leaves these imports broken — `agent/rag/` and `agent/router.py` were moved to `archive/` (gitignored) and will be reconstituted by later phases. Track here; strike through as they turn green.

| File | Broken import | Expected to turn green |
|---|---|---|
| `ui/app.py` | `from agent.rag import ...`, `from agent.rag.citation_verifier import ...` | Phase 5 (UI rebuild replaces this file entirely) — interim: Phase 1 shim at `agent/rag/__init__.py` re-exports from `vectorstore/` |
| `agent/metabo_agent.py` | `from agent.router import TASK_REACT_LOOP, build_llm_for` | Phase 3 (agent core rewrite replaces this file; `agent/router.py` rewritten for model-size routing) |
| `vectorstore/retriever.py` | `from agent.router import TASK_RERANK, build_llm_for` | Phase 3 (router rewrite) — interim: reranker call is optional, retriever should still work without it |
| `tests/test_citation_verifier.py` | `from agent.rag import ...` | Phase 1 shim |
| `tests/test_organism_resolver.py` | `from agent.rag import ...` | Phase 1 shim |
| `tests/test_rag_interfaces.py` | `from agent.rag.adapters import ...`, `from agent.rag.hybrid import ...`, `from agent.rag.interfaces import ...` | Phase 1 shim |
| `tests/test_rule_library.py` | `from agent.rag import ...` | Phase 1 shim |
| `tests/test_molecule_resolver.py` | `from agent.rag.interfaces import ...`, `from agent.rag.molecule_resolver import ...` | Phase 1 shim |
| `tests/test_router.py` | (verify at Phase 1 pytest run) | Phase 3 (new router) |

After Phase 1 lands the shim, all five `test_*_resolver.py` / `test_rag_*.py` / `test_rule_library.py` / `test_citation_verifier.py` files should at least *collect* (import without error). Full pass waits on Phase 3 for anything that transitively needs `agent.router`.

### Post-Phase-1 expected test state

After the Phase 1 commits (including `phase1: lazy-validate PRIMARY_LLM_API_KEY`), the only expected test failures are router/UI imports that need Phase 3:

- `tests/test_router.py` — cannot import `agent.router` (archived). Phase 3.
- `tests/test_ui_response_log.py` — collection error via `ui/app.py` → `agent.rag.citation_verifier`. The shim fixes the import path, but `ui/app.py` also transitively pulls `agent.metabo_agent` → `agent.router` (archived). Phase 3 rewrite.

`tests/test_config.py` and `tests/test_storage_paths.py` must pass from this commit forward — the import-time key raise has been replaced with a lazy `get_primary_llm_api_key()` helper, so reloading `config` with a clean env dict no longer crashes. If either of those files regresses, stop and investigate before continuing.

---

## Followups

- Firewall `:8000` / `:8001` / `:8002` to 127.0.0.1 + LAN CIDR only. Not done yet.
- vLLM streaming doesn't surface usage_metadata through LangChain at v0.19.0. `tokens_in` / `tokens_out` report as 0 in `Event{type=done}`. Affects eval harness (Phase 8) metrics. Workaround: non-streaming usage probe after stream, or local tokenization. Not blocking Phase 3.
- npm audit: 4 high-severity advisories in Next 14 transitive deps. Address before public deploy via Next 15 upgrade or `npm audit fix --force` with regression testing.
- `ui/web/public/favicon.ico` is a 32×32 PNG renamed. Replace with a true ICO via `png-to-ico` before public deploy if perfectionism matters.
- `ui/static/branding/` and `ui/web/public/branding/` hold duplicate source files. Add a sync script in 5.5 polish if drift becomes a concern.

---

## Service state (as of 2026-04-23, Phase 2 prep)

31B vLLM service stopped for Phase 2/3 dev. All 4 L40s freed. Restart via `sudo systemctl start vllm-gemma4` when needed (override.conf intact, key in `.env`, no code change required).
