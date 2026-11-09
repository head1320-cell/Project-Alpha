import { test, expect, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 캔버스 성과 그림 문법 — 백테스트 계열 셋 (2026-11-09 · 설계 `docs/superpowers/specs/2026-11-09-canvas-performance-viz-design.md`)
// ─────────────────────────────────────────────────────────────────────────────
//  (a) 제목·헤드라인은 서버 explain 그대로(화면이 문장을 짓지 않는다)
//  (b) 그림 하나 = 포트폴리오 선 + 낙폭(물속) + 증거 띠(리밸런싱 눈금 수 = n_rebalances · 기준일)
//  (c) 읽는 줄 — 기본은 마지막 날 · 키보드로 날짜가 바뀐다 · 떠다니는 툴팁 0 · title= 0
//  (d) 해마다 막대 수 = 서버 periods.yearly · 부분 연도는 '일부' 라고
//  (e) 벤치마크가 없으면 범례가 그렇게 말한다 — 짝: 있으면 벤치마크 끝값
//  (f) 합성 데이터면 띠 범례에 '연습용 데이터' — 짝: 실데이터면 없다
//  (g) 표로 보기 — 그림의 쌍둥이 표, 같은 값
//  (h) 대비 라이트·다크 AA 미달 0
//  (i) 기존 계약 그대로 — .pg-kv 총수익 · .pg-chart 보임 · [data-lookahead] · .pg-bt-cf
//  (j) 백테스트 불러오기 — 같은 문법 · 낙폭은 서버가 % 로 옮긴 값 · 벤치마크 · 리밸런싱을 모르면 띠가 말하지 않는다
//  (k) 전략 묶음 — 같은 문법(서버 모양 픽스처) · 낙폭은 같은 물속 · 벤치마크 없음 · 리밸런싱 날짜 없음 · 아래 절 그대로
// ═══════════════════════════════════════════════════════════════════════════════

const API = "http://localhost:8000/api/v1";
const DOC = { format: "project-alpha.portfolio-graph", version: 1, meta: {}, edges: [] as unknown[] };
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();

type View = Record<string, unknown>;
type RunBody = { ok: boolean; nodes: Record<string, { status: string; reason: string | null; view: View | null; explain?: {
  title: string; headline?: { label: string; value: number | null; unit: string; text: string } | null } | null }> };

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function run(page: Page): Promise<RunBody> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}

async function patchRun(page: Page, fn: (body: RunBody) => void) {
  await page.unroute("**/api/v1/allocation/graph/run**");
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as RunBody;
    fn(body);
    await route.fulfill({ response: res, json: body });
  });
}

async function detail(page: Page, id: string) {
  await node(page, id).click();
  await tab(page, "detail");
}

async function importText(page: Page, name: string, text: string) {
  await page.locator(".pg-import-input").setInputFiles({ name, mimeType: "application/json", buffer: Buffer.from(text) });
}

const side = (page: Page) => page.locator(".pg-side");
const strs = (v: unknown) => (Array.isArray(v) ? (v as string[]) : []);
const nums = (v: unknown) => (Array.isArray(v) ? (v as number[]) : []);
/** 새 부품 안의 title= 만 — 아래 절(전략 비중 표 등)의 이전부터 있던 title= 과 성과 라벨(`shared/ui/PerfLabel`)은 이 범위 밖이다. */
const NEW_PART_TITLES = ".pf-head [title]:not(.perf-label), .pf-fig [title], .pf-years [title], .pf-metrics [title], .pf-table [title]";

