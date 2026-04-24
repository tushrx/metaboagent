/**
 * API client stubs for the MetaboAgent backend.
 *
 * Real fetch wrappers (SSE for /chat, typed /tools, etc.) land in 5.2+.
 * This file exists so imports from components/ don't dangle.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8080";

export type HealthOverall = "ok" | "degraded" | "down";

export interface HealthResponse {
  default: "ok" | "down";
  deep: "ok" | "down";
  max_rigor: "ok" | "down";
  overall: HealthOverall;
}
