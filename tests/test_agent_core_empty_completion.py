"""Tests for the Phase 6.5.c H4 empty-completion nudge-retry.

After a successful tool call E4B occasionally emits an AIMessage with
zero content AND zero tool_calls and finish_reason=stop. The agent
detects this, injects a one-time HumanMessage nudge, and re-invokes
the LLM. A second consecutive empty response is surfaced as a clean
``error`` event rather than a silent empty ``final_answer``.

Reuses the scripted-stream harness from test_agent_core.

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_agent_core_empty_completion
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from langchain_core.messages import HumanMessage

from agent.core import run_agent
from tests.test_agent_core import (  # reuse helpers
    _ai,
    _drain,
    _make_scripted_stream,
    _tc,
    echo_tool,
)


class _EmptyCompletionBase(unittest.IsolatedAsyncioTestCase):
    """Smaller harness than _CoreTestBase so we can start/stop patches
    twice inside one test (needed by the nudge-counter-resets test)."""

    def _start_patches(self, turns, tools):
        fake = _make_scripted_stream(turns)
        sel = patch("agent.core.select_llm", return_value=MagicMock())
        stm = patch("agent.core._stream_llm", fake)
        reg = patch("agent.core.build_tool_registry", return_value=tools)
        sel.start(); stm.start(); reg.start()
        return (sel, stm, reg)

    def _stop_patches(self, patches):
        for p in patches:
            p.stop()

    async def _run_once(self, turns, tools):
        patches = self._start_patches(turns, tools)
        try:
            events = await _drain(run_agent(
                [HumanMessage(content="test question")],
            ))
        finally:
            self._stop_patches(patches)
        return events


# ---- a. single retry succeeds ---------------------------------------------

class NudgeSucceedsTests(_EmptyCompletionBase):
    async def test_empty_then_content_triggers_nudge_and_final_answer(self):
        turns = [
            # iter 0: model requests a tool
            [("final", _ai(tool_calls=[_tc("echo_tool", {"q": "x"}, "tc1")]))],
            # iter 1: empty response (H4)
            [("final", _ai(content=""))],
            # iter 2: after nudge, model provides real answer
            [("token", "Answer "),
             ("token", "is X"),
             ("final", _ai(content="Answer is X"))],
        ]
        events = await self._run_once(turns, {"echo_tool": echo_tool})
        types = [e["type"] for e in events]
        self.assertEqual(types, [
            "tool_call", "tool_result",
            "thinking",          # nudge notice
            "token", "token",
            "final_answer", "done",
        ])
        self.assertIn("Empty completion detected", events[2]["content"])
        self.assertEqual(events[-2]["content"], "Answer is X")


# ---- b. double empty emits error, not final_answer -------------------------

class DoubleEmptyEmitsErrorTests(_EmptyCompletionBase):
    async def test_two_empties_yield_error_no_final_answer(self):
        turns = [
            [("final", _ai(tool_calls=[_tc("echo_tool", {"q": "x"}, "tc1")]))],
            [("final", _ai(content=""))],   # iter 1 empty
            [("final", _ai(content=""))],   # iter 2 still empty after nudge
        ]
        events = await self._run_once(turns, {"echo_tool": echo_tool})
        types = [e["type"] for e in events]
        self.assertEqual(types, [
            "tool_call", "tool_result",
            "thinking",
            "error", "done",
        ])
        self.assertEqual(events[3]["where"], "agent_loop")
        self.assertIn("empty response twice", events[3]["message"])
        # No final_answer event should be emitted.
        self.assertNotIn("final_answer", types)


# ---- c. baseline untouched for normal flows --------------------------------

class BaselineUntouchedTests(_EmptyCompletionBase):
    async def test_non_empty_response_skips_nudge_path(self):
        turns = [
            [("token", "Hello "),
             ("token", "world"),
             ("final", _ai(content="Hello world"))],
        ]
        events = await self._run_once(turns, {})
        types = [e["type"] for e in events]
        self.assertEqual(types, ["token", "token", "final_answer", "done"])
        # No thinking (nudge notice), no error.
        self.assertNotIn("thinking", types)
        self.assertNotIn("error", types)
        self.assertEqual(events[-2]["content"], "Hello world")


# ---- d. nudge_count resets per run_agent invocation -----------------------

class NudgeCountPerInvocationTests(_EmptyCompletionBase):
    async def test_second_run_still_nudges(self):
        """Guard against a refactor that accidentally elevates nudge_count
        to module-level or class-level state."""

        def empty_then_content_script():
            return [
                [("final", _ai(tool_calls=[_tc("echo_tool", {"q": "x"}, "tc1")]))],
                [("final", _ai(content=""))],
                [("token", "ok"), ("final", _ai(content="ok"))],
            ]

        tools = {"echo_tool": echo_tool}
        first = await self._run_once(empty_then_content_script(), tools)
        first_types = [e["type"] for e in first]
        self.assertEqual(first_types, [
            "tool_call", "tool_result",
            "thinking",
            "token",
            "final_answer", "done",
        ])
        # Second invocation: fresh scripted stream, same shape.
        second = await self._run_once(empty_then_content_script(), tools)
        second_types = [e["type"] for e in second]
        # If nudge_count survived between runs, the second run would NOT
        # emit a 'thinking' and would instead emit 'error' + 'done' after
        # the empty response.
        self.assertEqual(second_types, first_types)
        self.assertIn("thinking", second_types)


if __name__ == "__main__":
    unittest.main()
