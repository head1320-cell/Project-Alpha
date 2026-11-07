import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import http from "node:http";
import net, { type AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { test, expect } from "./fixtures";
import { GET } from "../src/app/api/backend/[...path]/route";
import { startTrace } from "../src/app/api/backend/[...path]/trace";

// ═══════════════════════════════════════════════════════════════════════════════
// 중계 층 탐침(진단 도구) — `PROXY_TRACE_LOG` 단계 기록 · `scripts/proxy-probe/relay.mjs` · `classify.mjs`
// ─────────────────────────────────────────────────────────────────────────────
// 2026-11-07 에 임시로 만들어 쓴 탐침을 저장소에 둔다(쓰는 법: scripts/proxy-probe/README.md). 여기서 거는 것:
//  · 꺼져 있으면(기본) 파일을 하나도 쓰지 않는다 — 짝: 켜면 시작·머리·첫 조각·끝이 차례로
//  · 아무도 본문을 읽지 않으면 STUCK 의 자리는 `headers`(미리 당겨 읽지 않음 — `chunk1` 은 Next 가 실제로 읽었다는 뜻)
//  · 브라우저가 먼저 떠나면 `client-gone 499` · TCP 중계는 요청 줄·상태 줄·닫힘을 적는다 · 분류는 orphan / still-connected / unmatched 를 가른다
// ═══════════════════════════════════════════════════════════════════════════════

const PROBE = path.join(__dirname, "..", "scripts", "proxy-probe");

async function fakeBackend(onReq: (req: http.IncomingMessage, res: http.ServerResponse) => void) {
  const srv = http.createServer(onReq);
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", () => r()));
  const port = (srv.address() as AddressInfo).port;
  return { port, url: `http://127.0.0.1:${port}`, close: () => new Promise<void>((r) => { srv.closeAllConnections(); srv.close(() => r()); }) };
}

const call = (p: string[], signal?: AbortSignal) =>
  GET(new NextRequest(`http://localhost:3000/api/backend/${p.join("/")}`, signal ? { signal } : undefined), { params: { path: p } });

const tmpLog = () => path.join(mkdtempSync(path.join(os.tmpdir(), "px-")), "route.log");
/** 그 요청(시작 줄의 id)의 단계 이름만 차례로. */
function stagesOf(file: string, what: string): string[] {
  const all = readFileSync(file, "utf8").split("\n").filter(Boolean).map((l) => l.split(" "));
  const id = all.find((f) => f[2] === "start" && f.slice(3).join(" ") === what)?.[1];
  return all.filter((f) => f[1] === id).map((f) => (f[2] === "STUCK" ? `STUCK ${f[3]}` : f[2]));
}

const KEYS = ["BACKEND_URL", "PROXY_TRACE_LOG", "PROXY_TRACE_STUCK_MS", "BACKEND_PROXY_TIMEOUT_MS"] as const;
let saved: Record<string, string | undefined> = {};
test.beforeEach(() => { saved = Object.fromEntries(KEYS.map((k) => [k, process.env[k]])); });
test.afterEach(() => { for (const k of KEYS) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; } });

test("탐침 · 꺼져 있으면(기본) 본문을 감싸지 않고 아무것도 쓰지 않는다 — 짝: 켜면 감싼다", async () => {
  const b = await fakeBackend((_q, s) => { s.writeHead(200, { "content-type": "application/json" }); s.end('{"ok":1}'); });
  try {
    process.env.BACKEND_URL = b.url;
    delete process.env.PROXY_TRACE_LOG;
    const res = await call(["api", "v1", "off"]);
    expect(await res.json()).toEqual({ ok: 1 });
    const body = new ReadableStream<Uint8Array>();
    const off = startTrace("GET /off");
    expect(off.wrap(body), "꺼져 있으면 본문 그대로(감싸지 않음)").toBe(body);
    // 꺼진 채 시작한 기록은 나중에 켜도 쓰지 않는다 — 켜짐은 요청을 시작할 때 정해진다.
    const file = tmpLog();
    process.env.PROXY_TRACE_LOG = file;
    off.stage("fetch"); off.done("end");
    expect(existsSync(file), "꺼진 기록은 아무것도 쓰지 않음").toBe(false);
    // 짝: 켠 채 시작하면 감싸고 쓴다.
    const on = startTrace("GET /on-pair");
    const other = new ReadableStream<Uint8Array>();
    expect(on.wrap(other)).not.toBe(other);
    expect(stagesOf(file, "GET /on-pair")).toEqual(["start"]);
  } finally { await b.close(); }
});

