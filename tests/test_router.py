"""
Router behavior tests.

Covers:
- default policy (primary vs utility classification)
- fallback when UTILITY_LLM_BASE_URL is unset
- client construction wires base_url and model correctly
- policy override is respected
- unknown task types default to primary with a clear reason

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_router
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest


ENV_KEYS = (
    "PRIMARY_LLM_BASE_URL",
    "PRIMARY_LLM_MODEL_NAME",
    "PRIMARY_LLM_API_KEY",
    "UTILITY_LLM_BASE_URL",
    "UTILITY_LLM_MODEL_NAME",
    "UTILITY_LLM_API_KEY",
    "VLLM_BASE_URL",
    "VLLM_MODEL_NAME",
    "VLLM_API_KEY",
)


def _reload(env: dict):
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)
    import config
    importlib.reload(config)
    from agent import router
    importlib.reload(router)
    router.reset_client_cache()
    return router


class RoutingPolicyTest(unittest.TestCase):
    def test_primary_tasks_route_to_primary(self):
        router = _reload({
            "PRIMARY_LLM_BASE_URL": "http://primary:8000/v1",
            "PRIMARY_LLM_MODEL_NAME": "primary-model",
        })
        for task in (
            router.TASK_FINAL_SYNTHESIS,
            router.TASK_DESIGN,
            router.TASK_INVESTIGATE,
            router.TASK_COMPARE,
            router.TASK_REACT_LOOP,
        ):
            d = router.route(task)
            self.assertEqual(d.effective_role, router.ROLE_PRIMARY, task)
            self.assertEqual(d.base_url, "http://primary:8000/v1", task)
            self.assertEqual(d.model, "primary-model", task)
            self.assertFalse(d.used_fallback, task)

    def test_utility_tasks_fall_back_when_unset(self):
        router = _reload({
            "PRIMARY_LLM_BASE_URL": "http://primary:8000/v1",
            "PRIMARY_LLM_MODEL_NAME": "primary-model",
            # UTILITY_LLM_BASE_URL deliberately unset
        })
        for task in (
            router.TASK_CLASSIFY,
            router.TASK_REWRITE_QUERY,
            router.TASK_SUMMARIZE_EVIDENCE,
            router.TASK_VERIFY,
            router.TASK_RERANK,
        ):
            d = router.route(task)
            self.assertEqual(d.requested_role, router.ROLE_UTILITY, task)
            self.assertEqual(d.effective_role, router.ROLE_PRIMARY, task)
            self.assertTrue(d.used_fallback, task)
            self.assertEqual(d.base_url, "http://primary:8000/v1", task)
            self.assertIn("falling back", d.reason.lower())

    def test_utility_tasks_route_to_utility_when_set(self):
        router = _reload({
            "PRIMARY_LLM_BASE_URL": "http://primary:8000/v1",
            "PRIMARY_LLM_MODEL_NAME": "primary-model",
            "UTILITY_LLM_BASE_URL": "http://utility:8001/v1",
            "UTILITY_LLM_MODEL_NAME": "utility-model",
        })
        d = router.route(router.TASK_RERANK)
        self.assertEqual(d.effective_role, router.ROLE_UTILITY)
        self.assertFalse(d.used_fallback)
        self.assertEqual(d.base_url, "http://utility:8001/v1")
        self.assertEqual(d.model, "utility-model")

    def test_utility_model_defaults_to_primary_model_name(self):
        # UTILITY_LLM_BASE_URL is set but model name is not — config already
        # has it fall back to the primary model name.
        router = _reload({
            "PRIMARY_LLM_BASE_URL": "http://primary:8000/v1",
            "PRIMARY_LLM_MODEL_NAME": "primary-model",
            "UTILITY_LLM_BASE_URL": "http://utility:8001/v1",
        })
        d = router.route(router.TASK_CLASSIFY)
        self.assertEqual(d.effective_role, router.ROLE_UTILITY)
        self.assertEqual(d.base_url, "http://utility:8001/v1")
        self.assertEqual(d.model, "primary-model")

    def test_unknown_task_defaults_to_primary(self):
        router = _reload({})
        d = router.route("something_new")
        self.assertEqual(d.effective_role, router.ROLE_PRIMARY)
        self.assertFalse(d.used_fallback)
        self.assertIn("unknown", d.reason.lower())

    def test_custom_policy_override(self):
        router = _reload({})
        # Force final_synthesis to utility — and prove fallback still applies.
        custom = {router.TASK_FINAL_SYNTHESIS: router.ROLE_UTILITY}
        d = router.route(router.TASK_FINAL_SYNTHESIS, policy=custom)
        self.assertEqual(d.requested_role, router.ROLE_UTILITY)
        self.assertEqual(d.effective_role, router.ROLE_PRIMARY)  # not configured
        self.assertTrue(d.used_fallback)


class RoutedClientTest(unittest.TestCase):
    def test_primary_client_has_expected_base_url_and_model(self):
        router = _reload({
            "PRIMARY_LLM_BASE_URL": "http://primary:8000/v1",
            "PRIMARY_LLM_MODEL_NAME": "primary-model",
            "PRIMARY_LLM_API_KEY": "primary-key",
        })
        llm = router.build_llm_for(router.TASK_REACT_LOOP)
        self.assertEqual(llm.model_name, "primary-model")
        # ChatOpenAI exposes the resolved base URL as openai_api_base.
        self.assertIn("primary:8000", str(llm.openai_api_base))

    def test_utility_client_built_with_utility_endpoint(self):
        router = _reload({
            "PRIMARY_LLM_BASE_URL": "http://primary:8000/v1",
            "PRIMARY_LLM_MODEL_NAME": "primary-model",
            "UTILITY_LLM_BASE_URL": "http://utility:8001/v1",
            "UTILITY_LLM_MODEL_NAME": "utility-model",
        })
        llm = router.build_llm_for(router.TASK_RERANK)
        self.assertEqual(llm.model_name, "utility-model")
        self.assertIn("utility:8001", str(llm.openai_api_base))

    def test_client_cache_reuses_instances(self):
        router = _reload({})
        a = router.build_llm_for(router.TASK_REACT_LOOP)
        b = router.build_llm_for(router.TASK_FINAL_SYNTHESIS)  # same (primary, model)
        self.assertIs(a, b)  # cached

    def test_utility_fallback_returns_primary_client(self):
        router = _reload({
            "PRIMARY_LLM_BASE_URL": "http://primary:8000/v1",
            "PRIMARY_LLM_MODEL_NAME": "primary-model",
        })
        # No UTILITY_LLM_BASE_URL — rerank should silently use primary.
        llm = router.build_llm_for(router.TASK_RERANK)
        self.assertEqual(llm.model_name, "primary-model")


class DescribeRouteAliasTest(unittest.TestCase):
    def test_describe_route_returns_same_as_route(self):
        router = _reload({})
        d1 = router.route(router.TASK_CLASSIFY)
        d2 = router.describe_route(router.TASK_CLASSIFY)
        self.assertEqual(d1, d2)
        self.assertIn("task_type", d1.as_dict())


if __name__ == "__main__":
    unittest.main()
