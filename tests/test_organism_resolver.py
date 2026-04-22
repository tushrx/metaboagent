"""
Phase 6 — organism / chassis resolver tests.

Covers:
- Strain-level hits (scientific name, strain alias, taxonomy id) produce
  EXACT_STRAIN + ResolutionTier.EXACT.
- Species-level hits produce EXACT_SPECIES + ResolutionTier.EXACT.
- Chassis-generalized hits (chassis key, KEGG org code, common-name aliases)
  produce CHASSIS_GENERALIZED + ResolutionTier.APPROXIMATE.
- Unknown inputs return an empty list (no silent defaulting).
- Compatibility helpers ``to_chassis_key`` / ``to_kegg_org`` match legacy
  chassis map semantics without echoing unknowns.
- Injected ``taxonomy_lookup`` fires only when local tiers miss.
- ``resolve(kind=... != ORGANISM)`` short-circuits to ``[]`` — protocol
  requirement from ``EntityResolver``.
- ``Organism.as_chassis_dict()`` produces the legacy dict shape verbatim,
  so callers migrating from ``config.CHASSIS_ORGANISMS`` can swap cleanly.

Run with:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_organism_resolver
"""
from __future__ import annotations

import unittest

from agent.rag import (
    EntityKind,
    MatchType,
    Organism,
    OrganismResolver,
    ResolutionTier,
    default_organism_resolver,
)
from config import CHASSIS_ORGANISMS


class OrganismResolverStrainTests(unittest.TestCase):
    def setUp(self):
        self.resolver = default_organism_resolver()

    def _assert_strain(self, query: str, expected_chassis: str):
        cands = self.resolver.resolve(query, EntityKind.ORGANISM)
        self.assertTrue(cands, f"{query!r} did not resolve")
        cand = cands[0]
        self.assertEqual(cand.tier, ResolutionTier.EXACT)
        self.assertIsInstance(cand.entity, Organism)
        org = cand.entity
        self.assertEqual(org.match_type, MatchType.EXACT_STRAIN)
        self.assertEqual(org.canonical_id, expected_chassis)

    def test_full_scientific_name(self):
        self._assert_strain("Escherichia coli K-12 MG1655", "ecoli")
        self._assert_strain("Saccharomyces cerevisiae S288c", "scerevisiae")
        self._assert_strain("Pseudomonas putida KT2440", "pputida")

    def test_strain_aliases(self):
        for q in ("MG1655", "K-12", "K12"):
            self._assert_strain(q, "ecoli")
        for q in ("S288c", "S288C"):
            self._assert_strain(q, "scerevisiae")
        for q in ("KT2440", "KT-2440"):
            self._assert_strain(q, "pputida")
        for q in ("ATCC 13032", "ATCC13032", "13032"):
            self._assert_strain(q, "cglutamicum")

    def test_taxonomy_id_matches_strain(self):
        # Taxonomy IDs index at strain-level since they name a specific strain.
        self._assert_strain("511145", "ecoli")
        self._assert_strain("559292", "scerevisiae")
        self._assert_strain("160488", "pputida")

    def test_confidence_peak_for_strain(self):
        cands = self.resolver.resolve("MG1655", EntityKind.ORGANISM)
        self.assertAlmostEqual(cands[0].confidence, 0.95)


class OrganismResolverSpeciesTests(unittest.TestCase):
    def setUp(self):
        self.resolver = default_organism_resolver()

    def _assert_species(self, query: str, expected_chassis: str):
        cands = self.resolver.resolve(query, EntityKind.ORGANISM)
        self.assertTrue(cands, f"{query!r} did not resolve")
        cand = cands[0]
        self.assertEqual(cand.tier, ResolutionTier.EXACT)
        org = cand.entity
        self.assertIsInstance(org, Organism)
        self.assertEqual(org.match_type, MatchType.EXACT_SPECIES)
        self.assertEqual(org.canonical_id, expected_chassis)

    def test_species_names(self):
        self._assert_species("Escherichia coli", "ecoli")
        self._assert_species("Saccharomyces cerevisiae", "scerevisiae")
        self._assert_species("Corynebacterium glutamicum", "cglutamicum")
        self._assert_species("Bacillus subtilis", "bsubtilis")
        self._assert_species("Pseudomonas putida", "pputida")

    def test_species_case_and_dots(self):
        # "E.coli" and "E. coli" look like common names, handled at Tier 3.
        # But "saccharomyces cerevisiae" (lowercased, same tokens) stays
        # species-level.
        cands = self.resolver.resolve(
            "saccharomyces cerevisiae", EntityKind.ORGANISM)
        self.assertTrue(cands)
        self.assertEqual(cands[0].entity.match_type, MatchType.EXACT_SPECIES)


