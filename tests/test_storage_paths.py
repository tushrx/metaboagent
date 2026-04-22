"""
Tests that downstream modules resolve their on-disk paths through config.py,
so setting METABOAGENT_* env vars reroutes *all* storage, not just paths
exposed directly on `config`.

We re-import the modules under different env var setups and check that
module-level constants (KEGG_RAW, PUBMED_RAW, ...) land under the overridden
root.

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_storage_paths
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


STATE_KEYS = (
    "METABOAGENT_DATA_ROOT",
    "METABOAGENT_RAW_DATA_DIR",
    "METABOAGENT_PROCESSED_DATA_DIR",
    "METABOAGENT_CHROMADB_DIR",
    "METABOAGENT_LOG_DIR",
    "METABOAGENT_MODEL_CACHE_DIR",
)

DOWNSTREAM_MODULES = (
    "config",
    "data.ingestion.kegg_fetcher",
    "data.ingestion.kegg_parser",
    "data.ingestion.pubmed_fetcher",
)


def _reload_with_env(env: dict):
    """Clear env + cached modules, apply overrides, re-import in order."""
    for k in STATE_KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)
    for m in DOWNSTREAM_MODULES:
        sys.modules.pop(m, None)
    return {m: importlib.import_module(m) for m in DOWNSTREAM_MODULES}


class DownstreamPathOverrideTest(unittest.TestCase):
    def test_raw_override_reaches_fetchers(self):
        with tempfile.TemporaryDirectory() as data_root:
            mods = _reload_with_env({"METABOAGENT_DATA_ROOT": data_root})
            root = Path(data_root).resolve()

            kegg_fetcher = mods["data.ingestion.kegg_fetcher"]
            pubmed_fetcher = mods["data.ingestion.pubmed_fetcher"]
            kegg_parser = mods["data.ingestion.kegg_parser"]

            self.assertEqual(kegg_fetcher.KEGG_RAW, root / "raw" / "kegg")
            self.assertEqual(kegg_fetcher.REACTIONS_DIR, root / "raw" / "kegg" / "reactions")
            self.assertEqual(kegg_fetcher.LINKS_DIR, root / "raw" / "kegg" / "links")
            self.assertEqual(pubmed_fetcher.PUBMED_RAW, root / "raw" / "pubmed")
            self.assertEqual(pubmed_fetcher.XML_DIR, root / "raw" / "pubmed" / "xml")
            self.assertEqual(kegg_parser.KEGG_RAW, root / "raw" / "kegg")
            self.assertEqual(kegg_parser.LINKS_DIR, root / "raw" / "kegg" / "links")
            # dirs mkdir'd on import
            self.assertTrue(kegg_fetcher.LINKS_DIR.exists())
            self.assertTrue(pubmed_fetcher.XML_DIR.exists())

    def test_per_dir_raw_override_wins(self):
        with tempfile.TemporaryDirectory() as base, \
             tempfile.TemporaryDirectory() as raw_custom:
            mods = _reload_with_env({
                "METABOAGENT_DATA_ROOT": base,
                "METABOAGENT_RAW_DATA_DIR": raw_custom,
            })
            raw = Path(raw_custom).resolve()
            self.assertEqual(mods["data.ingestion.kegg_fetcher"].KEGG_RAW, raw / "kegg")
            self.assertEqual(mods["data.ingestion.pubmed_fetcher"].PUBMED_RAW, raw / "pubmed")
            # processed still follows DATA_ROOT
            self.assertEqual(
                mods["config"].PROCESSED_DATA_DIR,
                Path(base).resolve() / "processed",
            )

    def test_log_path_helper(self):
        with tempfile.TemporaryDirectory() as log_dir:
            mods = _reload_with_env({"METABOAGENT_LOG_DIR": log_dir})
            cfg = mods["config"]
            resolved = cfg.get_log_path("demo.log")
            self.assertEqual(resolved, Path(log_dir).resolve() / "demo.log")
            # parent directory should exist even if the file itself doesn't
            self.assertTrue(resolved.parent.exists())

    def test_defaults_stay_repo_local(self):
        mods = _reload_with_env({})
        cfg = mods["config"]
        repo_root = Path(cfg.PROJECT_ROOT)
        self.assertEqual(cfg.RAW_DATA_DIR, repo_root / "data" / "raw")
        self.assertEqual(cfg.LOG_DIR, repo_root / "logs")
        self.assertEqual(
            mods["data.ingestion.kegg_fetcher"].KEGG_RAW,
            repo_root / "data" / "raw" / "kegg",
        )


if __name__ == "__main__":
    unittest.main()
