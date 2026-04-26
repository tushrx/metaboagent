"""Phase 7.3 — demo cache lookup integration.

Verifies that when DEMO_MODE=1 and a matching cache entry exists, the
tool short-circuits and returns the cached real result instead of the
stub. Covers the five edge cases the milestone calls out: hit, miss,
different-args, malformed cache file, and DEMO_MODE-off bypass.

The cache root is patched to a temporary directory per test so the
suite is hermetic. ``_reset_cache`` is called on entry and exit so the
module-level lazy cache doesn't leak between tests.

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_demo_cache
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from agent.tools import _demo  # noqa: E402


def _write_cache(root: Path, query_id: str, entries: list[dict]) -> None:
    sub = root / query_id
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "tool_calls.json").write_text(
        json.dumps(entries, ensure_ascii=False)
    )


class _CacheTestBase(unittest.TestCase):
    """Per-test temp directory + DEMO_MODE=1 + cache module reset."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cache_root = Path(self._tmpdir.name)
        self._patcher = patch.object(_demo, "DEMO_CACHE_DIR", self._cache_root)
        self._patcher.start()
        self._prev_demo = os.environ.get("DEMO_MODE")
        os.environ["DEMO_MODE"] = "1"
        _demo._reset_cache()

    def tearDown(self) -> None:
        _demo._reset_cache()
        self._patcher.stop()
        if self._prev_demo is None:
            os.environ.pop("DEMO_MODE", None)
        else:
            os.environ["DEMO_MODE"] = self._prev_demo
        self._tmpdir.cleanup()


# ---- helper-level tests ----------------------------------------------------

class CanonicalArgsTests(unittest.TestCase):
    def test_strips_none_and_empty_string(self) -> None:
        self.assertEqual(
            _demo._canonical_args({"a": 1, "b": None, "c": ""}),
            '{"a": 1}',
        )

    def test_sorted_keys(self) -> None:
        self.assertEqual(
            _demo._canonical_args({"b": 2, "a": 1}),
            '{"a": 1, "b": 2}',
        )


class LoadCacheTests(_CacheTestBase):
    def test_missing_dir_returns_empty(self) -> None:
        # The DEMO_CACHE_DIR is patched to an empty tempdir (existing
        # but with no subfolders) — should still load to an empty map.
        self.assertEqual(_demo._load_cache(), {})

    def test_aggregates_multiple_query_dirs(self) -> None:
        _write_cache(self._cache_root, "q1", [
            {"tool_name": "fetch_kegg_live", "args": {"entity_id": "C00022"},
             "result": "{\"kind\": \"compound\", \"name\": \"Pyruvate\"}"},
        ])
        _write_cache(self._cache_root, "q2", [
            {"tool_name": "fetch_pubmed_live",
             "args": {"query": "lycopene", "max_results": 10},
             "result": "{\"hits\": []}"},
        ])
        cache = _demo._load_cache()
        self.assertEqual(len(cache), 2)
        self.assertIn(("fetch_kegg_live", '{"entity_id": "C00022"}'), cache)
        self.assertIn(
            ("fetch_pubmed_live", '{"max_results": 10, "query": "lycopene"}'),
            cache,
        )

    def test_malformed_json_is_skipped_with_warning(self) -> None:
        sub = self._cache_root / "broken"
        sub.mkdir()
        (sub / "tool_calls.json").write_text("not-json{{{")
        # Add a healthy sibling so we can verify it still loads.
        _write_cache(self._cache_root, "ok", [
            {"tool_name": "fetch_kegg_live", "args": {"entity_id": "R00022"},
             "result": "{\"x\": 1}"},
        ])
        cache = _demo._load_cache()
        self.assertEqual(len(cache), 1)
        self.assertIn(("fetch_kegg_live", '{"entity_id": "R00022"}'), cache)


# ---- end-to-end tool tests -------------------------------------------------

CACHED_KEGG = (
    '{"kind": "compound", "kegg_id": "C00022", "name": "Pyruvate", '
    '"formula": "C3H4O3"}'
)


class CacheHitTests(_CacheTestBase):
    def test_hit_returns_cached_real_result_not_stub(self) -> None:
        _write_cache(self._cache_root, "kegg_c00022", [
            {"tool_name": "fetch_kegg_live", "args": {"entity_id": "C00022"},
             "result": CACHED_KEGG},
        ])
        from agent.tools import fetch_kegg_live as mod
        with patch.object(mod._session, "get") as mocked:
            raw = mod.fetch_kegg_live.invoke({"entity_id": "C00022"})
        self.assertFalse(mocked.called, "cache hit must NOT touch network")
        body = json.loads(raw)
        self.assertEqual(body.get("kegg_id"), "C00022")
        self.assertEqual(body.get("name"), "Pyruvate")
        # The cached payload has no demo_mode key — proves we skipped the stub.
        self.assertNotIn("demo_mode", body)


class CacheMissTests(_CacheTestBase):
    def test_miss_falls_through_to_stub(self) -> None:
        # Empty cache directory, DEMO_MODE on.
        from agent.tools import fetch_kegg_live as mod
        with patch.object(mod._session, "get") as mocked:
            raw = mod.fetch_kegg_live.invoke({"entity_id": "C99999"})
        self.assertFalse(mocked.called)
        body = json.loads(raw)
        self.assertTrue(body.get("demo_mode"))
        self.assertEqual(body.get("tool"), "fetch_kegg_live")
        self.assertEqual(body.get("fallback"), "search_kegg")


class CacheDifferentArgsTests(_CacheTestBase):
    def test_different_args_is_a_miss(self) -> None:
        _write_cache(self._cache_root, "kegg_c00022", [
            {"tool_name": "fetch_kegg_live", "args": {"entity_id": "C00022"},
             "result": CACHED_KEGG},
        ])
        from agent.tools import fetch_kegg_live as mod
        # Same tool, different entity_id — must NOT hit.
        with patch.object(mod._session, "get") as mocked:
            raw = mod.fetch_kegg_live.invoke({"entity_id": "R00022"})
        body = json.loads(raw)
        self.assertTrue(body.get("demo_mode"))
        self.assertFalse(mocked.called)


class CacheBypassedWhenDemoModeOffTests(unittest.TestCase):
    """Negative case: DEMO_MODE off → cache is irrelevant; live HTTP runs."""

    def test_cache_not_consulted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_cache(root, "kegg_c00022", [
                {"tool_name": "fetch_kegg_live", "args": {"entity_id": "C00022"},
                 "result": CACHED_KEGG},
            ])
            with patch.object(_demo, "DEMO_CACHE_DIR", root):
                _demo._reset_cache()
                # Make sure DEMO_MODE is off.
                env = {k: v for k, v in os.environ.items() if k != "DEMO_MODE"}
                with patch.dict(os.environ, env, clear=True):
                    from agent.tools import fetch_kegg_live as mod
                    with patch.object(mod._session, "get") as mocked:
                        mocked.return_value.status_code = 404
                        mocked.return_value.text = ""
                        mod.fetch_kegg_live.invoke({"entity_id": "C00022"})
                    self.assertTrue(mocked.called,
                                    "DEMO_MODE off must bypass cache and "
                                    "attempt the live call")


if __name__ == "__main__":
    unittest.main()
