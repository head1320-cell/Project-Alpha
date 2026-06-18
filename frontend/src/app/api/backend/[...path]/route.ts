/**
 * Runtime backend proxy — App Router catch-all route handler.
 * ==========================================================================
 * Browser calls same-origin "/api/backend/<path>"; this handler forwards to the
 * backend at BACKEND_URL, read at REQUEST time (not build time).
 *
 * Why a route handler instead of next.config.js `rewrites()`:
 *   Next.js evaluates rewrites() at BUILD time and freezes the destination into
 *   routes-manifest.json. A runtime `BACKEND_URL` env is then IGNORED — the
 *   baked value (e.g. http://localhost:8000) is used forever. In a container
 *   that points at the frontend's own localhost:8000 (nothing there) → every
 *   proxied call ECONNREFUSEs → Next returns 500. A route handler instead reads
 *   process.env.BACKEND_URL on each request, so the backend address is a true
 *   runtime knob (set it in docker-compose / the platform env, no rebuild).
 *
 * Streaming: the screener uses an SSE endpoint (run-advanced-stream). We return
 * the upstream ReadableStream directly so progress/result events stream through
 * unbuffered.
 */
import { type NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function backendBase(): string {
  return (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/+$/, "");
}

// Hop-by-hop / encoding headers that must NOT be forwarded verbatim. undici has
// already decoded the body, so a forwarded content-encoding/content-length would
// describe the compressed bytes and corrupt the response in the browser.
const STRIP_RESPONSE = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
  "keep-alive",
]);

async function proxy(req: NextRequest, path: string[]): Promise<Response> {
  const target = `${backendBase()}/${(path || []).join("/")}${req.nextUrl.search || ""}`;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length"); // recomputed by fetch from the buffered body

  const init: RequestInit = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (e) {
    // Backend unreachable → surface a clear 502 (not a confusing generic 500).
    const msg = e instanceof Error ? e.message : String(e);
    return new Response(
      JSON.stringify({ error: true, detail: `백엔드에 연결할 수 없습니다 (${backendBase()}): ${msg}` }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }

  const respHeaders = new Headers();
  upstream.headers.forEach((v, k) => {
    if (!STRIP_RESPONSE.has(k.toLowerCase())) respHeaders.set(k, v);
  });
  // Help proxies (nginx) not buffer SSE.
  if ((upstream.headers.get("content-type") || "").includes("text/event-stream")) {
    respHeaders.set("x-accel-buffering", "no");
    respHeaders.set("cache-control", "no-cache, no-transform");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
}

type Ctx = { params: { path?: string[] } };

export async function GET(req: NextRequest, { params }: Ctx) { return proxy(req, params.path ?? []); }
export async function POST(req: NextRequest, { params }: Ctx) { return proxy(req, params.path ?? []); }
export async function PUT(req: NextRequest, { params }: Ctx) { return proxy(req, params.path ?? []); }
export async function PATCH(req: NextRequest, { params }: Ctx) { return proxy(req, params.path ?? []); }
export async function DELETE(req: NextRequest, { params }: Ctx) { return proxy(req, params.path ?? []); }
export async function HEAD(req: NextRequest, { params }: Ctx) { return proxy(req, params.path ?? []); }
export async function OPTIONS(req: NextRequest, { params }: Ctx) { return proxy(req, params.path ?? []); }
