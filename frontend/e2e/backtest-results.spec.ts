import { test, expect, type Page } from "@playwright/test";
import { completedRun, contrastAudit, STUB_RUN_ID, type AuditResult } from "./helpers";

/**
 * BU4 · 실행·결과·비교 화면 — 답 한 문장(서버 값) · 이 수치가 무엇인지 · 실패는 실패로 (계획 "BU4 상세")
 * 거는 것(짝으로 항상-통과·항상-침묵을 배제):
 *  · 결과 답 문장 = 서버 total_return_pct·기간·벤치 — 픽스처를 바꾸면 문장이 따라 바뀐다 · 없으면 판단 없이 "받지 못했어요"
 *  · PerfLabel 이 답 문장 옆(`.tx-answer` 안) · 연습용 표시는 mock 일 때만 · "GCP"·"실데이터" 글자 없음
 *  · 시점 정합 사유는 `title=` 이 아니라 보이는 글자 · 결과 실패 → alert + 다시 시도 · 404 → "찾지 못했어요"
 *  · 곡선이 지표보다 위 · 핵심 지표 6 만 펼침, 나머지는 "지표 모두 보기" 안 · ★산출 불가는 접지 않고 핵심 지표 아래★
 *  · 등락 숫자 = 부호 + 한국식 색(오름 --tx-up-ink · 내림 --tx-down-ink) · 주 단추 하나 · AA · 390
 *  · 진행 화면: 한 문장 + 단계 · 제출한 설정은 접힘(행은 있다) · 비교: 차이만 말하고 "낫다"를 말하지 않는다
 */

const B_ID = "bt_stub_e2e_2";
type Full = ReturnType<typeof completedRun>["full"] & Record<string, unknown>;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const answer = (p: Page) => p.locator(".tx-answer");

const tokenRgb = (p: Page, name: string) => p.evaluate((n) => {
  const el = document.createElement("span");
  el.style.color = `var(${n})`;
  document.body.appendChild(el);
  const c = getComputedStyle(el).color;
  el.remove();
  return c;
}, name);

/** 결과 화면을 고친 픽스처로 연다. */
async function openResults(page: Page, edit: (f: Full) => void = () => {}) {
  const f = clone(completedRun().full) as Full;
  edit(f);
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(f) }));
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  return f;
}
const stats = (f: Full) => (f.result as { backtest: { statistics: Record<string, unknown> } }).backtest.statistics;
const bt = (f: Full) => (f.result as { backtest: Record<string, unknown> }).backtest;

test("답 문장 = 서버 총수익률·기간 — 값을 바꾸면 문장이 따라 바뀐다(짝: 상수 배제)", async ({ page }) => {
  await openResults(page);
  await expect(answer(page)).toContainText("+12.3%");
  await expect(answer(page)).toContainText("2023.01.01~2023.05.31");
  await page.unrouteAll();
  await openResults(page, (f) => { stats(f).total_return_pct = -4.5; });
  await expect(answer(page)).toContainText("-4.5%");
  await expect(answer(page)).not.toContainText("+12.3%");
});

test("벤치 문장은 벤치가 있을 때만 · 총수익률이 없으면 판단 없이 '받지 못했어요'(0% 아님)", async ({ page }) => {
  await openResults(page);
  await expect(answer(page)).toContainText("같은 기간 KOSPI +6.0%");
  await page.unrouteAll();
  await openResults(page, (f) => { delete bt(f).benchmark; delete stats(f).total_return_pct; });
  await expect(answer(page)).not.toContainText("같은 기간");
  await expect(answer(page)).toContainText("총수익률을 받지 못했어요");
  await expect(answer(page)).not.toContainText("0%");
});

