"use client";

import Image from "next/image";
import { StatusDot } from "./status-dot";

export function Header() {
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
            Evidence-grounded biochem agent
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <StatusDot status="pending" label="Checking backend status…" />
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
