# RAG Design For Any Molecule, Any Bacterial Strain, And Chemistry + Biosynthesis Rules

Date: 2026-04-20

## Goal

Design a retrieval-augmented generation system that can support:
- any molecule
- any bacterial strain
- biosynthesis reasoning
- chemistry synthesis reasoning
- enzyme and pathway discovery
- literature-grounded answers
- experiment design support

This document answers:
- what data the RAG needs
- how to structure it
- how to retrieve across biology and chemistry
- how to support open-ended targets instead of a narrow curated set

---

## 1. Core Problem

If the system must answer for:
- any target molecule
- any host strain
- any synthesis route

then flat semantic search alone is not enough.

A proper system needs to combine:

1. Entity retrieval
Find the exact molecule, strain, enzyme, reaction, paper, or pathway.

2. Relationship retrieval
Find how they connect:
- molecule -> reaction
- reaction -> enzyme
- enzyme -> organism
- organism -> pathway

3. Rule retrieval
Find domain rules:
- biosynthesis heuristics
- strain engineering rules
- chemistry reaction logic
- cloning / expression design rules

4. Evidence retrieval
Find literature and database records supporting the answer.

That means the RAG should not be one index.

It should be a layered scientific retrieval system.

---

## 2. Design Principle

The right design is:

## Hybrid scientific RAG

Made of:
- structured entity store
- graph-like relationship store
- vector search
- rule library
- literature evidence layer

The LLM should use all of them together.

---

## 3. What “Any Molecule” Really Requires

Supporting any molecule means the system must handle:
- known natural products
- small molecules
- metabolites
- intermediates
- drug-like compounds
- analogs
- compounds outside KEGG

That means one source is not enough.

### Minimum molecule coverage needs

- KEGG compounds
- PubChem
- ChEBI
- HMDB
- ChEMBL
- ZINC or purchasability sources
- synonym normalization layer

### Molecule resolution must support

- common names
- synonyms
- IUPAC names
- KEGG IDs
- PubChem CID
- ChEBI IDs
- formula
- SMILES
- InChI

This is the first hard requirement.

If molecule resolution is weak, everything downstream breaks.

---

## 4. What “Any Bacterial Strain” Really Requires

Supporting any bacterial strain means:
- not just a few chassis organisms
- not just species-level names
- but strain-level reasoning where possible

The system should handle:
- species
- strain names
- common lab aliases
- taxonomic lineage
- genome/protein mapping where available
- known engineering traits

### Minimum strain-related sources

- NCBI taxonomy
- NCBI genome / gene / protein
- UniProt organism-linked proteins
- KEGG organism codes
- BioCyc / MetaCyc where available
- curated chassis metadata

### Strain-level metadata should include

- strain name
- species
- taxonomy
- gram status
- aerobic / anaerobic behavior
- genetic tools quality
- transformation feasibility
- secretion behavior
- native precursor pathways
- known tolerance traits
- known literature precedent

This is necessary to answer:
- Is this host suitable?
- Does it naturally support this precursor?
- Is it easy to engineer?
- Is there precedent?

---

## 5. What “Chemistry Synthesis Rules” Require

This is where most biology-focused systems fail.

If the product must also reason about chemistry synthesis, then the RAG needs:

### Chemistry data
- compound properties
- known synthetic routes
- precursors
- reagent classes
- transformation families
- protecting-group / step-count knowledge if supported
- purchasability
- industrial route evidence

### Chemistry rule library

Not just papers.

The system needs retrievable rules like:
- terpene / polyketide / alkaloid route patterns
- oxidation / reduction transformation logic
- common functional-group interconversions
- biosynthesis vs chemical synthesis tradeoff rules
- feedstock and waste heuristics
- route complexity heuristics

These should be stored as structured rules, not only as raw text.

---

## 6. Correct RAG Architecture

## Final architecture

The system should have 5 retrieval layers.

### Layer 1: Entity Resolution Layer

Purpose:
- resolve user terms into exact scientific objects

Examples:
- “lycopene” -> KEGG compound + PubChem CID + synonyms
- “MG1655” -> E. coli K-12 MG1655 strain entity
- “phytoene desaturase” -> enzyme family / EC mapping

Best storage:
- relational DB

### Layer 2: Relationship / Graph Layer

Purpose:
- traverse biological and chemical relationships

Examples:
- which reactions produce this molecule
- which enzymes catalyze these reactions
- which organisms carry these enzymes
- which pathways use these compounds

Best storage:
- graph DB or graph-like relational schema

### Layer 3: Vector Evidence Layer

Purpose:
- semantic retrieval over papers, pathway text, enzyme descriptions, and notes

Best storage:
- vector DB

### Layer 4: Rule Retrieval Layer

Purpose:
- retrieve scientific heuristics and design rules

Examples:
- host selection rules
- enzyme prioritization rules
- cofactor balancing rules
- route comparison rules
- chemistry synthesis heuristics

Best storage:
- structured rule table plus vectorized rule documents

