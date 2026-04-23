# Decisions

Short, dated notes on non-obvious conventions. Keep entries one-line where
possible. Newer entries go at the top.

## 2026-04-23 — Tests use unittest (not pytest)

Tests use `unittest` (not pytest). Invocation: `python3 -m unittest`. Stay
consistent across the repo. Pytest is not installed in either the system
Python or the `gemma4` venv, and adding it would be a new dependency.
