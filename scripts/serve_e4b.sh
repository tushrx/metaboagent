#!/usr/bin/env bash
set -euo pipefail
cd /home/tusharmicro/metaboagent
source .env
export HF_HOME=/mnt/storage_sdd/huggingface
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export CUDA_VISIBLE_DEVICES=0
mkdir -p logs
exec /home/tusharmicro/llm/gemma4/.venv/bin/python3 -m vllm.entrypoints.openai.api_server \
    --model google/gemma-4-E4B-it \
    --host 0.0.0.0 --port 8001 \
    --trust-remote-code \
    --max-model-len 32768 \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.90 \
    --max-num-seqs 16 \
    --enable-prefix-caching \
    --enable-auto-tool-choice \
    --tool-call-parser gemma4 \
    >> logs/vllm_e4b.log 2>&1
