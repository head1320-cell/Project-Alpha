import { test, expect, type Browser, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// CF 3부 PB6 · 고객 주소 + 고객 화면 `/c` (★유통 관문 뒤★ · 실제 서버 · 관리자 API 로 관문을 열고 닫는다 · AI 답만 가로챈다)
// ─────────────────────────────────────────────────────────────────────────────
//  · 관문이 닫혀 있으면 PB 판이 사유·빠진 칸을 말하고 만들기가 꺼진다 · 열리면 만들기 → 한 번만 보이는 주소
//  · 고객은 새 브라우저에서 주소 → PIN(틀리면 같은 말 · 5번이면 잠김 → PB 가 풀기) → 한 장(메뉴 없음) → 묻기
//  · PB 가 끄면 / 관문을 닫으면 고객 화면이 바로 막힌다(닫는 길은 관문과 무관하게 된다)
//  · 대비 — PB 판 · 고객 PIN · 고객 한 장(라이트·다크)
// ═══════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const GATE = `${API}/admin/distribution-gate`;
const PIN = "382915";
const DECL = { authority: "E2E 운영자 확인 기관", license_kind: "E2E 종류", license_no: "E2E-0001", verified_at: "2026-10-29", scope: "E2E 고객 한 장" };
const tag = () => `${Date.now().toString(36).slice(-5)}${Math.floor(Math.random() * 90 + 10)}`;

test.describe.configure({ mode: "serial" });

async function token(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()).access_token as string;
}

async function gate(page: Page, open: boolean) {
  const h = { Authorization: `Bearer ${await token(page)}` };
  if (open) expect((await page.request.post(GATE, { data: DECL, headers: h })).status()).toBe(201);
  else await page.request.delete(GATE, { headers: h });               // 열린 것이 없으면 404 — 닫힌 것은 같다
}

/** PB(관리자 계정)가 고객 하나 → 정기 점검(IRP) → 계산 → 한 장 → 한 장 화면. */
async function sheetPage(page: Page): Promise<{ cid: string; url: string }> {
  const t = await token(page);
  await page.addInitScript((x) => { try { localStorage.setItem("project-alpha.auth-token", x); } catch { /* */ } }, t);
  const r = await page.request.post(`${API}/pb/clients`, { data: { alias: `PB6 ${tag()}`, risk_tolerance: "moderate" }, headers: { Authorization: `Bearer ${t}` } });
  const cid = (await r.json()).client_id as string;
  await page.goto(`/allocation?client=${cid}&new=review`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-client-chip")).toBeVisible({ timeout: 30_000 });
  await page.locator('.pg-node[data-node-id="account"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="account_type"] .pg-choice[data-choice="irp"]').click();
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 60_000 });
  await page.locator(".pg-client-chip .pg-client-sheet").click();
  await expect(page).toHaveURL(/\/clients\/cl_[0-9a-f]+\/sheets\/sh_[0-9a-f]+$/, { timeout: 30_000 });
  await expect(page.locator(".cs-share")).toBeVisible();
  return { cid, url: page.url() };
}

