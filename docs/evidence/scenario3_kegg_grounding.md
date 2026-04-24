# Evidence: system prompt change enables KEGG grounding

One of the three end-to-end smoke scenarios at the close of Phase 3 asked
the agent: `"Look up KEGG compound C00022 (pyruvate) and summarize."`
Twice — once before a targeted system-prompt + docstring change, once
after. The before/after captures how explicit trigger language shifted
the agent from answering identifier questions out of its own memory to
grounding them in the KEGG database record.

Test prompt and harness are in `tests/test_agent_e2e.py`; the setup
hits a live vLLM on `:8001` serving `google/gemma-4-E4B-it` at
`temperature=0.0` with all 15 tools bound. Assertions require at least
one KEGG tool call, a matched `tool_result`, and the final answer to
contain `pyruvate` plus a metabolic-context anchor.

---

## Before

Commit: `30bbcc7 phase3: agent core with native tool calling`
(Phase 3.6 initial run, prior to the prompt/docstring fixes.)

Event sequence — `scenario_3 run_a (3.84s)`:

```
[000..249] 250 streaming tokens (no tool_call events)
[250] final_answer: "Pyruvate (C00022) is a central metabolic
      intermediate in biochemistry, serving as a critical nexus point
      in cellular metabolism. It is a three-carbon $\alpha$-keto acid
      that plays vital roles in both catabolic and anabolic pathways.

      Here is a summary of its key roles:

      1. **Glycolysis End-Product:** In the breakdown of glucose
         (glycolysis), pyruvate is the final product formed from two
         molecules of glyceraldehyde-3-phosphate.
      2. **Entry to TCA Cycle:** Under aerobic conditions, pyruvate
         is converted to acetyl-CoA by the pyruvate dehydrogenase
         complex, allowing it to enter the tricarboxylic acid (TCA)
         cycle for complete oxidation and energy generation.
      3. **Gluconeogenesis:** In the reverse process (gluconeogenesis),
         pyruvate can be converted back into phosphoenolpyruvate
         (PEP), allowing for the synthesis of glucose.
      4. **Anaplerotic Reactions:** It is a precursor for various
         amino acids (e.g., alanine) and can be used in other
         biosynthetic pathways..."
[251] done: usage={iterations: 1, tool_calls: 0, ms: 3844}
```

Factually correct, biochemistry-textbook quality. But zero tool calls —
the model responded entirely from its own recall. The test assertion
`expected at least one kegg tool_call, got []` failed on both runs.

---

## After

Commits:
- `d5d71be phase3: system prompt rule for identifier-grounded lookups`
- `8cb0cf5 phase3: strengthen docstrings for database-lookup tools (kegg/pubmed/uniprot)`

Same prompt, same temperature, same tool set. Event sequence —
`scenario_3 run_a (4.40s)`:

```
[000] tool_call: name=fetch_kegg_live args={entity_id: "C00022"}
      id=chatcmpl-tool-a025b59ee8ef7755
[001] tool_result: id=chatcmpl-tool-a025b59ee8ef7755 content=
      '{"query": "C00022", "kind": "compound",
        "kegg_id": "cpd:C00022",
        "name": "Pyruvate; ; Pyruvic acid; ; 2-Oxopropanoate; ;
                 2-Oxopropanoic acid; ; Pyroracemic acid",
        "url": "https://www.kegg.jp/entry/cpd:C00022",
        "formula": "C3H4O3", "exact_mass": "88.0160",
        "pathways": "map00010  Glycolysis / Gluconeogenesis ...'
[002..183] 182 streaming tokens
[184] final_answer: "Pyruvate (KEGG ID: C00022) is a central metabolic
      intermediate with the chemical formula $\text{C}_3\text{H}_4\text{O}_3$.
      It is known by several names, including Pyruvic acid and
      2-Oxopropanoate.

      Metabolically, pyruvate is highly significant as it participates
      in numerous pathways, including:
      *   **Glycolysis / Gluconeogenesis** (map00010)
      *   **Citrate cycle (TCA cycle)** (map00020)
      *   **Pento..."
[185] done: usage={iterations: 2, tool_calls: 1, ms: 4400}
```

The agent calls `fetch_kegg_live(entity_id="C00022")` first, gets the
canonical record (names, formula, exact mass, KEGG pathway map IDs),
and *then* writes the answer. The formula `C3H4O3` and pathway IDs
`map00010` / `map00020` now come from the database, not from memory.
Same factual quality as before, but traceably grounded.

---

## The change

Two edits, landed in sequence:

1. `agent/prompts/__init__.py` — added an identifier-grounding paragraph
   between the identity block and the two-phase flow:

   > When the user references a structured identifier — KEGG IDs (C\\d+,
   > R\\d+, K\\d+, map\\d+), ChEBI IDs (CHEBI:\\d+), UniProt accessions,
   > PMIDs, EC numbers, or similar — call the corresponding lookup tool
   > before answering. Do NOT answer identifier lookups from memory even
   > when you know the entity; the user is asking for the database
   > record, not your recall. The same applies when the user writes
   > "look up", "fetch", "from KEGG", "from PubMed", or "search for" —
   > these phrases are explicit tool requests.

2. `agent/tools/{fetch_kegg_live,kegg_search,fetch_pubmed_live,fetch_uniprot,literature_search}.py`
   — added "Call this tool whenever the user..." trigger paragraphs to
   each docstring. `parse_docstring=True` on the `@tool` decorator pulls
   these into the OpenAI-style schema descriptions the LLM sees at bind
   time.

System-prompt budget: 775 → 897 tokens after the new paragraph, trimmed
back to 800 by compacting the two-phase block. ChEBI extension later
bumped it to 813 (under the 900-token ceiling).

---

## Takeaway

E4B will gladly answer identifier questions from memory unless the prompt
and tool descriptions explicitly call for grounding — and the fix is
cheap: one paragraph in the system prompt plus one "call this when..."
sentence per database-lookup tool's docstring.
