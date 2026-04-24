"use client";

import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  Wrench,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ExternalLink,
} from "lucide-react";
import type { ToolActivity } from "@/lib/api";
import {
  type Citation,
  type CitationKind,
  citationLabel,
  extractCitations,
  groupCitations,
} from "@/lib/citations";
import type { PathwayData } from "@/lib/pathway";
import { PathwayDiagram } from "./pathway-diagram";

export interface EvidenceRailHandle {
  /** Scroll a specific tool-activity card into view. */
  scrollToToolCall: (toolCallId: string) => void;
}

interface Props {
  toolActivity: ToolActivity[];
  pathway: PathwayData | null;
  /** If true, the rail is inside the mobile drawer; skip the desktop-only hide. */
  embedded?: boolean;
}

export const EvidenceRail = forwardRef<EvidenceRailHandle, Props>(
  function EvidenceRail({ toolActivity, pathway, embedded = false }, ref) {
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

    const citations = useMemo(
      () => extractCitations(toolActivity),
      [toolActivity],
    );

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
          <CitationsSection citations={citations} />
          <PathwaySection pathway={pathway} />
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
  const [expanded, setExpanded] = useState(false);
  const args = argsSummary(activity.args);
  const duration = formatDuration(activity);
  const contentId = `tool-activity-${activity.id}`;

  return (
    <article
      role="article"
      aria-label={`Tool ${activity.name}, status ${activity.status}`}
      className="rounded-lg border border-gray-200 bg-white transition-shadow hover:shadow-sm"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls={contentId}
        className="flex w-full items-center justify-between gap-2 rounded-lg p-3 text-left focus:outline-none focus:ring-2 focus:ring-blue-400/40"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <Wrench size={14} className="shrink-0 text-gray-500" />
            <span className="truncate font-mono text-[13px] font-medium text-gray-900">
              {activity.name}
            </span>
          </div>
          {args && (
            <p className="truncate font-mono text-[11px] text-gray-500">
              {args}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge status={activity.status} />
          <span className="font-mono text-[11px] text-gray-500">{duration}</span>
          {expanded ? (
            <ChevronUp size={14} className="text-gray-400" />
          ) : (
            <ChevronDown size={14} className="text-gray-400" />
          )}
        </div>
      </button>

      {expanded && (
        <div
          id={contentId}
          className="border-t border-gray-100 px-3 py-2.5"
        >
          <div className="mb-2">
            <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              Args
            </h4>
            <pre className="max-h-40 overflow-auto rounded bg-gray-50 p-2 font-mono text-[11px] leading-relaxed text-gray-800">
              {JSON.stringify(activity.args, null, 2)}
            </pre>
          </div>

          {activity.status === "running" && (
            <p className="text-[12px] text-gray-500">
              Waiting for result…
            </p>
          )}

          {activity.status === "done" && activity.result !== undefined && (
            <div>
              <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                Result
              </h4>
              <pre className="max-h-64 overflow-auto rounded bg-gray-50 p-2 font-mono text-[11px] leading-relaxed text-gray-800 whitespace-pre-wrap break-words">
                {formatResult(activity.result)}
              </pre>
            </div>
          )}

          {activity.status === "error" && activity.error && (
            <div>
              <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-red-600">
                Error
              </h4>
              <p className="text-[12px] text-red-700">{activity.error}</p>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function formatResult(result: unknown): string {
  if (typeof result === "string") {
    // If it parses as JSON, pretty-print; else show raw.
    try {
      const parsed = JSON.parse(result);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return result;
    }
  }
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
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

// --- Citations -----------------------------------------------------------

function CitationsSection({ citations }: { citations: Citation[] }) {
  const groups = useMemo(() => groupCitations(citations), [citations]);
  return (
    <section className="border-b border-gray-200 px-4 py-3">
      <header className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
          Citations
        </h3>
        <span className="text-[11px] text-gray-400">
          {citations.length > 0 ? citations.length : null}
        </span>
      </header>
      {citations.length === 0 ? (
        <p className="text-sm text-gray-400">
          Citations from PubMed, KEGG, UniProt, and ChEBI will show up here
          as tools return them.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {groups.map(([kind, items]) => (
            <CitationGroup key={kind} kind={kind} items={items} />
          ))}
        </div>
      )}
    </section>
  );
}

function CitationGroup({
  kind,
  items,
}: {
  kind: CitationKind;
  items: Citation[];
}) {
  return (
    <div>
      <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
        {citationLabel(kind)} · {items.length}
      </h4>
      <ul className="flex flex-col gap-1">
        {items.map((c) => (
          <li key={`${c.kind}-${c.id}`}>
            <CitationRow citation={c} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function CitationRow({ citation }: { citation: Citation }) {
  const sourceLabel =
    citation.provenance.length === 1
      ? `from ${citation.provenance[0]}`
      : `seen in ${citation.provenance.length} tools`;

  return (
    <a
      href={citation.url}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`Open ${citation.id} on ${hostOf(citation.url)}, opens in new tab`}
      title={citation.provenance.join(", ")}
      className="group flex items-center justify-between gap-2 rounded-md border border-gray-200 bg-white px-2 py-1.5 transition-colors hover:border-blue-300 hover:bg-blue-50"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide text-gray-700 group-hover:bg-blue-100 group-hover:text-blue-800">
          {citationLabel(citation.kind)}
        </span>
        <span className="truncate font-mono text-[12px] text-gray-900">
          {citation.id}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <span className="text-[10px] text-gray-400">{sourceLabel}</span>
        <ExternalLink
          size={12}
          className="text-gray-400 group-hover:text-blue-600"
        />
      </div>
    </a>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "external";
  }
}

// --- Pathway -------------------------------------------------------------

function PathwaySection({ pathway }: { pathway: PathwayData | null }) {
  return (
    <section className="px-4 py-3">
      <header className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
          Pathway
        </h3>
        <span className="text-[11px] text-gray-400">
          {pathway && pathway.steps.length > 0 ? pathway.steps.length : null}
        </span>
      </header>
      <PathwayDiagram pathway={pathway} />
    </section>
  );
}