test("PerfLabel 은 답 문장 옆 · 응답이 말한 종류 그대로(짝: 라벨이 없으면 '미상')", async ({ page }) => {
  await openResults(page, (f) => { f.perf_label = { kind: "backtest", data_real: false, data_reason: "mock 시세" }; });
  await expect(answer(page).locator(".perf-label")).toHaveCount(1);
  await expect(answer(page).locator(".perf-label__kind")).toHaveText("백테스트");
  await page.unrouteAll();
  await openResults(page);
  await expect(answer(page).locator(".perf-label__kind")).toHaveText("미상");
});

test("연습용 표시는 mock 일 때만 · 'GCP'·'실데이터' 글자 없음(짝: 실 시세 응답이면 연습용 없음)", async ({ page }) => {
  await openResults(page);
  await expect(answer(page)).toContainText("연습용 데이터");
  await expect(page.locator(".terminal-main")).not.toContainText("GCP");
  await expect(page.locator(".terminal-main")).not.toContainText("실데이터");
  await page.unrouteAll();
  await openResults(page, (f) => {
    f.is_mock_data = false;
    (f.result as { data_source: Record<string, unknown> }).data_source = { fundamentals: "dart", market_data: "kis", fully_real: true };
  });
  await expect(answer(page)).not.toContainText("연습용");
  await expect(page.locator(".terminal-main")).not.toContainText("실데이터");
});

test("시점 정합 사유는 보이는 글자 — title= 툴팁이 아니다(짝: 판정이 있으면 그 요약이 보인다)", async ({ page }) => {
  await openResults(page);
  await expect(answer(page)).toContainText("시점 정합을 판정할 자료가 없어요");
  const titled = await page.locator(".terminal-main [title]:not(.perf-label)").count();
  expect(titled, "툴팁으로 숨긴 사유").toBe(0);
  await page.unrouteAll();
  await openResults(page, (f) => {
    (f.result as Record<string, unknown>).pit_evidence = { status: "partial", summary: "재무 3건이 정적 시차로 추정됐어요", note: "" };
  });
  await expect(answer(page)).toContainText("재무 3건이 정적 시차로 추정됐어요");
});

test("결과를 불러오지 못하면 alert + 다시 시도 → 풀리면 답(짝: 정상 alert 0) · 404 는 '찾지 못했어요'", async ({ page }) => {
  let fail = true;
  const f = clone(completedRun().full);
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) => fail
    ? r.fulfill({ status: 500, body: "boom" })
    : r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(f) }));
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "domcontentloaded" });
  // Next 의 경로 안내(#__next-route-announcer__)도 role=alert 라 화면 본문으로 좁힌다.
  const alerts = page.locator(".terminal-main").getByRole("alert");
  await expect(alerts).toContainText("불러오지 못했어요", { timeout: 30_000 });
  fail = false;
  await page.getByRole("button", { name: "다시 시도" }).click();
  await expect(answer(page)).toContainText("+12.3%");
  await expect(alerts).toHaveCount(0);

  await page.goto("/backtest/runs/bt_missing_bu4/results", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("이 실행을 찾지 못했어요")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("link", { name: /편집기/ }).or(page.getByRole("button", { name: /편집기/ })).first()).toBeVisible();
});

test("곡선이 지표보다 위 · 핵심 지표 6 만 펼침 · 나머지는 '지표 모두 보기' 안(짝: 열면 보인다)", async ({ page }) => {
  await openResults(page);
  const curve = page.locator(".brun-card-t", { hasText: "자산곡선" });
  const key = page.locator(".rs-key");
  const yc = (await curve.boundingBox())!.y;
  const yk = (await key.boundingBox())!.y;
  expect(yc).toBeLessThan(yk);
  await expect(page.locator(".rs-kpis--key .brun-kpi")).toHaveCount(6);
  const all = page.locator("details.rs-all");
  await expect(all).not.toHaveAttribute("open", "");
  await expect(all.locator(".brun-kpi").first()).toBeHidden();
  await all.locator("summary").click();
  await expect(all.locator(".brun-kpi").first()).toBeVisible();
});