### Layer 5: Session / Project Memory Layer

Purpose:
- remember what the current project already decided

Examples:
- chosen host
- rejected enzyme
- saved target
- prior experiment failures

Best storage:
- relational project store plus summarized vector memory

---

## 7. Data Collections Needed

The RAG should be organized by scientific object type, not just by source.

## Recommended collections

### A. Molecules
- names
- synonyms
- IDs
- formula
- SMILES
- InChI
- class
- physicochemical properties

### B. Reactions
- reaction equation
- substrates
- products
- reaction family
- reversibility
- linked enzymes

### C. Enzymes
- EC
- names
- orthologs
- sequence links
- organisms
- cofactors
- kinetic evidence

### D. Organisms / Strains
- strain metadata
- chassis traits
- native pathway hints
- engineering precedent

### E. Pathways
- ordered steps
- compounds
- enzymes
- source organisms

### F. Literature
- PubMed abstracts
- full-text snippets if licensed
- review papers
- patents if included

### G. Rules
- biosynthesis design rules
- chemistry transformation rules
- host engineering heuristics
- cloning rules
- experiment troubleshooting rules

### H. Internal project memory
- decisions
- designs
- failures
- saved evidence

---

## 8. Data Model

The best way to support “any molecule” and “any strain” is to normalize everything into scientific entities.

## Main entities

- Molecule
- Reaction
- Enzyme
- Protein
- Gene
- Organism
- Strain
- Pathway
- Paper
- Rule
- Experiment
- Construct

## Main relationships

- Molecule participates_in Reaction
- Reaction catalyzed_by Enzyme
- Enzyme encoded_by Gene
- Gene present_in Organism
- Organism contains Pathway
- Pathway produces Molecule
- Paper supports Claim
- Rule applies_to Entity

This structure is what makes open-ended scientific RAG possible.

---

## 9. Retrieval Flow

For a user query like:

`How can I produce artemisinic acid in a bacterial strain and how does that compare to chemical synthesis?`

The system should retrieve in this order:

### Step 1: Resolve entities
- artemisinic acid
- likely host strains
- route type = biological + chemical comparison

### Step 2: Pull graph neighbors
- reactions connected to target
- enzymes linked to route
- organisms with route evidence

### Step 3: Pull literature evidence
- microbial production papers
- chemical synthesis papers
- review articles

### Step 4: Pull rules
- host selection rules
- terpenoid biosynthesis heuristics
- P450 expression challenges
- route comparison framework

### Step 5: Synthesize
- final answer with facts, inferences, and uncertainty separated

This is the correct pattern.

---

## 10. Retrieval Modes

The RAG should support multiple retrieval modes.

### 1. Exact lookup
For:
- IDs
- exact ECs
- exact strain names
- exact compounds

### 2. Semantic retrieval
For:
- “enzyme that converts X to Y”
- “papers about heterologous production”
- “routes similar to this target”

### 3. Graph traversal
For:
- pathway expansion
- precursor search
- host-native overlap

### 4. Rule retrieval
For:
- what should I do next
- what are known bottlenecks
- what host is usually better

### 5. Temporal retrieval
For:
- recent papers
- latest methods
- new strain reports

Each query should choose the right combination.

---

## 11. How To Support Any Molecule

To support “any molecule,” the RAG must not assume the molecule already exists in KEGG.

## Recommended molecule strategy

### Tier 1: exact known compound
If found in:
- KEGG
- PubChem
- ChEBI
- ChEMBL

resolve to canonical entity.

### Tier 2: approximate known analog
If the exact target is not found:
- search by synonym variants
- search by formula
- search by embedding similarity
- search by nearest analogs

### Tier 3: inferred target class
If still not found:
- classify by chemistry / biosynthesis family
- retrieve routes and rules for analog class

This lets the system still reason usefully.

---

## 12. How To Support Any Bacterial Strain

To support “any bacterial strain,” use three levels.

### Tier 1: exact strain support
- explicit strain record
- linked genes / proteins / literature

### Tier 2: species-level fallback
If exact strain data is weak:
- use species-level knowledge
- flag that the answer is generalized from species data

### Tier 3: chassis similarity fallback
If species data is weak:
- map to similar chassis with known traits
- mark confidence lower

This is important because strain-level data will often be incomplete.

---

## 13. Rule Library Design

This is critical.

The system should have a dedicated rule corpus that is separate from papers.

## Rule categories

### A. Host selection rules
- if terpenoid target and MVA flux is key, yeast may be preferred
- if rapid iteration and simple cloning are needed, E. coli may be preferred

### B. Enzyme selection rules
- prioritize enzymes with literature precedent in target host
- penalize membrane proteins or complex cofactors when host support is weak

### C. Pathway design rules
- minimize heterologous step count
- prefer routes with native precursor availability
- check cofactor consistency

### D. Chemistry comparison rules
- compare biological and chemical route on feedstock, waste, step count, selectivity, scale, and purification burden

