import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BR R3 — 머리 줄 프로필 (설계 docs/superpowers/specs/2026-09-28-br-robustness-profile-design.md §R3)
// ─────────────────────────────────────────────────────────────────────────────
// 거는 것:
//  · 국면 배지는 머리 줄에 없다(짝 — 예전 계약 `a[href="/macro"]`) · 동그라미 하나 · 머리 줄 높이 64 그대로
//  · ★모름 ≠ 로그아웃★ 네 상태: 토큰 없음(서버를 부르지 않음) · 200(서버 이름·역할 그대로) · 401(토큰을 지우고 "끝났어요") ·
//    500(토큰을 두고 이름을 지어내지 않음 · 다시 시도)
//  · 로그아웃 = 토큰 지움 · 카드는 Esc·바깥 누르기로 닫히고 초점이 동그라미로
//  · 테마: 다크를 고르면 다크를 갖춘 화면만 어둡게(새로고침해도) · 없는 화면은 밝게 두고 그렇다고 말한다(짝) ·
//    시스템은 OS 를 따르고 바뀌면 따라온다(짝)
//  · 390px 에서 카드가 화면 안 · 라이트/다크 AA · 다크에서 옆 메뉴 활성 칸이 흰 채로 남지 않는다
// ═══════════════════════════════════════════════════════════════════════════════

const TOKEN_KEY = "project-alpha.auth-token";
const avatar = (page: Page) => page.locator(".terminal-header .pf-avatar").first();
const card = (page: Page) => page.locator(".pf-card");

async function withToken(page: Page, token: string) {
  // 한 번만 심는다 — 로그아웃 뒤 새로고침에서 다시 심으면 로그아웃을 확인할 수 없다.
  await page.addInitScript(([k, t]) => {
    if (!sessionStorage.getItem("__seeded")) { localStorage.setItem(k, t); sessionStorage.setItem("__seeded", "1"); }
  }, [TOKEN_KEY, token]);
}

async function me(page: Page, status: number, principal?: Record<string, unknown>) {
  const seen: (string | null)[] = [];
  await page.route("**/api/v1/auth/me", async (route) => {
    seen.push(route.request().headers()["authorization"] ?? null);
    if (status === 200) {
      await route.fulfill({ status, json: { principal, secret_state: "configured", secret_reason: null, admin_password_state: "set" } });
    } else {
      await route.fulfill({ status, json: { detail: "테스트 응답" } });
    }
  });
  return seen;
}

const tokenNow = (page: Page) => page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY);
const isDark = (page: Page) => page.evaluate(() => document.documentElement.classList.contains("dark"));

test("프로필(BR R3): 국면 배지 대신 동그라미 하나 · 토큰이 없으면 서버를 부르지 않고 '로그인 안 됨' + 로그인 · Esc·바깥 누르면 닫힘", async ({ page }) => {
  const calls = await me(page, 200, { username: "누구", role: "analyst" });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  const slot = page.locator(".terminal-header .header-actions");
  await expect(avatar(page)).toBeVisible();
  await expect(slot.locator('a[href="/macro"]'), "국면 배지는 머리 줄에서 빠졌다").toHaveCount(0);
  const box = (await avatar(page).boundingBox())!;
  expect(Math.round(box.width)).toBe(32);
  expect(Math.round(box.height)).toBe(32);
  expect(Math.round((await page.locator(".terminal-header").boundingBox())!.height), "머리 줄 높이").toBe(64);
  await expect(avatar(page)).toHaveAttribute("aria-label", "내 계정 — 로그인 안 됨");
  await expect(avatar(page)).toHaveAttribute("aria-expanded", "false");

  await avatar(page).click();
  await expect(card(page)).toBeVisible();
  await expect(avatar(page)).toHaveAttribute("aria-expanded", "true");
  await expect(card(page).locator(".pf-name")).toHaveText("로그인 안 됨");
  await expect(card(page).locator(".pf-login")).toHaveAttribute("href", "/login");
  await expect(card(page).locator(".pf-logout")).toHaveCount(0);
  expect(calls, "토큰이 없으면 /auth/me 를 부르지 않는다").toEqual([]);

  await page.keyboard.press("Escape");
  await expect(card(page)).toHaveCount(0);
  expect(await avatar(page).evaluate((el) => el === document.activeElement), "Esc 뒤 초점은 동그라미로").toBe(true);

  await avatar(page).click();
  await expect(card(page)).toBeVisible();
  await page.mouse.click(700, 500);
  await expect(card(page)).toHaveCount(0);
});

