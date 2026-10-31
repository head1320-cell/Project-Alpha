import { test, expect, type Page } from "@playwright/test";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { keepSame, sameValue } from "../src/widgets/portfolio-graph/keepSame";
import { PG_Z_USERS, pgZRule } from "../src/widgets/portfolio-graph/zoomVar";

/**
 * CF 3부 R8 · 그리기 성능 재기 (스펙 §8.3 결정 8 — `onlyRenderVisibleElements` 는 재기만, 기준 넘을 때만)
 *  묻는 것: R 묶음이 큰 문서(100·200노드)에서 끌기·화면 이동·확대를 느리게 했는가 · 이 환경에서 p95 33ms(30fps)를 넘는가.
 *  ★절대값은 이 컨테이너(headless) 기준★ — 실제 기기 성능은 미검증. 판단은 같은 환경의 전후 비교(기준 c6eb269 vs HEAD)로.
 *  재기는 `CANVAS_PERF=1` 일 때만(시간 숫자는 시험으로 걸지 않는다 — 흔들려서 표로만). 결과는 `CANVAS_PERF_OUT/perf.jsonl` 에 한 줄씩.
 *  ★전제 시험 하나는 늘 돈다★ — 잴 문서가 깨진 문서(검증 문제가 있는 화면)가 아님을 서버로 확인한다.
 */

const API = "http://localhost:8000/api/v1";
const PERF = process.env.CANVAS_PERF === "1";
const OUT = process.env.CANVAS_PERF_OUT ?? "test-results/canvas-perf";
const LABEL = process.env.CANVAS_PERF_LABEL ?? "head";
const RUN = process.env.CANVAS_PERF_RUN ?? "1";
const STEPS = 60;
/** 잴 동작만 고르기(탐침용 — 기본은 셋 모두). */
const ACTIONS = new Set((process.env.CANVAS_PERF_ACTIONS ?? "drag,pan,wheel").split(","));
const WHEELS = 20;

type Doc = { format: string; version: number; meta: { name: string }; nodes: object[]; edges: { id: string; source: string; target: string }[] };
/** 사슬 k개(종목 → 수익률 → 기대 수익 추정 → 비중 계산 · 선 4)를 가로 5사슬 격자로 — 서버 값 0(계산 전). */
function chainDoc(k: number, row = 640): Doc {
  const nodes: object[] = [], edges: Doc["edges"] = [];
  const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
  for (let c = 0; c < k; c++) {
    const x = (c % 5) * 1320, y = Math.floor(c / 5) * row;                     // 줄 사이 640 — 가장 긴 카드보다 길어 겹치지 않는다
    const [u, r, es, o] = [`u${c}`, `r${c}`, `e${c}`, `o${c}`];
    nodes.push({ id: u, type: "universe", position: { x, y }, params: { tickers: ["005930", "000660"] } },
               { id: r, type: "returns", position: { x: x + 330, y }, params: {} },
               { id: es, type: "estimate", position: { x: x + 660, y }, params: {} },
               { id: o, type: "optimizer", position: { x: x + 990, y }, params: {} });
    edges.push(e(u, "universe", r, "universe"), e(r, "returns", es, "returns"), e(r, "returns", o, "returns"), e(es, "belief", o, "belief"));
  }
  return { format: "project-alpha.portfolio-graph", version: 1, meta: { name: `perf ${k * 4}` }, nodes, edges };
}

