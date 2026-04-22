# Target Deployment Layout For This Repository

Date: 2026-04-20

## Goal

This document turns the infrastructure assessment into a concrete deployment layout for this repository.

It answers:
- which service should run where
- how GPUs should be assigned
- what should stay on CPU
- where data should live
- what the default production topology should be

---

## 1. Recommended Deployment Mode

For this repository, the best target layout is:

## Balanced scientific platform mode

Not:
- one giant 4-GPU model as the only service

But:
- one primary reasoning service
- one secondary utility / fast-response service
- CPU-based retrieval and indexing
- storage moved off the root volume

Reason:
- this repo is not just an LLM wrapper
- it includes retrieval, live tools, UI, ingestion, and scientific workflows
- the platform benefits more from balanced concurrency and specialized services than from spending all 4 GPUs on one idle model

---

## 2. Target Service Topology

## Final recommended layout

### GPU group A: primary reasoning
- GPUs: `0,1`
- NUMA: node `0`
- Role: main scientific reasoning model
- Consumers:
  - UI requests
  - CLI requests
  - design workflows
  - compare workflows
  - investigation workflows

### GPU group B: secondary inference / utility
- GPUs: `2,3`
- NUMA: node `1`
- Role: one of the following, depending on priority

Preferred order:
1. fast low-latency assistant model
2. verifier / reranker / citation-check model
3. chemistry-specialized model
4. overflow inference capacity

### CPU services
- Gradio UI
- API/backend service
- Chroma / vector retrieval
- ingestion
- KEGG/PubMed parsing
- embedding jobs by default
- scheduled data refresh

### Storage
- root disk: code + OS only
- secondary SSD: data + model cache + logs + Chroma persistence

---

## 3. Concrete Service Assignment

## Service 1: Main reasoning model

### Purpose
This is the model that writes the final scientific answer.

### Placement
- GPUs: `0,1`
- CPU affinity: NUMA node `0`

### Responsibilities
- orchestrator reasoning
- tool selection
- synthesis of final answer
- structured report generation

### Endpoint
- suggested port: `8000`

### Why this placement
- keeps the primary user-facing model on one NUMA-local GPU pair
- reduces cross-node overhead relative to a 4-GPU-wide deployment
- leaves room for a second inference service

---

## Service 2: Fast utility model

### Purpose
Use this service for lower-latency auxiliary tasks.

### Placement
- GPUs: `2,3`
- CPU affinity: NUMA node `1`

### Candidate uses
- answer drafting
- route classification
- citation verification prompts
- reranking or judge-style calls
- fallback assistant responses
- experiment-plan expansion

### Endpoint
- suggested port: `8001`

### Why this placement
- isolates secondary traffic from the main model
- gives a clean split by NUMA topology
- supports future multi-user behavior better than a single 4-GPU service

---

## Service 3: UI server

### Placement
- CPU only

### Current repo mapping
- `python3 -m scripts.run_ui`

### Recommendation
- keep UI process off GPU
- keep it lightweight
- configure it to call the primary model by default
- optionally send:
  - short classification tasks to utility model
  - final answers to primary model

---

## Service 4: Retrieval and vector database

### Placement
- CPU + RAM

### Current repo mapping
- `vectorstore/`
- Chroma persistence
- embedding model load path

### Recommendation
- keep retrieval on CPU
- use available RAM aggressively for cache efficiency
- do not move Chroma to GPU

Reason:
- CPU and RAM are abundant on this host
- GPU time is more valuable for inference

---

## Service 5: Embedding pipeline

### Default placement
- CPU

### Current repo mapping
- `vectorstore/embedder.py`
- `vectorstore/indexer.py`
- `vectorstore/live_indexer.py`

### Recommendation
- keep embeddings on CPU by default
- optionally create a batch-only GPU embedding mode later

Why:
- current CPU headroom is strong
- GPU capacity is the scarce resource
- embedding jobs are not the current bottleneck

---

## Service 6: Ingestion and ETL

### Placement
- CPU only

### Current repo mapping
- `scripts/ingest_all.py`
- `data/ingestion/`

### Recommendation
- run ingestion as background or scheduled jobs
- do not colocate ingestion assumptions with GPU model lifecycle
- isolate fetch/index schedules from interactive serving

---

## 4. Storage Layout

## Current risk

Root volume is already at high usage.

That is not a good long-term default for:
- raw scientific datasets
- Chroma persistence
- model caches
- logs

## Recommended target layout

### Keep on root
- repo checkout
- virtualenvs if small
- service definitions
- OS packages

### Move to `/mnt/storage_sdd`
- `data/raw/`
- `data/processed/`
- `data/chromadb/`
- `logs/`
- Hugging Face cache
- any model download cache
- generated reports / large artifacts

## Suggested target paths