test("탐침 · 켜면 시작 → 머리 → 첫 조각 → 끝을 차례로 적는다", async () => {
  const b = await fakeBackend((_q, s) => { s.writeHead(200, { "content-type": "application/json" }); s.end('{"ok":2}'); });
  try {
    process.env.BACKEND_URL = b.url;
    process.env.PROXY_TRACE_LOG = tmpLog();
    const res = await call(["api", "v1", "on"]);
    expect(await res.json()).toEqual({ ok: 2 });
    expect(stagesOf(process.env.PROXY_TRACE_LOG, "GET /api/v1/on")).toEqual(["start", "fetch", "headers", "chunk1", "end"]);
  } finally { await b.close(); }
});

test("탐침 · 아무도 본문을 읽지 않으면 STUCK 의 자리는 headers — 읽으면 그 뒤로 나아가고, 취소하면 cancel", async () => {
  const b = await fakeBackend((_q, s) => { s.writeHead(200, { "content-type": "text/plain" }); s.write("part"); /* 끝내지 않는다 */ });
  try {
    process.env.BACKEND_URL = b.url;
    process.env.PROXY_TRACE_LOG = tmpLog();
    process.env.PROXY_TRACE_STUCK_MS = "200";
    const res = await call(["api", "v1", "held"]);
    const file = process.env.PROXY_TRACE_LOG;
    await expect.poll(() => stagesOf(file, "GET /api/v1/held"), { timeout: 3000 }).toContain("STUCK stage=headers");
    expect(stagesOf(file, "GET /api/v1/held"), "미리 당겨 읽지 않았다").not.toContain("chunk1");
    await new Promise((r) => setTimeout(r, 500)); // 감시(100ms 마다)가 여러 번 더 돈 뒤에도
    expect(stagesOf(file, "GET /api/v1/held").filter((s) => s.startsWith("STUCK")), "STUCK 은 요청마다 한 번").toHaveLength(1);
    const reader = res.body!.getReader();
    expect(new TextDecoder().decode((await reader.read()).value)).toBe("part");
    await reader.cancel("시험이 그만 읽음");
    expect(stagesOf(file, "GET /api/v1/held")).toEqual(["start", "fetch", "headers", "STUCK stage=headers", "chunk1", "cancel"]);
  } finally { await b.close(); }
});

test("탐침 · 백엔드가 답하기 전에 브라우저가 떠나면 client-gone 499 로 끝난다(STUCK 아님)", async () => {
  const b = await fakeBackend(() => { /* 답하지 않는다 */ });
  try {
    process.env.BACKEND_URL = b.url;
    process.env.PROXY_TRACE_LOG = tmpLog();
    process.env.PROXY_TRACE_STUCK_MS = "300";
    const ctl = new AbortController();
    const pending = call(["api", "v1", "gone"], ctl.signal);
    await new Promise((r) => setTimeout(r, 100));
    const e = new Error("브라우저 연결이 끊김(시험)"); e.name = "ResponseAborted"; ctl.abort(e);
    expect((await pending).status).toBe(499);
    await new Promise((r) => setTimeout(r, 700));
    expect(stagesOf(process.env.PROXY_TRACE_LOG, "GET /api/v1/gone")).toEqual(["start", "fetch", "client-gone"]);
  } finally { await b.close(); }
});

async function freePort(): Promise<number> {
  const s = net.createServer();
  await new Promise<void>((r) => s.listen(0, "127.0.0.1", () => r()));
  const p = (s.address() as AddressInfo).port;
  await new Promise<void>((r) => s.close(() => r()));
  return p;
}

