import { test, expect } from "@playwright/test";
import { trackErrors, uniq, STUB_RUN_ID, completedRun, stubCompletedRun,
  contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BacktestRun workflow regression (스펙 §5) — locks in the durable run flow so a
// regression (results rendered under the config form, navigation before a valid
// run_id, dead loading/results URLs, mojibake) makes CI go red.
//
//  Test A drives the REAL backend: clicking "백테스트 실행" must create a run and
//  navigate to a dedicated /loading URL (never render results under the form), the
//  monitor must show a REAL stage + config, and cancel must reach an honest state.
//  It cancels instead of waiting out the full multi-minute simulation.
//
//  Test B stubs the run API with a real-schema completed payload so the
//  loading→results transition, the results workspace, honesty badges, Korean
//  encoding, and refresh recovery are verified deterministically and fast.
// ═══════════════════════════════════════════════════════════════════════════════

// Resilience regression (stubbed, deterministic): a transient status-poll error (proxy 504 / DB
// blip) must NOT flip the loading page to the terminal "만료된 링크" state — it keeps polling and
// shows live progress. Stubs the run API so it's fast and independent of the real engine.
const RESIL_ID = "bt_resil_e2e_1";
function simStatus() {
  return {
    run_id: RESIL_ID, status: "simulating", progress_percent: 55, current_stage: "simulating",
    status_message: "시뮬레이션 400/785일", strategy_name: "Condition",
    created_at: 1_700_000_000, started_at: 1_700_000_001, completed_at: null,
    error_code: null, error_message: null, correlation_id: RESIL_ID,
    is_mock_data: true, is_pit_verified: false, engine_version: "dev",
  };
}

test("Backtest: loading survives transient status errors (keeps polling, no dead-end)", async ({ page }) => {
  let n = 0;
  await page.route(new RegExp(`/runs/${RESIL_ID}/status`), (route) => {
    n += 1;
    // first 4 polls fail transiently (503), then recover to a live 'simulating' status
    if (n <= 4) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(simStatus()) });
  });
  await page.route(new RegExp(`/runs/${RESIL_ID}$`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...simStatus(), input_snapshot: { universe: "kospi200" }, parameter_snapshot: {}, result: null }) }));

  await page.goto(`/backtest/runs/${RESIL_ID}/loading`, { waitUntil: "domcontentloaded" });
  // through the transient window the terminal not-found must never appear
  for (let i = 0; i < 8; i++) {
    await page.waitForTimeout(1000);
    expect(await page.locator("body").innerText(), "no terminal not-found during transient errors")
      .not.toContain("만료되었거나 잘못된 링크");
  }
  // it recovered to live progress
  await expect(page.locator(".brun-progress")).toBeVisible();
  await expect(page.locator(".brun-stage")).toContainText("시뮬레이션");
});

// ★실제 인시던트 회귀★ — 숨겨진 탭에서 폴링이 영구 정지하던 문제.
// react-query의 retryer는 재시도 대기 후 canContinue()에서 focusManager.isFocused()를 보고,
// 탭이 숨겨져 있으면 timeout 없이 pause()한다. 그 뒤 1초 interval은 전부 dedupe되어 멈춘
// promise를 돌려주므로 브라우저에서 요청이 한 건도 나가지 않는다 — 사용자가 터미널을 보는
// 동안 UI가 마지막 스냅샷("시뮬레이션 63/728일")에 얼어붙은 채 "재시도 중"만 띄웠던 원인.
// 수정(retry:false + networkMode:"always")은 retryer를 폴링 루프에서 제거한다.
const HIDDEN_ID = "bt_hidden_e2e_1";