/** 페이지 안 계기 — rAF 간격 · long task · 문서 보존 쓰기(수·시간·바이트) · React 커밋 수. `__pf.on` 인 동안만 센다. */
function instrument() {
  type PF = { on: boolean; frames: number[]; lt: { s: number; d: number }[]; wip: { n: number; ms: number; bytes: number }; commits: number };
  const pf: PF = { on: false, frames: [], lt: [], wip: { n: 0, ms: 0, bytes: 0 }, commits: 0 };
  (window as unknown as { __pf: PF }).__pf = pf;
  const set = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k: string, v: string) {
    if (k !== "alpha_pg_wip" || !pf.on) return set.call(this, k, v);
    const t = performance.now();
    set.call(this, k, v);
    pf.wip.n++; pf.wip.ms += performance.now() - t; pf.wip.bytes = v.length;
  };
  // React 는 운영 빌드에서도 devtools 고리가 있으면 커밋마다 부른다(react-dom 18).
  const renderers = new Map<number, unknown>();
  Object.defineProperty(window, "__REACT_DEVTOOLS_GLOBAL_HOOK__", { configurable: true, value: {
    renderers, supportsFiber: true, isDisabled: false,
    inject(r: unknown) { renderers.set(renderers.size + 1, r); return renderers.size; },
    onCommitFiberRoot() { if (pf.on) pf.commits++; }, onCommitFiberUnmount() {}, onPostCommitFiberRoot() {}, onScheduleFiberRoot() {}, checkDCE() {},
  } });
  // 다시 그린 카드·선 세기(R8 계약 시험) — 커밋마다 섬유 나무를 걸어, 앞 커밋에 없던 섬유 중 함수 컴포넌트를 실제로 부른 것(PerformedWork)만.
  // 카드 = React Flow 가 넘긴 노드 props(positionAbsoluteX) + 우리 data.kind · 선 = 선 props(sourceX) + 우리 data.typeLabel ·
  // 감싸개 = React Flow 의 노드·선 감싸개(props 에 nodeTypes·edgeTypes) · 이야기 단계 = 오른쪽 창 단계(props 에 n·node·current).
  type F = { child: F | null; sibling: F | null; flags: number; type: unknown; memoizedProps: Record<string, unknown> | null };
  const rec = { track: false, prev: new WeakSet<object>(), cards: [] as string[], edges: [] as string[], wraps: [] as string[], wrapEdges: [] as string[],
                steps: [] as string[], root: null as { current: F } | null };
  (window as unknown as { __rr: typeof rec }).__rr = rec;
  const walk = (root: F, count: boolean) => {
    const seen = new WeakSet<object>();
    const stack: (F | null)[] = [root];
    while (stack.length) {
      const f = stack.pop();
      if (!f) continue;
      seen.add(f);
      if (count && !rec.prev.has(f) && (f.flags & 1) && typeof f.type === "function" && f.memoizedProps) {
        const p = f.memoizedProps, d = p.data as Record<string, unknown> | undefined;
        if (typeof p.positionAbsoluteX === "number" && d && "kind" in d) rec.cards.push(String(p.id));
        else if (typeof p.sourceX === "number" && d && "typeLabel" in d) rec.edges.push(String(p.id));
        else if ("nodeTypes" in p && typeof p.id === "string") rec.wraps.push(p.id);
        else if ("edgeTypes" in p && typeof p.id === "string") rec.wrapEdges.push(p.id);
        else if (typeof p.n === "number" && "node" in p && "current" in p && typeof p.id === "string") rec.steps.push(p.id);
      }
      stack.push(f.sibling, f.child);
    }
    rec.prev = seen;
  };
  (window as unknown as { __rrStart: () => void }).__rrStart = () => { rec.cards = []; rec.edges = []; rec.wraps = []; rec.wrapEdges = []; rec.steps = []; if (rec.root) walk(rec.root.current, false); rec.track = true; };
  const hook = (window as unknown as { __REACT_DEVTOOLS_GLOBAL_HOOK__: { onCommitFiberRoot: (id: number, root: { current: F }) => void } }).__REACT_DEVTOOLS_GLOBAL_HOOK__;
  hook.onCommitFiberRoot = (_id, root) => { if (pf.on) pf.commits++; rec.root = root; if (rec.track) walk(root.current, true); };
  const loop = (t: number) => { if (pf.on) pf.frames.push(t); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  try { new PerformanceObserver((l) => { for (const x of l.getEntries()) pf.lt.push({ s: x.startTime, d: x.duration }); }).observe({ type: "longtask" }); } catch { /* */ }
}

