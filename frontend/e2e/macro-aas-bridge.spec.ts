import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Macro → 캔버스 지속 브리지 (Phase 3b → BL4).
//
// 이 스펙의 요점은 "버튼이 이동하는가" 가 **아니다**. 증명해야 하는 것은 **새로고침을 견디는가** — 스냅샷이 서버에 ID 로
// 존재하고, 브라우저를 다시 로드해도 같은 ID 가 그대로 쓰이는가다. 그것이 재현성의 최소 조건이다.
// BL4 — 예전에는 마법사 0M 화면으로 갔다. 이제 `/allocation?snapshot=` 캔버스가 국면 노드에 그 스냅샷을 채운 흐름으로 연다.
// 정직성도 함께 고정한다: 수집기가 빈티지를 모르므로 스냅샷은 지금 시점 전용(forward_only)이고, 캔버스가 그것을 숨기면 안 된다.
// ═══════════════════════════════════════════════════════════════════════════════

const SNAP_RE = /rgs_\d+_[0-9a-f]+/;

async function openFromMacro(page: import("@playwright/test").Page) {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  const openBtn = page.locator(".mc-open-aas");
  await expect(openBtn).toBeVisible({ timeout: 30_000 });
  await openBtn.click();
  // 스냅샷 생성(서버 왕복) 후 캔버스로 이동 — 마법사 주소를 거치지 않는다.
  await page.waitForURL(/\/allocation\?snapshot=rgs_/, { timeout: 30_000 });
  const sid = new URL(page.url()).searchParams.get("snapshot") ?? "";
  expect(sid, "URL 에 스냅샷 ID 가 실려야 한다").toMatch(SNAP_RE);
  await expect(page.locator('.pg-node[data-node-id="regime"]')).toBeVisible({ timeout: 30_000 });
  return sid;
}

async function run(page: import("@playwright/test").Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  return (await resp).json();
}

test("Macro → 캔버스: 버튼이 스냅샷을 서버에 만들고 /allocation?snapshot= 으로 연다 · 국면 노드가 그 스냅샷을 쓴다", async ({ page }) => {
  const sink = trackErrors(page);
  const sid = await openFromMacro(page);
  await expect(page.locator(".pg-file-note")).toContainText(sid);
  const body = await run(page);
  expect(body.nodes.regime.status, body.nodes.regime.reason).toBe("ok");
  expect(body.nodes.regime.view.snapshot_id).toBe(sid);
  expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);
});

test("Macro → 캔버스: 새로고침을 견딘다 (이 스펙의 핵심)", async ({ page }) => {
  const sid = await openFromMacro(page);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator('.pg-node[data-node-id="regime"]')).toBeVisible({ timeout: 30_000 });
  const body = await run(page);
  expect(body.nodes.regime.view.snapshot_id, "새로고침 뒤에도 같은 스냅샷").toBe(sid);
});

test("Macro → 캔버스: 지금 시점 전용 한계를 숨기지 않는다", async ({ page }) => {
  await openFromMacro(page);
  const body = await run(page);
  // 빈티지 없는 스냅샷은 과거 검증에 쓸 수 없다 — 계보가 그렇게 말하고, 노드 카드가 칩으로 말한다.
  expect(body.nodes.regime.lineage.pit).toBe("forward_only");
  await expect(page.locator('.pg-node[data-node-id="regime"]')).toContainText("지금 시점 전용");
});

test("Macro → 캔버스: 스냅샷 저장이 실패하면 이동하지 않고 사유를 보인다(성공으로 위장하지 않는다)", async ({ page }) => {
  await page.route("**/regime-snapshots/from-current**", (r) => r.fulfill({
    json: { recorded: false, snapshot_id: null, message: "E2E: 스냅샷 저장소를 쓸 수 없습니다." } }));
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await page.locator(".mc-open-aas").click();
  await expect(page.getByText("E2E: 스냅샷 저장소를 쓸 수 없습니다.")).toBeVisible({ timeout: 20_000 });
  await expect(page).toHaveURL(/\/macro$/);
});

test("캔버스: 존재하지 않는 스냅샷 ID 는 국면 노드가 정직하게 못 찾았다고 말한다", async ({ page }) => {
  await page.goto("/allocation?snapshot=rgs_0_deadbeef", { waitUntil: "domcontentloaded" });
  await expect(page.locator('.pg-node[data-node-id="regime"]')).toBeVisible({ timeout: 30_000 });
  const body = await run(page);
  expect(body.nodes.regime.status).toBe("failed");
  expect(body.nodes.regime.reason).toContain("rgs_0_deadbeef");
});
