# Troubleshooting

## Embedder segfault on `cuda:0` when vLLM is running

**Symptom.** `eval_pathway_hallucination` (and any other eval that loads
PubMedBERT) segfaults with no Python traceback after the first run when
vLLM E4B is also occupying `cuda:0`.

**Cause.** vLLM E4B holds ~92% of `cuda:0` (~42 GB / 46 GB). Loading the
PubMedBERT embedder into the remaining headroom on the same device
triggers an OOM-driven CUDA segfault during model init — Python dies
without a traceback because the fault is below the Python layer.

**Fix.** Pin the embedder to a different GPU before launching the eval:

```bash
export EMBEDDING_DEVICE=cuda:3   # the multimodal-reserved GPU is empty
```

Used in `/tmp/ph_variance.sh` and any 3-run measurement driver. The
config knob is read by `vectorstore/retriever.py` at embedder init.

**Why this will bite again.** Anyone running evals in parallel without
checking `nvidia-smi` first will hit it. The default device picker walks
GPUs in order and `cuda:0` is normally the lowest-pressure GPU on a fresh
box — with vLLM running it's the highest. If you add another GPU-resident
model (reranker, vision encoder), pick a free GPU explicitly rather than
relying on the default.