test("Backtest: polling survives a hidden tab (no permanent retryer pause)", async ({ page }) => {
  let polls = 0;
  let failing = true;
  await page.route(new RegExp(`/runs/${HIDDEN_ID}/status`), (route) => {
    polls += 1;
    if (failing) {
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary" }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...simStatus(), run_id: HIDDEN_ID }) });
  });
  await page.route(new RegExp(`/runs/${HIDDEN_ID}$`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...simStatus(), run_id: HIDDEN_ID, input_snapshot: { universe: "kospi200" }, parameter_snapshot: {}, result: null }) }));

  await page.goto(`/backtest/runs/${HIDDEN_ID}/loading`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  // 탭을 숨긴다 — 사용자가 터미널로 전환한 순간을 재현
  await page.emulateMedia({ reducedMotion: null });
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { get: () => "hidden", configurable: true });
    Object.defineProperty(document, "hidden", { get: () => true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });

  const atHide = polls;
  await page.waitForTimeout(6000);
  // 수정 전: 여기서 polls가 전혀 늘지 않았다(retryer pause). 수정 후: 계속 나간다.
  expect(polls - atHide, "polling must continue while the tab is hidden").toBeGreaterThan(2);

  // 숨겨진 채로 서버가 회복되면 UI도 따라와야 한다
  failing = false;
  await page.waitForTimeout(3000);
  await expect(page.locator(".brun-stage")).toContainText("시뮬레이션");
});

