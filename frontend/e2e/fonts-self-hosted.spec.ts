import { test, expect, type Page } from "./fixtures";

// ═══════════════════════════════════════════════════════════════════════════════
// 글꼴은 ★같은 서버에서★ 준다 — 외부 글꼴 서버 요청 0 (2026-11-08)
// ─────────────────────────────────────────────────────────────────────────────
// Pretendard 는 처음부터 npm 으로 넣었다(ADR-003 · "외부 CDN 없음"). 그런데 숫자·티커용 JetBrains Mono 는 globals.css 첫 줄의
// Google Fonts `@import` 로 남아 있었다 — 화면마다 외부 요청이 하나 더 생기고, 외부가 막힌 사내망(PB 데스크톱)에서는 숫자 글꼴이 대체 글꼴로
// 바뀐다. 이제 npm(@fontsource-variable/jetbrains-mono)의 파일을 next/font/local 로 같은 서버에서 준다.
// 짝: "외부 요청 0" 만 보면 글꼴을 아예 빼도 통과한다 — 고정폭 숫자가 ★실제로 그 글꼴로 그려지는지★까지 본다.
// ═══════════════════════════════════════════════════════════════════════════════

const EXTERNAL_FONT = /fonts\.(googleapis|gstatic)\.com/;

async function openWatching(page: Page, path: string) {
  const external: string[] = [];
  const woff2: { url: string; status: number }[] = [];
  page.on("request", (r) => { if (EXTERNAL_FONT.test(r.url())) external.push(r.url()); });
  page.on("response", (r) => { if (/\.woff2(\?|$)/.test(r.url())) woff2.push({ url: r.url(), status: r.status() }); });
  await page.goto(path);
  await page.waitForLoadState("networkidle");
  return { external, woff2 };
}

test("외부 글꼴 서버로 가는 요청이 없다 — 여러 화면", async ({ page }) => {
  for (const path of ["/", "/screener", "/backtest", "/allocation"]) {
    const { external } = await openWatching(page, path);
    expect(external, `${path} 에서 외부 글꼴 요청`).toEqual([]);
  }
});

test("★짝★ 고정폭 글꼴 자리(종목코드 .scr-code)는 같은 서버에서 받은 JetBrains Mono 로 그려진다", async ({ page }) => {
  // `.num` 은 화면마다 다른 글꼴 규칙이 덮어써 Pretendard 로 그려지는 곳이 많다 — `var(--t-mono)` 를 그대로 쓰는 종목코드 칸을 본다.
  const { woff2 } = await openWatching(page, "/screener");
  const num = page.locator(".scr-code").first();
  await expect(num).toBeVisible({ timeout: 30_000 });
  const r = await num.evaluate(async (el) => {
    await document.fonts.ready;
    const unq = (x: string) => x.trim().replace(/^["']|["']$/g, "");
    const fam = getComputedStyle(el).fontFamily;
    const first = unq(fam.split(",")[0]);
    const loaded = [...document.fonts].some((f) => unq(f.family) === first && f.status === "loaded");
    // 그 글꼴의 @font-face 를 ★우리 스타일시트에서★ 찾는다 — 다른 출처(Google) CSS 는 규칙을 읽을 수 없어 여기서 빠진다.
    const srcs: string[] = [];   // 이미 절대 주소로 — 상대 url() 은 ★그 스타일시트 기준★이다(페이지 기준이 아니라)
    const ranges: string[] = [];
    const walk = (rules: CSSRuleList, base: string) => {
      for (const rule of Array.from(rules)) {
        if (rule instanceof CSSFontFaceRule && unq(rule.style.getPropertyValue("font-family")) === first) {
          const src = rule.style.getPropertyValue("src");
          srcs.push(...[...src.matchAll(/url\(["']?([^"')]+)["']?\)/g)].map((m) => new URL(m[1], base).href));
          ranges.push(rule.style.getPropertyValue("unicode-range") || "U+0-10FFFF");   // 없으면 전 범위
        }
        else if ("cssRules" in rule) { try { walk((rule as CSSGroupingRule).cssRules, base); } catch { /* 다른 출처 */ } }
      }
    };
    for (const sh of Array.from(document.styleSheets)) { try { walk(sh.cssRules, sh.href ?? location.href); } catch { /* 다른 출처 시트 */ } }
    const urls = srcs;
    const covers = (cp: number) => ranges.some((r) => r.split(",").some((part) => {
      const m = part.trim().match(/^u\+([0-9a-f]+)(?:-([0-9a-f]+))?$/i);
      return !!m && cp >= parseInt(m[1], 16) && cp <= parseInt(m[2] ?? m[1], 16);
    }));
    return { fam, first, loaded, urls, ranges: ranges.length, latin: covers(0x30), greek: covers(0x3c3) };
  });
  expect(r.loaded, `'${r.first}'(${r.fam}) 을 실제로 받아 썼어야 한다`).toBe(true);
  expect(r.first, "고정폭 자리의 첫 글꼴이 JetBrains Mono 계열이어야 한다").toMatch(/jetbrains|localFont/i);
  expect(r.urls.length, `'${r.first}' 의 @font-face 를 같은 서버 스타일시트에서 찾지 못했다`).toBeGreaterThan(0);
  const origin = new URL(page.url()).origin;
  expect(r.urls.every((u) => u.startsWith(origin)), `글꼴 파일이 같은 서버에 있어야 한다: ${r.urls}`).toBe(true);
  expect(woff2.some((w) => r.urls.includes(w.url) && w.status === 200), `그 파일을 실제로 받았어야 한다: ${JSON.stringify(woff2)}`).toBe(true);
  // 예전 Google 글꼴처럼 글자 범위별로 나뉘어 있어야 한다 — 라틴만 남기면 화면의 σ·β·μ(고정폭 자리)가 대체 글꼴로 바뀐다.
  expect(r.latin, "숫자(라틴)가 그 글꼴 범위 안").toBe(true);
  expect(r.greek, `그리스 글자(σ)도 그 글꼴 범위 안이어야 한다 — @font-face ${r.ranges}개`).toBe(true);
});
