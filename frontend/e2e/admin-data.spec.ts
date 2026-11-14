import { expect, test } from "./fixtures";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// /admin/data — DB 상태 패널 + **출처별 연구 등급** (Phase 8b 요구 4).
//
// 두 가지 구멍을 함께 메운다:
//  1. 이 라우트에는 E2E 가 **하나도 없었다** — admin.spec.ts 가 다른 세 라우트에 대해
//     메운 것과 같은 구멍이다(마운트 실패·API 404 를 아무도 못 본다).
//  2. Phase 8b 의 정직성 라벨은 백엔드만 테스트돼 있었다. 렌더된다는 보장이 없었고,
//     보장이 없으면 조용히 사라져도 알 수 없다.
//
// ★이 화면의 요점은 "두 축이 따로 보인다" 는 것이다★ (스펙 §3.5)
// "가져올 수 있다"(data_status)와 "과거 검증에 쓸 수 있다"(research_usage)는 다른 축이다.
// 하나로 합쳐 보여주면 사용자는 조회되는 모든 것을 백테스트에 써도 된다고 읽는다.
//
// 선택자 주의: BU7b 부터 h1 "데이터 상태" + 절 제목(h2)으로 구성된다(옛 영어 소제목 "DATA SOURCES" 는 없다).
// 화면 모습·확인 창·실패 상태는 `data-status.spec.ts` 가 본다.
// ═══════════════════════════════════════════════════════════════════════════════

