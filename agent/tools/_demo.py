"""Shared DEMO_MODE helpers for live-fetch tools.

Phase 7 contract: when the environment variable ``DEMO_MODE=1`` is set,
no tool may make outbound HTTP calls. Live-fetch tools short-circuit at
the top of the function and return a structured stub directing the
agent to use the indexed-corpus search tools instead.

The verify_* tools (verify_kegg_reaction, verify_ec_number) wired their
own stubs in Phase 6.5.a and intentionally return a slightly different
shape (``exists: False``); they are not consumers of this helper.
"""
from __future__ import annotations

import json
import os
from typing import Any


def is_demo_mode() -> bool:
    """True when DEMO_MODE=1 is set. Centralised so tests can monkey-patch
    one place if the contract ever changes."""
    return os.environ.get("DEMO_MODE") == "1"


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
    payload: dict[str, Any] = {
        "demo_mode": True,
        "tool": tool_name,
        "message": "live fetch disabled (DEMO_MODE=1); using indexed corpus only",
        "args": args,
    }
    if fallback is not None:
        payload["fallback"] = fallback
    return json.dumps(payload, ensure_ascii=False)