// ═══════════════════════════════════════════════════════════════════════════════
// 진행률 — 있는 것은 보여 주고, 없는 것은 지어내지 않는다 (P8)
// ─────────────────────────────────────────────────────────────────────────────
// ★계획서 v2 는 "퍼센트를 없애라" 고 했는데 그건 틀린 지시였다★
// 이 수치는 경과 시간이 아니라 엔진이 실제로 끝낸 일에서 나온다 —
// `30 + 55*done/total`(시뮬레이션 완료 일수, backtest_run_routes.py:55-84).
// 지웠다면 진실한 신호를 없애고 위의 `.brun-progress` 단언까지 깨뜨렸을 것이다.
//
// ★진짜 결함은 반대편에 있었다★ progress_percent 컬럼은 nullable 인데
// `Math.round(null)` 은 0 이다. 그래서 엔진이 아무것도 보고하지 않은 런이 "0% 진행" 으로
// 보였다 — 측정하지 않은 것과 0 을 같은 글자로 적는, P5 에서 고친 것과 같은 결함이다.
// ═══════════════════════════════════════════════════════════════════════════════
const PCT_ID = "bt_pct_e2e_1";
function pctStatus(extra: Record<string, unknown>) {
  return {
    run_id: PCT_ID, status: "simulating", current_stage: "simulating",
    status_message: "시뮬레이션 400/785일", strategy_name: "Condition",
    created_at: 1_700_000_000, started_at: 1_700_000_001, completed_at: null,
    error_code: null, error_message: null, correlation_id: PCT_ID,
    is_mock_data: true, is_pit_verified: false, engine_version: "dev", ...extra,
  };
}
async function stubPct(page: import("@playwright/test").Page, extra: Record<string, unknown>) {
  await page.route(new RegExp(`/runs/${PCT_ID}/status`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(pctStatus(extra)) }));
  await page.route(new RegExp(`/runs/${PCT_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ ...pctStatus(extra), input_snapshot: { universe: "kospi200" }, parameter_snapshot: {}, result: null }) }));
}

test("Backtest: 엔진이 보고한 진행률은 출처와 함께 그대로 보여 준다", async ({ page }) => {
  await stubPct(page, { progress_percent: 62 });
  await page.goto(`/backtest/runs/${PCT_ID}/loading`, { waitUntil: "networkidle" });

  await expect(page.locator(".brun-progress")).toBeVisible();
  await expect(page.locator(".brun-pct")).toContainText("62%");
  // 어디서 온 숫자인지 밝힌다 — 출처 없는 퍼센트는 신뢰도를 과장한다.
  await expect(page.locator(".brun-pct em")).toContainText("엔진 보고");
  // 원자료(완료 일수)도 함께 보인다.
  await expect(page.locator(".brun-msg")).toContainText("400/785일");
});

test("Backtest: 진행률이 없으면 0% 가 아니라 단계 목록만 보여 준다", async ({ page }) => {
  await stubPct(page, { progress_percent: null });
  await page.goto(`/backtest/runs/${PCT_ID}/loading`, { waitUntil: "networkidle" });

  // ★핵심 단언★ 없는 것을 0 으로 적지 않는다.
  const body = await page.locator(".brun-progress-wrap").innerText();
  expect(body, "측정하지 않은 진행률을 0% 로 적으면 안 된다").not.toMatch(/\b0\s*%/);
  expect(await page.locator(".brun-pct").count(), "퍼센트 표기가 없어야 한다").toBe(0);
  expect(await page.locator(".brun-progress").count(), "비례 막대도 없어야 한다").toBe(0);

  // 대신 실제 실행 단계를 열거한다 — 현재 단계가 표시된다.
  await expect(page.locator(".brun-phases")).toBeVisible();
  expect(await page.locator(".brun-phase").count()).toBeGreaterThan(4);
  await expect(page.locator(".brun-phase.on")).toContainText("시뮬레이션");
});

test("Backtest: a genuinely missing run shows the honest not-found (real 404)", async ({ page }) => {
  await page.goto("/backtest/runs/bt_missing_e2e_xyz/loading", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("만료되었거나 잘못된 링크")).toBeVisible({ timeout: 15_000 });
});

test("Backtest: run button creates a run + navigates to loading (never in-form) + honest cancel", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/backtest", { waitUntil: "networkidle" });
  const runBtn = page.locator(".tbt-run").first();
  await expect(runBtn).toBeVisible();
  await expect(runBtn).toContainText("백테스트 실행");

  await runBtn.click();
  // Never render final results under the form — must navigate to a dedicated run URL.
  await page.waitForURL(/\/backtest\/runs\/.+\/loading/, { timeout: 20_000 });
  const runId = page.url().match(/runs\/([^/]+)\/loading/)?.[1];
  expect(runId, "a real run_id in the URL").toBeTruthy();
  expect(page.url()).not.toMatch(/\/backtest$/); // left the config page

  // The loading monitor shows a REAL current stage (one of the lifecycle labels) + config rows.
  await expect(page.locator(".brun-stage").first()).toBeVisible();
  const stage = (await page.locator(".brun-stage").first().innerText()).trim();
  expect(stage.length, "a real stage label is shown").toBeGreaterThan(0);
  expect(await page.locator(".brun-cfg tr").count(), "config snapshot rows").toBeGreaterThan(0);
  expect(await page.locator("body").innerText()).not.toMatch(/�/); // encoding intact

  // Safe cancel → honest terminal state (not a silent hang).
  await page.locator(".brun-btn", { hasText: "실행 취소" }).first().click();
  await expect(page.locator(".brun-err-title")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".brun-err-title")).toContainText("취소");

  expect(uniq(sink.api404), "backtest run API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "backtest page errors").toEqual([]);
});

// The completed-run fixture (STUB_RUN_ID / completedRun / stubCompletedRun) now lives in
// ./helpers — route-health.spec.ts opens the same results route and needs the same payload.
// Behaviour here is unchanged; only the definition site moved.

test("Backtest: completed run → results workspace renders + refresh recovery (stubbed, deterministic)", async ({ page }) => {
  const sink = trackErrors(page);
  await stubCompletedRun(page);

  // Loading page must auto-navigate to results once status is completed.
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/loading`, { waitUntil: "networkidle" });
  await page.waitForURL(new RegExp(`/backtest/runs/${STUB_RUN_ID}/results`), { timeout: 15_000 });

  // Results workspace: header, grouped diagnostics, attribution, honesty badges, Korean intact.
  await expect(page.locator("h1")).toContainText("골든크로스");
  await expect(page.locator(".brun-kpi").first()).toBeVisible();
  expect(await page.locator(".brun-kpi").count(), "KPI cards for available metrics").toBeGreaterThan(6);
  // metrics are grouped into honest diagnostic sections (only groups with data render)
  const groups = await page.locator(".brun-mgroup-t").allInnerTexts();
  expect(groups.length, "grouped metric sections").toBeGreaterThan(2);
  // attribution chart (from engine contribution_pct) + honest omission note
  await expect(page.locator(".brun-card-t", { hasText: "Attribution" })).toBeVisible();
  await expect(page.locator(".brun-diag-omit")).toContainText("MFE/MAE");
  await expect(page.getByText("MOCK 데이터").first()).toBeVisible();
  await expect(page.getByText("PIT 미검증").first()).toBeVisible();
  await expect(page.locator("table").first()).toBeVisible(); // symbols / trades
  const body = await page.locator("body").innerText();
  expect(body).toContain("삼성전자");
  expect(body).not.toMatch(/�/);

  // Refresh recovery: the results URL is durable (bookmarkable / reloadable).
  await page.reload({ waitUntil: "networkidle" });
  expect(page.url()).toMatch(new RegExp(`/backtest/runs/${STUB_RUN_ID}/results`));
  await expect(page.locator(".brun-kpi").first()).toBeVisible();

  expect(uniq(sink.api404), "results API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "results page errors").toEqual([]);
});

