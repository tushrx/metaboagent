import { describe, expect, it } from "vitest";
import { pathwayToMermaid } from "@/lib/pathway-to-mermaid";
import type { PathwayData } from "@/lib/pathway";

describe("pathwayToMermaid", () => {
  it("serializes a clean pathway with enzyme+EC labels", () => {
    const pathway: PathwayData = {
      source_message_id: "m1",
      steps: [
        {
          index: 1,
          substrate: "acetyl-CoA",
          product: "acetoacetyl-CoA",
          enzyme: { name: "acetoacetyl-CoA thiolase", organism: "E. coli" },
          ec: "2.3.1.9",
          reaction: "R00238",
        },
        {
          index: 2,
          substrate: "acetoacetyl-CoA",
          product: "HMG-CoA",
          enzyme: { name: "HMG-CoA synthase" },
          ec: "2.3.3.10",
        },
      ],
    };
    const mmd = pathwayToMermaid(pathway);
    // Header
    expect(mmd.split("\n")[0]).toBe("flowchart LR");
    // 3 nodes total (substrate + 2 products), 2 edges.
    expect(mmd).toContain(`N0("acetyl-CoA")`);
    expect(mmd).toContain(`N1("acetoacetyl-CoA")`);
    expect(mmd).toContain(`N2("HMG-CoA")`);
    // Edge labels include enzyme name + EC joined by <br/>.
    expect(mmd).toContain(
      `N0 -->|"acetoacetyl-CoA thiolase<br/>EC 2.3.1.9"| N1`,
    );
    expect(mmd).toContain(`N1 -->|"HMG-CoA synthase<br/>EC 2.3.3.10"| N2`);
  });

  it("handles sparse steps (no enzyme, no EC) with a bare arrow", () => {
    const pathway: PathwayData = {
      source_message_id: "m2",
      steps: [
        {
          index: 1,
          substrate: "glucose",
          product: "glucose-6-phosphate",
          ec: "2.7.1.1",
        },
        {
          index: 2,
          substrate: "glucose-6-phosphate",
          product: "fructose-6-phosphate",
          // no enzyme, no EC
        },
      ],
    };
    const mmd = pathwayToMermaid(pathway);
    expect(mmd).toContain(`N0("glucose")`);
    expect(mmd).toContain(`N1("glucose-6-phosphate")`);
    expect(mmd).toContain(`N2("fructose-6-phosphate")`);
    // First edge has EC only (no enzyme name).
    expect(mmd).toContain(`N0 -->|"EC 2.7.1.1"| N1`);
    // Second edge is bare (no label block).
    expect(mmd).toMatch(/^\s*N1 --> N2$/m);
  });

  it("returns empty string for an empty pathway", () => {
    const pathway: PathwayData = { source_message_id: "m0", steps: [] };
    expect(pathwayToMermaid(pathway)).toBe("");
  });
});
