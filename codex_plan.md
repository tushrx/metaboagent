# Codex Plan: Unified AI Biochemistry, Microbiology, and Chemistry Expert

## Title

Design plan for a single AI system that gives a biochemist one clean interface for:
- microbiology
- metabolic engineering
- enzymology
- pathway design
- medicinal / synthetic chemistry
- literature-grounded scientific reasoning
- experiment planning

Review date: 2026-04-20

---

## 1. Product Vision

If I were a biochemist and wanted one AI expert instead of switching between PubMed, KEGG, UniProt, retrosynthesis tools, wet-lab notes, and chemistry references, I would design a system with one goal:

Give scientifically grounded, cross-domain answers that connect:
- molecule -> pathway -> enzyme -> host -> construct -> experiment -> scale-up risk

The product should not feel like a generic chatbot. It should feel like:
- a senior metabolic engineer,
- a microbiologist,
- a chemist,
- and a scientific research assistant,

working together inside one interface.

Core principle:

The system must combine deep retrieval, structured scientific tools, and expert workflow-specific UX, instead of relying on a general LLM alone.

---

## 2. What “Expert-Level” Means

To actually feel expert-level, the system must do more than answer questions in prose.

It should be able to:
- explain pathways and mechanism-level reasoning
- compare biological and chemical synthesis routes
- identify enzymes and likely orthologs
- select chassis organisms
- reason about cofactors, toxicity, flux bottlenecks, transport, and regulation
- propose plasmids, constructs, primers, and validation steps
- summarize literature with citations
- surface uncertainty honestly
- separate facts from hypotheses

This means the product needs three layers:

1. Knowledge layer
Scientific databases, literature, curated references, internal documents.

2. Reasoning layer
Specialized tools and planners for biology, chemistry, and experiment design.

3. Product layer
A clean interface that makes complex scientific work understandable and actionable.

---

## 3. Product Positioning

### The system should serve three main user modes

#### A. Ask Mode
For questions like:
- What enzymes convert GGPP to lycopene?
- What is the best host for taxadiene?
- Compare microbial vs chemical synthesis of vanillin.

#### B. Design Mode
For tasks like:
- Design a microbial strain for a target compound.
- Propose an expression strategy for a pathway.
- Build a plasmid and primer plan.

#### C. Investigate Mode
For tasks like:
- Why did my pathway fail?
- What are likely bottlenecks?
- Which enzyme candidates are most literature-supported?
- What papers published in the last 2 years matter here?

These modes should share one interface but produce different outputs.

---

## 4. Ideal User Experience

## One clean screen

The UI should be intentionally simple:
- central chat / workspace
- left rail for project context
- right evidence panel
- structured result cards below the answer

Not a dashboard full of unrelated widgets.

### The user experience should feel like this:

The user asks:
`Design a route to produce artemisinic acid in yeast.`

The system responds with:
- a concise expert summary
- pathway map
- enzyme recommendations
- host rationale
- plasmid / construct suggestions
- cited papers
- confidence and open risks

Then the user can click:
- `Compare alternative hosts`
- `Show recent papers`
- `Generate plasmid design`
- `Suggest validation experiments`
- `Estimate bottlenecks`

This is better than making the user rewrite prompts.

---

## 5. Clean UI Design

## Design direction

The UI should look like a scientific instrument, not a consumer chat app.

Visual goals:
- calm
- precise
- structured
- information-dense without being cluttered
- readable on long scientific sessions

### Recommended UI structure

#### Top bar
- project name
- active workspace
- model / evidence state
- sync / indexing status

#### Left sidebar
- Projects
- Molecules
- Organisms
- Saved literature collections
- Saved designs
- Experiment notebooks

#### Main center panel
- primary chat / task input
- response stream
- expandable structured sections

#### Right evidence panel
- citations
- source quality
- database hits
- latest papers
- confidence / uncertainty

#### Bottom action strip
- Design pathway
- Compare routes
- Rank enzymes
- Build plasmid
- Design primers
- Generate experiment plan

### UI output blocks

Every major answer should render into clean scientific blocks:

1. Executive Summary
2. Evidence
3. Proposed Pathway
4. Enzyme Candidates
5. Host Recommendation
6. Construct / Cloning Plan
7. Experimental Plan
8. Risks and Unknowns

