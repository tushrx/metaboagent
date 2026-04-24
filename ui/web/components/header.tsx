"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import type { HealthOverall, HealthResponse } from "@/lib/api";
import { StatusDot } from "./status-dot";

const POLL_INTERVAL_MS = 15_000;

type DotStatus = HealthOverall | "pending";

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

export function Header() {
  const [status, setStatus] = useState<DotStatus>("pending");
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function probe() {
      try {
        const res = await fetch("/api/health-proxy", { cache: "no-store" });
        const body = (await res.json()) as HealthResponse;
        if (cancelled) return;
        setHealth(body);
        setStatus(body.overall ?? "down");
      } catch {
        if (cancelled) return;
        setHealth(null);
        setStatus("down");
      }
    }

    probe();
    const id = setInterval(probe, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <header className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-5">
      <div className="flex items-center gap-3">
        <Image
          src="/branding/hbsu.png"
          alt="HBSU"
          width={40}
          height={40}
          priority
          title="Team from Homi Bhabha State University, Mumbai"
          className="rounded"
        />
        <div className="flex flex-col leading-tight">
          <span className="text-[17px] font-semibold tracking-tight text-gray-900">
            MetaboAgent
          </span>
          <span className="text-[13px] text-gray-500">
            Biochem agent grounded in PubMed, KEGG, UniProt
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <StatusDot status={status} label={statusLabel(status, health)} />
          <span className="text-sm text-gray-600">Backend</span>
        </div>

        <label
          className="flex cursor-not-allowed items-center gap-2 opacity-60"
          title="Deep mode — wiring comes in Phase 5.5"
        >
          <span className="text-sm text-gray-600">Deep mode</span>
          <span className="relative inline-flex h-5 w-9 items-center rounded-full bg-gray-200">
            <span className="ml-0.5 inline-block h-4 w-4 rounded-full bg-white shadow" />
          </span>
          <input type="checkbox" disabled className="sr-only" />
        </label>
      </div>
    </header>
  );
}
