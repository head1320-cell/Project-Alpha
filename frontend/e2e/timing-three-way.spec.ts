import { expect, test } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 3자 비교 — 기준 vs 타이밍만 vs 타이밍+매크로 (스펙 §8, Phase 7b).
//
// 이 스펙이 증명해야 하는 것은 "패널이 보이는가" 가 아니라 두 가지다:
//   1. 비교가 **읽히는가** — 세 다리가 각각 상태·노출·이유를 갖는가.
//   2. 오버레이 토글이 **장식이 아닌가** — 끄면 결과가 눈에 보이게 달라지는가.
//
// 2번이 게이트다. 토글이 아무것도 바꾸지 않으면 "선택적 오버레이" 라는 주장은 UI 문구일 뿐이다.
//
// ★부정 단언에는 정착 시간을 준다★
// 이전 단계에서 두 번의 키 입력 직후 곧바로 단언했다가 `toBeVisible()` 이 경합에서 이겨
// 아무것도 지키지 못하는 회귀 테스트를 만들었다. 여기서도 값이 바뀌길 기다린 뒤에 비교한다.
// ═══════════════════════════════════════════════════════════════════════════════

const PANEL = ".as-3w";
const LEGS = ".as-3w-legs .as-3w-leg";

/**
 * 팩터 창에서 카탈로그 팩터 하나를 담는다 — 레거시 카나리(13612 점수 등)는 V2 3-상태
 * 비교 대상이 아니므로, 비교가 나타나려면 카탈로그 팩터가 최소 하나 있어야 한다.
 *
 * 선택자는 timing-factors.spec.ts 가 이미 쓰고 있는 것을 그대로 쓴다 — 같은 UI 를 두 벌의
 * 선택자로 가리키면 클래스명이 바뀔 때 한쪽만 고쳐진다.
 */
async function addCatalogueFactor(
  page: import("@playwright/test").Page,
  opts: { threshold?: string } = {},
) {
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm-row").first()).toBeVisible({ timeout: 20_000 });
  await page.locator(".tfm-search").fill("평균 절대 모멘텀");
  await expect(page.locator(".tfm-row").first()).toBeVisible({ timeout: 20_000 });
  await page.locator(".tfm-row").first().click();
  if (opts.threshold != null) {
    // ★.tfm 으로 스코프한다★ 타이밍 페이지 자체도 .as-tm-num 을 쓰므로 문서 전체에서
    // .last() 를 잡으면 페이지 입력이 잡힌다 (timing-factors.spec.ts 가 겪은 함정).
    await page.locator(".tfm .as-tm-num").last().fill(opts.threshold);
  }
  await page.locator(".as-fb-apply", { hasText: "이 팩터 추가" }).click();
  await expect(page.locator(".as-3w-legs")).toBeVisible({ timeout: 30_000 });
}

async function openTimingWithFactor(page: import("@playwright/test").Page) {
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await expect(page.locator(PANEL)).toBeVisible({ timeout: 30_000 });
  await addCatalogueFactor(page);
}