test("★산출 불가는 접지 않는다★ — 핵심 지표 바로 아래에 사유와 함께 보인다(짝: 조건이 아니면 0개)", async ({ page }) => {
  await openResults(page, (f) => { const s = stats(f); s.num_trades = 0; delete s.win_rate; delete s.profit_factor; });
  // 체결 0건이면 픽스처에 없는 거래 지표 여섯 + 지운 둘 = 8 개가 사유와 함께 뜬다(absentReason 규칙 그대로).
  const na = page.locator(".rs-key .rs-na .brun-kpi-na");
  await expect(na).toHaveCount(8);
  await expect(page.locator(".rs-na")).toContainText("이긴 거래 비율");
  await expect(na.first()).toBeVisible();                       // 펼치지 않아도 보인다
  await expect(na.first()).toContainText("체결이 한 건도 없어");
  await expect(page.locator("details.rs-all .brun-kpi-na")).toHaveCount(0);
  await page.unrouteAll();
  await openResults(page);
  await expect(page.locator(".brun-kpi-na")).toHaveCount(0);
});

test("등락은 부호 + 한국식 색 — 오름 --tx-up-ink · 내림 --tx-down-ink(짝)", async ({ page }) => {
  await openResults(page);
  const v = page.locator(".rs-key .brun-kpi").first().locator(".brun-kpi-v");
  await expect(v).toHaveText("+12.3%");
  expect(await v.evaluate((e) => getComputedStyle(e).color)).toBe(await tokenRgb(page, "--tx-up-ink"));
  await page.unrouteAll();
  await openResults(page, (f) => { stats(f).total_return_pct = -4.5; });
  await expect(v).toHaveText("-4.5%");
  expect(await v.evaluate((e) => getComputedStyle(e).color)).toBe(await tokenRgb(page, "--tx-down-ink"));
});

test("결과 화면 주 단추는 하나", async ({ page }) => {
  await openResults(page);
  await expect(page.locator(".terminal-main .tx-btn--main")).toHaveCount(1);
});

