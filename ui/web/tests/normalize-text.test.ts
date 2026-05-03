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

  // --- \text{} collapse + downstream subscript/superscript -----------

  it("collapses $\\text{H}_2\\text{O}$ to H₂O via subscript pass", () => {
    expect(normalizeText("Formula: $\\text{H}_2\\text{O}$")).toBe(
      "Formula: H₂O",
    );
  });

  it("collapses $\\text{Ca}^{2+}$ to Ca²⁺ via superscript pass", () => {
    expect(normalizeText("Charge: $\\text{Ca}^{2+}$")).toBe("Charge: Ca²⁺");
  });

  it("handles compound $\\text{C}_3\\text{H}_4\\text{O}_3$ → C₃H₄O₃", () => {
    expect(
      normalizeText("Pyruvate ($\\text{C}_3\\text{H}_4\\text{O}_3$) is a..."),
    ).toBe("Pyruvate (C₃H₄O₃) is a...");
  });

  it("handles single-species $\\text{C}_3$ → C₃", () => {
    expect(normalizeText("$\\text{C}_3$")).toBe("C₃");
  });

  // --- $...$ wrapping reaction equations + chemistry shapes ----------

  it("strips $...$ around a reaction equation containing an arrow", () => {
    expect(normalizeText("$Glucose → Glucose-6-phosphate$")).toBe(
      "Glucose → Glucose-6-phosphate",
    );
  });

  it("strips $C=C$ (double bond)", () => {
    expect(normalizeText("the $C=C$ double bond")).toBe("the C=C double bond");
  });

  it("strips $C-C$ (single bond)", () => {
    expect(normalizeText("a $C-C$ bond")).toBe("a C-C bond");
  });

  it("strips $H_2(g)$ (state-of-matter notation) and applies subscript", () => {
    expect(normalizeText("$H_2(g)$ at 25°C")).toBe("H₂(g) at 25°C");
  });

  it("strips $Na+$ (charge without ^)", () => {
    expect(normalizeText("$Na+$ ion")).toBe("Na+ ion");
  });

  it("strips $(CH_3)_2$ and applies subscript to both groups", () => {
    expect(normalizeText("methyl group $(CH_3)_2$ here")).toBe(
      "methyl group (CH₃)₂ here",
    );
  });

  it("strips $NADH$ (plain compound name)", () => {
    expect(normalizeText("$NADH$ is a cofactor.")).toBe("NADH is a cofactor.");
  });

  it("strips $NAD^+$ and converts ^+ to ⁺", () => {
    expect(normalizeText("$NAD^+$")).toBe("NAD⁺");
  });

  // --- subscript Unicode ---------------------------------------------

  it("converts bare C_2 → C₂", () => {
    expect(normalizeText("just C_2 here")).toBe("just C₂ here");
  });

  it("converts glucose C_6H_12O_6 → C₆H₁₂O₆", () => {
    expect(normalizeText("glucose: C_6H_12O_6")).toBe("glucose: C₆H₁₂O₆");
  });

  it("converts braced C_{12} → C₁₂", () => {
    expect(normalizeText("C_{12}")).toBe("C₁₂");
  });

  it("converts braced C_{122} → C₁₂₂", () => {
    expect(normalizeText("C_{122}")).toBe("C₁₂₂");
  });

  // --- subscript HTML fallback ---------------------------------------

  it("falls back to {{SUB:M}} for K_M (uppercase letter)", () => {
    expect(normalizeText("K_M value")).toBe("K{{SUB:M}} value");
  });

  it("falls back to {{SUB:d}} for K_d (lowercase outside SUB_MAP)", () => {
    expect(normalizeText("the K_d constant")).toBe(
      "the K{{SUB:d}} constant",
    );
  });

  it("falls back to {{SUB:cat}} for K_{cat} (multi-letter braces)", () => {
    expect(normalizeText("K_{cat}/K_M")).toBe("K{{SUB:cat}}/K{{SUB:M}}");
  });

  // --- superscript Unicode -------------------------------------------

  it("converts bare Ca^{2+} → Ca²⁺", () => {
    expect(normalizeText("Ca^{2+} ion")).toBe("Ca²⁺ ion");
  });

  it("converts Al^{3+} → Al³⁺", () => {
    expect(normalizeText("Al^{3+}")).toBe("Al³⁺");
  });

  // --- superscript HTML fallback -------------------------------------

  it("falls back to {{SUP:abc}} for X^{abc} (letters outside SUP_MAP)", () => {
    expect(normalizeText("X^{abc}")).toBe("X{{SUP:abc}}");
  });

  // --- combined: dollar-strip + sub/super in one expression ----------

  it("$Ca^{2+}$ ion → Ca²⁺ ion (combined dollar+sup)", () => {
    expect(normalizeText("$Ca^{2+}$ ion")).toBe("Ca²⁺ ion");
  });

  it("$K_M$ value → K{{SUB:M}} value (combined dollar+sub-fallback)", () => {
    expect(normalizeText("$K_M$ value")).toBe("K{{SUB:M}} value");
  });

  // --- safety: prose with literal dollar signs / no LaTeX ------------

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

  it("leaves '$50' (number-only span) untouched", () => {
    expect(normalizeText("price: $50 each")).toBe("price: $50 each");
  });

  it("returns empty string unchanged", () => {
    expect(normalizeText("")).toBe("");
  });
});
