"""
RAG foundation (Phase 4) contract tests.

Covers the interface/protocol layer — no live network calls, no ChromaDB.

What we verify:
- Dataclasses hash/compare as expected (they're used as dict keys in dedup).
- ``ResolutionTier.rank()`` orders EXACT < APPROXIMATE < INFERRED.
- Our adapters satisfy the Protocol contracts structurally.
- HybridRetriever fans out, dedupes by (source, canonical_id), tier-orders,
  and tolerates a broken resolver.
- KeggIndexedResolver wires into a fake ``Retriever`` that mimics the real
  surface — this locks the adapter-to-retriever coupling.

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_rag_interfaces
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any, Optional

from agent.rag.adapters import (
    KeggIndexedResolver,
    KeggIndexedRetriever,
    LiteratureRetriever,
    PubChemResolver,
    UniProtResolver,
)
from agent.rag.hybrid import HybridRetriever
from agent.rag.interfaces import (
    EntityCandidate,
    EntityKind,
    EntityResolver,
    Enzyme,
    Evidence,
    Molecule,
    Paper,
    Reaction,
    ResolutionTier,
    StructuredRetriever,
)


# ---------- minimal stand-ins for the real Retriever ----------
@dataclass
class _FakeDoc:
    id: str
    text: str
    metadata: dict
    score: float
    extras: dict = field(default_factory=dict)


class _FakeRetriever:
    """Mirrors the subset of vectorstore.Retriever that adapters use."""

    def __init__(self, reactions=None, compounds=None, literature=None):
        self._reactions = reactions or []
        self._compounds = compounds or []
        self._literature = literature or []
        self.calls: list[tuple[str, dict]] = []

    def search_reactions(self, query, **kwargs):
        self.calls.append(("reactions", {"query": query, **kwargs}))
        return list(self._reactions)

    def search_compounds(self, query, **kwargs):
        self.calls.append(("compounds", {"query": query, **kwargs}))
        return list(self._compounds)

    def search_literature(self, query, **kwargs):
        self.calls.append(("literature", {"query": query, **kwargs}))
        return list(self._literature)


# ---------- Tier + dataclass shape ----------
class TierOrderingTest(unittest.TestCase):
    def test_tier_rank_strict_order(self):
        self.assertLess(ResolutionTier.EXACT.rank(), ResolutionTier.APPROXIMATE.rank())
        self.assertLess(ResolutionTier.APPROXIMATE.rank(), ResolutionTier.INFERRED.rank())

    def test_molecule_is_hashable(self):
        m = Molecule(canonical_id="C05432", source="kegg", name="Lycopene")
        # Frozen dataclass → must be hashable (set construction exercises __hash__).
        self.assertEqual({m, m}, {m})


# ---------- Protocol conformance (structural / runtime_checkable) ----------
class ProtocolConformanceTest(unittest.TestCase):
    def test_all_resolvers_match_protocol(self):
        for R in (KeggIndexedResolver(retriever=_FakeRetriever()),
                  PubChemResolver(),
                  UniProtResolver()):
            self.assertIsInstance(R, EntityResolver, R.name)

    def test_all_retrievers_match_protocol(self):
        for R in (KeggIndexedRetriever(retriever=_FakeRetriever()),
                  LiteratureRetriever(retriever=_FakeRetriever())):
            self.assertIsInstance(R, StructuredRetriever, R.name)


# ---------- KeggIndexedResolver wiring ----------
class KeggIndexedResolverTest(unittest.TestCase):
    def _fake(self):
        return _FakeRetriever(
            compounds=[_FakeDoc(
                id="kegg_C05432",
                text="Lycopene",
                score=0.88,
                metadata={"kegg_id": "C05432", "primary_name": "Lycopene",
                          "formula": "C40H56", "names": "lycopene,all-trans-lycopene"},
            )],
            reactions=[_FakeDoc(
                id="kegg_R02003",
                text="GGPP → prephytoene",
                score=0.81,
                metadata={"kegg_id": "R02003", "equation": "GGPP -> prephytoene",
                          "ec_numbers": "2.5.1.32", "substrates": "C00353",
                          "products": "C05807", "pathway_ids": "map00906"},
            )],
        )

    def test_molecule_candidate_populated(self):
        resolver = KeggIndexedResolver(retriever=self._fake())
        cands = resolver.resolve("lycopene", EntityKind.MOLECULE)
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertIsInstance(c.entity, Molecule)
        self.assertEqual(c.entity.canonical_id, "C05432")
        self.assertEqual(c.entity.formula, "C40H56")
        self.assertIn("lycopene", c.entity.synonyms)
        self.assertEqual(c.tier, ResolutionTier.INFERRED)
        # Confidence is the cosine score for inferred-tier candidates.
        self.assertAlmostEqual(c.confidence, 0.88, places=5)

    def test_reaction_candidate_splits_csv_metadata(self):
        resolver = KeggIndexedResolver(retriever=self._fake())
        cands = resolver.resolve("GGPP to prephytoene", EntityKind.REACTION)
        self.assertEqual(len(cands), 1)
        rxn: Reaction = cands[0].entity
        self.assertEqual(rxn.reaction_id, "R02003")
        self.assertEqual(rxn.ec_numbers, ("2.5.1.32",))
        self.assertEqual(rxn.substrates, ("C00353",))
        self.assertEqual(rxn.products, ("C05807",))

    def test_unsupported_kind_is_empty(self):
        resolver = KeggIndexedResolver(retriever=self._fake())
        self.assertEqual(resolver.resolve("x", EntityKind.ENZYME), [])
        self.assertEqual(resolver.resolve("", EntityKind.MOLECULE), [])


# ---------- LiteratureRetriever wiring ----------
class LiteratureRetrieverTest(unittest.TestCase):
    def test_evidence_shape(self):
        lit = _FakeRetriever(literature=[_FakeDoc(
            id="pmid_12345",
            text="Engineering E. coli to produce lycopene by overexpressing crtEBI.",
            score=0.77,
            metadata={"pmid": "12345", "title": "Lycopene in E. coli",
                      "year": "2012", "journal": "Metab Eng",
                      "source": "pubmed", "mesh_terms": "Lycopene,Escherichia coli"},
        )])
        retriever = LiteratureRetriever(retriever=lit)
        evs = retriever.retrieve("lycopene biosynthesis", kind=EntityKind.PAPER)
        self.assertEqual(len(evs), 1)
        ev = evs[0]
        self.assertIsInstance(ev, Evidence)
        self.assertIsInstance(ev.subject, Paper)
        self.assertEqual(ev.subject.pmid, "12345")
        self.assertEqual(ev.subject.mesh_terms, ("Lycopene", "Escherichia coli"))
        self.assertEqual(ev.source, "literature")
        self.assertAlmostEqual(ev.score, 0.77, places=5)


# ---------- HybridRetriever orchestration ----------
class _StubResolver:
    """Protocol-compatible stub that returns a fixed candidate list."""

    def __init__(self, name, supported_kinds, candidates):
        self.name = name
        self.supported_kinds = supported_kinds
        self._candidates = candidates

    def resolve(self, query, kind, *, limit=5):
        return list(self._candidates)


class _BrokenResolver:
    name = "broken"
    supported_kinds = (EntityKind.MOLECULE,)

    def resolve(self, query, kind, *, limit=5):
        raise RuntimeError("simulated resolver crash")


def _mol_candidate(canonical_id, source, tier, conf, provenance="stub"):
    return EntityCandidate(
        entity=Molecule(canonical_id=canonical_id, source=source),
        kind=EntityKind.MOLECULE,
        tier=tier,
        confidence=conf,
        provenance=provenance,
    )


class HybridRetrieverTest(unittest.TestCase):
    def test_fanout_and_tier_ordering(self):
        exact = _mol_candidate("C05432", "kegg", ResolutionTier.EXACT, 0.95, "kegg_live")
        approx = _mol_candidate("CID:446925", "pubchem",
                                ResolutionTier.APPROXIMATE, 0.70, "pubchem")
        inferred = _mol_candidate("C05432-near", "kegg",
                                  ResolutionTier.INFERRED, 0.8, "kegg_indexed")

        hr = HybridRetriever()
        hr.register_resolver(_StubResolver("a", (EntityKind.MOLECULE,), [inferred]))
        hr.register_resolver(_StubResolver("b", (EntityKind.MOLECULE,), [exact]))
        hr.register_resolver(_StubResolver("c", (EntityKind.MOLECULE,), [approx]))

        ordered = hr.resolve("lycopene", EntityKind.MOLECULE, limit=10)
        self.assertEqual([c.tier for c in ordered],
                         [ResolutionTier.EXACT,
                          ResolutionTier.APPROXIMATE,
                          ResolutionTier.INFERRED])

    def test_dedupe_keeps_better_tier(self):
        low = _mol_candidate("C05432", "kegg", ResolutionTier.INFERRED, 0.9, "lo")
        high = _mol_candidate("C05432", "kegg", ResolutionTier.EXACT, 0.95, "hi")
        hr = HybridRetriever()
        hr.register_resolver(_StubResolver("lo", (EntityKind.MOLECULE,), [low]))
        hr.register_resolver(_StubResolver("hi", (EntityKind.MOLECULE,), [high]))
        out = hr.resolve("lycopene", EntityKind.MOLECULE)
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], high)

    def test_unsupported_kind_resolver_is_skipped(self):
        m = _mol_candidate("C05432", "kegg", ResolutionTier.EXACT, 0.95)
        protein_only = _StubResolver("proteins_only", (EntityKind.ENZYME,), [m])
        molecules_only = _StubResolver("mols", (EntityKind.MOLECULE,), [m])
        hr = HybridRetriever()
        hr.register_resolver(protein_only)
        hr.register_resolver(molecules_only)
        out = hr.resolve("lycopene", EntityKind.MOLECULE)
        self.assertEqual(len(out), 1)  # protein-only resolver wasn't called

    def test_broken_resolver_does_not_crash_pipeline(self):
        good = _mol_candidate("C05432", "kegg", ResolutionTier.EXACT, 0.95)
        hr = HybridRetriever()
        hr.register_resolver(_BrokenResolver())
        hr.register_resolver(_StubResolver("good", (EntityKind.MOLECULE,), [good]))
        out = hr.resolve("lycopene", EntityKind.MOLECULE)
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], good)

    def test_empty_query_returns_empty(self):
        hr = HybridRetriever()
        hr.register_resolver(_StubResolver(
            "x", (EntityKind.MOLECULE,),
            [_mol_candidate("C00001", "kegg", ResolutionTier.EXACT, 0.95)]))
        self.assertEqual(hr.resolve("   ", EntityKind.MOLECULE), [])

    def test_retrieve_dedupes_by_doc_id_and_prefers_higher_score(self):
        class _Ret:
            name = "r"
            supported_kinds = (EntityKind.PAPER,)

            def __init__(self, items):
                self._items = items

            def retrieve(self, query, *, kind=None, filters=None, top_k=5):
                return list(self._items)

        low = Evidence(text="x", score=0.3, source="lit", doc_id="pmid_1")
        high = Evidence(text="x", score=0.9, source="lit", doc_id="pmid_1")

        hr = HybridRetriever()
        hr.register_retriever(_Ret([low]))
        hr.register_retriever(_Ret([high]))
        out = hr.retrieve("lycopene", kind=EntityKind.PAPER)
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], high)


class DefaultHybridFactoryTest(unittest.TestCase):
    def test_default_wires_all_adapters(self):
        """Smoke test: factory should produce a HybridRetriever populated
        with the Phase 4 adapters. No network calls here (we don't invoke)."""
        from agent.rag.hybrid import default_hybrid_retriever

        hr = default_hybrid_retriever()
        resolver_names = {r.name for r in hr.resolvers}
        retriever_names = {r.name for r in hr.retrievers}
        self.assertIn("kegg_live", resolver_names)
        self.assertIn("kegg_indexed", resolver_names)
        self.assertIn("pubchem", resolver_names)
        self.assertIn("uniprot", resolver_names)
        self.assertIn("literature_indexed", retriever_names)
        self.assertIn("kegg_indexed_retriever", retriever_names)


class EcPrefixStripperTests(unittest.TestCase):
    """Hardening regression: ``str.lstrip(\"ec:\")`` silently mis-strips because
    lstrip treats the arg as a character set. ``_strip_ec_prefix`` must use
    substring-aware ``removeprefix``-style stripping.
    """

    def test_strip_ec_prefix_handles_known_forms(self):
        from agent.rag.adapters import _strip_ec_prefix

        self.assertEqual(_strip_ec_prefix("ec:2.5.1.29"), "2.5.1.29")
        self.assertEqual(_strip_ec_prefix("EC 2.5.1.29"), "2.5.1.29")
        self.assertEqual(_strip_ec_prefix("EC:2.5.1.29"), "2.5.1.29")
        self.assertEqual(_strip_ec_prefix("2.5.1.29"), "2.5.1.29")

    def test_strip_ec_prefix_does_not_mangle_values(self):
        from agent.rag.adapters import _strip_ec_prefix

        # lstrip would have chewed through the leading "ec" here, returning
        # ":2.5.1.29" or worse. removeprefix must not.
        self.assertEqual(_strip_ec_prefix("ece:1.1.1.1"), "ece:1.1.1.1")
        self.assertEqual(_strip_ec_prefix("  ec:1.1.1.1  "), "1.1.1.1")


if __name__ == "__main__":
    unittest.main()