test("Backtest: compare two completed runs → overlay + metric delta + config diff (stubbed)", async ({ page }) => {
  const sink = trackErrors(page);
  const a = completedRun();
  // run B: a distinct completed run (different id, config, stronger stats).
  const B_ID = "bt_stub_e2e_2";
  const bFull = JSON.parse(JSON.stringify(a.full));
  bFull.run_id = B_ID; bFull.correlation_id = B_ID; bFull.strategy_name = "모멘텀 (E2E)";
  bFull.result.backtest.statistics.total_return_pct = 24.9;
  bFull.result.backtest.statistics.sharpe_ratio = 1.15;
  bFull.result.backtest.equity_curve = [100, 106, 110, 115, 121];
  bFull.input_snapshot = { ...a.full.input_snapshot, strategy_name: "모멘텀", start_date: "2022-06-01" };
  const bLite = { ...a.lite, run_id: B_ID, strategy_name: "모멘텀 (E2E)" };

  await page.route("**/api/v1/backtest/runs", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [a.lite, bLite] }) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(a.full) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${B_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(bFull) }));

  await page.goto(`/backtest/runs/${STUB_RUN_ID}/compare`, { waitUntil: "networkidle" });
  await expect(page.locator("h1")).toContainText("실행 비교");
  // pick run B from the candidate list (completed, not A)
  const select = page.locator(".brun-select");
  await expect(select).toBeVisible();
  await select.selectOption(B_ID);

  // overlay + metric delta + config diff all render
  await expect(page.locator(".brun-card-t", { hasText: "정규화 자산곡선" })).toBeVisible();
  await expect(page.locator(".brun-card-t", { hasText: "지표 델타" })).toBeVisible();
  await expect(page.locator(".brun-card-t", { hasText: "설정 차이" })).toBeVisible();
  expect(await page.locator(".brun-cmp tbody tr").count(), "delta+diff rows").toBeGreaterThan(4);
  // config diff highlights the differing strategy/date rows
  await expect(page.locator(".brun-cmp-diff").first()).toBeVisible();
  const body = await page.locator("body").innerText();
  expect(body).toContain("모멘텀");
  expect(body).not.toMatch(/�/);

  expect(uniq(sink.api404), "compare API 404s").toEqual([]);
  expect(uniq(sink.pageErrors), "compare page errors").toEqual([]);
});

// ═══════════════════════════════════════════════════════════════════════════════
// S1b — 사유를 댈 수 있는 결측만 '산출 불가'로 드러낸다
// ─────────────────────────────────────────────────────────────────────────────
// 전에는 값이 없는 지표를 조용히 빼 버렸다(BacktestResults 의 `avail` 필터). 그러면 화면에서
// 계산 실패와 '원래 없는 항목'이 같은 모습이 된다.
//
// ★그렇다고 없는 값 전부에 '없음'을 붙이지는 않는다★ 이유를 모르면서 아는 척하게 되고,
// 사유 없는 '없음'은 그 자체로 지어낸 정보다. 그래서 두 규칙만 쓴다 —
// 벤치마크 미지정(IR), 체결 0건(거래 품질). 둘 다 화면이 이미 들고 있는 값으로 판정된다.
//
// ★기본 픽스처로는 이 경로가 한 번도 안 밟힌다★ completedRun() 은 벤치마크가 있고
// num_trades: 3 이라 '산출 불가'가 0개다. 그래서 아래 첫 테스트는 조건을 만들어서 검사하고,
// 두 번째 테스트가 '조건이 아닐 때는 뜨지 않는다'를 지킨다. 둘이 같이 있어야 계약이 닫힌다.
// ═══════════════════════════════════════════════════════════════════════════════

