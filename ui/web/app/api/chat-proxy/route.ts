// Server-side proxy for POST /chat. Mirrors health-proxy in spirit, but
// streams the SSE response body straight through with no Next.js
// middleware/cache buffering — that's the whole reason this exists rather
// than a next.config rewrite.
//
// `duplex: 'half'` is required by undici when the request body is a
// ReadableStream; without it the fetch rejects.
//
// Reads upstream from process.env.API_BASE_URL (server-only, distinct from
// NEXT_PUBLIC_API_URL which is baked into the client bundle for other
// uses). Falls back to the loopback backend default.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

const UPSTREAM = process.env.API_BASE_URL || "http://127.0.0.1:8080";

export async function POST(req: Request): Promise<Response> {
  try {
    const upstream = await fetch(`${UPSTREAM}/chat`, {
      method: "POST",
      headers: {
        "content-type": req.headers.get("content-type") || "application/json",
      },
      body: req.body,
      cache: "no-store",
      // @ts-expect-error - undici extension; required to send a streaming body
      duplex: "half",
    });

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    const message =
      err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    return new Response(
      JSON.stringify({ error: "upstream_unreachable", message }),
      {
        status: 502,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
}
