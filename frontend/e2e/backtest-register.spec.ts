import { test, expect, type Page, type Route } from "@playwright/test";
import { completedRun, STUB_RUN_ID } from "./helpers";

/**
 * ST2 · 결과 화면의 "전략으로 등록" — 여러 전략 백테스트 화면(삭제)의 등록 판을 옮겼다.
 * 거는 것:
 *  · 화면을 여는 것만으로는 등록 목록을 묻지 않는다 · 눌러야 묻는다(짝)
 *  · 등록 본문은 옛 판과 같은 모양 `{run_id, name}` · 성공 → 이름·번호 · 캔버스 링크
 *  · 이미 등록한 실행이면 다시 등록하게 하지 않는다(짝: 아니면 이름 칸)
 *  · 409 거절 → 서버 사유 + 첫 불일치 날짜 그대로 · 목록 500 → alert + 다시 시도
 */

const STRATS = (runId: string | null) => runId
  ? [{ id: 4, name: "가치 상위 20", source_run_id: runId, is_active: true, is_mock_data: true, is_pit_verified: false, symbols: [], registered_at: 1, repro: null }]
  : [];

async function open(page: Page, o: { listed?: string | null; listStatus?: number; reply?: (r: Route, body: unknown) => Promise<void> } = {}) {
  const seen = { list: 0, posts: [] as unknown[] };
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(completedRun().full) }));
  await page.route("**/api/v1/multibacktest/strategies**", async (r) => {
    if (r.request().method() === "GET") {
      seen.list += 1;
      if (o.listStatus) return r.fulfill({ status: o.listStatus, json: { detail: "전략 목록을 읽지 못했어요" } });
      const s = STRATS(o.listed ?? null);
      return r.fulfill({ json: { count: s.length, strategies: s } });
    }
    const body = r.request().postDataJSON();
    seen.posts.push(body);
    if (o.reply) return o.reply(r, body);
    return r.fulfill({ status: 201, json: { ...STRATS("x")[0], id: 9, name: (body as { name: string }).name, source_run_id: STUB_RUN_ID } });
  });
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  return seen;
}

const act = (p: Page, a: string) => p.locator(`[data-act="${a}"]`);

test("열기 전에는 묻지 않고, 누르면 이름을 받아 옛 판과 같은 본문으로 등록한다", async ({ page }) => {
  const seen = await open(page);
  await expect(act(page, "reg-open")).toBeVisible();
  expect(seen.list, "결과 화면을 여는 것만으로 등록 목록을 묻지 않는다").toBe(0);
  await act(page, "reg-open").click();
  await expect(act(page, "reg-name")).toBeVisible();
  expect(seen.list).toBe(1);
  await act(page, "reg-name").fill("내 가치 전략");
  await act(page, "reg-go").click();
  await expect(page.locator(".rs-reg-ok")).toContainText("‘내 가치 전략’ 전략(#9)으로 등록했어요");
  await expect(page.locator('.rs-reg-ok a[href="/allocation"]')).toBeVisible();
  expect(seen.posts).toEqual([{ run_id: STUB_RUN_ID, name: "내 가치 전략" }]);
});

test("이미 등록한 실행이면 다시 등록하게 하지 않는다 (짝: 아니면 이름 칸)", async ({ page }) => {
  const seen = await open(page, { listed: STUB_RUN_ID });
  await act(page, "reg-open").click();
  await expect(page.locator(".rs-reg-ok")).toContainText("이미 ‘가치 상위 20’ 전략(#4)으로 등록돼 있어요");
  await expect(act(page, "reg-name")).toHaveCount(0);
  expect(seen.posts).toEqual([]);
});

test("거절(409)은 서버 사유와 첫 불일치 날짜를 그대로 · 칸은 남는다", async ({ page }) => {
  await open(page, { reply: (r) => r.fulfill({ status: 409, json: { detail: {
    reason: "다시 돌린 자산곡선이 저장본과 달라요", first_mismatch: { index: 3, date: "2024-01-05", stored: 1, rerun: 2 } } } }) });
  await act(page, "reg-open").click();
  await act(page, "reg-go").click();
  const alert = page.locator(".rs-reg [role=alert]");
  await expect(alert).toContainText("다시 돌린 자산곡선이 저장본과 달라요");
  await expect(alert).toContainText("2024-01-05");
  await expect(act(page, "reg-name")).toBeVisible();
});

test("목록을 못 읽으면 실패를 말하고 다시 시도한다 (빈 목록인 척하지 않는다)", async ({ page }) => {
  const seen = await open(page, { listStatus: 500 });
  await act(page, "reg-open").click();
  await expect(page.locator(".rs-reg [role=alert]")).toContainText("등록 상태를 확인하지 못했어요");
  await expect(act(page, "reg-name")).toHaveCount(0);
  await page.locator(".rs-reg-retry").click();
  await expect.poll(() => seen.list).toBe(2);
});
