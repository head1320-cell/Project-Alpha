import { test, expect } from "./fixtures";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { NextRequest } from "next/server";
import { GET } from "../src/app/api/backend/[...path]/route";

// ═══════════════════════════════════════════════════════════════════════════════
// 런타임 중계(`src/app/api/backend/[...path]/route.ts`) — ★브라우저가 떠나면 백엔드 호출도 멈춘다★
// ─────────────────────────────────────────────────────────────────────────────
// 잰 것(2026-11-07 · 탐침 빌드 + 두 층 TCP 중계 · 전체 E2E 30분): 백엔드가 답하기 ★전에★ 브라우저가 연결을 닫으면
// (페이지 이동·시험 끝) Next 는 닫힌 연결에 본문을 흘리지 않고 그냥 돌아선다(`pipeToNodeResponse` 의 `destroyed` 검사).
// 중계가 브라우저 신호를 백엔드 호출에 넘기지 않아, 그 백엔드 응답은 읽히지도 취소되지도 않고 남았다 —
// 단발 요청은 300초 시한까지, 스트림은 시한이 없어 끝없이. 다섯 건 모두 백엔드는 본문을 다 보냈다.
// 여기서는 실제 중계 모듈을 실제 `NextRequest` 로 부르고, 가짜 백엔드(빈 포트)로 연결이 끊기는지를 본다.
// Next 는 브라우저 연결이 끊기면 `req.signal` 을 `ResponseAborted` 로 멈추게 한다(next 14.2.5 base-server ·
// signalFromNodeResponse) — 시험은 그 계약을 그대로 흉내 낸다.
// 짝: 브라우저가 남아 있으면 답은 그대로 · 시한을 넘기면 여전히 504(499 로 접지 않음) · 백엔드가 없으면 502.
// ═══════════════════════════════════════════════════════════════════════════════

type Seen = { got: number; closedBeforeAnswer: number };

async function fakeBackend(onReq: (req: http.IncomingMessage, res: http.ServerResponse) => void) {
  const seen: Seen = { got: 0, closedBeforeAnswer: 0 };
  const srv = http.createServer((req, res) => {
    seen.got++;
    res.on("close", () => { if (!res.writableFinished) seen.closedBeforeAnswer++; });
    onReq(req, res);
  });
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", () => r()));
  const port = (srv.address() as AddressInfo).port;
  return {
    seen,
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise<void>((r) => { srv.closeAllConnections(); srv.close(() => r()); }),
  };
}

/** Next 가 브라우저 연결이 끊길 때 쓰는 까닭과 같은 이름. */
function browserGone() {
  const e = new Error("브라우저 연결이 끊김(시험)");
  e.name = "ResponseAborted";
  return e;
}

function callRoute(path: string[], signal?: AbortSignal) {
  const req = new NextRequest(`http://localhost:3000/api/backend/${path.join("/")}`, signal ? { signal } : undefined);
  return GET(req, { params: Promise.resolve({ path }) });
}

/** ms 안에 끝나면 그 값, 아니면 "아직 기다림" — 멈춘 중계가 시험을 붙잡지 않게. */
async function within<T>(p: Promise<T>, ms: number): Promise<T | "아직 기다림"> {
  let t: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<"아직 기다림">((r) => { t = setTimeout(() => r("아직 기다림"), ms); });
  try { return await Promise.race([p, late]); } finally { clearTimeout(t); }
}

const ENV_KEYS = ["BACKEND_URL", "BACKEND_PROXY_TIMEOUT_MS"] as const;
let saved: Record<string, string | undefined> = {};
test.beforeEach(() => { saved = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]])); });
test.afterEach(() => {
  for (const k of ENV_KEYS) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; }
});

test("중계 · 백엔드가 답하기 전에 브라우저가 떠나면 백엔드 호출도 바로 끊는다 — 499 · 시간 초과(504)로 적지 않는다", async () => {
  const b = await fakeBackend(() => { /* 답하지 않는다 */ });
  try {
    process.env.BACKEND_URL = b.url;
    process.env.BACKEND_PROXY_TIMEOUT_MS = "4000";
    const ctl = new AbortController();
    const pending = callRoute(["api", "v1", "slow"], ctl.signal);
    await expect.poll(() => b.seen.got, { message: "백엔드에 요청이 닿음" }).toBe(1);
    const t = Date.now();
    ctl.abort(browserGone());
    const res = await within(pending, 1500);
    expect(res, "브라우저가 떠난 뒤 1.5초 안에 중계가 끝난다(시한 4초를 기다리지 않음)").not.toBe("아직 기다림");
    if (res === "아직 기다림") return;
    expect(Date.now() - t).toBeLessThan(1500);
    expect(res.status, "브라우저가 떠남 = 499 — 시간 초과가 아니다").toBe(499);
    expect(((await res.json()) as { detail: string }).detail).toContain("브라우저가 요청을 거두어");
    await expect.poll(() => b.seen.closedBeforeAnswer, { timeout: 1500, message: "백엔드 연결이 답 전에 끊김" }).toBe(1);
  } finally { await b.close(); }
});

