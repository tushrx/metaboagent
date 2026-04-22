#!/usr/bin/env bash
# scripts/run_dev.sh — start MetaboAgent in development mode.
#
# Loads .env, turns Hugging Face offline mode on (weights are already cached
# under ~/.cache/huggingface), and launches the FastAPI backend + UI.
#
# Usage:   ./scripts/run_dev.sh
# Requires a running vLLM endpoint reachable at $PRIMARY_LLM_BASE_URL.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Load .env ---
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found at $REPO_ROOT/.env" >&2
  echo "       cp .env.example .env  and fill in PRIMARY_LLM_API_KEY." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${PRIMARY_LLM_API_KEY:?PRIMARY_LLM_API_KEY must be set in .env}"

# --- Hugging Face offline mode ---
# Safe to enable because Phase 1 verified PubMedBERT weights are cached at
# ~/.cache/huggingface/hub/models--microsoft--BiomedNLP-PubMedBERT-*
# (421 MB, pytorch_model.bin + config.json + tokenizer_config.json + vocab.txt).
# If you change EMBEDDING_MODEL_NAME to a model that is NOT cached, UNSET these
# two flags for a single warm-start, then re-enable them.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# --- Python path ---
export PYTHONPATH="$REPO_ROOT"

# --- Phase 1: retrieval smoke-test. Phase 4 replaces this block with ---
# --- `uvicorn app.server:app --host 0.0.0.0 --port 8080 --reload`.  ---
echo "[run_dev] PRIMARY_LLM_BASE_URL=${PRIMARY_LLM_BASE_URL:-http://localhost:8000/v1}"
echo "[run_dev] EMBEDDING_DEVICE=${EMBEDDING_DEVICE:-cuda:0}"
echo "[run_dev] HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1"
echo "[run_dev] Booting Retriever singleton (should log one PubMedBERT init)..."
python3 -c "from vectorstore.retriever import get_retriever; r = get_retriever(); print('[run_dev] retriever ready; device=', r.embedder.device)"

# Phase 4 will append:
#   exec uvicorn app.server:app --host 0.0.0.0 --port 8080 --reload