async function open(page: Page, doc: Doc, trackBoot = false) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(instrument);
  if (trackBoot) await page.addInitScript(() => { (window as never as { __rr: { track: boolean } }).__rr.track = true; });
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r8_seeded")) return;
      sessionStorage.setItem("r8_seeded", "1");
      for (const k of ["alpha_pg_panels", "alpha_pg_view", "alpha_pg_left_tab"]) localStorage.removeItem(k);
      localStorage.setItem("alpha_pg_welcomed", "1");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node")).toHaveCount(doc.nodes.length, { timeout: 60_000 });
  await settle(page, 800);
}
/** 확대 — React Flow 화면 변환에서 읽는다(우리 CSS 변수와 무관하게 — 탐침이 그 변수를 꺼도 잰다). */
const zoomOf = (page: Page) => page.locator(".react-flow__viewport").evaluate((el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);
const frame = (page: Page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
async function settle(page: Page, ms = 500) { await page.waitForTimeout(ms); await frame(page); await frame(page); }
async function view(page: Page, v: "fit" | "1x") {
  await page.locator(".react-flow__controls-fitview").click();
  await settle(page, 600);
  if (v === "1x") { await page.locator(".pg-zoom-pct").click(); await settle(page, 700); }
}
/** 화면 가운데에 가장 가까운, 화면 안에 다 보이는 카드의 머리 쪽 한 점. */
const cardPoint = (page: Page) => page.evaluate(() => {
  const W = innerWidth, H = innerHeight;
  let best: { x: number; y: number; d: number } | null = null;
  for (const el of document.querySelectorAll<HTMLElement>(".pg-node")) {
    const b = el.getBoundingClientRect();
    if (b.left < 0 || b.top < 0 || b.right > W || b.bottom > H || !b.width) continue;
    const x = b.left + b.width / 2, y = b.top + b.height * 0.15, d = Math.hypot(x - W / 2, y - H / 2);
    if (!best || d < best.d) best = { x, y, d };
  }
  return best;
});
/** 빈 캔버스(`.react-flow__pane`) 한 점 — 가운데에서 바깥으로 찾는다. */
const panePoint = (page: Page) => page.evaluate(() => {
  const W = innerWidth, H = innerHeight;
  for (let r = 0; r < 400; r += 8) {
    for (const [dx, dy] of [[0, r], [0, -r], [r, 0], [-r, 0], [r, r], [-r, -r], [r, -r], [-r, r]]) {
      const x = W / 2 + dx, y = H / 2 + dy;
      if (document.elementFromPoint(x, y)?.classList.contains("react-flow__pane")) return { x, y };
    }
  }
  return null;
});
const q = (a: number[], p: number) => { if (!a.length) return NaN; const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * (s.length - 1) + 0.5))]; };

/** 한 동작을 재서 한 줄을 남긴다. */
async function measure(page: Page, row: Record<string, unknown>, act: () => Promise<void>) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const m0 = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map((x) => [x.name, x.value]));
  const z0 = await zoomOf(page);
  const t0 = await page.evaluate(() => { const pf = (window as never as { __pf: { on: boolean; frames: number[]; commits: number; wip: { n: number; ms: number; bytes: number } } }).__pf;
    pf.frames = []; pf.commits = 0; pf.wip = { n: 0, ms: 0, bytes: 0 }; pf.on = true; return performance.now(); });
  const w0 = Date.now();
  await act();
  await frame(page);
  const wall = Date.now() - w0;
  await page.waitForTimeout(300);                                          // long task 기록이 늦게 온다
  const r = await page.evaluate((t: number) => {
    const pf = (window as never as { __pf: { on: boolean; frames: number[]; lt: { s: number; d: number }[]; commits: number; wip: { n: number; ms: number; bytes: number } } }).__pf;
    pf.on = false;
    const lt = pf.lt.filter((x) => x.s >= t);
    return { frames: pf.frames, ltN: lt.length, ltMs: lt.reduce((a, x) => a + x.d, 0), commits: pf.commits, wip: pf.wip };
  }, t0);
  const m1 = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map((x) => [x.name, x.value]));
  await cdp.detach();
  const iv = r.frames.slice(1).map((t, i) => t - r.frames[i]);
  const ms = (k: string) => Math.round((m1[k] - m0[k]) * 1000);
  const out = {
    ...row, label: LABEL, run: RUN, wallMs: wall, frames: iv.length,
    p50: +q(iv, 0.5).toFixed(1), p95: +q(iv, 0.95).toFixed(1), max: +Math.max(...iv).toFixed(1), over50: iv.filter((x) => x > 50).length,
    longN: r.ltN, longMs: Math.round(r.ltMs), scriptMs: ms("ScriptDuration"), layoutMs: ms("LayoutDuration"), styleMs: ms("RecalcStyleDuration"), taskMs: ms("TaskDuration"),
    commits: r.commits, wipN: r.wip.n, wipMs: +r.wip.ms.toFixed(1), wipBytes: r.wip.bytes, zoom0: +z0.toFixed(3), zoom1: +(await zoomOf(page)).toFixed(3),
    dom: await page.locator(".react-flow__node").count(),
  };
  mkdirSync(OUT, { recursive: true });
  appendFileSync(`${OUT}/perf.jsonl`, JSON.stringify(out) + "\n");
  return out;
}

