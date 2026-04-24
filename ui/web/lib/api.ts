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
  /**
   * Phase 7 will set this true when external fetches are disabled and
   * the agent runs against the indexed corpus only. Backend doesn't
   * emit this field yet; the UI treats it as falsy when absent.
   */
  demo_mode?: boolean;
}

// --- Chat request --------------------------------------------------------

export type Tier = "default" | "deep" | "max_rigor";

/** MIME types the UI + backend agree to accept for image attachments. */
export const ATTACHMENT_ALLOWED_MIME = [
  "image/png",
  "image/jpeg",
  "image/webp",
] as const;
export type AttachmentMime = (typeof ATTACHMENT_ALLOWED_MIME)[number];

/**
 * One image the user attached to a message. `data_base64` is the
 * full-resolution payload the backend will feed to the vision model
 * (Phase 6); `thumbnail_base64` is a small copy the UI uses for history
 * rendering so reloads don't decode the big blob. On restore from
 * localStorage `data_base64` may be null — the thumbnail is all we keep
 * locally (see chat-workspace persistence notes).
 */
export interface Attachment {
  kind: "image";
  mime_type: AttachmentMime;
  filename: string;
  data_base64: string | null;
  thumbnail_base64: string;
}

export interface MessageIn {
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
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

// --- UI-side aggregation -------------------------------------------------

/**
 * A running log of one tool_call -> tool_result/tool_error cycle, built
 * up from the event stream and shown in the evidence rail. IDs match the
 * server-assigned tool_call id so results can be stitched in out-of-order.
 */
export type ToolActivityStatus = "running" | "done" | "error";

export interface ToolActivity {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: ToolActivityStatus;
  result?: unknown;
  error?: string;
  startedAt: number;
  endedAt?: number;
}
