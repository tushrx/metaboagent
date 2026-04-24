# Decisions

Short, dated notes on non-obvious conventions. Keep entries one-line where
possible. Newer entries go at the top.

## 2026-04-24 — glucose_shikimate replaced with resveratrol_ecoli in pathway eval

Phase 6.5.b diagnosis showed the original prompt ("glucose to shikimate in 3
steps") was biochemically infeasible — the real shikimate pathway from
glucose is 7+ enzymatic steps. Both E4B and 26B correctly declined to
fabricate a 3-step answer; measuring against an infeasible prompt told us
nothing about agent capability. Replacement prompt (`resveratrol_ecoli` —
tyrosine → p-coumaric acid → 4-coumaroyl-CoA → resveratrol via TAL / 4CL /
STS) preserves the 3-step microbial-design difficulty while being
biochemically sound and KEGG-covered end-to-end.

## 2026-04-23 — Tests use unittest (not pytest)

Tests use `unittest` (not pytest). Invocation: `python3 -m unittest`. Stay
consistent across the repo. Pytest is not installed in either the system
Python or the `gemma4` venv, and adding it would be a new dependency.
