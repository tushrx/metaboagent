/**
 * Convert chemistry-notation placeholders emitted by `normalizeText`
 * into real React <sub>/<sup> elements at render time.
 *
 * Why placeholders rather than raw HTML: the chat renderer uses
 * react-markdown, which by default escapes raw HTML in markdown
 * source. Pulling in `rehype-raw` to enable raw HTML adds ~50 kB to
 * First Load JS (a full HTML5 parser via parse5). We avoid that by
 * having the normalizer emit `{{SUB:M}}` / `{{SUP:abc}}` strings — a
 * cheap pre-AST sentinel that we then walk through here.
 *
 * `processChildren` is the entry point that the markdown components
 * call. It walks any `children` value from react-markdown — which is
 * normally a string, an array of mixed strings and elements, or null —
 * and rewrites string children that contain placeholders into
 * fragments with real <sub>/<sup> nodes.
 */
import { Fragment, type ReactNode } from "react";

const PLACEHOLDER_RE = /\{\{(SUB|SUP):([^}]+)\}\}/g;

export function renderTextWithPlaceholders(text: string): ReactNode {
  if (!text || !text.includes("{{")) return text;

  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;

  // Reset .lastIndex defensively — the regex is module-scope and shared.
  PLACEHOLDER_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = PLACEHOLDER_RE.exec(text)) !== null) {
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index));
    if (m[1] === "SUB") {
      parts.push(<sub key={key++}>{m[2]}</sub>);
    } else {
      parts.push(<sup key={key++}>{m[2]}</sup>);
    }
    lastIndex = m.index + m[0].length;
  }

  if (lastIndex === 0) return text;
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return <Fragment>{parts}</Fragment>;
}

/**
 * Walk react-markdown's `children` and replace string children that
 * contain placeholders with real <sub>/<sup> React nodes. Non-string
 * children pass through unchanged so nested markdown (e.g. inline
 * <code>, <strong>) is preserved.
 */
export function processChildren(children: ReactNode): ReactNode {
  if (children == null) return children;
  if (typeof children === "string") {
    return renderTextWithPlaceholders(children);
  }
  if (Array.isArray(children)) {
    return children.map((child, i) => {
      if (typeof child === "string") {
        const rendered = renderTextWithPlaceholders(child);
        // Strings inside an array don't need keys; fragments returned
        // by the rendered helper do — wrap to give it a stable key.
        if (typeof rendered === "string") return rendered;
        return <Fragment key={`pl-${i}`}>{rendered}</Fragment>;
      }
      return child;
    });
  }
  return children;
}
