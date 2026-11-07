#!/usr/bin/env node
// 중계 층 탐침 — 남은(STUCK) 요청마다 "브라우저가 먼저 떠났나, 기다리는데 멈췄나" 를 가른다.
// 사용: node classify.mjs <로그 폴더> [--json]
//   <로그 폴더>/route.log : 중계 단계 기록(PROXY_TRACE_LOG) · <로그 폴더>/fe.log : 브라우저 쪽 TCP 중계 기록(relay.mjs)
// 가르는 법: 멈춘 자리 = STUCK 바로 앞 단계가 적힌 시각. 브라우저 쪽 연결이 그 시각 ★이전에★ 닫혔으면 orphan(브라우저가 먼저 떠남 —
// 아무도 기다리지 않음), 그때 아직 열려 있었으면 still-connected(브라우저가 기다리는데 멈춤 — 2026-11-07 의 원래 증상 후보).
// 브라우저 쪽 요청 줄을 찾지 못하면 unmatched(같은 방법·경로가 시작 시각 ±50ms 안에 없음).
import fs from "node:fs";
import path from "node:path";

const dir = process.argv[2];
const asJson = process.argv.includes("--json");
if (!dir) { console.error("사용: node classify.mjs <로그 폴더> [--json]"); process.exit(2); }
const ts = (s) => Date.parse(s);
const lines = (f) => fs.readFileSync(path.join(dir, f), "utf8").split("\n").filter(Boolean);

// route.log: "<시각> <id> <단계> [덧말]"
const route = new Map();
for (const line of lines("route.log")) {
  const m = line.match(/^(\S+) (\d+) (\S+)(?: (.*))?$/);
  if (!m) continue;
  const [, t, id, st, rest] = m;
  const r = route.get(id) ?? { last: null, stuck: false, what: "", start: null };
  if (st === "start") { r.start = ts(t); r.what = (rest ?? "").trim(); }
  if (st === "STUCK") r.stuck = true; else r.last = ts(t);
  route.set(id, r);
}
// fe.log: 브라우저 → 프론트 연결의 요청 줄과 닫힘
const reqs = [], closes = new Map();
for (const line of lines("fe.log")) {
  let m = line.match(/^(\S+) (\d+) c2s \d+ \| (\w+) \/api\/backend(\S+) HTTP/);
  if (m) { reqs.push({ t: ts(m[1]), conn: m[2], what: `${m[3]} ${m[4]}` }); continue; }
  m = line.match(/^(\S+) (\d+) (?:end|err) /);
  if (m && !closes.has(m[2])) closes.set(m[2], ts(m[1]));
}
const rows = [];
const count = { orphan: 0, stillConnected: 0, unmatched: 0 };
for (const [id, r] of route) {
  if (!r.stuck) continue;
  const near = reqs.filter((q) => q.what === r.what && Math.abs(q.t - r.start) <= 50).sort((a, b) => Math.abs(a.t - r.start) - Math.abs(b.t - r.start));
  if (near.length === 0) { count.unmatched++; rows.push({ id, kind: "unmatched", what: r.what }); continue; }
  const closed = closes.get(near[0].conn);
  const kind = closed !== undefined && closed <= r.last ? "orphan" : "still-connected";
  count[kind === "orphan" ? "orphan" : "stillConnected"]++;
  rows.push({ id, kind, what: r.what, browserClosedAfterMs: closed === undefined ? null : closed - r.start, stalledAtMs: r.last - r.start });
}
if (asJson) console.log(JSON.stringify({ ...count, rows }));
else {
  for (const x of rows) console.log(`${x.id} ${x.kind.padEnd(15)} ${x.what}${x.kind === "unmatched" ? "" : ` · 멈춘 자리 +${x.stalledAtMs}ms · 브라우저 닫힘 ${x.browserClosedAfterMs === null ? "없음" : `+${x.browserClosedAfterMs}ms`}`}`);
  console.log(`orphan ${count.orphan} · still-connected ${count.stillConnected} · unmatched ${count.unmatched}`);
}