test("R8 · 전제 — 잴 200노드 문서는 서버 검증 문제 0 · 노드·선 200 이 모두 그려짐 · 카드가 겹치지 않음 (짝: 선 하나를 빼면 문제 · 줄을 좁히면 겹침 안내)", async ({ page }) => {
  const doc = chainDoc(50);
  expect(doc.nodes).toHaveLength(200);
  expect(doc.edges).toHaveLength(200);
  const v = await (await page.request.post(`${API}/allocation/graph/validate`, { data: doc })).json();
  expect(v.errors).toEqual([]);
  const broken = { ...doc, edges: doc.edges.filter((x) => x.id !== "u0.universe->r0.universe") };
  const vb = await (await page.request.post(`${API}/allocation/graph/validate`, { data: broken })).json();
  expect((vb.errors as { node_id?: string; code: string }[]).some((x) => x.node_id === "r0" && x.code === "missing_input")).toBe(true);
  await open(page, doc);
  await expect(page.locator(".react-flow__edge")).toHaveCount(200);
  await expect(page.getByText("노드가 겹쳐요")).toHaveCount(0);
  const p2 = await page.context().newPage();
  await open(p2, chainDoc(10, 100));
  await expect(p2.getByText("노드가 겹쳐요")).toBeVisible();
});

const rrStart = (page: Page) => page.evaluate(() => (window as never as { __rrStart: () => void }).__rrStart());
const rrTake = (page: Page) => page.evaluate(() => {
  const r = (window as never as { __rr: { track: boolean; cards: string[]; edges: string[]; wraps: string[]; wrapEdges: string[]; steps: string[] } }).__rr;
  const u = (a: string[]) => [...new Set(a)].sort();
  r.track = false;
  return { cards: u(r.cards), edges: u(r.edges), wraps: u(r.wraps.filter((id) => !id.includes(":"))), wrapEdges: u(r.wrapEdges), steps: u(r.steps), cardRenders: r.cards.length };
});

