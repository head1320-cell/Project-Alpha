import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// CF 3부 PB4 · 고객 한 장 — 캔버스 칩 '한 장' → `/clients/<cid>/sheets/<sid>` (★실제 서버★ · AI 답만 가로챈다)
// ─────────────────────────────────────────────────────────────────────────────
//  · 계산한 뒤에만 만든다(계산 전·고친 뒤에는 단추가 꺼지고 그 까닭을 말한다)
//  · 한 장의 비중 = 캔버스가 받은 서버 계산의 비중 그대로 · 단계는 흐름의 모든 노드 · 연습용 띠 · "새 숫자를 만들지 않았어요"
//  · 인쇄 — 도구·메뉴는 숨고 한 장만 · 고객 AI 미리 묻기(답·사실 칩 · 투자 판단은 고객용 고정 문장) · 지우기 · 고객 화면에 한 장
// ═══════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const tag = () => `${Date.now().toString(36).slice(-5)}${Math.floor(Math.random() * 90 + 10)}`;

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

type RunBody = { nodes: Record<string, { status: string; view: Record<string, unknown> | null }> };

/** 고객 하나 → 새 정기 점검(`irp` 면 계좌 유형 IRP — 아니면 계좌 점검이 사유와 함께 멈춘다) → 계산 — 계산 응답을 돌려준다. */
async function reviewRun(page: Page, token: string, irp = true): Promise<{ cid: string; alias: string; body: RunBody }> {
  const alias = `PB4 한 장 ${tag()}`;
  const r = await page.request.post(`${API}/pb/clients`, { data: { alias, risk_tolerance: "moderate" }, headers: { Authorization: `Bearer ${token}` } });
  const cid = (await r.json()).client_id as string;
  await page.goto(`/allocation?client=${cid}&new=review`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-client-chip")).toBeVisible({ timeout: 30_000 });
  if (irp) {
    await page.locator('.pg-node[data-node-id="account"]').click();
    await page.locator('.pg-tab[data-tab="settings"]').click();
    await page.locator('.pg-basic-field[data-field="account_type"] .pg-choice[data-choice="irp"]').click();
  }
  const sheetBtn = page.locator(".pg-client-chip .pg-client-sheet");
  await expect(sheetBtn).toBeDisabled();                                     // 계산 전에는 만들 수 없다
  await expect(sheetBtn).toHaveAttribute("title", /계산/);
  const resp = page.waitForResponse((x) => x.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return { cid, alias, body };
}

async function makeSheet(page: Page): Promise<string> {
  await page.locator(".pg-client-chip .pg-client-sheet").click();
  await expect(page).toHaveURL(/\/clients\/cl_[0-9a-f]+\/sheets\/sh_[0-9a-f]+$/, { timeout: 30_000 });
  await expect(page.locator(".cs-sheet")).toBeVisible();
  return page.url().split("/").pop()!;
}

test("PB4 · 계산 뒤 '한 장' — 비중은 서버 계산 그대로 · 단계 전부(계산 못 한 단계는 사유와 함께) · 연습용 띠 · 꼬리말 · 고객 화면에 한 장", async ({ page }) => {
  const token = await login(page);
  const { cid, alias, body } = await reviewRun(page, token, false);
  const sid = await makeSheet(page);
  const sheet = page.locator(".cs-sheet");
  await expect(sheet.locator(".cs-alias")).toContainText(alias);
  const want = body.nodes.optimizer.view!.weights as Record<string, number>;
  await expect(sheet.locator(".cs-weight")).toHaveCount(Object.keys(want).length);
  for (const [code, pct] of Object.entries(want)) {
    await expect(sheet.locator(`.cs-weight[data-code="${code}"] .cs-weight-pct`)).toHaveText(`${pct}%`);
  }
  await expect(sheet.locator(".cs-step")).toHaveCount(13);
  await expect(sheet.locator('.cs-step[data-node-id="account"][data-status="failed"] .cs-step-failed')).toContainText("계좌 유형");
  await expect(sheet.locator('.cs-step[data-node-id="goal"][data-status="blocked"]')).toHaveCount(1);
  await expect(sheet.locator(".cs-practice")).toContainText("연습용");
  await expect(sheet.locator(".cs-foot")).toContainText("새 숫자를 만들지 않았어요");
  await page.goto(`/clients?client=${cid}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(`.cl-sheet[data-sheet-id="${sid}"]`)).toBeVisible();
});

test("PB4 · 고친 뒤에는 '한 장' 이 꺼진다 — 다시 계산하라고 말한다", async ({ page }) => {
  const token = await login(page);
  await reviewRun(page, token);
  await expect(page.locator(".pg-client-chip .pg-client-sheet")).toBeEnabled();
  await page.locator('.pg-node[data-node-id="client"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="risk_tolerance"] .pg-choice[data-choice="aggressive"]').click();
  const btn = page.locator(".pg-client-chip .pg-client-sheet");
  await expect(btn).toBeDisabled();
  await expect(btn).toHaveAttribute("title", /다시 계산/);
});

test("PB4 · 인쇄 — 메뉴·도구는 숨고 한 장만 · 미리 묻기(답·사실 칩 · 투자 판단은 고객용 고정 문장) · 지우기", async ({ page }) => {
  const token = await login(page);
  const { cid } = await reviewRun(page, token);
  const sid = await makeSheet(page);
  await page.emulateMedia({ media: "print" });
  await expect(page.locator(".cs-sheet")).toBeVisible();
  await expect(page.locator(".cs-tools")).toBeHidden();
  await expect(page.locator(".cs-ask")).toBeHidden();
  await expect(page.locator(".cs-share")).toBeHidden();                     // 고객 주소 판(PB6)도 인쇄에 싣지 않는다
  await expect(page.locator(".terminal-nav")).toBeHidden();
  await expect(page.locator(".terminal-sidebar")).toBeHidden();             // 메뉴 레일이 한 장 왼쪽을 덮지 않는다
  // 한 장 전체가 문서 흐름에 있다 — 화면 높이로 자르는 스크롤 상자가 위에 없어야 인쇄가 여러 쪽으로 이어진다
  const clip = await page.evaluate(() => {
    const sheet = document.querySelector(".cs-sheet")!;
    const out: string[] = [];
    for (let el = sheet.parentElement; el; el = el.parentElement) {
      const oy = getComputedStyle(el).overflowY;
      if (oy !== "visible" && el.scrollHeight > el.clientHeight + 1) out.push(`${el.tagName}.${el.className} ${oy}`);
    }
    return { out, left: sheet.getBoundingClientRect().left };
  });
  expect(clip.out).toEqual([]);
  expect(clip.left).toBeGreaterThanOrEqual(0);
  const pdf = (await page.pdf({ format: "A4" })).toString("latin1");
  expect((pdf.match(/\/Type\s*\/Page[^s]/g) ?? []).length).toBeGreaterThan(1);  // 13단계 한 장은 한 쪽에 다 들어가지 않는다
  await page.emulateMedia({ media: "screen" });

  let n = 0;
  await page.route("**/snapshots/*/ask", (r) => r.fulfill({ json: n++ === 0
    ? { available: true, source: "claude", answer: { answerable: true, cannot: null, sentences: [{ text: "가장 큰 비중은 34.04% 예요.", fact_ids: ["f1"] }] },
        facts: { f1: { target_kind: "sheet", target_id: sid, where: "비중 계산", part: "비중", index: 0, text: "삼성전자 34.04%" } },
        rejected: [], notice: "연습용 결과예요." }
    : { available: true, source: "claude", answer: { answerable: false, cannot: "투자 판단은 담당 PB와 상담해 주세요 — 여기서는 이 한 장에 적힌 내용만 설명해요.", sentences: [] },
        facts: {}, rejected: [], notice: null } }));
  const ask = page.locator(".cs-ask");
  await ask.locator(".cs-ask-input").fill("가장 큰 비중은 얼마예요?");
  await ask.locator(".cs-ask-go").click();
  await expect(ask.locator(".cs-ask-answer")).toContainText("가장 큰 비중은 34.04% 예요.");
  await expect(ask.locator(".cs-ask-fact")).toContainText("사실 1");
  await ask.locator(".cs-ask-input").fill("지금 사도 되나요?");
  await ask.locator(".cs-ask-go").click();
  await expect(ask.locator(".cs-ask-cannot")).toContainText("담당 PB");

  page.once("dialog", (d) => void d.accept());
  await page.locator(".cs-delete").click();
  await expect(page).toHaveURL(new RegExp(`/clients\\?client=${cid}$`));
  await expect(page.locator(`.cl-sheet[data-sheet-id="${sid}"]`)).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`PB4 · 대비(${scheme}) — 한 장 화면 AA 미달 0`, async ({ page }) => {
    const token = await login(page);
    await reviewRun(page, token);
    const url = new URL(page.url());
    await makeSheet(page);
    void url;
    if (scheme === "dark") {
      await page.evaluate(() => { try { localStorage.setItem("alpha_theme", "dark"); } catch { /* */ } });
      await page.reload();
      await expect(page.locator("html")).toHaveClass(/dark/);
    }
    await expect(page.locator(".cs-sheet")).toBeVisible();
    const a = await page.evaluate<AuditResult>(contrastAudit(".cs-page"));
    expect(a.checked).toBeGreaterThanOrEqual(12);
    expect(a.low, scheme).toEqual([]);
  });
}
