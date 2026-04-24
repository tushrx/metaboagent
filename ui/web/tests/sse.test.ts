import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChat, ChatRequestError } from "@/lib/sse";
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
