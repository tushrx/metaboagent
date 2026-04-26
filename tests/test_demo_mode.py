"""Phase 7.1 — DEMO_MODE gating.

Each live-fetch tool must short-circuit and return a JSON stub before
any HTTP attempt when DEMO_MODE=1. Tests force the env, monkey-patch
the module-level ``_session`` (or ``_run_ddg`` for web_search) to a
sentinel that raises if invoked, then assert the tool returned the
expected demo-stub shape.

Also covers the verify_* tools wired in Phase 6.5.a, so all 10 tools
that touch the network are exercised here.

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_demo_mode
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _boom(*_args, **_kwargs):  # pragma: no cover — sentinel never called when gate works
    raise AssertionError("HTTP call attempted in DEMO_MODE")


class _DemoModeBase(unittest.TestCase):
    """Set DEMO_MODE=1 around each test, restore prior value after."""

    def setUp(self) -> None:
        self._prev = os.environ.get("DEMO_MODE")
        os.environ["DEMO_MODE"] = "1"

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("DEMO_MODE", None)
        else:
            os.environ["DEMO_MODE"] = self._prev

    def _assert_stub(self, raw: str, *, tool: str, fallback: str | None = None) -> dict:
        body = json.loads(raw)
        self.assertTrue(body.get("demo_mode"))
        self.assertEqual(body.get("tool"), tool)
        msg = body.get("message", "")
        self.assertIn("demo mode", msg.lower())
        self.assertIn("args", body)
        if fallback is not None:
            self.assertEqual(body.get("fallback"), fallback)
            # When a fallback exists, the directive must name it explicitly
            # so the model has an unambiguous next-action target.
            self.assertIn(fallback, msg)
        return body


# ---- live-fetch tools using _session.get/post ------------------------------

class FetchKeggLiveTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import fetch_kegg_live as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.fetch_kegg_live.invoke({"entity_id": "R00024"})
        body = self._assert_stub(raw, tool="fetch_kegg_live", fallback="search_kegg")
        self.assertEqual(body["args"]["entity_id"], "R00024")


class FetchPubmedLiveTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import fetch_pubmed_live as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.fetch_pubmed_live.invoke(
                {"query": "lycopene biosynthesis", "max_results": 5}
            )
        body = self._assert_stub(
            raw, tool="fetch_pubmed_live", fallback="search_literature"
        )
        self.assertEqual(body["args"]["query"], "lycopene biosynthesis")


class FetchUniprotTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import fetch_uniprot as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.fetch_uniprot.invoke(
                {"protein_name_or_ec": "phytoene synthase",
                 "organism": "Escherichia coli"}
            )
        body = self._assert_stub(
            raw, tool="fetch_uniprot", fallback="search_literature"
        )
        self.assertEqual(body["args"]["protein_name_or_ec"], "phytoene synthase")


class FetchPubchemTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import fetch_pubchem as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.fetch_pubchem.invoke({"compound_name_or_cid": "lycopene"})
        body = self._assert_stub(raw, tool="fetch_pubchem")
        self.assertNotIn("fallback", body)


class FetchZincTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import fetch_zinc as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.fetch_zinc.invoke({"compound_name_or_zinc_id": "ZINC000000016978"})
        self._assert_stub(raw, tool="fetch_zinc")


class FetchSabioRkTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import fetch_sabio_rk as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.fetch_sabio_rk.invoke(
                {"ec_number": "2.5.1.32", "organism": "Escherichia coli"}
            )
        self._assert_stub(
            raw, tool="fetch_sabio_rk", fallback="search_literature"
        )


class FetchGeneSequenceTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import fetch_gene_sequence as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.fetch_gene_sequence.invoke(
                {"gene_or_accession": "crtE", "organism": "Erwinia"}
            )
        self._assert_stub(raw, tool="fetch_gene_sequence")


# ---- web_search uses _run_ddg, not _session --------------------------------

class WebSearchTests(_DemoModeBase):
    def test_short_circuits_before_ddg_call(self) -> None:
        from agent.tools import web_search as mod
        with patch.object(mod, "_run_ddg", side_effect=_boom):
            raw = mod.web_search.invoke({"query": "metabolic engineering 2025"})
        self._assert_stub(raw, tool="web_search")


# ---- verify_* tools wired in Phase 6.5.a -----------------------------------

class VerifyKeggReactionTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import verify_kegg_reaction as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.verify_kegg_reaction.invoke({"reaction_id": "R00022"})
        # verify_* uses a different stub shape (returns dict, not JSON str).
        self.assertIsInstance(raw, dict)
        self.assertFalse(raw["exists"])
        self.assertIn("DEMO_MODE", raw["note"])


class VerifyEcNumberTests(_DemoModeBase):
    def test_short_circuits_before_http(self) -> None:
        from agent.tools import verify_ec_number as mod
        with patch.object(mod._session, "get", side_effect=_boom):
            raw = mod.verify_ec_number.invoke({"ec_number": "2.5.1.32"})
        self.assertIsInstance(raw, dict)
        self.assertFalse(raw["exists"])
        self.assertIn("DEMO_MODE", raw["note"])


# ---- baseline: tools still work with DEMO_MODE off (no env) ----------------
# Smoke check that the gate is conditional, not unconditional. We don't run
# the network here — we patch _session.get to raise a known sentinel and
# expect that sentinel to bubble up (i.e. the gate did NOT short-circuit).

class GateOnlyFiresInDemoModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.pop("DEMO_MODE", None)

    def tearDown(self) -> None:
        if self._prev is not None:
            os.environ["DEMO_MODE"] = self._prev

    def test_fetch_kegg_live_attempts_http_when_unset(self) -> None:
        """Negative case: gate is conditional. With DEMO_MODE unset the
        tool must reach _session.get. Tools wrap network errors via the
        shared _http retry, so we just assert the session was invoked."""
        from agent.tools import fetch_kegg_live as mod
        with patch.object(mod._session, "get") as mocked:
            mocked.return_value.status_code = 404
            mocked.return_value.text = ""
            mod.fetch_kegg_live.invoke({"entity_id": "R00024"})
        self.assertTrue(mocked.called, "DEMO_MODE off must allow HTTP attempt")


if __name__ == "__main__":
    unittest.main()
