import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  extractPlan,
  formatPlanAsMarkdown,
  type PlanOption,
} from "@/lib/plan";

describe("extractPlan", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    warnSpy.mockRestore();
  });

  it("extracts a 3-option bare-array plan", () => {
    const text = `
Some lead-in prose about the literature.

<plan>
[
  {"id": "A", "title": "Microbial pathway in S. cerevisiae", "route": "microbial", "host": "scerevisiae", "summary": "Engineer yeast.", "est_difficulty": "high", "est_confidence": 0.85},
  {"id": "B", "title": "E. coli reconstruction", "route": "microbial", "host": "ecoli", "summary": "Use E. coli.", "est_difficulty": "medium", "est_confidence": 0.75},
  {"id": "C", "title": "Cell-free cascade", "route": "enzymatic", "host": null, "summary": "Purified enzymes.", "est_difficulty": "high", "est_confidence": 0.6}
]
</plan>
Pick an approach.`.trim();

    const { plan, textWithoutPlan } = extractPlan(text);
    expect(plan).not.toBeNull();
    expect(plan!).toHaveLength(3);
    expect(plan![0].id).toBe("A");
    expect(plan![0].host).toBe("scerevisiae");
    expect(plan![2].host).toBeUndefined(); // null in JSON -> undefined
    expect(textWithoutPlan).toContain("Some lead-in prose");
    expect(textWithoutPlan).toContain("Pick an approach.");
    expect(textWithoutPlan).not.toContain("<plan>");
  });

  it("extracts a single-option plan", () => {
    const text = `<plan>[{"id":"A","title":"Only option","summary":"do X"}]</plan>`;
    const { plan } = extractPlan(text);
    expect(plan).not.toBeNull();
    expect(plan!).toHaveLength(1);
    expect(plan![0].title).toBe("Only option");
  });

  it('extracts the canonical {target, approaches: [...]} shape', () => {
    const text = `<plan>{"target":"vanillin","approaches":[
      {"id":"A","title":"Microbial","summary":"E. coli route","route":"microbial"},
      {"id":"B","title":"Enzymatic","summary":"Purified lyase"}
    ]}</plan>`;
    const { plan } = extractPlan(text);
    expect(plan).not.toBeNull();
    expect(plan!).toHaveLength(2);
    expect(plan![0].id).toBe("A");
    expect(plan![1].title).toBe("Enzymatic");
  });

  it("extracts NDJSON-style (multiple {} without outer array)", () => {
    // Real Gemma 4 output from eval/results/phase1_diagnosis_*.json
    const text = `<plan>
{"id": "A", "title": "Yeast", "summary": "engineer scerevisiae", "est_confidence": 0.95}
{"id": "B", "title": "Cascade", "summary": "purified enzymes", "est_confidence": 0.75}
{"id": "C", "title": "Semi-synthetic", "summary": "fermentation + chem", "est_confidence": 0.85}
</plan>`;
    const { plan } = extractPlan(text);
    expect(plan).not.toBeNull();
    expect(plan!).toHaveLength(3);
    expect(plan!.map((p) => p.id)).toEqual(["A", "B", "C"]);
  });

  it("returns null and warns on malformed JSON inside <plan>", () => {
    const text = `Some prose <plan>this is not json</plan> more prose`;
    const { plan, textWithoutPlan } = extractPlan(text);
    expect(plan).toBeNull();
    expect(textWithoutPlan).toBe(text);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("returns null when there is no <plan> tag", () => {
    const text = "Just regular pathway prose with no plan block.";
    const { plan, textWithoutPlan } = extractPlan(text);
    expect(plan).toBeNull();
    expect(textWithoutPlan).toBe(text);
  });

  it("only extracts the first plan when multiple are present", () => {
    const text = `<plan>[{"id":"A","title":"first","summary":""}]</plan>
followed by
<plan>[{"id":"B","title":"second","summary":""}]</plan>`;
    const { plan, textWithoutPlan } = extractPlan(text);
    expect(plan).not.toBeNull();
    expect(plan!).toHaveLength(1);
    expect(plan![0].id).toBe("A");
    // Second plan stays in the residual text — defensive, surfaces it
    // for inspection rather than silently dropping it.
    expect(textWithoutPlan).toContain("<plan>");
  });

  it("is tolerant of whitespace and newlines around the JSON", () => {
    const text = `<plan>


    [
      {"id":"A","title":"spaced","summary":""}
    ]


  </plan>`;
    const { plan } = extractPlan(text);
    expect(plan).not.toBeNull();
    expect(plan![0].title).toBe("spaced");
  });

  it("returns null for partial-stream <plan> with no closing tag", () => {
    const text = `<plan>[{"id":"A","title":"`;
    const { plan, textWithoutPlan } = extractPlan(text);
    expect(plan).toBeNull();
    expect(textWithoutPlan).toBe(text);
  });
});

describe("formatPlanAsMarkdown", () => {
  it("renders a 3-option plan with metadata and a reply hint", () => {
    const plan: PlanOption[] = [
      {
        id: "A",
        title: "Yeast Heterologous Pathway",
        route: "microbial",
        host: "scerevisiae",
        summary: "Engineer S. cerevisiae.",
        est_difficulty: "high",
        est_confidence: 0.85,
      },
      {
        id: "B",
        title: "Enzymatic Cascade",
        route: "enzymatic",
        summary: "Purified enzymes.",
        est_difficulty: "high",
        est_confidence: 0.75,
      },
      {
        id: "C",
        title: "Chemical Oxidation",
        route: "chemical",
        summary: "Oxidise the precursor.",
        est_difficulty: "medium",
        est_confidence: 0.6,
      },
    ];
    const md = formatPlanAsMarkdown(plan);
    expect(md).toContain("**Approaches**");
    expect(md).toContain("**A. Yeast Heterologous Pathway**");
    expect(md).toContain("(microbial · scerevisiae · high difficulty · 0.85 confidence)");
    expect(md).toContain("Engineer S. cerevisiae.");
    expect(md).toContain(
      "*Reply with A, B, or C to continue with that approach.*",
    );
  });

  it("omits parenthetical metadata when no fields are present", () => {
    const plan: PlanOption[] = [
      { id: "A", title: "Bare option", summary: "just a title" },
    ];
    const md = formatPlanAsMarkdown(plan);
    expect(md).toContain("**A. Bare option**");
    expect(md).not.toContain("(");
    expect(md).toContain("*Reply with A to continue with that approach.*");
  });

  it("uses 'A or B' for two options", () => {
    const plan: PlanOption[] = [
      { id: "A", title: "First", summary: "" },
      { id: "B", title: "Second", summary: "" },
    ];
    expect(formatPlanAsMarkdown(plan)).toContain(
      "*Reply with A or B to continue with that approach.*",
    );
  });
});