### E. Troubleshooting rules
- precursor accumulation suggests downstream bottleneck
- product absence with gene expression can suggest folding/cofactor/transport issues

Rules should have:
- text
- category
- scope
- confidence
- source basis

---

## 14. Chunking Strategy

Bad chunking breaks scientific retrieval.

## Recommended chunking

### Molecules
- one canonical document per molecule

### Reactions
- one canonical document per reaction

### Enzymes
- one canonical document per EC or enzyme record

### Pathways
- one pathway overview document
- plus step-level subdocuments

### Papers
- abstract chunk
- methods/result chunks if full text available
- keep citations and metadata attached

### Rules
- one rule per chunk
- small, explicit, and retrievable

The rule is:
- chunk by scientific meaning, not by arbitrary token count

---

## 15. Metadata Strategy

Metadata is as important as embeddings.

## Molecule metadata
- ids
- synonyms
- class
- formula
- smiles
- source database

## Reaction metadata
- substrates
- products
- ECs
- pathway IDs

## Enzyme metadata
- EC
- organism codes
- cofactors
- localization

## Organism metadata
- species
- strain
- taxonomy
- gram status
- chassis score

## Literature metadata
- PMID
- year
- journal
- entity mentions
- topic tags

## Rule metadata
- category
- applies_to
- evidence type
- confidence

This makes filter-aware retrieval possible.

---

## 16. Retrieval Ranking

The final retriever should not rank only by semantic similarity.

Use a composite score:

- semantic similarity
- entity overlap
- graph proximity
- metadata match
- evidence quality
- recency when requested
- source trust

### Example

For enzyme ranking:
- exact EC match should outrank vague semantic relevance

For latest papers:
- recency must matter more than old citation count

For route comparison:
- rule matches + pathway relevance should matter, not just language similarity

---

## 17. Support For Chemistry + Biology Together

This is the most important design choice.

The chemistry and biology retrieval systems should not be separate silos.

They should be connected through shared molecule entities.

## Shared anchor

Molecule is the bridge between:
- chemical synthesis
- biosynthesis
- properties
- purchasability
- analogs
- pathway targets

When the user asks about a target molecule, the system should retrieve both:
- chemistry-side evidence
- biology-side evidence

Then compare them in one answer.

This is the right design.

---

## 18. Recommended Storage Architecture

## Use all three

### Relational DB
For:
- canonical entities
- metadata
- project memory
- exact filtering

### Vector DB
For:
- semantic retrieval
- papers
- descriptive scientific text
- rule documents

### Graph layer
For:
- traversal
- route planning
- entity connections

If a graph DB is too heavy, emulate it with relational join tables at first.

---

## 19. Query Planning Layer

The LLM should not directly hit vector search only.

There should be a query planner that decides:
- exact lookup?
- graph traversal?
- semantic search?
- rule lookup?
- latest literature search?

### Example planner outputs

#### Query type: target design
- resolve molecule
- retrieve pathways
- retrieve host candidates
- retrieve enzyme evidence
- retrieve design rules

#### Query type: compare chemical vs biological route
- resolve molecule
- retrieve chemical route evidence
- retrieve biosynthesis route evidence
- retrieve route comparison rules

#### Query type: troubleshoot
- resolve pathway step
- retrieve bottleneck rules
- retrieve enzyme-specific papers

This planning layer is what makes the RAG feel expert.

---

## 20. Quality Controls

To keep the RAG reliable:

### Must-have checks
- entity verification
- citation verification
- stale-source marking
- conflict detection
- source attribution

### Output labels
- `database fact`
- `literature-supported`
- `rule-based inference`
- `hypothesis`

This prevents the model from blending evidence and speculation.

---

## 21. MVP RAG For This Repo

If implementing this incrementally in this repo, I would build in this order:

### Phase 1
- strong molecule entity resolution
- strong organism / chassis resolution
- KEGG + PubMed + UniProt + PubChem hybrid retrieval
- structured pathway and enzyme retrieval

### Phase 2
- rule library
- host scoring
- strain support layer
- chemistry comparison retrieval

### Phase 3
- graph-backed route traversal
- analog / nearest-target reasoning
- project memory
- internal lab documents

### Phase 4
- strain-specific genome/protein support
- patents
- full route comparison engine
- experimental result memory

---

## 22. What The Final RAG Should Feel Like

When complete, this RAG should make the system feel like:

- it knows the exact molecule
- it understands the biology around it
- it understands the chemistry around it
- it knows which strains matter
- it can connect papers, pathways, enzymes, and design rules
- it can still reason when the exact target is missing by using analogs and rules

That is how you support:
- any molecule
- any bacterial strain
- and chemistry plus biosynthesis in one scientific system

---

## 23. Final Recommendation

Do not design this RAG as:
- one vector store of papers

Design it as:
- entity store
- graph relationships
- vector evidence
- rule retrieval
- project memory

with molecule and strain resolution as the foundation.

That is the correct RAG architecture for a scientific expert system that must support open-ended biology and chemistry questions.
