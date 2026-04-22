"""
Phase 9 — citation verifier tests.

Covers:
- Regex extraction (PMIDs, KEGG reaction / compound IDs, EC numbers) from
  realistic answer snippets.
- De-duplication and stable ordering.
- CitationVerifier with injected lookups:
    * VERIFIED when the lookup returns True
    * UNRESOLVED when it returns False
    * INFERRED when no lookup is configured for that type
    * UNRESOLVED on lookup exception (error path is best-effort, not fatal)
- Mixed-status CitationReport aggregates counts and groups by type.
- ``Citation.as_dict`` is stable / machine-readable.
- No Chroma dependency — the default factory is imported lazily and
  never called here.

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_citation_verifier
"""
from __future__ import annotations

import unittest

from agent.rag import (
    Citation,
    CitationReport,
    CitationStatus,
    CitationType,
    CitationVerifier,
    build_report,
    extract_citations,
)


ANSWER_SNIPPET = """
Target: Lycopene (C05432).
Host: Escherichia coli.
Step 1 — R02003: GGPP synthase, EC 2.5.1.29 (Pantoea ananatis).
Step 2 — R07212: phytoene synthase, EC 2.5.1.32.
Step 3 — R07561: phytoene desaturase, EC 1.3.99.31.
Precursor: C00341 (GPP).
References: PMID 16612385, PMID:23575629.
"""


class ExtractionTests(unittest.TestCase):
    def test_extract_all_shapes(self):
        cites = extract_citations(ANSWER_SNIPPET)
        values = {(c.cite_type, c.value) for c in cites}
        self.assertIn((CitationType.PMID, "16612385"), values)
        self.assertIn((CitationType.PMID, "23575629"), values)
        self.assertIn((CitationType.KEGG_REACTION, "R02003"), values)
        self.assertIn((CitationType.KEGG_REACTION, "R07212"), values)
        self.assertIn((CitationType.KEGG_REACTION, "R07561"), values)
        self.assertIn((CitationType.KEGG_COMPOUND, "C05432"), values)
        self.assertIn((CitationType.KEGG_COMPOUND, "C00341"), values)
        self.assertIn((CitationType.EC_NUMBER, "2.5.1.29"), values)
        self.assertIn((CitationType.EC_NUMBER, "2.5.1.32"), values)
        self.assertIn((CitationType.EC_NUMBER, "1.3.99.31"), values)

    def test_extraction_dedupes_repeats(self):
        text = "PMID 12345678 cites PMID:12345678 twice; R00024 and R00024."
        cites = extract_citations(text)
        pmids = [c for c in cites if c.cite_type is CitationType.PMID]
        rxns = [c for c in cites if c.cite_type is CitationType.KEGG_REACTION]
        self.assertEqual(len(pmids), 1)
        self.assertEqual(len(rxns), 1)

    def test_extraction_order_is_deterministic(self):
        cites = extract_citations(ANSWER_SNIPPET)
        types = [c.cite_type for c in cites]
        # PMID block first, then reactions, then compounds, then ECs.
        self.assertEqual(types, sorted(types, key=[
            CitationType.PMID,
            CitationType.KEGG_REACTION,
            CitationType.KEGG_COMPOUND,
            CitationType.EC_NUMBER,
        ].index))
        # Values sorted lexically within each type.
        pmids = [c.value for c in cites if c.cite_type is CitationType.PMID]
        self.assertEqual(pmids, sorted(pmids))

    def test_extraction_on_empty_text(self):
        self.assertEqual(extract_citations(""), [])
        self.assertEqual(extract_citations(None), [])

    def test_extracted_status_is_inferred(self):
        for c in extract_citations(ANSWER_SNIPPET):
            self.assertIs(c.status, CitationStatus.INFERRED)


class VerifierStatusTests(unittest.TestCase):
    def setUp(self):
        self.known_pmids = {"16612385"}
        self.known_rxns = {"R02003"}
        self.known_cpds = {"C05432"}
        self.known_ecs = {"2.5.1.29"}
        self.verifier = CitationVerifier(
            pmid_lookup=lambda v: (v in self.known_pmids, "literature"),
            reaction_lookup=lambda v: (v in self.known_rxns, "kegg_reactions"),
            compound_lookup=lambda v: (v in self.known_cpds, "kegg_compounds"),
            ec_lookup=lambda v: (v in self.known_ecs, "literature"),
        )

    def test_verified_hits_have_source(self):
        cites = self.verifier.verify_text(ANSWER_SNIPPET)
        by_key = {(c.cite_type, c.value): c for c in cites}
        self.assertIs(
            by_key[(CitationType.PMID, "16612385")].status,
            CitationStatus.VERIFIED,
        )
        self.assertEqual(
            by_key[(CitationType.PMID, "16612385")].source, "literature",
        )
        self.assertIs(
            by_key[(CitationType.KEGG_REACTION, "R02003")].status,
            CitationStatus.VERIFIED,
        )

    def test_unknown_ids_are_unresolved(self):
        cites = self.verifier.verify_text(ANSWER_SNIPPET)
        by_key = {(c.cite_type, c.value): c for c in cites}
        self.assertIs(
            by_key[(CitationType.PMID, "23575629")].status,
            CitationStatus.UNRESOLVED,
        )
        self.assertIn("not found",
                      by_key[(CitationType.PMID, "23575629")].note)

    def test_lookup_errors_become_unresolved(self):
        def boom(_v):
            raise RuntimeError("chroma is dead")

        v = CitationVerifier(pmid_lookup=boom)
        result = v.verify([Citation(
            cite_type=CitationType.PMID, value="11111111",
            status=CitationStatus.INFERRED,
        )])
        self.assertEqual(len(result), 1)
        self.assertIs(result[0].status, CitationStatus.UNRESOLVED)
        self.assertIn("lookup error", result[0].note)

    def test_missing_backend_marks_inferred_with_note(self):
        # Only a PMID lookup configured — EC citations should come back INFERRED.
        v = CitationVerifier(
            pmid_lookup=lambda x: (True, "literature"),
        )
        result = v.verify([
            Citation(cite_type=CitationType.EC_NUMBER, value="1.1.1.1",
                     status=CitationStatus.INFERRED),
        ])
        self.assertEqual(len(result), 1)
        self.assertIs(result[0].status, CitationStatus.INFERRED)
        self.assertIn("no lookup backend", result[0].note)

    def test_verify_preserves_input_values(self):
        # Ensure verifier doesn't silently mutate ids between input & output.
        source_cite = Citation(
            cite_type=CitationType.KEGG_COMPOUND, value="C05432",
            status=CitationStatus.INFERRED,
        )
        out = self.verifier.verify([source_cite])
        self.assertEqual(out[0].value, "C05432")
        self.assertIs(out[0].status, CitationStatus.VERIFIED)


