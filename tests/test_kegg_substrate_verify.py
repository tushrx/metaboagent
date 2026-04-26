"""Phase 8.3.B — substrate-relevance verifier tests.

Network-free: ``verify_kegg_reaction_id`` and ``resolve_compound_name``
are stubbed via monkeypatch on the module under test. The pure
classifier ``_classify_substrate_match`` is tested directly.

The mevalonate-style failure mode the verifier targets:
> agent emits 'Step 2: acetyl-CoA -> acetoacetyl-CoA / Reaction: R02082',
> but R02082's equation involves neither compound. Existence-only
> checking calls this a pass; substrate-relevance returns 'neither'.
"""
from __future__ import annotations

import pytest

from eval import _kegg_verify
from eval._kegg_verify import (
    _classify_substrate_match,
    get_reaction_compounds,
    verify_reaction_substrate,
)


# ---- pure classifier -----------------------------------------------------


def test_classifier_fully_matches():
    out = _classify_substrate_match(
        claimed_substrate_ids=["C00024"],
        claimed_product_ids=["C00083"],
        kegg_substrates=["C00024", "C00033"],
        kegg_products=["C00083", "C00010"],
    )
    assert out["verdict"] == "fully_matches"
    assert out["substrate_matches"] is True
    assert out["product_matches"] is True


def test_classifier_substrate_only():
    out = _classify_substrate_match(
        claimed_substrate_ids=["C00024"],
        claimed_product_ids=["C99999"],
        kegg_substrates=["C00024"],
        kegg_products=["C00083"],
    )
    assert out["verdict"] == "substrate_only"


def test_classifier_product_only():
    out = _classify_substrate_match(
        claimed_substrate_ids=["C99999"],
        claimed_product_ids=["C00083"],
        kegg_substrates=["C00024"],
        kegg_products=["C00083"],
    )
    assert out["verdict"] == "product_only"


def test_classifier_neither():
    out = _classify_substrate_match(
        claimed_substrate_ids=["C99999"],
        claimed_product_ids=["C99998"],
        kegg_substrates=["C00024"],
        kegg_products=["C00083"],
    )
    assert out["verdict"] == "neither"
    assert out["substrate_matches"] is False
    assert out["product_matches"] is False


def test_classifier_direction_lenient_reverse():
    """Agent claims A -> B, KEGG records B -> A. Both compounds appear in
    the equation — verdict should still be fully_matches.
    """
    out = _classify_substrate_match(
        claimed_substrate_ids=["C00083"],   # claimed substrate
        claimed_product_ids=["C00024"],      # claimed product
        kegg_substrates=["C00024", "C00033"],  # KEGG stores in opposite dir
        kegg_products=["C00083", "C00010"],
    )
    assert out["verdict"] == "fully_matches"


def test_classifier_isomer_set_match():
    """Resolver returns multiple C-IDs (phytoene isomers); any-of-set
    semantics — match if any resolved C-ID intersects the equation.
    """
    out = _classify_substrate_match(
        claimed_substrate_ids=["C05421", "C05423"],
        claimed_product_ids=["C05432"],
        kegg_substrates=["C05423"],   # only the all-trans isomer
        kegg_products=["C05432"],
    )
    assert out["verdict"] == "fully_matches"


def test_classifier_unresolvable_falls_through_to_neither():
    """Empty resolved sets cannot match anything — legitimate but
    indistinguishable from 'neither' on verdict alone. Caller checks
    substrate_resolved / product_resolved to disambiguate.
    """
    out = _classify_substrate_match(
        claimed_substrate_ids=[],
        claimed_product_ids=[],
        kegg_substrates=["C00024"],
        kegg_products=["C00083"],
    )
    assert out["verdict"] == "neither"


# ---- get_reaction_compounds ---------------------------------------------


def _stub_rid(equation: str | None, exists: bool = True):
    """Helper: build a fake verify_kegg_reaction_id return value."""
    if not exists:
        return {"exists": False, "reaction_id": "R00000"}
    return {
        "exists": True,
        "reaction_id": "R00000",
        "equation": equation,
        "name": "stub",
        "ec_numbers": [],
    }


def test_get_reaction_compounds_parses_lhs_rhs(monkeypatch):
    monkeypatch.setattr(
        _kegg_verify, "verify_kegg_reaction_id",
        lambda rid, **kw: _stub_rid("C00024 + C00033 <=> C00010 + C00083"),
    )
    out = get_reaction_compounds("R00000")
    assert out["substrates"] == ["C00024", "C00033"]
    assert out["products"] == ["C00010", "C00083"]
    assert out["exists"] is True


def test_get_reaction_compounds_handles_coefficients(monkeypatch):
    monkeypatch.setattr(
        _kegg_verify, "verify_kegg_reaction_id",
        lambda rid, **kw: _stub_rid("2 C00024 + 3 C00001 <=> C00033"),
    )
    out = get_reaction_compounds("R00000")
    assert out["substrates"] == ["C00024", "C00001"]
    assert out["products"] == ["C00033"]


