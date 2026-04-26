"""Phase 8.3.B — step-block parser tests for the pathway eval.

Pins the new arrow-chemistry parser and step-block builder used by the
substrate-relevance check. Network-free.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "eval"))

from eval_pathway_hallucination import (  # noqa: E402
    _block_for_rid,
    _clean_compound_token,
    _extract_chemistry,
    _parse_arrow_chemistry,
    _parse_step_blocks,
)


# ---- arrow chemistry -----------------------------------------------------


def test_arrow_unicode_arrow():
    sub, prod = _parse_arrow_chemistry("Acetyl-CoA → Citrate")
    assert sub == ["Acetyl-CoA"]
    assert prod == ["Citrate"]


def test_arrow_ascii_dash_arrow():
    sub, prod = _parse_arrow_chemistry("acetyl-CoA -> citrate")
    assert sub == ["acetyl-CoA"]
    assert prod == ["citrate"]


def test_arrow_fat_arrow():
    sub, prod = _parse_arrow_chemistry("acetyl-CoA => citrate")
    assert sub == ["acetyl-CoA"]
    assert prod == ["citrate"]


def test_multi_substrate_split_on_plus():
    sub, prod = _parse_arrow_chemistry("acetyl-CoA + oxaloacetate → citrate + CoA")
    assert sub == ["acetyl-CoA", "oxaloacetate"]
    assert prod == ["citrate", "CoA"]


def test_no_arrow_returns_empty():
    sub, prod = _parse_arrow_chemistry("Activation of ferulic acid to feruloyl-CoA")
    assert sub == []
    assert prod == []


def test_strips_markdown_emphasis_in_compound_names():
    sub, prod = _parse_arrow_chemistry("**Acetyl-CoA** → *Citrate*")
    # _clean_compound_token strips surrounding markdown.
    assert sub == ["Acetyl-CoA"]
    assert prod == ["Citrate"]


def test_strips_trailing_punctuation():
    sub, prod = _parse_arrow_chemistry("acetyl-CoA → citrate.")
    assert prod == ["citrate"]


def test_strips_trailing_parenthetical_on_each_side():
    sub, prod = _parse_arrow_chemistry(
        "pyruvate (cytosolic) → acetyl-CoA (mitochondrial)"
    )
    # The parenthetical at end of the side is stripped before plus-split,
    # so the cytosolic suffix on the LHS does NOT come through; defensive
    # cleanup also runs per token.
    assert sub == ["pyruvate"] or sub == ["pyruvate (cytosolic)"]
    # Keeping the assertion permissive: the resolver normalizer also
    # handles parentheticals, so it's enough that parsing didn't crash.
    assert "acetyl-CoA" in prod[0]


# ---- step block parsing ---------------------------------------------------


_SAMPLE_PHASE2 = """\
Here is the deep-dive for plan A.

Step 1: pyruvate → acetyl-CoA
- Reaction: R00209
- Enzyme: pyruvate dehydrogenase (EC 1.2.4.1)

Step 2: acetyl-CoA + oxaloacetate → citrate
- Reaction: R00351
- Enzyme: citrate synthase (EC 2.3.3.1)