for (const t of ["light", "dark"] as const) {
  test(`결과·비교·진행 AA — ${t}`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);
    await stubCompare(page);
    await stubProgress(page);
    for (const path of [`/backtest/runs/${STUB_RUN_ID}/results`, `/backtest/runs/${STUB_RUN_ID}/compare`, "/backtest/runs/bt_prog_bu4/loading"]) {
      await page.goto(path, { waitUntil: "networkidle" });
      if (path.endsWith("compare")) await page.locator(".brun-select").selectOption(B_ID);
      await page.waitForTimeout(600);
      const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
      expect(r.checked, path).toBeGreaterThan(5);
      expect(r.low, `${t} ${path}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
      if (t === "dark") expect(r.bright, `${t} ${path} 밝은 판`).toEqual([]);
    }
  });
}

test("390 — 결과·비교 화면 가로 넘침 없음(표는 상자 안에서만 스크롤)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await stubCompare(page);
  for (const path of [`/backtest/runs/${STUB_RUN_ID}/results`, `/backtest/runs/${STUB_RUN_ID}/compare`]) {
    await page.goto(path, { waitUntil: "networkidle" });
    const over = await page.evaluate(() => {
      const m = document.querySelector(".terminal-main") as HTMLElement;
      return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
    });
    expect(over, path).toBeLessThanOrEqual(0);
  }
});

// ── 진행 화면 ──────────────────────────────────────────────────────────────────
function progLite() {
  const now = Math.floor(Date.now() / 1000);
  return { ...completedRun().lite, run_id: "bt_prog_bu4", status: "simulating", current_stage: "simulating", progress_percent: 62,
    status_message: "시뮬레이션 400/785일", completed_at: null, started_at: now - 75, created_at: now - 80 };
}
async function stubProgress(page: Page) {
  const lite = progLite();
  await page.route(/\/api\/v1\/backtest\/runs\/bt_prog_bu4\/status/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(lite) }));
  await page.route(/\/api\/v1\/backtest\/runs\/bt_prog_bu4$/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...lite,
      input_snapshot: { universe: "kospi200", start_date: "2023-01-01", end_date: "2023-05-31", initial_capital: 50000000 }, parameter_snapshot: {}, result: null }) }));
}

test("진행 화면: 한 문장 + 지금 단계 · 제출한 설정은 접혀 있되 행은 있다", async ({ page }) => {
  await stubProgress(page);
  await page.goto("/backtest/runs/bt_prog_bu4/loading", { waitUntil: "networkidle" });
  await expect(page.locator(".tx-answer")).toContainText("백테스트를 돌리는 중이에요");
  await expect(page.locator(".brun-stage")).toContainText("시뮬레이션");
  await expect(page.locator(".brun-pct em")).toContainText("엔진 보고");
  const cfg = page.locator("details.rs-cfg");
  await expect(cfg).not.toHaveAttribute("open", "");
  expect(await cfg.locator(".brun-cfg tr").count()).toBeGreaterThan(0);
  await expect(page.locator(".terminal-main")).not.toContainText("실데이터");
  await expect(page.locator(".terminal-main .tx-btn--main")).toHaveCount(0);   // 진행 중엔 주 행동이 없다(취소는 보조)
});

// ── 비교 화면 ──────────────────────────────────────────────────────────────────
async function stubCompare(page: Page, editB: (f: Full) => void = () => {}) {
  const a = completedRun();
  const aFull = clone(a.full) as Full;
  const bFull = clone(a.full) as Full;
  Object.assign(bFull, { run_id: B_ID, correlation_id: B_ID, strategy_name: "모멘텀 (E2E)" });
  stats(bFull).total_return_pct = 24.9;
  stats(bFull).max_drawdown_pct = -18.0;
  editB(bFull);
  const bLite = { ...a.lite, run_id: B_ID, strategy_name: "모멘텀 (E2E)" };
  await page.route("**/api/v1/backtest/runs", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [a.lite, bLite] }) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(aFull) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${B_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(bFull) }));
}
async function openCompare(page: Page, editB?: (f: Full) => void) {
  await stubCompare(page, editB);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/compare`, { waitUntil: "networkidle" });
  await page.locator(".brun-select").selectOption(B_ID);
}

test("비교: 차이만 말한다 — 총수익률 +12.6%p · 최대 낙폭 -3.8%p, '낫다·우위'는 없다", async ({ page }) => {
  await openCompare(page);
  await expect(answer(page)).toContainText("총수익률 +12.6%p");
  await expect(answer(page)).toContainText("최대 낙폭 -3.8%p");
  await expect(page.locator(".terminal-main")).not.toContainText(/우위|나아요|낫다|좋아요|더 나은/);
});

test("비교: 한쪽 값이 없으면 '비교할 수 없어요' — 0 으로 두지 않는다(짝)", async ({ page }) => {
  await openCompare(page, (b) => { delete stats(b).total_return_pct; });
  await expect(answer(page)).toContainText("총수익률은 비교할 수 없어요");
  await expect(answer(page)).not.toContainText("총수익률 +");
  await expect(answer(page)).toContainText("최대 낙폭 -3.8%p");
});

test("비교 차이 색은 부호만 — 판단색이 아니다(최대 낙폭이 깊어져도 내림 색, 총수익률 증가는 오름 색)", async ({ page }) => {
  await openCompare(page);
  const delta = (label: string) => page.locator(".brun-cmp tr", { hasText: label }).first().locator("td").nth(3);
  expect(await delta("총수익률").evaluate((e) => getComputedStyle(e).color)).toBe(await tokenRgb(page, "--tx-up-ink"));
  expect(await delta("최대낙폭").evaluate((e) => getComputedStyle(e).color)).toBe(await tokenRgb(page, "--tx-down-ink"));
});
