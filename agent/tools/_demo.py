"""Shared DEMO_MODE helpers for live-fetch tools.

Phase 7 contract: when the environment variable ``DEMO_MODE=1`` is set,
no tool may make outbound HTTP calls. Live-fetch tools short-circuit at
the top of the function and either return a cached real result (Phase
7.3 — the demo cache) or a structured stub directing the agent to use
the indexed-corpus search tools instead (Phase 7.1 — the original
contract).

The verify_* tools (verify_kegg_reaction, verify_ec_number) wired their
own stubs in Phase 6.5.a and intentionally return a slightly different
shape (``exists: False``); they are not consumers of this helper.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_CACHE_DIR = REPO_ROOT / "data" / "demo_cache"


def is_demo_mode() -> bool:
    """True when DEMO_MODE=1 is set. Centralised so tests can monkey-patch
    one place if the contract ever changes."""
    return os.environ.get("DEMO_MODE") == "1"


def _canonical_args(args: dict[str, Any]) -> str:
    """Stable string key for cache lookup. None / empty-string-valued args
    are stripped so calls with and without optional defaults collide."""
    cleaned = {k: v for k, v in args.items() if v not in (None, "")}
    return json.dumps(cleaned, sort_keys=True, ensure_ascii=False)


# Lazily populated map: (tool_name, canonical_args_str) -> result_string.
# Loaded once on first lookup; reset by tests via _reset_cache().
_CACHE: dict[tuple[str, str], str] | None = None


def _reset_cache() -> None:
    """Test hook: forces the next lookup to re-read the cache directory."""
    global _CACHE
    _CACHE = None


def _load_cache() -> dict[tuple[str, str], str]:
    """Aggregate every data/demo_cache/<query_id>/tool_calls.json into a
    single (tool_name, canonical_args) -> result map. Bad / missing files
    are warned and skipped — cache must never crash the tool path."""
    cache: dict[tuple[str, str], str] = {}
    if not DEMO_CACHE_DIR.exists():
        return cache
    for sub in sorted(DEMO_CACHE_DIR.iterdir()):
        if not sub.is_dir():
            continue
        path = sub / "tool_calls.json"
        if not path.exists():
            continue
        try:
            with path.open() as f:
                entries = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("demo cache: skipping malformed %s: %s", path, e)
            continue
        if not isinstance(entries, list):
            log.warning("demo cache: %s is not a list, skipping", path)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            tool = entry.get("tool_name")
            args = entry.get("args")
            result = entry.get("result")
            if not isinstance(tool, str) or not isinstance(args, dict):
                continue
            if not isinstance(result, str):
                # Tool results are JSON strings on the wire; coerce dicts
                # for forward-compat with hand-edited cache files.
                try:
                    result = json.dumps(result, ensure_ascii=False)
                except (TypeError, ValueError):
                    continue
            cache[(tool, _canonical_args(args))] = result
    return cache


def lookup_demo_cache(tool_name: str, args: dict[str, Any]) -> str | None:
    """Return a cached tool-result string for (tool, args), or None if no
    matching entry exists in data/demo_cache/. Lazy-loaded once per
    process; safe to call from any tool body."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_cache()
    return _CACHE.get((tool_name, _canonical_args(args)))


def cached_or_stub(
    tool_name: str,
    *,
    fallback: str | None = None,
    **args: Any,
) -> str:
    """DEMO_MODE entrypoint for live-fetch tools.

    Resolution order:
        1. If a cache entry matches (tool_name, args), return it.
        2. Otherwise return the demo stub (with optional fallback hint).

    Callers must already have checked ``is_demo_mode()``. This helper
    does NOT re-check, so the live-call path stays untouched.
    """
    cached = lookup_demo_cache(tool_name, args)
    if cached is not None:
        return cached
    return stub(tool_name, fallback=fallback, **args)


def stub(tool_name: str, *, fallback: str | None = None, **args: Any) -> str:
    """Return a JSON-string stub matching the live-fetch tools' return shape.

    Args:
        tool_name: name of the calling tool, surfaced back to the agent.
        fallback: name of the indexed-corpus tool the agent should use
            instead (e.g. ``"kegg_search"``, ``"literature_search"``).
            Omit when no indexed alternative exists.
        **args: the calling tool's arguments, echoed for traceability.

    Returns:
        JSON string with keys: ``demo_mode`` (true), ``tool`` (name),
        ``message`` (human-readable note), ``args`` (echoed input),
        ``fallback`` (suggested indexed-corpus tool, optional).
    """
    if fallback is not None:
        message = (
            f"Live fetch disabled in demo mode. Immediately call {fallback} "
            f"now with the same query — do not ask the user for permission, "
            f"do not stop here. Compose your final answer ONLY after that "
            f"call returns. Do NOT claim information came from the indexed "
            f"corpus unless you actually called an indexed-corpus tool this turn."
        )
    else:
        message = (
            f"Live fetch disabled in demo mode. No indexed-corpus equivalent "
            f"for {tool_name} exists. Tell the user honestly that this lookup "
            f"is unavailable in demo mode rather than fabricating information."
        )
    payload: dict[str, Any] = {
        "demo_mode": True,
        "tool": tool_name,
        "message": message,
        "args": args,
    }
    if fallback is not None:
        payload["fallback"] = fallback
    return json.dumps(payload, ensure_ascii=False)
