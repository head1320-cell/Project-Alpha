import { readdirSync, readFileSync } from "node:fs";
import http from "node:http";
import type { AddressInfo, Socket } from "node:net";
import path from "node:path";
import { request as rawRequest } from "@playwright/test";
import { test, expect } from "./fixtures";

// ═══════════════════════════════════════════════════════════════════════════════
// 시험의 API 클라이언트는 ★쉰 연결을 다시 쓰지 않는다★ (`e2e/fixtures.ts` · 2026-11-07)
// ─────────────────────────────────────────────────────────────────────────────
// 잰 것: 전체 E2E 에서 정리 `DELETE http://localhost:8000/…` 가 `socket hang up` — 같은 요청 맥락의 바로 앞 호출과 5,007ms
// 떨어져 있었다. 백엔드(uvicorn)·Next 는 5초 쉰 연결을 닫고, Playwright 의 API 클라이언트는 프로세스 전체가 같은 keep-alive 연결
// 묶음을 쓰며 빈 연결에 스스로 시한을 두지 않는다(Node 는 서버의 `Keep-Alive: timeout=5` 힌트를 에이전트 시한이 있을 때만 쓴다).
// 여기서는 그 경합을 결정적으로 만든다: 가짜 서버가 ★같은 연결로 온 두 번째 요청에서 연결을 끊는다★(= 다시 쓰는 순간 서버가 닫음).
// 짝: 고정(fixtures)을 거치지 않은 맨 클라이언트는 실제로 연결을 다시 써서 끊긴다 — 전제가 살아 있는지 본다.
// ═══════════════════════════════════════════════════════════════════════════════

type Seen = { n: number; sockets: Set<number>; connection: string[]; probe: string[] };

async function oneShotServer() {
  const seen: Seen = { n: 0, sockets: new Set(), connection: [], probe: [] };
  const uses = new WeakMap<Socket, number>();
  const srv = http.createServer((req, res) => {
    const k = (uses.get(req.socket) ?? 0) + 1;
    uses.set(req.socket, k);
    if (k > 1) { req.socket.destroy(); return; } // 다시 쓴 연결 — 서버가 닫는 순간과 겹친 것처럼
    seen.n++;
    seen.sockets.add(req.socket.remotePort ?? -1);
    seen.connection.push(String(req.headers.connection ?? "-"));
    seen.probe.push(String(req.headers["x-probe"] ?? "-"));
    res.writeHead(200, { "content-type": "text/plain", "access-control-allow-origin": "*", "access-control-allow-headers": "x-probe" });
    res.end(req.method === "HEAD" ? undefined : "ok");
  });
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", () => r()));
  const url = `http://127.0.0.1:${(srv.address() as AddressInfo).port}`;
  return { seen, url, close: () => new Promise<void>((r) => { srv.closeAllConnections(); srv.close(() => r()); }) };
}

type Client = {
  get: (u: string, o?: object) => Promise<{ status(): number }>;
  post: (u: string, o?: object) => Promise<{ status(): number }>;
  put: (u: string, o?: object) => Promise<{ status(): number }>;
  patch: (u: string, o?: object) => Promise<{ status(): number }>;
  delete: (u: string, o?: object) => Promise<{ status(): number }>;
  head: (u: string, o?: object) => Promise<{ status(): number }>;
  fetch: (u: string, o?: object) => Promise<{ status(): number }>;
};

/** 동사마다 한 번씩 + 제 머리글을 준 호출 — 모두 새 연결이어야 한다. */
async function everyVerb(c: Client, url: string) {
  const st = [
    (await c.get(`${url}/a`)).status(),
    (await c.post(`${url}/b`, { data: { x: 1 } })).status(),
    (await c.put(`${url}/c`, { data: { x: 1 } })).status(),
    (await c.patch(`${url}/d`, { data: { x: 1 } })).status(),
    (await c.delete(`${url}/e`)).status(),
    (await c.head(`${url}/f`)).status(),
    (await c.fetch(`${url}/g`, { method: "GET" })).status(),
    (await c.get(`${url}/h`, { headers: { "x-probe": "kept" } })).status(),
  ];
  return st;
}

