import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// CF 3부 PB3 · 고객 여러 명 관리 — `/clients` · 고객별 설계 문서 · 캔버스 고객 칩 (★실제 서버★ — 가로채지 않는다)
// ─────────────────────────────────────────────────────────────────────────────
//  · 로그인 전에는 로그인하라고만 말한다 · 별칭에 전화번호 모양이면 서버 사유 그대로(짝: 보통 별칭은 목록에)
//  · 정기 점검으로 새 문서 → 캔버스(고객 칩 · 고객 노드에 이 고객의 성향) → 고객 문서에 저장 → 고친 것 → 다시 저장 →
//    고객 화면에 문서 → 다시 열면 고친 것 그대로 · ★이 브라우저 작업 중 문서와 섞지 않는다★(나와서 연 캔버스는 원래 작업 중 문서)
//  · 보관 → 목록에서 숨고 보관함에 · 보관한 고객의 문서는 읽기만 · 남의(없는) 고객 주소는 사유와 함께 일반 캔버스
// E2E 서버 DB 는 실행 사이에 남는다 — 별칭에 실행마다 다른 꼬리를 붙여 그 줄만 본다.
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

async function newClient(page: Page, token: string, alias: string, extra: Record<string, unknown> = {}) {
  const r = await page.request.post(`${API}/pb/clients`, { data: { alias, ...extra }, headers: { Authorization: `Bearer ${token}` } });
  expect(r.status(), await r.text()).toBe(201);
  return (await r.json()) as { client_id: string };
}

async function exportDoc(page: Page) {
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  return JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
}

const row = (page: Page, alias: string) => page.locator(".cl-item", { hasText: alias });

test("PB3 · 로그인 전에는 로그인하라고만 말한다 · 메뉴에 '고객'", async ({ page }) => {
  await page.goto("/clients", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".cl-signed-out")).toContainText("로그인");
  await expect(page.locator(".cl-signed-out a")).toHaveAttribute("href", /\/login\?next=%2Fclients/);
  await expect(page.locator('.nav-item[href="/clients"]')).toContainText("고객");
});

test("PB3 · 더하기 — 별칭에 전화번호 모양이면 서버 사유 그대로 · 짝: 보통 별칭은 목록에 · 실명을 적지 말라는 안내", async ({ page }) => {
  await login(page);
  await page.goto("/clients", { waitUntil: "domcontentloaded" });
  const add = page.locator(".cl-add");
  await expect(add).toContainText("실명");
  await add.locator(".cl-add-alias").fill("010-1234-5678");
  await add.locator(".cl-add-go").click();
  await expect(add.locator(".cl-add-error")).toContainText("전화번호");
  const alias = `PB3 고객 ${tag()}`;
  await add.locator(".cl-add-alias").fill(alias);
  await add.locator(".cl-add-risk").selectOption("moderate");
  await add.locator(".cl-add-go").click();
  await expect(row(page, alias)).toBeVisible();
  await expect(row(page, alias)).toContainText("위험중립형");
  await expect(add.locator(".cl-add-error")).toHaveCount(0);
});

