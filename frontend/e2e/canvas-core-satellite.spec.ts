import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "./fixtures";
import { contrastAudit, trackErrors, uniq, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ═════════════════════════════════════════════════════════════════════════════════════════════════
// 캔버스 '매매 몫 결합'(K4 · 2026-11-17 · 구현 계획 2026-11-16 §7.5) — 정책 백테스트(핵심) + 분봉 결과 조회(위성) + 국면별 매매 몫
// 자료: 두 달에 걸친 손 계산 열흘(2026-02-23 ~ 03-06 · 035720 · `seed_bars.py` 의 앞선 닷새 + 손 계산 열흘의 앞 닷새) ·
// 정책 백테스트는 모의 시세(기준일 고정 2026-06-30) · 국면은 E2E 서버(모의 게이트)의 합성 지수 — 확률은 같은 서버의 시장 국면 문에 묻는다.
// 거는 것:
//  · 칸은 비어서 시작하고 빈 칸으로 계산하면 서버 사유 · 국면 수 2 면 셋째 · 넷째 칸이 없다 ↔ 4 면 있다 · 자본 부족은 서버 사유 ·
//    칸에 적은 값이 그대로 계산에 실린다
//  · 결과 판: 두 판의 값 = 서버 값(서버 순서 · 어느 줄도 칠하지 않는다) · 몫의 길 = 시장 국면 문의 확률 × 표 · 몫 고정 = 날 가중 평균 ·
//    첫날 옮긴 몫 = 첫 목표 몫(핵심에서 옮긴다) · 합성 알림 · 한계 문장 = 서버 글 · 300px 판에서 표는 넘김 상자 안에서만 넘는다
//  · 라이트/다크 AA · 문체
// ═════════════════════════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const FROM = "2026-02-23", TO = "2026-03-06";
const STARTS = ["2026-02-23", "2026-03-02"];          // 몫을 정하는 날 — 겹친 기간의 첫날 · 3월의 첫 거래일
const DAYS_IN = [5, 5];                               // 그 몫이 적용된 거래일 수(2월 닷새 · 3월 닷새)
const RULE = { entry: { op: "cross_up", args: [{ ind: "close" }, { const: 10050 }] } };
const AMOUNT = 1_003_000;                             // 99주(체결가 10,080) · 자본 하한 = 1,003,000 × 1.00015 = 1,003,150.45
const PARAMS = { tickers: ["035720"], start_date: FROM, end_date: TO, rule: "custom", custom_rule: RULE,
  amount: AMOUNT, commission_bp: 1.5, slippage_ticks: 1, unknown_market: "KOSPI", unknown_instrument: "stock" };
const TABLE = [30, 10];                               // 국면 1 · 국면 2 일 때 매매 몫(%) — 사용자가 적는 값(도구는 정하지 않는다)
const MIX = { index: "KOSPI", k: 2, share_1: TABLE[0], share_2: TABLE[1], capital: 2_000_000 };
const BLANK = "지수를 고르십시오. 국면을 계산할 지수가 필요합니다.";
const SHORT = "매매 몫 자본이 모자랍니다. 자본 1,000,000원 · 필요 1,003,150원(진입 금액 × 동시에 보유할 수 있는 종목 수 1 × "
  + "(1 + 수수료율)). 그 자본으로 살 수 없는 진입이 있어 합치지 않았습니다.";
const MINUS = "−";
const fmt = (v: number, d: number) => v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
/** 화면의 퍼센트 서식(krFormat.pct · signedPct) — 보이는 자릿수로 0 이면 부호가 없다. */
const pct = (v: number, d: number) => `${Number(fmt(Math.abs(v), d).replace(/,/g, "")) === 0 ? "" : v < 0 ? MINUS : ""}${fmt(Math.abs(v), d)}%`;
const signed = (v: number, d: number) => `${Number(fmt(Math.abs(v), d).replace(/,/g, "")) === 0 ? "" : v < 0 ? MINUS : "+"}${fmt(Math.abs(v), d)}%`;

type Month = { date: string; probs_pct: number[]; target_pct: number; moved_pct: number; cost_pct: number };
type Panel = { key: string; label: string; total_return_pct: number; max_drawdown_pct: number; avg_share_pct: number; cost_pct: number };
type View = { months: Month[]; panels: Panel[]; fixed_share_pct: number; notes: string[]; synthetic: boolean;
  grades: { trial: string | null; regime: string | null; core_mock: boolean | null }; compare: { labels: { a: string; b: string } };
  request: { name: string; k: number; table_pct: number[]; capital: number; cost_bps: number }; needed_capital: number;
  window: { from: string; to: string; days: number };
  perf_label: { kind: string; kind_reason: string | null; data_real: boolean | null; data_reason: string | null } };

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

/** 정책 백테스트(모의 시세 · 기준일 고정) → 핵심 · 분봉 결과 조회 → 위성 · 매매 몫 결합. 국면 · 표 · 자본은 `mix` 그대로. */
async function importDoc(page: Page, key: string, mix: Record<string, unknown>) {
  const at = (x: number, y: number) => ({ x: x * 280, y: y * 200 });
  const nodes = [
    { id: "u", type: "universe", position: at(0, 0), params: { tickers: ["005930", "000660", "035420"] } },
    { id: "r", type: "returns", position: at(1, 0), params: { lookback_days: 252, as_of: "2026-06-30" } },
    { id: "e", type: "estimate", position: at(2, 1), params: {} },
    { id: "o", type: "optimizer", position: at(3, 0), params: {} },
    { id: "b", type: "backtest", position: at(4, 0), params: { rebalance: "M", cost_bps: 10 } },
    { id: "l", type: "intraday_load", position: at(4, 1), params: { trial_key: key } },
    { id: "m", type: "core_satellite_mix", position: at(5, 0), params: mix },
  ];
  const edges = [e("u", "universe", "r", "universe"), e("r", "returns", "e", "returns"), e("r", "returns", "o", "returns"),
    e("e", "belief", "o", "belief"), e("r", "returns", "b", "returns"), e("o", "weights", "b", "weights"),
    e("b", "backtest", "m", "core"), e("l", "run", "m", "run")];
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: { name: "매매 몫 결합" }, edges, nodes };
  await page.locator(".pg-import-input").setInputFiles({ name: "mix.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
  await expect(node(page, "m")).toBeVisible();
  await page.locator(".react-flow__controls-fitview").click();                              // 일곱 노드가 다 보이게 — 끝 노드를 누를 수 있게
}

/** 계산하기 — 보낸 문서의 `m` 칸과 답을 함께 돌려준다(칸에 적은 값이 그대로 실렸는지 본다). */
async function run(page: Page) {
  const req = page.waitForRequest((r) => r.url().includes("/allocation/graph/run") && r.method() === "POST", { timeout: 60_000 });
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 240_000 });
  await page.locator(".pg-run").click();
  const sent = (await req).postDataJSON() as { nodes: { id: string; params?: Record<string, unknown> }[] };
  const out = await (await resp).json();
  return { out, sentMix: sent.nodes.find((x) => x.id === "m")?.params ?? null };
}

