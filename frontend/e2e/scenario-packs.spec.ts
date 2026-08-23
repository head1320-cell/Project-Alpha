import { expect, test } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// ScenarioPackV2 — model_type · 팩 신원 · 시나리오×3자 비교 (스펙 §5, Phase 9).
//
// ★스펙 §5 가 막으려는 실패는 하나다★
//   "가상 충격이 역사적 사실처럼 제시되는 것."
// Phase 9 이전에는 화면 어디에도 그 구별이 없었다 — 국내 시나리오팩 7종은 `mode: "kr_pack"`
// 이라는 *분류*만 달고 있었고, 그건 "이것이 가정이다" 를 말해 주지 않는다.
//
// 그래서 이 스펙이 확인하는 것은 라벨이 **결과가 보이는 모든 곳에** 있는지다. 선택 창에만
// 있으면 정작 숫자를 보는 자리에서 사라지고, 그건 라벨이 없는 것과 거의 같다.
// ═══════════════════════════════════════════════════════════════════════════════

const OPEN = ".as-fb-apply";

/**
 * 포트폴리오를 심는다. ★없으면 3자 비교 패널이 빈 상태로 남는다★ — 그러면 아래 단언들이
 * "통과" 하면서 아무것도 검증하지 못한다(7b 의 헛돈 게이트와 같은 함정). 프로바이더가
 * 새로고침을 견디려고 쓰는 것과 **같은** 키를 쓴다.
 */
async function seedPortfolio(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    sessionStorage.setItem("alpha_alloc_wip", JSON.stringify({
      holdings: [{ code: "005930", name: "삼성전자", weight: 60 },
                 { code: "000660", name: "SK하이닉스", weight: 40 }],
      views: [], model: "bl",
    }));
  });
}

async function openPicker(page: import("@playwright/test").Page) {
  await seedPortfolio(page);
  await page.goto("/allocation/stress", { waitUntil: "networkidle" });
  await page.locator(OPEN, { hasText: "시나리오 창에서 선택" }).click();
  await expect(page.locator(".tfm")).toBeVisible();
}

/**
 * 검색어를 넣으면 셸이 **패밀리를 넘어 전체**에서 찾는다 — 두 등급을 한 화면에 모으는 길.
 *
 * ★공백은 쓸 수 없다★ 셸이 `q.trim()` 으로 판정하므로 공백만 넣으면 검색이 아니라 패밀리
 * 필터로 되돌아간다(그러면 한 패밀리만 보이고 등급도 한 종류만 나온다). `"실제"` 는 두
 * model_type 라벨("역사 리플레이 (**실제** 시세)" · "가정 충격 (**실제**로 일어난 적 없음)")에
 * 모두 들어 있고 그 라벨은 전 항목의 `searchExtra` 에 실려 있어, 결과가 전체가 된다.
 */
const ALL = "실제";

async function searchAll(page: import("@playwright/test").Page, q: string = ALL) {
  await page.locator(".tfm .tfm-search").fill(q);
  await expect(page.locator(".tfm .tfm-row").first()).toBeVisible({ timeout: 20_000 });
}

test("model_type: 목록의 모든 시나리오가 역사인지 가정인지 스스로 밝힌다", async ({ page }) => {
  await openPicker(page);
  await searchAll(page);

  const rows = page.locator(".tfm .tfm-row");
  const n = await rows.count();
  expect(n, "시나리오가 하나도 없다").toBeGreaterThan(10);

  for (let i = 0; i < n; i++) {
    await expect(rows.nth(i).locator(".as-model-type"),
      `${i}번째 행에 model_type 배지가 없다`).toHaveCount(1);
  }
});

test("model_type: 두 등급이 다른 클래스를 쓴다 (눈으로 구별 가능해야 한다)", async ({ page }) => {
  // ★같은 스타일이면 구별이 없는 것과 같다★ 이 배지의 존재 이유가 구별이다.
  // 한 패밀리 안에서는 등급이 하나뿐일 수 있으므로 **전체 목록**에서 센다.
  await openPicker(page);
  await searchAll(page);

  const classes = await page.locator(".tfm .as-model-type").evaluateAll(
    (els: Element[]) => els.map(
      (e) => (e.className || "").split(/\s+/).find((c: string) => c.startsWith("mt-"))));
  const distinct = new Set(classes.filter(Boolean));
  expect(distinct, `등급 클래스가 ${[...distinct]} — 서로 다른 등급이 같게 보인다`)
    .toEqual(new Set(["mt-historical_replay", "mt-hypothetical"]));
});

