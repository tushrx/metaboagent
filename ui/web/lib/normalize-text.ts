/**
 * Normalize raw LaTeX-flavoured fragments and chemistry notation that
 * Gemma 4 emits in chat prose, so the markdown renderer shows arrows,
 * Unicode subscripts/superscripts, Greek letters, and bare compound
 * names — not the raw source.
 *
 * Display math `$$...$$` and inline math `$...$` that contains real
 * math commands (\frac, \sum, \int, Greek letters, etc.) are LEFT
 * UNTOUCHED so that remark-math + rehype-katex can render them.
 *
 * "Simple chemistry" inside `$...$` (no \X commands beyond the simple
 * arrow set, or no \X at all) is treated as chat prose: dollar
 * wrappers stripped, sub/super converted, etc.
 *
 * A separate, narrower normalizer lives in `lib/pathway.ts`
 * (`normalizeArrows`) for the pathway-step parser. They overlap on
 * the arrow patterns by design — the pathway parser must stay
 * independent of the chat-display path.
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

// Commands that the chat-prose path handles itself (arrow conversions
// + \text collapse). Inside `$...$`, these don't promote a span to
// "math" — `$\rightarrow$` should still strip down to `→`. Anything
// outside this set is treated as KaTeX-bound math.
const SIMPLE_PROSE_COMMANDS = new Set([
  "text",
  "rightarrow",
  "leftarrow",
  "rightleftharpoons",
  "leftrightarrow",
  "longrightarrow",
  "Rightarrow",
  "to",
]);

// --- Greek letter map -------------------------------------------------
// Applied AFTER the arrow command pass. KaTeX handles Greek inside
// math spans natively; this map is for `\beta` that the model emits in
// PROSE outside any `$...$` wrapper.
const GREEK_REPLACEMENTS: ReadonlyArray<[RegExp, string]> = [
  [/\\alpha\b/g, "α"], [/\\Alpha\b/g, "Α"],
  [/\\beta\b/g, "β"], [/\\Beta\b/g, "Β"],
  [/\\gamma\b/g, "γ"], [/\\Gamma\b/g, "Γ"],
  [/\\delta\b/g, "δ"], [/\\Delta\b/g, "Δ"],
  [/\\epsilon\b/g, "ε"], [/\\Epsilon\b/g, "Ε"],
  [/\\theta\b/g, "θ"], [/\\Theta\b/g, "Θ"],
  [/\\lambda\b/g, "λ"], [/\\Lambda\b/g, "Λ"],
  [/\\mu\b/g, "μ"], [/\\Mu\b/g, "Μ"],
  [/\\rho\b/g, "ρ"], [/\\Rho\b/g, "Ρ"],
  [/\\sigma\b/g, "σ"], [/\\Sigma\b/g, "Σ"],
  [/\\pi\b/g, "π"], [/\\Pi\b/g, "Π"],
  [/\\phi\b/g, "φ"], [/\\Phi\b/g, "Φ"],
  [/\\omega\b/g, "ω"], [/\\Omega\b/g, "Ω"],
  [/\\tau\b/g, "τ"], [/\\Tau\b/g, "Τ"],
  [/\\kappa\b/g, "κ"], [/\\Kappa\b/g, "Κ"],
];

// --- Dollar-strip regexes ---------------------------------------------
// Math-like: spaces allowed, but inner span must contain at least one
// math marker. Catches reaction equations like
// "$Glucose → Glucose-6-phosphate$".
const DOLLAR_MATH_RE =
  /\$([A-Za-z0-9().+\-\s_^{}\[\]→⇌←↔⇒]*[_^→⇌←↔⇒][A-Za-z0-9().+\-\s_^{}\[\]→⇌←↔⇒]*)\$/g;

// Chemistry-shape: no spaces inside, length ≤ 30, must contain at
// least one letter. Brackets allowed for biochem concentration like
// $[S]$, $[NADH]$.
const DOLLAR_CHEM_RE =
  /\$([A-Za-z0-9\-+=()_^{}\[\]→⇌←↔⇒]{1,30})\$/g;

// Charge-only spans like $+2$, $-1$, $+3$. Length 2-4 (sign + 1-3
// digits). Currency stays safe because `$50` and `$100` don't start
// with +/−.
const DOLLAR_CHARGE_RE = /\$([+\-][0-9]{1,3})\$/g;

// --- Sub/superscript regexes ------------------------------------------
const SUB_RE = /([A-Za-z0-9)\]])_(\{[^}]+\}|\d+|[A-Za-z])/g;
const SUP_RE =
  /([A-Za-z0-9)\]])\^(\{[^}]+\}|\d+[+\-=]?|[+\-=]|[A-Za-z])/g;

// --- Unicode maps ------------------------------------------------------
const SUB_MAP: Record<string, string> = {
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
  "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
  "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
  a: "ₐ", e: "ₑ", h: "ₕ", i: "ᵢ", j: "ⱼ",
  k: "ₖ", l: "ₗ", m: "ₘ", n: "ₙ", o: "ₒ",
  p: "ₚ", r: "ᵣ", s: "ₛ", t: "ₜ", u: "ᵤ",
  v: "ᵥ", x: "ₓ",
};

const SUP_MAP: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
  "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
  n: "ⁿ", i: "ⁱ",
};

function mapAllOrNull(
  content: string,
  map: Record<string, string>,
): string | null {
  let chars = content;
  if (chars.startsWith("{") && chars.endsWith("}")) chars = chars.slice(1, -1);
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

/**
 * Decide whether the contents of a `$...$` span should be treated as
 * KaTeX-bound math. True when the span contains any `\command` outside
 * `SIMPLE_PROSE_COMMANDS` (Greek letters, \frac, \sum, \int, etc.).
 */
