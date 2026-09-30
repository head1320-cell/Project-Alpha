import { test, expect, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { freezeCharts, stubCompletedRun, STUB_RUN_ID } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BS5 — 7개 모듈 다크 (설계 docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md §BS5)
// ─────────────────────────────────────────────────────────────────────────────
// ① ★라이트는 한 픽셀도 바뀌지 않는다★ — 다크를 입히기 **전에** 라이트 계산 스타일(글자·바탕·테두리·SVG 칠)을
//    `golden/light-styles.json` 에 얼렸다. 요소 종류(태그+클래스)마다 본 스타일 조합의 집합이 같아야 한다.
//    다시 얼리기: UPDATE_LIGHT_GOLDEN=1 (다크 작업 전 커밋에서만 — 그 뒤에 얼리면 증거가 아니다).
// ═══════════════════════════════════════════════════════════════════════════════

const ROUTES = ["/dashboard", "/screener", "/backtest", "/macro", "/macro/agentic-mcp", "/macro/causal-deepm",
  "/macro/neural-sde", "/macro/pinn-tail", "/macro/tsfm-latent", "/insights", "/risk-tools", "/admin/data", "/derivatives"];

const GOLDEN = path.join(__dirname, "golden", "light-styles.json");

async function openModule(page: Page, route: string) {
  await freezeCharts(page);
  await page.goto(route, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".terminal-main")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(3_000);   // 위젯 마운트 + 첫 데이터(module-motion 과 같은 기다림)
  // 요소 수가 1.5초 동안 그대로일 때까지(최대 20초) — /macro 는 병렬 실행에서 3초 뒤에도 절반쯤만 그려져 있었다.
  let last = -1, same = 0;
  for (let i = 0; i < 40 && same < 3; i++) {
    const n = await page.evaluate(() => document.querySelectorAll(".terminal-main *").length);
    same = n === last ? same + 1 : 0; last = n;
    await page.waitForTimeout(500);
  }
}

/** 보이는 요소마다 `태그.클래스 | 글자 | 바탕 | 위·아래 테두리 | 칠 | 선` — 종류별 집합(순서·개수 무관). */
function styleSet(page: Page): Promise<Record<string, string[]>> {
  return page.evaluate(() => {
    const out: Record<string, Set<string>> = {};
    for (const el of document.querySelectorAll<HTMLElement | SVGElement>(".terminal-root, .terminal-root *")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      const cls = (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean).sort().slice(0, 4).join(".");
      const key = `${el.tagName.toLowerCase()}.${cls}`;
      const v = [cs.color, cs.backgroundColor, cs.borderTopColor, cs.borderBottomColor, cs.fill, cs.stroke, cs.backgroundImage === "none" ? "" : cs.backgroundImage].join("|");
      (out[key] ??= new Set()).add(v);
    }
    return Object.fromEntries(Object.entries(out).map(([k, s]) => [k, [...s].sort()]));
  });
}

test.describe("라이트 계산 스타일 골든(BS5)", () => {
  for (const route of ROUTES) {
    test(`라이트 그대로: ${route}`, async ({ page }) => {
      await openModule(page, route);
      const got = await styleSet(page);
      expect(Object.keys(got).length, "잰 요소 종류가 너무 적다").toBeGreaterThan(10);
      if (process.env.UPDATE_LIGHT_GOLDEN === "1") {
        const all = fs.existsSync(GOLDEN) ? JSON.parse(fs.readFileSync(GOLDEN, "utf8")) : {};
        all[route] = got;
        fs.writeFileSync(GOLDEN, JSON.stringify(all, null, 1) + "\n");
        return;
      }
      const want = JSON.parse(fs.readFileSync(GOLDEN, "utf8"))[route] as Record<string, string[]>;
      // ★새 스타일 조합이 생기면 실패★ — 라이트 색이 바뀌면 골든에 없던 조합이 나온다. 데이터가 늦게 와서 일부 요소가
      // 덜 그려진 것(조합이 빠진 것)은 바뀐 것이 아니다(실측: /macro 는 실행마다 그린 요소 수가 202~321 로 달랐다).
      const changed = Object.keys(got).filter((k) => k in want)
        .map((k) => ({ k, extra: got[k].filter((v) => !want[k].includes(v)) })).filter((x) => x.extra.length);
      expect(changed, `${route} 라이트 스타일이 바뀌었다`).toEqual([]);
      const seen = Object.keys(want).filter((k) => k in got).length;
      expect(seen / Object.keys(want).length, `${route} 골든의 요소 종류를 너무 적게 봤다 — 비교가 성립하지 않는다`).toBeGreaterThan(0.6);
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ② ★다크는 주요 상태 전부에서 AA★ — 실제 경로로 켠다(저장된 테마 dark → `DARK_READY` 화면에서만 html.dark).
//    규칙(WCAG 2.x): 글자 대비 4.5:1(큰 글씨 3:1) · SVG 글자는 fill 로 잰다 · 비활성 조작부는 제외(1.4.3 예외).
//    밝은 **판** 금지 — 글자를 품었거나 48×48 이상인 밝은 바탕. 계열색 막대·범례 칸·스위치 손잡이는 판이 아니다.
// ═══════════════════════════════════════════════════════════════════════════════

type Issue = string;
async function darkIssues(page: Page): Promise<Issue[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const lum = (c: string) => {
      const m = c.match(/\d+(\.\d+)?/g); if (!m) return 0;
      const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(+m[0]) + 0.7152 * f(+m[1]) + 0.0722 * f(+m[2]);
    };
    const solid = (c: string) => { const m = c.match(/rgba?\(([^)]*)\)/); if (!m) return false; const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number); return p.length < 4 || p[3] > 0.5; };
    const bgOf = (el: Element | null): string => {
      for (let n = el; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; if (solid(c)) return c; }
      return "rgb(255, 255, 255)";
    };
    const tag = (el: Element) => `${el.tagName.toLowerCase()}.${(el.getAttribute("class") ?? "").split(/\s+/).slice(0, 2).join(".")}`;
    for (const el of document.querySelectorAll<HTMLElement>(".terminal-root *, body > [role='dialog'] *")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const text = Array.from(el.childNodes).some((n) => n.nodeType === 3 && (n.textContent ?? "").trim());
      if (solid(cs.backgroundColor) && lum(cs.backgroundColor) > 0.6 && ((r.width >= 48 && r.height >= 48) || (el.textContent ?? "").trim()))
        out.push(`밝은 판 ${tag(el)} ${cs.backgroundColor}`);
      if (!text || el.closest("[disabled],[aria-disabled='true']")) continue;
      const svg = el instanceof SVGElement;
      const fg = svg ? cs.fill : cs.color;
      if (!fg || fg === "none") continue;
      const a = lum(fg), b = lum(bgOf(svg ? el.closest("svg")?.parentElement ?? null : el));
      const q = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const px = parseFloat(cs.fontSize), big = px >= 24 || (px >= 18.66 && parseInt(cs.fontWeight, 10) >= 700);
      if (q < (big ? 3 : 4.5)) out.push(`대비 ${q.toFixed(2)}:1 ${tag(el)} ${fg} "${(el.textContent ?? "").trim().slice(0, 16)}"`);
    }
    return [...new Set(out)];
  });
}

async function openDark(page: Page, route: string) {
  await page.addInitScript(() => localStorage.setItem("alpha_theme", "dark"));
  await openModule(page, route);
  expect(await page.evaluate(() => document.documentElement.classList.contains("dark")), `${route} 에서 다크가 켜진다`).toBe(true);
}

type State = { name: string; route: string; act?: (page: Page) => Promise<void> };
const STATES: State[] = [
  ...ROUTES.map((route) => ({ name: route, route })),
  { name: "스크리너 · 팩터 고르기", route: "/screener", act: async (p) => { await p.locator(".bsc-add-btn").first().click(); } },
  { name: "백테스터 · 팩터 고르기", route: "/backtest", act: async (p) => { await p.getByRole("button", { name: /^팩터$/ }).first().click(); } },
  { name: "백테스터 · 매도 조건", route: "/backtest", act: async (p) => { await p.locator(".tbt-mode").nth(1).click(); } },
  { name: "백테스터 · 유니버스", route: "/backtest", act: async (p) => { await p.locator(".tbt-mode").nth(2).click(); } },
  { name: "기업 · 분석 뒤", route: "/insights", act: async (p) => { const go = p.locator(".ca-pg-go").first(); if (await go.count()) await go.click(); } },
  ...[1, 2, 3, 4, 5, 6, 7].map((i) => ({ name: `매크로 · 탭 ${i + 1}`, route: "/macro",
    act: async (p: Page) => { await p.locator(".mc-tabs .mc-tab").nth(i).click(); } })),
];

test.describe("다크 AA(BS5)", () => {
  for (const s of STATES) {
    test(`다크: ${s.name}`, async ({ page }) => {
      await openDark(page, s.route);
      if (s.act) { await s.act(page); await page.waitForTimeout(2_500); }
      const issues = await darkIssues(page);
      expect(issues, `${s.name} 다크 결함`).toEqual([]);
    });
  }

  test("다크: 백테스트 진행·비교 화면(스텁 실행)", async ({ page }) => {
    await stubCompletedRun(page);
    for (const sub of ["loading", "compare"]) {
      await openDark(page, `/backtest/runs/${STUB_RUN_ID}/${sub}`);
      expect(await darkIssues(page), `${sub} 다크 결함`).toEqual([]);
    }
  });

  test("짝: 다크를 골라도 첫 화면은 밝다 · 다크를 고르지 않으면 모듈도 밝다", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("alpha_theme", "dark"));
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1_500);
    expect(await page.evaluate(() => document.documentElement.classList.contains("dark")), "첫 화면(예외)").toBe(false);
    const light = await page.context().newPage();
    await light.goto("/screener", { waitUntil: "domcontentloaded" });
    await light.evaluate(() => localStorage.setItem("alpha_theme", "light"));
    await light.reload({ waitUntil: "domcontentloaded" });
    await expect(light.locator(".terminal-main")).toBeVisible({ timeout: 20_000 });
    expect(await light.evaluate(() => document.documentElement.classList.contains("dark")), "라이트를 고르면 모듈도 밝다").toBe(false);
  });
});
