"use client";

import Image from "next/image";
import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { HealthOverall, HealthResponse } from "@/lib/api";
import { StatusDot } from "./status-dot";

// Adaptive polling cadence. Streaming is the "user cares right now"
// signal — poll faster. Idle = background, cheap. A down status also
// reverts to the shorter cadence so recovery shows up promptly.
const POLL_ACTIVE_MS = 5_000;
const POLL_IDLE_MS = 60_000;
const POLL_DOWN_MS = 15_000;
const DEEP_MODE_HELPER_TIMEOUT_MS = 10_000;

type DotStatus = HealthOverall | "pending";

interface HeaderProps {
  deepMode: boolean;
  onDeepModeChange: (on: boolean) => void;
  onNewConversation?: () => void;
  canClearConversation?: boolean;
  /** True while a /chat response is streaming — bumps polling cadence. */
  streaming?: boolean;
  /** Receives every /health probe result; used by the demo-mode banner. */
  onHealth?: (health: HealthResponse | null) => void;
}

function onlineCount(h: HealthResponse | null): number {
  if (!h) return 0;
  return (["default", "deep", "max_rigor"] as const).reduce(
    (n, k) => n + (h[k] === "ok" ? 1 : 0),
    0,
  );
}

function statusLabel(status: DotStatus, h: HealthResponse | null): string {
  if (status === "pending") return "Checking backend status…";
  const count = onlineCount(h);
  if (status === "ok") return "All tiers online (3/3)";
  if (status === "down") return "Backend offline (0/3 tiers)";
  return `${count}/3 tiers online`;
}

export function Header({
  deepMode,
  onDeepModeChange,
  onNewConversation,
  canClearConversation = false,
  streaming = false,
  onHealth,
}: HeaderProps) {
  const [status, setStatus] = useState<DotStatus>("pending");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [showHelper, setShowHelper] = useState(true);
  const interactedRef = useRef(false);
  const streamingRef = useRef(streaming);
  const statusRef = useRef<DotStatus>(status);

  // Fade out the deep-mode helper text after 10s or on first toggle.
  useEffect(() => {
    const t = setTimeout(
      () => setShowHelper(false),
      DEEP_MODE_HELPER_TIMEOUT_MS,
    );
    return () => clearTimeout(t);
  }, []);

  // Keep refs fresh so the single self-rescheduling probe loop reads
  // the latest streaming / status without re-mounting its interval.
  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const probe = async () => {
      try {
        const res = await fetch("/api/health-proxy", { cache: "no-store" });
        const body = (await res.json()) as HealthResponse;
        if (cancelled) return;
        setHealth(body);
        setStatus(body.overall ?? "down");
        onHealth?.(body);
      } catch {
        if (cancelled) return;
        setHealth(null);
        setStatus("down");
        onHealth?.(null);
      }
      if (cancelled) return;
      const next = streamingRef.current
        ? POLL_ACTIVE_MS
        : statusRef.current === "down"
          ? POLL_DOWN_MS
          : POLL_IDLE_MS;
      timer = setTimeout(probe, next);
    };

    probe();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const handleToggle = (next: boolean) => {
    onDeepModeChange(next);
    if (!interactedRef.current) {
      interactedRef.current = true;
      setShowHelper(false);
    }
  };

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-3 sm:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <Image
          src="/branding/hbsu.png"
          alt="HBSU"
          width={40}
          height={40}
          priority
          title="Team from Homi Bhabha State University, Mumbai"
          className="shrink-0 rounded"
        />
        <div className="hidden min-w-0 flex-col leading-tight sm:flex">
          <span className="text-[17px] font-semibold tracking-tight text-gray-900">
            MetaboAgent
          </span>
          <span className="truncate text-[13px] text-gray-500">
            Biochem agent grounded in PubMed, KEGG, UniProt
          </span>
        </div>
        <span className="truncate text-[15px] font-semibold text-gray-900 sm:hidden">
          MetaboAgent
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-2 sm:gap-4">
        <div
          className="flex items-center gap-2"
          title={statusLabel(status, health)}
        >
          <StatusDot status={status} label={statusLabel(status, health)} />
          <span className="hidden text-sm text-gray-600 sm:inline">Backend</span>
        </div>

        <div className="relative flex items-center">
          <button
            type="button"
            onClick={() => handleToggle(!deepMode)}
            role="switch"
            aria-checked={deepMode}
            aria-label="Toggle deep mode"
            title={
              deepMode
                ? "Deep mode ON — 26B tier"
                : "Deep mode OFF — E4B default"
            }
            className="flex items-center gap-2 focus:outline-none"
          >
            <span className="hidden text-sm text-gray-600 sm:inline">Deep mode</span>
            <span
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                deepMode ? "bg-blue-600" : "bg-gray-200"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                  deepMode ? "translate-x-[18px]" : "translate-x-0.5"
                }`}
              />
            </span>
          </button>
          {showHelper && (
            <div className="pointer-events-none absolute right-0 top-full z-10 mt-2 w-[240px] rounded-md border border-gray-200 bg-white px-3 py-2 text-[12px] text-gray-600 shadow-sm">
              Deep mode routes to the 26B model. Slower, more thorough.
            </div>
          )}
        </div>

        {onNewConversation && (
          <button
            type="button"
            onClick={onNewConversation}
            disabled={!canClearConversation}
            aria-label="Start a new conversation"
            title="New conversation"
            className="flex h-8 w-8 items-center justify-center rounded-full text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
          >
            <Trash2 size={16} />
          </button>
        )}
      </div>
    </header>
  );
}
