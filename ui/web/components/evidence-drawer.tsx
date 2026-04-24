"use client";

import { Layers, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ToolActivity } from "@/lib/api";
import { extractCitations } from "@/lib/citations";
import type { PathwayData } from "@/lib/pathway";
import { EvidenceRail } from "./evidence-rail";

interface Props {
  toolActivity: ToolActivity[];
  pathway: PathwayData | null;
}

/**
 * Mobile-only evidence drawer: a floating Layers button at the
 * bottom-right (hidden on lg+ viewports) that opens a slide-in panel
 * holding the same EvidenceRail content. The desktop rail is always
 * visible at lg+; this drawer is the narrow-viewport equivalent.
 */
export function EvidenceDrawer({ toolActivity, pathway }: Props) {
  const [open, setOpen] = useState(false);
  const citationCount = extractCitations(toolActivity).length;
  const badgeCount = toolActivity.length + citationCount;

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {/* Floating toggle — hidden on lg+ where the rail is always visible. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open evidence panel"
        aria-expanded={open}
        className="fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400/60 lg:hidden"
      >
        <Layers size={20} />
        {badgeCount > 0 && (
          <span className="absolute -right-1 -top-1 flex min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1 text-[11px] font-semibold leading-5 text-white">
            {badgeCount > 99 ? "99+" : badgeCount}
          </span>
        )}
      </button>

      {/* Backdrop + drawer. Only active when open; rendered always so
          transitions work on open/close. */}
      <div
        onClick={() => setOpen(false)}
        className={`fixed inset-0 z-40 bg-gray-900/40 transition-opacity lg:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        aria-hidden={!open}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Evidence panel"
        className={`fixed inset-y-0 right-0 z-50 flex w-[88%] max-w-[400px] flex-col bg-white shadow-xl transition-transform lg:hidden ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4">
          <div className="flex items-center gap-2">
            <Layers size={16} className="text-gray-500" />
            <span className="text-[15px] font-semibold text-gray-900">
              Evidence
            </span>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close evidence panel"
            className="flex h-8 w-8 items-center justify-center rounded-full text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400/40"
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex-1 overflow-hidden">
          <EvidenceRail
            toolActivity={toolActivity}
            pathway={pathway}
            embedded
          />
        </div>
      </div>
    </>
  );
}
