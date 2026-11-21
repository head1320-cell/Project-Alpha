import { test, expect, type Page, type Request } from "./fixtures";

// ═══════════════════════════════════════════════════════════════════════════════
// F3 (2026-11-21) — 운영에서 확인된 시세가 없는 종목의 `/insights`
// ─────────────────────────────────────────────────────────────────────────────
// 서버는 운영에서 합성 바탕 가격을 쓰지 않는다(감사 F3 · 사용자 결정 3 → 1). 실시세도 적재 일봉 종가도 없는 종목은
// 가격 파생 값(현재가 · 괴리율 · 종합 점수 · 괴리 점수 · PER · PBR · 배당수익률)이 null 이고 판정은 "시세 없음"이다.
// E2E 는 mock(`KIS_USE_MOCK=1`)이라 서버가 그런 항목을 내지 않는다 → 종목 한 건 응답(`byTicker`)만 운영의 모양으로 고친다.
// 지키는 것:
//   · 현재가가 필요한 계산(가치평가 evaluate · 밸류에이션 밴드 · 여러 모형 · 재무 위험)을 ★묻지 않는다★ — 0 원이나 null 을 보내지 않는다
//   · 답 문장은 판정을 보류하고 까닭을 말한다 · 현재가 자리는 N/A · 0원 · 0점을 그리지 않는다
//   · ★짝★ 시세가 있으면(고치지 않은 mock 응답) 예전처럼 묻고 그린다
// ═══════════════════════════════════════════════════════════════════════════════

const API = "**/api/backend/api/v1";
/** 현재가를 쓰는 요청 — 시세가 없으면 하나도 나가면 안 된다. */
const PRICED = ["/valuation/evaluate", "/valuation-sandbox", "/risk-deep", "/reverse-dcf", "/valuation-distribution",
  "/macro-sensitivity", "/models/"];

async function asProductionWithoutPrice(page: Page) {
  await page.route(`${API}/screener/run-advanced`, async (route) => {
    const body = route.request().postDataJSON() as { custom_tickers?: string[]; limit?: number };
    const res = await route.fetch();
    const json = await res.json();
    if (body.custom_tickers?.length === 1 && body.limit === 1 && json.items?.[0]) {
      Object.assign(json.items[0], {
        current_price: null, gap_pct: null, composite_score: null, gap_score: null, per: null, pbr: null,
        dividend_yield_pct: null, verdict: "시세 없음", price_is_mock: false, price_source: null,
        price_unavailable: { live: "kis_credentials_missing", close: "not_loaded" },
      });
    }
    await route.fulfill({ response: res, json });
  });
}

function watchPriced(page: Page): { priced: string[]; nullPrice: string[] } {
  const seen = { priced: [] as string[], nullPrice: [] as string[] };
  page.on("request", (r: Request) => {
    const u = r.url();
    if (!u.includes("/api/backend/")) return;
    if (PRICED.some((p) => u.includes(p))) seen.priced.push(u);
    const body = r.postData() ?? "";
    if (/price=(null|undefined|NaN)\b/.test(u) || /"(current_)?price"\s*:\s*null/.test(body)) seen.nullPrice.push(u);
  });
  return seen;
}

async function open(page: Page, code = "005930") {
  await page.goto(`/insights?code=${code}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ci .ci-head h1")).toBeVisible({ timeout: 40_000 });
}

test("시세가 없는 종목 — 현재가가 필요한 계산을 묻지 않고 판정을 보류하며 까닭을 말한다", async ({ page }) => {
  await asProductionWithoutPrice(page);
  const seen = watchPriced(page);
  await open(page);
  await expect(page.locator(".ci .tx-answer-s")).toHaveText("시세 없음. 현재가가 없어 판정을 보류합니다.", { timeout: 40_000 });
  await expect(page.locator(".ci")).toContainText("시세 없음 · 가치평가 계산 안 함");
  await expect(page.locator(".ci-head .ci-price")).toHaveText("N/A");
  // 내재가치는 가격과 무관하다 — 시세가 없어도 서버가 낸 값(원)이 보인다(판정만 보류)
  await expect(page.locator(".ci .tx-fig", { hasText: "내재가치" }).locator("dd")).toHaveText(/^[\d,]+원$/);
  // 종합점수 자리는 0점이 아니라 미상 + 사유
  const numbers = page.locator(".ci-sec[data-sec=numbers]");
  await numbers.evaluate((e) => e.scrollIntoView({ block: "start" }));
  await expect(numbers.locator(".ca-cp-judge .tx-unknown").first()).toContainText("시세 없음");
  // 절을 모두 지나간 뒤에도 현재가를 쓰는 요청이 하나도 없다
  for (const s of ["value", "models", "numbers", "money", "risk", "peers", "factors"]) {
    await page.locator(`.ci-sec[data-sec=${s}]`).evaluate((e) => e.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(300);
  }
  await page.waitForTimeout(1500);
  expect(seen.priced).toEqual([]);
  expect(seen.nullPrice).toEqual([]);
});

test("짝 — 시세가 있으면 예전처럼 가치평가를 묻고 판정한다", async ({ page }) => {
  const seen = watchPriced(page);
  await open(page);
  await expect(page.locator(".ci .tx-answer-s")).not.toHaveText("시세 없음. 현재가가 없어 판정을 보류합니다.", { timeout: 40_000 });
  await expect(page.locator(".ci-head .ci-price")).not.toHaveText("N/A");
  await expect(page.locator(".ci")).not.toContainText("시세 없음 · 가치평가 계산 안 함");
  await expect.poll(() => seen.priced.filter((u) => u.includes("/valuation/evaluate")).length, { timeout: 40_000 }).toBeGreaterThan(0);
  expect(seen.nullPrice).toEqual([]);
});
