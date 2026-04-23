"""Tests for agent.history — bounded window, lazy summary, call dedup.

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_history
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
)

from agent.history import History


class BoundedMessagesTests(unittest.TestCase):
    SYSTEM = "SYSTEM"

    def setUp(self) -> None:
        self.mock_llm = MagicMock()
        self.mock_llm.invoke.return_value = AIMessage(content="MOCK_SUMMARY")
        self.h = History(summary_llm_factory=lambda: self.mock_llm)

    def _add_alternating(self, n_pairs: int, extra_user: int = 0) -> None:
        """Append n_pairs of (user, assistant) then extra_user trailing user turns."""
        for i in range(1, n_pairs + 1):
            self.h.add_user_turn(f"user-{i}")
            self.h.add_assistant_turn(f"assistant-{i}")
        for j in range(1, extra_user + 1):
            self.h.add_user_turn(f"user-extra-{j}")

    def test_empty_history_returns_system_only(self) -> None:
        out = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], SystemMessage)
        self.mock_llm.invoke.assert_not_called()

    def test_three_turns_no_summary(self) -> None:
        # 1 pair + 1 trailing user = 3 turns (2 user + 1 assistant)
        self._add_alternating(1, extra_user=1)
        out = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual(len(out), 4)
        self.assertIsInstance(out[0], SystemMessage)
        self.assertEqual([m.content for m in out[1:]],
                         ["user-1", "assistant-1", "user-extra-1"])
        self.mock_llm.invoke.assert_not_called()

    def test_four_turns_no_summary(self) -> None:
        self._add_alternating(2)
        out = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual(len(out), 5)
        self.mock_llm.invoke.assert_not_called()

    def test_six_turns_summary_covers_two_oldest(self) -> None:
        self._add_alternating(3)
        out = self.h.bounded_messages(self.SYSTEM)
        # Expected: [System, summary, user-2, assistant-2, user-3, assistant-3]
        self.assertEqual(len(out), 6)
        self.assertIsInstance(out[0], SystemMessage)
        self.assertIsInstance(out[1], HumanMessage)
        self.assertIn("2 earlier turns summarized", out[1].content)
        self.assertIn("MOCK_SUMMARY", out[1].content)
        self.assertEqual(out[2].content, "user-2")
        self.assertEqual(out[3].content, "assistant-2")
        self.assertEqual(out[4].content, "user-3")
        self.assertEqual(out[5].content, "assistant-3")
        self.assertEqual(self.mock_llm.invoke.call_count, 1)

    def test_twelve_turns_summary_covers_eight(self) -> None:
        self._add_alternating(6)
        out = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual(len(out), 6)
        self.assertIn("8 earlier turns summarized", out[1].content)
        self.assertEqual(out[2].content, "user-5")
        self.assertEqual(out[5].content, "assistant-6")

    def test_summary_cached_across_calls(self) -> None:
        self._add_alternating(3)
        _ = self.h.bounded_messages(self.SYSTEM)
        _ = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual(self.mock_llm.invoke.call_count, 1)

    def test_summary_regenerates_on_overflow(self) -> None:
        """Adding more turns must re-summarize the combined older block, not chain."""
        self._add_alternating(3)
        _ = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual(self.mock_llm.invoke.call_count, 1)
        # Drop 2 more by adding a 4th pair → older now has 4 turns
        self.h.add_user_turn("user-4")
        self.h.add_assistant_turn("assistant-4")
        self.mock_llm.invoke.return_value = AIMessage(content="NEW_SUMMARY")
        out = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual(self.mock_llm.invoke.call_count, 2)
        self.assertIn("4 earlier turns summarized", out[1].content)
        self.assertIn("NEW_SUMMARY", out[1].content)

    def test_tool_messages_excluded_from_window(self) -> None:
        """Intermediate tool-calling steps must not appear in bounded_messages."""
        self.h.add_user_turn("u1")
        self.h.add_assistant_turn(
            "", tool_calls=[{"name": "t", "args": {}, "id": "tc1"}]
        )
        self.h.add_tool_result("tc1", "result")
        self.h.add_assistant_turn("a1-final")
        self.h.add_user_turn("u2")
        self.h.add_assistant_turn("a2-final")
        out = self.h.bounded_messages(self.SYSTEM)
        self.assertEqual([m.content for m in out[1:]],
                         ["u1", "a1-final", "u2", "a2-final"])
        self.mock_llm.invoke.assert_not_called()


class CallDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = History(summary_llm_factory=lambda: MagicMock())

    def test_first_call_returns_true(self) -> None:
        self.assertTrue(
            self.h.check_and_record_call("search_kegg", {"query": "glucose"})
        )

    def test_exact_repeat_returns_false(self) -> None:
        self.h.check_and_record_call("search_kegg", {"query": "glucose"})
        self.assertFalse(
            self.h.check_and_record_call("search_kegg", {"query": "glucose"})
        )

    def test_different_args_return_true(self) -> None:
        self.h.check_and_record_call("search_kegg", {"query": "glucose"})
        self.assertTrue(
            self.h.check_and_record_call("search_kegg", {"query": "fructose"})
        )

    def test_key_order_canonicalized(self) -> None:
        self.h.check_and_record_call("tool", {"a": 1, "b": 2})
        self.assertFalse(
            self.h.check_and_record_call("tool", {"b": 2, "a": 1})
        )

    def test_whitespace_in_strings_canonicalized(self) -> None:
        self.h.check_and_record_call("tool", {"name": "aspirin"})
        self.assertFalse(
            self.h.check_and_record_call("tool", {"name": "  aspirin  "})
        )

    def test_different_tools_dont_dedup(self) -> None:
        self.h.check_and_record_call("a", {"x": 1})
        self.assertTrue(self.h.check_and_record_call("b", {"x": 1}))

    def test_nested_dict_canonicalized(self) -> None:
        self.h.check_and_record_call(
            "tool", {"outer": {"inner_a": 1, "inner_b": 2}}
        )
        self.assertFalse(
            self.h.check_and_record_call(
                "tool", {"outer": {"inner_b": 2, "inner_a": 1}}
            )
        )

    def test_new_user_turn_clears_dedup_window(self) -> None:
        self.h.check_and_record_call("tool", {"x": 1})
        self.assertFalse(self.h.check_and_record_call("tool", {"x": 1}))
        self.h.add_user_turn("next message")
        self.assertTrue(self.h.check_and_record_call("tool", {"x": 1}))


if __name__ == "__main__":
    unittest.main()