class OrganismResolverGeneralizedTests(unittest.TestCase):
    def setUp(self):
        self.resolver = default_organism_resolver()

    def _assert_generalized(self, query: str, expected_chassis: str):
        cands = self.resolver.resolve(query, EntityKind.ORGANISM)
        self.assertTrue(cands, f"{query!r} did not resolve")
        cand = cands[0]
        self.assertEqual(cand.tier, ResolutionTier.APPROXIMATE)
        org = cand.entity
        self.assertIsInstance(org, Organism)
        self.assertEqual(org.match_type, MatchType.CHASSIS_GENERALIZED)
        self.assertEqual(org.canonical_id, expected_chassis)

    def test_chassis_keys(self):
        for key in ("ecoli", "scerevisiae", "cglutamicum", "bsubtilis", "pputida"):
            self._assert_generalized(key, key)

    def test_kegg_org_codes(self):
        self._assert_generalized("eco", "ecoli")
        self._assert_generalized("sce", "scerevisiae")
        self._assert_generalized("cgl", "cglutamicum")
        self._assert_generalized("bsu", "bsubtilis")
        self._assert_generalized("ppu", "pputida")

    def test_common_names(self):
        self._assert_generalized("E. coli", "ecoli")
        self._assert_generalized("e. coli", "ecoli")
        self._assert_generalized("e.coli", "ecoli")
        self._assert_generalized("yeast", "scerevisiae")
        self._assert_generalized("baker's yeast", "scerevisiae")
        self._assert_generalized("S. cerevisiae", "scerevisiae")

    def test_confidence_midrange_for_generalized(self):
        cands = self.resolver.resolve("eco", EntityKind.ORGANISM)
        self.assertAlmostEqual(cands[0].confidence, 0.70)


class OrganismResolverMissTests(unittest.TestCase):
    def setUp(self):
        self.resolver = default_organism_resolver()

    def test_unknown_returns_empty(self):
        self.assertEqual(self.resolver.resolve("Mus musculus"), [])
        self.assertEqual(self.resolver.resolve("nonexistent organism 12345"), [])
        self.assertEqual(self.resolver.resolve(""), [])
        self.assertEqual(self.resolver.resolve("   "), [])

    def test_wrong_kind_returns_empty(self):
        # Protocol contract: resolve(kind != ORGANISM) must short-circuit.
        self.assertEqual(
            self.resolver.resolve("MG1655", EntityKind.MOLECULE), [])
        self.assertEqual(
            self.resolver.resolve("MG1655", EntityKind.ENZYME), [])

    def test_resolve_canonical_returns_none_on_miss(self):
        self.assertIsNone(self.resolver.resolve_canonical("Mus musculus"))
        self.assertIsNone(self.resolver.resolve_canonical(""))


class OrganismResolverCompatTests(unittest.TestCase):
    def setUp(self):
        self.resolver = default_organism_resolver()

    def test_to_chassis_key(self):
        self.assertEqual(self.resolver.to_chassis_key("MG1655"), "ecoli")
        self.assertEqual(self.resolver.to_chassis_key("Escherichia coli"), "ecoli")
        self.assertEqual(self.resolver.to_chassis_key("eco"), "ecoli")
        self.assertEqual(self.resolver.to_chassis_key("ecoli"), "ecoli")
        self.assertEqual(self.resolver.to_chassis_key("yeast"), "scerevisiae")
        self.assertIsNone(self.resolver.to_chassis_key("Mus musculus"))

    def test_to_kegg_org(self):
        self.assertEqual(self.resolver.to_kegg_org("MG1655"), "eco")
        self.assertEqual(self.resolver.to_kegg_org("Escherichia coli"), "eco")
        self.assertEqual(self.resolver.to_kegg_org("yeast"), "sce")
        self.assertEqual(self.resolver.to_kegg_org("KT2440"), "ppu")
        self.assertIsNone(self.resolver.to_kegg_org("Mus musculus"))

    def test_as_chassis_dict_matches_legacy(self):
        # Every supported chassis must round-trip through Organism into the
        # exact legacy dict shape in CHASSIS_ORGANISMS.
        for key in CHASSIS_ORGANISMS:
            org = self.resolver.resolve_canonical(key)
            self.assertIsNotNone(org, f"{key!r} resolver miss")
            legacy = CHASSIS_ORGANISMS[key]
            produced = org.as_chassis_dict()
            self.assertEqual(produced["name"], legacy["name"])
            self.assertEqual(produced["kegg_org"], legacy["kegg_org"])
            self.assertEqual(produced["native_pathways"],
                             list(legacy["native_pathways"]))
            self.assertEqual(produced["genetic_tools"], legacy["genetic_tools"])
            self.assertEqual(produced["growth_rate"], legacy["growth_rate"])


