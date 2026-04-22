# Infrastructure And Model Distribution Report

Date: 2026-04-20
Time checked: around 23:52 local host time

## Purpose

This report reviews the actual machine infrastructure and current runtime load, then recommends a proper model distribution strategy for better performance.

The focus is:
- CPU
- RAM
- GPU topology
- current model placement
- current load
- better default deployment layout

---

## 1. Host Summary

### Operating system
- Host: `dell`
- Kernel: `Linux 6.8.0-110-generic`
- OS family: Ubuntu Linux

### CPU
- CPU model: `Intel Xeon Silver 4514Y`
- Sockets: `2`
- Physical cores per socket: `16`
- Threads per core: `2`
- Total logical CPUs: `64`
- NUMA nodes: `2`

### Memory
- Total RAM: `125 GiB`
- Used RAM: `24 GiB`
- Free RAM: `35 GiB`
- Buff/cache: `66 GiB`
- Available RAM: `100 GiB`
- Swap: `126 GiB`
- Swap used: `0`

### Disk
- Root disk `/`: `440G total`, `354G used`, `64G available`, `85% used`
- Secondary storage `/mnt/storage_sdd`: `1.8T total`, `128G used`, `1.6T available`, `8% used`

### GPU
- GPUs: `4 x NVIDIA L40`
- VRAM per GPU: `46068 MiB`
- Driver: `590.48.01`
- CUDA: `13.1`

---

## 2. Current System Load

### CPU load
- Uptime load averages: `0.16, 0.14, 0.12`
- `vmstat` snapshot shows CPUs mostly idle: `99-100% idle`

Assessment:
- CPU is heavily underutilized right now.
- There is no CPU bottleneck at the time of inspection.

### Memory load
- Available memory remains high at about `100 GiB`
- Swap usage is `0`

Assessment:
- RAM headroom is strong.
- The system is not memory-constrained.

### Disk load
- Root volume is at `85%`

Assessment:
- This is the main infrastructure risk outside GPU allocation.
- Root has limited headroom for logs, caches, temporary model artifacts, package installs, and expanded datasets.
- Large data, Chroma persistence, and model caches should preferentially live on `/mnt/storage_sdd`.

---

## 3. Current Running AI/Inference Processes

Observed major processes:
- `python3 -m scripts.run_ui`
- `vllm.entrypoints.openai.api_server --model google/gemma-4-31B-it --tensor-parallel-size 4`
- `VLLM::EngineCore`
- `VLLM::Worker_TP0`
- `VLLM::Worker_TP1`
- `VLLM::Worker_TP2`
- `VLLM::Worker_TP3`

Relevant process memory snapshot:
- API server RSS: about `2.2 GiB`
- EngineCore RSS: about `1.1 GiB`
- Each TP worker RSS: about `3.8 GiB`
- UI process RSS: about `1.9 GiB`

Important note:
- The GPU-resident footprint is much larger than host RSS. VRAM use is what matters most for the active model.

---

## 4. Current GPU Allocation

### Actual placement

All four GPUs are occupied by a single vLLM deployment:
- Model: `google/gemma-4-31B-it`
- Tensor parallel size: `4`

### Per-GPU usage
- GPU0: `43971 / 46068 MiB`
- GPU1: `43971 / 46068 MiB`
- GPU2: `43971 / 46068 MiB`
- GPU3: `43971 / 46068 MiB`

Approximate free VRAM per GPU:
- about `2.1 GiB`

### GPU utilization at time of check
- GPU util was `0%` on all cards
- Power draw remained around `78-79W`

Assessment:
- The model is fully resident in VRAM and keeping all 4 GPUs reserved.
- At the moment of inspection, the system was not actively serving significant inference traffic.
- This is a valid configuration for maximum single-model capability, but not the best default for overall system efficiency.

---

## 5. GPU Topology And NUMA Implications

Topology summary:
- GPU0 and GPU1 are close to each other within NUMA node 0
- GPU2 and GPU3 are close to each other within NUMA node 1
- Cross-pair communication between `(0,1)` and `(2,3)` crosses system interconnect (`SYS`)

Assessment:
- A 4-way tensor-parallel model spans both NUMA domains.
- That is acceptable when the single-model requirement is more important than efficiency.
- But it is not the cleanest topology for latency or locality.

Practical implication:
- Two independent 2-GPU model groups would align more naturally with the physical topology:
  - Group A: GPU0 + GPU1 on NUMA node 0
  - Group B: GPU2 + GPU3 on NUMA node 1

---

## 6. Was The Current Default Reasonable?

## Short answer

Yes, for one specific goal:
- maximize one model’s capability with the largest model that comfortably fits across all 4 GPUs

No, as a general default for a scientific assistant stack.

## What is good about the current default

- It gives one strong model the full machine.
- It is simple to operate.
- It leaves CPU free for retrieval, UI, indexing orchestration, and embeddings.
- It likely supports high context and stronger reasoning quality than a smaller single-node model.

## What is bad about the current default

- It consumes all GPU capacity even when idle.
- It leaves almost no VRAM headroom per card.
- It prevents concurrent GPU-resident services.
- It gives no room for:
  - reranker models on GPU
  - specialized chemistry/biology models
  - batch embedding on GPU
  - a second low-latency inference endpoint
