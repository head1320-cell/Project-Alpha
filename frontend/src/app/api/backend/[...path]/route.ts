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

// Upper bound on how long we wait for the backend. Long real-data backtests
// (screen-to-backtest over a broad universe) can legitimately take minutes; the
// default undici headersTimeout (~300s) would otherwise abort with an opaque
// throw that we'd report as a confusing 502. We set an explicit, configurable
// budget and, on timeout, return a clear 504 instead. Tune via env.
function proxyTimeoutMs(): number {
  const n = Number(process.env.BACKEND_PROXY_TIMEOUT_MS);
  return Number.isFinite(n) && n > 0 ? n : 300_000;
}

// Distinguish "the request ran out of time" from "the backend is unreachable".
// undici wraps the real cause: a timeout surfaces as TimeoutError/AbortError or
// a UND_ERR_*_TIMEOUT code, often nested under err.cause.
function isTimeoutError(e: unknown): boolean {
  if (!(e instanceof Error)) return false;
  const name = e.name || "";
  const code = (e as { code?: string }).code || "";
  const causeCode = ((e as { cause?: { code?: string } }).cause?.code) || "";
  return (
    name === "TimeoutError" ||
    name === "AbortError" ||
    code === "UND_ERR_HEADERS_TIMEOUT" ||
    code === "UND_ERR_BODY_TIMEOUT" ||
    causeCode === "UND_ERR_HEADERS_TIMEOUT" ||
    causeCode === "UND_ERR_BODY_TIMEOUT"
  );
}

async function proxy(req: NextRequest, path: string[]): Promise<Response> {
  const target = `${backendBase()}/${(path || []).join("/")}${req.nextUrl.search || ""}`;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length"); // recomputed by fetch from the buffered body

  // SSE streaming endpoints (e.g. run-advanced-stream) can legitimately stay
  // open for a long time and are already guarded by undici's per-chunk inactivity
  // (bodyTimeout); a TOTAL deadline would cut healthy long streams. So apply the
  // hard deadline only to unary requests (e.g. screen-to-backtest), where a long
  // hang is the actual failure we want to surface as a clean 504.
  const isStream = (path || []).join("/").includes("stream");
  const timeoutMs = proxyTimeoutMs();
  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: "manual",
    ...(isStream ? {} : { signal: AbortSignal.timeout(timeoutMs) }),
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    // Timed out → 504 with an actionable message (not a misleading "unreachable").
    if (isTimeoutError(e)) {
      return new Response(
        JSON.stringify({
          error: true,
          detail: `분석이 너무 오래 걸려 시간이 초과되었습니다 (>${Math.round(timeoutMs / 1000)}초). `
            + `유니버스 범위(종목 수)나 조건을 줄여 다시 시도하세요.`,
        }),
        { status: 504, headers: { "content-type": "application/json" } },
      );
    }
    // Genuinely unreachable backend → clear 502 (not a confusing generic 500).
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