test("S1b: 벤치마크가 없고 체결이 0건이면 그 지표들을 '산출 불가'로 사유와 함께 적는다", async ({ page }) => {
  // 기존 픽스처를 깊은 복사해서 조건만 뒤집는다(compare 테스트가 쓰는 방식과 같다).
  const base = completedRun();
  const full = JSON.parse(JSON.stringify(base.full));
  full.result.backtest.benchmark = null;                    // → 정보비율(IR) 산출 불가
  full.result.backtest.statistics.num_trades = 0;           // → 거래 품질 산출 불가
  full.result.backtest.round_trips = [];
  full.result.backtest.trades = [];
  await page.route(`**/api/v1/backtest/runs/${STUB_RUN_ID}`, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(full) }));
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });

  const na = page.locator(".brun-kpi-na");
  expect(await na.count(), "산출 불가 카드").toBeGreaterThan(0);

  // 사유가 화면에 있어야 한다 — 배지만으로는 왜 없는지 알 수 없다.
  const naText = await na.allInnerTexts();
  expect(naText.join(" ")).toMatch(/벤치마크|체결이 한 건도/);
  for (const t of naText) expect(t, "'산출 불가' 표기").toContain("산출 불가");

  // ★핵심★ 숫자를 그리지 않는다. 0 이나 — 을 적으면 측정된 값처럼 읽힌다.
  for (const el of await na.all()) {
    expect(await el.locator(".brun-kpi-v").count(), "산출 불가에는 값 노드가 없어야 한다").toBe(0);
    const t = (await el.innerText()).replace("산출 불가", "");
    expect(t, "산출 불가 카드에 수치가 들어가면 안 된다").not.toMatch(/-?\d+\.?\d*\s*%/);
  }
});

test("S1b: 벤치마크와 체결이 있으면 '산출 불가'가 하나도 뜨지 않는다", async ({ page }) => {
  // 반대 방향 — 조건이 아닌데도 뜨면 없는 결측을 지어내는 셈이다.
  await stubCompletedRun(page);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  await expect(page.locator(".brun-kpi").first()).toBeVisible();
  expect(await page.locator(".brun-kpi-na").count(), "조건이 아니면 0개").toBe(0);
});

test("S1c: 차트 색이 토큰으로 실제 해석된다 (var() 가 SVG 에서 죽지 않는다)", async ({ page }) => {
  // ★이건 기능 테스트가 통과해도 안 잡히는 종류다★
  // stroke 를 "#1200ff" → "var(--chart-line)" 로 바꿨는데 그 변수가 정의돼 있지 않거나
  // SVG 속성에서 var() 가 해석되지 않으면 선은 검정/none 으로 그려진다. 결과 화면의
  // 기존 단언은 전부 그대로 통과한다 — 차트가 "있는지"만 보기 때문이다.
  await stubCompletedRun(page);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });

  const line = page.locator(".recharts-line-curve").first();
  await expect(line).toBeVisible();
  const stroke = await line.evaluate((e) => getComputedStyle(e).stroke);
  // 해석 실패 시 브라우저는 none / rgb(0,0,0) 을 준다.
  expect(stroke, "차트 선 색이 해석되지 않았다").not.toBe("none");
  expect(stroke, "차트 선이 검정으로 떨어졌다 — var() 가 죽었다").not.toBe("rgb(0, 0, 0)");
  // 토큰이 실제로 우리 액센트여야 한다(#1200ff = rgb(18, 0, 255)).
  expect(stroke).toBe("rgb(18, 0, 255)");
});