- `/mnt/storage_sdd/metaboagent/data/raw`
- `/mnt/storage_sdd/metaboagent/data/processed`
- `/mnt/storage_sdd/metaboagent/data/chromadb`
- `/mnt/storage_sdd/metaboagent/logs`
- `/mnt/storage_sdd/hf-cache`

## Repo-facing method

Either:
1. replace repo-local directories with symlinks, or
2. make all paths configurable via environment variables

Preferred:
- environment-configurable paths in `config.py`

---

## 5. Model Routing Policy

To use two inference services correctly, the app should not send everything to the same model.

## Recommended routing rules

### Send to primary model
- full design requests
- pathway design
- compare-route tasks
- troubleshooting tasks
- final answer synthesis

### Send to utility model
- classify the request
- rewrite retrieval queries
- summarize retrieved evidence
- verify answer consistency
- rank candidate snippets
- generate shorter follow-up answers

This routing gives better perceived performance and preserves expensive model capacity.

---

## 6. Recommended Process Topology

## Process group A

### Primary inference service
- model server on GPUs `0,1`
- port `8000`
- CPU affinity aligned to NUMA node `0`

### Attached consumers
- main UI requests
- CLI requests

## Process group B

### Utility inference service
- model server on GPUs `2,3`
- port `8001`
- CPU affinity aligned to NUMA node `1`

### Attached consumers
- background reasoning jobs
- verifier flows
- fast-path tasks

## Process group C

### App + retrieval services
- Gradio UI
- API layer
- ChromaDB
- ingestion scheduler
- all on CPU

---

## 7. Deployment Profiles

## Profile A: Research workstation default

Use when:
- one operator
- interactive use
- moderate throughput

Recommended:
- primary model on `0,1`
- utility model on `2,3`
- CPU retrieval
- SSD-backed data

This should be the default for this repo.

## Profile B: Maximum-answer-quality mode

Use when:
- only one user
- absolute best reasoning quality matters
- no need for secondary GPU services

Recommended:
- one large model on `0,1,2,3`
- CPU retrieval
- no utility service

This matches the current spirit of deployment, but should be treated as a special mode, not the default.

## Profile C: Higher-concurrency mode

Use when:
- multiple users
- latency matters
- answers can come from a somewhat smaller main model

Recommended:
- one model on `0,1`
- one model on `2,3`
- app routes based on task class

---

## 8. Repo-Specific Changes Needed

To support the target deployment cleanly, this repository should eventually add:

### A. Configurable infrastructure paths

In `config.py`, make these configurable:
- data root
- raw data dir
- processed data dir
- Chroma dir
- log dir
- model base URL(s)

### B. Multiple model endpoints

Instead of one:
- `VLLM_BASE_URL`

Support:
- `PRIMARY_LLM_BASE_URL`
- `UTILITY_LLM_BASE_URL`

And optionally:
- `PRIMARY_LLM_MODEL_NAME`
- `UTILITY_LLM_MODEL_NAME`

### C. Request router

Add a small routing layer so:
- complex answer synthesis -> primary model
- support tasks -> utility model

### D. Better infra profile selection

Add deployment profiles such as:
- `single_flagship`
- `balanced`
- `throughput`

---

## 9. Monitoring Requirements

For this target layout, add monitoring for:

### GPU metrics
- utilization
- memory used
- memory free
- power draw
- temperature

### Model server metrics
- request count
- queue depth
- token throughput
- latency percentiles
- error rates

### Host metrics
- root disk usage
- SSD usage
- RAM available
- CPU saturation
- swap usage

### Retrieval metrics
- Chroma latency
- embedding latency
- ingestion duration

---

## 10. Recommended Default For This Repository

If I had to set one proper default for this exact repo today, it would be:

## Default

- Main reasoning model on GPUs `0,1`
- Utility / verifier model on GPUs `2,3`
- UI on CPU
- Retrieval on CPU
- Embeddings on CPU
- All large data moved to `/mnt/storage_sdd`

## Why this is the best default

- matches the physical topology better
- preserves strong reasoning capability
- creates room for specialized scientific services
- improves future concurrency
- reduces the cost of idle GPU reservation
- fits the actual architecture of this repo better than a single giant model does

---

## 11. What To Keep As Override Modes

Keep these as explicit override modes:

### `single_flagship`
- all 4 GPUs on one model
- best for solo deep reasoning sessions

### `balanced`
- split `0,1` and `2,3`
- best default

### `throughput`
- multiple smaller services
- best for more users or batch workloads

---

## 12. Final Recommendation

For this repository, the proper target deployment is not “put everything behind one 4-GPU model.”

The proper deployment is:
- split GPU capacity by NUMA-local pairs,
- keep retrieval and embeddings on CPU,
- move data and caches to the large SSD,
- and route tasks between a primary reasoning model and a secondary utility model.

That gives the best balance of:
- reasoning quality
- responsiveness
- flexibility
- and infrastructure efficiency.
