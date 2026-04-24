# Finding: Gemma 4 E4B's Chemical Structure Recognition Is Insufficient Without Domain Specialization

## Setup

- **20-structure benchmark** sourced from PubChem, tiered by visual
  complexity: simple (aspirin, caffeine, glucose, glycine, ethanol),
  medium (ibuprofen, pyruvate, acetyl-CoA, NAD+, ATP, cholesterol,
  vanillin, artemisinin), hard (taxol, mevalonate, lycopene, FAD,
  coenzyme B12), very-hard (erythromycin, rapamycin).
- **Ground truth** = PubChem canonical SMILES re-canonicalised through
  RDKit, plus an RDKit-computed InChIKey per entry.
- **Extraction** = direct vision call to Gemma 4 E4B via vLLM's
  OpenAI-compatible API; tool prompt asks for JSON-only output with
  `smiles`, `confidence`, `alternative_smiles`, and `notes`.
- **Scoring** runs in RDKit and assigns each result to one of four
  buckets:
  - `PASS_STRICT` — RDKit-canonical SMILES matches ground truth.
  - `PASS_INCHI` — InChIKey matches (credits structurally equivalent
    representations that happen to differ by component ordering,
    protonation, or tautomer).
  - `PARTIAL` — model returned RDKit-valid SMILES but a structurally
    different molecule.
  - `FAIL` — model returned no SMILES or RDKit rejected it.

## Results

| bucket | count | % |
|---|---|---|
| PASS_STRICT | 1 | 5 % |
| PASS_INCHI | 0 | 0 % |
| PARTIAL | 13 | 65 % |
| FAIL | 6 | 30 % |

| tier | n | PASS_STRICT | PASS_INCHI | PARTIAL | FAIL |
|---|---|---|---|---|---|
| simple | 5 | 1 (20%) | 0 | 4 (80%) | 0 |
| medium | 8 | 0 | 0 | 5 (62%) | 3 (38%) |
| hard | 5 | 0 | 0 | 3 (60%) | 2 (40%) |
| very-hard | 2 | 0 | 0 | 1 (50%) | 1 (50%) |

Only ethanol (C₂H₆O, the trivial case) passed strict matching. Two of
the six FAILs on the initial run were 90 s vision-call timeouts on
very dense structures (coenzyme B12, erythromycin). Re-running those
two with a 300 s timeout (and `max_retries=0` so the openai client
doesn't silently triple the wallclock via its default two-retry
policy) flipped one verdict and not the other: erythromycin produced
structurally valid but wrong SMILES (PARTIAL), while coenzyme B12
still timed out at 300 s (FAIL). In other words, the accuracy ceiling
is not wholly a timeout artefact — longer timeouts move some FAILs
into PARTIAL, but they do not manufacture correct answers, and the
densest structures remain beyond E4B's practical vision latency.

## Observations

- **The model produces chemistry-shaped output that is structurally
  valid but represents the wrong molecule.** The simple-tier failures
  are revealing: aspirin was extracted as phenyl acetate (dropped the
  ortho-carboxylic acid), caffeine became a diazepane with a pendant
  amide, glucose became a four-carbon tetrose. These are not
  canonicalisation drift — they are compound confusions.
- **Self-reported confidence is uncorrelated with accuracy.** Several
  PARTIAL-bucket results carried `confidence: "high"`. A downstream
  UI cannot use the confidence field as a filter.
- **The `notes` field is qualitatively useful despite the wrong main
  extraction.** The model frequently flags stereochemistry ambiguity,
  ring-junction uncertainty, and tautomer concerns that a human
  reviewer would want to see. It's an honest commentary on a wrong
  answer.
- **Two of six initial failures were vision-encoder timeouts**, not
  extraction errors. E4B on a dense dinucleotide-sized structure at
  default vLLM settings can take more than 90 s on a single L40, and
  cobalamin does not produce a response even within 300 s. This has
  implications for latency budgets at demo time: we should not promise
  a best-effort extraction on arbitrarily dense structures.

## Implications

- **General-purpose multimodal LLMs are not a substitute for
  specialised OCSR systems** (optical chemical structure recognition).
  Tools like DECIMER, OSRA, Imago, and MolScribe were purpose-built
  for this exact task; they encode prior knowledge of chemistry
  notation that a general-purpose vision encoder does not.
- **A production metabolic-engineering agent should integrate a
  specialised OCSR tool** as the primary SMILES extractor. Gemma 4
  vision can still play a role in enrichment: surfacing notes,
  flagging ambiguity, or reading higher-level pathway diagrams that
  do not require atom-level precision.
- **Gemma 4 vision may still be fit for higher-level tasks we have
  not yet evaluated** — reading pathway diagrams, interpreting lab
  photographs, annotating gel images. Those are distinct capabilities
  from atom-level structure extraction and need their own benchmarks.

## Reproducibility

- **Test set:** `eval/scenarios/structures/` (20 PNGs + `ground_truth.json`)
- **Eval script:** `eval/eval_structure_extraction.py`
- **Raw results:** `eval/results/structure_extraction_*.json`
- **Tool under test:** `agent/tools/parse_structure_image.py`

Re-running: `PYTHONPATH=. python3 eval/eval_structure_extraction.py`
(set `PARSE_STRUCTURE_TIMEOUT_S=300` to extend the per-call timeout
for very dense structures).

## What the MetaboAgent product does with this finding

- **The `parse_structure_image` tool is available** in the agent's
  tool registry and wired end-to-end from attachment upload through
  RDKit validation, so the capability exists and can demonstrate the
  pipeline.
- **The evidence-rail UI marks the tool as experimental** with an
  amber badge and an explicit tooltip naming the 5% accuracy number.
  The expanded card shows the RDKit-canonicalised SMILES alongside
  the model's self-reported confidence and caveat notes — a user
  can see exactly what the model said, whether it hedged, and has
  enough information to verify manually before trusting the result.
- **The primary value proposition — text-based pathway design with
  evidence grounded in PubMed / KEGG / UniProt — does not depend on
  vision accuracy.** The chemistry OCSR limitation is a scoped
  finding, not a product-level blocker.
- **Future work:** integrate DECIMER or an equivalent OCSR model as
  the primary extractor, keep Gemma 4 for enrichment (notes,
  confidence signals, ambiguity flagging). A-B evaluation against
  this same 20-structure benchmark would give a defensible accuracy
  number to publish.