This is the right abstraction. Scientists do not want a wall of text.

---

## 6. UX Rules for Scientific Trust

To feel expert, the system must be trustworthy.

### Hard rules

- Never present speculation as fact.
- Always cite source type.
- Separate known data from inferred recommendation.
- Show confidence score per major claim.
- Mark when evidence is old, sparse, or conflicting.
- Let the user inspect the exact paper/database entry behind claims.

### Output labels

Use clear labels such as:
- `Confirmed from database`
- `Supported by literature`
- `Model inference`
- `Hypothesis / needs validation`

This matters more than fancy UI.

---

## 7. Core System Architecture

The system should be a multi-layer scientific copilot.

### Layer 1: Foundation model

Use a strong reasoning LLM for orchestration and synthesis.

Role:
- route the task
- plan tool usage
- synthesize final expert answer
- explain tradeoffs
- manage memory and context

But the LLM should not be the source of truth.

### Layer 2: Scientific tool agents

Create domain tools with clear ownership:

#### Biology tools
- KEGG lookup
- UniProt lookup
- BRENDA / SABIO kinetics
- NCBI gene / protein sequence retrieval
- chassis compatibility analysis
- codon optimization hooks
- plasmid design
- primer design

#### Chemistry tools
- PubChem lookup
- ChEBI / HMDB / MetaCyc integration
- reaction / synthesis route comparison
- retrosynthesis integration
- property estimation
- purchasability / supplier lookup

#### Literature tools
- PubMed search
- semantic literature retrieval
- citation clustering
- recent-paper monitor
- claim verification

#### Systems biology tools
- pathway planning
- bottleneck detection
- cofactor balancing
- toxicity / burden heuristics
- transporter and secretion checks

### Layer 3: Scientific memory + retrieval

Use a hybrid knowledge system:
- relational metadata store
- vector store
- graph-like biological relationships

Best design:

1. Vector DB for semantic retrieval
2. Relational DB for structured entities
3. Optional graph DB for:
   - compound -> reaction
   - reaction -> enzyme
   - enzyme -> organism
   - pathway -> host

This is much better than storing everything as flat text.

---

## 8. Knowledge Sources

To feel like a true biochemistry + microbiology + chemistry expert, the system should integrate:

### Essential biology / biochemistry sources
- KEGG
- UniProt
- PubMed
- NCBI Gene / Protein / Nuccore
- BRENDA
- SABIO-RK
- MetaCyc / BioCyc
- ChEBI
- GO annotations

### Essential chemistry sources
- PubChem
- ZINC
- ChEMBL
- vendor / catalog sources where relevant

### Optional high-value sources
- patents
- protocols
- internal lab notes
- SOPs
- previous successful constructs
- assay results

The product becomes much more valuable when it can combine public science with lab-private knowledge.

---

## 9. Data Model

The system should organize knowledge as scientific entities.

### Main entities
- Molecule
- Reaction
- Enzyme
- Gene
- Protein
- Organism
- Pathway
- Construct
- Experiment
- Paper
- Hypothesis

### Example relationship graph

- Molecule is produced by Reaction
- Reaction is catalyzed by Enzyme
- Enzyme is encoded by Gene
- Gene exists in Organism
- Organism supports Pathway
- Construct expresses Gene
- Experiment tests Hypothesis
- Paper supports Claim

This makes the product much more usable than plain chat history.

---

## 10. Agent Design

I would not design one giant general agent.

I would design one orchestrator with specialist workers.

### Recommended agent topology

#### 1. Orchestrator Agent
Decides:
- what the user is asking
- which domain tools to use
- what output structure is needed

#### 2. Pathway Planner
Handles:
- retrosynthesis
- precursor analysis
- host-native overlap
- step ordering

#### 3. Enzyme Expert
Handles:
- EC mapping
- ortholog selection
- organism candidates
- kinetic evidence
- expression feasibility

#### 4. Chemistry Expert
Handles:
- molecule properties
- chemical synthesis routes
- biosynthesis vs chemical route comparison
- analog / precursor reasoning

#### 5. Wet-Lab Design Expert
Handles:
- plasmid recommendations
- promoter / backbone / marker choice
- primer design
- cloning strategy
- assay suggestions

