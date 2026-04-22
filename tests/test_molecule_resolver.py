"""
Phase 5 — molecule resolver tests.

All tests use injected fake sub-resolvers and fake InChIKey/formula lookups,
so nothing hits the network or ChromaDB. Covers:

- input-form classification for all supported forms
- Tier 1 EXACT paths: KEGG compound id, PubChem CID, InChIKey, formula
- Tier 2 APPROXIMATE paths: name → PubChem + KEGG-indexed with synonym-promote
- Tier 3 INFERRED fallback: semantic KEGG when nothing else matched
- Cross-source merge: KEGG hit with xref to PubChem CID unifies with a
  PubChem hit into a single canonical Molecule
- ChEBI stub: disabled-by-default behavior, easy enable path
- resolve_canonical returns a single merged molecule for downstream tools

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_molecule_resolver
"""
from __future__ import annotations

import unittest

from agent.rag.interfaces import (
    EntityCandidate,
    EntityKind,
    Molecule,
    ResolutionTier,
)
from agent.rag.molecule_resolver import (
    ChEBIResolver,
    InputForm,
    MoleculeResolver,
    classify_input,
)


# ---------- fake sub-resolvers ----------
class _FakeResolver:
    """Returns a fixed candidate list keyed by query string.

    Matches the EntityResolver Protocol. ``supported_kinds`` is MOLECULE by
    default but tests can override.
    """

    def __init__(self, name: str, by_query: dict[str, list[EntityCandidate]]):
        self.name = name
        self._by_query = by_query
        self.supported_kinds = (EntityKind.MOLECULE,)
        self.calls: list[tuple[str, EntityKind]] = []

    def resolve(self, query: str, kind: EntityKind, *, limit: int = 5):
        self.calls.append((query, kind))
        return list(self._by_query.get(query, []))


def _make_candidate(mol: Molecule, tier: ResolutionTier, confidence: float,
                    provenance: str) -> EntityCandidate:
    return EntityCandidate(
        entity=mol, kind=EntityKind.MOLECULE,
        tier=tier, confidence=confidence, provenance=provenance,
    )


# ---------- Lycopene canonical fixtures ----------
_LYCOPENE_KEGG = Molecule(
    canonical_id="C05432",
    source="kegg",
    name="Lycopene",
    synonyms=("lycopene", "all-trans-lycopene"),
    formula="C40H56",
    url="https://www.kegg.jp/entry/cpd:C05432",
    cross_refs=(("pubchem", "CID:446925"),),
)
_LYCOPENE_PUBCHEM = Molecule(
    canonical_id="CID:446925",
    source="pubchem",
    name="Lycopene",
    synonyms=("Lycopene", "psi,psi-Carotene"),
    formula="C40H56",
    molecular_weight=536.87,
    smiles="CC(=CCC/C(=C/C=C/C(=C/C=C/C(=C/C=C/C=C(/C)\\C=C\\C=C(/C)\\C=C\\C=C(/C)CCC=C(C)C)/C)/C)C",
    url="https://pubchem.ncbi.nlm.nih.gov/compound/446925",
)


# ---------- classify_input ----------
class ClassifyInputTest(unittest.TestCase):
    CASES = [
        ("", InputForm.EMPTY),
        ("  ", InputForm.EMPTY),
        ("C05432", InputForm.KEGG_COMPOUND),
        ("cpd:C05432", InputForm.KEGG_COMPOUND),
        ("C99999", InputForm.KEGG_COMPOUND),
        ("CHEBI:15756", InputForm.CHEBI_ID),
        ("chebi:15756", InputForm.CHEBI_ID),
        ("CHEBI15756", InputForm.CHEBI_ID),
        ("446925", InputForm.PUBCHEM_CID),
        ("CID:446925", InputForm.PUBCHEM_CID),
        ("CID 446925", InputForm.PUBCHEM_CID),
        ("C40H56", InputForm.FORMULA),
        ("C8H10N4O2", InputForm.FORMULA),
        ("OAIJSZIZWZSQBC-GYZMGTAESA-N", InputForm.INCHIKEY),
        ("InChI=1S/C40H56", InputForm.INCHI),
        ("lycopene", InputForm.NAME),
        ("phytoene desaturase product", InputForm.NAME),
        ("all-trans-lycopene", InputForm.NAME),
    ]

    def test_classify(self):
        for q, expected in self.CASES:
            self.assertEqual(classify_input(q), expected, f"query={q!r}")


