import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Macro → AAS 지속 브리지 (Phase 3b).
//
// 이 스펙의 요점은 "버튼이 이동하는가" 가 **아니다**. 그건 예전 휘발성 동작으로도 통과한다.
// 증명해야 하는 것은 **새로고침을 견디는가** — 스냅샷이 서버에 ID 로 존재하고, 브라우저를
// 다시 로드해도 같은 ID 가 그대로 붙어 있는가다. 그것이 재현성의 최소 조건이다.
//
// 정직성도 함께 고정한다: 지금 수집기는 빈티지를 모르므로 스냅샷은 forward_only 여야 하고,
// UI 가 그것을 숨기면 안 된다.
// ═══════════════════════════════════════════════════════════════════════════════

const SNAP_RE = /rgs_\d+_[0-9a-f]+/;

test("Macro → AAS: 스냅샷이 서버에 생기고 URL 로 넘어온다", async ({ page }) => {
  const sink = trackErrors(page);

  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  const openBtn = page.locator(".mc-open-aas");
  await expect(openBtn).toBeVisible({ timeout: 30_000 });

  await openBtn.click();
  // 스냅샷 생성(서버 왕복) 후 0M 스테이지로 이동
  await page.waitForURL(/\/allocation\/macro\?snapshot=rgs_/, { timeout: 30_000 });

  const url = new URL(page.url());
  const sid = url.searchParams.get("snapshot") ?? "";
  expect(sid, "URL 에 스냅샷 ID 가 실려야 한다").toMatch(SNAP_RE);

  // 미리보기가 실제 스냅샷 내용을 렌더한다
  await expect(page.locator(".as-macro-map")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-macro-repro")).toContainText(sid);

  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("Macro → AAS: 적용 전에는 미리보기 — 적용해야 컨텍스트에 붙는다", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await page.locator(".mc-open-aas").click();
  await page.waitForURL(/\/allocation\/macro\?snapshot=/, { timeout: 30_000 });

  // 도착 시점은 **미리보기** — 아직 붙지 않았다
  const apply = page.locator(".as-macro-apply");
  await expect(apply).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-ctx-snap")).toHaveCount(0);

  await apply.click();

  // 적용 후에야 컨텍스트 스트립에 나타난다
  await expect(page.locator(".as-ctx-snap")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".as-macro-attached")).toBeVisible();
});

test("Macro → AAS: 새로고침을 견딘다 (이 스펙의 핵심)", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await page.locator(".mc-open-aas").click();
  await page.waitForURL(/\/allocation\/macro\?snapshot=/, { timeout: 30_000 });
  const sid = new URL(page.url()).searchParams.get("snapshot")!;

  await page.locator(".as-macro-apply").click();
  await expect(page.locator(".as-ctx-snap")).toBeVisible({ timeout: 10_000 });

  // ── 쿼리 파라미터 **없이** 다른 스테이지로 이동한 뒤 새로고침 ──
  // URL 에 기대지 않고도 같은 스냅샷이 살아 있어야 한다.
  await page.goto("/allocation/construct", { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });

  const strip = page.locator(".as-ctx-snap");
  await expect(strip, "새로고침 후에도 스냅샷이 붙어 있어야 한다").toBeVisible({ timeout: 20_000 });
  // 같은 ID 인지 — 짧게 표시되므로 접두사를 뗀 조각으로 대조
  await expect(strip).toContainText(sid.replace(/^rgs_/, "").slice(0, 12));

  // 0M 으로 돌아가면 미리보기가 아니라 "연결됨" 상태여야 한다
  await page.goto("/allocation/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-macro-attached")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-macro-apply")).toHaveCount(0);
  await expect(page.locator(".as-macro-repro")).toContainText(sid);
});

test("Macro → AAS: forward_only 한계를 숨기지 않는다", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await page.locator(".mc-open-aas").click();
  await page.waitForURL(/\/allocation\/macro\?snapshot=/, { timeout: 30_000 });

  // 수집기가 빈티지를 모르므로 backtest_eligible 이면 안 된다
  const badge = page.locator(".as-macro-badge.as-usage-forward_only");
  await expect(badge, "빈티지 없는 스냅샷은 forward_only 로 표시되어야 한다").toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-usage-backtest_eligible")).toHaveCount(0);

  // 사유가 화면에 있어야 한다 — 툴팁에만 숨기지 않는다
  await expect(page.locator(".as-macro-warn")).toContainText("빈티지");
});

test("AAS: snapshot 파라미터 없이 들어와도 게이트/스테이지가 깨지지 않는다", async ({ page }) => {
  const sink = trackErrors(page);

  // 게이트는 layout 의 isGate 분기로 **크롬 없이** bare 렌더된다 — 위저드(.aas-wiz)가
  // 없는 것이 정상이고, 목표 선택 화면(.aas-gate)이 나와야 한다.
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".aas-gate")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".aas-goal").first()).toBeVisible();

  await page.goto("/allocation/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-macro-snap")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-empty").first()).toBeVisible();

  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("AAS: 존재하지 않는 스냅샷 ID 는 정직하게 못 찾았다고 말한다", async ({ page }) => {
  await page.goto("/allocation/macro?snapshot=rgs_0_deadbeef", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-macro-missing")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-macro-missing")).toContainText("rgs_0_deadbeef");
  // 없는 스냅샷을 붙일 수는 없어야 한다
  await expect(page.locator(".as-macro-apply")).toHaveCount(0);
});