test("R8 · 고른 카드를 끄는 걸음마다 다시 그리는 카드는 그 카드 하나 · 선은 그 카드에 닿은 선만 (짝: 고른 카드를 바꾸면 고름이 바뀐 카드는 다시 그린다 · 계기는 처음 열 때 카드를 모두 센다)", async ({ page }) => {
  const doc = chainDoc(10);                                                // 40노드 · 40선
  await open(page, doc, true);
  // 계기가 정말 센다 — 처음 열 때는 카드 40장이 모두 그려진다(세는 길이 비어 있으면 아래 '하나만'이 늘 통과한다).
  const boot = await rrTake(page);
  expect(boot.cards).toHaveLength(40);
  expect(boot.wraps).toHaveLength(40);                                     // 감싸개·선 감싸개·이야기 단계도 세는 길이 살아 있다
  expect(boot.wrapEdges).toHaveLength(40);
  expect(boot.steps).toHaveLength(40);
  expect(boot.edges.length).toBeGreaterThan(0);
  await view(page, "fit");
  const b0 = (await page.locator('.pg-node[data-node-id="r0"]').boundingBox())!;
  const before = await page.locator('.react-flow__node[data-id="e0"]').getAttribute("aria-label");
  expect(before).toBeTruthy();
  // 먼저 고른다 — 고르기는 다른 선을 옅게 해(값이 바뀜) 선을 모두 다시 그린다. 재는 것은 그 뒤 '끄는 걸음'만.
  await page.mouse.click(b0.x + b0.width / 2, b0.y + 14);
  await expect(page.locator('.react-flow__node[data-id="r0"]')).toHaveClass(/selected/);
  await settle(page, 300);
  // 고른 뒤 다시 잰다 — 고른 카드의 도구줄('여기까지 계산')이 처음 잰 머리 자리를 덮을 수 있다(200노드에서 재서 찾음 · 기준 빌드도 같음). 카드 가운데를 잡는다.
  const b = (await page.locator('.pg-node[data-node-id="r0"]').boundingBox())!;
  const x = b.x + b.width / 2, y = b.y + b.height / 2;
  await rrStart(page);
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let i = 1; i <= 12; i++) { await page.mouse.move(x + i * 6, y + i * 3); await frame(page); }
  await page.mouse.up();
  await settle(page, 300);
  const drag = await rrTake(page);
  expect(drag.cardRenders, "끌기가 정말 일어나 끈 카드는 여러 번 다시 그려졌다").toBeGreaterThan(3);
  expect(drag.cards).toEqual(["r0"]);
  expect(drag.wraps).toEqual(["r0"]);                                       // React Flow 감싸개도 끈 카드 하나만(손잡이·설정이 늘 같은 것)
  const touching = doc.edges.filter((x) => x.source === "r0" || x.target === "r0").map((x) => x.id).sort();
  expect(drag.edges.length).toBeGreaterThan(0);
  expect(drag.edges.every((id) => touching.includes(id)), `다시 그린 선 ${drag.edges.join(", ")} ⊆ r0 에 닿은 선`).toBe(true);
  expect(drag.wrapEdges.every((id) => touching.includes(id)), `다시 그린 선 감싸개 ${drag.wrapEdges.join(", ")} ⊆ r0 에 닿은 선`).toBe(true);
  expect(drag.steps.every((id) => id === "r0"), `다시 그린 이야기 단계 ${drag.steps.join(", ")} ⊆ r0`).toBe(true);
  // 끈 카드는 정말 옮겨졌고 · 다른 카드의 이름(상태)은 그대로
  const moved = await page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}").nodes.find((n: { id: string }) => n.id === "r0").position.x);
  expect(moved).toBeGreaterThan(330);
  await expect(page.locator('.react-flow__node[data-id="e0"]')).toHaveAttribute("aria-label", before!);
  // 짝 — 값이 바뀐 카드는 다시 그린다: 다른 카드를 누르면 고름이 바뀐 두 카드(r0 풀림 · u6 고름 — r0 의 도구줄에서 먼, 화면 안 카드)
  await rrStart(page);
  const u6 = (await page.locator('.pg-node[data-node-id="u6"]').boundingBox())!;
  await page.mouse.click(u6.x + u6.width / 2, u6.y + 14);
  await settle(page, 300);
  const pick = await rrTake(page);
  expect(pick.cards).toEqual(expect.arrayContaining(["r0", "u6"]));
  expect(pick.steps).toEqual(expect.arrayContaining(["r0", "u6"]));          // 이야기 단계도 '지금 고른 것'이 바뀐 둘은 다시 그린다
  await expect(page.locator('.react-flow__node[data-id="u6"]')).toHaveClass(/selected/);
  await expect(page.locator('.react-flow__node[data-id="r0"]')).not.toHaveClass(/selected/);
});

// ── 규칙(브라우저 없이) — 값이 같으면 앞의 객체(R8) ──────────────────────────────────────
test("R8 · keepSame — 값이 같으면 앞 객체 그대로 (짝: 자리·data 칸·함수·종류가 다르면 새 객체 · 사라진 id 는 기억에서 빠짐)", () => {
  const f = () => 1;
  const params = { tickers: ["005930"] };
  const mk = (x: number, extra: Record<string, unknown> = {}) => ({ id: "a", position: { x, y: 0 }, data: { kind: "returns", params, onRun: f, ...extra } });
  const prev = new Map<string, unknown>();
  const [a1] = keepSame(prev, [mk(0)]);
  const [a2] = keepSame(prev, [mk(0)]);                                      // 새로 만들었지만 값이 같다
  expect(a2).toBe(a1);
  expect(keepSame(prev, [mk(11)])[0]).not.toBe(a1);                          // 자리가 다르다
  const [b1] = keepSame(prev, [mk(11)]);
  expect(keepSame(prev, [mk(11, { num: 2 })])[0]).not.toBe(b1);              // data 칸이 더해졌다
  const [c1] = keepSame(prev, [mk(11)]);
  expect(keepSame(prev, [{ ...mk(11), data: { ...mk(11).data, onRun: () => 1 } }])[0]).not.toBe(c1);   // 다른 함수(같은 몸이어도)
  const [d1] = keepSame(prev, [mk(11)]);
  expect(keepSame(prev, [{ ...mk(11), data: { ...mk(11).data, params: { tickers: ["005930"] } } }])[0]).toBe(d1);   // 깊이 안의 같은 값
  expect(keepSame(prev, [{ ...mk(11), data: { ...mk(11).data, params: { tickers: ["000660"] } } }])[0]).not.toBe(d1);
  keepSame(prev, []);
  expect(prev.size).toBe(0);                                                 // 사라진 id 는 기억에서 빠진다
  // sameValue — 배열 길이 · 빠진 열쇠 · 깊이를 넘으면 같은 것(===)만
  expect(sameValue([1, 2], [1, 2])).toBe(true);
  expect(sameValue([1, 2], [1, 2, 3])).toBe(false);
  expect(sameValue({ a: 1, b: undefined }, { a: 1, c: undefined })).toBe(false);
  expect(sameValue({ a: { b: { c: { d: { e: 1 } } } } }, { a: { b: { c: { d: { e: 1 } } } } })).toBe(false);
  expect(sameValue(new Date(0), new Date(0))).toBe(false);                   // 평범한 객체가 아니면 같은 것일 때만
});

