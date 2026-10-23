import { readFileSync } from "node:fs";
import path from "node:path";
import { test, expect, type Page, type Request } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU8b · 로그인 `/login` — 메뉴 없는 단독 한 화면 (계획 "BU8 상세" · 사용자 결정)
 * 거는 것(짝으로 항상-통과·항상-거부를 배제):
 *  · 셸(머리 줄·왼쪽 메뉴)이 없다 — 짝: 홈에는 있다
 *  · 실패는 사람 말, 원문은 닫힌 '원래 사유 보기' 안에만 · 502 원문의 내부 주소는 보이는 글에 없다 · 네트워크 실패도 말한다
 *  · 요청 본문은 정확히 {username, password} · Enter 로 보낸다 · 보내는 동안 단추가 잠긴다
 *  · 돌아가기: 안전한 `?next=`(앱 안 경로)면 그리로 — 짝: 바깥 주소(`//`·`https:`·`/\`)는 홈으로 · next 없음도 홈으로
 *    · 임시 비밀번호면 next 보다 비밀번호 바꾸는 칸이 먼저(BS1)
 *  · 아이디 64자 한도(서버 한도와 같다) · em-dash 0 · 라이트/다크 AA · 390 가로 넘침 0
 *  · ★로그인이 여는 것 지도★(사용자 결정): 층 셋이 지도 파일(`entities/session/accessMap.json`) 그대로 — 그 파일이 서버 보호 목록과
 *    같은지는 `tests/test_login_access_map.py` 가 양방향으로 본다 · 서버 칩 둘: 데이터 출처(connection-status) · 실행 모드(live/mode 번역,
 *    모르는 값은 서버 값 그대로, 실패는 '확인하지 못했어요' — 침묵 0)
 * 성공 경로는 실제 서버(admin) 로 한 번 확인하고, 응답 모양에 따른 갈래는 서버 응답을 바꿔 확인한다.
 */

const LOGIN = "**/api/v1/auth/login";
const user = (p: Page) => p.locator('input[name="username"]');
const pass = (p: Page) => p.locator('input[name="password"]');
const err = (p: Page) => p.locator(".login-error");

async function fill(page: Page, u = "nobody-e2e", pw = "wrong-pass") {
  await user(page).fill(u);
  await pass(page).fill(pw);
}
/** 로그인 응답을 고쳐 준다 — 토큰 모양은 서버와 같다(쓰이는 곳이 없는 가짜 값). */
async function okLogin(page: Page, must = false) {
  await page.route(LOGIN, (r) => r.fulfill({ json: { access_token: "e2e.fake.token", token_type: "bearer", must_change_password: must } }));
}

test("셸 없이 혼자 선다 — 머리 줄·왼쪽 메뉴 0 · 짝: 홈에는 있다 · 첫 화면으로 가는 이름표", async ({ page }) => {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".lg h1")).toHaveText("로그인");
  await expect(page.locator(".terminal-sidebar, .terminal-header")).toHaveCount(0);
  await expect(page.locator(".lg-brand")).toHaveAttribute("href", "/");
  await expect(page.locator(".lg-note")).toHaveText("계정은 관리자에게 받아요. 따로 가입하는 곳은 없어요.");
  await expect(page.locator(".lg")).not.toContainText("—");
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".terminal-sidebar")).toHaveCount(1);
});

test("★틀린 자격 증명(실제 서버 401) → 사람 말 · 원문은 닫힌 칸 안에 그대로 · 'HTTP' 글자 0★", async ({ page }) => {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await fill(page);
  const res = page.waitForResponse((r) => r.url().endsWith("/api/v1/auth/login"));
  await page.locator(".login-submit").click();
  const body = (await (await res).json()) as { detail: string };
  expect((await res).status()).toBe(401);
  await expect(err(page)).toHaveAttribute("role", "alert");
  await expect(err(page).locator(".lg-error-say")).toHaveText("아이디 또는 비밀번호가 맞지 않아요.");
  const raw = err(page).locator("details.lg-raw");
  expect(await raw.evaluate((d) => (d as HTMLDetailsElement).open), "원문 칸은 닫혀 있다").toBe(false);
  expect(await err(page).innerText(), "닫힌 원문은 보이는 글이 아니다").not.toContain(body.detail);
  await raw.locator("summary").click();
  await expect(raw).toContainText(body.detail);
  await expect(err(page)).not.toContainText("HTTP");
  await expect(page).toHaveURL(/\/login/);
});

test("★502(내부 주소가 든 원문) → '서버에 닿지 못했어요' · 내부 주소는 보이는 글에 없다★ · 네트워크 실패도 같은 말(원문 칸 없음)", async ({ page }) => {
  await page.route(LOGIN, (r) => r.fulfill({ status: 502, json: { error: true, detail: "백엔드에 연결할 수 없어요 (http://internal-backend:8000): ECONNREFUSED" } }));
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await fill(page);
  await page.locator(".login-submit").click();
  await expect(err(page).locator(".lg-error-say")).toHaveText("서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요.");
  const visible = await err(page).innerText();
  expect(visible).not.toContain("internal-backend");
  expect(visible).not.toContain("백엔드");
  await err(page).locator("details.lg-raw summary").click();
  await expect(err(page).locator("details.lg-raw")).toContainText("internal-backend");

  await page.unroute(LOGIN);
  await page.route(LOGIN, (r) => r.abort("connectionrefused"));
  await page.locator(".login-submit").click();
  await expect(err(page).locator(".lg-error-say")).toHaveText("서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요.");
  await expect(err(page).locator("details.lg-raw")).toHaveCount(0);
});

test("422(형식) → 사람 말 · 배열 사유는 글자로(객체 그대로 0) · 아이디는 64자에서 막힌다(서버 한도)", async ({ page }) => {
  await page.route(LOGIN, (r) => r.fulfill({ status: 422, json: { detail: [{ loc: ["body", "username"], msg: "String should have at most 64 characters", type: "string_too_long" }] } }));
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await user(page).fill("a".repeat(70));
  expect((await user(page).inputValue()).length).toBe(64);
  await pass(page).fill("x");
  await page.locator(".login-submit").click();
  await expect(err(page).locator(".lg-error-say")).toHaveText("아이디와 비밀번호를 다시 확인해 주세요.");
  await err(page).locator("details.lg-raw summary").click();
  await expect(err(page).locator("details.lg-raw")).toContainText("body.username: String should have at most 64 characters");
  await expect(err(page)).not.toContainText("[object Object]");
});

test("★요청 본문은 정확히 {username, password} · Enter 로 보낸다 · 보내는 동안 단추가 잠긴다★", async ({ page }) => {
  let seen: Request | null = null;
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  await page.route(LOGIN, async (r) => { seen = r.request(); await gate; await r.fulfill({ status: 401, json: { detail: "x" } }); });
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await fill(page, "e2e-user", "pw-123");
  await pass(page).press("Enter");
  await expect(page.locator(".login-submit")).toBeDisabled();
  await expect(page.locator(".login-submit")).toHaveText("확인하는 중이에요");
  await expect(page.locator(".lg-form")).toHaveAttribute("aria-busy", "true");
  await expect.poll(() => seen !== null).toBe(true);
  expect(JSON.parse(seen!.postData() ?? "{}")).toEqual({ username: "e2e-user", password: "pw-123" });
  expect(seen!.method()).toBe("POST");
  release();
  await expect(page.locator(".login-submit")).toBeEnabled();
  await expect(page.locator(".login-submit")).toHaveText("로그인");
});

test("성공(실제 서버 admin) + 안전한 next → 그 화면으로 · 토큰이 남는다", async ({ page }) => {
  await page.goto(`/login?next=${encodeURIComponent("/settings")}`, { waitUntil: "domcontentloaded" });
  await fill(page, "admin", "frm123!");
  await page.locator(".login-submit").click();
  await page.waitForURL(/\/settings$/);
  await expect(page.locator(".set-name")).toHaveText("admin", { timeout: 20_000 });
});

for (const bad of ["//evil.example", "https://evil.example/x", "/\\evil.example", "javascript:alert(1)"]) {
  test(`★열린 리다이렉트 없음 — next=${bad} 는 홈으로★`, async ({ page }) => {
    await okLogin(page);
    await page.goto(`/login?next=${encodeURIComponent(bad)}`, { waitUntil: "domcontentloaded" });
    await fill(page);
    await page.locator(".login-submit").click();
    await page.waitForURL(/\/dashboard$/);
    expect(new URL(page.url()).host).toBe(new URL(page.url()).host);   // 같은 앱 안
    expect(page.url()).not.toContain("evil");
  });
}

test("next 없음 → 홈(옛: 첫 화면) · 짝: 안전한 next 는 그대로 · 임시 비밀번호면 next 보다 비밀번호 칸이 먼저", async ({ page }) => {
  await okLogin(page);
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await fill(page);
  await page.locator(".login-submit").click();
  await page.waitForURL(/\/dashboard$/);

  await page.goto(`/login?next=${encodeURIComponent("/macro?tab=regime")}`, { waitUntil: "domcontentloaded" });
  await fill(page);
  await page.locator(".login-submit").click();
  await page.waitForURL(/\/macro\?tab=regime$/);

  await page.unroute(LOGIN);
  await okLogin(page, true);
  await page.goto(`/login?next=${encodeURIComponent("/macro")}`, { waitUntil: "domcontentloaded" });
  await fill(page);
  await page.locator(".login-submit").click();
  await page.waitForURL(/\/settings#password$/);
});

test("이미 로그인했으면 그렇다고 말하고 이어서 갈 곳을 준다 · 폼은 그대로(다른 계정으로 들어갈 수 있다)", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"));
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: { principal: { username: "누구", role: "analyst" }, must_change_password: false } }));
  await page.goto(`/login?next=${encodeURIComponent("/screener")}`, { waitUntil: "domcontentloaded" });
  const already = page.locator(".lg-already");
  await expect(already).toContainText("누구");
  await expect(already.locator("a")).toHaveAttribute("href", "/screener");
  await expect(user(page)).toBeVisible();
});

test("로그인 링크는 지금 화면을 next 로 넘긴다 — 프로필 카드(홈) · 설정", async ({ page }) => {
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await page.locator(".terminal-header .pf-avatar").first().click();
  await expect(page.locator(".pf-card .pf-login")).toHaveAttribute("href", "/login?next=%2Fdashboard");
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".set-signed-out a")).toHaveAttribute("href", "/login?next=%2Fsettings");
});

type MapItem = { label: string; href?: string; routes?: string[] };
type AccessMap = Record<"open" | "login" | "admin", { title: string; why?: string; items: MapItem[] }>;
const ACCESS = JSON.parse(readFileSync(path.join(__dirname, "../src/entities/session/accessMap.json"), "utf8")) as AccessMap;

test("★로그인이 여는 것 지도: 층 셋이 지도 파일 그대로 · 열린 층은 그 화면으로 가는 링크 · 관리자 층은 이유를 말한다★", async ({ page }) => {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  const map = page.locator(".lg-map");
  await expect(map).toBeVisible();
  const tiers = map.locator(".lg-tier");
  await expect(tiers).toHaveCount(3);
  expect(await tiers.evaluateAll((els) => els.map((e) => e.getAttribute("data-tier")))).toEqual(["open", "login", "admin"]);
  for (const k of ["open", "login", "admin"] as const) {
    const tier = map.locator(`.lg-tier[data-tier="${k}"]`);
    await expect(tier.locator(".lg-tier-t")).toHaveText(ACCESS[k].title);
    expect(await tier.locator(".lg-chip").allInnerTexts(), `${k} 층 항목`).toEqual(ACCESS[k].items.map((i) => i.label));
  }
  const open = await map.locator('.lg-tier[data-tier="open"] a.lg-chip').evaluateAll((els) => els.map((e) => [e.textContent, e.getAttribute("href")]));
  expect(open).toEqual(ACCESS.open.items.map((i) => [i.label, i.href]));
  await expect(map.locator('.lg-tier[data-tier="login"] a, .lg-tier[data-tier="admin"] a'), "잠긴 층은 링크가 아니다").toHaveCount(0);
  await expect(map.locator(".lg-why")).toHaveText(ACCESS.admin.why!);
  await expect(map.locator(".lg-map-cap")).toHaveText("서버의 보호 목록과 같은 내용이에요.");
});

test("★지금 이 서버 칩: 데이터 출처는 connection-status 로만 · 실행 모드는 서버 값의 번역(짝: 값이 바뀌면 문장도) · 실패는 말한다★", async ({ page }) => {
  const chip = (k: string) => page.locator(`.lg-srv .tx-chip[data-ev="${k}"]`);
  const seen = page.waitForResponse((r) => r.url().endsWith("/api/v1/live/mode"));
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  const mode = (await (await seen).json()) as { mode: string };
  expect(mode.mode, "이 환경은 그림자 모드로 시작한다").toBe("SHADOW");
  await expect(chip("mode")).toHaveText("실행 모드: 주문 없이 신호만 기록해요", { timeout: 20_000 });
  await expect(chip("data")).toHaveText("연습용 데이터");

  await page.route("**/api/v1/live/mode", (r) => r.fulfill({ json: { mode: "LIVE" } }));
  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ json: { mock_allowed: false, real_mode: true, bok_configured: true, fred_configured: true } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(chip("mode")).toHaveText("실행 모드: 실제 돈으로 주문해요", { timeout: 20_000 });
  await expect(chip("data")).toHaveText("한국은행 실데이터");
  await expect(chip("data")).toHaveAttribute("data-tone", "ok");

  await page.unroute("**/api/v1/live/mode");
  await page.route("**/api/v1/live/mode", (r) => r.fulfill({ json: { mode: "MOON" } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(chip("mode")).toHaveText("실행 모드: MOON", { timeout: 20_000 });

  await page.unroute("**/api/v1/live/mode");
  await page.route("**/api/v1/live/mode", (r) => r.fulfill({ status: 500, json: { detail: "x" } }));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(chip("mode")).toHaveText("실행 모드를 확인하지 못했어요", { timeout: 20_000 });
  await expect(chip("mode")).toHaveAttribute("data-tone", "unknown");
});

test("감속 모션이면 지도가 처음부터 다 보인다(숨는 층 없음)", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  const els = await page.locator(".lg-form, .lg-map, .lg-tier, .lg-tier-n").all();
  expect(els.length).toBeGreaterThan(6);
  for (const el of els) expect(await el.evaluate((e) => parseFloat(getComputedStyle(e).opacity))).toBeGreaterThan(0.9);
});

for (const theme of ["light", "dark"] as const) {
  test(`로그인 대비 AA (${theme}) — 실패 칸까지 · 다크면 다크`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await page.route(LOGIN, (r) => r.fulfill({ status: 401, json: { detail: "아이디 또는 비밀번호가 올바르지 않습니다." } }));
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(theme === "dark");
    await fill(page);
    await page.locator(".login-submit").click();
    await expect(err(page)).toBeVisible();
    await err(page).locator("details.lg-raw summary").click();
    const r = await page.evaluate<AuditResult>(contrastAudit(".lg"));
    expect(r.checked).toBeGreaterThan(8);
    expect(r.low, JSON.stringify(r.low)).toEqual([]);
    if (theme === "dark") expect(r.bright, "다크인데 밝은 판").toEqual([]);
  });
}

test("390 폭: 가로 넘침 없이 제목·두 칸·단추가 첫 화면에 다 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".lg h1")).toBeVisible();
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over).toBeLessThanOrEqual(1);
  const b = await page.locator(".login-submit").boundingBox();
  expect(b).not.toBeNull();
  expect(b!.y + b!.height).toBeLessThan(844);
  expect(b!.width, "주 단추는 전체 폭").toBeGreaterThan(300);
});
