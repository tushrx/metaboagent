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
import {
  API_BASE_URL,
  type AgentEvent,
  type MessageIn,
  type Tier,
} from "./api";

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

  const res = await fetch(`${API_BASE_URL}/chat`, {
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
      `chat: HTTP ${res.status}${text ? ` — ${text.slice(0, 200)}` : ""}`,
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