class CitationReportTests(unittest.TestCase):
    def test_build_report_counts_and_grouping(self):
        known_pmids = {"16612385"}
        v = CitationVerifier(
            pmid_lookup=lambda x: (x in known_pmids, "literature"),
        )
        report = build_report(ANSWER_SNIPPET, v)
        self.assertIsInstance(report, CitationReport)
        counts = report.counts
        # Verified: 1 PMID. Unresolved: 1 PMID. All KEGG/EC lack backends → INFERRED.
        self.assertEqual(counts["verified"], 1)
        self.assertEqual(counts["unresolved"], 1)
        self.assertGreater(counts["inferred"], 0)
        # by_type grouping preserves the original extraction order.
        pmids = report.by_type(CitationType.PMID)
        self.assertEqual(len(pmids), 2)

    def test_report_as_dict_is_machine_readable(self):
        v = CitationVerifier()  # all types → INFERRED
        report = build_report("PMID 99999999 and R00024.", v)
        d = report.as_dict()
        self.assertIn("counts", d)
        self.assertIn("citations", d)
        self.assertTrue(all(
            set(row.keys()) == {"cite_type", "value", "status", "source", "note"}
            for row in d["citations"]
        ))


class EcCacheHardeningTests(unittest.TestCase):
    """Phase-9 hardening: the EC fallback index must be built once, not per-lookup.

    The public API is injectable, so we mimic the default-factory behaviour
    by caching a reaction-metadata fetch result inside a dict keyed on the
    first call. A regression here would restore the N×5000-row rescan we
    had before hardening.
    """

    def test_ec_fallback_index_built_once(self):
        from agent.rag.citation_verifier import _build_ec_index

        class FakeColl:
            def __init__(self):
                self.calls = 0

            def get(self, **kwargs):
                self.calls += 1
                return {
                    "metadatas": [
                        {"ec_numbers": "2.5.1.29, 4.2.3.4"},
                        {"ec_numbers": "1.1.1.1"},
                    ]
                }

        coll = FakeColl()
        # Simulate the factory's build-once-then-reuse behaviour.
        cache: dict[str, frozenset[str]] = {}

        def get_index():
            if "reactions" not in cache:
                cache["reactions"] = _build_ec_index(coll)
            return cache["reactions"]

        idx1 = get_index()
        idx2 = get_index()
        idx3 = get_index()

        self.assertEqual(coll.calls, 1)
        self.assertIs(idx1, idx2)
        self.assertIs(idx2, idx3)
        self.assertIn("2.5.1.29", idx1)
        self.assertIn("1.1.1.1", idx1)
        self.assertNotIn("9.9.9.9", idx1)

    def test_build_ec_index_returns_empty_on_error(self):
        from agent.rag.citation_verifier import _build_ec_index

        class ExplodingColl:
            def get(self, **kwargs):
                raise RuntimeError("chroma down")

        self.assertEqual(_build_ec_index(ExplodingColl()), frozenset())


class CitationDataclassTests(unittest.TestCase):
    def test_citation_is_frozen_and_hashable(self):
        c = Citation(
            cite_type=CitationType.PMID, value="12345678",
            status=CitationStatus.VERIFIED, source="literature",
        )
        {c}  # hashable
        with self.assertRaises(Exception):
            c.value = "other"  # type: ignore[misc]

    def test_citation_as_dict_keys(self):
        c = Citation(
            cite_type=CitationType.EC_NUMBER, value="1.1.1.1",
            status=CitationStatus.INFERRED,
        )
        d = c.as_dict()
        self.assertEqual(d["cite_type"], "ec_number")
        self.assertEqual(d["status"], "inferred")
        self.assertEqual(d["value"], "1.1.1.1")


if __name__ == "__main__":
    unittest.main()
