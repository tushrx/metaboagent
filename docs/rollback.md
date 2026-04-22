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

Rotate before making the repo public. After rotation, update `.env`, kill + relaunch vLLM with the new `--api-key`, and verify with the curl snippet above.