#### 6. Literature Analyst
Handles:
- search
- summarization
- claim verification
- novelty / recency analysis

The orchestrator should merge these outputs into one coherent answer.

---

## 11. Recommended User Workflows

### Workflow 1: Target-first design

User input:
`I want to make lycopene in E. coli.`

System flow:
1. Identify target molecule.
2. Find known biosynthetic routes.
3. Compare host-native capability.
4. Recommend pathway enzymes.
5. Suggest construct strategy.
6. Suggest validation assays.

### Workflow 2: Protein/enzyme investigation

User input:
`Which phytoene desaturase is best for yeast expression?`

System flow:
1. Resolve EC / enzyme family.
2. Retrieve orthologs and evidence.
3. Rank by literature + host compatibility.
4. Show top candidates and tradeoffs.

### Workflow 3: Failure analysis

User input:
`My engineered strain makes precursor but not product. Why?`

System flow:
1. Inspect missing conversion step.
2. Check enzyme compatibility.
3. Evaluate cofactor issues.
4. Evaluate toxicity / transport.
5. Suggest experiments to discriminate causes.

### Workflow 4: Route comparison

User input:
`Compare microbial and chemical synthesis of vanillin.`

System flow:
1. Gather biological route evidence.
2. Gather chemical route evidence.
3. Compare feedstocks, steps, cost drivers, waste, scale, risks.
4. Produce table + verdict.

---

## 12. Output Design

The final answer should always be dual-format:

### A. Short expert answer
2-5 paragraphs with the recommendation.

### B. Structured scientific output

For example:

- Target
- Best host
- Recommended pathway
- Recommended enzymes
- Key citations
- Main risks
- Next experiment

This allows:
- readability for humans
- machine-actionable downstream workflows

---

## 13. Clean Result Components

These are the components I would build into the UI first.

### 1. Molecule card
- name
- IDs
- formula
- class
- key properties

### 2. Pathway card
- ordered steps
- compounds
- reaction IDs
- enzyme IDs

### 3. Enzyme ranking card
- enzyme name
- source organism
- EC
- score
- evidence summary

### 4. Host suitability card
- host
- native overlap
- engineering ease
- likely bottlenecks

### 5. Experiment plan card
- build
- test
- measure
- troubleshoot

### 6. Evidence card
- PMIDs
- database entries
- latest papers
- confidence

---

## 14. What Makes It Feel “One Another” Instead of Separate Tools

Your phrase "design one another" is important.

The system should not feel like:
- one chemistry tab
- one microbiology tab
- one literature tab

It should feel like one connected scientific brain.

That means:

When the user asks about a molecule, the product should naturally connect:
- chemical identity
- biosynthetic routes
- enzyme mechanism
- host engineering
- cloning strategy
- literature support

The user should not have to tell the system which discipline to enter.

The orchestrator should infer the needed disciplines automatically.

That is the real product advantage.

---

## 15. Recommendations for the UI Tone

The tone should be:
- precise
- calm
- technical
- non-hyped

Avoid:
- generic assistant phrasing
- motivational fluff
- overly casual UI language

Prefer:
- `Recommended host`
- `Evidence quality`
- `Known bottlenecks`
- `Recent supporting papers`
- `Suggested validation experiments`

This reinforces expert trust.

---

## 16. Memory and Project Context

The product becomes much stronger if it remembers:
- current target molecule
- selected host
- chosen pathway branch
- prior constructs
- previous failed experiments
- preferred chassis

### Project memory should include
- target portfolio
- saved literature
- saved hypotheses
- construct versions
- assay results
- decisions made and why

This turns the system from chatbot into scientific workspace.

---

## 17. Safety and Scientific Guardrails

This system should be useful but controlled.

### Guardrails
- refuse unsafe pathogen enablement
- avoid protocol-level wet-lab instructions for risky organisms
- avoid fake confidence
- flag missing evidence
- distinguish educational guidance from validated procedure

### Scientific quality guardrails
- citation verification
- database ID verification
- contradiction checks between sources
- freshness checks for “latest” questions
- output schema validation

---

## 18. Technical Stack Recommendation

