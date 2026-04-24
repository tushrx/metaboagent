"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";
import { Wrench, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import type { ToolActivity } from "@/lib/api";

export interface EvidenceRailHandle {
  /** Scroll a specific tool-activity card into view. */
  scrollToToolCall: (toolCallId: string) => void;
}

interface Props {
  toolActivity: ToolActivity[];
  /** If true, the rail is inside the mobile drawer; skip the desktop-only hide. */
  embedded?: boolean;
}

export const EvidenceRail = forwardRef<EvidenceRailHandle, Props>(
  function EvidenceRail({ toolActivity, embedded = false }, ref) {
    const listRef = useRef<HTMLOListElement>(null);

    useImperativeHandle(ref, () => ({
      scrollToToolCall(id: string) {
        const el = listRef.current?.querySelector<HTMLElement>(
          `[data-tool-id="${CSS.escape(id)}"]`,
        );
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        el?.classList.add("ring-2", "ring-blue-400");
        setTimeout(
          () => el?.classList.remove("ring-2", "ring-blue-400"),
          1200,
        );
      },
    }));

    const containerClass = embedded
      ? "flex h-full w-full flex-col bg-white"
      : "hidden h-full w-[360px] shrink-0 flex-col border-l border-gray-200 bg-gray-50 lg:flex";

    return (
      <aside
        className={containerClass}
        role="complementary"
        aria-label="Evidence panel"
      >
        <div className="flex-1 overflow-y-auto">
          <ToolsRunSection toolActivity={toolActivity} listRef={listRef} />
          <CitationsSection />
          <PathwaySection />
        </div>
      </aside>
    );
  },
);

// --- Tools Run -----------------------------------------------------------

function ToolsRunSection({
  toolActivity,
  listRef,
}: {
  toolActivity: ToolActivity[];
  listRef: React.RefObject<HTMLOListElement>;
}) {
  return (
    <section className="border-b border-gray-200 px-4 py-3">
      <header className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
          Tools run
        </h3>
        <span className="text-[11px] text-gray-400">
          {toolActivity.length > 0 ? toolActivity.length : null}
        </span>
      </header>

      {toolActivity.length === 0 ? (
        <p className="text-sm text-gray-400">
          No tools called yet. Ask something and the agent&apos;s database
          lookups will appear here.
        </p>
      ) : (
        <ol ref={listRef} className="flex flex-col gap-2">
          {toolActivity.map((a) => (
            <li key={a.id} data-tool-id={a.id}>
              <ToolActivityCard activity={a} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ToolActivityCard({ activity }: { activity: ToolActivity }) {
  const args = argsSummary(activity.args);
  const duration = formatDuration(activity);

  return (
    <article
      role="article"
      aria-label={`Tool ${activity.name}, status ${activity.status}`}
      className="rounded-lg border border-gray-200 bg-white p-3 transition-shadow hover:shadow-sm"
    >
      <header className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Wrench size={14} className="shrink-0 text-gray-500" />
          <span className="truncate font-mono text-[13px] font-medium text-gray-900">
            {activity.name}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge status={activity.status} />
          <span className="font-mono text-[11px] text-gray-500">{duration}</span>
        </div>
      </header>
      {args && (
        <p className="mt-1.5 truncate font-mono text-[11px] text-gray-500">
          {args}
        </p>
      )}
      {activity.error && (
        <p className="mt-1.5 text-[12px] text-red-600">{activity.error}</p>
      )}
    </article>
  );
}

function StatusBadge({
  status,
}: {
  status: ToolActivity["status"];
}) {
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
        <Loader2 size={10} className="animate-spin" /> running
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700">
        <AlertCircle size={10} /> error
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-1.5 py-0.5 text-[10px] font-medium text-green-700">
      <CheckCircle2 size={10} /> done
    </span>
  );
}

function formatDuration(a: ToolActivity): string {
  if (a.status === "running") {
    const elapsed = (Date.now() - a.startedAt) / 1000;
    return `${elapsed.toFixed(1)}s…`;
  }
  if (a.endedAt) {
    return `${((a.endedAt - a.startedAt) / 1000).toFixed(1)}s`;
  }
  return "—";
}

function argsSummary(args: Record<string, unknown>): string {
  const keys = Object.keys(args);
  if (keys.length === 0) return "";
  const parts = keys.slice(0, 3).map((k) => {
    const v = args[k];
    const vs =
      typeof v === "string" ? v : JSON.stringify(v);
    return `${k}=${vs}`;
  });
  const suffix = keys.length > 3 ? ` +${keys.length - 3} more` : "";
  return parts.join("  ") + suffix;
}

// --- Citations (populated in the next commit) ---------------------------

function CitationsSection() {
  return (
    <section className="border-b border-gray-200 px-4 py-3">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
        Citations
      </h3>
      <p className="text-sm text-gray-400">
        Citations extracted from tool results will appear here.
      </p>
    </section>
  );
}

// --- Pathway (Phase 5.4) -------------------------------------------------

function PathwaySection() {
  return (
    <section className="px-4 py-3">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
        Pathway
      </h3>
      <p className="text-sm text-gray-400">
        Pathway visualization arrives in 5.4 when the agent emits pathway steps.
      </p>
    </section>
  );
}