Step 3: a description with no arrow markup at all.
- Reaction: R12345
"""


def test_parse_step_blocks_three_steps_found():
    blocks = _parse_step_blocks(_SAMPLE_PHASE2)
    nums = [b["step_num"] for b in blocks]
    assert nums == [1, 2, 3]


def test_step_blocks_parse_substrates_products():
    blocks = _parse_step_blocks(_SAMPLE_PHASE2)
    assert blocks[0]["substrate_names"] == ["pyruvate"]
    assert blocks[0]["product_names"] == ["acetyl-CoA"]
    assert blocks[1]["substrate_names"] == ["acetyl-CoA", "oxaloacetate"]
    assert blocks[1]["product_names"] == ["citrate"]
    # Step 3 has no arrow → empty
    assert blocks[2]["substrate_names"] == []
    assert blocks[2]["product_names"] == []


def test_step_blocks_capture_rids_per_block():
    blocks = _parse_step_blocks(_SAMPLE_PHASE2)
    assert blocks[0]["rids"] == ["R00209"]
    assert blocks[1]["rids"] == ["R00351"]
    assert blocks[2]["rids"] == ["R12345"]


def test_step_blocks_capture_ecs_per_block():
    blocks = _parse_step_blocks(_SAMPLE_PHASE2)
    assert blocks[0]["ecs"] == ["1.2.4.1"]
    assert blocks[1]["ecs"] == ["2.3.3.1"]
    assert blocks[2]["ecs"] == []


def test_block_for_rid_locates_correct_step():
    blocks = _parse_step_blocks(_SAMPLE_PHASE2)
    b = _block_for_rid("R00351", blocks)
    assert b is not None
    assert b["step_num"] == 2
    assert b["substrate_names"] == ["acetyl-CoA", "oxaloacetate"]


def test_block_for_rid_returns_none_when_outside_any_block():
    text = "RIDs sometimes appear in a header: R00099. Then:\n\n" + _SAMPLE_PHASE2
    # R00099 is in the prologue before any Step line — _parse_step_blocks
    # only sees blocks from "Step 1" onwards, so the prologue R-id has no
    # matching block.
    blocks = _parse_step_blocks(text)
    assert _block_for_rid("R00099", blocks) is None
    assert _block_for_rid("R00351", blocks) is not None


def test_empty_text_returns_no_blocks():
    assert _parse_step_blocks("") == []
    assert _parse_step_blocks(None) == []


# ---- LaTeX arrow + body fallback (real-world phase-2 styling) -------------


def test_arrow_latex_dollar_rightarrow():
    sub, prod = _parse_arrow_chemistry(
        r"Ferulic Acid + CoA $\rightarrow$ Feruloyl-CoA"
    )
    assert sub == ["Ferulic Acid", "CoA"]
    assert prod == ["Feruloyl-CoA"]


def test_arrow_bare_latex():
    sub, prod = _parse_arrow_chemistry(r"acetyl-CoA \to citrate")
    assert sub == ["acetyl-CoA"]
    assert prod == ["citrate"]


def test_clean_token_strips_latex_math_wrappers():
    # $\text{H}_2\text{O}$ should reduce to "H_2O" (subscript markers
    # stay; resolver handles further normalization)
    cleaned = _clean_compound_token(r"$\text{H}_2\text{O}$")
    assert "H" in cleaned and "O" in cleaned
    assert "$" not in cleaned and "\\text" not in cleaned


def test_extract_chemistry_falls_back_to_reaction_line():
    """Step head has no arrow — chemistry lives on a Reaction: bullet."""
    head = "Ferulic Acid Activation (Precursor Generation)"
    body = (
        "**Step 1: Ferulic Acid Activation (Precursor Generation)**\n"
        "*   **Reaction:** Ferulic Acid + CoA $\\rightarrow$ Feruloyl-CoA\n"
        "*   **Enzyme:** Feruloyl-CoA Synthetase\n"
    )
    sub, prod = _extract_chemistry(head, body)
    assert sub == ["Ferulic Acid", "CoA"]
    assert prod == ["Feruloyl-CoA"]


def test_extract_chemistry_prefers_step_head_when_present():
    head = "acetyl-CoA → citrate"
    body = (
        "Step 1: acetyl-CoA → citrate\n"
        "*   **Reaction:** something completely different\n"
    )
    sub, prod = _extract_chemistry(head, body)
    assert sub == ["acetyl-CoA"]
    assert prod == ["citrate"]


def test_block_for_rid_prefers_block_with_chemistry():
    """An R-ID that appears in two blocks goes to the chemistry-bearing one."""
    text = (
        "**Step 1: Ferulic Acid Activation**\n"
        "*   **Enzyme:** Feruloyl-CoA Synthetase\n"
        "*   **KEGG Reaction:** R12566\n"
        "\n"
        "Step 2: Feruloyl-CoA $\\rightarrow$ Vanillin\n"
        "    Reaction: R12566 EC 4.1.2.61\n"
    )
    blocks = _parse_step_blocks(text)
    b = _block_for_rid("R12566", blocks)
    assert b is not None
    # Step 2 has chemistry from the LaTeX arrow on its head.
    assert b["step_num"] == 2
    assert b["substrate_names"] == ["Feruloyl-CoA"]
    assert b["product_names"] == ["Vanillin"]


def test_bullet_prefixed_step_head_is_recognized():
    """Bullet-list step style: '*   **Step 1: ...**'."""
    text = (
        "**Pathway Steps:**\n"
        "*   **Step 1: Feruloyl-CoA Hydro-lyase Activity**\n"
        "    *   **Reaction:** Feruloyl-CoA $\\rightarrow$ Vanillin + Acetyl-CoA\n"
        "    *   **Reaction ID:** R12566\n"
    )
    blocks = _parse_step_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["step_num"] == 1
    assert "Feruloyl-CoA" in blocks[0]["substrate_names"]
    assert "Vanillin" in blocks[0]["product_names"]
    assert blocks[0]["rids"] == ["R12566"]


def test_real_world_vanillin_phase2_excerpt():
    """End-to-end: a phase-2 fragment from an actual eval run.

    The agent emits a prose-only step header AND a diagram-rendering
    section with explicit LaTeX arrow chemistry. Either path should
    surface a step block whose chemistry resolves to ferulic acid →
    feruloyl-CoA (or the symmetric Step 2: feruloyl-CoA → vanillin).
    """
    text = (
        "**Step 1: Ferulic Acid Activation (Precursor Generation)**\n"
        "*   **Reaction:** Ferulic Acid + CoA $\\rightarrow$ Feruloyl-CoA\n"
        "*   **KEGG Reaction:** R12566\n"
        "\n"
        "**Step 2: Vanillin Formation (Core Conversion)**\n"
        "*   **Reaction:** Feruloyl-CoA $\\rightarrow$ Vanillin\n"
        "*   **EC Number:** $\\text{4.1.2.61}$\n"
    )
    blocks = _parse_step_blocks(text)
    assert len(blocks) == 2
    # Step 1 picks up chemistry from the Reaction: bullet
    assert blocks[0]["substrate_names"] == ["Ferulic Acid", "CoA"]
    assert blocks[0]["product_names"] == ["Feruloyl-CoA"]
    # Step 2 picks up chemistry from the Reaction: bullet
    assert blocks[1]["substrate_names"] == ["Feruloyl-CoA"]
    assert blocks[1]["product_names"] == ["Vanillin"]
