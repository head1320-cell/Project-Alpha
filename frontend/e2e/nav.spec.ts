import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Navigation surfaces regression — locks in that Allocation Studio (AAS, module 06)
// appears on the Landing toolset + Dashboard grid, and that the shell-level breadcrumb
// renders on every tool tab. A regression (AAS dropped, breadcrumb missing) → CI red.
// ═══════════════════════════════════════════════════════════════════════════════

test("Landing: 모듈 6개와 포트폴리오 설계가 첫 화면에 있다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/", { waitUntil: "networkidle" });

  expect(await page.locator(".ld-mod").count(), "6 module rows").toBe(6);
  // BU8a — 갤러리 카드(영어 이름)가 도구 허브(다섯 도구 → 가운데 포트폴리오 설계)가 됐다. 이름은 왼쪽 메뉴와 같은 말.
  // 줄 수·주소 계약은 그대로다(그 둘이 이 스펙이 지키려던 것이다).
  await expect(page.locator(".ld-h2", { hasText: "모든 도구가 스튜디오로 이어져요" })).toBeVisible();
  const aas = page.locator(".ld-mod", { hasText: "포트폴리오 설계" });
  await expect(aas).toBeVisible();
  await expect(aas).toHaveAttribute("href", "/allocation");

  expect(uniq(sink.pageErrors), "landing page errors").toEqual([]);
});

test("Dashboard: 모듈 줄에 포트폴리오 설계가 있다 · 최상위 화면에는 브레드크럼이 없다(BU0)", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/dashboard", { waitUntil: "networkidle" });

  // BU0 — 최상위 화면은 메뉴가 "지금 어디"를 말한다. 브레드크럼은 중첩 경로에만(아래 짝 테스트).
  await expect(page.locator(".tcrumb")).toHaveCount(0);
  // AAS module row present and links to /allocation (BU1 — 한국어 이름 "포트폴리오 설계", 카드 → 목록 줄)
  const aas = page.locator(".dash-mod", { hasText: "포트폴리오 설계" }).first();
  await expect(aas).toBeVisible();
  await expect(aas).toHaveAttribute("href", "/allocation");
  // data-ingestion strip still present
  await expect(page.locator(".dash-mod-stat")).toBeVisible();

  expect(uniq(sink.pageErrors), "dashboard page errors").toEqual([]);
});

// ── BU0 · 셸 — 한국어 메뉴 · 지금 화면 표시 · 중첩에만 브레드크럼 ─────────────────────────────────────

const MENU = ["홈", "종목 찾기", "백테스트", "매크로 분석", "기업 분석", "위험 점검", "포트폴리오 설계", "내 계좌", "데이터 상태",
  "파생상품 계산기", "설정"];

test("메뉴(BU0): 한국어 이름 · 번호·고정폭 없음 · 화면마다 '지금 여기'는 정확히 하나이고 그 화면의 이름이다", async ({ page }) => {
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  const items = page.locator(".terminal-nav .nav-item");
  await expect(items).toHaveCount(MENU.length);                       // 로그인 안 됨 — 관리 메뉴 없음
  expect(await items.evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")))).toEqual(MENU);
  await expect(page.locator(".nav-number")).toHaveCount(0);
  const font = await page.locator(".terminal-nav .nav-text").first().evaluate((e) => getComputedStyle(e).fontFamily);
  expect(font, "메뉴 글자는 고정폭이 아니다").not.toMatch(/Mono|monospace/i);
  await expect(page.locator(".terminal-main .corner-mark, .terminal-main .grid-overlay")).toHaveCount(0);

  const cases: [string, string][] = [
    ["/dashboard", "홈"], ["/screener", "종목 찾기"], ["/backtest", "백테스트"], ["/macro", "매크로 분석"],
    ["/insights", "기업 분석"], ["/risk-tools", "위험 점검"], ["/allocation", "포트폴리오 설계"], ["/derivatives", "파생상품 계산기"],
    ["/macro/tsfm-latent", "매크로 분석"],                                  // 중첩도 상위 메뉴가 켜진다
  ];
  for (const [path, label] of cases) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    const cur = page.locator('.terminal-nav [aria-current="page"]');
    await expect(cur, `지금 여기 on ${path}`).toHaveCount(1);
    await expect(cur).toHaveAttribute("aria-label", label);
  }
});

test("브레드크럼(BU0): 중첩 경로에만 '상위 › 현재' — 상위는 누르면 돌아가고, 최상위에는 없다(짝)", async ({ page }) => {
  for (const path of ["/screener", "/macro", "/insights", "/allocation", "/settings"]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".terminal-nav .nav-item").first()).toBeVisible();
    await expect(page.locator(".tcrumb"), `최상위 ${path} 에는 브레드크럼이 없다`).toHaveCount(0);
  }
  await page.goto("/macro/tsfm-latent", { waitUntil: "domcontentloaded" });
  const crumb = page.locator(".tcrumb");
  await expect(crumb).toBeVisible();
  await expect(crumb.locator(".tcrumb-up")).toHaveText("매크로 분석");
  await expect(crumb.locator(".tcrumb-cur")).toHaveText("잠재 요인");
  await expect(crumb.locator(".tcrumb-cur")).toHaveAttribute("aria-current", "page");
  // 브레드크럼은 본문 첫 제목을 덮지 않는다 — 상자가 null 이면 이 비교는 공허하다, 그래서 먼저 단언한다.
  const a = await crumb.boundingBox();
  const h = await page.locator(".terminal-main h1").first().boundingBox();
  expect(a, "브레드크럼 상자").not.toBeNull();
  expect(h, "본문 제목 상자").not.toBeNull();
  expect(intersects(a, h), "브레드크럼이 본문 제목과 겹친다").toBe(false);
  await crumb.locator("a.tcrumb-up").click();
  await expect(page).toHaveURL(/\/macro$/);
  await expect(page.locator(".tcrumb")).toHaveCount(0);
});

