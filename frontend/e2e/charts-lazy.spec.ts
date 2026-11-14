import { test, expect, type Page } from "./fixtures";

// ═══════════════════════════════════════════════════════════════════════════════
// 차트 코드는 ★화면이 뜬 뒤에★ 받는다 — 차트 화면 3곳 (2026-11-08 · 스택 최신화 뒤 4번)
// ─────────────────────────────────────────────────────────────────────────────
// 첫 화면 JS 를 재 보니 /macro·/insights·/derivatives 만 화면 고유 코드가 120~160 kB 였고, 그중 96 kB(gzip)가 차트 라이브러리(recharts)였다.
// 차트는 데이터가 온 뒤에야(파생상품은 [가격 계산하기] 뒤에야) 그려지므로, 차트 코드를 첫 화면 JS 에서 빼고 화면이 붙자마자 따로 받는다.
//   (a) 서버가 준 HTML 의 <script> 에 recharts 가 없다
//   (b) ★짝★ 그래도 차트는 실제로 그려진다 — 그 코드는 뒤에 온 요청으로 왔다("늘 빈칸" 구현 배제)
//   (c) 차트 코드를 못 받으면 차트 자리에 그렇다고 말하고, 화면의 나머지(답 문장·계산 결과)는 그대로다 — 화면 전체가 죽지 않는다
// recharts 조각은 그 안의 class 이름 문자열(`recharts-wrapper`)로 알아본다 — 조각 파일 이름은 빌드마다 바뀐다.
// ═══════════════════════════════════════════════════════════════════════════════

const MARK = "recharts-wrapper";

type Screen = {
  path: string;
  /** 차트가 나오게 하는 사용자 동작(없으면 데이터가 오면 나온다). */
  act?: (page: Page) => Promise<void>;
  /** 차트 코드를 못 받아도 보여야 하는 이 화면의 나머지(act 뒤). */
  rest: (page: Page) => Promise<void>;
};

const SCREENS: Screen[] = [
  {
    path: "/macro",
    rest: async (page) => {
      await expect(page.locator(".mc-tab").first()).toBeVisible({ timeout: 30_000 });
      await expect(page.locator(".mc .tx-answer-s")).not.toBeEmpty();   // 답 문장(서버 국면) — macro-head 스펙과 같은 자리
    },
  },
  {
    path: "/insights",
    rest: async (page) => {
      await expect(page.locator(".ca-pg-go")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText("삼성전자").first()).toBeVisible({ timeout: 30_000 });
    },
  },
  {
    path: "/derivatives",
    act: async (page) => { await page.getByRole("button", { name: "가격 계산하기" }).click(); },
    rest: async (page) => { await expect(page.locator(".dv-ans")).toBeVisible({ timeout: 30_000 }); },
  },
  {
    // 스튜디오 페이지(ADR 004 · 2026-11-10) — `StudioPanel` 이 recharts 를 직접 import 해 네 페이지의 초기 script 에 실려 있었다.
    path: "/macro/tsfm-latent",
    rest: async (page) => { await expect(page.locator(".ms-studio .ms-answer")).toBeVisible({ timeout: 30_000 }); },
  },
];

/** 서버가 준 HTML 의 <script src> 목록(같은 출처 절대 주소). */
async function initialScripts(page: Page, path: string): Promise<string[]> {
  const res = await page.request.get(path);
  expect(res.status(), `${path} HTML`).toBe(200);
  const html = await res.text();
  return [...html.matchAll(/<script[^>]+src="([^"]+\.js[^"]*)"/g)].map((m) => new URL(m[1], res.url()).href);
}

for (const s of SCREENS) {
  test(`${s.path} — (a) 첫 화면 JS 에 차트 라이브러리가 없다`, async ({ page }) => {
    const scripts = await initialScripts(page, s.path);
    expect(scripts.length, "초기 script 가 하나도 없으면 이 시험은 공허하다").toBeGreaterThan(3);
    const withCharts: string[] = [];
    for (const u of scripts) if ((await (await page.request.get(u)).text()).includes(MARK)) withCharts.push(u);
    expect(withCharts, `${s.path} 의 초기 script 중 recharts 가 든 것`).toEqual([]);
  });

  test(`${s.path} — (b) ★짝★ 차트는 실제로 그려지고, 그 코드는 뒤에 온 요청으로 왔다`, async ({ page }) => {
    const initial = new Set(await initialScripts(page, s.path));
    const late: string[] = [];
    page.on("response", async (r) => {
      if (!/\/_next\/static\/chunks\/.+\.js/.test(r.url())) return;
      try { if ((await r.text()).includes(MARK)) late.push(r.url()); } catch { /* 페이지가 닫히며 끊긴 응답 */ }
    });
    await page.goto(s.path);
    if (s.act) await s.act(page);
    await expect(page.locator(".recharts-surface").first()).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => late.length, { message: "recharts 가 든 조각을 받았어야 한다" }).toBeGreaterThan(0);
    expect(late.filter((u) => initial.has(u)), "그 조각은 첫 화면 HTML 에 없던 것이어야 한다").toEqual([]);
  });

  test(`${s.path} — (c) 차트 코드를 못 받으면 차트 자리에 그렇게 말하고, 나머지 화면은 그대로다`, async ({ page }) => {
    let cut = 0;
    await page.route("**/_next/static/chunks/**", async (route) => {
      const res = await route.fetch();
      const body = await res.text();
      if (body.includes(MARK)) { cut++; return route.abort("failed"); }
      return route.fulfill({ response: res, body });
    });
    await page.goto(s.path);
    if (s.act) await s.act(page);
    await s.rest(page);
    const fail = page.locator(".chart-slot--fail").first();
    await expect(fail).toBeVisible({ timeout: 30_000 });
    await expect(fail).toContainText("차트 로딩 실패");
    await expect(fail.getByRole("button", { name: "새로 고침" })).toBeVisible();
    expect(cut, "recharts 조각 요청을 실제로 끊었어야 한다(아니면 이 시험은 공허하다)").toBeGreaterThan(0);
    await s.rest(page);   // 화면 전체가 오류 화면으로 바뀌지 않았다
    await expect(page.locator(".recharts-surface")).toHaveCount(0);
  });
}

// ── 캔버스는 차트 라이브러리를 아예 받지 않는다 (ADR 004 · 2026-11-10) ──
// 캔버스 결과의 그림 셋(프런티어 · 시점별 노출 · 수익률 곡선)은 직접 SVG 다. 예전에는 결과 패널이 recharts 를 정적으로 실어,
// 차트를 하나도 보지 않아도 캔버스를 열기만 하면 그 조각이 왔다.
test("/allocation — 캔버스는 기본 흐름을 돌리고 결과를 열어도 recharts 조각을 받지 않는다", async ({ page }) => {
  const got: string[] = [];
  let seen = 0;
  const pending: Promise<void>[] = [];
  page.on("response", (r) => {
    if (!/\/_next\/static\/chunks\/.+\.js/.test(r.url())) return;
    seen++;
    pending.push(r.text().then((t) => { if (t.includes(MARK)) got.push(r.url()); }).catch(() => { /* 끊긴 응답 */ }));
  });
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  const done = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await done;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  await page.locator(".pg-node").first().click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await page.waitForLoadState("networkidle");
  await Promise.all(pending);
  expect(seen, "조각을 하나도 못 봤으면 이 시험은 공허하다").toBeGreaterThan(3);
  expect(got, "캔버스가 받은 조각 중 recharts 가 든 것").toEqual([]);
});