test("API 클라이언트 · page.request 는 동사마다 새 연결 — 서버가 다시 쓴 연결을 끊어도 실패하지 않는다", async ({ page }) => {
  const s = await oneShotServer();
  try {
    expect(await everyVerb(page.request as unknown as Client, s.url)).toEqual(Array(8).fill(200));
    expect(s.seen.n).toBe(8);
    expect(s.seen.sockets.size, "요청마다 다른 연결").toBe(8);
    expect(new Set(s.seen.connection)).toEqual(new Set(["close"]));
    expect(s.seen.probe.at(-1), "제 머리글은 그대로 간다").toBe("kept");
  } finally { await s.close(); }
});

test("API 클라이언트 · request 고정도 같다", async ({ request }) => {
  const s = await oneShotServer();
  try {
    expect(await everyVerb(request as unknown as Client, s.url)).toEqual(Array(8).fill(200));
    expect(s.seen.sockets.size).toBe(8);
  } finally { await s.close(); }
});

test("API 클라이언트 · route.fetch 도 새 연결 — 가로챈 브라우저 요청의 머리글은 그대로", async ({ page }) => {
  const s = await oneShotServer();
  try {
    await page.route(`${s.url}/**`, async (r) => { const res = await r.fetch(); await r.fulfill({ response: res }); });
    await page.goto("about:blank");
    const st = await page.evaluate(async (u) => {
      const out: number[] = [];
      for (let i = 0; i < 3; i++) out.push((await fetch(`${u}/r${i}`, { headers: { "x-probe": `p${i}` } })).status);
      return out;
    }, s.url);
    expect(st).toEqual([200, 200, 200]);
    expect(s.seen.sockets.size, "route.fetch 마다 다른 연결").toBe(s.seen.n);
    expect(s.seen.probe.filter((p) => p.startsWith("p")), "브라우저 요청의 머리글이 실려 간다").toEqual(["p0", "p1", "p2"]);
  } finally { await s.close(); }
});

test("API 클라이언트 · 시험 안에서 만든 맥락(browser.newContext)도 같다", async ({ browser }) => {
  const s = await oneShotServer();
  const ctx = await browser.newContext();
  try {
    expect(await everyVerb(ctx.request as unknown as Client, s.url)).toEqual(Array(8).fill(200));
    expect(s.seen.sockets.size).toBe(8);
  } finally { await ctx.close(); await s.close(); }
});

test("API 클라이언트 · 짝(전제): 고정을 거치지 않은 맨 클라이언트는 연결을 다시 써서 끊긴다", async () => {
  const s = await oneShotServer();
  const raw = await rawRequest.newContext();
  try {
    expect((await raw.get(`${s.url}/1`)).status()).toBe(200);
    const second = await raw.get(`${s.url}/2`).then(() => "답을 받음", (e: Error) => e.message);
    expect(second, "맨 클라이언트는 쉰 연결을 다시 쓴다 — 이 전제가 바뀌면 fixtures.ts 를 다시 볼 것").toContain("socket hang up");
  } finally { await raw.dispose(); await s.close(); }
});

test("API 클라이언트 · 모든 스펙은 test 를 ./fixtures 에서 가져온다(빠지면 그 스펙만 연결을 다시 쓴다)", async () => {
  const dir = path.join(__dirname);
  const specs = readdirSync(dir).filter((f) => f.endsWith(".spec.ts"));
  expect(specs.length, "스펙을 실제로 읽었다").toBeGreaterThan(90);
  const RAW = /^import\s*\{[^}]*\btest\b[^}]*\}\s*from\s*"@playwright\/test"/m; // 줄 머리의 가져오기만(아래 짝의 글은 줄 머리가 아님)
  const bad = specs.filter((f) => RAW.test(readFileSync(path.join(dir, f), "utf8")));
  expect(bad, "@playwright/test 에서 test 를 바로 가져오는 스펙").toEqual([]);
  // 짝: 검사가 실제로 잡고(바로 가져옴) 실제로 통과시킨다(./fixtures).
  expect(RAW.test('import { test, expect, type Page } from "@playwright/test";')).toBe(true);
  expect(RAW.test('import { test, expect, type Page } from "./fixtures";')).toBe(false);
});
