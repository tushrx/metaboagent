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

// Order matters: longer prefixes must replace before shorter ones, e.g.
// \longrightarrow must fire before \rightarrow, otherwise we'd produce
// `\long→` mid-stream.
const COMMAND_REPLACEMENTS: ReadonlyArray<[RegExp, string]> = [
  [/\\rightleftharpoons\b/g, "⇌"],
  [/\\leftrightarrow\b/g, "↔"],
  [/\\longrightarrow\b/g, "→"],
  [/\\Rightarrow\b/g, "⇒"],
  [/\\rightarrow\b/g, "→"],
  [/\\leftarrow\b/g, "←"],
  [/\\to\b/g, "→"],
];

// The math-like dollar-strip fires on spans that contain at least one
// of these "math marker" characters. After the command pass these are
// the unicode equivalents — we do NOT need to keep the LaTeX command
// names in this set.
const MATH_MARKER_CHARS = "_^→⇌←↔⇒";
const MATH_INNER_CHARS = "A-Za-z0-9().+\\-\\s_^{}→⇌←↔⇒";

const DOLLAR_MATH_RE = new RegExp(
  `\\$([${MATH_INNER_CHARS}]*[${MATH_MARKER_CHARS}][${MATH_INNER_CHARS}]*)\\$`,
  "g",
);

// "Plain-name" dollar-strip: short letter-or-digit identifier wrapped in
// $...$ (e.g. $NADH$, $ATP$, $NAD+$). Spaces are intentionally excluded
// from the char class to keep currency prose like "$50 to $100" safe —
// a permissive class with spaces would match the `50 to ` span between
// the two dollar signs. We require at least one letter inside to rule
// out `$50$`.
const DOLLAR_NAME_RE = /\$([A-Za-z0-9+\-]{1,12})\$/g;

export function normalizeText(input: string): string {
  if (!input) return input;

  let s = input;

  // 1. HTML entity arrow.
  s = s.replace(/&rarr;/gi, "→");

  // 2. LaTeX command -> unicode glyph (longest-prefix-first; see comment
  //    on COMMAND_REPLACEMENTS).
  for (const [re, glyph] of COMMAND_REPLACEMENTS) {
    s = s.replace(re, glyph);
  }

  // 3. Collapse \text{X} -> X. Handles compound chemistry like
  //    $\text{C}_3\text{H}_4\text{O}_3$ where each species is wrapped.
  s = s.replace(/\\text\{([^{}]*)\}/g, "$1");

  // 4. Strip $...$ for spans that look like math notation (contain a
  //    sub/superscript or arrow marker). Catches reaction equations:
  //    "$Glucose → Glucose-6-phosphate$" -> "Glucose → Glucose-6-phosphate".
  s = s.replace(DOLLAR_MATH_RE, "$1");

  // 5. Strip $...$ for plain compound names (e.g. $NADH$ -> NADH).
  //    Letter-or-digit only, length-capped, must contain at least one
  //    letter. Currency stays safe via the no-spaces rule above.
  s = s.replace(DOLLAR_NAME_RE, (match, inner) => {
    return /[A-Za-z]/.test(inner) ? inner : match;
  });

  return s;
}
