/**
 * Normalize raw LaTeX-flavoured fragments that Gemma 4 occasionally
 * emits inside chat prose, so that the markdown renderer shows arrows
 * and chemistry notation rather than the raw source. We intentionally
 * do NOT pull in a math renderer (KaTeX); the chemistry our agent
 * surfaces is well covered by ASCII subscripts (`X_n`) once the LaTeX
 * scaffolding is stripped.
 *
 * A separate, narrower normalizer lives in `lib/pathway.ts`
 * (`normalizeArrows`) for the pathway-step parser. They overlap on the
 * arrow patterns by design — the pathway parser must stay independent
 * of the chat-display path.
 */
export function normalizeText(input: string): string {
  if (!input) return input;

  let s = input;

  // HTML entity arrow.
  s = s.replace(/&rarr;/gi, "→");

  // $\rightarrow$ — LaTeX inline arrow as Gemma 4 commonly emits it.
  s = s.replace(/\$\\rightarrow\$/g, "→");

  // \rightarrow — bare LaTeX arrow command (no $ delimiters).
  s = s.replace(/\\rightarrow\b/g, "→");

  // Collapse \text{X} → X. Handles compound chemistry like
  // $\text{C}_3\text{H}_4\text{O}_3$ where each species is wrapped.
  s = s.replace(/\\text\{([^{}]*)\}/g, "$1");

  // Strip outer $...$ for spans that are now plain ASCII sub/superscripts
  // (e.g. $C_3H_4O_3$ → C_3H_4O_3). Requires at least one `_` or `^`
  // inside, so prose with literal dollar signs (currency, code) is left
  // alone.
  s = s.replace(
    /\$([A-Za-z0-9().+\-\s_^→{}]*[_^][A-Za-z0-9().+\-\s_^→{}]*)\$/g,
    "$1",
  );

  return s;
}
