# MetaboAgent

An evidence-grounded co-scientist for metabolic pathway engineering. Designs microbial production routes for medicines and sustainable chemicals (antimalarials, anticancer compounds, bio-based fragrances and fuels) by combining a 54k-document corpus (KEGG reactions/compounds + PubMed literature) with Gemma 4 function-calling and 15 specialized tools.

Built for the **Gemma 4 Good Hackathon** (Kaggle × Google DeepMind).

---

## Requirements

- Python 3.11+
- CUDA 12.x (4× NVIDIA L40 recommended; CPU-only also works with `EMBEDDING_DEVICE=cpu`)
- [vLLM](https://docs.vllm.ai) for serving Gemma 4 models
- Gemma 4 model weights downloaded via Hugging Face

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/tushrx/metaboagent.git
cd metaboagent
pip install -r requirements.txt --break-system-packages
```

### 2. Configure environment

Copy and fill in the required values:

```bash
cp .env.example .env   # then edit .env
```

Minimum `.env`:

```env
# API key configured in vLLM (--api-key flag)
PRIMARY_LLM_API_KEY=your-vllm-api-key
VLLM_API_KEY=your-vllm-api-key

# Set to cpu if GPUs are fully occupied by vLLM
EMBEDDING_DEVICE=cpu

# Path to Hugging Face model cache (where PubMedBERT weights are stored)
HF_HOME=/path/to/huggingface/cache
```

### 3. Start vLLM (Gemma 4)

**E4B — fast tool-calling tier (port 8001):**

```bash
bash scripts/serve_e4b.sh
```

**26B MoE — deep reasoning tier (port 8002, optional):**

```bash
bash scripts/serve_26b.sh
```

Both scripts require the model weights cached locally. Set `HF_HOME` to the directory where you downloaded the models.

### 4. Start the backend

```bash
bash scripts/run_server.sh
# or: uvicorn app.server:app --host 127.0.0.1 --port 8080
```

Health check:

```bash
curl http://localhost:8080/health
# {"default":"ok","deep":"ok","max_rigor":"down","overall":"degraded","demo_mode":false}
```

### 5. Start the UI

```bash
bash scripts/run_ui.py   # Gradio UI at http://localhost:7860
```

---

## Configuration

All settings are in `config.py` and driven by environment variables. Key overrides:

| Variable | Default | Description |
|---|---|---|
| `PRIMARY_LLM_BASE_URL` | `http://127.0.0.1:8001/v1` | vLLM E4B endpoint |
| `PRIMARY_LLM_MODEL_NAME` | `google/gemma-4-E4B-it` | Model name as served by vLLM |
| `PRIMARY_LLM_API_KEY` | — | Must match `--api-key` in vLLM |
| `DEEP_LLM_BASE_URL` | `http://127.0.0.1:8002/v1` | vLLM 26B MoE endpoint |
| `EMBEDDING_DEVICE` | `cuda:0` | `cpu` if GPU is occupied by vLLM |
| `HF_HOME` | `~/.cache/huggingface` | Hugging Face cache root |
| `METABOAGENT_CHROMADB_DIR` | `data/chromadb` | ChromaDB persistence directory |
| `DEMO_MODE` | `0` | Set to `1` to disable live fetches (offline demo) |

---

## Tools

15 tools available to the agent:

| Tool | Description |
|---|---|
| `search_kegg` | Semantic search over 12k KEGG reactions + 19k compounds |
| `search_literature` | Semantic search over 22k PubMed abstracts |
| `fetch_kegg_live` | Live KEGG API lookup by ID (C-, R-, K-, map-) |
| `fetch_pubmed_live` | Live PubMed search |
| `fetch_uniprot` | UniProt protein record fetch |
| `fetch_pubchem` | PubChem compound lookup |
| `fetch_sabio_rk` | SABIO-RK kinetic parameter fetch |
| `fetch_zinc` | ZINC compound lookup |
| `fetch_gene_sequence` | NCBI nucleotide sequence fetch |
| `compare_synthesis_routes` | Compare multiple biosynthesis routes |
| `retrosynthesis` | Retrosynthetic analysis |
| `verify_ec_number` | Validate EC numbers against KEGG |
| `enzyme_ranker` | Rank candidate enzymes for a reaction |
| `design_primers` | PCR primer design |
| `parse_structure_image` | Extract SMILES from a structure image (multimodal) |

---

## Architecture

```
User ──► FastAPI /chat (SSE stream) ──► Agent core
                                            │
                        ┌───────────────────┼──────────────────┐
                        ▼                   ▼                  ▼
                   Gemma 4 E4B        Gemma 4 26B MoE     Tools (15)
                   :8001 (default)    :8002 (deep)             │
                                                               ▼
                                                    ChromaDB (54k docs)
                                                    PubMedBERT embedder
```

The router selects E4B for quick tool calls and 26B MoE for multi-step pathway design. Events stream as JSON lines (`token`, `tool_call`, `tool_result`, `final_answer`, `done`).

---

## Demo mode (offline)

```bash
DEMO_MODE=1 bash scripts/run_demo.sh
```

Disables all live API fetches. All queries are answered from the local ChromaDB corpus.

---

## License

Apache 2.0