test("중계 · 까닭 없이 멈춘 신호(AbortError)도 499 — 시간 초과 검사보다 먼저 본다", async () => {
  const b = await fakeBackend(() => { /* 답하지 않는다 */ });
  try {
    process.env.BACKEND_URL = b.url;
    process.env.BACKEND_PROXY_TIMEOUT_MS = "4000";
    const ctl = new AbortController();
    const pending = callRoute(["api", "v1", "slow"], ctl.signal);
    await expect.poll(() => b.seen.got).toBe(1);
    ctl.abort(); // 까닭 없음 → fetch 는 이름이 AbortError 인 오류로 끝난다
    const res = await within(pending, 1500);
    expect(res).not.toBe("아직 기다림");
    if (res === "아직 기다림") return;
    expect(res.status, "AbortError 라도 브라우저가 떠난 것 — 504 가 아니다").toBe(499);
  } finally { await b.close(); }
});

test("중계 · 스트림도 — 시한이 없는 스트림 요청에서 브라우저가 떠나면 백엔드 호출을 끊는다", async () => {
  const b = await fakeBackend(() => { /* 답하지 않는다 */ });
  try {
    process.env.BACKEND_URL = b.url;
    const ctl = new AbortController();
    const pending = callRoute(["api", "v1", "screener", "run-advanced-stream"], ctl.signal);
    await expect.poll(() => b.seen.got).toBe(1);
    ctl.abort(browserGone());
    const res = await within(pending, 1500);
    expect(res, "스트림은 시한이 없어 예전에는 끝없이 기다렸다").not.toBe("아직 기다림");
    if (res === "아직 기다림") return;
    expect(res.status).toBe(499);
    await expect.poll(() => b.seen.closedBeforeAnswer, { timeout: 1500 }).toBe(1);
  } finally { await b.close(); }
});

test("중계 · 짝: 브라우저가 남아 있으면 느린 답도 그대로 전한다(끊지 않음)", async () => {
  const b = await fakeBackend((_req, res) => {
    setTimeout(() => { res.writeHead(200, { "content-type": "application/json", "x-probe": "kept" }); res.end(JSON.stringify({ ok: 1 })); }, 300);
  });
  try {
    process.env.BACKEND_URL = b.url;
    const ctl = new AbortController(); // 멈추지 않는 브라우저 신호
    const res = await within(callRoute(["api", "v1", "slow"], ctl.signal), 3000);
    expect(res).not.toBe("아직 기다림");
    if (res === "아직 기다림") return;
    expect(res.status).toBe(200);
    expect(res.headers.get("x-probe")).toBe("kept");
    expect(await res.json()).toEqual({ ok: 1 });
    expect(b.seen.closedBeforeAnswer, "답이 끝나기 전에 끊지 않았다").toBe(0);
  } finally { await b.close(); }
});

test("중계 · 짝: 브라우저는 남았는데 백엔드가 시한을 넘기면 여전히 504 — 499 로 접지 않는다", async () => {
  const b = await fakeBackend(() => { /* 답하지 않는다 */ });
  try {
    process.env.BACKEND_URL = b.url;
    process.env.BACKEND_PROXY_TIMEOUT_MS = "400";
    const res = await within(callRoute(["api", "v1", "slow"], new AbortController().signal), 3000);
    expect(res, "시한(0.4초)이 지나면 끝난다").not.toBe("아직 기다림");
    if (res === "아직 기다림") return;
    expect(res.status).toBe(504);
    expect(((await res.json()) as { detail: string }).detail).toContain("시간이 초과");
    await expect.poll(() => b.seen.closedBeforeAnswer, { timeout: 1500, message: "시한이 지나면 백엔드 연결도 끊김" }).toBe(1);
  } finally { await b.close(); }
});

test("중계 · 짝: 백엔드가 없으면 502 — 499·504 로 접지 않는다", async () => {
  const b = await fakeBackend(() => {});
  const url = b.url;
  await b.close(); // 빈 포트 — 아무도 듣지 않는다
  process.env.BACKEND_URL = url;
  const res = await within(callRoute(["api", "v1", "slow"], new AbortController().signal), 3000);
  expect(res).not.toBe("아직 기다림");
  if (res === "아직 기다림") return;
  expect(res.status).toBe(502);
  expect(((await res.json()) as { detail: string }).detail).toContain("백엔드에 연결 불가");
});
