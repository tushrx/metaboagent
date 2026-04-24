import { describe, expect, it } from "vitest";
import { extractCitations } from "@/lib/citations";
import type { ToolActivity } from "@/lib/api";

/** Build a minimal ToolActivity with a JSON-stringified result payload. */
function makeActivity(
  name: string,
  resultPayload: object | string,
  id = `${name}-${Math.random().toString(36).slice(2, 7)}`,
): ToolActivity {
  return {
    id,
    name,
    args: {},
    status: "done",
    result:
      typeof resultPayload === "string"
        ? resultPayload
        : JSON.stringify(resultPayload),
    startedAt: 0,
    endedAt: 1000,
  };
}

describe("extractCitations", () => {
  it("pulls 10 deduped PMIDs from a pubmed tool result", () => {
    const hits = Array.from({ length: 10 }, (_, i) => ({
      pmid: `3000000${i}`,
      title: `paper ${i}`,
    }));
    const activity = makeActivity("fetch_pubmed_live", {
      query: "artemisinin",
      hits,
    });
    const citations = extractCitations([activity]);
    const pmids = citations.filter((c) => c.kind === "pmid");
    expect(pmids).toHaveLength(10);
    for (const c of pmids) {
      expect(c.url).toMatch(/^https:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/\d+\/$/);
      expect(c.provenance).toEqual(["fetch_pubmed_live"]);
    }
    // Dedup: same 10 PMIDs posted twice stay at 10.
    const again = extractCitations([activity, makeActivity("fetch_pubmed_live", { hits })]);
    const pmids2 = again.filter((c) => c.kind === "pmid");
    expect(pmids2).toHaveLength(10);
  });

  it("extracts KEGG compound + pathway map IDs", () => {
    const activity = makeActivity("fetch_kegg_live", {
      query: "C00022",
      kegg_id: "cpd:C00022",
      formula: "C3H4O3",
      pathways:
        "map00010 Glycolysis map00020 Citrate cycle map00030 Pentose phosphate",
      related_reaction: "R00200",
    });
    const citations = extractCitations([activity]);
    const kinds = citations.map((c) => c.kind).sort();
    expect(kinds).toContain("kegg_compound");
    expect(kinds).toContain("kegg_pathway");
    expect(kinds).toContain("kegg_reaction");

    const pathways = citations.filter((c) => c.kind === "kegg_pathway");
    const pathwayIds = pathways.map((c) => c.id).sort();
    expect(pathwayIds).toEqual(["map00010", "map00020", "map00030"]);
    expect(pathways[0].url).toBe("https://www.kegg.jp/pathway/map00010");

    const compound = citations.find((c) => c.kind === "kegg_compound");
    expect(compound?.id).toBe("C00022");
    expect(compound?.url).toBe("https://www.kegg.jp/entry/C00022");
  });

  it("extracts UniProt accessions and tags provenance", () => {
    const activity = makeActivity("fetch_uniprot", {
      query: "phytoene synthase",
      accession: "P22887",
      other_seen: "Q14739 mentioned cross-ref O60341",
    });
    const citations = extractCitations([activity]);
    const uniprot = citations.filter((c) => c.kind === "uniprot");
    const ids = uniprot.map((c) => c.id).sort();
    expect(ids).toContain("P22887");
    expect(ids).toContain("Q14739");
    expect(ids).toContain("O60341");
    expect(uniprot[0].provenance).toEqual(["fetch_uniprot"]);
    expect(uniprot[0].url).toMatch(
      /^https:\/\/www\.uniprot\.org\/uniprotkb\/[A-Z0-9]+\/entry$/,
    );
  });

  it("captures both PMID and DOI from the same result", () => {
    const activity = makeActivity("fetch_pubmed_live", {
      hits: [
        {
          pmid: "36296479",
          title: "From Plant to Yeast",
          doi: "10.3390/molecules27207029",
        },
      ],
    });
    const citations = extractCitations([activity]);
    const pmid = citations.find((c) => c.kind === "pmid");
    const doi = citations.find((c) => c.kind === "doi");
    expect(pmid?.id).toBe("36296479");
    expect(pmid?.url).toBe("https://pubmed.ncbi.nlm.nih.gov/36296479/");
    expect(doi?.id.toLowerCase()).toBe("10.3390/molecules27207029");
    expect(doi?.url.toLowerCase()).toBe(
      "https://doi.org/10.3390/molecules27207029",
    );
  });

  it("returns an empty array for empty / missing / malformed results", () => {
    const empty = makeActivity("any_tool", "");
    const missing: ToolActivity = {
      id: "x",
      name: "any_tool",
      args: {},
      status: "done",
      startedAt: 0,
      endedAt: 1,
      // no result field
    };
    const malformed = makeActivity("any_tool", "{{not valid json but no ids");
    const circular: Record<string, unknown> = {};
    circular.self = circular; // JSON.stringify would throw

    const weird: ToolActivity = {
      id: "y",
      name: "any_tool",
      args: {},
      status: "done",
      startedAt: 0,
      endedAt: 1,
      result: circular,
    };

    const citations = extractCitations([empty, missing, malformed, weird]);
    expect(citations).toEqual([]);
  });

  // ---- source-aware gating -------------------------------------------

  it("KEGG result with C00022 does NOT extract as UniProt", () => {
    const activity = makeActivity("fetch_kegg_live", {
      kegg_id: "cpd:C00022",
      formula: "C3H4O3",
      pathways: "map00010 map00020",
    });
    const citations = extractCitations([activity]);
    const uniprot = citations.filter((c) => c.kind === "uniprot");
    expect(uniprot).toHaveLength(0);
    // KEGG compound should still come through:
    const compound = citations.find((c) => c.kind === "kegg_compound");
    expect(compound?.id).toBe("C00022");
  });

  it("UniProt result with P05067 DOES extract as UniProt", () => {
    const activity = makeActivity("fetch_uniprot", {
      accession: "P05067",
      protein_name: "Amyloid-beta precursor protein",
    });
    const citations = extractCitations([activity]);
    const uniprot = citations.find((c) => c.kind === "uniprot");
    expect(uniprot?.id).toBe("P05067");
    expect(uniprot?.url).toBe(
      "https://www.uniprot.org/uniprotkb/P05067/entry",
    );
  });

  it("dedupes citations seen in multiple tools and records both provenances", () => {
    const a = makeActivity("fetch_pubmed_live", {
      hits: [{ pmid: "12345678" }],
    });
    const b = makeActivity("search_literature", {
      hits: [{ pmid: "12345678" }],
    });
    const citations = extractCitations([a, b]);
    const pmids = citations.filter((c) => c.kind === "pmid");
    expect(pmids).toHaveLength(1);
    expect(pmids[0].provenance.sort()).toEqual([
      "fetch_pubmed_live",
      "search_literature",
    ]);
  });
});