test("PB3 · 정기 점검으로 새 문서 → 저장 → 고침 → 다시 저장 → 다시 열기 · 작업 중 문서와 섞지 않는다", async ({ page }) => {
  const token = await login(page);
  // 작업 중 문서 — 기본 사슬이 이 탭에 남는다
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  const wipCount = await page.locator(".pg-node").count();
  const alias = `PB3 점검 ${tag()}`;
  const { client_id } = await newClient(page, token, alias, { risk_tolerance: "moderate", profile_source: "survey", assessed_at: "2026-01-02" });

  await page.goto(`/clients?client=${client_id}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".cl-detail")).toContainText(alias);
  await page.locator(".cl-new-review").click();
  await expect(page).toHaveURL(new RegExp(`/allocation\\?client=${client_id}&new=review`));
  const chip = page.locator(".pg-client-chip");
  await expect(chip).toContainText(alias);
  await expect(chip.locator(".pg-client-state")).toContainText("저장 전");
  await expect(page.locator(".pg-node")).toHaveCount(13);
  let doc = await exportDoc(page);
  expect(doc.nodes.find((n: { id: string }) => n.id === "client").params)
    .toMatchObject({ alias, risk_tolerance: "moderate", profile_source: "survey", assessed_at: "2026-01-02" });

  await chip.locator(".pg-client-save").click();
  await expect(chip.locator(".pg-client-state")).toContainText("저장함");
  await expect(page).toHaveURL(new RegExp(`client=${client_id}&doc=cd_`));
  const docId = new URL(page.url()).searchParams.get("doc")!;

  // 고치면 '고친 것이 있어요' → 다시 저장
  await page.locator('.pg-node[data-node-id="account"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="account_type"] .pg-choice[data-choice="irp"]').click();
  await expect(chip.locator(".pg-client-state")).toContainText("고친 것 있음");
  await chip.locator(".pg-client-save").click();
  await expect(chip.locator(".pg-client-state")).toContainText("저장함");

  // 고객 화면에 문서가 있고, 다시 열면 고친 것 그대로
  await page.goto(`/clients?client=${client_id}`, { waitUntil: "domcontentloaded" });
  const d = page.locator(`.cl-doc[data-doc-id="${docId}"]`);
  await expect(d).toContainText("정기 점검");
  await d.locator(".cl-doc-open").click();
  await expect(page.locator(".pg-client-chip .pg-client-state")).toContainText("저장함");
  doc = await exportDoc(page);
  expect(doc.nodes.find((n: { id: string }) => n.id === "account").params.account_type).toBe("irp");

  // 메뉴로 나가 일반 캔버스 — 원래 작업 중 문서(고객 문서가 섞이지 않았다)
  await page.locator('.nav-item[href="/allocation"]').click();
  await expect(page).toHaveURL(/\/allocation$/);
  await expect(page.locator(".pg-client-chip")).toHaveCount(0);
  await expect(page.locator(".pg-node")).toHaveCount(wipCount);
  await expect(page.locator('.pg-node[data-node-id="client"]')).toHaveCount(0);
});

test("PB3 · 메뉴로 들어가 연 고객 문서 — 되돌리기로 이전 캔버스가 고객 문서에 섞이지 않는다", async ({ page }) => {
  const token = await login(page);
  const alias = `PB3 되돌리기 ${tag()}`;
  const { client_id } = await newClient(page, token, alias);
  const g = { format: "project-alpha.portfolio-graph", version: 1, edges: [],
              nodes: [{ id: "c", type: "client_profile", params: { alias }, position: { x: 0, y: 0 } },
                      { id: "u", type: "universe", params: { tickers: ["005930"] }, position: { x: 400, y: 0 } }] };
  const made = await page.request.post(`${API}/pb/clients/${client_id}/docs`, { data: { name: "두 노드 문서", graph: g }, headers: { Authorization: `Bearer ${token}` } });
  const docId = (await made.json()).doc_id as string;
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  // 앱 안 이동(메뉴 → 고객 → 캔버스에서 열기) — 이전 캔버스가 상태에 남은 채로 들어간다
  await page.locator('.nav-item[href="/clients"]').click();
  await row(page, alias).click();
  await page.locator(`.cl-doc[data-doc-id="${docId}"] .cl-doc-open`).click();
  await expect(page.locator(".pg-client-chip .pg-client-state")).toContainText("저장함");
  await expect(page.locator(".pg-node")).toHaveCount(2);
  await page.locator(".pg-node").first().click();
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(300);
  await expect(page.locator(".pg-node")).toHaveCount(2);                     // 이전 캔버스로 돌아가지 않는다
  await expect(page.locator(".pg-client-chip .pg-client-state")).toContainText("저장함");
});

test("PB3 · 보관 — 목록에서 숨고 보관함에 · 보관한 고객의 문서는 읽기만 · 다시 꺼내면 돌아온다", async ({ page }) => {
  const token = await login(page);
  const alias = `PB3 보관 ${tag()}`;
  const { client_id } = await newClient(page, token, alias);
  const g = { format: "project-alpha.portfolio-graph", version: 1, nodes: [{ id: "c", type: "client_profile", params: {}, position: { x: 0, y: 0 } }], edges: [] };
  const made = await page.request.post(`${API}/pb/clients/${client_id}/docs`, { data: { name: "보관 전 문서", graph: g }, headers: { Authorization: `Bearer ${token}` } });
  const docId = (await made.json()).doc_id as string;
  await page.goto(`/clients?client=${client_id}`, { waitUntil: "domcontentloaded" });
  await page.locator(".cl-archive").click();
  await expect(row(page, alias)).toHaveCount(0);
  await page.locator('.cl-list-tab[data-tab="archived"]').click();
  await expect(row(page, alias)).toBeVisible();
  await page.goto(`/allocation?client=${client_id}&doc=${docId}`, { waitUntil: "domcontentloaded" });
  const chip = page.locator(".pg-client-chip");
  await expect(chip).toContainText("보관");
  await expect(chip.locator(".pg-client-save")).toBeDisabled();
  // 고쳐도 저장할 수 없다(고친 것이 없어서 꺼진 것이 아니다 — 공허한 확인이 아니게 하나 고친다)
  await page.locator('.pg-node[data-node-id="c"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="risk_tolerance"] .pg-choice[data-choice="aggressive"]').click();
  await expect(chip).toHaveAttribute("data-state", "archived");
  await expect(chip.locator(".pg-client-save")).toBeDisabled();
  await page.goto(`/clients?client=${client_id}`, { waitUntil: "domcontentloaded" });
  await page.locator(".cl-unarchive").click();
  await page.locator('.cl-list-tab[data-tab="active"]').click();
  await expect(row(page, alias)).toBeVisible();
});

test("PB3 · 목록을 읽는 사이 보관·다시 꺼내기를 해도 목록이 최신이다(처음 읽기와 겹침)", async ({ page }) => {
  // 처음 목록 읽기가 끝나기 전에 고치면, 다시 읽기가 처음 읽기(고치기 전 값)에 얹혀 옛 목록이 남았다 — 고객이 많아 목록이 느려지자 드러남.
  const token = await login(page);
  const alias = `PB3 겹침 ${tag()}`;
  const { client_id } = await newClient(page, token, alias);
  let first = true;
  await page.route("**/api/v1/pb/clients", async (r) => {
    if (r.request().method() === "GET" && first) {
      first = false;
      const res = await r.fetch();                       // 고치기 전 목록을 받아 두고
      await new Promise((ok) => setTimeout(ok, 1500));   // 늦게 돌려준다
      await r.fulfill({ response: res });
    } else await r.continue();
  });
  await page.goto(`/clients?client=${client_id}`, { waitUntil: "domcontentloaded" });
  await page.locator(".cl-archive").click();             // 처음 목록이 아직 오는 중
  await expect(row(page, alias)).toHaveCount(0);
  await page.waitForTimeout(1800);                       // 늦은 옛 목록이 도착한 뒤에도
  await expect(row(page, alias)).toHaveCount(0);
});

test("PB3 · 목록을 읽는 사이 더한 고객도 목록에 보인다(처음 읽기와 겹침)", async ({ page }) => {
  await login(page);
  const alias = `PB3 겹쳐 더함 ${tag()}`;
  let first = true;
  await page.route("**/api/v1/pb/clients", async (r) => {
    if (r.request().method() === "GET" && first) {
      first = false;
      const res = await r.fetch();
      await new Promise((ok) => setTimeout(ok, 1500));
      await r.fulfill({ response: res });
    } else await r.continue();
  });
  await page.goto("/clients", { waitUntil: "domcontentloaded" });
  await page.locator(".cl-add-alias").fill(alias);
  await page.locator(".cl-add-go").click();              // 처음 목록이 아직 오는 중
  await page.waitForTimeout(1800);
  await expect(row(page, alias)).toBeVisible();
});

test("PB3 · 없는(남의) 고객 주소 — 사유를 말하고 일반 캔버스로 연다(칩 없음)", async ({ page }) => {
  await login(page);
  await page.goto("/allocation?client=cl_0000000000000000&doc=cd_0000000000000000", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("고객 문서를 열지 못했어요")).toBeVisible();
  await expect(page.getByText("그 고객이 없어요")).toBeVisible();
  await expect(page.locator(".pg-client-chip")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`PB3 · 대비(${scheme}) — 고객 화면 AA 미달 0`, async ({ page }) => {
    const token = await login(page);
    await newClient(page, token, `PB3 대비 ${tag()}`, { risk_tolerance: "conservative", assessed_at: "2026-02-03", horizon_years: 7 });
    if (scheme === "dark") await page.addInitScript(() => { try { localStorage.setItem("alpha_theme", "dark"); } catch { /* */ } });
    await page.goto("/clients", { waitUntil: "domcontentloaded" });
    await expect(page.locator(".cl-item").first()).toBeVisible();
    if (scheme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    const a = await page.evaluate<AuditResult>(contrastAudit(".cl-page"));
    expect(a.checked).toBeGreaterThanOrEqual(8);
    expect(a.low, `${scheme}`).toEqual([]);
  });
}
