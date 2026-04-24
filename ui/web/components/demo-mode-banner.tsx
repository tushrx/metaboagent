"use client";

import { Lock, X } from "lucide-react";
import { useState } from "react";

interface Props {
  visible: boolean;
}

/**
 * Shown above the chat when the backend reports `demo_mode: true` in
 * /health. The field doesn't exist in the backend yet (Phase 7); this
 * component stays dormant until then. Dismissible — one render per
 * session is enough.
 */
export function DemoModeBanner({ visible }: Props) {
  const [dismissed, setDismissed] = useState(false);
  if (!visible || dismissed) return null;

  return (
    <div
      role="status"
      aria-label="Demo mode active"
      className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-[13px] text-amber-900"
    >
      <div className="flex items-center gap-2">
        <Lock size={14} className="shrink-0 text-amber-700" />
        <span>
          Offline demo mode — external data fetches are disabled; using
          indexed corpus only.
        </span>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss demo-mode banner"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-amber-700 transition-colors hover:bg-amber-100 hover:text-amber-900"
      >
        <X size={14} />
      </button>
    </div>
  );
}
