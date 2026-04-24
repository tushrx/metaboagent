/**
 * Regex-based citation extraction from tool_result payloads.
 *
 * We stringify each tool result and apply a set of identifier patterns
 * (PubMed, KEGG reactions/compounds/orthologs/pathways, UniProt, ChEBI,
 * DOI). Hits are deduplicated by (kind, id) and annotated with the list
 * of tool names that produced them.
 *
 * Note: regex extraction will inevitably produce false positives
 * (especially for UniProt's 6-char pattern, which can match random
 * strings). This is acceptable at the evidence-rail display layer
 * because every citation is a link to an authoritative source — if a
 * false hit 404s the user just sees a "not found" page on the target
 * site.
 */
import type { ToolActivity } from "./api";

export type CitationKind =
  | "pmid"
  | "kegg_compound"
  | "kegg_reaction"
  | "kegg_ortholog"
  | "kegg_pathway"
  | "uniprot"
  | "chebi"
  | "doi";

export interface Citation {
  kind: CitationKind;
  id: string;
  url: string;
  /** Tool names (sorted, deduped) whose results surfaced this citation. */
  provenance: string[];
}

// ---- Regex patterns -----------------------------------------------------

// Use fresh instances each call — global regexes carry lastIndex.
//
// PMID and CHEBI allow `["\s:,]*` between the prefix and the digits so we
// match both prose (``PMID:12345``) and JSON-stringified tool results
// (``"pmid":"12345"``). UniProt widens the spec's `[A-NR-Z]` first letter
// to `[A-Z]` so we don't miss the common ``P12345``/``O60341``/``Q14739``
// forms — false positives are tolerable at the evidence-panel layer.
function patterns() {
  return {
    pmid: /pmid["\s:,]*(\d{4,})/gi,
    kegg: /\b([CRK]\d{5})\b/g,
    keggPath: /\b(map\d{5})\b/g,
    chebi: /chebi["\s:,]*(\d+)/gi,
    uniprot: /\b([A-Z][0-9][A-Z0-9]{3}[0-9])\b/g,
    doi: /10\.\d{4,9}\/[-._;()/:A-Z0-9]+/gi,
  };
}

// ---- URL builders -------------------------------------------------------

function urlFor(kind: CitationKind, id: string): string {
  switch (kind) {
    case "pmid":
      return `https://pubmed.ncbi.nlm.nih.gov/${id}/`;
    case "kegg_compound":
    case "kegg_reaction":
    case "kegg_ortholog":
      return `https://www.kegg.jp/entry/${id}`;
    case "kegg_pathway":
      return `https://www.kegg.jp/pathway/${id}`;
    case "uniprot":
      return `https://www.uniprot.org/uniprotkb/${id}/entry`;
    case "chebi":
      return `https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:${id}`;
    case "doi":
      return `https://doi.org/${id}`;
  }
}

function keggKind(token: string): CitationKind {
  const c = token.charAt(0).toUpperCase();
  if (c === "C") return "kegg_compound";
  if (c === "R") return "kegg_reaction";
  return "kegg_ortholog"; // K
}

// ---- Source-aware gating ------------------------------------------------

type RegexKey = "pmid" | "doi" | "kegg" | "keggPath" | "chebi" | "uniprot";

const ALL_REGEXES: ReadonlySet<RegexKey> = new Set<RegexKey>([
  "pmid",
  "doi",
  "kegg",
  "keggPath",
  "chebi",
  "uniprot",
]);

/**
 * Which regexes to apply per tool name. A C00022 that looks like a
 * UniProt accession shouldn't be extracted as one when the provenance
 * is a KEGG lookup. Tools not in this map fall back to running every
 * regex (safe default for unknown / new tools).
 */
const REGEXES_BY_TOOL: Record<string, ReadonlySet<RegexKey>> = {
  fetch_pubmed_live: new Set<RegexKey>(["pmid", "doi"]),
  search_literature: new Set<RegexKey>(["pmid", "doi", "chebi"]),
  web_search: new Set<RegexKey>(["pmid", "doi", "chebi"]),
  fetch_kegg_live: new Set<RegexKey>(["kegg", "keggPath"]),
  search_kegg: new Set<RegexKey>(["kegg", "keggPath"]),
  fetch_uniprot: new Set<RegexKey>(["uniprot", "chebi"]),
  fetch_pubchem: new Set<RegexKey>(["chebi"]),
};

function enabledFor(toolName: string): ReadonlySet<RegexKey> {
  return REGEXES_BY_TOOL[toolName] ?? ALL_REGEXES;
}

// ---- Extraction ---------------------------------------------------------

function extractFromText(
  text: string,
  enabled: ReadonlySet<RegexKey>,
): Array<{ kind: CitationKind; id: string }> {
  const hits: Array<{ kind: CitationKind; id: string }> = [];
  const p = patterns();

  if (enabled.has("pmid")) {
    for (const m of Array.from(text.matchAll(p.pmid))) {
      hits.push({ kind: "pmid", id: m[1] });
    }
  }
  if (enabled.has("kegg")) {
    for (const m of Array.from(text.matchAll(p.kegg))) {
      hits.push({ kind: keggKind(m[1]), id: m[1].toUpperCase() });
    }
  }
  if (enabled.has("keggPath")) {
    for (const m of Array.from(text.matchAll(p.keggPath))) {
      hits.push({ kind: "kegg_pathway", id: m[1] });
    }
  }
  if (enabled.has("chebi")) {
    for (const m of Array.from(text.matchAll(p.chebi))) {
      hits.push({ kind: "chebi", id: m[1] });
    }
  }
  if (enabled.has("uniprot")) {
    for (const m of Array.from(text.matchAll(p.uniprot))) {
      hits.push({ kind: "uniprot", id: m[1] });
    }
  }
  if (enabled.has("doi")) {
    for (const m of Array.from(text.matchAll(p.doi))) {
      hits.push({ kind: "doi", id: m[0] });
    }
  }

  return hits;
}

function stringifyResult(result: unknown): string {
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result);
  } catch {
    return String(result);
  }
}

