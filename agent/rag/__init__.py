"""
TRANSITION SHIM — DELETE IN PHASE 5.

Do not import from here in new code. This package exists only so the
Day-1 callers that still do ``from agent.rag import ...`` or
``from agent.rag.<submodule> import ...`` keep working while the
package is split across its real homes:

    agent.rag.interfaces        -> agent.entities
    agent.rag.adapters          -> vectorstore.adapters
    agent.rag.hybrid            -> vectorstore.hybrid
    agent.rag.molecule_resolver -> agent.resolvers.molecule
    agent.rag.organism_resolver -> agent.resolvers.organism
    agent.rag.rules             -> agent.rules
    agent.rag.citation_verifier -> agent.verify.citations

New code should import directly from those target modules. Phase 5
removes this shim entirely — any remaining imports from ``agent.rag``
at that point will become hard errors.
"""
from __future__ import annotations

import sys

from agent import entities as _entities
from agent import rules as _rules
from agent.resolvers import molecule as _molecule_resolver
from agent.resolvers import organism as _organism_resolver
from agent.verify import citations as _citation_verifier
from vectorstore import adapters as _adapters
from vectorstore import hybrid as _hybrid

# Make ``from agent.rag.<submodule> import X`` resolve to the new locations.
sys.modules[__name__ + ".interfaces"] = _entities
sys.modules[__name__ + ".adapters"] = _adapters
sys.modules[__name__ + ".hybrid"] = _hybrid
sys.modules[__name__ + ".molecule_resolver"] = _molecule_resolver
sys.modules[__name__ + ".organism_resolver"] = _organism_resolver
sys.modules[__name__ + ".rules"] = _rules
sys.modules[__name__ + ".citation_verifier"] = _citation_verifier

# Top-level re-exports for ``from agent.rag import X`` callers. Mirrors the
# public surface of the pre-split archive/agent_rag/__init__.py.
from agent.entities import (
    EntityCandidate,
    EntityKind,
    EntityResolver,
    Enzyme,
    Evidence,
    MatchType,
    Molecule,
    Organism,
    Paper,
    Reaction,
    ResolutionTier,
    StructuredRetriever,
)
from vectorstore.hybrid import HybridRetriever, default_hybrid_retriever
from agent.resolvers.molecule import (
    ChEBIResolver,
    InputForm,
    MoleculeResolver,
    classify_input,
)
from agent.resolvers.organism import (
    OrganismResolver,
    default_organism_resolver,
)
from agent.rules import (
    EvidenceBasis,
    Rule,
    RuleCategory,
    RuleRepository,
    RuleScope,
    default_rule_repository,
)
from agent.verify.citations import (
    Citation,
    CitationReport,
    CitationStatus,
    CitationType,
    CitationVerifier,
    build_report,
    default_chroma_verifier,
    extract_citations,
)

__all__ = [
    "ChEBIResolver",
    "Citation",
    "CitationReport",
    "CitationStatus",
    "CitationType",
    "CitationVerifier",
    "EntityCandidate",
    "EntityKind",
    "EntityResolver",
    "Enzyme",
    "Evidence",
    "EvidenceBasis",
    "HybridRetriever",
    "InputForm",
    "MatchType",
    "Molecule",
    "MoleculeResolver",
    "Organism",
    "OrganismResolver",
    "Paper",
    "Reaction",
    "ResolutionTier",
    "Rule",
    "RuleCategory",
    "RuleRepository",
    "RuleScope",
    "StructuredRetriever",
    "build_report",
    "classify_input",
    "default_chroma_verifier",
    "default_hybrid_retriever",
    "default_organism_resolver",
    "default_rule_repository",
    "extract_citations",
]
