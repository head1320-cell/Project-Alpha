import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// ═══════════════════════════════════════════════════════════════════════════════
// CF 3부 P · 제약 — 보고가 ★무엇이 적용됐고 무엇이 안 됐는지★ 말한다
// ─────────────────────────────────────────────────────────────────────────────
//  P1 · 옵티마이저 결과에 "제약이 어떻게 적용됐나" — 업종 상한이 빠졌으면 '적용 안 됨'(짝: 종목 상한만이면 없음)
//       · 설명(이야기 탭)도 '제약 지킴' 을 확인으로 말하지 않는다 · 기대 수익 추정은 수익률 입력을 쓰지 않는다고 말한다
//  개발 DB 에는 업종 표(`instrument_master`)가 없어 업종 상한이 ★실제로 전부 빠진다★ — 그것이 이 테스트가 보는 상황이다.
// ═══════════════════════════════════════════════════════════════════════════════

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function exportDoc(page: Page) {
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  return JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
}

/** 기본 사슬을 내보내 옵티마이저 제약만 바꿔 다시 싣는다 — 위치·다른 칸은 앱이 만든 그대로. */
async function withConstraints(page: Page, constraints: Record<string, unknown>) {
  const doc = await exportDoc(page);
  const opt = doc.nodes.find((n: { id: string }) => n.id === "optimizer");
  opt.params = { ...opt.params, constraints };
  await page.locator(".pg-import-input").setInputFiles({
    name: "c.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
  await expect(node(page, "optimizer")).toBeVisible();
}

async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
}

test("P1 · 업종 상한이 빠지면 결과가 '적용 안 됨' 이라고 말한다 — 설명도 확인이라 하지 않는다", async ({ page }) => {
  await openCanvas(page);
  await withConstraints(page, { group_caps_pct: { "반도체": 30 }, max_weight_pct: 40 });
  await run(page);
  await node(page, "optimizer").click();
  await tab(page, "detail");
  const rep = page.locator(".pg-side .pg-cons");
  await expect(rep).toBeVisible();
  await expect(rep.locator(".pg-cons-unapplied")).toHaveCount(1);
  await expect(rep.locator(".pg-cons-unapplied")).toContainText("반도체");
  await expect(rep.locator(".pg-cons-head .pg-tag"), "빠진 것이 있으면 '제약 지킴' 이 아니다").not.toHaveText("제약 지킴");

  await tab(page, "story");
  const step = page.locator('.pg-step[data-node-id="optimizer"]');
  await expect(step.locator(".pg-trust")).toContainText("반도체");
  await expect(step.locator(".pg-trust"), "적용된 것만 지켰다고 말한다").toContainText("적용된 제약 안에서");
});

test("P1 · 짝 — 종목 상한만이면 빠진 것이 없다", async ({ page }) => {
  await openCanvas(page);
  await withConstraints(page, { max_weight_pct: 40 });
  await run(page);
  await node(page, "optimizer").click();
  await tab(page, "detail");
  const rep = page.locator(".pg-side .pg-cons");
  await expect(rep).toBeVisible();
  await expect(rep.locator(".pg-cons-unapplied")).toHaveCount(0);
  await expect(rep).toHaveAttribute("data-cons-status", /ok|approx/);
});

test("P1 · 기대 수익 추정은 이어진 수익률을 쓰지 않는다고 말한다", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await tab(page, "story");
  await expect(page.locator('.pg-step[data-node-id="estimate"]')).toContainText("이어진 수익률은 이 단계에서 쓰지 않아요");
  await expect(page.locator('.pg-step[data-node-id="optimizer"]'), "짝: 옵티마이저 설명에는 없다")
    .not.toContainText("이어진 수익률은");
});