async function makeLink(page: Page): Promise<string> {
  const share = page.locator(".cs-share");
  await share.locator(".cs-share-pin").fill(PIN);
  await share.locator(".cs-share-days").selectOption("7");
  await share.locator(".cs-share-make").click();
  const url = share.locator(".cs-share-url");
  await expect(url).toHaveValue(/\/c#t=[A-Za-z0-9_-]{40,}$/);
  return url.inputValue();
}

async function customer(browser: Browser, link: string, pbToken?: string): Promise<Page> {
  const ctx = await browser.newContext();                               // 로그인 없는 새 브라우저
  if (pbToken) await ctx.addInitScript((x) => { try { localStorage.setItem("project-alpha.auth-token", x); } catch { /* */ } }, pbToken);
  const p = await ctx.newPage();
  await p.goto(link);
  await expect(p.locator(".sv-pin-card")).toBeVisible();
  return p;
}

async function enter(p: Page, pin: string) {
  await p.locator(".sv-pin").fill(pin);
  await p.locator(".sv-open").click();
}

test.afterEach(async ({ page }) => { await gate(page, false); });

test("PB6 · 관문이 닫혀 있으면 PB 판이 사유·빠진 칸을 말하고 만들기가 꺼진다 — 서버도 403", async ({ page }) => {
  await gate(page, false);
  const { cid } = await sheetPage(page);
  const share = page.locator(".cs-share");
  await expect(share.locator(".cs-share-blocked")).toContainText("유통 관문이 닫혀");
  await expect(share.locator(".cs-share-missing")).toContainText("인가 번호");
  await expect(share.locator(".cs-share-make")).toBeDisabled();
  await expect(share.locator(".cs-share-pin")).toBeDisabled();
  const sid = page.url().split("/").pop()!;
  const r = await page.request.post(`${API}/pb/clients/${cid}/share-links`, {
    data: { sheet_id: sid, pin: PIN, days: 7 }, headers: { Authorization: `Bearer ${await token(page)}` } });
  expect(r.status()).toBe(403);
  expect((await r.json()).detail.code).toBe("distribution_blocked");
});

test("PB6 · PIN 을 적는 사이 관문이 닫히면 — 서버 사유를 보이고, 6자리가 적혀 있어도 만들기는 꺼진다", async ({ page }) => {
  await gate(page, true);
  await sheetPage(page);
  const share = page.locator(".cs-share");
  await share.locator(".cs-share-pin").fill(PIN);
  await expect(share.locator(".cs-share-make")).toBeEnabled();                  // 짝 — 열려 있으면 켜진다
  await gate(page, false);
  await share.locator(".cs-share-make").click();
  await expect(share.locator(".cs-share-err")).toContainText("인가");           // 403 의 사유 문장 그대로(상태 번호가 아니라)
  await expect(share.locator(".cs-share-blocked")).toBeVisible();
  await expect(share.locator(".cs-share-pin")).toHaveValue(PIN);
  await expect(share.locator(".cs-share-make")).toBeDisabled();                 // PIN 이 6자리여도 관문이 닫혀 있으면 꺼진다
  await expect(page.locator(".cs-share-row")).toHaveCount(0);
});

test("PB6 · 주소 → 고객 PIN(틀리면 같은 말) → 한 장(메뉴 없음 · 주소창에 토큰 없음) → 묻기 → PB 가 끄면 바로 막힘", async ({ page, browser }) => {
  await gate(page, true);
  await sheetPage(page);
  const weights = await page.locator(".cs-sheet .cs-weight").count();
  const link = await makeLink(page);
  await expect(page.locator('.cs-share-row[data-state="open"] .cs-share-title')).toHaveText("이 한 장");
  await expect(page.locator(".cs-delete")).toHaveCount(0);                      // 보여 준 한 장은 지울 수 없다

  // 같은 브라우저에 PB 로그인이 남아 있어도 고객 경로에는 싣지 않는다
  const c = await customer(browser, link, await token(page));
  const sent: string[] = [];
  c.on("request", (q) => { if (q.url().includes("/api/v1/share/") && q.headers()["authorization"]) sent.push(q.url()); });
  expect(c.url()).not.toContain("#t=");                                         // 주소창에서 토큰을 지운다
  await expect(c.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  await expect(c.locator('meta[name="referrer"]')).toHaveAttribute("content", "no-referrer");
  await enter(c, "902817");
  await expect(c.locator(".sv-err")).toHaveText("주소나 PIN 이 맞지 않아요.");
  await enter(c, PIN);
  await expect(c.locator(".cs-sheet")).toBeVisible();
  await expect(c.locator(".cs-sheet .cs-weight")).toHaveCount(weights);
  await expect(c.locator(".cs-weights-sec .cs-sub")).toHaveText("이번 점검에서 정한 비중이에요.");   // 고객에게는 '노드' 를 말하지 않는다
  await expect(c.locator(".terminal-nav")).toHaveCount(0);
  await expect(c.locator(".sv-until")).toContainText("까지 열려요");

  await c.route("**/api/v1/share/ask", (r) => r.fulfill({ json: {
    available: true, source: "claude", answer: { answerable: true, cannot: null, sentences: [{ text: "가장 큰 비중은 34.04% 예요.", fact_ids: ["f1"] }] },
    facts: { f1: { where: "비중 계산", part: "비중", index: 0, text: "삼성전자 34.04%" } }, rejected: [], notice: null } }));
  await c.locator(".cs-ask-input").fill("가장 큰 비중은요?");
  await c.locator(".cs-ask-go").click();
  await expect(c.locator(".cs-ask-answer")).toContainText("34.04%");
  await c.unroute("**/api/v1/share/ask");
  expect(sent).toEqual([]);

  page.once("dialog", (d) => void d.accept());
  await page.locator(".cs-share-row .cs-share-revoke").click();
  await expect(page.locator('.cs-share-row[data-state="revoked"]')).toHaveCount(1);
  await c.locator(".cs-ask-input").fill("다시 물어요");
  await c.locator(".cs-ask-go").click();
  await expect(c.locator(".sv-stop")).toContainText("끝난 주소");
  await c.context().close();
});

test("PB6 · 다섯 번 틀리면 잠기고 PB 가 풀면 다시 열린다", async ({ page, browser }) => {
  await gate(page, true);
  await sheetPage(page);
  const link = await makeLink(page);
  const c = await customer(browser, link);
  for (let i = 0; i < 4; i++) {
    await enter(c, "902817");
    await expect(c.locator(".sv-err")).toBeVisible();
  }
  await enter(c, "902817");
  await expect(c.locator(".sv-stop")).toContainText("잠긴 주소");
  await page.reload();
  const row = page.locator('.cs-share-row[data-state="locked"]');
  await expect(row).toContainText("PIN 틀림 5번");
  await row.locator(".cs-share-reopen").click();
  await expect(page.locator('.cs-share-row[data-state="open"]')).toHaveCount(1);
  await c.reload();                                                             // 토큰은 이 탭(sessionStorage)에 남아 있다
  await enter(c, PIN);
  await expect(c.locator(".cs-sheet")).toBeVisible();
  await c.context().close();
});

test("PB6 · 관문을 닫으면 열려 있던 고객 화면도 막히고, PB 는 여전히 주소를 끌 수 있다", async ({ page, browser }) => {
  await gate(page, true);
  await sheetPage(page);
  const link = await makeLink(page);
  const c = await customer(browser, link);
  await enter(c, PIN);
  await expect(c.locator(".cs-sheet")).toBeVisible();
  await gate(page, false);
  await c.locator(".cs-ask-input").fill("비중은요?");
  await c.locator(".cs-ask-go").click();
  await expect(c.locator(".sv-stop")).toContainText("지금은 열 수 없어요");
  await expect(c.locator(".sv-stop")).not.toContainText("인가");                 // 고객에게 운영 사유를 보이지 않는다
  await page.reload();
  await expect(page.locator(".cs-share-blocked")).toBeVisible();
  page.once("dialog", (d) => void d.accept());
  await page.locator(".cs-share-row .cs-share-revoke").click();
  await expect(page.locator('.cs-share-row[data-state="revoked"]')).toHaveCount(1);
  await c.context().close();
});

test("PB6 · 390 — PIN·묻기 칸이 납작해지지 않고 가로로 넘치지 않는다", async ({ page, browser }) => {
  await gate(page, true);
  await sheetPage(page);
  const link = await makeLink(page);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const c = await ctx.newPage();
  await c.goto(link);
  await expect(c.locator(".sv-pin")).toHaveAttribute("placeholder", "숫자 6자리");   // 점 모양은 이미 적힌 PIN 처럼 보인다
  expect((await c.locator(".sv-pin").boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await enter(c, PIN);
  await expect(c.locator(".cs-sheet")).toBeVisible();
  const box = (await c.locator(".cs-ask-input").boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(40);                                // 좁으면 세로로 쌓는다 — 칸 높이는 그대로
  expect(await c.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await ctx.close();
});

test("PB6 · 토큰 없는 주소는 열 수 없다고 말한다", async ({ page }) => {
  await page.goto("/c");
  await expect(page.locator(".sv-missing")).toContainText("주소가 완전하지 않아요");
  await expect(page.locator(".terminal-nav")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`PB6 · 대비(${scheme}) — PB 판 · 고객 PIN · 고객 한 장 AA 미달 0`, async ({ page, browser }) => {
    await gate(page, true);
    await sheetPage(page);
    const link = await makeLink(page);
    const ctx = await browser.newContext({ colorScheme: scheme });
    await ctx.addInitScript((s) => { try { localStorage.setItem("alpha_theme", s); } catch { /* */ } }, scheme);
    const c = await ctx.newPage();
    if (scheme === "dark") {
      await page.evaluate(() => { try { localStorage.setItem("alpha_theme", "dark"); } catch { /* */ } });
      await page.reload();
      await expect(page.locator("html")).toHaveClass(/dark/);
    }
    await expect(page.locator('.cs-share-row[data-state="open"]')).toBeVisible();     // 목록까지 읽힌 판을 잰다
    const a0 = await page.evaluate<AuditResult>(contrastAudit(".cs-share"));
    expect(a0.checked).toBeGreaterThanOrEqual(6);
    expect(a0.low, `panel ${scheme}`).toEqual([]);
    await c.goto(link);
    await expect(c.locator(".sv-pin-card")).toBeVisible();
    if (scheme === "dark") await expect(c.locator("html")).toHaveClass(/dark/);
    const a1 = await c.evaluate<AuditResult>(contrastAudit(".sv-page"));
    expect(a1.low, `pin ${scheme}`).toEqual([]);
    await enter(c, PIN);
    await expect(c.locator(".cs-sheet")).toBeVisible();
    const a2 = await c.evaluate<AuditResult>(contrastAudit(".sv-page"));
    expect(a2.checked).toBeGreaterThanOrEqual(12);
    expect(a2.low, `sheet ${scheme}`).toEqual([]);
    await ctx.close();
  });
}
