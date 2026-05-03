"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

interface Props {
  /**
   * Returns the text to copy. Lazy so callers can read from a ref's
   * `.textContent` at click-time (used for code blocks where we don't
   * want to walk the children prop tree).
   */
  getText: () => string;
  /** Tailwind classes for positioning (e.g. `absolute top-2 right-2`). */
  className?: string;
  ariaLabel?: string;
  /**
   * "default" = 28×28 (h-7 w-7) for message-level / code-block use.
   * "compact" = 20×20 (h-5 w-5) for inline use in tight rows
   * (citation cards). Tailwind can't reliably override h-7 from a
   * caller-supplied className because both classes have equal
   * specificity and CSS source order wins, so we expose the size as
   * an explicit prop.
   */
  size?: "default" | "compact";
}

export function CopyButton({
  getText,
  className = "",
  ariaLabel = "Copy to clipboard",
  size = "default",
}: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const text = getText();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silent fallback — clipboard API may be blocked in insecure
      // contexts. Don't surface error UI for a low-stakes action.
    }
  };

  const dim = size === "compact" ? "h-5 w-5" : "h-7 w-7";
  const iconSize = size === "compact" ? 11 : 14;

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={ariaLabel}
      title={copied ? "Copied!" : "Copy"}
      className={`inline-flex items-center justify-center rounded-md ${dim} text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40 ${className}`}
    >
      {copied ? (
        <Check size={iconSize} className="text-green-600" />
      ) : (
        <Copy size={iconSize} />
      )}
    </button>
  );
}
