"""Phase 8.3.B — KEGG compound name → id resolver tests.

Network-free: every test pins ``use_remote_fallback=False``. The remote
fallback path is exercised by the live integration in
``eval/eval_pathway_hallucination.py`` and the 3-run measurement that
closes 8.3.B; unit tests stay deterministic.
"""
from __future__ import annotations

from eval._kegg_name_resolver import (
    _normalize,
    reset_remote_cache,
    resolve_compound_name,
)


def test_local_lookup_acetyl_coa():
    assert resolve_compound_name("acetyl-CoA", use_remote_fallback=False) == ["C00024"]


def test_local_lookup_normalization_whitespace_and_case():
    assert resolve_compound_name("  Acetyl-CoA  ", use_remote_fallback=False) == ["C00024"]
    assert resolve_compound_name("ACETYL-COA", use_remote_fallback=False) == ["C00024"]


def test_aliases_resolve_to_same_id():
    a = resolve_compound_name("p-coumarate", use_remote_fallback=False)
    b = resolve_compound_name("4-coumaric acid", use_remote_fallback=False)
    assert a == b == ["C00811"]


def test_phytoene_returns_both_isomers():
    out = resolve_compound_name("phytoene", use_remote_fallback=False)
    assert "C05421" in out
    assert "C05423" in out


def test_alpha_ketoglutarate_aliases():
    base = ["C00026"]
    assert resolve_compound_name("alpha-ketoglutarate", use_remote_fallback=False) == base
    assert resolve_compound_name("2-oxoglutarate", use_remote_fallback=False) == base
    assert resolve_compound_name("AKG", use_remote_fallback=False) == base


def test_unknown_no_remote_returns_empty():
    assert resolve_compound_name(
        "never-heard-of-this-compound-xyz", use_remote_fallback=False
    ) == []


def test_empty_input_returns_empty():
    assert resolve_compound_name("", use_remote_fallback=False) == []
    assert resolve_compound_name("   ", use_remote_fallback=False) == []


def test_arrow_fragment_stripped():
    # If a step-line sliver leaks in, normalization should pull off the
    # arrow tail rather than fail to resolve.
    assert resolve_compound_name(
        "pyruvate -> acetyl-CoA", use_remote_fallback=False
    ) == ["C00022"]


def test_parenthetical_suffix_stripped():
    assert resolve_compound_name(
        "pyruvate (cytosolic)", use_remote_fallback=False
    ) == ["C00022"]


def test_markdown_emphasis_stripped():
    assert resolve_compound_name("**pyruvate**", use_remote_fallback=False) == ["C00022"]


def test_normalize_idempotent():
    s = " HMG-CoA "
    n1 = _normalize(s)
    n2 = _normalize(n1)
    assert n1 == n2 == "hmg-coa"


def test_returned_list_is_a_copy():
    """Mutating the returned list must not poison the local table."""
    out = resolve_compound_name("acetyl-CoA", use_remote_fallback=False)
    out.append("CXXXXX")
    again = resolve_compound_name("acetyl-CoA", use_remote_fallback=False)
    assert again == ["C00024"]


def test_reset_remote_cache_does_not_clear_local():
    reset_remote_cache()
    assert resolve_compound_name("acetyl-CoA", use_remote_fallback=False) == ["C00024"]
