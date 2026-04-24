/**
 * Shared types for the MetaboAgent backend boundary.
 *
 * Wire format: see app/schemas.py + agent/core.py. The AgentEvent union
 * mirrors the event stream yielded by run_agent and emitted over SSE
 * from POST /chat.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8080";

// --- Health --------------------------------------------------------------

export type HealthOverall = "ok" | "degraded" | "down";

export interface HealthResponse {
  default: "ok" | "down";
  deep: "ok" | "down";
  max_rigor: "ok" | "down";
  overall: HealthOverall;
}

// --- Chat request --------------------------------------------------------

export type Tier = "default" | "deep" | "max_rigor";

export interface MessageIn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  messages: MessageIn[];
  tier?: Tier;
  max_iterations?: number;
  temperature?: number;
}

// --- Agent events (SSE stream) ------------------------------------------

export interface TokenEvent {
  type: "token";
  content: string;
}

export interface ToolCallEvent {
  type: "tool_call";
  name: string;
  args: Record<string, unknown>;
  id: string;
}

export interface ToolResultEvent {
  type: "tool_result";
  id: string;
  content: unknown;
}

export interface ToolErrorEvent {
  type: "tool_error";
  id: string;
  name: string;
  message: string;
}

export interface FinalAnswerEvent {
  type: "final_answer";
  content: string;
}

export interface ErrorEvent {
  type: "error";
  where: string;
  message: string;
}

export interface DoneEvent {
  type: "done";
  usage: {
    tokens_in?: number;
    tokens_out?: number;
    iterations?: number;
    tool_calls?: number;
    ms?: number;
  };
}

export type AgentEvent =
  | TokenEvent
  | ToolCallEvent
  | ToolResultEvent
  | ToolErrorEvent
  | FinalAnswerEvent
  | ErrorEvent
  | DoneEvent;