function isMathSpan(content: string): boolean {
  const re = /\\([A-Za-z]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (!SIMPLE_PROSE_COMMANDS.has(m[1])) return true;
  }
  return false;
}

interface Segment {
  math: boolean;
  text: string;
}

/**
 * Walk the input and split it into math segments (which are left
 * untouched for KaTeX) and prose segments (which run through the
 * normalization passes). Display math `$$...$$` is always math.
 * Inline `$...$` is math only if `isMathSpan` says so — otherwise
 * it's prose with a chemistry-shaped dollar wrapper.
 *
 * Unmatched lone `$` characters stay in their prose segment.
 */
function splitForMath(input: string): Segment[] {
  const out: Segment[] = [];
  let buf = "";
  let i = 0;

  const flushProse = () => {
    if (buf.length > 0) {
      out.push({ math: false, text: buf });
      buf = "";
    }
  };

  while (i < input.length) {
    // Display math $$...$$ (always math).
    if (input[i] === "$" && input[i + 1] === "$") {
      const close = input.indexOf("$$", i + 2);
      if (close !== -1) {
        flushProse();
        out.push({ math: true, text: input.slice(i, close + 2) });
        i = close + 2;
        continue;
      }
    }

    // Inline $...$ — only "math" if the contents trigger isMathSpan.
    if (input[i] === "$") {
      let close = -1;
      for (let j = i + 1; j < input.length; j++) {
        if (input[j] === "$" && input[j - 1] !== "\\") {
          close = j;
          break;
        }
      }
      if (close !== -1) {
        const content = input.slice(i + 1, close);
        if (isMathSpan(content)) {
          flushProse();
          out.push({ math: true, text: input.slice(i, close + 1) });
          i = close + 1;
          continue;
        }
        // Not math — fall through to buffer the chars normally.
      }
    }

    buf += input[i];
    i++;
  }

  flushProse();
  return out;
}

function applyProsePasses(input: string): string {
  let s = input;

  // 1. HTML entity arrow.
  s = s.replace(/&rarr;/gi, "→");

  // 2. LaTeX command -> unicode glyph (longest-prefix-first).
  for (const [re, glyph] of COMMAND_REPLACEMENTS) {
    s = s.replace(re, glyph);
  }

  // 3. Collapse \text{X} -> X.
  s = s.replace(/\\text\{([^{}]*)\}/g, "$1");

  // 4. Greek letter map -> unicode glyph.
  for (const [re, glyph] of GREEK_REPLACEMENTS) {
    s = s.replace(re, glyph);
  }

  // 5. Math-like $...$ strip (spaces allowed, marker required).
  s = s.replace(DOLLAR_MATH_RE, "$1");

  // 6. Chemistry-shape $...$ strip (no spaces, ≤30 chars, has letter).
  s = s.replace(DOLLAR_CHEM_RE, (match, inner) => {
    return /[A-Za-z]/.test(inner) ? inner : match;
  });

  // 7. Charge-only $...$ strip ($+2$, $-1$).
  s = s.replace(DOLLAR_CHARGE_RE, "$1");

  // 8. Subscript: every-char-mapped -> Unicode, else placeholder.
  s = s.replace(SUB_RE, (_match, base, content) => {
    const unicode = mapAllOrNull(content, SUB_MAP);
    if (unicode !== null) return base + unicode;
    return `${base}{{SUB:${stripBraces(content)}}}`;
  });

  // 9. Superscript: same, but with the conservative SUP_MAP.
  s = s.replace(SUP_RE, (_match, base, content) => {
    const unicode = mapAllOrNull(content, SUP_MAP);
    if (unicode !== null) return base + unicode;
    return `${base}{{SUP:${stripBraces(content)}}}`;
  });

  return s;
}

export function normalizeText(input: string): string {
  if (!input) return input;
  const segments = splitForMath(input);
  return segments
    .map((seg) => (seg.math ? seg.text : applyProsePasses(seg.text)))
    .join("");
}
