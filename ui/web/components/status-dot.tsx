"use client";

type Overall = "ok" | "degraded" | "down" | "pending";

interface StatusDotProps {
  status: Overall;
  label: string;
}

const COLORS: Record<Overall, string> = {
  ok: "bg-green-500",
  degraded: "bg-amber-500",
  down: "bg-red-500",
  pending: "bg-gray-300",
};

export function StatusDot({ status, label }: StatusDotProps) {
  return (
    <span
      title={label}
      aria-label={label}
      className={`inline-block h-2.5 w-2.5 rounded-full ${COLORS[status]} transition-colors`}
    />
  );
}