- It spans both NUMA domains, which is less clean than 2-GPU pair deployments.

Conclusion:
- The current setup is acceptable if the machine is dedicated to one single large reasoning model.
- It is not the proper default if the goal is a balanced multi-service scientific platform.

---

## 7. Proper Default Infrastructure Strategy

The right default depends on product intent.

### Option A: Single flagship model mode

Use this if the only priority is best-answer quality from one general model.

Recommended shape:
- 1 large reasoning model across all 4 GPUs
- CPU embeddings
- no second GPU service

Pros:
- maximum model quality
- simplest serving setup

Cons:
- poor overall resource efficiency
- no GPU elasticity
- little room for additional services

This is close to the current configuration.

### Option B: Balanced scientific platform mode

Use this if the product is a real multi-tool scientific workspace.

Recommended shape:
- GPU0 + GPU1: primary reasoning model
- GPU2 + GPU3: secondary service pool

Possible secondary service pool uses:
- faster smaller assistant model
- reranker / verifier
- chemistry-specialized model
- batch jobs

Pros:
- better topology alignment
- better concurrency
- room for specialized workloads
- safer operationally

Cons:
- primary model may need to be smaller than the current 31B TP=4 layout

This is the better default for a platform.

### Option C: Throughput-oriented split serving

Use this if multiple users or multiple simultaneous tasks matter more than one-model maximum size.

Recommended shape:
- 2 independent inference servers
- one on GPU0 + GPU1
- one on GPU2 + GPU3

Pros:
- better concurrent serving
- failure isolation
- topology-aware deployment

Cons:
- no single giant model unless it fits on 2 GPUs

---

## 8. Recommended Model Distribution For This Machine

If this host is meant to power a serious biochemistry + microbiology + chemistry expert system, my recommendation is:

## Recommended default

### Layout
- `GPU0 + GPU1`: primary reasoning model
- `GPU2 + GPU3`: secondary scientific services

### CPU
- Keep embedding model on CPU by default
- Keep Chroma / retrieval / indexing on CPU and RAM

### RAM usage model
- RAM is not the bottleneck here
- use RAM aggressively for:
  - caches
  - retrieval indexes
  - literature preprocessing
  - batch parsing

### Disk placement
- move large mutable assets off root to `/mnt/storage_sdd`
- especially:
  - Chroma persistence
  - raw data
  - processed data
  - Hugging Face caches
  - logs

---

## 9. Recommended Roles By Resource Type

### GPUs

Best use:
- LLM inference
- optional rerankers
- optional chemistry-specialized inference

Do not waste all 4 GPUs on one model by default unless quality requirements force it.

### CPUs

Best use:
- embeddings if throughput is moderate
- parsing
- indexing
- retrieval orchestration
- API/UI/backend logic
- periodic ETL

This host has enough CPU for those jobs comfortably.

### RAM

Best use:
- DB cache
- vector retrieval cache
- OS page cache for data files
- document preprocessing
- larger retrieval working sets

### Secondary SSD

Best use:
- all high-churn storage
- all large scientific datasets
- model caches

---

## 10. Operational Assessment

### Current state

CPU:
- healthy
- lightly loaded

RAM:
- healthy
- plenty of free capacity

GPU:
- fully allocated
- no practical spare capacity for additional GPU services

Disk:
- root is the weakest point

### Overall assessment

The host is strong enough for a serious scientific AI stack.

But the current default deployment is skewed toward:
- one large model
- low concurrency
- low GPU flexibility

instead of:
- balanced platform performance
- topology-aware serving
- room for specialist services

---

## 11. Best-Practice Recommendation

If I were setting this up properly by default, I would use:

### Default production layout
- 2 GPUs for primary reasoning model
- 2 GPUs for secondary model or scientific utility services
- embeddings on CPU
- all large data and caches on secondary SSD
- explicit CPU/NUMA affinity for model servers where possible

### When to keep the current 4-GPU layout
- if one flagship model is the only real workload
- if answer quality is clearly better and worth the full-machine reservation
- if concurrent users and multi-model services do not matter

### When to change immediately
- if you want faster multi-user responsiveness
- if you want verifier/reranker services
- if you want chemistry and biology specialists running side by side
- if you plan to scale the product beyond one operator

---

## 12. Concrete Action Items

1. Move dataset, Chroma, logs, and model caches from root volume to `/mnt/storage_sdd`.
2. Decide whether the product is:
   - single flagship model first, or
   - balanced multi-service scientific platform.
3. If platform-first, split GPU allocation into:
   - `(0,1)`
   - `(2,3)`
4. Add NUMA-aware process pinning for inference workers.
5. Reserve GPU headroom instead of running at near-full VRAM on every device.
6. Add monitoring for:
   - GPU util
   - VRAM util
   - request latency
   - queue depth
   - root disk usage

---

## 13. Final Verdict

The infrastructure itself is strong:
- 64 logical CPUs
- 125 GiB RAM
- 4 x L40
- large secondary SSD

The current deployment is not wrong, but it is optimized for one large model, not for best overall platform performance.

Proper default for this machine:
- use CPU and RAM for retrieval/indexing,
- use the secondary SSD for data,
- and distribute GPU models in 2-GPU NUMA-aligned groups unless a single 4-GPU flagship model is strictly required.