/** 같은 서버의 시장 국면 문 — 노드와 같은 지수 · 국면 수 · 기간. 몫을 정하는 날의 확률. */
async function probsAt(page: Page, token: string): Promise<number[][]> {
  const q = new URLSearchParams({ index: "KOSPI", k: "2", from: FROM, to: TO });
  const r = await page.request.get(`${API}/intraday/market-regime?${q}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  const days = (await r.json()).days as { date: string; probs: number[] | null }[];
  return STARTS.map((d) => {
    const p = days.find((x) => x.date === d)?.probs ?? null;
    expect(p, `${d} 의 국면 확률`).not.toBeNull();
    return p as number[];
  });
}

/** 캔버스의 단추와 같은 두 문(계산 → 저장)으로 위성 시행 하나를 남기고 그 열쇠를 돌려준다(같은 설정 = 같은 시행). */
async function keptTrial(page: Page, token: string): Promise<string> {
  const headers = { Authorization: `Bearer ${token}` };
  const graph = { format: "project-alpha.portfolio-graph", version: 1, edges: [], nodes: [{ id: "is", type: "intraday_setup", params: PARAMS }] };
  const ran = await page.request.post(`${API}/allocation/graph/run`, { data: graph, headers, timeout: 120_000 });
  expect(ran.ok(), await ran.text()).toBe(true);
  const hash = (await ran.json()).nodes.is.view_hash as string;
  const saved = await page.request.post(`${API}/allocation/graph/save`, { data: { graph, node_id: "is", preview_hash: hash }, headers, timeout: 120_000 });
  const body = await saved.json();
  expect(body.ok, body.message).toBe(true);
  return body.saved_id as string;
}

/**
 * 판(.pg-side) 안의 결과 — 판 밖으로 넘친 것 가운데 넘김 상자(표의 `.tj-scroll-x` · 낙폭 구간 표의 `.pf-eps-wrap`) 밖의 것 ·
 * 상자가 모두 판 안에 있는지 · 몫의 길 표의 상자가 실제로 넘기는지(전제: 여섯 칸 표는 300px 판에 들지 않는다 — 공허하지 않게.
 * 두 판 표(다섯 칸)는 300px 에 들어간다 — 첫 실행에서 잼).
 */
const spillOf = (page: Page) => page.evaluate(() => {
  const side = document.querySelector(".pg-side")!; const right = side.getBoundingClientRect().right + 1;
  const over = [...side.querySelectorAll(".pg-csm *")].filter((el) => el.getClientRects().length && el.getBoundingClientRect().right > right);
  const boxes = [...side.querySelectorAll(".pg-csm .tj-scroll-x, .pg-csm .pf-eps-wrap")];
  const months = side.querySelector(".pg-csm .pg-csm-months")?.closest(".tj-scroll-x");
  return { outside: over.filter((el) => !el.closest(".tj-scroll-x, .pf-eps-wrap")).map((el) => String(el.getAttribute("class"))),
           boxesInside: boxes.length === 4 && boxes.every((b) => b.getBoundingClientRect().right <= right),
           monthsScrolls: !!months && months.scrollWidth > months.clientWidth };
});
/**
 * 머리 줄(.pg-kv)의 이름 칸 가운데 글자가 여러 줄로 쪼개진 것 — 없어야 한다(긴 값이 이름 칸을 한 글자 폭으로 누르지 않는다).
 * 상자 높이가 아니라 ★글자의 줄 수★를 센다 — 행이 flex 라 값 칸이 여러 줄이면 이름 칸 상자도 그 높이로 늘어난다(첫 측정의 내 실수).
 */
const brokenNames = (page: Page) => page.locator(".pg-side .pg-csm .pg-kv dt").evaluateAll((els) => els.filter((el) => {
  const range = document.createRange();
  range.selectNodeContents(el);
  return new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size > 1;
}).map((el) => el.textContent));
/**
 * 몫의 길 표에서 이웃한 두 칸의 ★글자★ 사이 가장 좁은 간격(px). 300px 판에서는 표가 넘김 상자보다 넓어 남는 폭이 없고,
 * 공용 `.pg-table` 의 칸 여백은 좌우 0 이라 칸이 서로 붙었다("29.8%24.04%" — 스크린샷 검수에서 찾음 · 그때 잰 값 0px).
 */
const tightestGap = (page: Page) => page.locator(".pg-side .pg-csm-months").evaluate((t) => {
  const text = (el: Element) => { const r = document.createRange(); r.selectNodeContents(el); return r.getBoundingClientRect(); };
  let min = Infinity;
  for (const row of t.querySelectorAll("tr")) {
    const cells = [...row.children];
    for (let i = 1; i < cells.length; i++) min = Math.min(min, text(cells[i]).left - text(cells[i - 1]).right);
  }
  return Math.round(min);
});
/**
 * 이 판의 문장(설명 줄 · 서버 한계 문장)이 ★낱말 가운데서★ 꺾인 자리 — 없어야 한다("…대비입니 / 다." · "1 / 로" — 스크린샷 검수에서 찾음).
 * 글자마다 상자(Range)를 재어, 앞 글자 상자의 아래보다 아래에서 시작하면 새 줄이다. 그 사이에 빈칸이 하나도 없으면 낱말 가운데서 꺾인 것이다.
 * 짝: 같은 판의 문장 가운데 실제로 줄이 바뀐 것이 있어야 한다(한 줄짜리만 보면 공허하다) — `wrapped` 로 센다.
 */
const midWordBreaks = (page: Page) => page.locator(".pg-side .pg-csm .pg-note, .pg-side .pg-csm-notes li").evaluateAll((els) => {
  const breaks: string[] = [];
  let wrapped = 0;
  for (const el of els) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let prev: { ch: string; bottom: number } | null = null, space = false, lines = 1;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const s = n.textContent ?? "";
      for (let i = 0; i < s.length; i++) {
        if (/\s/.test(s[i])) { space = true; continue; }
        const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1);
        const box = r.getClientRects()[0];
        if (!box) continue;
        if (prev && box.top >= prev.bottom - 2) {                       // 새 줄
          lines += 1;
          if (!space) breaks.push(`${prev.ch}|${s[i]} · ${(el.textContent ?? "").slice(0, 24)}`);
        }
        prev = { ch: s[i], bottom: box.bottom }; space = false;
      }
    }
    if (lines > 1) wrapped += 1;
  }
  return { breaks, wrapped };
});

test("설정: 칸은 비어서 시작하고 빈 칸은 서버 사유 · 국면 수 2 면 셋째 · 넷째 칸이 없고 4 면 있다 · 자본 부족은 서버 사유 · 적은 값 그대로 계산한다", async ({ page }) => {
  test.setTimeout(420_000);
  const sink = trackErrors(page);
  await page.addInitScript(() => { try { localStorage.setItem("alpha_pg_panels", JSON.stringify({ left: true, right: true, rightW: 300 })); } catch { /* */ } });
  const token = await login(page);
  const key = await keptTrial(page, token);
  await openCanvas(page);
  await importDoc(page, key, {});

  let { out } = await run(page);
  expect(out.nodes.b.status, out.nodes.b.reason).toBe("ok");
  expect(out.nodes.l.status, out.nodes.l.reason).toBe("ok");
  expect(out.nodes.m.status).toBe("failed");
  expect(out.nodes.m.reason).toBe(BLANK);                                                   // 지어내지 않는다 — 빈 칸은 실패
  await node(page, "m").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-node-status-why")).toHaveText(BLANK);
  await expect(page.locator(".pg-side .pg-csm")).toHaveCount(0);

  await tab(page, "settings");
  const field = (name: string) => page.locator(`.pg-side .pg-basic-field[data-field="${name}"]`);
  await expect(field("index").locator('.pg-choice[aria-pressed="true"]')).toHaveAttribute("data-choice", "");   // '정하지 않음'
  for (const name of ["k", "share_1", "share_2", "capital"]) await expect(field(name).locator("input"), name).toHaveValue("");
  await expect(field("share_3")).toHaveCount(0);
  await expect(field("share_4")).toHaveCount(0);
  await field("index").locator('.pg-choice[data-choice="KOSPI"]').click();
  await field("k").locator("input").fill("2");
  await expect(field("share_1")).toHaveCount(1);
  await expect(field("share_3")).toHaveCount(0);                                            // 국면 수 2 — 셋째 · 넷째 칸은 뜻이 없다
  await expect(field("share_4")).toHaveCount(0);
  await field("k").locator("input").fill("4");
  await expect(field("share_3")).toHaveCount(1);                                            // 짝: 4 면 보인다
  await expect(field("share_4")).toHaveCount(1);
  await expect(field("share_3").locator("input")).toHaveValue("");                          // 보여도 비어 있다
  await field("k").locator("input").fill("2");
  await expect(field("share_3")).toHaveCount(0);
  await field("share_1").locator("input").fill(String(TABLE[0]));
  await field("share_2").locator("input").fill(String(TABLE[1]));
  await field("capital").locator("input").fill("1000000");
  expect(await page.locator(".pg-side").evaluate((el) => Math.round(el.getBoundingClientRect().width))).toBe(300);

  ({ out } = await run(page));
  expect(out.nodes.m.status).toBe("failed");
  expect(out.nodes.m.reason).toBe(SHORT);                                                   // 자본 1,000,000 < 하한 1,003,150.45
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-node-status-why")).toHaveText(SHORT);

  await tab(page, "settings");
  await field("capital").locator("input").fill(String(MIX.capital));
  const done = await run(page);
  expect(done.sentMix).toEqual(MIX);                                                        // 칸에 적은 값 그대로 — 화면이 값을 보태거나 바꾸지 않는다
  expect(done.out.nodes.m.status, done.out.nodes.m.reason).toBe("ok");
  const v = done.out.nodes.m.view as View;
  expect(v.request.table_pct).toEqual(TABLE);
  expect(v.needed_capital).toBe(1_003_150.45);
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-csm-panels tbody tr")).toHaveCount(2);
  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`결과 판(${theme}): 두 판 = 서버 값 · 몫의 길 = 시장 국면 문의 확률 × 표 · 몫 고정 = 날 가중 평균 · 300px 넘침 0 · 대비 · 문체`, async ({ page }) => {
    test.setTimeout(300_000);
    const sink = trackErrors(page);
    await page.addInitScript((t) => {
      try { localStorage.setItem("alpha_theme", t); localStorage.setItem("alpha_pg_panels", JSON.stringify({ left: true, right: true, rightW: 300 })); } catch { /* */ }
    }, theme);
    const token = await login(page);
    const key = await keptTrial(page, token);
    const probs = await probsAt(page, token);
    await openCanvas(page);
    await importDoc(page, key, MIX);
    const { out } = await run(page);
    const m = out.nodes.m;
    expect(m.status, m.reason).toBe("ok");
    const v = m.view as View;

    // 서버의 몫 — 같은 서버의 시장 국면 문이 준 확률 × 표 · 날 가중 평균 · 첫날은 핵심에서 옮긴다
    expect([v.window.from, v.window.to, v.window.days]).toEqual([FROM, TO, 10]);
    expect(v.months.map((x) => x.date)).toEqual(STARTS);
    const targets = probs.map((p) => p[0] * TABLE[0] + p[1] * TABLE[1]);
    v.months.forEach((mo, i) => {
      expect(Math.abs(mo.probs_pct[0] - probs[i][0] * 100), `${mo.date} 국면 1`).toBeLessThanOrEqual(0.0051);   // 서버는 소수 둘째 자리로 싣는다
      expect(Math.abs(mo.probs_pct[1] - probs[i][1] * 100), `${mo.date} 국면 2`).toBeLessThanOrEqual(0.0051);
      expect(mo.target_pct).toBeCloseTo(targets[i], 3);
    });
    const weighted = (targets[0] * DAYS_IN[0] + targets[1] * DAYS_IN[1]) / (DAYS_IN[0] + DAYS_IN[1]);
    expect(v.fixed_share_pct).toBeCloseTo(weighted, 3);
    expect(v.months[0].moved_pct).toBeCloseTo(v.months[0].target_pct, 4);                    // 시작은 전부 핵심 — 첫 목표만큼 옮긴다
    expect(v.months[0].cost_pct).toBeCloseTo(v.months[0].target_pct * v.request.cost_bps / 1e4, 5);
    expect(v.panels.map((p) => p.key)).toEqual(["regime", "fixed"]);
    expect(v.grades).toEqual({ trial: "E3", regime: "E0", core_mock: true });               // 손 계산 분봉(실제 분봉 경로) · 모의 지수 · 모의 시세
    expect(v.synthetic).toBe(true);                                                          // 연습용

    await node(page, "m").click();
    await tab(page, "detail");
    const panel = page.locator(".pg-side .pg-csm");
    await expect(panel).toBeVisible();
    // 성과 숫자는 무슨 성과인지 말한다(Z4 계약) — 서버 라벨 그대로: 과거 위의 시뮬레이션(백테스트) · 합성 자료. 판 전체에 한 번만
    // (패널의 공용 라벨과 겹쳐 두 번 그리지 않는다 — 첫 판은 이 노드가 라벨을 내지도 그리지도 않아 게이트의 계약 시험에서 찾음).
    expect(v.perf_label).toEqual({ kind: "backtest", kind_reason: null, data_real: false, data_reason: null });
    const label = page.locator(".pg-side .perf-label");
    await expect(label).toHaveCount(1);
    await expect(panel.locator(".perf-label")).toHaveClass(/perf-label--backtest/);
    await expect(panel.locator(".perf-label .perf-label__kind")).toHaveText("백테스트");
    await expect(panel.locator(".perf-label .perf-label__data")).toHaveText("합성데이터");
    await expect(panel.locator(".tx-notice[data-tone='practice'] .tx-notice-t")).toHaveText("합성 자료 위의 숫자입니다");
    await expect(panel.locator(".tx-notice[data-tone='practice'] .tx-notice-b"))
      .toHaveText("모의 시세 · 모의 지수 · 합성 분봉 가운데 하나 이상으로 계산했습니다. 계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.");
    await expect(panel.locator(".pg-kv [data-server]").first()).toHaveText(`${v.request.name} · 2개`);
    const kv = (k: string) => panel.locator(".pg-kv > div").filter({ has: page.locator("dt", { hasText: k }) }).locator("dd");
    await expect(kv("자료 등급")).toHaveText("시행 E3 · 국면 E0 · 핵심 모의 시세");

    // 두 판 — 서버 순서 · 서버 값 · 어느 줄도 칠하지 않는다
    const rows = panel.locator(".pg-csm-panels tbody tr");
    await expect(rows).toHaveCount(2);
    for (const [i, p] of v.panels.entries()) {
      const row = rows.nth(i);
      await expect(row).toHaveAttribute("data-k", p.key);
      await expect(row).not.toHaveAttribute("class", /./);
      await expect(row.locator("th")).toHaveText(`${p.label} 판`);
      await expect(row.locator("td").nth(0)).toHaveText(signed(p.total_return_pct, 2));
      await expect(row.locator("td").nth(1)).toHaveText(pct(p.max_drawdown_pct, 2));
      await expect(row.locator("td").nth(2)).toHaveText(pct(p.avg_share_pct, 1));
      await expect(row.locator("td").nth(3)).toHaveText(pct(p.cost_pct, 3));
    }
    await expect(panel.locator(".pg-csm-fixed")).toContainText(`목표 몫 ${pct(v.fixed_share_pct, 2)}(국면 몫 판의 날 가중 평균)`);

    // 몫의 길 — 날마다 확률 · 목표 · 옮긴 몫 · 비용
    const mrows = panel.locator(".pg-csm-months tbody tr");
    await expect(mrows).toHaveCount(2);
    for (const [i, mo] of v.months.entries()) {
      const row = mrows.nth(i);
      await expect(row).toHaveAttribute("data-date", mo.date);
      await expect(row.locator("th")).toHaveText(mo.date);
      const cells = row.locator("td");
      await expect(cells).toHaveCount(2 + 3);
      await expect(cells.nth(0)).toHaveText(pct(mo.probs_pct[0], 1));
      await expect(cells.nth(1)).toHaveText(pct(mo.probs_pct[1], 1));
      await expect(cells.nth(2)).toHaveText(pct(mo.target_pct, 2));
      await expect(cells.nth(3)).toHaveText(pct(mo.moved_pct, 2));
      await expect(cells.nth(4)).toHaveText(pct(mo.cost_pct, 3));
    }
    await expect(panel.locator(".pg-csm-notes li")).toHaveText(v.notes);                     // 한계 문장 = 서버 글
    await expect(panel.locator(".pf-cmp")).toHaveCount(1);                                    // 두 곡선 겹쳐 보기(같은 부품)
    expect(v.compare.labels).toEqual({ a: "국면 몫", b: "몫 고정" });                          // A = 국면 몫 판의 곡선(서버 순서)
    await expect(panel.locator(".pg-note").filter({ hasText: "첫날 끝 값을 1로" }))
      .toHaveText(`A ${v.compare.labels.a} 판 · B ${v.compare.labels.b} 판. 각 판의 첫날 끝 값을 1로 맞췄습니다. 기간 수익률은 시작 자본 대비입니다.`);

    // 좁은 판(300px): 표는 판 안의 넘김 상자에서만 옆으로 넘는다 — 상자 밖으로 넘친 것 0 · 상자는 판 안 · 두 상자 모두 실제로 넘긴다
    expect(await page.locator(".pg-side").evaluate((el) => Math.round(el.getBoundingClientRect().width))).toBe(300);
    expect(await spillOf(page), "결과 판의 넘침").toEqual({ outside: [], boxesInside: true, monthsScrolls: true });
    expect(await brokenNames(page), "머리 줄의 이름 칸이 쪼개진 것").toEqual([]);
    expect(await tightestGap(page), "몫의 길 표에서 이웃한 칸 글자 사이의 가장 좁은 간격(px)").toBeGreaterThanOrEqual(6);
    const words = await midWordBreaks(page);
    expect(words.breaks, "판의 문장이 낱말 가운데서 꺾인 자리").toEqual([]);
    expect(words.wrapped, "줄이 바뀐 문장 수(0 이면 위 검사가 공허하다)").toBeGreaterThan(2);
    // 낙폭 구간 표 둘은 좁은 판에서 위아래로 놓인다(나란히 두면 칸마다 절반 폭에서 넘긴다)
    const eps = await panel.locator(".pf-cmp-eps > div").evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().left)));
    expect(eps).toHaveLength(2);
    expect(eps[0]).toBe(eps[1]);

    for (const root of [".pg-side .pg-csm"]) {
      const a = (await page.evaluate(contrastAudit(root))) as AuditResult;
      expect(a.checked, root).toBeGreaterThan(3);
      expect(a.low, `${theme} ${root}`).toEqual([]);
      const voice = (await page.evaluate(voiceAudit(root))) as VoiceResult;
      expect(voice.checked, root).toBeGreaterThan(3);
      expect(voice.haeyo, root).toEqual([]);
      expect(voice.dash, root).toEqual([]);
      expect(voice.banned, root).toEqual([]);
    }
    expect(uniq(sink.api404), "404").toEqual([]);
    expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
    expect(uniq(sink.pageErrors), "page errors").toEqual([]);
    expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
  });
}
