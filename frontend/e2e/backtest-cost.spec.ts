import { test, expect, type Page } from "./fixtures";
import { completedRun, contrastAudit, STUB_RUN_ID, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 비용 분해 — 일봉 백테스트의 서버 `cost_model` 을 결과 화면 · 캔버스 '백테스트 결과 조회' 판에 그대로 (S1 · 2026-11-19)
// ─────────────────────────────────────────────────────────────────────────────
//  편집기의 안내("결과의 비용 분해에 항목별로 표시됩니다")가 약속한 절이 결과 화면에 없었다(관측). 매도세를 켜면 종목 마스터가
//  모르는 종목의 매도세는 0 원이 아니라 미상인데, 그 사실이 화면 어디에도 나오지 않았다.
//  (a) 다섯 성분의 상태 · 부과한 금액 · 서버 사유 = 서버 블록(짝: 블록을 바꾸면 따라 바뀐다 — 상수 화면 배제)
//  (b) 끈 성분 · 미상 성분의 금액은 0 원이 아니라 N/A(미상 ≠ 0) · 미상인데 일부를 부과했으면 '일부'
//  (c) 거래일별 매도세 — 매도 · 부과 · 미상 건수 · 세율별 건수 · 미상 사유별 건수 · 근거 문장 = 서버 값
//  (d) 블록이 없는 옛 실행 — 없다고 말한다(0 원 표를 그리지 않는다)
//  (e) 실제 실행(매도세 켬) — 결과 화면과 캔버스 판이 그 실행의 서버 블록 그대로
//  (f) 라이트 · 다크 AA · 390 가로 넘침 0 · 문체(서버 글은 data-server)
// ═══════════════════════════════════════════════════════════════════════════════

const API = "http://localhost:8000/api/v1";
const DOC = { format: "project-alpha.portfolio-graph", version: 1, meta: {}, edges: [] as unknown[] };
type Dict = Record<string, unknown>;
type Full = ReturnType<typeof completedRun>["full"] & Dict;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const PARTS = ["commission", "slippage", "tax", "spread", "impact"] as const;
const PART_KO: Record<string, string> = { commission: "수수료", slippage: "슬리피지", tax: "매도세", spread: "호가 스프레드", impact: "시장충격" };
const STATE_KO: Record<string, string> = { charged: "부과", off: "끔", unmeasurable: "미상", unsupported: "엔진에 없음" };
/** 서버 문장의 강조 표시(★ · ** · `)는 화면에서 걷는다 — 글자는 그대로. */
const plain = (s: string) => s.replace(/\*\*|★|`/g, "");
const won = (v: number) => `${Math.round(v).toLocaleString("ko-KR")}원`;

/** 엔진이 실제로 낸 블록(합성 시세 · 매도세 켬 · 스프레드 켬 · 마스터가 모르는 종목 — 2026-11-19 탐침 그대로). */
function tradeDateBlock(): Dict {
  return {
    components: {
      commission: { state: "charged", bps: 0.0, krw: 15396.0368, reason: null },
      slippage: { state: "charged", bps: 0.0, krw: 5132.0123, reason: null },
      tax: { state: "unmeasurable", bps: 0.0, krw: 0.0, reason: "매도 2건 가운데 2건은 세율을 몰라 부과하지 않았습니다. 0 원이 아니라 미상입니다." },
      spread: { state: "charged", bps: 0.0, krw: 2566.0061, reason: null },
      impact: { state: "off", bps: 0.0, krw: 0.0, reason: "이 실행에서 껐습니다 — 부과하지 않기로 **선택**한 것이지 비용이 없다는 뜻이 아닙니다." },
    },
    total_krw: 23094.06, total_bps: 0.0, n_unmeasurable: 1,
    policy: { commission_bps: 15.0, slippage_bps: 5.0, charge_tax: true, tax_bps: null, charge_spread: true, spread_bps: 5.0,
      charge_impact: false, impact_coeff: null, impact_coeff_note: "", tax_schedule: "trade_date",
      tax_schedule_note: "매도세는 매도마다 그 거래일(체결일) · 시장 · 상품의 세율(세율표)로 계산합니다. 정책에는 세율 하나를 두지 않습니다." },
    version: "d1f26717d794", round_trip_bps: 45.0, n_unmeasured_trades: 2,
    sell_tax: {
      basis: "trade_date", label: "추론", grades: [],
      note: "매도마다 그 거래일(체결일) · 시장 · 상품의 증권거래세와 농어촌특별세를 세율표(보도 · 안내 자료 요약)로 부과했습니다. 법령 원문과 대조하지 않은 추론값입니다.",
      n_sells: 2, n_charged: 0, n_unmeasured: 2, rates_bp: [],
      unmeasured: [{ code: "unknown_market_or_instrument", n: 2, message: "종목의 시장·상품 구분을 알 수 없어 매도세를 계산하지 않았습니다." }],
      round_trip_note: "왕복 bp 에는 매도세를 넣지 않았습니다. 매도세는 거래일 · 시장 · 상품마다 다릅니다.",
    },
  };
}

async function openResults(page: Page, edit: (f: Full) => void = () => {}) {
  const f = clone(completedRun().full) as Full;
  edit(f);
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(f) }));
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  return f;
}
const withBlock = (block: Dict | null) => (f: Full) => { (f.result as Dict).cost_model = block; };
const card = (page: Page) => page.locator(".brun-cost");
const row = (root: ReturnType<Page["locator"]>, part: string) => root.locator(`.cbd-table tbody tr[data-part="${part}"]`);

/** 화면의 비용 분해가 서버 블록 그대로인가 — 상태 낱말 · 금액(N/A · 일부) · 사유 · 매도세 셈. `root` 는 `.cbd` 를 품은 곳. */
async function sameAsServer(root: ReturnType<Page["locator"]>, block: Dict) {
  const comps = block.components as Record<string, { state: string; krw: number; reason: string | null }>;
  await expect(root.locator(".cbd-table tbody tr")).toHaveCount(PARTS.length);
  for (const p of PARTS) {
    const c = comps[p];
    const r = row(root, p);
    await expect(r.locator("th")).toHaveText(PART_KO[p]);
    await expect(r.locator(".cbd-state")).toHaveText(STATE_KO[c.state]);
    await expect(r).toHaveAttribute("data-state", c.state);
    const amount = c.state === "charged" ? won(c.krw)
      : c.state === "unmeasurable" && c.krw > 0 ? `${won(c.krw)} · 일부` : "N/A";
    await expect(r.locator(".cbd-krw")).toHaveText(amount);
    const why = root.locator(`.cbd-why li[data-part="${p}"]`);
    if (c.reason) await expect(why.locator("[data-server]")).toHaveText(plain(c.reason));
    else await expect(why).toHaveCount(0);
  }
  await expect(root.locator(".cbd-total")).toHaveText(won(block.total_krw as number));
  await expect(root.locator(".cbd-ver")).toContainText(String(block.version));
  const st = block.sell_tax as Dict | undefined;
  if (!st) { await expect(root.locator(".cbd-tax")).toHaveCount(0); return; }
  const tax = root.locator(".cbd-tax");
  await expect(tax.locator(".cbd-tax-n")).toHaveText(`매도 ${st.n_sells}건 · 부과 ${st.n_charged}건 · 미상 ${st.n_unmeasured}건`);
  await expect(tax.locator(".cbd-tax-label")).toHaveText(String(st.label));
  const rates = st.rates_bp as { bp: number; n: number }[];
  if (rates.length) {
    await expect(tax.locator(".cbd-rate")).toHaveText(rates.map((x) => `${(x.bp / 100).toFixed(2)}% ${x.n}건`));
  } else await expect(tax.locator(".cbd-rate")).toHaveCount(0);
  const unm = st.unmeasured as { code: string; n: number; message: string }[];
  await expect(tax.locator(".cbd-unm")).toHaveCount(unm.length);
  for (const u of unm) {
    const li = tax.locator(`.cbd-unm[data-code="${u.code}"]`);
    await expect(li.locator("[data-server]")).toHaveText(plain(u.message));
    await expect(li.locator(".cbd-unm-n")).toHaveText(`${u.n}건`);
  }
  await expect(tax.locator(".cbd-tax-note")).toHaveText(plain(String(st.note)));
  await expect(tax.locator(".cbd-tax-rt")).toHaveText(plain(String(st.round_trip_note)));
  const grades = st.grades as string[];
  if (grades.length) await expect(tax.locator(".cbd-grades")).toHaveText(`세율표 근거 등급 ${grades.join(" · ")}`);
  else await expect(tax.locator(".cbd-grades")).toHaveCount(0);
}

test("(a)(b)(c) 결과 화면 비용 분해 = 서버 블록 — 미상 매도세 · 끈 충격은 N/A · 서버 사유 · 매도세 셈", async ({ page }) => {
  const block = tradeDateBlock();
  await openResults(page, withBlock(block));
  await expect(card(page).locator(".brun-card-t")).toContainText("비용 분해");
  await sameAsServer(card(page), block);
  // 끈 성분의 사유는 강조 표시를 걷은 서버 글 그대로 — '**' 가 화면에 남지 않는다.
  await expect(card(page)).not.toContainText("**");
  // 미상인 성분을 이름으로 적는다(세지 않는다 — 옛 실행의 n_unmeasurable 은 늘 0 이었다).
  await expect(card(page).locator(".cbd-unmeasured")).toHaveText("재지 못한 성분 · 매도세");
  await expect(card(page).locator(".cbd-ntrades")).toHaveText("일부 비용을 재지 못한 거래 2건");
});

test("(a) 짝 — 블록을 바꾸면 화면이 따라 바뀐다(모두 부과한 매도세 · 세율별 건수 · 미상 줄 없음)", async ({ page }) => {
  const block = tradeDateBlock();
  const comps = block.components as Record<string, Dict>;
  comps.tax = { state: "charged", bps: 0.0, krw: 7846.5408, reason: null };
  block.total_krw = 30933.91;
  block.n_unmeasurable = 0;
  block.n_unmeasured_trades = 0;
  Object.assign(block.sell_tax as Dict, { grades: ["T1"], n_charged: 2, n_unmeasured: 0, rates_bp: [{ bp: 18.0, n: 1 }, { bp: 15.0, n: 1 }], unmeasured: [] });
  await openResults(page, withBlock(block));
  await sameAsServer(card(page), block);
  await expect(row(card(page), "tax").locator(".cbd-krw")).toHaveText("7,847원");
  await expect(card(page).locator(".cbd-unmeasured")).toHaveCount(0);
  await expect(card(page).locator(".cbd-ntrades")).toHaveCount(0);
});

test("(b) 미상인데 일부를 부과한 성분은 금액 뒤에 '일부' — 전체 금액처럼 읽히지 않게 · 미상 사유는 사유마다 제 건수", async ({ page }) => {
  const block = tradeDateBlock();
  (block.components as Record<string, Dict>).tax = { state: "unmeasurable", bps: 0.0, krw: 3600.0,
    reason: "매도 4건 가운데 2건은 세율을 몰라 부과하지 않았습니다. 0 원이 아니라 미상입니다." };
  Object.assign(block.sell_tax as Dict, { grades: ["T1"], n_sells: 4, n_charged: 2, n_unmeasured: 2, rates_bp: [{ bp: 18.0, n: 2 }],
    unmeasured: [{ code: "unknown_market_or_instrument", n: 1, message: "종목의 시장·상품 구분을 알 수 없어 매도세를 계산하지 않았습니다." },
                 { code: "outside_schedule", n: 1, message: "이 거래일의 매도세는 확인하지 못한 구간입니다." }] });
  await openResults(page, withBlock(block));
  await sameAsServer(card(page), block);
  await expect(row(card(page), "tax").locator(".cbd-krw")).toHaveText("3,600원 · 일부");
});

test("(b) 옛 실행(실행 단위 n_unmeasurable 이 늘 0 이던 때)도 미상 성분을 상태로 읽어 이름으로 적는다", async ({ page }) => {
  // 2026-11-19 전의 서버는 미상 성분이 있어도 n_unmeasurable 에 0 을 실었다(그때 저장된 실행이 남아 있다).
  const block = tradeDateBlock();
  block.n_unmeasurable = 0;
  (block.components as Record<string, Dict>).impact = { state: "unmeasurable", bps: 0.0, krw: 0.0,
    reason: "켜져 있으나 참여율(주문금액/거래대금)을 구하지 못했습니다 — ★0 으로 부과하면 '충격이 없었다' 는 관측이 되어 비용이 조용히 싸집니다.★" };
  await openResults(page, withBlock(block));
  await sameAsServer(card(page), block);
  await expect(card(page).locator(".cbd-unmeasured")).toHaveText("재지 못한 성분 · 매도세 · 시장충격");
  await expect(card(page)).not.toContainText("★");
});

test("(c) 꺼진 매도세(고정 정책 · 블록에 sell_tax 없음) — 매도세 절을 그리지 않는다", async ({ page }) => {
  const block = tradeDateBlock();
  delete block.sell_tax;
  (block.components as Record<string, Dict>).tax = { state: "off", bps: 0.0, krw: 0.0,
    reason: "이 실행에서 껐습니다 — 부과하지 않기로 **선택**한 것이지 비용이 없다는 뜻이 아닙니다." };
  await openResults(page, withBlock(block));
  await sameAsServer(card(page), block);
  await expect(row(card(page), "tax").locator(".cbd-krw")).toHaveText("N/A");
});

test("(d) 비용 분해가 없는 옛 실행 — 없다고 말하고 표를 그리지 않는다(0 원 표 아님)", async ({ page }) => {
  await openResults(page, withBlock(null));
  await expect(card(page).locator(".cbd-none")).toHaveText("이 실행의 결과에는 비용 분해가 없습니다. 어떤 비용을 부과했는지 이 화면은 알 수 없습니다.");
  await expect(card(page).locator(".cbd-table")).toHaveCount(0);
  await page.unrouteAll();
  await openResults(page, (f) => { delete (f.result as Dict).cost_model; });
  await expect(card(page).locator(".cbd-none")).toBeVisible();
});

test("(e) 실제 실행(매도세 켬) — 결과 화면과 캔버스 '백테스트 결과 조회' 판이 그 실행의 서버 블록 그대로", async ({ page }) => {
  test.setTimeout(300_000);
  const created = await (await page.request.post(`${API}/backtest/runs`, { data: { strategy_name: "E2E 매도세 거래일별",
    config: { universe: "kospi50", filter_ast: { logic: "AND", conditions: [], groups: [] }, strategy_name: "GoldenCross",
              start_date: "2023-01-01", end_date: "2023-12-31", max_tickers: 2, max_positions: 2, charge_sell_tax: true } } })).json();
  const rid = created.run_id as string;
  await expect.poll(async () => ((await (await page.request.get(`${API}/backtest/runs/${rid}/status`)).json()) as { status: string }).status,
    { timeout: 240_000, intervals: [2_000] }).toBe("completed");
  const full = await (await page.request.get(`${API}/backtest/runs/${rid}`)).json() as { result: { cost_model: Dict } };
  const block = full.result.cost_model;
  const st = block.sell_tax as Dict;
  expect(st, "매도세를 켠 실행은 거래일별 셈을 싣는다").toBeTruthy();
  expect(st.n_sells as number, "매도가 없으면 이 시험이 공허하다").toBeGreaterThan(0);

  await page.goto(`/backtest/runs/${rid}/results`, { waitUntil: "networkidle" });
  await sameAsServer(card(page), block);

  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.locator(".pg-import-input").setInputFiles({ name: "cost.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ ...DOC, nodes: [{ id: "lo", type: "backtest_load", params: { run_id: rid }, position: { x: 0, y: 0 } }] })) });
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await resp).json() as { nodes: Record<string, { status: string; reason: string | null; view: Dict }> };
  expect(body.nodes.lo.status, body.nodes.lo.reason ?? "").toBe("ok");
  expect(body.nodes.lo.view.cost_model, "캔버스 뷰는 저장된 블록 그대로").toEqual(block);
  await page.locator('.pg-node[data-node-id="lo"]').click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await sameAsServer(page.locator(".pg-side .cbd"), block);
});

for (const t of ["light", "dark"] as const) {
  test(`(f) 비용 분해 AA · 문체 — ${t}`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);
    await openResults(page, withBlock(tradeDateBlock()));
    await page.waitForTimeout(600);
    const r = await page.evaluate<AuditResult>(contrastAudit(".brun-cost"));
    expect(r.checked).toBeGreaterThan(10);
    expect(r.low, `${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (t === "dark") expect(r.bright, `${t} 밝은 판`).toEqual([]);
    const v = await page.evaluate<VoiceResult>(voiceAudit(".brun-cost"));
    expect(v.checked).toBeGreaterThan(5);
    expect(v.haeyo, "해요체").toEqual([]);
    expect(v.dash, "화면이 지은 글의 줄표").toEqual([]);
    expect(v.titles, "툴팁").toBe(0);
  });
}

test("(f) 390 — 비용 분해가 화면 밖으로 넘치지 않는다(표는 상자 안에서만 스크롤)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openResults(page, withBlock(tradeDateBlock()));
  await expect(card(page).locator(".cbd-table")).toBeVisible();
  const over = await page.evaluate(() => {
    const m = document.querySelector(".terminal-main") as HTMLElement;
    const c = document.querySelector(".brun-cost") as HTMLElement;
    return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth,
      c.getBoundingClientRect().right - m.getBoundingClientRect().right);
  });
  expect(over).toBeLessThanOrEqual(0.5);
});
