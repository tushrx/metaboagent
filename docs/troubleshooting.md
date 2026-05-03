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

## Don't run `npm run build` while `next dev` is running

**Symptom.** Every page request to `http://127.0.0.1:3100` returns 500
with stacked `MODULE_NOT_FOUND` errors in `logs/online_ui.log` of the
form `Cannot find module './<chunk>.js'` originating from
`.next/server/webpack-runtime.js`.

**Cause.** Both `next dev` and `next build` write into
`ui/web/.next/`. A production build replaces the chunk-file layout that
the live dev server has cached in its in-memory webpack runtime. The
dev server then tries to `require('./<chunk>.js')` for chunk names that
no longer exist (or now sit at a different relative path). One
fingerprint to look for: `ls -la /proc/<dev-pid>/fd | grep '\.next/trace
(deleted)'` — the dev server is still holding a fd to a trace file that
something else unlinked.

**Recovery.** Kill the dev server, wipe `.next/`, restart:

```bash
PID=$(ss -tlnp | grep :3100 | grep -oP 'pid=\K\d+' | head -1)
kill -TERM "$PID" "$(ps -o ppid= -p "$PID" | tr -d ' ')"
rm -rf ui/web/.next
nohup npx --prefix ui/web next dev -p 3100 -H 127.0.0.1 \
  > logs/online_ui.log 2>&1 &
```

**How to verify a UI build is clean without clobbering dev.** Pick
whichever applies:

- `npx tsc --noEmit` (type-check only, doesn't touch `.next/`).
- `npm run lint` (eslint only).
- Stop dev, run `npm run build`, then restart dev.
- Or build into a separate output directory by setting
  `distDir` in `next.config.js` for that one build.
