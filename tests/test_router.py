"""Tests for agent.router.select_llm — hermetic (ChatOpenAI is mocked).

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_router
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import config
from agent.router import ModelTier, select_llm


class _BasePatch(unittest.TestCase):
    """Patches agent.router.ChatOpenAI for every test. The mock returns a
    MagicMock whose .bind_tools() returns a sentinel we can assert on."""

    def setUp(self) -> None:
        patcher = patch("agent.router.ChatOpenAI")
        self.mock_chat_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_instance = MagicMock(name="ChatOpenAI-instance")
        self.bound_sentinel = MagicMock(name="bind_tools-result")
        self.mock_instance.bind_tools.return_value = self.bound_sentinel
        self.mock_chat_cls.return_value = self.mock_instance


class DefaultTierTests(_BasePatch):
    def test_default_tier_uses_primary_endpoint(self) -> None:
        result = select_llm("default", [])
        self.mock_chat_cls.assert_called_once()
        kwargs = self.mock_chat_cls.call_args.kwargs
        # PRIMARY defaults to http://localhost:8000/v1; router rewrites to 127.0.0.1.
        self.assertEqual(
            kwargs["base_url"],
            config.PRIMARY_LLM_BASE_URL.replace("localhost", "127.0.0.1"),
        )
        self.assertEqual(kwargs["model"], config.PRIMARY_LLM_MODEL_NAME)
        self.assertEqual(kwargs["api_key"],
                         config.PRIMARY_LLM_API_KEY or "none")
        self.mock_instance.bind_tools.assert_called_once_with([])
        self.assertIs(result, self.bound_sentinel)


class DeepTierTests(_BasePatch):
    def test_deep_tier_uses_deep_endpoint(self) -> None:
        select_llm("deep", [])
        kwargs = self.mock_chat_cls.call_args.kwargs
        self.assertEqual(kwargs["base_url"], config.DEEP_LLM_BASE_URL)
        self.assertEqual(kwargs["model"], config.DEEP_LLM_MODEL_NAME)
        self.assertEqual(kwargs["api_key"],
                         config.PRIMARY_LLM_API_KEY or "none")


class MaxRigorTierTests(_BasePatch):
    def test_max_rigor_tier_uses_max_rigor_endpoint(self) -> None:
        """Router resolves max_rigor even if :8000 is down — no pre-flight."""
        select_llm("max_rigor", [])
        kwargs = self.mock_chat_cls.call_args.kwargs
        self.assertEqual(kwargs["base_url"], config.MAX_RIGOR_LLM_BASE_URL)
        self.assertEqual(kwargs["model"], config.MAX_RIGOR_LLM_MODEL_NAME)
        self.assertEqual(kwargs["api_key"],
                         config.PRIMARY_LLM_API_KEY or "none")


class ToolsForwardingTests(_BasePatch):
    def test_tools_list_forwarded_to_bind_tools(self) -> None:
        sentinel_tool_a = MagicMock(name="tool_a")
        sentinel_tool_b = MagicMock(name="tool_b")
        select_llm("default", [sentinel_tool_a, sentinel_tool_b])
        self.mock_instance.bind_tools.assert_called_once_with(
            [sentinel_tool_a, sentinel_tool_b]
        )

    def test_empty_tools_list_still_calls_bind_tools(self) -> None:
        select_llm("deep", [])
        self.mock_instance.bind_tools.assert_called_once_with([])

    def test_tuple_tools_converted_to_list(self) -> None:
        a, b = MagicMock(name="a"), MagicMock(name="b")
        select_llm("default", (a, b))
        self.mock_instance.bind_tools.assert_called_once_with([a, b])


class TemperatureTests(_BasePatch):
    def test_default_temperature_is_point_two(self) -> None:
        select_llm("default", [])
        self.assertEqual(self.mock_chat_cls.call_args.kwargs["temperature"], 0.2)

    def test_temperature_override_respected(self) -> None:
        select_llm("default", [], temperature=0.7)
        self.assertEqual(self.mock_chat_cls.call_args.kwargs["temperature"], 0.7)


class InvalidTierTests(_BasePatch):
    def test_unknown_tier_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            select_llm("turbo", [])  # type: ignore[arg-type]
        self.assertIn("turbo", str(ctx.exception))
        self.mock_chat_cls.assert_not_called()

    def test_empty_string_tier_raises(self) -> None:
        with self.assertRaises(ValueError):
            select_llm("", [])  # type: ignore[arg-type]

    def test_none_tier_raises(self) -> None:
        with self.assertRaises(ValueError):
            select_llm(None, [])  # type: ignore[arg-type]


class IPv4RewriteTests(_BasePatch):
    def test_localhost_rewritten_to_127_0_0_1(self) -> None:
        """If a tier endpoint carries 'localhost', router rewrites it."""
        with patch.dict(
            "agent.router._TIER_ENDPOINTS",
            {"default": ("http://localhost:8001/v1",
                         config.PRIMARY_LLM_MODEL_NAME)},
        ):
            select_llm("default", [])
            self.assertEqual(
                self.mock_chat_cls.call_args.kwargs["base_url"],
                "http://127.0.0.1:8001/v1",
            )


class TierLiteralExportedTests(unittest.TestCase):
    def test_model_tier_literal_exports_three_values(self) -> None:
        from typing import get_args
        self.assertEqual(
            set(get_args(ModelTier)),
            {"default", "deep", "max_rigor"},
        )


if __name__ == "__main__":
    unittest.main()