test("탐침 · TCP 중계는 요청 줄·상태 줄·닫힘을 적고, --quiet 면 본문 조각 줄을 뺀다", async () => {
  const b = await fakeBackend((_q, s) => { s.writeHead(200, { "content-type": "text/plain", connection: "close" }); s.write("a"); setTimeout(() => s.write("b"), 60); setTimeout(() => s.end(), 120); });
  const runRelay = async (quiet: boolean) => {
    const port = await freePort();
    const log = tmpLog();
    const child = spawn(process.execPath, [path.join(PROBE, "relay.mjs"), String(port), String(b.port), log, ...(quiet ? ["--quiet"] : [])], { stdio: "ignore" });
    try {
      await expect.poll(() => existsSync(log) && readFileSync(log, "utf8").includes("up"), { timeout: 5000 }).toBe(true);
      const body = await new Promise<string>((ok, bad) => {
        http.get({ host: "127.0.0.1", port, path: "/probe?x=1", agent: false }, (r) => { let t = ""; r.on("data", (c) => (t += c)); r.on("end", () => ok(t)); }).on("error", bad);
      });
      expect(body).toBe("ab");
      await expect.poll(() => readFileSync(log, "utf8"), { timeout: 3000 }).toMatch(/ end (client|server) /);
      return readFileSync(log, "utf8");
    } finally { child.kill(); }
  };
  try {
    const full = await runRelay(false);
    expect(full).toMatch(/ \d+ c2s \d+ \| GET \/probe\?x=1 HTTP\/1\.1/);
    expect(full).toMatch(/ \d+ s2c \d+ \| HTTP\/1\.1 200/);
    expect(full.split("\n").filter((l) => / s2c /.test(l)).length, "본문 조각도 줄로").toBeGreaterThan(1);
    const quiet = await runRelay(true);
    expect(quiet).toMatch(/ \| GET \/probe\?x=1 HTTP\/1\.1/);
    expect(quiet).toMatch(/ \| HTTP\/1\.1 200/);
    expect(quiet.split("\n").filter((l) => / s2c /.test(l) && !/ \| HTTP/.test(l) && !/chunk-end/.test(l)), "quiet 는 본문 조각 줄이 없다").toEqual([]);
  } finally { await b.close(); }
});

test("탐침 · 분류: 브라우저가 멈춘 자리보다 먼저 떠났으면 orphan · 그때 열려 있었으면(뒤에 떠나도) still-connected · 짝을 못 찾으면 unmatched", () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "pxc-"));
  const T = (ms: number) => new Date(Date.UTC(2026, 10, 7, 0, 0, 0, ms)).toISOString();
  writeFileSync(path.join(dir, "route.log"), [
    `${T(0)} 1 start GET /api/v1/a`, `${T(1)} 1 fetch`, `${T(100)} 1 headers 200`, `${T(10200)} 1 STUCK stage=headers age=10200ms GET /api/v1/a`,
    `${T(0)} 2 start GET /api/v1/b`, `${T(1)} 2 fetch`, `${T(100)} 2 headers 200`, `${T(10200)} 2 STUCK stage=headers age=10200ms GET /api/v1/b`,
    `${T(0)} 3 start GET /api/v1/c`, `${T(1)} 3 fetch`, `${T(10200)} 3 STUCK stage=fetch age=10200ms GET /api/v1/c`,
    `${T(0)} 5 start GET /api/v1/e`, `${T(1)} 5 fetch`, `${T(100)} 5 headers 200`, `${T(10200)} 5 STUCK stage=headers age=10200ms GET /api/v1/e`,
    `${T(0)} 4 start GET /api/v1/d`, `${T(1)} 4 fetch`, `${T(9)} 4 headers 200`, `${T(10)} 4 chunk1 5`, `${T(11)} 4 end chunks=1`,
  ].join("\n") + "\n");
  writeFileSync(path.join(dir, "fe.log"), [
    `${T(0)} 10 c2s 500 | GET /api/backend/api/v1/a HTTP/1.1`, `${T(50)} 10 end client c2s=500 s2c=0`,
    `${T(2)} 11 c2s 500 | GET /api/backend/api/v1/b HTTP/1.1`, `${T(30000)} 11 end client c2s=500 s2c=0`,
    `${T(0)} 12 c2s 500 | GET /api/backend/api/v1/d HTTP/1.1`,
    `${T(0)} 13 c2s 500 | GET /api/backend/api/v1/e HTTP/1.1`, `${T(5000)} 13 end client c2s=500 s2c=0`, // 멈춘 뒤 4.9초 기다리다 떠남

  ].join("\n") + "\n");
  const r = spawnSync(process.execPath, [path.join(PROBE, "classify.mjs"), dir, "--json"], { encoding: "utf8" });
  expect(r.status, r.stderr).toBe(0);
  const out = JSON.parse(r.stdout) as { orphan: number; stillConnected: number; unmatched: number; rows: { id: string; kind: string }[] };
  expect({ orphan: out.orphan, stillConnected: out.stillConnected, unmatched: out.unmatched }).toEqual({ orphan: 1, stillConnected: 2, unmatched: 1 });
  expect(Object.fromEntries(out.rows.map((x) => [x.id, x.kind]))).toEqual({ 1: "orphan", 2: "still-connected", 3: "unmatched", 5: "still-connected" });
});
