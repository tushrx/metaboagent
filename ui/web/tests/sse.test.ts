import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChat, ChatRequestError, formatChatError } from "@/lib/sse";
import type { AgentEvent } from "@/lib/api";

function sseFrame(payload: object): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

/**
 * Build a mock Response with a ReadableStream that emits ``chunks`` as
 * distinct chunks (each enqueue is a separate reader.read() cycle). Each
 * chunk is UTF-8 encoded.
 */
function mockResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

async function collect(iter: AsyncIterable<AgentEvent>) {
  const out: AgentEvent[] = [];
  for await (const ev of iter) out.push(ev);
  return out;
}

describe("streamChat", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("parses a clean sequence of SSE frames in order", async () => {
    const chunks = [
      sseFrame({ type: "token", content: "Hello " }),
      sseFrame({ type: "token", content: "world" }),
      sseFrame({
        type: "tool_call",
        name: "fetch_kegg_live",
        args: { entity_id: "C00022" },
        id: "tc_1",
      }),
      sseFrame({ type: "tool_result", id: "tc_1", content: "{...}" }),
      sseFrame({ type: "final_answer", content: "Hello world" }),
      sseFrame({ type: "done", usage: { iterations: 2, ms: 1234 } }),
    ];
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse(chunks)) as unknown as typeof fetch;

    const events = await collect(
      streamChat([{ role: "user", content: "hi" }]),
    );

    expect(events.map((e) => e.type)).toEqual([
      "token",
      "token",
      "tool_call",
      "tool_result",
      "final_answer",
      "done",
    ]);
    expect(events[2]).toMatchObject({
      type: "tool_call",
      name: "fetch_kegg_live",
      args: { entity_id: "C00022" },
      id: "tc_1",
    });
  });

  it("re-assembles a frame that is split across two network chunks", async () => {
    // Split one frame's JSON in the middle of the string.
    const full = sseFrame({ type: "token", content: "split-across-chunks" });
    const cut = Math.floor(full.length / 2);
    const part1 = full.slice(0, cut);
    const part2 = full.slice(cut);

    // Follow with one more complete frame so we see ordering.
    const followUp = sseFrame({ type: "done", usage: {} });

    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        mockResponse([part1, part2, followUp]),
      ) as unknown as typeof fetch;

    const events = await collect(streamChat([{ role: "user", content: "q" }]));
    expect(events.length).toBe(2);
    expect(events[0]).toEqual({
      type: "token",
      content: "split-across-chunks",
    });
    expect(events[1].type).toBe("done");
  });

  it("ignores SSE comment frames and malformed JSON", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      mockResponse([
        ": keepalive\n\n",
        "data: {not-json\n\n",
        sseFrame({ type: "token", content: "ok" }),
        sseFrame({ type: "done", usage: {} }),
      ]),
    ) as unknown as typeof fetch;

    const events = await collect(streamChat([{ role: "user", content: "q" }]));
    expect(events.map((e) => e.type)).toEqual(["token", "done"]);
  });

  it("throws ChatRequestError on non-2xx response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("boom", { status: 500 }),
    ) as unknown as typeof fetch;

    await expect(
      collect(streamChat([{ role: "user", content: "q" }])),
    ).rejects.toBeInstanceOf(ChatRequestError);
  });
});

describe("formatChatError", () => {
  it("substitutes a friendly message for HTML 5xx bodies (Cloudflare 502 page)", () => {
    const html =
      "<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head>" +
      "<body><h1>Bad gateway</h1>Error code: 502</body></html>";
    const msg = formatChatError(502, "Bad Gateway", html);
    expect(msg).toBe(
      "[HTTP 502] The server is temporarily unreachable. Please try again in a moment.",
    );
    expect(msg).not.toMatch(/<\/?html|DOCTYPE/i);
  });

  it("uses timeout phrasing for HTML 504 (NGINX gateway timeout page)", () => {
    const html = "<html><body>504 Gateway Time-out</body></html>";
    const msg = formatChatError(504, "Gateway Timeout", html);
    expect(msg).toBe(
      "[HTTP 504] The agent took too long to respond. Try a simpler question or use cached prompts.",
    );
  });

  it("recognizes JSON {error: upstream_unreachable} from chat-proxy", () => {
    const body = JSON.stringify({
      error: "upstream_unreachable",
      message: "fetch failed: ECONNREFUSED 127.0.0.1:8080",
    });
    const msg = formatChatError(502, "Bad Gateway", body);
    expect(msg).toBe(
      "[HTTP 502] The agent backend is unreachable. The server may have restarted.",
    );
  });

  it("preserves the JSON message for structured 4xx validation errors", () => {
    const body = JSON.stringify({
      error: "validation_failed",
      message: "messages[0].content must be a non-empty string",
    });
    const msg = formatChatError(400, "Bad Request", body);
    expect(msg).toBe(
      "[HTTP 400] messages[0].content must be a non-empty string",
    );
  });

  it("falls back to a generic '[HTTP 500] Server error' for 500 with empty body", () => {
    expect(formatChatError(500, "", "")).toBe("[HTTP 500] Server error");
  });
});
