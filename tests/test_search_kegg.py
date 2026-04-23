"""Verify search_kegg's filter_type/filter_value contract after the
Milestone 3.2 REFACTOR: the "none"/"null"/"" footgun is rejected, and
valid filters are forwarded to the retriever's matching kwargs.

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_search_kegg
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from agent.tools import kegg_search as kegg_mod
from agent.tools.kegg_search import search_kegg


class SearchKeggFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock = MagicMock()
        self.mock.search_reactions.return_value = []
        self.mock.search_compounds.return_value = []
        # Inject mock retriever; _get_retriever() returns it directly.
        self._prev = kegg_mod._retriever
        kegg_mod._retriever = self.mock

    def tearDown(self) -> None:
        kegg_mod._retriever = self._prev

    def _rxn_kwargs(self) -> dict:
        return self.mock.search_reactions.call_args.kwargs

    def _cpd_kwargs(self) -> dict:
        return self.mock.search_compounds.call_args.kwargs

    def test_both_none_no_filter(self) -> None:
        search_kegg.invoke({"query": "glucose"})
        self.assertEqual(self._rxn_kwargs(), {"top_k": 5})
        self.assertEqual(self._cpd_kwargs(), {"top_k": 5})

    def test_ec_number_filter_applied(self) -> None:
        search_kegg.invoke(
            {"query": "oxidoreductase", "filter_type": "ec_number",
             "filter_value": "1.1.1.1"}
        )
        self.assertEqual(
            self._rxn_kwargs(), {"top_k": 5, "ec_number": "1.1.1.1"}
        )
        # ec_number does NOT propagate to search_compounds
        self.assertEqual(self._cpd_kwargs(), {"top_k": 5})

    def test_filter_value_none_string_rejected(self) -> None:
        search_kegg.invoke(
            {"query": "glucose", "filter_type": "compound_id",
             "filter_value": "none"}
        )
        self.assertEqual(self._rxn_kwargs(), {"top_k": 5})
        self.assertEqual(self._cpd_kwargs(), {"top_k": 5})

    def test_filter_value_empty_string_rejected(self) -> None:
        search_kegg.invoke(
            {"query": "glucose", "filter_type": "compound_id",
             "filter_value": ""}
        )
        self.assertEqual(self._rxn_kwargs(), {"top_k": 5})
        self.assertEqual(self._cpd_kwargs(), {"top_k": 5})

    def test_filter_value_null_string_rejected(self) -> None:
        search_kegg.invoke(
            {"query": "glucose", "filter_type": "compound_id",
             "filter_value": "null"}
        )
        self.assertEqual(self._rxn_kwargs(), {"top_k": 5})
        self.assertEqual(self._cpd_kwargs(), {"top_k": 5})

    def test_pathway_id_filter_applied(self) -> None:
        search_kegg.invoke(
            {"query": "glycolysis", "filter_type": "pathway_id",
             "filter_value": "map00010"}
        )
        self.assertEqual(
            self._rxn_kwargs(), {"top_k": 5, "pathway_id": "map00010"}
        )
        self.assertEqual(self._cpd_kwargs(), {"top_k": 5})

    def test_compound_id_filter_propagates_to_both(self) -> None:
        search_kegg.invoke(
            {"query": "glucose", "filter_type": "compound_id",
             "filter_value": "C00031"}
        )
        self.assertEqual(
            self._rxn_kwargs(), {"top_k": 5, "compound_id": "C00031"}
        )
        self.assertEqual(
            self._cpd_kwargs(), {"top_k": 5, "compound_id": "C00031"}
        )


if __name__ == "__main__":
    unittest.main()
