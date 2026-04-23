"""Tests for agent.core.run_agent — hermetic; LLM stream is patched.

The test strategy: patch ``agent.core._stream_llm`` to yield scripted
(kind, payload) tuples, patch ``agent.core.select_llm`` to a no-op
MagicMock, and patch ``agent.core.build_tool_registry`` to return a
minimal tool set built on-the-fly per test. This lets us assert the
event sequence (not LLM internals or HTTP).

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_agent_core
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool

from agent.core import run_agent


# ---- helpers ---------------------------------------------------------------

def _make_scripted_stream(turns):
    """Build a replacement for agent.core._stream_llm.

    ``turns`` is a list of turn-scripts. Each turn-script is a list of
    (kind, payload) tuples — exactly what _stream_llm yields internally.
    Each call to astream pops one turn-script; raises if exhausted.
    """
    remaining = list(turns)

    async def fake_stream(llm, messages):
        if not remaining:
            raise RuntimeError("scripted LLM stream exhausted")
        for ev in remaining.pop(0):
            yield ev

    return fake_stream


def _ai(content="", tool_calls=None, usage=None):
    kw: dict = {"content": content}
    if tool_calls:
        kw["tool_calls"] = tool_calls
    if usage:
        um = dict(usage)
        um.setdefault(
            "total_tokens",
            int(um.get("input_tokens", 0)) + int(um.get("output_tokens", 0)),
        )
        kw["usage_metadata"] = um
    return AIMessage(**kw)


def _tc(name, args, call_id):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


async def _drain(gen):
    out = []
    async for ev in gen:
        out.append(ev)
    return out


@tool(parse_docstring=True)
def echo_tool(q: str) -> str:
    """Return the query back as-is.

    Args:
        q: the query string.
    """
    return f"echoed:{q}"


@tool(parse_docstring=True)
def raising_tool(q: str) -> str:
    """Raises deliberately.

    Args:
        q: unused.
    """
    raise RuntimeError("kaboom")


# ---- test base -------------------------------------------------------------

class _CoreTestBase(unittest.IsolatedAsyncioTestCase):
    def _run(self, turns, *, tools=None, **kwargs):
        """Patch the three seams and drain run_agent."""
        fake = _make_scripted_stream(turns)
        registry = tools if tools is not None else {}
        select_patch = patch("agent.core.select_llm", return_value=MagicMock())
        stream_patch = patch("agent.core._stream_llm", fake)
        registry_patch = patch(
            "agent.core.build_tool_registry", return_value=registry,
        )
        select_patch.start(); stream_patch.start(); registry_patch.start()
        self.addCleanup(select_patch.stop)
        self.addCleanup(stream_patch.stop)
        self.addCleanup(registry_patch.stop)

        async def _go():
            return await _drain(run_agent(
                [HumanMessage(content="test question")], **kwargs,
            ))
        return _go()


# ---- a. happy path, no tools ----------------------------------------------

class HappyPathNoToolsTests(_CoreTestBase):
    async def test_text_only_response(self):
        turns = [[
            ("token", "Aspirin "),
            ("token", "is "),
            ("token", "C9H8O4."),
            ("final", _ai(content="Aspirin is C9H8O4.")),
        ]]
        events = await self._run(turns)
        types = [e["type"] for e in events]
        self.assertEqual(types, ["token", "token", "token", "final_answer", "done"])
        self.assertEqual(events[3]["content"], "Aspirin is C9H8O4.")
        self.assertEqual(events[4]["usage"]["iterations"], 1)
        self.assertEqual(events[4]["usage"]["tool_calls"], 0)


# ---- b. happy path, one tool call -----------------------------------------

class HappyPathOneToolTests(_CoreTestBase):
    async def test_single_tool_then_answer(self):
        turns = [
            [("final", _ai(tool_calls=[_tc("echo_tool", {"q": "x"}, "tc1")]))],
            [("token", "Result: echoed:x"),
             ("final", _ai(content="Result: echoed:x"))],
        ]
        events = await self._run(turns, tools={"echo_tool": echo_tool})
        types = [e["type"] for e in events]
        self.assertEqual(types, [
            "tool_call", "tool_result", "token", "final_answer", "done",
        ])
        self.assertEqual(events[0]["name"], "echo_tool")
        self.assertEqual(events[0]["args"], {"q": "x"})
        self.assertEqual(events[1]["content"], "echoed:x")
        self.assertEqual(events[3]["content"], "Result: echoed:x")
        self.assertEqual(events[4]["usage"]["iterations"], 2)
        self.assertEqual(events[4]["usage"]["tool_calls"], 1)


# ---- c. tool raises --------------------------------------------------------

class ToolRaisesTests(_CoreTestBase):
    async def test_exception_becomes_tool_error_loop_continues(self):
        turns = [
            [("final", _ai(tool_calls=[_tc("raising_tool", {"q": "x"}, "tc1")]))],
            [("token", "sorry"), ("final", _ai(content="sorry"))],
        ]
        events = await self._run(turns, tools={"raising_tool": raising_tool})
        types = [e["type"] for e in events]
        self.assertEqual(types, [
            "tool_call", "tool_error", "token", "final_answer", "done",
        ])
        self.assertIn("kaboom", events[1]["message"])
        self.assertEqual(events[1]["name"], "raising_tool")

    async def test_unknown_tool_name_yields_tool_error(self):
        turns = [
            [("final", _ai(tool_calls=[_tc("nonexistent", {}, "tc1")]))],
            [("token", "oh well"), ("final", _ai(content="oh well"))],
        ]
        events = await self._run(turns, tools={})  # empty registry
        types = [e["type"] for e in events]
        self.assertEqual(types, [
            "tool_call", "tool_error", "token", "final_answer", "done",
        ])
        self.assertIn("nonexistent", events[1]["message"])


# ---- d. max iterations -----------------------------------------------------

class MaxIterationsTests(_CoreTestBase):
    async def test_overflow_emits_graceful_final_answer(self):
        # Every turn returns a tool_call → loop never resolves.
        looping_turn = [("final", _ai(
            tool_calls=[_tc("echo_tool", {"q": f"iter"}, "tcX")],
        ))]
        # Use distinct args so dedup does NOT short-circuit
        turns = [
            [("final", _ai(
                tool_calls=[_tc("echo_tool", {"q": f"q{i}"}, f"tc{i}")],
            ))]
            for i in range(5)
        ]
        events = await self._run(
            turns, tools={"echo_tool": echo_tool}, max_iterations=3,
        )
        types = [e["type"] for e in events]
        # 3 iterations × (tool_call, tool_result) + final_answer + done
        self.assertEqual(
            types,
            ["tool_call", "tool_result"] * 3 + ["final_answer", "done"],
        )
        self.assertIn("maximum", events[-2]["content"].lower())
        self.assertIn("iteration", events[-2]["content"].lower())
        self.assertEqual(events[-1]["usage"]["iterations"], 3)


# ---- e. duplicate tool call -----------------------------------------------

class DuplicateToolCallTests(_CoreTestBase):
    async def test_same_sig_dedups_with_synthetic_result(self):
        # Two turns ask for the same (name, args). Second should dedup.
        turns = [
            [("final", _ai(
                tool_calls=[_tc("echo_tool", {"q": "x"}, "tc1")],
            ))],
            [("final", _ai(
                tool_calls=[_tc("echo_tool", {"q": "x"}, "tc2")],  # same sig
            ))],
            [("token", "done"), ("final", _ai(content="done"))],
        ]
        call_count = {"n": 0}
        real_invoke = echo_tool.invoke

        def _count_invoke(args):
            call_count["n"] += 1
            return real_invoke(args)
        mock_tool = MagicMock(spec=BaseTool, name="echo_tool")
        mock_tool.name = "echo_tool"
        mock_tool.ainvoke = MagicMock(
            side_effect=lambda args: _wrap_async(real_invoke(args), call_count),
        )
        events = await self._run(turns, tools={"echo_tool": mock_tool})
        types = [e["type"] for e in events]
        self.assertEqual(types, [
            "tool_call", "tool_result",
            "tool_call", "tool_result",
            "token", "final_answer", "done",
        ])
        # Second tool_result is the dedup synthetic, not an actual invocation
        self.assertIn("[dedup]", events[3]["content"])
        # Real tool ainvoke called exactly once
        self.assertEqual(mock_tool.ainvoke.call_count, 1)


async def _wrap_async(value, counter):
    counter["n"] += 1
    return value


# ---- f. token interleaving -------------------------------------------------

class StreamingInterleaveTests(_CoreTestBase):
    async def test_tokens_yield_before_tool_call_in_same_turn(self):
        turns = [
            [("token", "Let "),
             ("token", "me "),
             ("token", "check"),
             ("final", _ai(
                 content="Let me check",
                 tool_calls=[_tc("echo_tool", {"q": "aspirin"}, "tc1")],
             ))],
            [("token", "The "),
             ("token", "answer"),
             ("final", _ai(content="The answer"))],
        ]
        events = await self._run(turns, tools={"echo_tool": echo_tool})
        types = [e["type"] for e in events]
        # First turn: 3 tokens then tool_call → tool_result
        # Second turn: 2 tokens then final_answer
        self.assertEqual(types, [
            "token", "token", "token",
            "tool_call", "tool_result",
            "token", "token",
            "final_answer", "done",
        ])
        # Token ordering preserved
        self.assertEqual(events[0]["content"], "Let ")
        self.assertEqual(events[5]["content"], "The ")


# ---- router error handling -------------------------------------------------

class RouterErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_tier_yields_error_then_done(self):
        # Don't patch select_llm — let the real router raise ValueError.
        with patch(
            "agent.core.build_tool_registry", return_value={},
        ):
            events = await _drain(run_agent(
                [HumanMessage(content="hi")],
                tier="turbo",  # type: ignore[arg-type]
            ))
        types = [e["type"] for e in events]
        self.assertEqual(types, ["error", "done"])
        self.assertEqual(events[0]["where"], "router")
        self.assertIn("turbo", events[0]["message"])


# ---- usage accumulation ----------------------------------------------------

class UsageAccumulationTests(_CoreTestBase):
    async def test_usage_metadata_accumulates_across_turns(self):
        turns = [
            [("final", _ai(
                tool_calls=[_tc("echo_tool", {"q": "x"}, "tc1")],
                usage={"input_tokens": 100, "output_tokens": 20},
            ))],
            [("token", "done"),
             ("final", _ai(
                 content="done",
                 usage={"input_tokens": 150, "output_tokens": 5},
             ))],
        ]
        events = await self._run(turns, tools={"echo_tool": echo_tool})
        done = events[-1]
        self.assertEqual(done["usage"]["tokens_in"], 250)
        self.assertEqual(done["usage"]["tokens_out"], 25)
        self.assertEqual(done["usage"]["iterations"], 2)
        self.assertEqual(done["usage"]["tool_calls"], 1)
        self.assertGreaterEqual(done["usage"]["ms"], 0)


if __name__ == "__main__":
    unittest.main()
