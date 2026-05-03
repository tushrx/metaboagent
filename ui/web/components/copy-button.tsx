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
}

export function CopyButton({
  getText,
  className = "",
  ariaLabel = "Copy to clipboard",
}: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
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

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={ariaLabel}
      title={copied ? "Copied!" : "Copy"}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40 ${className}`}
    >
      {copied ? (
        <Check size={14} className="text-green-600" />
      ) : (
        <Copy size={14} />
      )}
    </button>
  );
}
