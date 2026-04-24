"""Unit tests for verify_kegg_reaction and verify_ec_number (Phase 6.5.a).

Mocks the module-level requests.Session so no live KEGG calls happen.

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_verify_tools
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import requests

from agent.tools import verify_ec_number as ec_mod
from agent.tools import verify_kegg_reaction as rxn_mod
from agent.tools.verify_ec_number import verify_ec_number
from agent.tools.verify_kegg_reaction import verify_kegg_reaction


def _resp(status: int, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


_R00022_BODY = """\
ENTRY       R00022                      Reaction
NAME        cysteine reaction
EQUATION    C00097 + C00001 <=> C00491 + C00021
ENZYME      2.3.3.10        2.3.3.8
///
"""

_EC_2_3_3_10_BODY = """\
ENTRY       EC 2.3.3.10                 Enzyme
NAME        hydroxymethylglutaryl-CoA synthase; HMG-CoA synthase
SYSNAME     acetyl-CoA:acetoacetyl-CoA C-acetyltransferase
REACTION    [RN:R01978]
ALL_REAC    R01978
///
"""


class VerifyKeggReactionTests(unittest.TestCase):
    def setUp(self) -> None:
        rxn_mod._cache.clear()
        self._prev_session = rxn_mod._session
        self._mock_session = MagicMock()
        rxn_mod._session = self._mock_session
        # make sure DEMO_MODE doesn't leak in
        self._prev_demo = os.environ.pop("DEMO_MODE", None)

    def tearDown(self) -> None:
        rxn_mod._session = self._prev_session
        rxn_mod._cache.clear()
        if self._prev_demo is not None:
            os.environ["DEMO_MODE"] = self._prev_demo
        else:
            os.environ.pop("DEMO_MODE", None)

    def test_valid_reaction_returns_exists_with_equation(self) -> None:
        self._mock_session.get.return_value = _resp(200, _R00022_BODY)
        result = verify_kegg_reaction.invoke({"reaction_id": "R00022"})
        self.assertTrue(result["exists"])
        self.assertEqual(result["reaction_id"], "R00022")
        self.assertEqual(result["equation"], "C00097 + C00001 <=> C00491 + C00021")
        self.assertIn("cysteine reaction", result["name"])
        self.assertEqual(result["ec_numbers"], ["2.3.3.10", "2.3.3.8"])

    def test_invalid_reaction_returns_exists_false(self) -> None:
        self._mock_session.get.return_value = _resp(404)
        result = verify_kegg_reaction.invoke({"reaction_id": "R99999"})
        self.assertFalse(result["exists"])
        self.assertEqual(result["reaction_id"], "R99999")
        self.assertNotIn("equation", result)

    def test_malformed_input_does_not_hit_network(self) -> None:
        result = verify_kegg_reaction.invoke({"reaction_id": "not-an-id"})
        self.assertFalse(result["exists"])
        self.assertIn("malformed", result["error"])
        self._mock_session.get.assert_not_called()

    def test_rnprefix_and_case_are_normalized(self) -> None:
        self._mock_session.get.return_value = _resp(200, _R00022_BODY)
        result = verify_kegg_reaction.invoke({"reaction_id": "rn:r00022"})
        self.assertEqual(result["reaction_id"], "R00022")
        called_url = self._mock_session.get.call_args[0][0]
        self.assertIn("rn:R00022", called_url)

    def test_cache_prevents_duplicate_fetch(self) -> None:
        self._mock_session.get.return_value = _resp(200, _R00022_BODY)
        verify_kegg_reaction.invoke({"reaction_id": "R00022"})
        verify_kegg_reaction.invoke({"reaction_id": "R00022"})
        self.assertEqual(self._mock_session.get.call_count, 1)

    def test_network_error_raises(self) -> None:
        self._mock_session.get.side_effect = requests.Timeout("boom")
        # @tool wraps ToolException; use .invoke to run the pure function.
        with self.assertRaises(RuntimeError):
            verify_kegg_reaction.invoke({"reaction_id": "R00022"})

    def test_demo_mode_returns_stub_without_network(self) -> None:
        os.environ["DEMO_MODE"] = "1"
        result = verify_kegg_reaction.invoke({"reaction_id": "R00022"})
        self.assertFalse(result["exists"])
        self.assertIn("DEMO_MODE", result["note"])
        self._mock_session.get.assert_not_called()


class VerifyEcNumberTests(unittest.TestCase):
    def setUp(self) -> None:
        ec_mod._cache.clear()
        self._prev_session = ec_mod._session
        self._mock_session = MagicMock()
        ec_mod._session = self._mock_session
        self._prev_demo = os.environ.pop("DEMO_MODE", None)

    def tearDown(self) -> None:
        ec_mod._session = self._prev_session
        ec_mod._cache.clear()
        if self._prev_demo is not None:
            os.environ["DEMO_MODE"] = self._prev_demo
        else:
            os.environ.pop("DEMO_MODE", None)

    def test_valid_ec_returns_recommended_name_and_reactions(self) -> None:
        self._mock_session.get.return_value = _resp(200, _EC_2_3_3_10_BODY)
        result = verify_ec_number.invoke({"ec_number": "2.3.3.10"})
        self.assertTrue(result["exists"])
        self.assertEqual(result["ec_number"], "2.3.3.10")
        self.assertIn("HMG-CoA synthase", result["recommended_name"])
        self.assertIn("R01978", result["reactions"])

    def test_invalid_ec_returns_exists_false(self) -> None:
        self._mock_session.get.return_value = _resp(404)
        result = verify_ec_number.invoke({"ec_number": "9.9.9.9"})
        self.assertFalse(result["exists"])
        self.assertEqual(result["ec_number"], "9.9.9.9")

    def test_malformed_ec_does_not_hit_network(self) -> None:
        result = verify_ec_number.invoke({"ec_number": "1.-.-.-"})
        self.assertFalse(result["exists"])
        self.assertIn("malformed", result["error"])
        self._mock_session.get.assert_not_called()

    def test_prefix_and_whitespace_normalized(self) -> None:
        self._mock_session.get.return_value = _resp(200, _EC_2_3_3_10_BODY)
        for raw in ("EC 2.3.3.10", "ec:2.3.3.10", "2.3.3.10"):
            ec_mod._cache.clear()
            result = verify_ec_number.invoke({"ec_number": raw})
            self.assertEqual(result["ec_number"], "2.3.3.10")

    def test_demo_mode_returns_stub_without_network(self) -> None:
        os.environ["DEMO_MODE"] = "1"
        result = verify_ec_number.invoke({"ec_number": "2.3.3.10"})
        self.assertFalse(result["exists"])
        self.assertIn("DEMO_MODE", result["note"])
        self._mock_session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