test("/admin/data: 마운트되고 페이지 에러·API 404 가 없다", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/admin/data", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "원천별 연구 등급" })).toBeVisible({ timeout: 20_000 });

  // 클라이언트 페치가 끝난 뒤에도 살아 있는지 — "렌더되고 첫 응답에서 죽는" 경우를 잡는다.
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(1_000);
  await expect(page.getByRole("heading", { name: "원천별 연구 등급" })).toBeVisible();

  const body = await page.locator("body").innerText();
  expect(body, "한글이 깨지면 안 된다").not.toMatch(/�/);
  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("정직성 라벨: 출처마다 두 축이 **따로** 보인다", async ({ page }) => {
  await page.goto("/admin/data", { waitUntil: "networkidle" });
  const rows = page.locator(".t-honesty-row");
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  expect(await rows.count(), "출처가 하나도 없다").toBeGreaterThanOrEqual(4);

  for (const row of await rows.all()) {
    // ★두 배지가 모두 있어야 한다★ 하나로 합치면 §3.5 의 구별이 화면에서 사라진다.
    await expect(row.locator(".t-honesty-st")).toHaveCount(1);
    await expect(row.locator(".t-honesty-use")).toHaveCount(1);
    // 왜 그 등급인지도 함께 — 등급만 있으면 사용자가 무엇을 확인해야 할지 모른다.
    expect((await row.locator(".t-honesty-why").innerText()).trim().length).toBeGreaterThan(5);
  }
});

test("정직성 라벨: mock 모드와 키 부재가 화면까지 정직하게 내려온다", async ({ page }) => {
  // 이 환경은 KIS_USE_MOCK=1 이고 FRED_API_KEY 가 없다. 그 사실이 등급으로 드러나야 한다 —
  // 드러나지 않으면 사용자는 합성 데이터를 실데이터로 오해한다.
  await page.goto("/admin/data", { waitUntil: "networkidle" });
  await expect(page.locator(".t-honesty-row").first()).toBeVisible({ timeout: 20_000 });

  const prices = page.locator(".t-honesty-row", { hasText: "ETF" }).first();
  await expect(prices.locator(".t-honesty-use")).toHaveClass(/u-forward_only/);

  const fred = page.locator(".t-honesty-row", { hasText: "FRED" }).first();
  await expect(fred.locator(".t-honesty-use")).toHaveClass(/u-unavailable/);
});

test("정직성 라벨: 등급마다 다른 클래스를 쓴다 (눈으로 구별 가능해야 한다)", async ({ page }) => {
  // ★같은 스타일이면 구별이 없는 것과 같다★ 이 화면의 존재 이유가 구별이다.
  await page.goto("/admin/data", { waitUntil: "networkidle" });
  await expect(page.locator(".t-honesty-row").first()).toBeVisible({ timeout: 20_000 });

  const classes = await page.locator(".t-honesty-use").evaluateAll(
    (els: Element[]) => els.map(
      (e) => (e.className || "").split(/\s+/).find((c: string) => c.startsWith("u-"))));
  const distinct = new Set(classes.filter(Boolean));
  expect(distinct.size, `등급 클래스가 ${distinct.size}종 — 서로 다른 등급이 같게 보인다`)
    .toBeGreaterThanOrEqual(2);
});

// ── 분봉 적재 (ADR 006 §7) ───────────────────────────────────────────────────────────
// 분봉의 적재 범위는 '백테스트 › 분봉 규칙' 안에만 있었다 — 적재 현황을 보는 이 화면에도 같은 문(`GET /intraday/coverage`)으로 둔다.
// 분봉은 DB 표가 아니라 일파일이라 '표별 적재'에 섞지 않고 절을 따로 둔다. ★값이 없으면 0 이 아니라 사유★.

const BE = "/api/backend/api/v1";
const minute = (page: import("@playwright/test").Page) => page.locator(".dsx-minute");
async function signIn(page: import("@playwright/test").Page) {
  const r = await page.request.post(`${BE}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
}
const coverage = (sources: { kis: number; synthetic: number; unknown: number }, loaded: number) => ({
  from: "2026-10-15", to: "2026-11-14", gate: { mock: true }, days: [],
  summary: { calendar_days: 31, loaded_days: loaded, blocked_days: 0, unreadable_days: 0, not_checked_days: 0,
             bars: sources.kis + sources.synthetic + sources.unknown, sources, defect_total: 3 },
  empty: null, session_rules: { available: true, open: "0900", closing_auction_from: "1520", close: "1530", grade: "T1", reason: null, message: null },
  unknowns: [], limits: { days: 31, tickers: 30 },
});

test("분봉 적재: 로그인 전에는 서버에 묻지 않고 로그인하라고 말한다", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/intraday/coverage")) asked.push(r.url()); });
  await page.goto("/admin/data", { waitUntil: "networkidle" });
  await expect(minute(page).getByRole("heading", { name: "분봉 적재" })).toBeVisible();
  await expect(minute(page)).toContainText("로그인하면 분봉 적재 범위를 조회할 수 있습니다.");
  await expect(minute(page).locator(".dsx-minute-read")).toHaveCount(0);            // 모르는 것을 0 으로 그리지 않는다
  await expect(minute(page).locator('a[href="/backtest/intraday"]')).toBeVisible();
  expect(asked).toEqual([]);
});

test("분봉 적재: 적재가 없으면 0 이 아니라 서버 사유 (짝: 있으면 날·봉·출처별 행 수 · 합성이면 합성이라고 · 실패는 재시도)", async ({ page }) => {
  await signIn(page);
  await page.goto("/admin/data", { waitUntil: "domcontentloaded" });                // 실제 서버 — 최근 한 달에는 심은 분봉이 없다
  await expect(minute(page)).toContainText("이 기간에 적재된 분봉이 없습니다.");
  await expect(minute(page).locator(".dsx-minute-read")).toHaveCount(0);

  let mode: "synthetic" | "real" | "fail" = "synthetic";
  await page.route("**/api/v1/intraday/coverage*", (r) => mode === "fail" ? r.fulfill({ status: 500, json: { detail: "읽기 실패(시험)" } })
    : r.fulfill({ json: mode === "synthetic" ? coverage({ kis: 0, synthetic: 1_560, unknown: 0 }, 2) : coverage({ kis: 780, synthetic: 0, unknown: 0 }, 1) }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(minute(page).locator(".dsx-minute-read")).toHaveText("2026-10-15 ~ 2026-11-14 · 달력 31일 가운데 적재된 날 2일 · 봉 1,560개 · 결함 3건");
  await expect(minute(page).locator('[data-k="kis"] dd')).toHaveText("0행");
  await expect(minute(page).locator('[data-k="synthetic"] dd')).toHaveText("1,560행");
  await expect(minute(page).locator(".tx-notice-t")).toHaveText("합성 분봉이 섞여 있습니다.");

  mode = "real";                                                                     // 짝: 실제 응답뿐이면 합성 알림이 없다
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(minute(page).locator(".dsx-minute-read")).toContainText("적재된 날 1일 · 봉 780개");
  await expect(minute(page).locator('[data-k="kis"] dd')).toHaveText("780행");
  await expect(minute(page).locator(".tx-notice")).toHaveCount(0);

  mode = "fail";
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(minute(page).getByRole("alert")).toContainText("분봉 적재 범위 조회 실패");
  await expect(minute(page).locator(".dsx-minute-read")).toHaveCount(0);
  mode = "real";
  await minute(page).getByRole("button", { name: "재시도" }).click();
  await expect(minute(page).locator(".dsx-minute-read")).toContainText("봉 780개");
});
