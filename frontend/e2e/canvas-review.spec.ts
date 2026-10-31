import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// ═══════════════════════════════════════════════════════════════════════════════
// CF 3부 PB2 · 정기 점검 흐름 — 고객 → 계좌 점검 → 목표까지 · 지금 비중 → 보유 진단 · 목표 비중 → 리밸런싱 판단 →
// 주문 목록 미리보기(★주문 없음★) → 실행 목표 · 결정 기록
// ─────────────────────────────────────────────────────────────────────────────
//  · 빠른 시작에서 놓으면 서버 검증 오류 0 · 카드가 겹치지 않는다
//  · ★고객 정보는 비워 둔다★ — 계좌 유형이 없어 계좌 점검이 사유와 함께 멈추고, 목표까지는 그 때문에 막힌다(나머지는 돈다)
//  · ★지금 비중은 유니버스 한 곳★ — 리밸런싱 판단이 유니버스 쪽을 읽고, 주문 목록은 제 칸이 유니버스와 같다고 말한다
//  · 계좌 유형을 고르면 계좌 점검·목표까지가 돈다 — 목표는 연도·곡선이 없어 목표 비중을 내지 않는다고 말한다
// ═══════════════════════════════════════════════════════════════════════════════

type RunBody = { nodes: Record<string, { status: string; reason: string | null; view: Record<string, unknown> | null;
                                           explain: { trust?: { state: string; text: string }[] } | null }> };

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();

async function openReview(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.locator('.pg-template[data-template="review"]').click();
  await expect(node(page, "client")).toBeVisible();
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function run(page: Page): Promise<RunBody> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await resp).json();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}

async function exportDoc(page: Page) {
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  return JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
}

const OTHERS = ["client", "universe", "now", "returns", "estimate", "hold", "optimizer", "decide", "orders", "target", "journal"];

test("PB2 · 정기 점검 — 빠른 시작에서 놓으면 13노드 · 서버 검증 오류 0 · 카드가 겹치지 않는다", async ({ page }) => {
  await openReview(page);
  await expect(page.locator(".pg-node")).toHaveCount(13);
  const doc = await exportDoc(page);
  const v = await (await page.request.post("http://localhost:8000/api/v1/allocation/graph/validate", { data: doc })).json();
  expect(v.errors).toEqual([]);
  // 고객 정보는 비워 둔다 — 템플릿이 성향·계좌 유형·목표를 정하지 않는다
  const params = (id: string) => doc.nodes.find((x: { id: string }) => x.id === id).params;
  expect(params("client")).toEqual({});
  expect(params("account")).not.toHaveProperty("account_type");
  expect(params("goal")).toEqual({});
  // 지금 비중은 유니버스 한 곳 — 리밸런싱 판단은 비워 유니버스 쪽을 읽고, 주문 목록만 같은 값을 갖는다
  expect(params("decide")).not.toHaveProperty("holdings");
  expect(params("orders").current_weights).toEqual(params("universe").weights);
  const boxes = await page.locator(".react-flow__node").evaluateAll((els) => els.map((el) => {
    const r = el.getBoundingClientRect(); return { id: el.getAttribute("data-id"), l: r.left, t: r.top, r: r.right, b: r.bottom };
  }));
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    expect(a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b, `${a.id} ↔ ${b.id} 겹침`).toBe(false);
  }
});

test("PB2 · 계산 — 계좌 유형이 없어 계좌 점검은 사유와 함께 멈추고 목표까지는 막힌다 · 나머지는 돈다 · 주문 목록은 유니버스와 같은 보유에서", async ({ page }) => {
  await openReview(page);
  const body = await run(page);
  expect(body.nodes.account.status).toBe("failed");
  expect(body.nodes.account.reason).toContain("계좌 유형을 골라 주세요");
  expect(body.nodes.goal.status).toBe("blocked");
  for (const id of OTHERS) expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
  // 리밸런싱 판단의 '지금 비중' 출처는 유니버스 노드다(직접 적은 값이 아니다)
  const inputs = ((body.nodes.decide.view!.result as Record<string, unknown>).inputs as { key: string; source: string }[]);
  expect(inputs.find((x) => x.key === "holdings")!.source).toContain("유니버스");
  // 주문 목록은 두 '지금 비중' 이 같다고 말한다
  const trust = (body.nodes.orders.explain?.trust ?? []).map((t) => t.text);
  expect(trust.some((t) => t.includes("유니버스 노드의 ‘지금 비중’과 같아요"))).toBe(true);
  await expect(node(page, "account").locator(".pg-node-status-why")).toContainText("계좌 유형");
  await tab(page, "story");
  await expect(page.locator('.pg-step[data-node-id="orders"]')).toContainText("유니버스 노드의 ‘지금 비중’과 같아요");
});

test("PB2 · 계좌 유형을 고르면 계좌 점검·목표까지가 돈다 — 목표는 연도·곡선이 없어 목표 비중을 내지 않는다고 말한다", async ({ page }) => {
  await openReview(page);
  await node(page, "account").click();
  await tab(page, "settings");
  await page.locator('.pg-basic-field[data-field="account_type"] .pg-choice[data-choice="irp"]').click();
  const body = await run(page);
  expect(body.nodes.account.status, body.nodes.account.reason ?? "").toBe("ok");
  expect(body.nodes.goal.status, body.nodes.goal.reason ?? "").toBe("ok");
  await node(page, "goal").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-goal-target")).toContainText("내지 않음");
  // 사유는 표 밑 한 줄로 — 표의 이름 칸이 긴 사유에 눌려 한 글자씩 세로로 서지 않는다 · 서버 필드 이름은 사람 말로
  await expect(page.locator(".pg-side .pg-goal-why")).toContainText("목표 연도");
  const label = page.locator(".pg-side .pg-kv dt", { hasText: "남은 기간" });
  expect((await label.boundingBox())!.height, "이름 칸이 한 줄").toBeLessThanOrEqual(24);
  const side = (await page.locator(".pg-side").innerText());
  for (const raw of ["horizon_days", "target_retirement_year", "risky/safe", "**"]) expect(side, raw).not.toContain(raw);
});

test("PB2 · 명령 팔레트에서도 '정기 점검 불러오기' 로 놓는다", async ({ page }) => {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.pg-template[data-template="review"]')).toContainText("정기 점검");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("정기 점검");
  await page.locator('.pg-cmd-item[data-cmd="tpl:review"]').click();
  await expect(node(page, "client")).toBeVisible();
  await expect(page.locator(".pg-node")).toHaveCount(13);
});
