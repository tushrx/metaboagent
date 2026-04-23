"""
Tests for config.py env-driven path and endpoint resolution.

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_config
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path


def _reload_config(env_overrides: dict) -> object:
    """Apply env overrides, reimport config, and return the module."""
    env_keys = [
        "METABOAGENT_DATA_ROOT",
        "METABOAGENT_RAW_DATA_DIR",
        "METABOAGENT_PROCESSED_DATA_DIR",
        "METABOAGENT_CHROMADB_DIR",
        "METABOAGENT_LOG_DIR",
        "METABOAGENT_MODEL_CACHE_DIR",
        "PRIMARY_LLM_BASE_URL",
        "PRIMARY_LLM_MODEL_NAME",
        "PRIMARY_LLM_API_KEY",
        "UTILITY_LLM_BASE_URL",
        "UTILITY_LLM_MODEL_NAME",
        "UTILITY_LLM_API_KEY",
        "VLLM_BASE_URL",
        "VLLM_MODEL_NAME",
        "VLLM_API_KEY",
        "HF_HOME",
    ]
    for k in env_keys:
        os.environ.pop(k, None)
    os.environ.update(env_overrides)

    if "config" in sys.modules:
        del sys.modules["config"]
    return importlib.import_module("config")


class ConfigDefaultsTest(unittest.TestCase):
    def test_defaults_use_repo_local_paths(self):
        cfg = _reload_config({})
        repo_root = Path(cfg.PROJECT_ROOT)
        self.assertEqual(cfg.DATA_ROOT, repo_root / "data")
        self.assertEqual(cfg.RAW_DATA_DIR, repo_root / "data" / "raw")
        self.assertEqual(cfg.CHROMADB_DIR, repo_root / "data" / "chromadb")
        self.assertEqual(cfg.LOG_DIR, repo_root / "logs")

    def test_default_primary_endpoint(self):
        # Phase 2 topology: PRIMARY is Gemma 4 E4B on :8001 (default agentic
        # tier). Day-1 had this pointing at 31B on :8000 — that's now the
        # max_rigor tier (see config.MAX_RIGOR_LLM_*).
        cfg = _reload_config({})
        self.assertEqual(cfg.PRIMARY_LLM_BASE_URL, "http://127.0.0.1:8001/v1")
        self.assertEqual(cfg.PRIMARY_LLM_MODEL_NAME, "google/gemma-4-E4B-it")
        self.assertEqual(cfg.VLLM_BASE_URL, cfg.PRIMARY_LLM_BASE_URL)
        self.assertEqual(cfg.VLLM_MODEL_NAME, cfg.PRIMARY_LLM_MODEL_NAME)

    def test_default_tier_endpoints_distinct(self):
        # Router contract: the three tiers must resolve to distinct
        # (base_url, model) pairs and all three must use 127.0.0.1.
        cfg = _reload_config({})
        tiers = {
            "default":   (cfg.PRIMARY_LLM_BASE_URL,   cfg.PRIMARY_LLM_MODEL_NAME),
            "deep":      (cfg.DEEP_LLM_BASE_URL,      cfg.DEEP_LLM_MODEL_NAME),
            "max_rigor": (cfg.MAX_RIGOR_LLM_BASE_URL, cfg.MAX_RIGOR_LLM_MODEL_NAME),
        }
        self.assertEqual(len(set(tiers.values())), 3,
                         f"tier endpoints not distinct: {tiers}")
        for name, (url, _model) in tiers.items():
            self.assertIn("127.0.0.1", url,
                          f"{name} endpoint {url!r} must use 127.0.0.1")
            self.assertNotIn("localhost", url,
                             f"{name} endpoint {url!r} must not use localhost")

    def test_utility_defaults_to_none(self):
        cfg = _reload_config({})
        self.assertIsNone(cfg.UTILITY_LLM_BASE_URL)
        self.assertIsNone(cfg.UTILITY_LLM_MODEL_NAME)


class ConfigOverrideTest(unittest.TestCase):
    def test_data_root_override_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _reload_config({"METABOAGENT_DATA_ROOT": tmp})
            self.assertEqual(cfg.DATA_ROOT, Path(tmp).resolve())
            self.assertEqual(cfg.RAW_DATA_DIR, Path(tmp).resolve() / "raw")
            self.assertEqual(cfg.PROCESSED_DATA_DIR, Path(tmp).resolve() / "processed")
            self.assertEqual(cfg.CHROMADB_DIR, Path(tmp).resolve() / "chromadb")
            self.assertTrue(cfg.RAW_DATA_DIR.exists())

    def test_per_dir_overrides_win_over_data_root(self):
        with tempfile.TemporaryDirectory() as base, \
             tempfile.TemporaryDirectory() as raw_override:
            cfg = _reload_config({
                "METABOAGENT_DATA_ROOT": base,
                "METABOAGENT_RAW_DATA_DIR": raw_override,
            })
            self.assertEqual(cfg.DATA_ROOT, Path(base).resolve())
            self.assertEqual(cfg.RAW_DATA_DIR, Path(raw_override).resolve())
            # processed/chromadb still follow the DATA_ROOT default
            self.assertEqual(cfg.PROCESSED_DATA_DIR, Path(base).resolve() / "processed")

    def test_primary_llm_env_overrides(self):
        cfg = _reload_config({
            "PRIMARY_LLM_BASE_URL": "http://example:9000/v1",
            "PRIMARY_LLM_MODEL_NAME": "custom/model",
            "PRIMARY_LLM_API_KEY": "env-key-123",
        })
        self.assertEqual(cfg.PRIMARY_LLM_BASE_URL, "http://example:9000/v1")
        self.assertEqual(cfg.PRIMARY_LLM_MODEL_NAME, "custom/model")
        self.assertEqual(cfg.PRIMARY_LLM_API_KEY, "env-key-123")
        # legacy aliases track the new values
        self.assertEqual(cfg.VLLM_BASE_URL, "http://example:9000/v1")
        self.assertEqual(cfg.VLLM_MODEL_NAME, "custom/model")
        self.assertEqual(cfg.VLLM_API_KEY, "env-key-123")

    def test_legacy_vllm_env_still_works(self):
        cfg = _reload_config({
            "VLLM_BASE_URL": "http://legacy:8000/v1",
            "VLLM_MODEL_NAME": "legacy/model",
            "VLLM_API_KEY": "legacy-key",
        })
        self.assertEqual(cfg.PRIMARY_LLM_BASE_URL, "http://legacy:8000/v1")
        self.assertEqual(cfg.PRIMARY_LLM_MODEL_NAME, "legacy/model")
        self.assertEqual(cfg.PRIMARY_LLM_API_KEY, "legacy-key")

    def test_utility_llm_configured(self):
        cfg = _reload_config({
            "UTILITY_LLM_BASE_URL": "http://localhost:8001/v1",
            "UTILITY_LLM_MODEL_NAME": "utility/model",
        })
        self.assertEqual(cfg.UTILITY_LLM_BASE_URL, "http://localhost:8001/v1")
        self.assertEqual(cfg.UTILITY_LLM_MODEL_NAME, "utility/model")
        # utility key falls back to primary key when unset
        self.assertEqual(cfg.UTILITY_LLM_API_KEY, cfg.PRIMARY_LLM_API_KEY)

    def test_utility_llm_model_defaults_to_primary_when_url_set(self):
        cfg = _reload_config({
            "UTILITY_LLM_BASE_URL": "http://localhost:8001/v1",
        })
        self.assertEqual(cfg.UTILITY_LLM_BASE_URL, "http://localhost:8001/v1")
        self.assertEqual(cfg.UTILITY_LLM_MODEL_NAME, cfg.PRIMARY_LLM_MODEL_NAME)

    def test_model_cache_dir_sets_hf_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _reload_config({"METABOAGENT_MODEL_CACHE_DIR": tmp})
            self.assertEqual(cfg.MODEL_CACHE_DIR, str(Path(tmp).resolve()))
            self.assertEqual(os.environ.get("HF_HOME"), str(Path(tmp).resolve()))


class ConfigHardeningTests(unittest.TestCase):
    """Phase-1 hardening: importing config must never raise when the API key
    is absent (tests / ingestion / path tools don't need it). Enforcement
    is lazy — ``get_primary_llm_api_key()`` raises at the point an LLM
    client is actually being built.
    """

    def test_missing_api_key_does_not_raise_at_import(self):
        import re

        cfg = _reload_config({})  # no PRIMARY / VLLM key set
        self.assertIsNone(cfg.PRIMARY_LLM_API_KEY)
        with self.assertRaises(RuntimeError) as ctx:
            cfg.get_primary_llm_api_key()
        self.assertRegex(str(ctx.exception), r"PRIMARY_LLM_API_KEY.*not set")

    def test_api_key_env_suppresses_warning(self):
        # Collect any warnings emitted by config import.
        logger = logging.getLogger("config")
        records: list[logging.LogRecord] = []

        class _Collector(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Collector(level=logging.WARNING)
        logger.addHandler(handler)
        try:
            cfg = _reload_config({"PRIMARY_LLM_API_KEY": "env-set-key"})
        finally:
            logger.removeHandler(handler)
        self.assertEqual(cfg.PRIMARY_LLM_API_KEY, "env-set-key")
        key_warnings = [r for r in records if "PRIMARY_LLM_API_KEY" in r.getMessage()]
        self.assertEqual(key_warnings, [])


if __name__ == "__main__":
    unittest.main()
