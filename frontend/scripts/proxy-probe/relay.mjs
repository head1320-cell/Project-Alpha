#!/usr/bin/env node
// 중계 층 탐침 — TCP 중계(진단용). 연결마다 요청 줄·상태 줄·바이트·닫힘을 시각과 함께 적는다(본문 내용은 적지 않는다).
// 사용: node relay.mjs <듣는 포트> <대상 포트> <기록 파일> [--quiet]
//   --quiet : 요청 줄·상태 줄·조각 끝·닫힘만(본문 조각 줄은 뺀다 — 브라우저 쪽처럼 양이 많은 곳)
// 줄 꼴: <ISO 시각> <연결> open | c2s <바이트> [| 요청 줄] | s2c <바이트> [| 상태 줄] [chunk-end] | end client|server c2s=… s2c=… | err client|server <코드>
// 닫힘은 양쪽에 그대로 옮긴다(FIN 은 FIN 으로, 끊김은 끊김으로) — 연결 유지 동작을 바꾸지 않으려고.
import fs from "node:fs";
import net from "node:net";

const [listen, target, logFile] = [Number(process.argv[2]), Number(process.argv[3]), process.argv[4]];
const QUIET = process.argv.includes("--quiet");
if (!listen || !target || !logFile) {
  console.error("사용: node relay.mjs <듣는 포트> <대상 포트> <기록 파일> [--quiet]");
  process.exit(2);
}
const out = fs.createWriteStream(logFile, { flags: "a" });
const w = (s) => out.write(`${new Date().toISOString()} ${s}\n`);
const head = (buf) => {
  const s = buf.subarray(0, 160).toString("latin1");
  const m = s.match(/^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [^\r\n]{0,140}|^HTTP\/1\.[01] \d{3}/);
  return m ? ` | ${m[0]}` : "";
};
let seq = 0;
net.createServer((c) => {
  const id = ++seq;
  const s = net.connect(target, "127.0.0.1");
  if (!QUIET) w(`${id} open`);
  let c2s = 0, s2c = 0;
  c.on("data", (b) => { c2s += b.length; const h = head(b); if (!QUIET || h) w(`${id} c2s ${b.length}${h}`); s.write(b); });
  s.on("data", (b) => {
    s2c += b.length;
    const h = head(b);
    const tail = b.subarray(Math.max(0, b.length - 5)).toString("latin1") === "0\r\n\r\n" ? " [chunk-end]" : "";
    if (!QUIET || h || tail) w(`${id} s2c ${b.length}${h}${tail}`);
    c.write(b);
  });
  c.on("end", () => { w(`${id} end client c2s=${c2s} s2c=${s2c}`); s.end(); });
  s.on("end", () => { w(`${id} end server c2s=${c2s} s2c=${s2c}`); c.end(); });
  c.on("error", (e) => { w(`${id} err client ${e.code}`); s.destroy(); });
  s.on("error", (e) => { w(`${id} err server ${e.code}`); c.destroy(); });
  c.on("close", () => s.destroy());
  s.on("close", () => c.destroy());
}).listen(listen, "127.0.0.1", () => w(`relay ${listen} -> ${target} up`));