def test_get_reaction_compounds_no_equation(monkeypatch):
    monkeypatch.setattr(
        _kegg_verify, "verify_kegg_reaction_id",
        lambda rid, **kw: _stub_rid(None),
    )
    out = get_reaction_compounds("R00000")
    assert out["substrates"] == []
    assert out["products"] == []
    assert out["exists"] is True


def test_get_reaction_compounds_rid_invalid(monkeypatch):
    monkeypatch.setattr(
        _kegg_verify, "verify_kegg_reaction_id",
        lambda rid, **kw: _stub_rid(None, exists=False),
    )
    out = get_reaction_compounds("R99999")
    assert out["exists"] is False
    assert out["substrates"] == []
    assert out["products"] == []


# ---- verify_reaction_substrate (integration of resolver + lookup) ---------


def _patch_lookup(monkeypatch, equation: str | None, exists: bool = True):
    monkeypatch.setattr(
        _kegg_verify, "verify_kegg_reaction_id",
        lambda rid, **kw: _stub_rid(equation, exists=exists),
    )


def test_verify_reaction_substrate_fully_matches(monkeypatch):
    # Agent: acetyl-CoA -> citrate (R00351, citrate synthase)
    # KEGG: C00024 + C00036 + C00001 <=> C00158 + C00010
    _patch_lookup(monkeypatch, "C00024 + C00036 + C00001 <=> C00158 + C00010")
    out = verify_reaction_substrate("R00351", "acetyl-CoA", "citrate")
    assert out["verdict"] == "fully_matches"
    assert out["substrate_matches"] is True
    assert out["product_matches"] is True
    assert out["claimed_substrate_ids"] == ["C00024"]
    assert out["claimed_product_ids"] == ["C00158"]


def test_verify_reaction_substrate_neither_real_but_wrong(monkeypatch):
    # Agent: acetyl-CoA -> acetoacetyl-CoA, but cites a R-ID for some
    # totally unrelated reaction (say lactate dehydrogenase: pyruvate + NADH <=> lactate + NAD+).
    _patch_lookup(monkeypatch, "C00022 + C00004 <=> C00186 + C00003")
    out = verify_reaction_substrate("R01700", "acetyl-CoA", "acetoacetyl-CoA")
    assert out["verdict"] == "neither"
    assert out["substrate_matches"] is False
    assert out["product_matches"] is False


def test_verify_reaction_substrate_substrate_only(monkeypatch):
    # Agent: acetyl-CoA -> citrate, but cited R-ID's equation has acetyl-CoA
    # in it but NOT citrate.
    _patch_lookup(monkeypatch, "C00024 + C00033 <=> C00083 + C00010")
    out = verify_reaction_substrate("R00000", "acetyl-CoA", "citrate")
    assert out["verdict"] == "substrate_only"
    assert out["substrate_matches"] is True
    assert out["product_matches"] is False


def test_verify_reaction_substrate_rid_invalid(monkeypatch):
    _patch_lookup(monkeypatch, None, exists=False)
    out = verify_reaction_substrate("R99999", "acetyl-CoA", "citrate")
    assert out["verdict"] == "rid_invalid"
    assert out["rid_exists"] is False


def test_verify_reaction_substrate_unresolved_substrate(monkeypatch):
    """Resolver miss + remote disabled → empty resolved set → cannot match."""
    _patch_lookup(monkeypatch, "C00024 + C00036 <=> C00158 + C00010")
    out = verify_reaction_substrate(
        "R00351", "totally-fake-compound-xyz", "citrate",
        use_remote_resolver=False,
    )
    assert out["verdict"] == "product_only"  # citrate matched, fake didn't
    assert out["substrate_resolved"] is False
    assert out["product_resolved"] is True


def test_verify_reaction_substrate_reverse_direction(monkeypatch):
    """KEGG records reaction in reverse of agent's stated direction."""
    # KEGG: citrate <=> acetyl-CoA + oxaloacetate (just for illustration)
    _patch_lookup(monkeypatch, "C00158 <=> C00024 + C00036")
    out = verify_reaction_substrate("R00000", "acetyl-CoA", "citrate")
    # Direction-lenient — both compounds present, verdict fully_matches.
    assert out["verdict"] == "fully_matches"


def test_verify_reaction_substrate_accepts_name_lists(monkeypatch):
    """Step lines can have multi-substrate sides ('A + B -> C').
    The resolver runs over each name and the matcher unions the C-IDs.
    """
    # R00351 stored direction: citrate <=> acetyl-CoA + oxaloacetate + CoA
    _patch_lookup(monkeypatch, "C00158 + C00010 <=> C00024 + C00001 + C00036")
    out = verify_reaction_substrate(
        "R00351",
        ["acetyl-CoA", "oxaloacetate"],   # multi-substrate step
        ["citrate"],
    )
    assert out["verdict"] == "fully_matches"
    # Both substrate names should resolve into claimed_substrate_ids
    assert "C00024" in out["claimed_substrate_ids"]
    assert "C00036" in out["claimed_substrate_ids"]
    assert out["claimed_product_ids"] == ["C00158"]