test("model_type: 국내 시나리오팩은 **가정**이라고 적힌다 (역사가 아니다)", async ({ page }) => {
  // Phase 9 이전의 정확한 구멍 — kr_pack 은 패밀리였을 뿐 인식론적 주장이 아니었다.
  await openPicker(page);
  await page.locator(".tfm .tfm-search").fill("반도체");
  const row = page.locator(".tfm .tfm-row").first();
  await expect(row.locator(".as-model-type")).toHaveClass(/mt-hypothetical/);

  await row.click();
  await expect(page.locator(".tfm-right .as-model-type")).toContainText("실제로 일어난 적 없음");
});

test("model_type: 역사 리플레이만 실제 시세를 주장한다", async ({ page }) => {
  await openPicker(page);
  await page.locator(".tfm .tfm-search").fill("코로나");
  const row = page.locator(".tfm .tfm-row").first();
  await expect(row.locator(".as-model-type")).toHaveClass(/mt-historical_replay/);
});

test("팩 신원: 라벨이 아니라 pack_id@hash 가 재현 좌표다", async ({ page }) => {
  await openPicker(page);
  await page.locator(".tfm .tfm-search").fill("반도체");
  await page.locator(".tfm .tfm-row").first().click();
  // 라벨은 계수가 바뀌어도 그대로다 — 해시는 충격 정의를 따라간다.
  await expect(page.locator(".tfm-right")).toContainText(/semi_selloff@[0-9a-f]{12}/);
});

test("결과 자리에도 라벨이 있다 — 칩과 컨텍스트 스트립", async ({ page }) => {
  const sink = trackErrors(page);
  await openPicker(page);
  await page.locator(".tfm .tfm-search").fill("반도체");
  await page.locator(".tfm .tfm-row").first().click();
  await page.locator(OPEN, { hasText: "이 시나리오로 검증" }).click();
  await expect(page.locator(".tfm")).toHaveCount(0);

  // ① 좌측 칩 — 선택 창을 닫은 뒤에도 등급이 남아 있어야 한다
  await expect(page.locator(".tfc-chip .as-model-type")).toHaveClass(/mt-hypothetical/);

  // ② 컨텍스트 스트립 (스펙 §4 ⑦) — 라벨만이 아니라 팩 신원까지
  const scen = page.locator(".as-ctx-scen");
  await expect(scen).toContainText("반도체");
  await expect(scen.locator(".as-model-type")).toHaveCount(1);
  await expect(scen.locator(".as-ctx-scen-id")).toContainText(/[0-9a-f]{12}/);

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("시나리오×3자 비교: 판정 불가인 다리에 0% 를 적지 않는다", async ({ page }) => {
  // ★스냅샷이 없으면 timing_macro 는 노출 0 의 unavailable 이다★
  // 거기에 0% 손실을 적으면 **만들지 못한 비교가 셋 중 가장 안전해 보인다.**
  const sink = trackErrors(page);
  await seedPortfolio(page);
  await page.goto("/allocation/stress", { waitUntil: "networkidle" });

  const panel = page.locator(".as-s3w");
  await expect(panel).toBeVisible({ timeout: 20_000 });

  // ★전제조건을 먼저 단정한다★ 다리가 렌더되지 않았다면 아래 단언은 통과해도 무의미하다.
  const legs = panel.locator(".as-s3w-leg");
  await expect(legs.first()).toBeVisible({ timeout: 20_000 });
  await expect(legs).toHaveCount(3);

  // 스냅샷을 붙이지 않았으므로 매크로 다리는 판정 불가여야 한다.
  const macro = panel.locator(".as-s3w-leg.timing_macro");
  await expect(macro.locator(".as-s3w-na")).toContainText("판정 불가");
  await expect(macro.locator(".as-s3w-loss"), "판정 불가인데 손실이 적혔다").toHaveCount(0);
  // 판정된 다리에는 숫자가 있어야 한다 — 전부 비면 이 테스트가 헛돈다.
  await expect(panel.locator(".as-s3w-leg.timing_only .as-s3w-loss")).toBeVisible();

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.api404), "API 404s").toEqual([]);
});

test("시나리오×3자 비교: 선형 근사라는 사실이 화면에 있다", async ({ page }) => {
  await seedPortfolio(page);
  await page.goto("/allocation/stress", { waitUntil: "networkidle" });
  const panel = page.locator(".as-s3w");
  await expect(panel.locator(".as-s3w-leg").first()).toBeVisible({ timeout: 20_000 });
  // run_scenario 가 자기 선형 근사를 notes 에 적는 것과 같은 이유 — 숨기지 않는다.
  await expect(panel).toContainText("선형");
});
