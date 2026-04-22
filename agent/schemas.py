"""
MetaboAgent — Data Schemas
Pydantic models for all structured data flowing through the system.
"""
from pydantic import BaseModel, Field
from typing import Optional


# ── KEGG Data Models ──

class KEGGReaction(BaseModel):
    """A single KEGG reaction entry."""
    reaction_id: str = Field(description="KEGG reaction ID, e.g. R00024")
    name: str = Field(default="", description="Reaction name")
    definition: str = Field(default="", description="Reaction equation in text form")
    equation: str = Field(default="", description="Balanced equation with compound IDs")
    ec_numbers: list[str] = Field(default_factory=list, description="Associated EC numbers")
    pathway_ids: list[str] = Field(default_factory=list, description="Linked KEGG pathway IDs")
    substrate_ids: list[str] = Field(default_factory=list, description="Substrate compound IDs")
    product_ids: list[str] = Field(default_factory=list, description="Product compound IDs")
    organisms: list[str] = Field(default_factory=list, description="Organisms with this reaction")
    comment: str = Field(default="", description="Additional notes")


class KEGGCompound(BaseModel):
    """A single KEGG compound entry."""
    compound_id: str = Field(description="KEGG compound ID, e.g. C05432")
    name: str = Field(default="", description="Primary name")
    names: list[str] = Field(default_factory=list, description="All synonyms")
    formula: str = Field(default="", description="Molecular formula")
    mol_weight: Optional[float] = Field(default=None, description="Molecular weight")
    reaction_ids: list[str] = Field(default_factory=list, description="Reactions involving this compound")
    pathway_ids: list[str] = Field(default_factory=list, description="Pathways containing this compound")


class KEGGEnzyme(BaseModel):
    """A single KEGG enzyme entry."""
    ec_number: str = Field(description="EC number, e.g. 1.3.99.31")
    name: str = Field(default="", description="Enzyme name")
    names: list[str] = Field(default_factory=list, description="All names/synonyms")
    reaction_ids: list[str] = Field(default_factory=list, description="Catalyzed reactions")
    substrate: list[str] = Field(default_factory=list, description="Known substrates")
    product: list[str] = Field(default_factory=list, description="Known products")
    organisms: list[str] = Field(default_factory=list, description="Organisms with this enzyme")
    genes: list[str] = Field(default_factory=list, description="Gene names")


class KEGGPathway(BaseModel):
    """A single KEGG reference pathway."""
    pathway_id: str = Field(description="Pathway ID, e.g. map00900")
    name: str = Field(default="", description="Pathway name")
    description: str = Field(default="", description="Pathway description")
    reaction_ids: list[str] = Field(default_factory=list, description="Reactions in this pathway")
    compound_ids: list[str] = Field(default_factory=list, description="Compounds in this pathway")


# ── Literature Models ──

class PubMedAbstract(BaseModel):
    """A PubMed abstract document."""
    pmid: str = Field(description="PubMed ID")
    title: str = Field(default="")
    abstract: str = Field(default="")
    authors: list[str] = Field(default_factory=list)
    journal: str = Field(default="")
    year: Optional[int] = Field(default=None)
    mesh_terms: list[str] = Field(default_factory=list)
    doi: str = Field(default="")


# ── Vector Store Document ──

class VectorDocument(BaseModel):
    """A document ready for embedding and indexing into ChromaDB."""
    doc_id: str = Field(description="Unique document ID")
    text: str = Field(description="Text content to embed")
    metadata: dict = Field(default_factory=dict, description="Filterable metadata fields")
    collection: str = Field(description="Target ChromaDB collection name")


# ── Agent Tool I/O Models ──

class RetrievalResult(BaseModel):
    """A single result from hybrid retrieval."""
    doc_id: str
    text: str
    metadata: dict = Field(default_factory=dict)
    score: float = Field(description="Combined retrieval score")
    source: str = Field(description="Collection source: kegg_reactions|kegg_compounds|literature")


class PathwayStep(BaseModel):
    """A single step in a metabolic pathway."""
    step_number: int
    reaction_id: str = Field(description="KEGG reaction ID")
    ec_number: str = Field(default="", description="EC number for this step")
    enzyme_name: str = Field(default="", description="Recommended enzyme")
    source_organism: str = Field(default="", description="Organism to source enzyme from")
    substrate: str = Field(description="Input compound(s)")
    product: str = Field(description="Output compound(s)")
    is_native: bool = Field(default=False, description="Whether host already has this reaction")
    action: str = Field(default="heterologous_expression",
                        description="heterologous_expression|overexpression|native|knockout")
    evidence: list[str] = Field(default_factory=list, description="PMIDs or KEGG IDs supporting this")


class EnzymeCandidate(BaseModel):
    """A ranked enzyme candidate for a specific reaction step."""
    ec_number: str
    enzyme_name: str
    source_organism: str
    gene_name: str = Field(default="")
    kcat: Optional[float] = Field(default=None, description="Turnover number (1/s)")
    km: Optional[float] = Field(default=None, description="Michaelis constant (mM)")
    catalytic_efficiency: Optional[float] = Field(default=None, description="kcat/Km")
    host_compatibility_score: float = Field(default=0.5, description="0-1 score for expression in host")
    literature_evidence: list[str] = Field(default_factory=list, description="PMIDs")
    overall_score: float = Field(default=0.0, description="Composite ranking score")


class HostScore(BaseModel):
    """Scoring of a chassis organism for a given target pathway."""
    organism_id: str
    organism_name: str
    native_pathway_overlap: float = Field(description="Fraction of pathway steps already native")
    precursor_availability: float = Field(description="Score for precursor supply")
    genetic_tools_score: float = Field(description="0-1 score for genetic accessibility")
    literature_precedent: float = Field(description="Score based on similar engineering literature")
    overall_score: float = Field(description="Weighted composite score")
    rationale: str = Field(default="", description="LLM-generated explanation")


# ── Final Output: Strain Blueprint ──

class StrainModifications(BaseModel):
    """Genetic modifications for the engineered strain."""
    express: list[str] = Field(default_factory=list, description="Genes to heterologously express")
    overexpress: list[str] = Field(default_factory=list, description="Native genes to overexpress")
    knockout: list[str] = Field(default_factory=list, description="Genes to delete")
    optimize: list[str] = Field(default_factory=list, description="Optimization notes (codon, promoter, etc.)")


class Citation(BaseModel):
    """A literature or database citation."""
    source_id: str = Field(description="PMID, KEGG ID, or other identifier")
    source_type: str = Field(description="pubmed|kegg|brenda")
    title: str = Field(default="")
    relevance: str = Field(default="", description="Why this citation matters")
    url: str = Field(default="")


class StrainBlueprint(BaseModel):
    """Complete strain design output — the final deliverable."""
    target_molecule: dict = Field(description="name, kegg_id, class")
    host_organism: dict = Field(description="name, rationale")
    pathway: list[PathwayStep] = Field(description="Ordered metabolic pathway")
    modifications: StrainModifications
    citations: list[Citation] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, description="Agent's confidence in this design")
    reasoning_trace: str = Field(default="", description="Full chain-of-thought reasoning")
