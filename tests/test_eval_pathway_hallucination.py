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

from eval_pathway_hallucination import STEP_LINE_RE  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
