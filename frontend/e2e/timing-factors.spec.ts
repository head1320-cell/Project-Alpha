import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// AAS TIMING 통합 팩터 창 — 기존 카나리(cramped inline rows)를 팩터 칩 + 단일 모달로 통합.
// 회귀 방지: 창이 열리고 5개 패밀리가 모두 노출되며, 신규 팩터를 검색→설정→추가하면 칩이 늘어난다.
test("AAS Timing: unified factor window lists all families and adds a new factor", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });

  // 기존의 비좁은 인라인 카나리 편집 행은 더 이상 없어야 한다(팩터 칩으로 대체)
  expect(await page.locator(".as-tm-canary").count(), "legacy cramped canary rows removed").toBe(0);
  const before = await page.locator(".tfc-chip").count();
  expect(before, "existing canaries render as factor chips").toBeGreaterThan(0);

  // 통합 팩터 창 열기
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm")).toBeVisible();
  const fams = await page.locator(".tfm-fams button").allInnerTexts();
  // Phase 8 에서 breadth·volatility·drawdown·correlation 4개가 늘어 9개가 됐다.
  // ★이 숫자는 백엔드 SIGNAL_FAMILIES 와 같이 움직인다★ 패밀리를 더하면 여기도 고칠 것.
  expect(fams.length, "9 signal families in one window").toBe(9);

  // 검색 → 신규 팩터(이격도) 선택 → 파라미터 노출 → 추가
  await page.locator(".tfm-search").fill("이격");
  await expect(page.locator(".tfm-row").first()).toBeVisible();
  await page.locator(".tfm-row").first().click();
  await expect(page.locator(".tfm-sel-t")).toContainText("이격도");
  await page.locator(".as-fb-apply", { hasText: "이 팩터 추가" }).click();

  await expect(page.locator(".tfm")).toHaveCount(0);           // 모달 닫힘
  await expect(page.locator(".tfc-chip")).toHaveCount(before + 1);
  await expect(page.locator(".tfc-chip-t").last()).toContainText("이격도");

  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/�/);
  expect(uniq(sink.pageErrors), "timing factor window page errors").toEqual([]);
  expect(uniq(sink.api404), "timing factor window API 404s").toEqual([]);
});

// 정직성 회귀: 유료 컨텐츠 조건식을 재현했다고 주장하지 않는다는 노트가 창에 항상 보여야 한다.
test("AAS Timing: factor window shows the provenance/honesty note", async ({ page }) => {
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm-note")).toContainText("유료");
  await expect(page.locator(".tfm-note")).toContainText("재현한 것이 아닙니다");
});

// ── Phase 6b — 셸 이전으로 생긴 계약 + 스펙 §8.1 요구 13(주기 충돌 경고) ─────────
async function openTimingWindow(page: import("@playwright/test").Page) {
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });
  await page.locator(".as-fb-apply", { hasText: "팩터 창에서 추가" }).first().click();
  await expect(page.locator(".tfm")).toBeVisible();
}

// 셸이 제공하는 Escape 닫기 — 이전에는 backdrop 클릭만 됐다.
test("AAS Timing: shell contract — Escape closes, dialog is modal", async ({ page }) => {
  await openTimingWindow(page);
  await expect(page.locator(".tfm")).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape");
  await expect(page.locator(".tfm")).toHaveCount(0);
});

test("AAS Timing: frequency conflict is warned, and alignment is confirmed", async ({ page }) => {
  const sink = trackErrors(page);
  await openTimingWindow(page);

  // 일간 팩터(N일 이동평균) + 기본 리밸런싱(월말) → 신호가 버려진다는 경고
  await page.locator(".tfm-search").fill("N일 이동평균");
  await page.locator(".tfm-row").first().click();
  await expect(page.locator(".tfm-freq-sel")).toHaveValue("month_end");
  await expect(page.locator(".tfm-freq-warn")).toBeVisible();
  await expect(page.locator(".tfm-freq-warn")).toContainText("버려집니다");

  // 리밸런싱을 일간으로 맞추면 경고가 사라지고 정렬 확인이 뜬다
  await page.locator(".tfm-freq-sel").selectOption("day");
  await expect(page.locator(".tfm-freq-warn")).toHaveCount(0);
  await expect(page.locator(".tfm-freq-ok")).toBeVisible();

  // 반대 방향 — 월간 팩터를 일간 리밸런싱에 쓰면 같은 값이 반복된다
  await page.locator(".tfm-search").fill("평균 절대 모멘텀");
  await page.locator(".tfm-row").first().click();
  await page.locator(".tfm-freq-sel").selectOption("day");
  await expect(page.locator(".tfm-freq-warn")).toContainText("반복 적용");

  expect(uniq(sink.pageErrors), "frequency warning page errors").toEqual([]);
  expect(uniq(sink.api404), "frequency warning API 404s").toEqual([]);
});

// 정직성: as_of 팩터는 목록에 보이되 **추가할 수 없다**. 숨기면 왜 없는지 알 수 없고,
// 추가를 허용하면 값이 영원히 없는(=늘 위험-오프) 규칙이 조용히 만들어진다.
test("AAS Timing: an as-of factor is visible, explained, and not addable", async ({ page }) => {
  await openTimingWindow(page);
  await page.locator(".tfm-search").fill("장단기 금리차");

  const row = page.locator(".tfm-row").first();
  await expect(row).toBeVisible();
  await expect(row.locator(".tfm-off")).toHaveText("미가용");
  await expect(row).toContainText("추가할 수 없습니다");

  await row.click();
  await expect(page.locator(".as-fb-apply", { hasText: "이 팩터 추가" })).toBeDisabled();

  // 값을 못 만드는 팩터에는 미리보기를 아예 요청하지 않는다(빈 차트를 그리지 않는다)
  await expect(page.locator(".tfm-hist")).toHaveCount(0);
});

