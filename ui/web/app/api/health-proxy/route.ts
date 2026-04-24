import { NextResponse } from "next/server";
import { API_BASE_URL } from "@/lib/api";

// Server-side proxy so the browser never has to wrangle CORS against the
// FastAPI backend directly. Runs on every request; no cache.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    const body = await res.json().catch(() => null);
    if (!body) {
      return NextResponse.json(
        { default: "down", deep: "down", max_rigor: "down", overall: "down" },
        { status: 503 },
      );
    }
    return NextResponse.json(body, { status: res.status });
  } catch {
    return NextResponse.json(
      { default: "down", deep: "down", max_rigor: "down", overall: "down" },
      { status: 503 },
    );
  }
}