// The breadcrumb box comparison helper (bbox 가 null 이면 false — 그래서 호출 전에 null 이 아님을 단언한다).
const intersects = (a: { x: number; y: number; width: number; height: number } | null, b: typeof a) =>
  !!a && !!b && !(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y);

test("관리 메뉴(BU0): 관리자에게만 보인다 — 분석가·로그인 안 됨에는 없다(짝)", async ({ page }) => {
  const TOKEN_KEY = "project-alpha.auth-token";
  let role = "analyst";
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ status: 200,
    json: { principal: { username: "누구", role }, secret_state: "configured", secret_reason: null, admin_password_state: "set" } }));
  await page.addInitScript((k) => localStorage.setItem(k, "t-nav"), TOKEN_KEY);
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.locator('.terminal-header .pf-avatar[data-state="signed_in"]')).toBeVisible();
  await expect(page.locator('.terminal-nav a[href="/admin/live-trading"]')).toHaveCount(0);
  role = "admin";
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator('.terminal-header .pf-avatar[data-state="signed_in"]')).toBeVisible();
  for (const [href, label] of [["/admin/live-trading", "실거래"], ["/admin/multi-backtest", "여러 전략 백테스트"], ["/admin/realism", "현실성 점검"]]) {
    await expect(page.locator(`.terminal-nav a[href="${href}"]`)).toHaveAttribute("aria-label", label);
  }
});

test("Shell header(BR R3): 오른쪽 슬롯은 회원 프로필 동그라미 — 국면 배지는 없다(국면은 /macro) · 모든 탭에서 같다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

  // 셸 헤더의 우측 슬롯 — BR R3 에서 국면 배지를 빼고 회원 프로필로 바꿨다(사용자 결정).
  const slot = page.locator(".terminal-header .header-actions");
  await expect(slot).toBeVisible();
  await expect(slot.locator(".pf-avatar")).toBeVisible();
  // 짝 — 예전 계약(국면 배지 = /macro 링크)이 머리 줄에 남아 있지 않다.
  await expect(slot.locator('a[href="/macro"]')).toHaveCount(0);
  await expect(slot.locator(".skeleton")).toHaveCount(0);

  // 셸에 붙었으므로 다른 탭에서도 같다 · 국면은 /macro 화면에 그대로 있다.
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".terminal-header .header-actions .pf-avatar")).toBeVisible();
  await expect(page.locator('.terminal-header .header-actions a[href="/macro"]')).toHaveCount(0);

  expect(uniq(sink.pageErrors), "shell header page errors").toEqual([]);
  expect(uniq([...sink.api404, ...sink.apiOther4xx5xx]), "토큰이 없으면 /auth/me 도 부르지 않는다 — 4xx/5xx 없음").toEqual([]);
});

test("S1d: 셸 크롬(헤더·사이드바)의 모든 포커스 대상이 앱 포커스 링을 받는다", async ({ page }) => {
  await page.goto("/dashboard", { waitUntil: "networkidle" });
  await expect(page.locator(".terminal-nav .nav-item").first()).toBeVisible();

  const targets = page.locator(
    ".terminal-header a, .terminal-header button, .terminal-sidebar a, .terminal-sidebar button",
  );
  const n = await targets.count();
  // 크롬 자체가 사라지면 0개가 되고 아래 루프가 통째로 비어 통과한다 — 그래서 먼저 센다.
  // 브랜드 1 + 레일 토글 1 + 메뉴 11(BU0 파생·설정 · BV9 내 계좌) = 13 이지만 하한은 12 그대로(+ 프로필 동그라미 1 — BR R3).
  expect(n, "셸 크롬의 포커스 대상 수").toBeGreaterThanOrEqual(12);

  const bare: string[] = [];
  for (let i = 0; i < n; i++) {
    const el = targets.nth(i);
    await el.focus();
    const seen = await el.evaluate((e) => {
      const c = getComputedStyle(e);
      return { w: c.outlineWidth, s: c.outlineStyle, c: c.outlineColor,
               tag: e.tagName, cls: (e.getAttribute("class") || "").slice(0, 40) };
    });
    // UA 기본값은 "1px auto rgb(16,16,16)" 로 떨어진다 — 앱 링은 2px solid 액센트다.
    if (seen.s !== "solid" || parseFloat(seen.w) < 2) {
      bare.push(`${seen.tag}.${seen.cls} → ${seen.w} ${seen.s} ${seen.c}`);
    }
  }
  expect(bare, "포커스 링이 없는 셸 크롬 요소").toEqual([]);
});
