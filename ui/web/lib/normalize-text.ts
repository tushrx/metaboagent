/**
 * Normalize raw LaTeX-flavoured fragments and chemistry notation that
 * Gemma 4 emits in chat prose, so the markdown renderer shows arrows,
 * Unicode subscripts/superscripts, and bare compound names — not the
 * raw source. We intentionally do NOT pull in a math renderer (KaTeX);
 * chemistry notation in our domain is well covered by Unicode glyphs
 * with HTML <sub>/<sup> as a fallback.
 *
 * A separate, narrower normalizer lives in `lib/pathway.ts`
 * (`normalizeArrows`) for the pathway-step parser. They overlap on the
 * arrow patterns by design — the pathway parser must stay independent
 * of the chat-display path.
 *
 * Pass order matters; see the inline comments in `normalizeText`.
 */

// --- LaTeX command -> unicode glyph -----------------------------------
// Order matters: longer prefixes must replace before shorter ones, e.g.
// \longrightarrow must fire before \rightarrow.
const COMMAND_REPLACEMENTS: ReadonlyArray<[RegExp, string]> = [
  [/\\rightleftharpoons\b/g, "⇌"],
  [/\\leftrightarrow\b/g, "↔"],
  [/\\longrightarrow\b/g, "→"],
  [/\\Rightarrow\b/g, "⇒"],
  [/\\rightarrow\b/g, "→"],
  [/\\leftarrow\b/g, "←"],
  [/\\to\b/g, "→"],
];

// --- Dollar-strip regexes ---------------------------------------------
// Math-like: spaces allowed, but inner span must contain at least one
// math marker (sub/super/arrow). Catches reaction equations like
// "$Glucose → Glucose-6-phosphate$".
const DOLLAR_MATH_RE =
  /\$([A-Za-z0-9().+\-\s_^{}→⇌←↔⇒]*[_^→⇌←↔⇒][A-Za-z0-9().+\-\s_^{}→⇌←↔⇒]*)\$/g;

// Chemistry-shape: no spaces inside, length ≤ 30, must contain at
// least one letter. Catches $C=C$, $H_2(g)$, $Na+$, $(CH_3)_2$, $NADH$.
// No-spaces is what protects "$50 to $100" — the inner span there has
// spaces and won't match.
const DOLLAR_CHEM_RE = /\$([A-Za-z0-9\-+=()_^{}→⇌←↔⇒]{1,30})\$/g;

// --- Sub/superscript regexes ------------------------------------------
// Base char (the thing being subscripted/superscripted) is a letter,
// digit, or closing bracket — covers H, 5, ), ].
// Content is either braced ({12}, {2+}, {cat}), bare digits (12), or a
// single letter. Superscript also allows bare "digits[+|-|=]?" for
// charges like ^2+ and bare sign ^+.
const SUB_RE = /([A-Za-z0-9)\]])_(\{[^}]+\}|\d+|[A-Za-z])/g;
const SUP_RE =
  /([A-Za-z0-9)\]])\^(\{[^}]+\}|\d+[+\-=]?|[+\-=]|[A-Za-z])/g;

// --- Unicode maps ------------------------------------------------------
// Subscript: digits + signs + parens + the "common subscript-able
// lowercase letters" per spec.
const SUB_MAP: Record<string, string> = {
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
  "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
  "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
  a: "ₐ", e: "ₑ", h: "ₕ", i: "ᵢ", j: "ⱼ",
  k: "ₖ", l: "ₗ", m: "ₘ", n: "ₙ", o: "ₒ",
  p: "ₚ", r: "ᵣ", s: "ₛ", t: "ₜ", u: "ᵤ",
  v: "ᵥ", x: "ₓ",
};

// Superscript: digits + signs + parens + n + i only. Letter set is
// intentionally smaller than subscript — Unicode superscripts for most
// letters exist but stack visually awkwardly when chained, so we let
// multi-letter exponents fall back to <sup>HTML</sup>.
const SUP_MAP: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
  "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
  n: "ⁿ", i: "ⁱ",
};

/**
 * Try to map every character of `content` through `map`. Returns the
 * concatenated unicode string if every char has a mapping; null
 * otherwise (signal to caller that HTML fallback is needed).
 */
function mapAllOrNull(
  content: string,
  map: Record<string, string>,
): string | null {
  // Strip { } if the content is brace-wrapped.
  let chars = content;
  if (chars.startsWith("{") && chars.endsWith("}")) {
    chars = chars.slice(1, -1);
  }
  if (chars.length === 0) return null;
  const out: string[] = [];
  for (const c of chars) {
    const mapped = map[c];
    if (mapped === undefined) return null;
    out.push(mapped);
  }
  return out.join("");
}

function stripBraces(s: string): string {
  if (s.startsWith("{") && s.endsWith("}")) return s.slice(1, -1);
  return s;
}

export function normalizeText(input: string): string {
  if (!input) return input;

  let s = input;

  // 1. HTML entity arrow.
  s = s.replace(/&rarr;/gi, "→");

  // 2. LaTeX command -> unicode glyph (longest-prefix-first).
  for (const [re, glyph] of COMMAND_REPLACEMENTS) {
    s = s.replace(re, glyph);
  }

  // 3. Collapse \text{X} -> X. Handles compound chemistry like
  //    $\text{C}_3\text{H}_4\text{O}_3$ where each species is wrapped.
  s = s.replace(/\\text\{([^{}]*)\}/g, "$1");

  // 4. Math-like $...$ strip (spaces allowed, marker required). Catches
  //    reaction equations: "$Glucose → Glucose-6-phosphate$".
  s = s.replace(DOLLAR_MATH_RE, "$1");

  // 5. Chemistry-shape $...$ strip (no spaces, ≤30 chars, has letter).
  //    Catches $C=C$, $C-C$, $Na+$, $(CH_3)_2$, $NADH$.
  s = s.replace(DOLLAR_CHEM_RE, (match, inner) => {
    return /[A-Za-z]/.test(inner) ? inner : match;
  });

  // 6. Subscript: every-char-mapped -> Unicode, else placeholder. The
  //    placeholder is parsed back into a React <sub> element by the
  //    chat renderer (see `lib/render-text.tsx`). We don't emit raw
  //    HTML here because react-markdown without rehype-raw would
  //    escape it — and pulling rehype-raw in adds ~50 kB to First
  //    Load JS for an HTML5 parser we don't otherwise need.
  s = s.replace(SUB_RE, (_match, base, content) => {
    const unicode = mapAllOrNull(content, SUB_MAP);
    if (unicode !== null) return base + unicode;
    return `${base}{{SUB:${stripBraces(content)}}}`;
  });

  // 7. Superscript: same, but with the conservative SUP_MAP.
  s = s.replace(SUP_RE, (_match, base, content) => {
    const unicode = mapAllOrNull(content, SUP_MAP);
    if (unicode !== null) return base + unicode;
    return `${base}{{SUP:${stripBraces(content)}}}`;
  });

  return s;
}