/** 세 노드가 ★같은 문법★으로 그려졌는가 — 머리(서버 explain) · 그림 하나 · 읽는 줄(키보드) · 해마다 · 표 쌍둥이 · recharts·툴팁 0 · 대비. */
async function sameGrammar(page: Page, n: RunBody["nodes"][string], dates: string[], hasDd: boolean) {
  const ex = n.explain!;
  await expect(side(page).locator(".pf-title")).toHaveText(ex.title);
  await expect(side(page).locator(".pf-hero")).toContainText(ex.headline!.text);
  const fig = side(page).locator(".pf-curve");
  await expect(fig).toBeVisible();
  await expect(fig.locator(".pf-line-port")).toHaveCount(1);
  await expect(fig.locator(".pf-dd-area")).toHaveCount(hasDd ? 1 : 0);
  const read = side(page).locator(".pf-read");
  await expect(read).toContainText(dates[dates.length - 1]);
  await fig.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(read).toContainText(dates[dates.length - 2]);
  await page.keyboard.press("End");
  await expect(read).toContainText(dates[dates.length - 1]);
  const yearly = (n.view!.periods as { yearly: unknown[] }).yearly;
  expect(yearly.length, "서버가 해마다 수익을 줘야 이 시험이 공허하지 않다").toBeGreaterThan(0);
  await expect(side(page).locator(".pf-year")).toHaveCount(yearly.length);
  await expect(side(page).locator(".recharts-wrapper, .recharts-tooltip-wrapper")).toHaveCount(0);
  await expect(side(page).locator(NEW_PART_TITLES)).toHaveCount(0);
  await expect(side(page).locator(".pf-kv")).toContainText("총수익");
  await expect(side(page).locator(".pg-perf .perf-label")).toBeVisible();
  await expect(side(page).locator(".pg-result")).not.toContainText("NaN");
  const det = side(page).locator("details.pf-table");
  await det.locator("summary").click();
  await expect(det.locator("table.pf-table-curve tbody tr")).toHaveCount(dates.length);
  await det.locator("summary").click();
  await side(page).locator("details.pf-metrics summary").click();
  for (const dark of [false, true]) {
    await page.evaluate((d) => document.documentElement.classList.toggle("dark", d), dark);
    await page.waitForTimeout(150);
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
    expect(audit.checked, "검사한 텍스트 노드 수").toBeGreaterThan(40);
    expect(audit.low, `${dark ? "dark" : "light"} AA 미달`).toEqual([]);
    if (dark) expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  }
  await page.evaluate(() => document.documentElement.classList.remove("dark"));
}

test("(a) 제목·헤드라인은 서버 explain 그대로", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const ex = body.nodes.backtest.explain!;
  await detail(page, "backtest");
  await expect(side(page).locator(".pf-title")).toHaveText(ex.title);
  await expect(side(page).locator(".pf-hero")).toContainText(ex.headline!.text);
  await expect(side(page).locator(".pf-hero")).toContainText(ex.headline!.label);
});

test("(b) 그림 하나 — 포트폴리오 선 · 낙폭(물속) · 증거 띠의 리밸런싱 눈금 수 = n_rebalances · 기준일 표식", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const v = body.nodes.backtest.view!;
  await detail(page, "backtest");
  const fig = side(page).locator(".pf-curve");
  await expect(fig).toBeVisible();
  await expect(fig.locator(".pf-line-port")).toHaveCount(1);
  await expect(fig.locator(".pf-dd-area")).toHaveCount(1);
  await expect(fig.locator(".pf-strip-rebal")).toHaveCount(Number(v.n_rebalances));
  const asOf = (v.coverage as { as_of_effective?: string } | undefined)?.as_of_effective;
  await expect(fig.locator(".pf-strip-asof")).toHaveCount(asOf ? 1 : 0);
  // 두 계열이면 범례가 늘 있다(색만으로 가르지 않는다).
  await expect(side(page).locator(".pf-legend")).toContainText("포트폴리오");
});

test("(c) 읽는 줄 — 기본은 마지막 날 · ArrowLeft/Home 으로 날짜가 바뀐다 · 떠다니는 툴팁 0 · title= 0", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const dates = strs(body.nodes.backtest.view!.dates);
  await detail(page, "backtest");
  const read = side(page).locator(".pf-read");
  await expect(read).toContainText(dates[dates.length - 1]);
  await side(page).locator(".pf-curve").focus();
  await page.keyboard.press("ArrowLeft");
  await expect(read).toContainText(dates[dates.length - 2]);
  await page.keyboard.press("Home");
  await expect(read).toContainText(dates[0]);
  await expect(read).toContainText("포트폴리오");
  await expect(side(page).locator(".recharts-tooltip-wrapper")).toHaveCount(0);
  // 새 부품에는 title= 이 없다(ADR-003 §2.4). 성과 라벨(`shared/ui/PerfLabel`)의 title= 은 이전부터의 것이라 이 범위 밖이다.
  await expect(side(page).locator(".pg-pf [title]:not(.perf-label)")).toHaveCount(0);
});

