import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// Walk-forward policy backtest (roadmap 07) — drives the real backend: pick a goal (seeds a
// portfolio) → Journal → run the policy backtest → OOS equity + KPIs + honesty badges render.
//
// ★E — 이 스펙이 거짓 주장을 지키고 있었다★
// ─────────────────────────────────────────────────────────────────────────────
// 여기 `await expect(page.getByText("OOS · look-ahead 없음")).toBeVisible();` 가
// 있었다. 그런데 그 배지는 **응답에 근거가 하나도 없는 하드코딩 상수**였다 — 화면이
// 단정했고, 이 스펙이 그 단정을 계약으로 못 박고 있었다. 테스트가 틀린 것을 지키면
// 고치는 쪽이 red 가 된다.
//
// 이제 화면은 응답의 `lookahead_evidence` 롤업을 그린다. 재지 않는 축이 둘(생존편향·
// 가격 정의) 있어 판정은 `verified` 가 될 수 없고, 배지는 `data-lookahead` 로 그
// 상태를 말한다. ★새 속성도 계약이다★(ADR 001) — 바꾸려면 이 파일도 함께 고친다.
test("Allocation: policy walk-forward backtest renders OOS equity + metrics + honesty badges", async ({ page }) => {
  const sink = trackErrors(page);

  // goal gate seeds holdings
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await expect(page.locator(".aas-goal").first()).toBeVisible();
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });

  // Journal hosts the Policy Backtest
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });
  const runBtn = page.locator(".as-fb-apply", { hasText: "정책 백테스트" }).first();
  await expect(runBtn).toBeVisible();
  await runBtn.click();

  // OOS results: KPI cards + equity/benchmark chart + honesty badges
  await expect(page.locator(".as-bt-kpi").first()).toBeVisible({ timeout: 30_000 });
  expect(await page.locator(".as-bt-kpi").count(), "OOS metric KPIs").toBeGreaterThan(6);
  await expect(page.locator(".as-bt-card", { hasText: "OOS 자산곡선" })).toBeVisible();
  // ★배지가 응답을 읽는다★ — 상수 문구가 아니라 롤업 상태를 단정한다.
  const la = page.locator(".as-bt-badge[data-lookahead]");
  await expect(la).toBeVisible();
  // ★`verified` 는 나올 수 없다★ — 이 경로는 생존편향·가격 정의를 재지 않는다.
  //   그것이 결함이 아니라 **사실**이고, 화면이 그 사실을 그리는지가 이 계약이다.
  await expect(la).not.toHaveAttribute("data-lookahead", "verified");
  // 사유는 툴팁에 실린다 — 상태만 보이고 왜인지 없으면 라벨이 아니라 장식이다.
  await expect(la).toHaveAttribute("title", /./);
  // ★성과의 종류도 함께 말한다★ (Z) — 이 위젯은 타입에 `perf_label` 이 없어서
  //   응답이 싣는데도 그리지 못하고 있었다.
  await expect(page.locator(".as-bt-badges .perf-label")).toBeVisible();
  // per-rebalance weight table
  await expect(page.locator(".as-bt-wtbl tbody tr").first()).toBeVisible();

  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/�/); // Korean encoding intact
  expect(uniq(sink.pageErrors), "policy backtest page errors").toEqual([]);
  expect(uniq(sink.api404), "policy backtest API 404s").toEqual([]);
});
