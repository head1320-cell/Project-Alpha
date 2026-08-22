import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// Navigation surfaces regression — locks in that Allocation Studio (AAS, module 06)
// appears on the Landing toolset + Dashboard grid, and that the shell-level breadcrumb
// renders on every tool tab. A regression (AAS dropped, breadcrumb missing) → CI red.
// ═══════════════════════════════════════════════════════════════════════════════

test("Landing: 모듈 갤러리에 6개 카드와 Allocation Studio 가 있다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/", { waitUntil: "networkidle" });

  expect(await page.locator(".lp-module").count(), "6 gallery cards").toBe(6);
  await expect(page.locator(".lp-module", { hasText: "Allocation Studio" })).toBeVisible();
  // L1 에서 랜딩이 갤러리로 바뀌며 섹션 라벨이 "01 — 06" → "SIX SURFACES · ONE RECORD" 가 됐다.
  // 카드 수·href 계약은 그대로다(그 둘이 이 스펙이 지키려던 것이다).
  await expect(page.locator(".lp-section-head").getByText("RESEARCH MODULES")).toBeVisible();
  // the AAS column links to /allocation
  await expect(page.locator(".lp-module", { hasText: "Allocation Studio" })).toHaveAttribute("href", "/allocation");

  expect(uniq(sink.pageErrors), "landing page errors").toEqual([]);
});

test("Dashboard: module grid shows Allocation card + a breadcrumb bar", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/dashboard", { waitUntil: "networkidle" });

  // breadcrumb (shell-level) is present and names the module
  await expect(page.locator(".tcrumb")).toBeVisible();
  await expect(page.locator(".tcrumb")).toContainText("PROJECT ALPHA");
  // AAS module card present and links to /allocation
  const aas = page.locator(".dash-mod", { hasText: "Allocation" }).first();
  await expect(aas).toBeVisible();
  await expect(aas).toHaveAttribute("href", "/allocation");
  // data-ingestion strip still present
  await expect(page.locator(".dash-mod-stat")).toBeVisible();

  expect(uniq(sink.pageErrors), "dashboard page errors").toEqual([]);
});

test("Breadcrumb renders with the correct module on each tool tab", async ({ page }) => {
  const cases: [string, string][] = [
    ["/screener", "Screener"], ["/backtest", "Backtester"], ["/macro", "Macro Analysis"],
    ["/insights", "Company Analysis"], ["/risk-tools", "Risk Analysis"], ["/allocation", "Allocation Studio"],
  ];
  for (const [path, label] of cases) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    const cur = page.locator(".tcrumb-cur").first();
    await expect(cur, `crumb on ${path}`).toBeVisible();
    await expect(cur).toContainText(label);
  }
});

// The breadcrumb must not overlap a tab's own top toolbar (Company search / Screener universe).
const intersects = (a: { x: number; y: number; width: number; height: number } | null, b: typeof a) =>
  !!a && !!b && !(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y);

test("Breadcrumb does not overlap the tab top toolbar (Company + Screener)", async ({ page }) => {
  for (const path of ["/insights", "/screener"]) {
    await page.goto(path, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    const crumb = await page.locator(".tcrumb").boundingBox();
    const toolbar = await page.locator(".t-toolbar").first().boundingBox();
    expect(intersects(crumb, toolbar), `crumb/toolbar overlap on ${path}`).toBe(false);
  }
  // the Company 분석 button (in the toolbar) is visible/clickable, not covered
  await page.goto("/insights", { waitUntil: "networkidle" });
  await expect(page.locator(".ca-pg-go")).toBeVisible();
});

test("Shell header: RegimeBadge loads real regime data and links to /macro", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

  // 셸 헤더의 우측 슬롯 — 삭제된 TopNav 에 있던 것을 TerminalShell 로 옮겼다.
  const slot = page.locator(".terminal-header .header-actions");
  await expect(slot).toBeVisible();

  // 배지는 macroApi.regime() 이 돌아오기 전까지 .skeleton 을 렌더한다.
  // 로딩 상태로 굳지 않고 실제 데이터로 바뀌는 것까지 확인한다 — 이게 이 테스트의 핵심이다.
  const badge = slot.locator('a[href="/macro"]');
  await expect(badge).toBeVisible({ timeout: 20_000 });
  await expect(slot.locator(".skeleton")).toHaveCount(0);

  // regime 라벨 + stress 점수(정수)가 함께 표시된다
  await expect(badge).toHaveAttribute("title", /Stress\s+\d+\s*\/\s*100/);
  expect((await badge.innerText()).trim().length, "배지에 텍스트가 있어야 한다").toBeGreaterThan(0);

  // 셸에 붙었으므로 다른 탭에서도 나와야 한다
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  await expect(page.locator('.terminal-header .header-actions a[href="/macro"]')).toBeVisible({ timeout: 20_000 });

  expect(uniq(sink.pageErrors), "regime badge page errors").toEqual([]);
  expect(uniq([...sink.api404, ...sink.apiOther4xx5xx]), "regime 조회가 4xx/5xx 면 안 된다").toEqual([]);
});

test("AAS Timing gauge value does not overlap the composite label", async ({ page }) => {
  await page.goto("/allocation/timing", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  const gaugeNum = await page.locator(".as-gauge-c b").first().boundingBox().catch(() => null);
  const label = await page.locator(".as-tm-mkt-lab").first().boundingBox().catch(() => null);
  // if the composite section rendered, the big number and the label must not intersect
  if (gaugeNum && label) expect(intersects(gaugeNum, label), "gauge value overlaps label").toBe(false);
});

// ═══════════════════════════════════════════════════════════════════════════════
// S1d — 셸 크롬의 키보드 포커스 링
// ─────────────────────────────────────────────────────────────────────────────
// globals.css 의 포커스 링 규칙은 원래 .terminal-main 한정이었다. 헤더와 사이드바는
// 그 밖에 있어서 앱 크롬의 인터랙티브 요소가 전부 UA 기본 outline(1px auto)로 떨어졌다.
// 탭 순서상 앞쪽 전체가 "지금 어디에 있는지" 안 보이는 구간이었다는 뜻이다.
//
// ★샘플이 아니라 전수로 센다★ .first() 하나만 보면 나머지 10개가 벗겨져도 초록이다.
// 이 세션에서 세 번 겪은 '아무것도 안 지키는 초록'이 정확히 그 모양이었다.
// ═══════════════════════════════════════════════════════════════════════════════

test("S1d: 셸 크롬(헤더·사이드바)의 모든 포커스 대상이 앱 포커스 링을 받는다", async ({ page }) => {
  await page.goto("/dashboard", { waitUntil: "networkidle" });
  await expect(page.locator(".terminal-nav .nav-item").first()).toBeVisible();

  const targets = page.locator(
    ".terminal-header a, .terminal-header button, .terminal-sidebar a, .terminal-sidebar button",
  );
  const n = await targets.count();
  // 크롬 자체가 사라지면 0개가 되고 아래 루프가 통째로 비어 통과한다 — 그래서 먼저 센다.
  // 브랜드 1 + 레일 토글 1 + 네비 8 = 10 이 하한. 국면 배지는 API 응답에 달려 있어 뺐다.
  expect(n, "셸 크롬의 포커스 대상 수").toBeGreaterThanOrEqual(10);

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