test("S1b: 지표 설명이 hover 전용이 아니다 (title= 제거)", async ({ page }) => {
  // ContextStrip 의 title= 16개를 걷어낸 P3 과 같은 규칙 — 키보드·터치에도 닿아야 한다.
  await stubCompletedRun(page);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });

  const kpi = page.locator(".brun-kpi").first();
  expect(await kpi.getAttribute("title"), "설명을 title= 로 숨기지 않는다").toBeNull();
  await expect(kpi.locator(".brun-kpi-tip")).toContainText(/\S/);
});

test("S1b: hover 밖으로 꺼낸 산문이 읽을 수 있는 크기다 (12px 하한)", async ({ page }) => {
  // ★위 테스트만으로는 절반이다★ 설명을 title= 에서 꺼내 놓고 10px 로 적으면 키보드·터치
  // 사용자에게 '보이기는 한다'로 끝난다 — 꺼낸 이유가 가독성인데 가독성을 다시 깎는 셈이다.
  // 실제로 처음 구현이 tip 10px / 배지 9.5px 이었고, 이 테스트가 그 회귀를 막는다.
  // 주변 표·라벨의 9~10.5px 은 대상이 아니다: 저건 수치와 라벨이지 산문이 아니다.
  const base = completedRun();
  const full = JSON.parse(JSON.stringify(base.full));
  full.result.backtest.benchmark = null;
  full.result.backtest.statistics.num_trades = 0;
  full.result.backtest.round_trips = [];
  full.result.backtest.trades = [];
  await page.route(`**/api/v1/backtest/runs/${STUB_RUN_ID}`, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(full) }));
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  await expect(page.locator(".brun-kpi").first()).toBeVisible();

  // 셀렉터가 0개면 조용히 통과한다 — 이 세션에서 세 번 겪은 '아무것도 안 지키는 초록'이다.
  for (const sel of [".brun-kpi-tip", ".brun-kpi-nabadge"]) {
    const nodes = page.locator(sel);
    expect(await nodes.count(), `${sel} 가 렌더돼야 검사가 성립한다`).toBeGreaterThan(0);
    const sizes = await nodes.evaluateAll((els) =>
      els.map((e) => parseFloat(getComputedStyle(e).fontSize)));
    for (const px of sizes) expect(px, `${sel} 본문 하한 12px`).toBeGreaterThanOrEqual(12);
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// S1b-2 — Card 로 감싼 뒤의 구조 · 다크 · 대비
// ─────────────────────────────────────────────────────────────────────────────
// 이 세 가지는 눈으로 보면 "괜찮아 보이는" 종류라서 계산으로 잡는다.
// 여백은 이중으로 쌓여도 그냥 넉넉해 보이고, 다크는 카드만 어두워도 다크처럼 보이며,
// 대비는 3.16:1 과 4.5:1 이 육안으로 거의 구분되지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════

// 대비 감사기는 e2e/helpers.ts 로 옮겼다 — A2 에서 목표 게이트도 같은 검사를 받는다.
// 40줄짜리 평가기를 표면마다 복붙하면 구현이 갈라진다(루트 선택자만 다르다).
const CONTRAST_AUDIT = contrastAudit(".brun-results");

test("S1b-2: Card 가 여백의 주인이다 — .brun-card 와 이중으로 쌓이지 않는다", async ({ page }) => {
  // before: .brun-card padding 12/14 + .brun-card-t margin-bottom 8
  // after : CardHeader(px-3 py-2) + CardContent(p-3) 만. 둘 다 살아 있으면 22.5px 이 된다.
  await stubCompletedRun(page);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  const cards = page.locator(".brun-results .brun-card");
  const n = await cards.count();
  expect(n, "결과 화면의 카드 수").toBeGreaterThanOrEqual(5);

  const seen = await cards.evaluateAll((els) => els.map((card) => {
    const cs = getComputedStyle(card);
    const title = card.querySelector(".brun-card-t");
    return {
      padTop: parseFloat(cs.paddingTop), padLeft: parseFloat(cs.paddingLeft),
      titleMb: title ? parseFloat(getComputedStyle(title).marginBottom) : -1,
      contentPad: card.children[1] ? parseFloat(getComputedStyle(card.children[1] as HTMLElement).paddingTop) : -1,
      root: parseFloat(getComputedStyle(document.documentElement).fontSize),
    };
  }));
  for (const s of seen) {
    expect(s.padTop, ".brun-card 자체 패딩은 0 (Card 하위가 가진다)").toBe(0);
    expect(s.padLeft, ".brun-card 자체 패딩은 0").toBe(0);
    expect(s.titleMb, ".brun-card-t 의 margin-bottom 은 CardHeader 가 대신한다").toBe(0);
    expect(s.contentPad, "CardContent = p-3 (root 기준 0.75rem)").toBeCloseTo(s.root * 0.75, 1);
  }
});

test("S1b-2: 카드 제목이 h2 로 헤딩 목차를 만든다 (레벨 건너뛰기 없음)", async ({ page }) => {
  // 전에는 전부 <div> 라 스크린리더에 목차가 없었다. CardTitle 기본값 h3 를 그대로 쓰면
  // h1 다음이 h3 가 되어 레벨을 건너뛴다 — 그래서 as="h2" 를 넣었다.
  await stubCompletedRun(page);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  const levels = await page.locator(".brun-results h1, .brun-results h2, .brun-results h3, .brun-results h4")
    .evaluateAll((els) => els.map((e) => Number(e.tagName[1])));
  expect(levels.length, "헤딩 수").toBeGreaterThanOrEqual(4);
  expect(levels[0], "첫 헤딩은 h1").toBe(1);
  for (let i = 1; i < levels.length; i++) {
    expect(levels[i] - levels[i - 1], `헤딩 레벨 건너뜀 (${levels[i - 1]}→${levels[i]})`).toBeLessThanOrEqual(1);
  }
  // 카드 제목이 전부 헤딩이어야 한다 — 하나라도 div 로 남으면 목차에 구멍이 난다.
  const titleTags = await page.locator(".brun-results .brun-card-t").evaluateAll((els) => els.map((e) => e.tagName));
  expect(new Set(titleTags), "모든 .brun-card-t 가 H2").toEqual(new Set(["H2"]));
});

test("★S1b-2: 결과 화면 텍스트가 라이트·다크 양쪽에서 WCAG AA 를 넘는다★", async ({ page }) => {
  // ★이 테스트가 실제로 잡은 것 두 가지★
  //  ① .dark 의 --chart-* 가 죽어 있었다. :root 라이트 기본값을 .dark 뒤에 두는 바람에
  //     특이도가 같아 뒤가 이겼고, 다크에서 빨강이 #dc2626(3.67:1) 그대로였다.
  //     토큰은 "정의돼 있었지만 한 번도 적용되지 않은" 상태였고 기존 테스트는 전부 초록이었다.
  //  ② 라이트의 --chart-up(#16a34a)이 3.16:1 로 미달이었다. stroke 로는 충분(3:1)하지만
  //     같은 토큰이 수익률 숫자의 글자색이라 4.5:1 을 받아야 한다.
  await stubCompletedRun(page);
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  await expect(page.locator(".brun-kpi").first()).toBeVisible();

  const light = await page.evaluate<AuditResult>(CONTRAST_AUDIT);
  // 검사한 노드가 0 이면 조용히 통과한다 — 이 세션에서 반복해서 겪은 실패 모양이다.
  expect(light.checked, "라이트에서 검사한 텍스트 노드 수").toBeGreaterThan(20);
  expect(light.low, "라이트: AA 미달 텍스트").toEqual([]);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(CONTRAST_AUDIT);
  expect(dark.checked, "다크에서 검사한 텍스트 노드 수").toBeGreaterThan(20);
  expect(dark.low, "다크: AA 미달 텍스트").toEqual([]);
  // ★"반만 다크"를 막는다★ 카드만 어둡고 어딘가 흰 판이 남아 있으면 그게 더 나쁘다(§47).
  expect(dark.bright, "다크인데 밝은 배경이 남아 있다").toEqual([]);
});