test("(d) 해마다 막대 수 = 서버 periods.yearly · 부분 연도는 '일부' · 값은 서버 그대로", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const yearly = (body.nodes.backtest.view!.periods as { yearly: { year: number; return_pct: number; partial: boolean }[] }).yearly;
  expect(yearly.length, "서버가 해마다 수익을 줘야 이 시험이 공허하지 않다").toBeGreaterThan(0);
  await detail(page, "backtest");
  const rows = side(page).locator(".pf-year");
  await expect(rows).toHaveCount(yearly.length);
  for (let i = 0; i < yearly.length; i++) {
    const y = yearly[i];
    await expect(rows.nth(i)).toContainText(String(y.year));
    await expect(rows.nth(i)).toContainText(`${y.return_pct >= 0 ? "+" : "−"}${Math.abs(y.return_pct).toFixed(1)}%`);
    await expect(rows.nth(i)).toHaveAttribute("data-partial", String(y.partial));
    if (y.partial) await expect(rows.nth(i)).toContainText("일부");
    else await expect(rows.nth(i)).not.toContainText("일부");
  }
});

test("(e) 벤치마크가 없으면 범례가 그렇게 말한다 — 짝: 있으면 벤치마크 끝값", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const v = body.nodes.backtest.view!;
  await detail(page, "backtest");
  const legend = side(page).locator(".pf-legend");
  if (Array.isArray(v.bench_curve)) await expect(legend).toContainText("벤치마크");
  await patchRun(page, (b) => { b.nodes.backtest.view!.bench_curve = null; b.nodes.backtest.view!.benchmark_label = null; });
  await run(page);
  await detail(page, "backtest");
  await expect(legend).toContainText("벤치마크 없음");
  await expect(side(page).locator(".pf-curve .pf-line-bench")).toHaveCount(0);
});

test("(f) 합성 데이터면 띠 범례에 '연습용 데이터' — 짝: 실데이터라고 말하면 없다", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await detail(page, "backtest");
  await expect(side(page).locator(".pf-strip-legend")).toContainText("연습용 데이터");
  await expect(side(page).locator(".pf-curve .pf-strip-practice")).toHaveCount(1);
  await patchRun(page, (b) => {
    const n = b.nodes.backtest as unknown as { provenance?: { perf_label?: { data_real?: boolean | null } } };
    if (n.provenance?.perf_label) n.provenance.perf_label.data_real = true;
    (b.nodes.backtest.view!.perf_label as { data_real?: boolean | null }).data_real = true;
  });
  await run(page);
  await detail(page, "backtest");
  await expect(side(page).locator(".pf-strip-legend")).not.toContainText("연습용 데이터");
  await expect(side(page).locator(".pf-curve .pf-strip-practice")).toHaveCount(0);
});

test("(g) 표로 보기 — 그림의 쌍둥이 표 · 해마다 값이 같다 · 곡선 전체 날짜·값", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const v = body.nodes.backtest.view!;
  const yearly = (v.periods as { yearly: { year: number; return_pct: number }[] }).yearly;
  const dates = strs(v.dates);
  await detail(page, "backtest");
  const det = side(page).locator("details.pf-table");
  await det.locator("summary").click();
  const yrows = det.locator("table.pf-table-years tbody tr");
  await expect(yrows).toHaveCount(yearly.length);
  await expect(yrows.first()).toContainText(String(yearly[0].year));
  const crows = det.locator("table.pf-table-curve tbody tr");
  await expect(crows).toHaveCount(dates.length);
  await expect(crows.last()).toContainText(dates[dates.length - 1]);
});