# ---------- Tier 1 EXACT ----------
class Tier1ExactTest(unittest.TestCase):
    def test_kegg_compound_id_hits_kegg_live(self):
        kegg = _FakeResolver("kegg_live", {
            "C05432": [_make_candidate(_LYCOPENE_KEGG,
                                        ResolutionTier.EXACT, 0.95, "kegg_live")],
        })
        # Other sub-resolvers should not be consulted in Tier 1 for KEGG IDs.
        pubchem = _FakeResolver("pubchem", {})
        indexed = _FakeResolver("kegg_indexed", {})
        resolver = MoleculeResolver(
            kegg_live=kegg, pubchem=pubchem, kegg_indexed=indexed,
        )
        cands = resolver.resolve("C05432")
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].tier, ResolutionTier.EXACT)
        self.assertEqual(cands[0].entity.canonical_id, "C05432")
        self.assertEqual(pubchem.calls, [])
        self.assertEqual(indexed.calls, [])

    def test_pubchem_cid_hits_pubchem(self):
        pubchem = _FakeResolver("pubchem", {
            "446925": [_make_candidate(_LYCOPENE_PUBCHEM,
                                        ResolutionTier.EXACT, 0.95, "pubchem")],
        })
        resolver = MoleculeResolver(
            pubchem=pubchem,
            kegg_live=_FakeResolver("kegg_live", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
        )
        # Both "446925" and "CID:446925" must route to the same lookup.
        for q in ("446925", "CID:446925"):
            cands = resolver.resolve(q)
            self.assertEqual(len(cands), 1, q)
            self.assertEqual(cands[0].tier, ResolutionTier.EXACT, q)

    def test_inchikey_routes_to_pubchem_via_lookup(self):
        inchikey = "OAIJSZIZWZSQBC-GYZMGTAESA-N"
        pubchem = _FakeResolver("pubchem", {
            "446925": [_make_candidate(_LYCOPENE_PUBCHEM,
                                        ResolutionTier.EXACT, 0.95, "pubchem")],
        })
        def _fake_inchikey_lookup(key):
            return 446925 if key == inchikey else None

        resolver = MoleculeResolver(
            pubchem=pubchem,
            kegg_live=_FakeResolver("kegg_live", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
            inchikey_lookup=_fake_inchikey_lookup,
        )
        cands = resolver.resolve(inchikey)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].tier, ResolutionTier.EXACT)
        self.assertEqual(cands[0].entity.canonical_id, "CID:446925")
        self.assertEqual(cands[0].entity.inchikey, inchikey)

    def test_formula_downgrades_to_approximate(self):
        pubchem = _FakeResolver("pubchem", {
            "446925": [_make_candidate(_LYCOPENE_PUBCHEM,
                                        ResolutionTier.EXACT, 0.95, "pubchem")],
        })
        resolver = MoleculeResolver(
            pubchem=pubchem,
            kegg_live=_FakeResolver("kegg_live", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
            formula_lookup=lambda f: 446925 if f == "C40H56" else None,
            inchikey_lookup=lambda k: None,
        )
        cands = resolver.resolve("C40H56")
        self.assertEqual(len(cands), 1)
        # Formula isn't a unique identifier → tier is APPROXIMATE.
        self.assertEqual(cands[0].tier, ResolutionTier.APPROXIMATE)


# ---------- Tier 2 APPROXIMATE ----------
class Tier2ApproximateTest(unittest.TestCase):
    def test_name_query_fans_out_to_pubchem_and_kegg_indexed(self):
        pubchem = _FakeResolver("pubchem", {
            "lycopene": [_make_candidate(_LYCOPENE_PUBCHEM,
                                          ResolutionTier.APPROXIMATE, 0.70, "pubchem")],
        })
        # KEGG indexed is semantic (INFERRED), but name match upgrades to APPROXIMATE.
        kegg_indexed = _FakeResolver("kegg_indexed", {
            "lycopene": [_make_candidate(_LYCOPENE_KEGG,
                                          ResolutionTier.INFERRED, 0.82, "kegg_indexed")],
        })
        resolver = MoleculeResolver(
            pubchem=pubchem,
            kegg_indexed=kegg_indexed,
            kegg_live=_FakeResolver("kegg_live", {}),
            inchikey_lookup=lambda k: None,
        )
        cands = resolver.resolve("lycopene", limit=10)
        # KEGG + PubChem share pubchem CID via cross-refs → merged to 1 candidate.
        self.assertEqual(len(cands), 1)
        merged_mol: Molecule = cands[0].entity
        # Canonical ID stays the best-tier entry's id (kegg was promoted to
        # APPROXIMATE, pubchem is also APPROXIMATE — kegg sorted first alph).
        self.assertIn(cands[0].tier, (ResolutionTier.APPROXIMATE,))
        xrefs = merged_mol.cross_refs_dict()
        self.assertIn("pubchem", xrefs)
        self.assertEqual(xrefs["pubchem"], "CID:446925")
        # Synonyms union preserved.
        self.assertIn("all-trans-lycopene", merged_mol.synonyms)
        self.assertIn("psi,psi-Carotene", merged_mol.synonyms)

    def test_name_with_no_match_tier_downs_to_inferred(self):
        pubchem = _FakeResolver("pubchem", {})
        unknown_mol = Molecule(
            canonical_id="C99999", source="kegg",
            name="unrelated compound",
        )
        kegg_indexed = _FakeResolver("kegg_indexed", {
            "never heard of it": [_make_candidate(unknown_mol,
                                                   ResolutionTier.INFERRED, 0.4, "kegg_indexed")],
        })
        resolver = MoleculeResolver(
            pubchem=pubchem,
            kegg_indexed=kegg_indexed,
            kegg_live=_FakeResolver("kegg_live", {}),
            inchikey_lookup=lambda k: None,
        )
        cands = resolver.resolve("never heard of it")
        self.assertEqual(len(cands), 1)
        # Kept at INFERRED because no name match.
        self.assertEqual(cands[0].tier, ResolutionTier.INFERRED)


# ---------- merge semantics ----------
class MergeTest(unittest.TestCase):
    def test_merge_shares_inchikey(self):
        inchikey = "OAIJSZIZWZSQBC-GYZMGTAESA-N"
        a = Molecule(canonical_id="C05432", source="kegg", name="Lycopene",
                     inchikey=inchikey, synonyms=("lycopene",))
        b = Molecule(canonical_id="CID:446925", source="pubchem", name="Lycopene",
                     inchikey=inchikey, formula="C40H56")
        resolver = MoleculeResolver(
            pubchem=_FakeResolver("pubchem", {
                "x": [_make_candidate(b, ResolutionTier.APPROXIMATE, 0.7, "pubchem")]}),
            kegg_indexed=_FakeResolver("kegg_indexed", {
                "x": [_make_candidate(a, ResolutionTier.INFERRED, 0.9, "kegg_indexed")]}),
            kegg_live=_FakeResolver("kegg_live", {}),
            inchikey_lookup=lambda k: None,
        )
        cands = resolver.resolve("x", limit=5)
        # InChIKey-merged → single candidate.
        self.assertEqual(len(cands), 1)
        merged: Molecule = cands[0].entity
        self.assertEqual(merged.inchikey, inchikey)
        # formula from pubchem enriches the primary.
        self.assertEqual(merged.formula, "C40H56")

    def test_non_matching_molecules_stay_separate(self):
        a = Molecule(canonical_id="C05432", source="kegg", name="Lycopene",
                     formula="C40H56")
        b = Molecule(canonical_id="CID:2244", source="pubchem", name="Aspirin",
                     formula="C9H8O4")
        resolver = MoleculeResolver(
            pubchem=_FakeResolver("pubchem", {
                "x": [_make_candidate(b, ResolutionTier.APPROXIMATE, 0.7, "pubchem")]}),
            kegg_indexed=_FakeResolver("kegg_indexed", {
                "x": [_make_candidate(a, ResolutionTier.INFERRED, 0.9, "kegg_indexed")]}),
            kegg_live=_FakeResolver("kegg_live", {}),
            inchikey_lookup=lambda k: None,
        )
        cands = resolver.resolve("x", limit=5)
        self.assertEqual(len(cands), 2)


# ---------- ChEBI stub ----------
class ChEBIStubTest(unittest.TestCase):
    def test_stub_returns_empty_by_default(self):
        stub = ChEBIResolver()
        self.assertFalse(stub.enabled)
        self.assertEqual(stub.resolve("lycopene", EntityKind.MOLECULE), [])

    def test_subclass_can_implement_fetch(self):
        class FakeChEBI(ChEBIResolver):
            name = "chebi_fake"
            enabled = True

            def _fetch(self, query, kind, *, limit):
                mol = Molecule(canonical_id="CHEBI:15756", source="chebi",
                               name="lycopene")
                return [_make_candidate(mol, ResolutionTier.EXACT, 0.95, self.name)]

        resolver = MoleculeResolver(
            chebi=FakeChEBI(),
            kegg_live=_FakeResolver("kegg_live", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
            pubchem=_FakeResolver("pubchem", {}),
        )
        cands = resolver.resolve("CHEBI:15756")
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].entity.source, "chebi")
        self.assertEqual(cands[0].tier, ResolutionTier.EXACT)


