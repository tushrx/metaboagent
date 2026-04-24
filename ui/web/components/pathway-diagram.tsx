"use client";

import { useEffect, useRef, useState } from "react";
import type { PathwayData } from "@/lib/pathway";
import { pathwayToMermaid } from "@/lib/pathway-to-mermaid";

interface Props {
  pathway: PathwayData | null;
}

type RenderState =
  | { kind: "empty" }
  | { kind: "rendering"; source: string }
  | { kind: "ready"; svg: string; source: string }
  | { kind: "error"; message: string; source: string };

let mermaidInitialized = false;

/**
 * Lazy-load mermaid on first non-null pathway. Full bundle is ~500 kB
 * gzipped — we never pay for it if no pathway ever arrives.
 */
async function loadMermaid() {
  const mod = await import("mermaid");
  const mermaid = mod.default;
  if (!mermaidInitialized) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "default",
      flowchart: { useMaxWidth: true, htmlLabels: true },
    });
    mermaidInitialized = true;
  }
  return mermaid;
}

export function PathwayDiagram({ pathway }: Props) {
  const [state, setState] = useState<RenderState>({ kind: "empty" });
  // Each render gets a unique id so mermaid doesn't collide.
  const idCounter = useRef(0);

  useEffect(() => {
    let cancelled = false;

    if (!pathway || pathway.steps.length === 0) {
      setState({ kind: "empty" });
      return;
    }

    const source = pathwayToMermaid(pathway);
    setState({ kind: "rendering", source });

    (async () => {
      try {
        const mermaid = await loadMermaid();
        const id = `pathway-${++idCounter.current}`;
        const { svg } = await mermaid.render(id, source);
        if (!cancelled) setState({ kind: "ready", svg, source });
      } catch (err) {
        console.error("mermaid render failed:", err);
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
            source,
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pathway]);

  if (state.kind === "empty") {
    return (
      <p className="text-sm text-gray-400">
        Pathway appears here when the agent proposes reaction steps.
      </p>
    );
  }

  if (state.kind === "rendering") {
    return (
      <p className="text-sm text-gray-500">
        <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-blue-400" />
        Rendering pathway diagram…
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <div>
        <p className="mb-2 text-sm text-red-600">
          Couldn&apos;t render the pathway diagram. Here&apos;s the source:
        </p>
        <pre className="overflow-auto rounded bg-gray-50 p-2 font-mono text-[11px] leading-relaxed text-gray-800">
          {state.source}
        </pre>
        <p className="mt-2 text-[11px] text-gray-500">{state.message}</p>
      </div>
    );
  }

  // state.kind === "ready"
  const stepCount = pathway?.steps.length ?? 0;
  return (
    <div>
      {/* mermaid emits sanitized SVG when securityLevel = "strict". */}
      <div
        className="pathway-svg overflow-x-auto"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: state.svg }}
      />
      <p className="mt-2 text-[11px] text-gray-500">
        {stepCount} step{stepCount === 1 ? "" : "s"} extracted from assistant reply
      </p>
    </div>
  );
}
