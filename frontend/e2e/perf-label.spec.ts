import { test, expect, type Page } from "@playwright/test";
import { STUB_RUN_ID, completedRun, freezeCharts, trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Z — 성과 상태 라벨 `.perf-label` (애드덤 §4 / 합격기준 #3)
// ─────────────────────────────────────────────────────────────────────────────
// 백엔드 어휘와 파생은 pytest 가 지킨다(`test_perf_kind` 16 · `test_perf_label_wiring` ·
// `test_perf_label_contract` 11). ★이 스펙이 지키는 것은 pytest 가 볼 수 없는 것★ —
// **화면이 실제로 무엇을 그리는가** 다.
//
//   1. 응답이 말한 종류가 화면에 나온다
//   2. ★응답이 아무 말도 안 하면 `unknown` 이다★ — `backtest` 로 기울지 않는다
//   3. ★백테스트 페이지라도 응답이 `paper` 라면 화면은 모의투자라고 쓴다★
//      — 이 설계의 핵심 주장이다. 라벨은 **배치가 아니라 사실**이다.
//   4. 두 축(`kind` / `data_real`)이 독립이다
//   5. 알아보지 못한 값도 `unknown` 이고 **본 값이 사유에 실린다**
//
// ★새 클래스도 계약이다★ — ADR 001("클래스명을 만들면 스펙도 함께"). 여기서 단정하는
// `.perf-label*` 를 바꾸려면 이 파일도 함께 고쳐야 한다. 기존 `brun-*`·`tbt-prov`·
// `as-bt-badge` 는 **한 글자도 건드리지 않았다**.
// ═══════════════════════════════════════════════════════════════════════════════

const B_ID = "bt_stub_e2e_2";

/** 실행 비교 화면을 A/B 두 라벨로 띄운다. `null` 을 주면 그 키를 아예 뺀다. */
async function openCompare(
  page: Page,
  aLabel: unknown | null,
  bLabel: unknown | null,
) {
  const a = completedRun();
  const aFull = JSON.parse(JSON.stringify(a.full));
  const bFull = JSON.parse(JSON.stringify(a.full));
  bFull.run_id = B_ID;
  bFull.correlation_id = B_ID;
  bFull.strategy_name = "모멘텀 (E2E)";
  bFull.result.backtest.statistics.total_return_pct = 24.9;
  const bLite = { ...a.lite, run_id: B_ID, strategy_name: "모멘텀 (E2E)" };

  // ★키를 "넣지 않는 것" 과 "null 을 넣는 것" 은 다른 상태다★ — 전자를 재려면
  // 정말로 키가 없어야 한다. `completedRun()` 픽스처는 원래 이 키가 없다.
  if (aLabel !== null) aFull.perf_label = aLabel;
  if (bLabel !== null) bFull.perf_label = bLabel;

  await page.route("**/api/v1/backtest/runs", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [a.lite, bLite] }) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(aFull) }));
  await page.route(new RegExp(`/api/v1/backtest/runs/${B_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(bFull) }));

  await page.goto(`/backtest/runs/${STUB_RUN_ID}/compare`, { waitUntil: "networkidle" });
  await expect(page.locator("h1")).toContainText("실행 비교");
  await page.locator(".brun-select").selectOption(B_ID);
  await expect(page.locator(".brun-cmp-labels")).toBeVisible();
}

const BACKTEST_SYNTHETIC = {
  kind: "backtest", kind_reason: null,
  data_real: false, data_reason: null,
};

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

// ── 1. 응답이 말한 종류가 화면에 나온다 ──────────────────────────────────────

test("★응답이 선언한 종류를 화면이 그대로 그린다★", async ({ page }) => {
  const sink = trackErrors(page);
  await openCompare(page, BACKTEST_SYNTHETIC, BACKTEST_SYNTHETIC);

  const labels = page.locator(".brun-cmp-labels .perf-label");
  await expect(labels).toHaveCount(2);
  await expect(labels.first()).toHaveClass(/perf-label--backtest/);
  await expect(labels.first().locator(".perf-label__kind")).toHaveText("백테스트");
  await expect(labels.first().locator(".perf-label__data")).toHaveText("합성데이터");

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

// ── 2. ★응답이 말하지 않으면 `unknown`★ (변이 i 를 죽인다) ──────────────────

test("★`perf_label` 이 없으면 `unknown` 이다 — `backtest` 로 기울지 않는다★", async ({ page }) => {
  // `completedRun()` 픽스처에는 이 키가 아예 없다. 백테스트 결과 페이지 위인데도
  // 화면이 "백테스트" 라고 **추측하면 안 된다** — 그것이 이 설계의 반대편이다.
  await openCompare(page, null, null);

  const labels = page.locator(".brun-cmp-labels .perf-label");
  await expect(labels).toHaveCount(2);
  await expect(labels.first()).toHaveClass(/perf-label--unknown/);
  await expect(labels.first()).not.toHaveClass(/perf-label--backtest/);
  await expect(labels.first().locator(".perf-label__kind")).toHaveText("미상");
  // ★왜 모르는지도 함께 나온다★ — 빈 `unknown` 은 사유 없는 "unavailable" 과 같다.
  await expect(labels.first().locator(".perf-label__why"))
    .toContainText("종류를 말하지 않습니다");
});

// ── 3. ★핵심 주장★ 라벨은 배치가 아니라 사실이다 ────────────────────────────

test("★백테스트 화면이라도 응답이 `paper` 면 화면은 모의투자라고 쓴다★", async ({ page }) => {
  await openCompare(page, { kind: "paper", data_real: null, data_reason: null }, BACKTEST_SYNTHETIC);

  const labels = page.locator(".brun-cmp-labels .perf-label");
  await expect(labels.nth(0)).toHaveClass(/perf-label--paper/);
  await expect(labels.nth(0).locator(".perf-label__kind")).toHaveText("모의투자");
  // 같은 화면의 B 는 여전히 백테스트다 — ★한 화면이 한 종류라고 가정하지 않는다★.
  await expect(labels.nth(1)).toHaveClass(/perf-label--backtest/);
});

// ── 4. 두 축이 독립이다 ─────────────────────────────────────────────────────

test("★`kind` 와 `data_real` 은 다른 축이다★ — 실데이터 백테스트도 있다", async ({ page }) => {
  await openCompare(
    page,
    { kind: "backtest", data_real: true, data_reason: null },
    { kind: "paper", data_real: false, data_reason: null },
  );

  const labels = page.locator(".brun-cmp-labels .perf-label");
  await expect(labels.nth(0).locator(".perf-label__kind")).toHaveText("백테스트");
  await expect(labels.nth(0).locator(".perf-label__data")).toHaveText("실데이터");
  await expect(labels.nth(1).locator(".perf-label__kind")).toHaveText("모의투자");
  await expect(labels.nth(1).locator(".perf-label__data")).toHaveText("합성데이터");
});

test("★데이터 축이 `null` 이면 '데이터 미상' 이다 — `false`(합성) 로 접지 않는다★", async ({ page }) => {
  await openCompare(page, { kind: "backtest", data_real: null, data_reason: null }, BACKTEST_SYNTHETIC);
  const first = page.locator(".brun-cmp-labels .perf-label").first();
  await expect(first.locator(".perf-label__data")).toHaveText("데이터 미상");
});

// ── 5. 알아보지 못한 값 ─────────────────────────────────────────────────────

test("★알아보지 못한 종류는 `unknown` 이고 본 값이 사유에 실린다★", async ({ page }) => {
  await openCompare(page, { kind: "totally_new_kind", data_real: false }, BACKTEST_SYNTHETIC);

  const first = page.locator(".brun-cmp-labels .perf-label").first();
  await expect(first).toHaveClass(/perf-label--unknown/);
  await expect(first.locator(".perf-label__why")).toContainText("totally_new_kind");
  // ★데이터 축은 그대로 살려 둔다★ — 종류를 못 알아본 것이 데이터 사실을 지우지 않는다.
  await expect(first.locator(".perf-label__data")).toHaveText("합성데이터");
});

// ── 6. 어느 종류든 보여야 한다 (다크 포함) ──────────────────────────────────

test("★라벨은 라이트/다크 양쪽에서 보인다★ — 하드코딩 hex 를 쓰지 않은 이유", async ({ page }) => {
  await openCompare(page, BACKTEST_SYNTHETIC, { kind: "live", data_real: true });

  const labels = page.locator(".brun-cmp-labels .perf-label");
  await expect(labels.nth(1).locator(".perf-label__kind")).toHaveText("실계좌");

  // ★다크는 `prefers-color-scheme` 이 아니라 `.dark` 클래스다★ — `aas-dark.spec.ts:53`
  // 이 쓰는 것과 같은 방법으로 켠다. `emulateMedia` 로 켜면 아무 일도 일어나지 않고
  // 테스트는 조용히 통과한다(= 아무것도 재지 않는다).
  const read = () => page.evaluate(() => {
    const el = document.querySelector(".brun-cmp-labels .perf-label") as HTMLElement | null;
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { color: cs.color, bg: cs.backgroundColor, border: cs.borderTopColor };
  });

  const light = await read();
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  const dark = await read();

  expect(light, "라이트에서 라벨을 찾지 못했다").not.toBeNull();
  expect(dark, "다크에서 라벨을 찾지 못했다").not.toBeNull();
  // ★토큰을 썼다면 테마가 바뀔 때 값이 따라 바뀐다★ — 하드코딩 hex 면 그대로 남는다.
  expect(dark!.bg, "배경이 다크에서 그대로다 — 라이트 리터럴을 의심하라").not.toBe(light!.bg);
  expect(dark!.color, "글자색이 다크에서 그대로다").not.toBe(light!.color);
});