// ── Phase 6b-2 — 과거 미리보기 (§8.1 요구 4) ────────────────────────────────
test("AAS Timing: historical preview shows value, threshold, state and flips", async ({ page }) => {
  const sink = trackErrors(page);
  await openTimingWindow(page);

  await page.locator(".tfm-search").fill("평균 절대 모멘텀");
  await page.locator(".tfm-row").first().click();

  const hist = page.locator(".tfm-hist");
  await expect(hist).toBeVisible();
  // 스펙이 요구한 네 가지가 모두 보인다
  await expect(hist.locator(".tfm-hist-stats")).toContainText("현재");
  await expect(hist.locator(".tfm-hist-stats")).toContainText("임계");
  await expect(hist.locator(".tfm-hist-st")).toBeVisible();
  await expect(hist.locator(".tfm-hist-stats")).toContainText("전환");

  // 월 표본이라는 사실을 숨기지 않는다
  await expect(hist.locator(".tfm-hist-lim")).toContainText("월");
  await expect(hist.locator(".tfm-hist-bar").first()).toBeVisible();

  expect(uniq(sink.pageErrors), "preview page errors").toEqual([]);
  expect(uniq(sink.api404), "preview API 404s").toEqual([]);
});

test("AAS Timing: preview is re-scored when the threshold changes", async ({ page }) => {
  await openTimingWindow(page);
  await page.locator(".tfm-search").fill("평균 절대 모멘텀");
  await page.locator(".tfm-row").first().click();
  await expect(page.locator(".tfm-hist-stats")).toContainText("임계");

  // 비율(0~1) 팩터에 임계 1.5 → 통과 불가 → 현재 상태가 위험-온일 수 없다
  // ★.tfm 으로 스코프한다★ — 타이밍 페이지 자체도 .as-tm-num 을 쓰고(page.tsx:101·175),
  // 그중 하나는 모달보다 뒤에 렌더되므로 문서 전체에서 .last() 를 잡으면 페이지 입력이 잡힌다.
  const thr = page.locator(".tfm .as-tm-num").last();
  await thr.fill("1.5");
  await expect(page.locator(".tfm-hist-st")).not.toHaveClass(/s-risk_on/);
});

// 일간 팩터는 월 표본이라 전환 횟수가 과소집계된다 — 그 한계를 화면에 적는다.
test("AAS Timing: a daily factor discloses that its flip count is undersampled", async ({ page }) => {
  await openTimingWindow(page);
  await page.locator(".tfm-search").fill("N일 이동평균");
  await page.locator(".tfm-row").first().click();
  await expect(page.locator(".tfm-hist-lim")).toContainText("과소");
});

// ── Phase 12b — 데이터 계보 (§3.4 · §8.1 "lineage") ──────────────────────────
// 11a 감사가 A3 로 잡은 자리다: §8.1 표는 Phase 6 배달로 적고 있었으나 코드에 0건이었다.
test("AAS Timing: 미리보기 옆에 데이터 계보가 함께 온다", async ({ page }) => {
  await openTimingWindow(page);
  await page.locator(".tfm-search").fill("이격도");
  await page.locator(".tfm-row").first().click();

  const lin = page.locator(".tfm-lin");
  await expect(lin, "값만 보여주고 출처를 말하지 않습니다").toBeVisible({ timeout: 20_000 });
  await expect(lin).toContainText("데이터 계보");
  await expect(lin).toContainText("출처");
  // ★시점 기준이 핵심이다★ 이게 없으면 그 숫자가 언제 기준인지 알 방법이 없다.
  await expect(lin).toContainText("시점 기준");
});

test("AAS Timing: mock 표기는 '사용' 이 아니라 '허용' 이라고 말한다", async ({ page }) => {
  // ★이 문구가 정직성 축이다★ 실제로 어느 계층(DB/KIS/mock)이 답했는지는 읽기마다
  // 다르고 추적 계측이 필요하다. 쓰였다고 단정하면 모르는 것을 아는 척하는 것이다.
  await openTimingWindow(page);
  await page.locator(".tfm-search").fill("이격도");
  await page.locator(".tfm-row").first().click();

  const lin = page.locator(".tfm-lin");
  await expect(lin).toBeVisible({ timeout: 20_000 });
  await expect(lin).toContainText("mock 폴백");
  const txt = await lin.innerText();
  expect(txt, "mock 을 '사용했다' 고 단정하고 있습니다")
    .not.toMatch(/mock\s*(을|를)?\s*사용(했|함)/);
});

// ── Phase 12a — §6.1 "소스 없음" 묶음은 보이되 켤 수 없다 ────────────────────
test("AAS Timing: 소스가 없는 팩터도 목록에 보이고, 사유와 함께 막힌다", async ({ page }) => {
  // ★목록에서 빼면 사용자는 검토한 적조차 없게 된다★ "안 하기로 했다" 와 다른 상태다.
  await openTimingWindow(page);
  await page.locator(".tfm-search").fill("대차잔고");

  const row = page.locator(".tfm-row").first();
  await expect(row, "§6.1 의 소스 없음 팩터가 목록에 없습니다").toBeVisible({ timeout: 20_000 });
  await expect(row.locator(".tfm-off")).toHaveText("미가용");
  // 사유는 툴팁이 아니라 행에 — 셸이 세 창에 준 것과 같은 규칙
  await expect(row.locator(".tfm-row-p")).toContainText("피드");

  await row.click();
  await expect(page.locator(".as-fb-apply", { hasText: "이 팩터 추가" })).toBeDisabled();
});