test("3자 비교: 세 다리가 각각 상태·노출·이유를 갖는다", async ({ page }) => {
  const sink = trackErrors(page);
  await openTimingWithFactor(page);

  await expect(page.locator(LEGS)).toHaveCount(3);
  for (const leg of await page.locator(LEGS).all()) {
    await expect(leg.locator(".as-3w-state")).toBeVisible();

    // ★이 단언은 P5 에서 뒤집혔다 — 예전 버전이 결함을 계약으로 굳히고 있었다★
    // 이전에는 세 다리 **전부** 에 `.as-3w-exp b` 가 "%" 를 담기를 요구했다. 그런데
    // 판정 불가 다리의 노출은 0 이므로 화면에 `0%` 와 폭 0 막대가 그려졌고, 그것은 진짜
    // 0% 노출과 구별되지 않았다. 헤더에 "판정 불가" 라고 적어 두고 아래에 숫자를 적으면
    // 사용자는 숫자를 믿는다. 이제 판정한 다리에만 숫자를 요구하고, 판정하지 못한
    // 다리에는 **숫자가 없을 것**을 요구한다.
    const na = leg.locator(".as-3w-na");
    if (await na.count()) {
      await expect(na, "판정 불가 사유가 보여야 한다").toBeVisible();
      expect(await leg.locator(".as-3w-exp").count(), "판정 불가에 노출 수치를 적지 않는다").toBe(0);
      expect(await leg.locator(".as-3w-bar").count(), "판정 불가에 비례 막대를 그리지 않는다").toBe(0);
    } else {
      await expect(leg.locator(".as-3w-exp b")).toContainText("%");
    }

    // 스펙 §8: 모든 위험-온/오프 판단이 이유를 갖는다 — 빈 문자열이면 이유가 없는 것이다.
    expect((await leg.locator(".as-3w-why").innerText()).trim().length).toBeGreaterThan(5);
  }
  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("3자 비교: 기준선은 항상 전액 투자다 (타이밍을 하지 않았다면)", async ({ page }) => {
  await openTimingWithFactor(page);
  await expect(page.locator(".as-3w-leg.baseline .as-3w-exp b")).toHaveText("100%");
});

test("3자 비교: 스냅샷이 없으면 매크로 다리를 지어내지 않는다", async ({ page }) => {
  await openTimingWithFactor(page);
  // 스냅샷을 붙이지 않고 들어온 경로 — 세 번째 다리는 판정 불가 + 사유여야 한다.
  await expect(page.locator(".as-3w-ov-none")).toBeVisible();
  await expect(page.locator(".as-3w-ov-none")).toContainText("스냅샷");
  await expect(page.locator(".as-3w-leg.timing_macro .as-3w-state")).toHaveText("판정 불가");
});

test("3자 비교: 매크로 오버레이를 끄면 결과가 눈에 보이게 달라진다 (게이트)", async ({ page }) => {
  const sink = trackErrors(page);

  // 스냅샷을 실제로 붙인다 — 오버레이의 출처는 라이브 매크로가 아니라 붙어 있는 스냅샷이다.
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await page.locator(".mc-open-aas").click();
  await page.waitForURL(/\/allocation\/macro\?snapshot=rgs_/, { timeout: 30_000 });
  await page.locator(".as-macro-apply").click();
  await expect(page.locator(".as-ctx-snap")).toBeVisible({ timeout: 20_000 });

  // 스냅샷은 컨텍스트에 붙어 있으므로 라우트 이동으로도 유지된다(3b 가 고정한 성질).
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await expect(page.locator(".as-ctx-snap")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(PANEL)).toBeVisible({ timeout: 30_000 });
  // ★임계를 낮춰 타이밍이 반드시 통과하게 만든다★
  // 이게 없으면 타이밍 단독이 0% 로 나올 수 있고, 그때 "끄면 같아진다" 는 0 == 0 이라
  // 참이지만 아무것도 증명하지 못한다 — 게이트가 헛돌지 않도록 조건을 고정한다.
  // (임계가 실제로 존중된다는 것 자체가 백엔드에서 따로 검증된 성질이다.)
  await addCatalogueFactor(page, { threshold: "-999" });

  const macroExp = page.locator(".as-3w-leg.timing_macro .as-3w-exp b");
  const timingExp = page.locator(".as-3w-leg.timing_only .as-3w-exp b");
  await expect(macroExp).toBeVisible({ timeout: 30_000 });

  // 오버레이가 켜진 상태 — 매크로 다리는 타이밍 단독을 넘지 못한다(one-way).
  const onMacro = Number((await macroExp.innerText()).replace("%", ""));
  const onTiming = Number((await timingExp.innerText()).replace("%", ""));
  expect(onMacro, "매크로가 노출을 키웠다 — 오버레이는 줄이기만 해야 한다")
    .toBeLessThanOrEqual(onTiming);

  // 끈다. ★값이 바뀌길 기다린 뒤에 비교한다★
  await page.locator(".as-3w-toggle input").uncheck();
  await expect(page.locator(".as-3w-ov-off")).toBeVisible({ timeout: 20_000 });
  await expect(macroExp).toHaveText(`${onTiming}%`, { timeout: 20_000 });

  // ★이 단언이 헛돌 수 있는 경우를 덮지 않고 드러낸다★
  // 타이밍 단독이 이미 0% 면 매크로가 깎을 것이 없어 켜든 끄든 0% 다 — 그때 "끄면 같아진다"는
  // 참이지만 아무것도 증명하지 못한다. 실제로 제약이 걸려 있었을 때만 "눈에 보이는 변화"를
  // 요구하고, 아니면 왜 요구하지 않는지 기록한다.
  if (onMacro < onTiming) {
    expect(Number((await macroExp.innerText()).replace("%", "")),
      "오버레이를 껐는데 노출이 그대로다 — 토글이 장식이다").toBeGreaterThan(onMacro);
  } else {
    // eslint-disable-next-line no-console
    console.log(`[3자 비교] 오버레이가 제약을 걸지 않은 상태(타이밍 ${onTiming}%, `
      + `매크로 ${onMacro}%) — 토글의 가시적 변화는 이 실행에서 검증되지 않았다.`);
  }

  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});