class OrganismResolverOrganismShapeTests(unittest.TestCase):
    def setUp(self):
        self.resolver = default_organism_resolver()

    def test_organism_has_expected_fields(self):
        org = self.resolver.resolve_canonical("MG1655")
        self.assertIsNotNone(org)
        self.assertEqual(org.canonical_id, "ecoli")
        self.assertEqual(org.scientific_name, "Escherichia coli K-12 MG1655")
        self.assertEqual(org.species, "Escherichia coli")
        self.assertEqual(org.strain, "K-12 MG1655")
        self.assertEqual(org.kegg_org, "eco")
        self.assertEqual(org.taxonomy_id, "511145")
        self.assertIn("MEP", org.native_pathways)
        self.assertEqual(org.source, "chassis_db")
        self.assertIn(("kegg", "eco"), org.cross_refs)
        self.assertIn(("ncbi_taxonomy", "511145"), org.cross_refs)
        # Aliases include chassis key and human forms.
        self.assertIn("MG1655", org.aliases)
        self.assertIn("E. coli", org.aliases)

    def test_cross_refs_dict_helper(self):
        org = self.resolver.resolve_canonical("yeast")
        self.assertEqual(org.cross_refs_dict(),
                         {"kegg": "sce", "ncbi_taxonomy": "559292"})


class OrganismResolverTaxonomyHookTests(unittest.TestCase):
    def test_taxonomy_lookup_fires_only_on_miss(self):
        calls: list[str] = []

        def fake_lookup(q: str):
            calls.append(q)
            return Organism(
                canonical_id=f"tax:{q}",
                source="ncbi_taxonomy",
                scientific_name="Mus musculus",
                species="Mus musculus",
                match_type=MatchType.INFERRED,
            )

        resolver = OrganismResolver(taxonomy_lookup=fake_lookup)

        # Hit a known chassis — hook must NOT fire.
        resolver.resolve("MG1655")
        self.assertEqual(calls, [])

        # Miss — hook fires.
        cands = resolver.resolve("Mus musculus")
        self.assertEqual(calls, ["mus musculus"])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].entity.source, "ncbi_taxonomy")
        self.assertEqual(cands[0].tier, ResolutionTier.INFERRED)
        self.assertEqual(cands[0].provenance, "organism_resolver:taxonomy")

    def test_taxonomy_lookup_exception_is_swallowed(self):
        def bad_lookup(q: str):
            raise RuntimeError("network down")

        resolver = OrganismResolver(taxonomy_lookup=bad_lookup)
        # Must return [] rather than propagate — resolvers never raise on
        # "normal empty result".
        self.assertEqual(resolver.resolve("Mus musculus"), [])


class OrganismResolverInjectionTests(unittest.TestCase):
    def test_custom_chassis_map(self):
        custom = {
            "synth_a": {
                "name": "Synthetic organism A",
                "native_pathways": ["custom"],
                "genetic_tools": "n/a",
                "growth_rate": "unknown",
                "kegg_org": "syna",
            },
        }
        custom_aliases = {
            "synth_a": {
                "species": "Synthetica alpha",
                "strain": "SA-1",
                "common_names": ("synth-A",),
                "strain_aliases": ("SA-1",),
                "taxonomy_id": "999999",
            },
        }
        resolver = OrganismResolver(
            chassis_map=custom, chassis_aliases=custom_aliases)

        self.assertEqual(resolver.to_chassis_key("SA-1"), "synth_a")
        self.assertEqual(resolver.to_chassis_key("synth-A"), "synth_a")
        self.assertEqual(resolver.to_kegg_org("Synthetica alpha"), "syna")
        # No E. coli in a custom map.
        self.assertIsNone(resolver.to_chassis_key("MG1655"))


if __name__ == "__main__":
    unittest.main()
