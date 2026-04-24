"""Unit tests for the eval/eval_pathway_hallucination.py harness.

Keeps the regexes honest: step-line detection must accept the several
markdown styles the model drifts into, and reject false positives like
"1 gram" or "Figure 1.".

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_eval_pathway_hallucination
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# eval/ isn't a package; add it to the path so we can import the module.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "eval"))

from eval_pathway_hallucination import (  # noqa: E402
    STEP_LINE_RE,
    _classify_no_ids_reason,
)


class StepLineRegexTests(unittest.TestCase):
    # ---- accepting forms ---------------------------------------------------

    def test_canonical_step_colon(self) -> None:
        self.assertIsNotNone(STEP_LINE_RE.search(
            "Step 1: Acetyl-CoA → Acetoacetyl-CoA"
        ))

    def test_bolded_step(self) -> None:
        self.assertIsNotNone(STEP_LINE_RE.search(
            "**Step 1:** Acetyl-CoA → Acetoacetyl-CoA"
        ))

    def test_markdown_numbered_period(self) -> None:
        self.assertIsNotNone(STEP_LINE_RE.search(
            "1. **Ferulic Acid Activation:** Ferulic acid → Feruloyl-CoA"
        ))

    def test_markdown_numbered_paren(self) -> None:
        self.assertIsNotNone(STEP_LINE_RE.search(
            "1) Activate ferulic acid to feruloyl-CoA"
        ))

    def test_bolded_numbered(self) -> None:
        self.assertIsNotNone(STEP_LINE_RE.search(
            "**1.** Ferulic Acid Activation"
        ))

    def test_step_embedded_in_multiline_block(self) -> None:
        # The typical shape: header paragraph, then step lines.
        text = (
            "Here is the pathway:\n\n"
            "Step 1: A → B\n"
            "    Reaction: R00012  EC 2.3.1.16\n"
            "Step 2: B → C\n"
        )
        self.assertIsNotNone(STEP_LINE_RE.search(text))
        # findall catches both
        self.assertEqual(len(STEP_LINE_RE.findall(text)), 2)

    # ---- rejecting forms ---------------------------------------------------

    def test_prose_one_gram(self) -> None:
        """A digit not followed by .,),: must not match."""
        self.assertIsNone(STEP_LINE_RE.search("1 gram of glucose"))

    def test_figure_caption_not_step(self) -> None:
        """Line anchor must stop 'Figure 1.' from matching."""
        self.assertIsNone(STEP_LINE_RE.search("Figure 1. shows the pathway"))

    def test_inline_numeric_not_step(self) -> None:
        """A digit mid-line after other text must not match (line anchor)."""
        self.assertIsNone(STEP_LINE_RE.search("and then 1. The first step is…"))

    def test_empty_text_no_match(self) -> None:
        self.assertIsNone(STEP_LINE_RE.search(""))


class NoIdsReasonClassifierTests(unittest.TestCase):
    def test_empty_text_is_silent_giveup(self) -> None:
        self.assertEqual(_classify_no_ids_reason(""), "silent_giveup")

    def test_short_punt_is_silent_giveup(self) -> None:
        self.assertEqual(
            _classify_no_ids_reason("ok."),
            "silent_giveup",
        )

    def test_long_design_with_hedge_is_declared(self) -> None:
        # Mimics artemisinic_yeast's real output: structurally a full
        # design + explicit hedge.
        text = (
            "Step 1: FPP → Artemisinic Acid\n"
            "    Reaction: (Precursor) → FPP\n"
            "    PMID: [Evidence needed]\n"
            "The exact KEGG R-IDs and EC numbers need to be confirmed via "
            "database lookups to provide the full reaction diagram."
        )
        self.assertEqual(
            _classify_no_ids_reason(text),
            "declared_insufficient_evidence",
        )

    def test_long_design_without_hedge_is_unclassified(self) -> None:
        # Enough text to rule out silent giveup, but no hedge language —
        # shouldn't be credited as honest either.
        text = (
            "Step 1: A → B. Step 2: B → C. This is a long description "
            "of a pathway that the model confidently asserted without any "
            "hedging language or acknowledgement of missing data."
        )
        self.assertEqual(
            _classify_no_ids_reason(text),
            "unclassified",
        )


if __name__ == "__main__":
    unittest.main()
