/**
 * Proxy stage trace — a DIAGNOSTIC, off by default.
 * ==========================================================================
 * Only when `PROXY_TRACE_LOG=<file>` is set (read per request, like BACKEND_URL) does the proxy append one line
 * per stage of each request: start · fetch · headers <status> · chunk1 <bytes> · end · cancel · body-error ·
 * fetch-error · client-gone · nobody — and, from a watchdog, `STUCK stage=<last stage> age=<ms>` once for any
 * request still open after `PROXY_TRACE_STUCK_MS` (default 10000). Unset → nothing is written and the upstream
 * body is returned untouched (no wrapper).
 *
 * `chunk1` means Next actually READ the first body chunk (the wrapper uses highWaterMark 0, so nothing is pulled
 * ahead of the reader). A request stuck at `headers` therefore means: the backend's headers arrived, nobody read
 * the body. How to run the whole layer probe and read the result: frontend/scripts/proxy-probe/README.md.
 */
import { appendFileSync } from "node:fs";

type Live = { what: string; t0: number; stage: string; reported: boolean };
const state = { seq: 0, live: new Map<number, Live>(), timer: null as ReturnType<typeof setInterval> | null, every: 0, warned: false };

export type Trace = {
  stage(name: string, extra?: string): void;
  /** Last stage: the request is no longer open. */
  done(name: string, extra?: string): void;
  wrap(body: ReadableStream<Uint8Array> | null): ReadableStream<Uint8Array> | null;
};

const OFF: Trace = { stage() {}, done() {}, wrap: (b) => b };

function write(file: string, line: string) {
  try {
    appendFileSync(file, `${new Date().toISOString()} ${line}\n`);
  } catch (e) {
    // A broken trace must not break the proxy — but say it once instead of dropping lines silently.
    if (!state.warned) { state.warned = true; console.error(`[proxy-trace] cannot write ${file}: ${e instanceof Error ? e.message : e}`); }
  }
}

function stuckMs(): number {
  const n = Number(process.env.PROXY_TRACE_STUCK_MS);
  return Number.isFinite(n) && n > 0 ? n : 10_000;
}

/** The limit and the file are read on every tick; a shorter limit than the running timer's restarts it. */
function ensureWatchdog() {
  const every = Math.max(50, Math.min(5_000, Math.floor(stuckMs() / 2)));
  if (state.timer && state.every <= every) return;
  if (state.timer) clearInterval(state.timer);
  state.every = every;
  state.timer = setInterval(() => {
    const file = process.env.PROXY_TRACE_LOG;
    if (!file) return;
    const now = Date.now(), limit = stuckMs();
    for (const [id, l] of state.live) {
      if (!l.reported && now - l.t0 > limit) { l.reported = true; write(file, `${id} STUCK stage=${l.stage} age=${now - l.t0}ms ${l.what}`); }
    }
  }, every);
  state.timer.unref?.();
}

export function startTrace(what: string): Trace {
  const file = process.env.PROXY_TRACE_LOG;
  if (!file) return OFF;
  ensureWatchdog();
  const id = ++state.seq;
  const live: Live = { what, t0: Date.now(), stage: "start", reported: false };
  state.live.set(id, live);
  write(file, `${id} start ${what}`);
  const stage = (name: string, extra?: string) => { live.stage = name; write(file, `${id} ${name}${extra ? ` ${extra}` : ""}`); };
  const done = (name: string, extra?: string) => { stage(name, extra); state.live.delete(id); };
  return {
    stage,
    done,
    wrap(body) {
      if (!body) { done("nobody"); return null; }
      const reader = body.getReader();
      let n = 0;
      return new ReadableStream<Uint8Array>({
        async pull(c) {
          try {
            const { done: last, value } = await reader.read();
            if (last) { done("end", `chunks=${n}`); c.close(); return; }
            if (n++ === 0) stage("chunk1", String(value.byteLength));
            c.enqueue(value);
          } catch (e) {
            done("body-error", e instanceof Error ? e.name : String(e));
            c.error(e);
          }
        },
        cancel(reason) {
          done("cancel", reason instanceof Error ? reason.name : String(reason));
          return reader.cancel(reason);
        },
      }, { highWaterMark: 0 });
    },
  };
}
