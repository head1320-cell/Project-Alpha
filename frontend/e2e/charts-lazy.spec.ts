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
    path: "/derivatives",
    act: async (page) => { await page.getByRole("button", { name: "가격 계산하기" }).click(); },
    rest: async (page) => { await expect(page.locator(".dv-ans")).toBeVisible({ timeout: 30_000 }); },
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
    await expect(fail).toContainText("차트를 불러오지 못했어요");
    await expect(fail.getByRole("button", { name: "새로 고침" })).toBeVisible();
    expect(cut, "recharts 조각 요청을 실제로 끊었어야 한다(아니면 이 시험은 공허하다)").toBeGreaterThan(0);
    await s.rest(page);   // 화면 전체가 오류 화면으로 바뀌지 않았다
    await expect(page.locator(".recharts-surface")).toHaveCount(0);
  });
}
