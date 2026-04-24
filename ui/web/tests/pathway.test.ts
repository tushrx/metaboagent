import { describe, expect, it } from "vitest";
import { extractPathway } from "@/lib/pathway";

describe("extractPathway", () => {
  it("parses a clean, fully-populated 4-step pathway", () => {
    const content = `Here is a mevalonate pathway route in *E. coli*:

Step 1: acetyl-CoA → acetoacetyl-CoA
    Reaction: R00238   EC 2.3.1.9
    Enzyme: acetoacetyl-CoA thiolase (E. coli)   PMID:12345678

Step 2: acetoacetyl-CoA → HMG-CoA
    Reaction: R01978   EC 2.3.3.10
    Enzyme: HMG-CoA synthase (S. cerevisiae)   PMID:23456789

Step 3: HMG-CoA → mevalonate
    Reaction: R02082   EC 1.1.1.34
    Enzyme: HMG-CoA reductase (S. cerevisiae)   PMID:34567890

Step 4: mevalonate → mevalonate-5-phosphate
    Reaction: R02245   EC 2.7.1.36
    Enzyme: mevalonate kinase (H. sapiens)   PMID:45678901

Confidence: 0.80 — grounded in KEGG and classic mevalonate literature.`;

    const p = extractPathway(content, "msg-123");
    expect(p.source_message_id).toBe("msg-123");
    expect(p.steps).toHaveLength(4);

    const s1 = p.steps[0];
    expect(s1.index).toBe(1);
    expect(s1.substrate).toBe("acetyl-CoA");
    expect(s1.product).toBe("acetoacetyl-CoA");
    expect(s1.reaction).toBe("R00238");
    expect(s1.ec).toBe("2.3.1.9");
    expect(s1.enzyme?.name).toBe("acetoacetyl-CoA thiolase");
    expect(s1.enzyme?.organism).toBe("E. coli");
    expect(s1.pmid).toBe("12345678");

    const s4 = p.steps[3];
    expect(s4.product).toBe("mevalonate-5-phosphate");
    expect(s4.reaction).toBe("R02245");
    expect(s4.enzyme?.name).toBe("mevalonate kinase");
  });

  it("parses a sparse pathway (missing enzyme / PMID) without crashing", () => {
    const content = `Step 1: glucose -> glucose-6-phosphate
    Reaction: R00299   EC 2.7.1.1

Step 2: glucose-6-phosphate → fructose-6-phosphate
    Enzyme: phosphoglucose isomerase

Step 3: fructose-6-phosphate -> F1,6BP
`;
    const p = extractPathway(content, "m-sparse");
    expect(p.steps).toHaveLength(3);

    expect(p.steps[0].reaction).toBe("R00299");
    expect(p.steps[0].ec).toBe("2.7.1.1");
    expect(p.steps[0].enzyme).toBeUndefined();
    expect(p.steps[0].pmid).toBeUndefined();

    expect(p.steps[1].enzyme?.name).toBe("phosphoglucose isomerase");
    expect(p.steps[1].reaction).toBeUndefined();

    expect(p.steps[2].substrate).toBe("fructose-6-phosphate");
    expect(p.steps[2].product).toBe("F1,6BP");
    expect(p.steps[2].enzyme).toBeUndefined();
  });

  it("returns empty steps for non-pathway text", () => {
    const content = `Pyruvate (C00022) is a central metabolic hub that participates in many pathways including glycolysis and the TCA cycle.

It is produced from phosphoenolpyruvate by pyruvate kinase and can be further oxidized to acetyl-CoA.`;
    const p = extractPathway(content, "m-none");
    expect(p.steps).toEqual([]);
    expect(p.source_message_id).toBe("m-none");
  });

  it("normalizes LaTeX / HTML arrow renderings before parsing", () => {
    // Real-world artifact: Gemma 4 keeps emitting $\rightarrow$ despite the
    // system prompt asking for plain →. We normalize at the boundary.
    const content = `Step 1: Acetyl-CoA $\\rightarrow$ Acetoacetyl-CoA
    Reaction: R00238   EC 2.3.1.9
    Enzyme: Thiolase (E. coli)

Step 2: Acetoacetyl-CoA \\rightarrow HMG-CoA
    Enzyme: HMG-CoA synthase

Step 3: HMG-CoA &rarr; Mevalonate
`;
    const p = extractPathway(content, "m-latex");
    expect(p.steps).toHaveLength(3);
    expect(p.steps[0].substrate).toBe("Acetyl-CoA");
    expect(p.steps[0].product).toBe("Acetoacetyl-CoA");
    expect(p.steps[1].substrate).toBe("Acetoacetyl-CoA");
    expect(p.steps[1].product).toBe("HMG-CoA");
    expect(p.steps[2].product).toBe("Mevalonate");
  });

  it("truncates to the first pathway when a second 'Step 1' appears", () => {
    const content = `Pathway A:
Step 1: A1 → A2
    Enzyme: enzA
Step 2: A2 → A3

Pathway B:
Step 1: B1 → B2
Step 2: B2 → B3
`;
    const p = extractPathway(content, "m-two");
    expect(p.steps.map((s) => s.substrate)).toEqual(["A1", "A2"]);
    expect(p.steps.map((s) => s.product)).toEqual(["A2", "A3"]);
  });
});