// ── 확대 값 --pg-z 는 쓰는 곳에만(R8) ─────────────────────────────────────────────────
/** globals.css 에서 `var(--pg-z` 를 쓰는 규칙의 선택자 중 PG_Z_USERS 에 들지 않는 것. BEM 꾸밈(`X--y`)은 바탕 클래스 `X` 와 늘 함께 붙는다(이 코드의 규칙). */
function missingUsers(css: string): { found: number; missing: string[] } {
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const missing: string[] = [];
  let found = 0;
  for (const m of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!m[2].includes("var(--pg-z")) continue;
    for (const raw of m[1].split(",")) {
      found++;
      const sel = raw.trim().replace(/^\.pg-canvas\[data-zoom="\w+"\]\s+/, "").replace(/:[a-z-]+(\([^)]*\))?/g, "").replace(/--[\w-]+/g, "");
      if (!PG_Z_USERS.some((u) => sel === u || sel.endsWith(` ${u}`))) missing.push(raw.trim());
    }
  }
  return { found, missing };
}

test("R8 · globals.css 의 var(--pg-z) 규칙은 모두 '쓰는 곳' 목록에 든다 (짝: 목록에 없는 새 규칙은 걸린다)", () => {
  const r = missingUsers(readFileSync("src/app/globals.css", "utf8"));
  expect(r.found).toBeGreaterThanOrEqual(PG_Z_USERS.length);              // 정말 규칙을 찾았다(비어 있으면 늘 통과)
  expect(r.missing).toEqual([]);
  expect(missingUsers(".pg-new-thing { width: calc(1px / var(--pg-z, 1)); } .pg-waypoint { width: calc(1px / var(--pg-z, 1)); }").missing)
    .toEqual([".pg-new-thing"]);
  expect(pgZRule(0.5)).toBe(`.pg-canvas :is(${PG_Z_USERS.join(", ")}) { --pg-z: 0.5; }`);
});

