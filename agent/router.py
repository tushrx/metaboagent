"""Model-tier dispatcher for the Gemma 4 family.

Three tiers — no heuristics, no auto-escalation, no service health check.
Tier selection happens upstream (UI toggle, user request, or agent-core
decision). This module only resolves tier → tools-bound ChatOpenAI.

  default    → E4B on :8001  (PRIMARY_LLM_* — set via .env)
  deep       → 26B MoE on :8002
  max_rigor  → 31B dense on :8000 (caller must ensure systemd service is up)

All three tiers share a single API key (PRIMARY_LLM_API_KEY / VLLM_API_KEY).
No instance cache: building ChatOpenAI per call costs microseconds and
avoids cross-tier state bleeding.
"""
from __future__ import annotations

from typing import Any, Literal, Sequence

from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from config import (
    DEEP_LLM_BASE_URL,
    DEEP_LLM_MODEL_NAME,
    MAX_RIGOR_LLM_BASE_URL,
    MAX_RIGOR_LLM_MODEL_NAME,
    PRIMARY_LLM_API_KEY,
    PRIMARY_LLM_BASE_URL,
    PRIMARY_LLM_MODEL_NAME,
)

ModelTier = Literal["default", "deep", "max_rigor"]

_TIER_ENDPOINTS: dict[str, tuple[str, str]] = {
    "default":   (PRIMARY_LLM_BASE_URL,    PRIMARY_LLM_MODEL_NAME),
    "deep":      (DEEP_LLM_BASE_URL,       DEEP_LLM_MODEL_NAME),
    "max_rigor": (MAX_RIGOR_LLM_BASE_URL,  MAX_RIGOR_LLM_MODEL_NAME),
}
_VALID_TIERS = tuple(_TIER_ENDPOINTS)


def _force_ipv4(url: str) -> str:
    """Swap ``localhost`` → ``127.0.0.1`` (Phase 2 IPv6-first refused lesson)."""
    return url.replace("localhost", "127.0.0.1")


def select_llm(
    tier: ModelTier,
    tools: Sequence[Any],
    temperature: float = 0.2,
) -> Runnable:
    """Build a tools-bound ChatOpenAI for the requested Gemma 4 tier.

    Args:
        tier: one of "default", "deep", "max_rigor".
        tools: LangChain tool objects to bind. May be an empty list.
        temperature: sampling temperature.

    Returns:
        A Runnable (ChatOpenAI wrapped by bind_tools) ready for
        .invoke() / .stream() / .ainvoke() / .astream().

    Raises:
        ValueError: if ``tier`` is outside the three valid names. Literal
            erases at runtime, so callers that bypass type-checking still
            get a clear failure here rather than a KeyError from the
            dispatch table.
    """
    if tier not in _VALID_TIERS:
        raise ValueError(
            f"Unknown tier: {tier!r}; expected one of {_VALID_TIERS}"
        )

    base_url, model = _TIER_ENDPOINTS[tier]
    llm = ChatOpenAI(
        model=model,
        base_url=_force_ipv4(base_url),
        api_key=PRIMARY_LLM_API_KEY or "none",
        temperature=temperature,
        timeout=120,
    )
    return llm.bind_tools(list(tools))
