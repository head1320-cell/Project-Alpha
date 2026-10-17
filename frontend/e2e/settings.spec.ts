import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { cardsOverflow, contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BS1 — 설정 · 비밀번호 바꾸기 · 관리자 계정 발급 (설계 docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md §BS1)
// ─────────────────────────────────────────────────────────────────────────────
// 거는 것 (★실제 백엔드★ — 응답을 흉내 내지 않는 흐름이 중심):
//  · 관리자가 계정을 만들면 임시 비밀번호가 한 번만 보인다 → 그 계정으로 로그인하면 설정으로 보내지고 "먼저 바꿔 주세요"
//  · 바꾸기 전에는 보호 라우트가 403 · 규칙이 다 맞기 전에는 단추가 꺼져 있다(짝) · 바꾸면 옛 토큰은 401, 새 토큰은 산다(짝)
//  · 지금 비밀번호가 틀리면 서버 사유 그대로 · 분석가에게는 계정 관리가 없다(짝)
//  · 로그인 안 됨 · 모름(500 — 토큰을 두고 다시 시도) · 프로필 카드의 '설정' 줄 · 390 · 라이트/다크 AA
// ★admin 비밀번호는 바꾸지 않는다★ — 다른 스펙이 frm123! 로 로그인한다.
// ═══════════════════════════════════════════════════════════════════════════════

const TOKEN_KEY = "project-alpha.auth-token";
const API = "/api/backend/api/v1/auth";

async function apiLogin(req: APIRequestContext, username: string, password: string) {
  const r = await req.post(`${API}/login`, { data: { username, password } });
  expect(r.status(), `${username} 로그인`).toBe(200);
  return (await r.json()) as { access_token: string; must_change_password: boolean };
}

async function seedToken(page: Page, token: string) {
  await page.addInitScript(([k, t]) => {
    if (!sessionStorage.getItem("__seeded")) { localStorage.setItem(k, t); sessionStorage.setItem("__seeded", "1"); }
  }, [TOKEN_KEY, token]);
}

const tokenNow = (page: Page) => page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY);
const uniqueName = () => `e2e_${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;

test("설정(BS1): 관리자가 계정을 만들면 임시 비밀번호가 한 번 보인다 → 그 계정은 설정으로 보내져 먼저 바꾼다 → 옛 토큰은 죽는다", async ({ page, request }) => {
  const admin = await apiLogin(request, "admin", "frm123!");
  await seedToken(page, admin.access_token);
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".set-name")).toHaveText("admin");
  await expect(page.locator(".set-role")).toHaveText("관리자");

  // ── 발급 ─────────────────────────────────────────────────────────────
  const name = uniqueName();
  const admin_ = page.locator(".set-admin");
  await expect(admin_).toBeVisible();
  await admin_.locator('input[name="new-username"]').fill(name);
  await admin_.locator(".set-issue").click();
  const issued = page.locator(".set-issued");
  await expect(issued).toBeVisible();
  const temp = (await issued.locator(".set-issued-pw").textContent())!.trim();
  expect(temp.length).toBeGreaterThanOrEqual(12);
  await expect(issued).toContainText("다시 볼 수 없어요");
  await expect(issued.locator(".set-copy")).toBeVisible();
  await expect(admin_.locator(`.set-acct[data-username="${name}"]`)).toContainText("바꿀 차례");
  // 닫으면 임시 비밀번호가 화면에서 사라진다.
  await issued.locator(".set-issued-close").click();
  await expect(page.locator(".set-issued")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(temp);

  // ── 받은 사람이 로그인 → 설정으로 보내짐 ───────────────────────────────
  const ctx = await page.context().browser()!.newContext();
  const p2 = await ctx.newPage();
  await p2.goto("/login");
  await p2.locator('input[name="username"]').fill(name);
  await p2.locator('input[name="password"]').fill(temp);
  await p2.locator(".login-submit").click();
  await p2.waitForURL(/\/settings/);
  await expect(p2.locator(".set-must")).toBeVisible();
  await expect(p2.locator(".set-must")).toContainText("먼저 바꿔");
  const tempToken = (await p2.evaluate((k) => localStorage.getItem(k), TOKEN_KEY))!;
  const blocked = await p2.request.get("/api/backend/api/v1/live/audit/summary", { headers: { Authorization: `Bearer ${tempToken}` } });
  expect(blocked.status(), "바꾸기 전에는 보호 라우트가 열리지 않는다").toBe(403);

  // ── 규칙이 다 맞기 전에는 단추가 꺼져 있다(짝) ─────────────────────────
  const form = p2.locator(".set-pw");
  const submit = form.locator(".set-pw-submit");
  await expect(form.locator('.set-rule[data-ok="true"]'), "빈 칸이면 어떤 규칙도 '맞아요' 가 아니다").toHaveCount(0);
  await form.locator('input[name="current-password"]').fill(temp);
  await form.locator('input[name="new-password"]').fill("short");
  await expect(form.locator('.set-rule[data-rule="length"]')).toHaveAttribute("data-ok", "false");
  await expect(submit).toBeDisabled();
  const next = `pw-${name}-9`;
  await form.locator('input[name="new-password"]').fill(next);
  await form.locator('input[name="confirm-password"]').fill(next + "x");
  await expect(form.locator('.set-rule[data-rule="confirm"]')).toHaveAttribute("data-ok", "false");
  await expect(submit).toBeDisabled();
  await form.locator('input[name="confirm-password"]').fill(next);
  await expect(form.locator('.set-rule[data-ok="false"]')).toHaveCount(0);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(p2.locator(".set-done")).toContainText("비밀번호를 바꿨어요");
  await expect(p2.locator(".set-must")).toHaveCount(0);

  const newToken = (await p2.evaluate((k) => localStorage.getItem(k), TOKEN_KEY))!;
  expect(newToken).not.toBe(tempToken);
  expect((await p2.request.get(`${API}/me`, { headers: { Authorization: `Bearer ${tempToken}` } })).status(), "옛 토큰은 죽는다").toBe(401);
  expect((await p2.request.get(`${API}/me`, { headers: { Authorization: `Bearer ${newToken}` } })).status(), "새 토큰은 산다(짝)").toBe(200);
  const opened = await p2.request.get("/api/backend/api/v1/live/audit/summary", { headers: { Authorization: `Bearer ${newToken}` } });
  expect([401, 403]).not.toContain(opened.status());
  await ctx.close();

  // 관리자 목록도 바뀐다 — 다시 불러오면 '바꿀 차례' 가 없다.
  await page.reload();
  await expect(page.locator(`.set-acct[data-username="${name}"]`)).toBeVisible();
  await expect(page.locator(`.set-acct[data-username="${name}"]`)).not.toContainText("바꿀 차례");
});

test("설정: 지금 비밀번호가 틀리면 서버 사유 그대로 · 분석가에게는 계정 관리가 없다(짝) · 초기화하면 그 사람 토큰이 죽는다", async ({ page, request }) => {
  const admin = await apiLogin(request, "admin", "frm123!");
  const name = uniqueName();
  const made = await request.post(`${API}/users`, { data: { username: name, role: "analyst" }, headers: { Authorization: `Bearer ${admin.access_token}` } });
  expect(made.status()).toBe(201);
  const temp = (await made.json()).temporary_password as string;
  const first = await apiLogin(request, name, temp);
  const changed = await request.post(`${API}/password`, { data: { current_password: temp, new_password: `pw-${name}-1` }, headers: { Authorization: `Bearer ${first.access_token}` } });
  expect(changed.status()).toBe(200);
  const tok = (await changed.json()).access_token as string;

  await seedToken(page, tok);
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".set-name")).toHaveText(name);
  await expect(page.locator(".set-role")).toHaveText("분석가");
  await expect(page.locator(".set-admin"), "분석가에게는 계정 관리가 없다").toHaveCount(0);
  await expect(page.locator(".set-must")).toHaveCount(0);

  const form = page.locator(".set-pw");
  await form.locator('input[name="current-password"]').fill("not-my-password");
  await form.locator('input[name="new-password"]').fill(`pw-${name}-2`);
  await form.locator('input[name="confirm-password"]').fill(`pw-${name}-2`);
  await form.locator(".set-pw-submit").click();
  await expect(form.locator(".set-error")).toHaveText("지금 비밀번호가 맞지 않아요.");
  expect(await tokenNow(page), "실패해도 토큰은 그대로").toBe(tok);

  // 관리자가 초기화하면 이 사람의 토큰이 죽는다.
  const reset = await request.post(`${API}/users/${name}/reset-password`, { headers: { Authorization: `Bearer ${admin.access_token}` } });
  expect(reset.status()).toBe(200);
  await page.reload();
  await expect(page.locator(".set-signed-out")).toBeVisible();
  await expect(page.locator(".set-signed-out")).toContainText("로그인이 끝났어요");
});

test("설정: 로그인 안 됨이면 로그인으로 안내 · 모름(500)이면 토큰을 두고 다시 시도 · 프로필 카드에 '설정' 줄", async ({ page }) => {
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".set-signed-out")).toBeVisible();
  await expect(page.locator(".set-signed-out a")).toHaveAttribute("href", "/login?next=%2Fsettings");
  // 로그인 안 돼도 화면 테마는 고를 수 있다(이 브라우저에만 남는다).
  await expect(page.locator('.set-seg-b[data-theme="dark"]')).toBeVisible();

  await page.locator(".terminal-header .pf-avatar").first().click();
  await expect(page.locator(".pf-card .pf-settings")).toHaveAttribute("href", "/settings");

  await seedToken(page, "t-keep");
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 500, json: { detail: "테스트" } }));
  await page.goto("/dashboard");
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".set-unknown")).toContainText("500");
  await expect(page.locator(".set-unknown .set-retry")).toBeVisible();
  expect(await tokenNow(page), "모름 ≠ 로그아웃 — 토큰을 지우지 않는다").toBe("t-keep");
});

for (const scheme of ["light", "dark"] as const) {
  test(`설정: ${scheme} AA · 390 가로 넘침 없음 · 다크를 고르면 이 화면도 어둡다`, async ({ page, request }) => {
    const admin = await apiLogin(request, "admin", "frm123!");
    await seedToken(page, admin.access_token);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* 없음 */ } }, scheme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/settings", { waitUntil: "domcontentloaded" });
      await expect(page.locator(".set-name")).toHaveText("admin");
      await expect(page.locator(".set-acct").first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(scheme === "dark");
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, `${width}px 가로 넘침`).toBeLessThanOrEqual(0);
      expect(await page.evaluate<string[]>(cardsOverflow(".set .set-card")), `${width}px 카드 밖으로 나간 칸`).toEqual([]);
      const a = await page.evaluate<AuditResult>(contrastAudit(".set"));
      expect(a.checked).toBeGreaterThan(12);
      expect(a.low, `${scheme} ${width} 대비`).toEqual([]);
      if (scheme === "dark") expect(a.bright, "다크인데 밝은 바탕").toEqual([]);
    }
  });
}