test("R8 · --pg-z 는 물려받지 않는다 — 캔버스·쓰는 요소만 확대 값 · 카드 감싸개는 1 · 먼 보기 이름·단계 띠 머리·꺾는 점 크기는 예전 식 그대로 (짝: 확대가 바뀌면 크기도 바뀐다)", async ({ page }) => {
  const doc = chainDoc(5);
  doc.edges[0] = { ...doc.edges[0], waypoints: [{ x: 280, y: 260 }] } as Doc["edges"][number];
  await open(page, doc);
  await page.evaluate(() => localStorage.setItem("alpha_pg_view", JSON.stringify({ lanes: true, wire: "curve", minimap: false, ghosts: true })));
  await page.reload();
  await expect(page.locator(".pg-lane-head").first()).toBeVisible({ timeout: 30_000 });
  await view(page, "fit");
  const read = () => page.evaluate(() => {
    const canvas = document.querySelector<HTMLElement>(".pg-canvas")!;
    const z = new DOMMatrixReadOnly(getComputedStyle(document.querySelector(".react-flow__viewport")!).transform).a;
    const px = (sel: string, prop: "fontSize" | "width") => parseFloat(getComputedStyle(document.querySelector(sel)!)[prop]);
    return { z, canvasZ: Number(getComputedStyle(canvas).getPropertyValue("--pg-z")), level: canvas.dataset.zoom,
             wrapZ: getComputedStyle(document.querySelector(".react-flow__node")!).getPropertyValue("--pg-z").trim(),
             farName: px(".pg-node-far-name", "fontSize"), lane: px(".pg-lane-head", "fontSize"), dot: px(".pg-waypoint", "width") };
  });
  // 먼 보기 안에서 크기가 상한(28px)에 걸리지 않는 확대로 — 11/z < 28 이려면 z > 0.39 (맞춰 보기 0.2 에서 휠 여섯 칸 ≈ 0.46)
  await page.mouse.move(720, 450);
  for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, -100); await frame(page); }
  await settle(page, 400);
  const a = await read();
  expect(a.level).toBe("far");
  expect(11 / a.z).toBeLessThan(28);
  expect(a.canvasZ).toBeCloseTo(a.z, 4);                                    // 캔버스 자신은 확대 값(E2E 가 읽는 계약 그대로)
  expect(Number(a.wrapZ)).toBe(1);                                          // 물려받지 않는다 — 쓰는 곳이 아닌 요소는 처음 값
  expect(a.farName).toBeCloseTo(Math.min(28, 11 / a.z), 1);
  expect(a.lane).toBeCloseTo(Math.min(30, 13 / a.z), 1);
  expect(a.dot).toBeCloseTo(12 / a.z, 1);
  // 짝 — 한 칸 더 확대하면 값과 크기가 따라 바뀐다(물려받지 않아도 쓰는 곳은 새 값을 받는다)
  await page.mouse.wheel(0, -100);
  await settle(page, 400);
  const b = await read();
  expect(b.level).toBe("far");
  expect(b.z).toBeGreaterThan(a.z * 1.05);
  expect(b.canvasZ).toBeCloseTo(b.z, 4);
  expect(b.farName).toBeCloseTo(Math.min(28, 11 / b.z), 1);
  expect(b.farName).not.toBeCloseTo(a.farName, 1);
  expect(b.lane).toBeCloseTo(Math.min(30, 13 / b.z), 1);
  expect(b.dot).toBeCloseTo(12 / b.z, 1);
});

for (const k of [25, 50]) {
  for (const v of ["fit", "1x"] as const) {
    test(`R8 · 재기 — ${k * 4}노드 · ${v === "fit" ? "맞춰 보기" : "1배"} · 카드 끌기 · 화면 이동 · 휠 확대 (CANVAS_PERF=1 일 때만)`, async ({ page }) => {
      test.skip(!PERF, "재기는 CANVAS_PERF=1 일 때만 — 시간 숫자는 이 환경에서 흔들려 시험으로 걸지 않는다");
      test.setTimeout(240_000);
      const doc = chainDoc(k);
      await open(page, doc);
      const base = { n: k * 4, view: v };

      if (ACTIONS.has("drag")) {
      await view(page, v);
      const c = await cardPoint(page);
      expect(c, "화면 안에 다 보이는 카드가 있어야 끌기를 잰다").not.toBeNull();
      const drag = await measure(page, { ...base, action: "drag" }, async () => {
        await page.mouse.move(c!.x, c!.y);
        await page.mouse.down();
        for (let i = 1; i <= STEPS; i++) { await page.mouse.move(c!.x + i * 4, c!.y + i * 2); await frame(page); }
        await page.mouse.up();
      });
      expect(drag.wipN, "놓은 뒤에는 문서가 한 번은 보존돼야 한다(끌기가 정말 일어났는지)").toBeGreaterThan(0);
      }

      if (ACTIONS.has("pan")) {
      await view(page, v);
      const p = await panePoint(page);
      expect(p, "빈 캔버스 한 점이 있어야 화면 이동을 잰다").not.toBeNull();
      await measure(page, { ...base, action: "pan" }, async () => {
        await page.mouse.move(p!.x, p!.y);
        await page.mouse.down();
        for (let i = 1; i <= STEPS; i++) { await page.mouse.move(p!.x - i * 5, p!.y - i * 3); await frame(page); }
        await page.mouse.up();
      });
      }

      if (ACTIONS.has("wheel")) {
      await view(page, v);
      let mid = 0;
      const zr = await measure(page, { ...base, action: "wheel" }, async () => {
        await page.mouse.move(720, 450);
        for (let i = 0; i < WHEELS; i++) {
          await page.mouse.wheel(0, i < WHEELS / 2 ? -100 : 100); await frame(page);
          if (i === WHEELS / 2 - 1) mid = await zoomOf(page);
        }
      });
      expect(mid, "휠 확대가 정말 일어났는지 — 가운데에서 시작보다 커야 한다").toBeGreaterThan(zr.zoom0 * 1.5);
      }
    });
  }
}