export function extractCitations(activities: ToolActivity[]): Citation[] {
  // Map key: `${kind}::${id}` → Citation
  const map = new Map<string, Citation>();

  for (const a of activities) {
    if (a.result === undefined || a.result === null) continue;
    const text = stringifyResult(a.result);
    if (!text) continue;

    for (const hit of extractFromText(text, enabledFor(a.name))) {
      const key = `${hit.kind}::${hit.id}`;
      const existing = map.get(key);
      if (existing) {
        if (!existing.provenance.includes(a.name)) {
          existing.provenance = [...existing.provenance, a.name].sort();
        }
      } else {
        map.set(key, {
          kind: hit.kind,
          id: hit.id,
          url: urlFor(hit.kind, hit.id),
          provenance: [a.name],
        });
      }
    }
  }

  return Array.from(map.values());
}

// ---- Display helpers (used by the UI) -----------------------------------

export function citationLabel(kind: CitationKind): string {
  switch (kind) {
    case "pmid":
      return "PMID";
    case "kegg_compound":
      return "KEGG cpd";
    case "kegg_reaction":
      return "KEGG rxn";
    case "kegg_ortholog":
      return "KEGG KO";
    case "kegg_pathway":
      return "KEGG map";
    case "uniprot":
      return "UniProt";
    case "chebi":
      return "ChEBI";
    case "doi":
      return "DOI";
  }
}

/** Group citations by kind; preserves insertion order within each group. */
export function groupCitations(
  citations: Citation[],
): Array<[CitationKind, Citation[]]> {
  const order: CitationKind[] = [
    "pmid",
    "doi",
    "kegg_pathway",
    "kegg_reaction",
    "kegg_compound",
    "kegg_ortholog",
    "uniprot",
    "chebi",
  ];
  const groups = new Map<CitationKind, Citation[]>();
  for (const c of citations) {
    const existing = groups.get(c.kind);
    if (existing) existing.push(c);
    else groups.set(c.kind, [c]);
  }
  return order
    .filter((k) => groups.has(k))
    .map((k) => [k, groups.get(k)!] as [CitationKind, Citation[]]);
}
