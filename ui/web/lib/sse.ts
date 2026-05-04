/**
 * SSE client for POST /chat.
 *
 * EventSource only supports GET, so we hand-roll an async generator over
 * fetch() + ReadableStream + TextDecoder. Frames are "data: <json>\n\n".
 * We buffer across TCP chunks until we see a blank line.
 *
 * Use:
 *   const ctrl = new AbortController();
 *   for await (const ev of streamChat([{role:"user",content:"hi"}], "default", ctrl.signal)) {
 *     // ev is a typed AgentEvent
 *   }
 */
import { type AgentEvent, type MessageIn, type Tier } from "./api";

export class ChatRequestError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ChatRequestError";
    this.status = status;
  }
}

export interface StreamChatOptions {
  tier?: Tier;
  maxIterations?: number;
  temperature?: number;
  signal?: AbortSignal;
}

export async function* streamChat(
  messages: MessageIn[],
  options: StreamChatOptions = {},
): AsyncGenerator<AgentEvent, void, void> {
  const { tier = "default", maxIterations, temperature, signal } = options;

  // messages may carry `attachments` (Phase 5.6); JSON.stringify passes
  // them through verbatim. Backend clamps at ≤3/msg + mime allowlist.
  const body: Record<string, unknown> = { messages, tier };
  if (maxIterations !== undefined) body.max_iterations = maxIterations;
  if (temperature !== undefined) body.temperature = temperature;

  const res = await fetch(`/api/chat-proxy`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new ChatRequestError(
      res.status,
      formatChatError(res.status, res.statusText, text),
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        // Flush any trailing frame (server should always end with \n\n
        // after the done event, but be defensive).
        const trailing = buffer.trim();
        if (trailing) {
          const ev = parseFrame(trailing);
          if (ev) yield ev;
        }
        return;
      }

      buffer += decoder.decode(value, { stream: true });

      // Events are separated by a blank line. Split, keep the last
      // (possibly partial) frame back in the buffer.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const ev = parseFrame(frame);
        if (ev) yield ev;
      }
    }
  } finally {
    reader.releaseLock?.();
  }
}

/**
 * Parse a single SSE frame. Returns null for blanks, comments, or
 * malformed JSON. Ignores multi-line frames whose first line is the
 * only `data:` line we care about; the backend emits one data line
 * per event per CLAUDE.md §4.
 */
function parseFrame(frame: string): AgentEvent | null {
  const trimmed = frame.trim();
  if (!trimmed) return null;
  // SSE comment frames start with ":" — ignore.
  if (trimmed.startsWith(":")) return null;
  if (!trimmed.startsWith("data:")) return null;

  const payload = trimmed.slice(5).trimStart();
  try {
    return JSON.parse(payload) as AgentEvent;
  } catch {
    return null;
  }
}

/**
 * Build a human-readable error message from a non-2xx /api/chat-proxy
 * response. Always leads with "[HTTP <status>]" so developers can grep,
 * then a friendly suffix tailored to the body shape:
 *   - HTML body (Cloudflare 502 / NGINX gateway page) → generic "server
 *     temporarily unreachable" (or timeout phrasing for 504)
 *   - JSON body → recognized {error: "upstream_unreachable" | "upstream_timeout"}
 *     get tailored messages; otherwise prefer parsed.message, then parsed.error
 *   - Anything else → fall back to res.statusText, or a generic class label
 */
export function formatChatError(
  status: number,
  statusText: string,
  body: string,
): string {
  const prefix = `[HTTP ${status}]`;
  const trimmed = body.trim();
  const lower = trimmed.toLowerCase();

  if (lower.startsWith("<!doctype") || lower.startsWith("<html")) {
    if (status === 504) {
      return `${prefix} The agent took too long to respond. Try a simpler question or use cached prompts.`;
    }
    return `${prefix} The server is temporarily unreachable. Please try again in a moment.`;
  }

  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as { error?: unknown; message?: unknown };
      if (parsed.error === "upstream_unreachable") {
        return `${prefix} The agent backend is unreachable. The server may have restarted.`;
      }
      if (parsed.error === "upstream_timeout") {
        return `${prefix} The agent took too long to respond. Try a simpler question or use cached prompts.`;
      }
      if (typeof parsed.message === "string" && parsed.message) {
        return `${prefix} ${parsed.message}`;
      }
      if (typeof parsed.error === "string" && parsed.error) {
        return `${prefix} ${parsed.error}`;
      }
    } catch {
      // fall through to generic fallback
    }
  }

  const fallback = statusText || (status >= 500 ? "Server error" : "Request error");
  return `${prefix} ${fallback}`;
}