for (const scheme of ["light", "dark"] as const) {
  test(`(h) 대비: ${scheme} — 결과 패널 AA 미달 0${scheme === "dark" ? " · 밝은 배경 0" : ""}`, async ({ page }) => {
    await openCanvas(page);
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await detail(page, "backtest");
    await expect(side(page).locator(".pf-curve")).toBeVisible();
    await side(page).locator("details.pf-metrics summary").click();
    await page.waitForTimeout(200);
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
    expect(audit.checked, "검사한 텍스트 노드 수").toBeGreaterThan(40);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

test("(i) 기존 계약 그대로 — .pg-kv 총수익 · .pg-chart 보임 · [data-lookahead] · .pg-bt-cf · 성과 라벨", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await detail(page, "backtest");
  await expect(side(page).locator(".pg-kv", { hasText: "총수익" }).first()).toBeVisible();
  const kv = side(page).locator(".pf-kv");
  await expect(kv).toContainText("총수익");
  await expect(side(page).locator(".pg-chart").first()).toBeVisible();
  await expect(side(page).locator("[data-lookahead]")).toHaveCount(1);
  await expect(side(page).locator(".pg-bt-cf, .pg-bt-cf-na").first()).toBeVisible();
  await expect(side(page).locator(".pg-perf .perf-label")).toBeVisible();
  // 영어 약어 라벨은 없다 — 한글로.
  await expect(kv).not.toContainText("CAGR");
  await expect(kv).not.toContainText("MDD");
});

test("(j) 백테스트 불러오기 — 같은 문법 · 낙폭은 서버가 % 로 옮긴 값 · 벤치마크 · 리밸런싱을 모르면 띠가 말하지 않는다", async ({ page }) => {
  // 끝난 실행 하나를 만든다(진행 카드 시험과 같은 경로) — 끝날 때까지 상태를 읽기만 한다.
  const created = await (await page.request.post(`${API}/backtest/runs`, { data: { strategy_name: "E2E 성과 문법",
    config: { universe: "kospi50", filter_ast: { logic: "AND", conditions: [], groups: [] }, strategy_name: "GoldenCross",
              start_date: "2023-01-01", end_date: "2023-12-31", max_tickers: 2, max_positions: 2 } } })).json();
  const rid = created.run_id as string;
  await expect.poll(async () => ((await (await page.request.get(`${API}/backtest/runs/${rid}/status`)).json()) as { status: string }).status,
    { timeout: 180_000, intervals: [2_000] }).toMatch(/^(completed|failed|cancelled|expired)$/);
  await openCanvas(page);
  await importText(page, "pf-load.json", JSON.stringify({ ...DOC, nodes: [{ id: "lo", type: "backtest_load", params: { run_id: rid }, position: { x: 0, y: 0 } }] }));
  const body = await run(page);
  const n = body.nodes.lo;
  expect(n.status, n.reason ?? "").toBe("ok");
  const v = n.view!;
  const dates = strs((v.equity as { dates?: unknown }).dates);
  const ddPct = nums(v.drawdown_pct);
  await detail(page, "lo");
  await sameGrammar(page, n, dates, ddPct.length === dates.length);
  // 낙폭은 서버가 % 로 옮긴 `drawdown_pct` — 통계의 '가장 크게 빠진 폭' 과 같은 단위(화면이 ×100 하지 않는다 · 축 글자도 그 값).
  const stats = v.statistics as { max_drawdown_pct: number };
  expect(Math.abs(Math.min(...ddPct))).toBeCloseTo(Math.abs(stats.max_drawdown_pct), 0);
  await expect(side(page).locator(".pf-curve .pf-dd .pf-ytick")).toHaveText(`${Math.min(...ddPct).toFixed(0)}%`);
  // 벤치마크 — 서버가 곡선을 주면 회색 선·범례(이름)·끝값. 짝: 없으면 '벤치마크 없음'.
  const bm = v.benchmark as { label?: string; curve?: unknown } | null;
  if (bm && nums(bm.curve).length === dates.length) {
    await expect(side(page).locator(".pf-curve .pf-line-bench")).toHaveCount(1);
    await expect(side(page).locator(".pf-legend")).toContainText(`벤치마크 ${bm.label ?? ""}`.trim());
  } else {
    await expect(side(page).locator(".pf-legend")).toContainText("벤치마크 없음");
  }
  // 리밸런싱 날짜도 횟수도 모르는 노드 — 띠는 리밸런싱을 말하지 않는다(0번이라고도 하지 않는다 · 모름 ≠ 0).
  await expect(side(page).locator(".pf-strip-legend")).not.toContainText("리밸런싱");
  await expect(side(page).locator(".pf-curve .pf-strip-rebal")).toHaveCount(0);
  await expect(side(page).locator(".pf-strip-legend")).toContainText("연습용 데이터");          // is_mock_data → data_real=false
  await expect(side(page).locator(".pg-note", { hasText: `실행 ${rid}` })).toBeVisible();          // 아래 절(실행 id) 그대로
  await expect(side(page).locator(".pg-kv", { hasText: "총수익" }).first()).toBeVisible();          // BL3 W1 계약
});

test("(k) 전략 묶음 — 같은 문법(서버 모양 픽스처) · 낙폭은 숨은 오른쪽 축이 아니라 같은 물속 · 벤치마크 없음 · 리밸런싱 날짜 없음 · 아래 절 그대로", async ({ page }) => {
  // 개발 서버에는 등록된 전략이 없어 이 노드를 실제로 돌릴 수 없다(`/multibacktest/strategies` → 0). 7번이 ★실제로 돌린★ 곡선·기간별 수익·
  // 낙폭 사건을 전략 묶음 뷰 모양(`allocation_graph_nodes_strategy._strategy_backtest`)으로 옮긴 픽스처로 화면 문법만 건다 — 수는 서버 것이다.
  await openCanvas(page);
  const base = await run(page);
  const bv = base.nodes.backtest.view!;
  const s = bv.summary as Record<string, number>;
  const dates = strs(bv.dates), eq = nums(bv.equity_curve), dd = nums(bv.drawdown_curve);
  const nReb = Number(bv.n_rebalances);
  expect(nReb, "7번에 리밸런싱이 있어야 '날짜 없음' 문장이 공허하지 않다").toBeGreaterThan(0);
  const total = s.total_return_pct;
  const src = (id: number, name: string) => ({ strategy_id: id, name, registered: true, is_mock_data: true, is_pit_verified: false, repro_equal: null });
  const fixture = {
    status: "ok", reason: null,
    view: {
      summary: { total_return_pct: total, annualized_return_pct: s.cagr_pct, max_drawdown_pct: Math.abs(s.max_drawdown_pct), sharpe_ratio_full: s.sharpe_ratio,
                 n_rebalances: nReb, attribution: { allocation_effect_pct: null, cost_effect_pct: -0.12, netting_effect_pct: null, cash_effect_pct: null, macro_effect_pct: null } },
      strategy_names: { "1": "전략 하나", "2": "전략 둘" }, n_trading_days: dates.length, warnings: [],
      sources: { strategies: [src(1, "전략 하나"), src(2, "전략 둘")] },
      perf_label: { kind: "backtest", kind_reason: null, data_real: false, data_reason: null }, cost_model: null,
      period: { start: dates[0], end: dates[dates.length - 1], whole_record: true }, method: "equal", policy: "monthly",
      curve: dates.map((d, i) => ({ date: d, equity: Math.round(eq[i] * 1e8), dd: dd[i] })),       // 원 단위 · 같은 모양(비율이라 기간별 수익·낙폭 사건은 그대로)
      periods: bv.periods, drawdowns: bv.drawdowns, last_weights: { "1": 0.6, "2": 0.4 },
    },
    explain: { title: "전략 2개를 묶어 돌려 봤어요",
               headline: { label: "전체 수익", value: total, unit: "%", text: `${total >= 0 ? "+" : ""}${total.toFixed(1)}%` },
               facts: ["전략 2개를 ‘같은 비중’ 방식으로 달마다 다시 나눴어요."],
               trust: [{ state: "confirmed", text: "기록하지 않고 계산만 했어요 — 실행 기록은 남지 않아요." }],
               unmeasured: ["표본 밖 성과 — 등록된 전략의 과거 기록을 다시 나눈 결과예요"] },
  };
  await importText(page, "pf-strategy.json", JSON.stringify({ ...DOC, nodes: [{ id: "m", type: "strategy_backtest", params: {}, position: { x: 0, y: 0 } }] }));
  await patchRun(page, (b) => { b.ok = true; (b as unknown as { errors: unknown[] }).errors = []; b.nodes.m = { ...b.nodes.m, ...fixture }; });
  const body = await run(page);
  await detail(page, "m");
  await sameGrammar(page, body.nodes.m, dates, true);
  // 낙폭은 같은 물속 · 곡선은 원 단위(끝값 '억원') · 벤치마크 없음은 범례가 말한다
  await expect(side(page).locator(".pf-curve .pf-endlabel--port")).toContainText("억원");
  await expect(side(page).locator(".pf-legend")).toContainText("벤치마크 없음");
  await expect(side(page).locator(".pf-curve .pf-line-bench")).toHaveCount(0);
  // 리밸런싱 횟수는 알지만 날짜는 없다 — 눈금 0 · 글로 그렇게 말한다(눈금 없이 횟수만 그리지 않는다)
  await expect(side(page).locator(".pf-curve .pf-strip-rebal")).toHaveCount(0);
  await expect(side(page).locator(".pf-strip-legend")).toContainText(`리밸런싱 ${nReb}번 (날짜는 기록에 없어요)`);
  await expect(side(page).locator(".pf-strip-legend")).toContainText("연습용 데이터");
  // 아래 절 그대로 — 기간·다시 나눈 횟수 · 전략 비중 · 수익 나눠 보기(안 잰 칸 넷은 '안 쟀어요') · 전략 출처 둘
  await expect(side(page).locator(".pg-kv", { hasText: "다시 나눈 횟수" })).toContainText(`${nReb}번`);
  await expect(side(page).locator(".pg-h4", { hasText: "마지막 날 전략 비중" })).toBeVisible();
  await expect(side(page).locator(".pg-tag--unknown", { hasText: "안 쟀어요" })).toHaveCount(4);
  await expect(side(page).locator(".pg-src li")).toHaveCount(2);
});
