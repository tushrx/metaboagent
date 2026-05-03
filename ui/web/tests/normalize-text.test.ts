import { describe, expect, it } from "vitest";
import { normalizeText } from "@/lib/normalize-text";

describe("normalizeText", () => {
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

  it("strips $\\text{X}_n$ to markdown-friendly X_n", () => {
    expect(normalizeText("Formula: $\\text{H}_2\\text{O}$")).toBe(
      "Formula: H_2O",
    );
  });

  it("strips $\\text{X}^n$ to X^n", () => {
    expect(normalizeText("Charge: $\\text{Ca}^{2+}$")).toBe("Charge: Ca^{2+}");
  });

  it("handles compound chemistry like $\\text{C}_3\\text{H}_4\\text{O}_3$", () => {
    expect(
      normalizeText("Pyruvate ($\\text{C}_3\\text{H}_4\\text{O}_3$) is a..."),
    ).toBe("Pyruvate (C_3H_4O_3) is a...");
  });

  it("leaves plain prose untouched", () => {
    const plain = "This is a regular sentence with no LaTeX.";
    expect(normalizeText(plain)).toBe(plain);
  });

  it("leaves prose with literal dollar signs alone (currency)", () => {
    // No `_` or `^` inside the $...$ span, so the $ delimiters are kept.
    expect(normalizeText("This costs $50 today, not $100.")).toBe(
      "This costs $50 today, not $100.",
    );
  });

  it("returns empty string unchanged", () => {
    expect(normalizeText("")).toBe("");
  });
});
