import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BU7c — 파생상품 계산기 `/derivatives` (계획 "BU7 상세", 사용자 결정: ★있는 계산기를 탭으로 연결★)
// ─────────────────────────────────────────────────────────────────────────────
// ★먼저 써서 옛 화면(옵션만 계산 · 몬테카를로 가짜 카드 · 빈 칸 = 0 · 실패해도 옛 결과)에서 빨강을 기록한다★ 지키는 것:
//   · 결과 = 서버 값(응답을 고치면 따라간다) · 숫자마다 한 줄 풀이
//   · ★빈 칸은 0 이 아니다★ — 요청 0 + "값을 넣어 주세요"
//   · 실패 = alert + 다시 시도, ★옛 결과는 지운다★ · 입력을 바꾸면 결과에 낡았다고 쓴다
//   · 서버가 계산하지 않는 모형은 "설명만" — 결과처럼 보이는 상수 카드("10,000 / ON / ON") 0
//   · 만기 손익 그림의 손익분기 = 행사가 ± 서버 이론가 · CVA 노출 곡선 점 = 서버 `ee_values` 수
// ═══════════════════════════════════════════════════════════════════════════════

const fail500 = { status: 500, contentType: "application/json", body: '{"detail":"boom"}' };

async function open(page: Page, q = "") {
  await page.goto(`/derivatives${q}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dv")).toBeVisible({ timeout: 40_000 });
}
/** 계산기 응답 고치기 — 실제 응답을 받아 fn 이 바꾼다. 요청 본문도 모은다. */
async function patch(page: Page, path: string, fn: (b: Record<string, unknown>) => void = () => {}) {
  const bodies: Record<string, unknown>[] = [];
  await page.route(`**${path}`, async (route) => {
    bodies.push(route.request().postDataJSON());
    const res = await route.fetch(); const body = await res.json();
    fn(body);
    await route.fulfill({ response: res, json: body });
  });
  return bodies;
}
const tab = (page: Page, name: string) => page.getByRole("tab", { name });

test("탭 다섯 + 주소 동기 — 누르면 `?tab=` 이 바뀌고, 새로고침해도 그 탭 · 옛 주소(xva·mc)도 받는다", async ({ page }) => {
  await open(page);
  await expect(page.getByRole("tab")).toHaveText(["옵션", "채권", "선물 헤지", "신용 위험(CVA)", "아직 계산하지 않는 모형"]);
  await expect(tab(page, "옵션")).toHaveAttribute("aria-selected", "true");
  await tab(page, "채권").click();
  await expect(page).toHaveURL(/\/derivatives\?tab=bond$/);
  await page.reload();
  await expect(tab(page, "채권")).toHaveAttribute("aria-selected", "true", { timeout: 20_000 });
  await open(page, "?tab=xva");
  await expect(tab(page, "신용 위험(CVA)")).toHaveAttribute("aria-selected", "true");
  await open(page, "?tab=mc");
  await expect(tab(page, "아직 계산하지 않는 모형")).toHaveAttribute("aria-selected", "true");
});

test("옵션 결과 = 서버 값(고치면 따라간다) · σ·r 은 %로 넣고 서버엔 소수로 · 그릭스 풀이는 서버 숫자", async ({ page }) => {
  const bodies = await patch(page, "/analyze-option", (b) => { b.Price = 12.3456; b.Delta = 0.5; });
  await open(page);
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  await expect(page.locator(".dv-ans")).toContainText("12.3456원", { timeout: 20_000 });
  await expect(page.getByTestId("option-greeks")).toContainText("기초자산이 1원 오르면 옵션 가격이 약 +0.5000원 움직여요.");
  expect(bodies).toEqual([{ S: 100, K: 100, sigma: 0.25, r: 0.035, T: 0.25, option_type: "call" }]);
});

test("★빈 칸은 0 이 아니다★ — 요청 0 + '값을 넣어 주세요' · 짝: 채우면 요청 1", async ({ page }) => {
  let calls = 0;
  page.on("request", (q) => { if (q.url().includes("/analyze-option")) calls += 1; });
  await open(page);
  await page.getByLabel("기초자산 가격").fill("");
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  await expect(page.locator(".dv-field-miss")).toHaveText(["값을 넣어 주세요"]);
  await page.waitForTimeout(500);
  expect(calls).toBe(0);
  await expect(page.getByTestId("option-greeks")).toHaveCount(0);
  await page.getByLabel("기초자산 가격").fill("100");
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  await expect(page.getByTestId("option-greeks")).toBeVisible({ timeout: 20_000 });
  expect(calls).toBe(1);
});

test("★실패 500 → alert + 다시 시도, 옛 결과는 남지 않는다★ · 풀면 회복", async ({ page }) => {
  await open(page);
  const go = page.getByRole("button", { name: "가격 계산하기" });
  await go.click();
  await expect(page.getByTestId("option-greeks")).toBeVisible({ timeout: 20_000 });
  await page.route("**/analyze-option", (r) => r.fulfill(fail500));
  await go.click();
  await expect(page.locator(".dv").getByRole("alert")).toContainText("옵션 가격을 계산하지 못했어요");
  await expect(page.getByTestId("option-greeks")).toHaveCount(0);
  await page.unroute("**/analyze-option");
  await page.locator(".dv").getByRole("button", { name: "다시 시도" }).click();
  await expect(page.getByTestId("option-greeks")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".dv [role=alert]")).toHaveCount(0);
});

test("입력을 바꾸면 결과에 '입력이 바뀌었어요' · 짝: 바꾸기 전엔 없음 · 다시 계산하면 사라진다", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  await expect(page.getByTestId("option-greeks")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".dv-stale")).toHaveCount(0);
  await page.getByLabel("행사가").fill("110");
  await expect(page.locator(".dv-stale")).toContainText("입력이 바뀌었어요");
  await page.locator(".dv-stale").getByRole("button", { name: "다시 계산하기" }).click();
  await expect(page.locator(".dv-stale")).toHaveCount(0, { timeout: 20_000 });
});

test("만기 손익 그림 — 손익분기 = 행사가 + 이론가(콜) · 행사가 − 이론가(풋)", async ({ page }) => {
  await patch(page, "/analyze-option", (b) => { b.Price = 7.5; });
  await open(page);
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  const pay = page.getByTestId("payoff");
  await expect(pay).toHaveAttribute("data-breakeven", "107.5000", { timeout: 20_000 });
  await expect(pay.locator(".dv-be")).toHaveText("107.5000원");
  await expect(pay.locator(".recharts-surface")).toHaveCount(1);
  await page.getByRole("radio", { name: "풋(팔 권리)" }).click();
  await page.getByRole("button", { name: "가격 계산하기" }).click();
  await expect(pay).toHaveAttribute("data-breakeven", "92.5000", { timeout: 20_000 });
});

test("채권 · 선물 헤지 결과 = 서버 값 — 헤지 방향은 한국어('Short' 없음) · β=0 이면 감소율 대신 서버 사유(0% 아님)", async ({ page }) => {
  await patch(page, "/analyze-bond", (b) => { b.Price = 9999.5; b.DV01 = 1.2345; });
  await open(page, "?tab=bond");
  await page.getByRole("button", { name: "채권 계산하기" }).click();
  await expect(page.locator(".dv-ans")).toContainText("9,999.50원", { timeout: 20_000 });
  await expect(page.getByTestId("bond-figs")).toContainText("수익률이 0.01%p 오르면 가격이 약 1.2345원 내려요.");

  await open(page, "?tab=hedge");
  await page.getByRole("button", { name: "헤지 계산하기" }).click();
  await expect(page.locator(".dv-ans")).toContainText("계약을 매도", { timeout: 20_000 });
  await expect(page.locator(".dv-out")).not.toContainText("Short");
  await page.getByLabel("지금 베타").fill("0");
  await page.getByRole("button", { name: "헤지 계산하기" }).click();
  const red = page.locator('.dv-fig[data-k="reduction"]');
  await expect(red).toContainText("계산하지 않아요", { timeout: 20_000 });
  await expect(red).toContainText("줄일 시장 위험이 없어요");
  await expect(red).not.toContainText("0%");
});

test("신용 위험 — 답 = 서버 CVA · ★노출 곡선 점 수 = 서버 ee_values 수★ · 양식화 가정 칩", async ({ page }) => {
  await patch(page, "/calculate-cva", (b) => {
    (b.unilateral_cva as Record<string, number>).cva_amount = 123_000_000;
    (b.exposure_profile as Record<string, unknown>).ee_values = [1, 4, 9, 16, 25, 30, 28, 20, 10, 0].map((x) => x * 1e6);
  });
  await open(page, "?tab=cva");
  await page.getByRole("button", { name: "신용 위험 계산하기" }).click();
  await expect(page.locator(".dv-ans")).toContainText("1억원", { timeout: 20_000 });
  const curve = page.getByTestId("cva-curve");
  await expect(curve).toHaveAttribute("data-points", "10");
  await expect(curve.locator(".recharts-line-dots circle")).toHaveCount(10);
  await expect(page.locator(".dv-out .tx-chip", { hasText: "상품 종류마다 정한 모양" })).toBeVisible();
});

test("★아직 계산하지 않는 모형 — 설명만, 결과처럼 보이는 상수 카드 0★(옛 '10,000 / ON / ON')", async ({ page }) => {
  await open(page, "?tab=models");
  await expect(page.locator(".dv-model")).toHaveCount(3);
  const text = await page.locator(".dv").innerText();
  expect(text).not.toMatch(/10,000|\bON\b|Antithetic|Stratified/);
  await expect(page.locator(".dv")).toContainText("설명만 있어요");
});

test("글 · 대비 · 390 — em-dash·영어 대문자·툴팁 0 · 탭마다 결과까지 라이트/다크 AA · 가로 넘침 0", async ({ page }) => {
  const runs: [string, string][] = [["", "가격 계산하기"], ["?tab=bond", "채권 계산하기"], ["?tab=hedge", "헤지 계산하기"], ["?tab=cva", "신용 위험 계산하기"], ["?tab=models", ""]];
  for (const [q, btn] of runs) {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.evaluate(() => document.documentElement.classList.remove("dark")).catch(() => {});
    await open(page, q);
    if (btn) { await page.getByRole("button", { name: btn }).click(); await expect(page.locator(".dv-out")).toBeVisible({ timeout: 20_000 }); }
    await page.waitForTimeout(500);
    const r = await page.locator(".dv").evaluate((root) => {
      const texts: string[] = [];
      const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n: Node | null;
      while ((n = walk.nextNode())) {
        const el = n.parentElement!; const s = (n.textContent ?? "").trim();
        if (!s || !el.getClientRects().length || el.closest("[data-server],[data-mono],.recharts-wrapper")) continue;
        texts.push(s);
      }
      return { texts, titles: root.querySelectorAll("[title]").length };
    });
    expect(r.texts.filter((s) => s.includes("—")), `${q} em-dash`).toEqual([]);
    expect(r.texts.filter((s) => /\b(Call|Put|Price|Delta|Gamma|Theta|Vega|Rho|Monte Carlo|Short|Long|XVA|Hull-White 1F)\b/.test(s)), `${q} 영어`).toEqual([]);
    expect(r.titles, `${q} title`).toBe(0);
    const light = await page.evaluate<AuditResult>(contrastAudit(".dv"));
    expect(light.low, `${q} 라이트`).toEqual([]);
    await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.waitForTimeout(300);
    const dark = await page.evaluate<AuditResult>(contrastAudit(".dv"));
    expect(dark.low, `${q} 다크`).toEqual([]);
    expect(dark.bright, `${q} 다크 밝은 판`).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    const over = await page.evaluate(() => {
      const m = document.querySelector(".terminal-main") as HTMLElement;
      return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
    });
    expect(over, `${q} 390 넘침`).toBeLessThanOrEqual(0);
  }
});
