"""Bounded-window chat history with lazy summarization and call dedup.

Per CLAUDE.md §6 Milestone 3.3. The sliding window keeps the last
``_RECENT_KEEP`` user/assistant turns verbatim. Older turns collapse
into a single summary sentence generated lazily on first overflow.
Tool calls and tool results are agent-loop-local; they never enter the
bounded window returned to the next turn's LLM call.

The summary LLM defaults to whichever endpoint ``config.PRIMARY_LLM_*``
resolves to (E4B on :8001 in the current deployment). The constructor
accepts ``summary_llm_factory`` so tests can inject a mock.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from config import PRIMARY_LLM_API_KEY, PRIMARY_LLM_BASE_URL, PRIMARY_LLM_MODEL_NAME

# Keep the last 2 user + last 2 assistant turns verbatim. Under normal
# strictly-alternating chat (U A U A …) that is exactly the last 4 turns.
_RECENT_USER_KEEP = 2
_RECENT_ASSISTANT_KEEP = 2
_RECENT_KEEP = _RECENT_USER_KEEP + _RECENT_ASSISTANT_KEEP

_SUMMARY_SYSTEM = (
    "Summarize these prior conversation turns in ONE sentence. Preserve: "
    "the compound or pathway being discussed, any user preferences, and "
    "any concluded decisions. No preamble, no closer — just the sentence."
)


def _force_ipv4(url: str) -> str:
    """Swap ``localhost`` → ``127.0.0.1`` (Phase 2 IPv6-first refused lesson)."""
    return url.replace("localhost", "127.0.0.1")


def _canonicalize(value: Any) -> Any:
    """Strip whitespace in string leaves, normalize dicts/lists recursively."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    return value


def _call_signature(tool_name: str, args: dict[str, Any]) -> str:
    canon = _canonicalize(args)
    return f"{tool_name}::{json.dumps(canon, sort_keys=True, ensure_ascii=False)}"


class History:
    """Per-session conversation state with bounded window + lazy recap + dedup.

    The public surface:
        add_user_turn / add_assistant_turn / add_tool_result  — appenders
        bounded_messages(system_prompt)                        — LLM-ready list
        check_and_record_call(tool_name, args)                 — dedup gate
    """

    def __init__(
        self,
        *,
        summary_llm_factory: Optional[Callable[[], BaseChatModel]] = None,
    ) -> None:
        self._messages: list[BaseMessage] = []
        self._summary: Optional[str] = None
        self._summary_covers: int = 0
        self._prior_calls: set[str] = set()
        self._summary_llm_factory = summary_llm_factory or _default_summary_llm

    # ---- appenders --------------------------------------------------------

    def add_user_turn(self, content: str) -> None:
        self._messages.append(HumanMessage(content=content))
        # Each new user turn starts a fresh dedup window — the archived
        # metabo_agent.py behavior we are preserving.
        self._prior_calls.clear()

    def add_assistant_turn(
        self, content: str, tool_calls: Optional[list] = None,
    ) -> None:
        self._messages.append(
            AIMessage(content=content, tool_calls=tool_calls or [])
        )

    def add_tool_result(
        self, tool_call_id: str, content: str, is_error: bool = False,
    ) -> None:
        self._messages.append(
            ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
                status="error" if is_error else "success",
            )
        )

    # ---- LLM-ready slice --------------------------------------------------

    def bounded_messages(self, system_prompt: str) -> list[BaseMessage]:
        """Return [SystemMessage, optional summary HumanMessage, ≤4 recent turns]."""
        turns = self._clean_turns()
        out: list[BaseMessage] = [SystemMessage(content=system_prompt)]

        if len(turns) <= _RECENT_KEEP:
            out.extend(turns)
            return out

        split = len(turns) - _RECENT_KEEP
        older = turns[:split]
        recent = turns[split:]
        summary = self._ensure_summary(older)
        out.append(
            HumanMessage(
                content=f"[{len(older)} earlier turns summarized: {summary}]"
            )
        )
        out.extend(recent)
        return out

    # ---- call dedup -------------------------------------------------------

    def check_and_record_call(
        self, tool_name: str, args: dict[str, Any],
    ) -> bool:
        """Return True for a fresh call (and record it); False on repeat."""
        sig = _call_signature(tool_name, args)
        if sig in self._prior_calls:
            return False
        self._prior_calls.add(sig)
        return True

    # ---- internals --------------------------------------------------------

    def _clean_turns(self) -> list[BaseMessage]:
        """User turns + final-answer assistant turns only. AIMessages with
        tool_calls (intermediate steps) and ToolMessages are agent-loop-local
        and do not cross turn boundaries."""
        return [
            m for m in self._messages
            if isinstance(m, HumanMessage)
            or (isinstance(m, AIMessage) and not getattr(m, "tool_calls", []))
        ]

    def _ensure_summary(self, older: list[BaseMessage]) -> str:
        if self._summary is not None and self._summary_covers == len(older):
            return self._summary
        llm = self._summary_llm_factory()
        prompt = [
            SystemMessage(content=_SUMMARY_SYSTEM),
            HumanMessage(
                content="\n\n".join(self._render_turn(m) for m in older)
            ),
        ]
        resp = llm.invoke(prompt)
        text = getattr(resp, "content", resp)
        self._summary = str(text).strip()
        self._summary_covers = len(older)
        return self._summary

    @staticmethod
    def _render_turn(m: BaseMessage) -> str:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        return f"{role}: {m.content}"


def _default_summary_llm() -> BaseChatModel:
    """Build the default summary LLM lazily so tests can skip the import."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=PRIMARY_LLM_MODEL_NAME,
        base_url=_force_ipv4(PRIMARY_LLM_BASE_URL),
        api_key=PRIMARY_LLM_API_KEY or "none",
        temperature=0.0,
        max_tokens=120,
        timeout=30,
    )