test("프로필: 200 이면 서버 이름·역할 그대로(토큰을 실어 묻는다) · 로그아웃은 토큰을 지우고 '로그아웃했어요'", async ({ page }) => {
  await withToken(page, "t-abc");
  const calls = await me(page, 200, { username: "kim", role: "analyst", source: "token" });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toHaveText("K");
  await expect(avatar(page)).toHaveAttribute("aria-label", "내 계정 — kim (분석가)");
  expect(calls[0]).toBe("Bearer t-abc");
  await avatar(page).click();
  await expect(card(page).locator(".pf-name")).toHaveText("kim");
  await expect(card(page).locator(".pf-role")).toHaveText("분석가");
  await expect(card(page).locator(".pf-login")).toHaveCount(0);

  await card(page).locator(".pf-logout").click();
  expect(await tokenNow(page)).toBeNull();
  await expect(card(page).locator(".pf-name")).toHaveText("로그인 안 됨");
  await expect(card(page).locator(".pf-note")).toHaveText("로그아웃했어요.");
  await expect(card(page).locator(".pf-login")).toBeVisible();
  await expect(avatar(page)).toHaveAttribute("aria-label", "내 계정 — 로그인 안 됨");
});

test("프로필: 관리자 역할은 '관리자' · 어휘 밖 역할은 서버 값 그대로(짝 — 분석가로 접지 않는다)", async ({ page }) => {
  await withToken(page, "t-adm");
  await me(page, 200, { username: "root", role: "admin" });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toHaveAttribute("aria-label", "내 계정 — root (관리자)");
  await page.unroute("**/api/v1/auth/me");
  await me(page, 200, { username: "ops", role: "operator" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toHaveAttribute("aria-label", "내 계정 — ops (operator)");
});

test("프로필: 401 이면 토큰을 지우고 '로그인이 끝났어요' · 500 이면 토큰을 두고 이름을 지어내지 않는다(짝) · 다시 시도", async ({ page }) => {
  await withToken(page, "t-old");
  await me(page, 401);
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toHaveAttribute("aria-label", "내 계정 — 로그인 안 됨");
  expect(await tokenNow(page), "끝난 토큰은 지운다").toBeNull();
  await avatar(page).click();
  await expect(card(page).locator(".pf-note")).toHaveText("로그인이 끝났어요 — 다시 로그인해 주세요.");

  // 짝 — 서버가 답하지 못한 것은 로그아웃이 아니다.
  await page.evaluate((k) => { localStorage.setItem(k, "t-keep"); }, TOKEN_KEY);
  await page.unroute("**/api/v1/auth/me");
  await me(page, 500);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toHaveAttribute("aria-label", "내 계정 — 확인하지 못했어요");
  expect(await tokenNow(page), "모를 때는 토큰을 지우지 않는다").toBe("t-keep");
  await expect(avatar(page).locator("svg"), "이름을 모르면 글자를 지어내지 않는다").toHaveCount(1);
  await avatar(page).click();
  await expect(card(page).locator(".pf-name")).toHaveText("계정 정보를 확인하지 못했어요");
  await expect(card(page).locator(".pf-sub")).toContainText("500");
  await expect(card(page).locator(".pf-login")).toHaveCount(0);

  await page.unroute("**/api/v1/auth/me");
  await me(page, 200, { username: "lee", role: "analyst" });
  await card(page).locator(".pf-retry").click();
  await expect(card(page).locator(".pf-name")).toHaveText("lee");
});

test("화면 테마: 다크를 고르면 설계 화면·모듈은 어둡게(새로고침해도) · 늘 어두운 관리 화면·다크가 없는 화면은 그렇다고 말한다(짝)", async ({ page }) => {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  expect(await isDark(page), "기본은 라이트 — 지금 화면 그대로").toBe(false);
  await avatar(page).click();
  await expect(card(page).locator('.pf-seg-b[data-theme="light"]')).toHaveAttribute("aria-pressed", "true");
  await card(page).locator('.pf-seg-b[data-theme="dark"]').click();
  expect(await isDark(page)).toBe(true);
  expect(await page.evaluate(() => localStorage.getItem("alpha_theme"))).toBe("dark");
  await expect(card(page).locator(".pf-theme-note"), "다크를 갖춘 화면에서는 안내가 없다").toHaveCount(0);

  await page.reload({ waitUntil: "domcontentloaded" });
  expect(await isDark(page), "새로고침해도 — 첫 그림 전에 붙는다").toBe(true);

  // BS5 — 스크리너도 다크를 갖췄다(예전 이 자리는 "밝게"였다).
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toBeVisible();
  expect(await isDark(page), "다크를 갖춘 모듈은 어둡게").toBe(true);
  await avatar(page).click();
  await expect(card(page).locator(".pf-theme-note")).toHaveCount(0);
  await page.keyboard.press("Escape");
  // 짝 — 늘 어두운 관리 화면은 테마와 상관없다고 말한다(밝게만이라고 하지 않는다).
  await page.goto("/admin/live-trading", { waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toBeVisible();
  await avatar(page).click();
  await expect(card(page).locator(".pf-theme-note")).toContainText("늘 어둡게");
  await page.keyboard.press("Escape");
  // 짝 — 다크가 없는 화면은 밝게 두고 그렇다고 말한다.
  await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
  await expect(avatar(page)).toBeVisible();
  expect(await isDark(page), "다크가 없는 화면은 밝게").toBe(false);
  await avatar(page).click();
  await expect(card(page).locator(".pf-theme-note")).toContainText("밝게만");
  await card(page).locator('.pf-seg-b[data-theme="light"]').click();
  await expect(card(page).locator(".pf-theme-note"), "라이트면 안내할 것이 없다").toHaveCount(0);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  expect(await isDark(page)).toBe(false);
});

test("화면 테마: 시스템은 OS 설정을 따르고, 바뀌면 따라온다(짝)", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("alpha_theme", "system"));
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  expect(await isDark(page)).toBe(true);
  await page.emulateMedia({ colorScheme: "light" });
  await expect.poll(() => isDark(page)).toBe(false);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(() => isDark(page)).toBe(true);
});

test("프로필 카드: 390px 에서 화면 안 · 라이트·다크 AA · 다크에서 옆 메뉴 활성 칸이 흰 채로 남지 않는다", async ({ page }) => {
  await withToken(page, "t-abc");
  await me(page, 200, { username: "kim", role: "analyst" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await avatar(page).click();
  const b = (await card(page).boundingBox())!;
  expect(b.x).toBeGreaterThanOrEqual(0);
  expect(b.x + b.width).toBeLessThanOrEqual(390);

  await page.setViewportSize({ width: 1280, height: 800 });
  const light = await page.evaluate<AuditResult>(contrastAudit(".pf-card"));
  expect(light.checked).toBeGreaterThan(5);
  expect(light.low, "라이트 AA").toEqual([]);

  await page.evaluate(() => localStorage.setItem("alpha_theme", "dark"));
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  expect(await isDark(page)).toBe(true);
  await avatar(page).click();
  const dark = await page.evaluate<AuditResult>(contrastAudit(".pf-card"));
  expect(dark.checked).toBeGreaterThan(5);
  expect(dark.low, "다크 AA").toEqual([]);
  expect(dark.bright, "다크인데 밝은 배경").toEqual([]);
  const head = await page.evaluate<AuditResult>(contrastAudit(".terminal-header"));
  expect(head.low).toEqual([]);
  const active = await page.locator(".terminal-nav .nav-item.active").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(active, "다크에서 활성 칸이 흰색").not.toBe("rgb(255, 255, 255)");
});
