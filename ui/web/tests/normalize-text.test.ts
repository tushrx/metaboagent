import { describe, expect, it } from "vitest";
import { normalizeText } from "@/lib/normalize-text";

describe("normalizeText", () => {
  // --- arrow patterns --------------------------------------------------

  it("converts $\\rightarrow$ (LaTeX inline arrow) to →", () => {
    expect(normalizeText("Glucose $\\rightarrow$ Pyruvate")).toBe(
      "Glucose → Pyruvate",
    );
  });

  it("converts bare \\rightarrow command to →", () => {
    expect(normalizeText("Step 1: A \\rightarrow B")).toBe("Step 1: A → B");
  });

  it("converts &rarr; HTML entity to →", () => {
    expect(normalizeText("Glucose &rarr; Pyruvate")).toBe(
      "Glucose → Pyruvate",
    );
  });

  it("converts \\rightleftharpoons to ⇌ (equilibrium)", () => {
    expect(normalizeText("$A \\rightleftharpoons B$")).toBe("A ⇌ B");
  });

  it("converts \\longrightarrow to → before \\rightarrow rule fires", () => {
    expect(normalizeText("A \\longrightarrow B")).toBe("A → B");
  });

  it("converts \\to, \\leftarrow, \\Rightarrow to their glyphs", () => {
    expect(normalizeText("A \\to B \\leftarrow C \\Rightarrow D")).toBe(
      "A → B ← C ⇒ D",
    );
  });

  // --- chemistry-notation $...$ wrapping ------------------------------

  it("strips $\\text{X}_n$ to markdown-friendly X_n", () => {
    expect(normalizeText("Formula: $\\text{H}_2\\text{O}$")).toBe(
      "Formula: H_2O",
    );
  });

  it("strips $\\text{X}^n$ to X^n with charge braces preserved", () => {
    expect(normalizeText("Charge: $\\text{Ca}^{2+}$")).toBe("Charge: Ca^{2+}");
  });

  it("handles compound chemistry like $\\text{C}_3\\text{H}_4\\text{O}_3$", () => {
    expect(
      normalizeText("Pyruvate ($\\text{C}_3\\text{H}_4\\text{O}_3$) is a..."),
    ).toBe("Pyruvate (C_3H_4O_3) is a...");
  });

  it("handles single-species $\\text{C}_3$", () => {
    expect(normalizeText("$\\text{C}_3$")).toBe("C_3");
  });

  // --- $...$ wrapping reaction equations and bare compound names ----

  it("strips $...$ around a reaction equation containing an arrow", () => {
    expect(normalizeText("$Glucose → Glucose-6-phosphate$")).toBe(
      "Glucose → Glucose-6-phosphate",
    );
  });

  it("strips $NADH$ (plain compound name)", () => {
    expect(normalizeText("$NADH$ is a cofactor.")).toBe("NADH is a cofactor.");
  });

  it("preserves $NAD^+$ (math marker present)", () => {
    expect(normalizeText("$NAD^+$")).toBe("NAD^+");
  });

  // --- safety: prose with literal dollar signs ------------------------

  it("leaves plain prose untouched", () => {
    const plain = "This is a regular sentence with no LaTeX.";
    expect(normalizeText(plain)).toBe(plain);
  });

  it("leaves currency prose alone ($50 to $100)", () => {
    expect(normalizeText("Costs $50 to $100 today.")).toBe(
      "Costs $50 to $100 today.",
    );
  });

  it("leaves single-dollar phrases like '$200/L for media' alone", () => {
    expect(normalizeText("Step costs $200/L for media.")).toBe(
      "Step costs $200/L for media.",
    );
  });

  it("returns empty string unchanged", () => {
    expect(normalizeText("")).toBe("");
  });
});