# ---------- resolve_canonical ----------
class ResolveCanonicalTest(unittest.TestCase):
    def test_returns_merged_molecule(self):
        kegg = _FakeResolver("kegg_live", {
            "C05432": [_make_candidate(_LYCOPENE_KEGG,
                                        ResolutionTier.EXACT, 0.95, "kegg_live")],
        })
        resolver = MoleculeResolver(
            kegg_live=kegg,
            pubchem=_FakeResolver("pubchem", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
        )
        mol = resolver.resolve_canonical("C05432")
        self.assertIsInstance(mol, Molecule)
        self.assertEqual(mol.canonical_id, "C05432")
        self.assertEqual(mol.cross_refs_dict().get("pubchem"), "CID:446925")

    def test_none_on_no_match(self):
        resolver = MoleculeResolver(
            pubchem=_FakeResolver("pubchem", {}),
            kegg_live=_FakeResolver("kegg_live", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
        )
        self.assertIsNone(resolver.resolve_canonical("nonexistent"))

    def test_ignores_non_molecule_kind(self):
        resolver = MoleculeResolver(
            pubchem=_FakeResolver("pubchem", {}),
            kegg_live=_FakeResolver("kegg_live", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
        )
        self.assertEqual(resolver.resolve("lycopene", kind=EntityKind.ENZYME), [])


# ---------- Representative-molecule fixtures (end-to-end shape check) ----------
class RepresentativeMoleculesTest(unittest.TestCase):
    """Document-level tests covering the three Day-1 demo scenarios + caffeine.

    These fixtures also serve as documentation for expected resolution
    behavior on the hackathon's validation molecules.
    """

    def _fixture(self, kegg_id, cid, name, synonyms=(), formula=None):
        kegg_mol = Molecule(
            canonical_id=kegg_id, source="kegg", name=name,
            synonyms=synonyms, formula=formula,
            cross_refs=(("pubchem", f"CID:{cid}"),),
        )
        pubchem_mol = Molecule(
            canonical_id=f"CID:{cid}", source="pubchem", name=name,
            synonyms=synonyms, formula=formula,
        )
        return kegg_mol, pubchem_mol

    def test_artemisinic_acid(self):
        kegg_mol, pc_mol = self._fixture(
            "C11514", 5315548, "Artemisinic acid",
            synonyms=("artemisinate",), formula="C15H22O2")
        resolver = MoleculeResolver(
            kegg_live=_FakeResolver("kegg_live", {
                "C11514": [_make_candidate(kegg_mol,
                                            ResolutionTier.EXACT, 0.95, "kegg_live")]}),
            pubchem=_FakeResolver("pubchem", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
        )
        mol = resolver.resolve_canonical("C11514")
        self.assertIsNotNone(mol)
        self.assertEqual(mol.name, "Artemisinic acid")
        self.assertEqual(mol.formula, "C15H22O2")

    def test_taxadiene_by_name(self):
        kegg_mol, pc_mol = self._fixture(
            "C11894", 443162, "Taxa-4,11-diene",
            synonyms=("taxadiene",), formula="C20H32")
        resolver = MoleculeResolver(
            pubchem=_FakeResolver("pubchem", {
                "taxadiene": [_make_candidate(pc_mol,
                                               ResolutionTier.APPROXIMATE, 0.7, "pubchem")]}),
            kegg_indexed=_FakeResolver("kegg_indexed", {
                "taxadiene": [_make_candidate(kegg_mol,
                                               ResolutionTier.INFERRED, 0.75, "kegg_indexed")]}),
            kegg_live=_FakeResolver("kegg_live", {}),
            inchikey_lookup=lambda k: None,
        )
        cands = resolver.resolve("taxadiene")
        # Synonym-promote + xref merge → one canonical hit.
        self.assertEqual(len(cands), 1)
        merged = cands[0].entity
        self.assertIn("taxadiene", merged.synonyms)
        self.assertEqual(merged.formula, "C20H32")
        self.assertEqual(merged.cross_refs_dict().get("pubchem"), "CID:443162")

    def test_vanillin_pubchem_cid(self):
        kegg_mol, pc_mol = self._fixture(
            "C00755", 1183, "Vanillin",
            synonyms=("4-Hydroxy-3-methoxybenzaldehyde",), formula="C8H8O3")
        resolver = MoleculeResolver(
            pubchem=_FakeResolver("pubchem", {
                "1183": [_make_candidate(pc_mol,
                                          ResolutionTier.EXACT, 0.95, "pubchem")]}),
            kegg_live=_FakeResolver("kegg_live", {}),
            kegg_indexed=_FakeResolver("kegg_indexed", {}),
        )
        mol = resolver.resolve_canonical("1183")
        self.assertIsNotNone(mol)
        self.assertEqual(mol.canonical_id, "CID:1183")
        self.assertEqual(mol.formula, "C8H8O3")


if __name__ == "__main__":
    unittest.main()
