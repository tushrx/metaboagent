"""
Phase 7 — rule library skeleton tests.

Covers:
- :class:`Rule` dataclass shape and hashability.
- :class:`RuleRepository` filters: category, scope, applies_to (full token +
  axis prefix), tag, min_confidence, free-text query, limit.
- Duplicate rule_ids raise at construction time (fail-fast config error).
- Seed rules cover every declared :class:`RuleCategory` so the agent has at
  least one example of each family.
- Ordering is deterministic (category → scope → -confidence → rule_id).

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_rule_library
"""
from __future__ import annotations

import unittest

from agent.rag import (
    EvidenceBasis,
    Rule,
    RuleCategory,
    RuleRepository,
    RuleScope,
    default_rule_repository,
)


class RuleDataclassTests(unittest.TestCase):
    def test_minimal_rule_fields(self):
        r = Rule(
            rule_id="x.y",
            category=RuleCategory.HOST_SELECTION,
            scope=RuleScope.GENERAL,
            text="Example rule.",
        )
        self.assertEqual(r.confidence, 0.5)
        self.assertEqual(r.evidence_basis, EvidenceBasis.EXPERT_HEURISTIC)
        self.assertEqual(r.applies_to, ())
        self.assertEqual(r.source, "seed")

    def test_rule_is_hashable(self):
        # Frozen dataclass → hashable → safe as dict keys / set members.
        r = Rule(
            rule_id="x.y",
            category=RuleCategory.HOST_SELECTION,
            scope=RuleScope.GENERAL,
            text="Example.",
        )
        {r: 1}
        {r}


class RuleRepositoryConstructionTests(unittest.TestCase):
    def test_empty_repo(self):
        repo = RuleRepository([])
        self.assertEqual(len(repo), 0)
        self.assertEqual(repo.all(), [])
        self.assertIsNone(repo.by_id("anything"))

    def test_duplicate_rule_id_raises(self):
        dup = Rule(rule_id="a", category=RuleCategory.HOST_SELECTION,
                   scope=RuleScope.GENERAL, text="1")
        dup2 = Rule(rule_id="a", category=RuleCategory.TROUBLESHOOTING,
                    scope=RuleScope.GENERAL, text="2")
        with self.assertRaises(ValueError):
            RuleRepository([dup, dup2])

    def test_by_id_roundtrip(self):
        r = Rule(rule_id="abc", category=RuleCategory.PATHWAY_HEURISTIC,
                 scope=RuleScope.GENERAL, text="step")
        repo = RuleRepository([r])
        self.assertIs(repo.by_id("abc"), r)
        self.assertIsNone(repo.by_id("missing"))


class DefaultRuleRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = default_rule_repository()

    def test_nonempty_and_unique_ids(self):
        self.assertGreater(len(self.repo), 0)
        ids = [r.rule_id for r in self.repo]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_category_has_at_least_one_rule(self):
        cats = {r.category for r in self.repo}
        for expected in RuleCategory:
            self.assertIn(expected, cats,
                          f"seed rules missing category {expected}")

    def test_confidences_are_in_range(self):
        for r in self.repo:
            self.assertGreaterEqual(r.confidence, 0.0)
            self.assertLessEqual(r.confidence, 1.0)


class RuleRepositorySearchTests(unittest.TestCase):
    def setUp(self):
        self.repo = default_rule_repository()

    def test_filter_by_category(self):
        hits = self.repo.search(category=RuleCategory.HOST_SELECTION)
        self.assertTrue(hits)
        self.assertTrue(all(r.category is RuleCategory.HOST_SELECTION
                            for r in hits))

    def test_filter_by_scope(self):
        hits = self.repo.search(scope=RuleScope.GENERAL)
        self.assertTrue(hits)
        self.assertTrue(all(r.scope is RuleScope.GENERAL for r in hits))

    def test_filter_by_min_confidence(self):
        hits = self.repo.search(min_confidence=0.80)
        self.assertTrue(hits)
        self.assertTrue(all(r.confidence >= 0.80 for r in hits))

    def test_filter_by_tag(self):
        hits = self.repo.search(tag="terpenoid")
        self.assertTrue(hits)
        self.assertTrue(all("terpenoid" in r.tags for r in hits))

    def test_applies_to_full_token(self):
        hits = self.repo.search(applies_to="chassis:ecoli")
        self.assertTrue(hits)
        self.assertTrue(all(any("chassis:ecoli" == a.lower() for a in r.applies_to)
                            for r in hits))

    def test_applies_to_axis_prefix(self):
        hits = self.repo.search(applies_to="chassis:")
        self.assertTrue(hits)
        # Every hit has at least one applies_to on the "chassis" axis.
        for r in hits:
            self.assertTrue(any(a.lower().startswith("chassis:")
                                for a in r.applies_to))

    def test_applies_to_value_only(self):
        # Value-only lookup: match "ecoli" against the value side of any
        # applies_to entry.
        hits = self.repo.search(applies_to="ecoli")
        self.assertTrue(hits)

    def test_applies_to_unknown_returns_empty(self):
        self.assertEqual(self.repo.search(applies_to="chassis:no_such_host"), [])

    def test_free_text_query_single_term(self):
        hits = self.repo.search(query="precursor")
        self.assertTrue(hits)
        for r in hits:
            blob = (r.rule_id + r.text + (r.rationale or "")
                    + " ".join(r.tags)).lower()
            self.assertIn("precursor", blob)

    def test_free_text_query_multi_term_is_and(self):
        # "cofactor pathway" should narrow to rules containing both.
        hits = self.repo.search(query="cofactor pathway")
        self.assertTrue(hits)
        for r in hits:
            blob = (r.text + " " + (r.rationale or "")
                    + " " + " ".join(r.tags)).lower()
            self.assertIn("cofactor", blob)
            self.assertIn("pathway", blob)

    def test_free_text_no_match_returns_empty(self):
        self.assertEqual(
            self.repo.search(query="zzzz_nonsense_token"), [])

    def test_limit(self):
        hits = self.repo.search(limit=2)
        self.assertEqual(len(hits), 2)

    def test_ordering_category_then_confidence(self):
        # Within any single category, confidence should be descending.
        for cat in RuleCategory:
            hits = self.repo.search(category=cat)
            confidences = [r.confidence for r in hits]
            self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_combined_filters(self):
        hits = self.repo.search(
            category=RuleCategory.PATHWAY_HEURISTIC,
            query="precursor",
            min_confidence=0.5,
        )
        self.assertTrue(hits)
        for r in hits:
            self.assertIs(r.category, RuleCategory.PATHWAY_HEURISTIC)
            self.assertGreaterEqual(r.confidence, 0.5)


class RuleRepositoryExtensibilityTests(unittest.TestCase):
    """Confirm that adding rules is purely additive — no other touch points."""

    def test_custom_repo_from_custom_rules(self):
        custom = [
            Rule(
                rule_id="custom.one",
                category=RuleCategory.CHEMISTRY_COMPARISON,
                scope=RuleScope.MOLECULE,
                text="Custom rule text.",
                applies_to=("molecule:lycopene",),
                tags=("custom",),
                confidence=0.9,
                evidence_basis=EvidenceBasis.LITERATURE,
            ),
        ]
        repo = RuleRepository(custom)
        self.assertEqual(len(repo), 1)
        self.assertIs(repo.by_id("custom.one"), custom[0])
        self.assertEqual(
            repo.search(applies_to="molecule:lycopene"), custom)
        self.assertEqual(repo.search(tag="custom"), custom)


if __name__ == "__main__":
    unittest.main()