### Backend
- Python
- FastAPI for service layer
- Postgres for structured scientific entities
- Chroma / pgvector / similar for semantic retrieval
- Redis for cache and job state

### Agent layer
- orchestrator + specialist tools
- strong reasoning model for synthesis
- deterministic tool wrappers for data retrieval and transforms

### Frontend
- React / Next.js
- strong structured component system
- graph visualization for pathways
- SVG rendering for plasmids / construct maps

### Infra
- async job workers for ingestion
- scheduled refresh for literature and databases
- object storage for documents / reports
- observability: logs, traces, query telemetry, failure metrics

---

## 19. Recommended MVP

If building this from scratch, I would not try to do everything at once.

### MVP scope

#### Phase 1
- Ask Mode
- KEGG + PubMed + UniProt + PubChem
- pathway lookup
- enzyme ranking
- host recommendation
- citations
- clean scientific chat UI

#### Phase 2
- design mode
- plasmid design
- primer design
- experiment planning
- route comparison

#### Phase 3
- internal lab knowledge integration
- project memory
- collaborative workspaces
- automated literature monitoring
- advanced failure analysis

---

## 20. MVP Screen Design

### Home screen
- single input
- recent projects
- example prompts

### Project screen
- current target
- chat thread
- pathway panel
- evidence panel
- saved results

### Design result screen
- summary
- pathway diagram
- enzyme ranking
- host analysis
- construct plan
- risks
- export button

---

## 21. Example Premium Interaction

User:
`Design a microbial strategy to produce taxadiene and compare E. coli vs yeast.`

System:
- identifies taxadiene
- retrieves biosynthetic route
- compares MEP vs MVA host logic
- ranks enzymes for GGPP and taxadiene synthase
- cites key literature
- recommends host based on engineering goal
- proposes construct architecture
- lists top 3 risks
- suggests immediate validation experiments

This is the bar.

---

## 22. What I Would Build First If I Wanted “That Level of Expertise”

Order matters.

### First build
- reliable retrieval
- entity resolution
- structured pathway outputs
- citation verification

### Then build
- enzyme ranking
- host recommendation
- comparison workflows

### Then build
- plasmid / primer / experiment modules

### Then build
- advanced project memory and collaboration

The biggest mistake would be polishing UI before scientific grounding is reliable.

---

## 23. Design Principles

1. One interface, many expert systems behind it.
2. Structured science first, prose second.
3. Evidence visible by default.
4. Biology and chemistry must connect naturally.
5. Project memory is as important as chat.
6. Trust comes from verification, not tone.
7. Clean UI means low clutter, not low density.

---

## 24. Final Recommendation

If the goal is to build an AI that feels like a true biochemistry + microbiology + chemistry expert in one place, I would design it as:

- a clean scientific workspace,
- powered by one orchestration model,
- backed by specialized biology/chemistry tools,
- grounded in database + literature retrieval,
- with structured outputs for pathway, enzyme, host, construct, and experiment planning.

The winning product is not “ChatGPT for biology.”

The winning product is:

`an expert scientific design workspace that thinks across molecule, pathway, enzyme, host, and experiment in one continuous flow.`

---

## 25. Concrete Next Build Plan

If you want to implement this in this repository, I would do it in this order:

1. Redesign the UI around:
   - chat center
   - evidence side panel
   - structured result cards

2. Upgrade the agent output schema to always return:
   - summary
   - pathway
   - enzymes
   - host
   - evidence
   - risks
   - next experiments

3. Add a true domain router:
   - ask
   - design
   - investigate
   - compare

4. Strengthen expert tools:
   - better enzyme ranking
   - better route comparison
   - verified citation layer
   - improved host scoring

5. Add project memory:
   - saved targets
   - saved papers
   - saved designs
   - experiment logs

6. Add chemistry depth:
   - route comparison
   - analog reasoning
   - purchasability / precursor support

7. Add exportable scientific reports:
   - PDF
   - Markdown
   - lab-ready design summaries

---

## 26. Final Verdict

The correct design is not one giant answer engine.

It is one clean scientific product with:
- one interface,
- many specialist reasoning tools,
- visible evidence,
- structured outputs,
- and a workflow built for how biochemists actually think.

That is how I would design “AI microbiology and chemistry expert in one place.”
