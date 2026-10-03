import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * BU5b-1 · 매크로 분석 탭 안 카드 — 개요·지표·국면·가치 (계획 "BU5b 상세")
 * 거는 것(짝으로 항상-통과·항상-침묵을 배제):
 *  · ★시각화 보존★ 탭마다 그림 수(차트 svg · 격자 칸 · 막대) ≥ 바꾸기 전 화면에서 잰 값 — 그림을 지우면 빨강(사용자 상시 규칙 2)
 *  · 글: 보이는 em-dash 0 · 영어 열거값·꼬리표(Goldilocks·STRESS·CAUTIOUS·mock…) 0 · `title` 툴팁 0 · 카드 제목 17/700 대문자 없음 ·
 *    고정폭은 티커(`[data-mono]`)에만. 서버가 쓴 설명 문장(`[data-server]`)은 손대지 않으므로 글 검사에서 뺀다.
 *  · 색의 뜻 넷: 등락(지표 전월비) = 빨강/파랑 + 부호 · 수준(z·백분위) = 주황/청록 양쪽 색(등락색 아님) ·
 *    판단(공격/방어·자산 틸트·스트레스) = 값이 달라도 같은 색 · 국면 = `--mc-q-*`
 *  · 읽기 줄: 히트맵 칸에 초점 → 아래 한 줄이 그 칸의 지표·값을 말한다(짝: 다른 칸 → 다른 글)
 *  · 지연 로더 넷 + 드릴다운: 500 → 그 카드 안 alert + [다시 시도] → 풀면 그림(짝: 정상 alert 0) · 축 분해 실패에도 카드가 남는다
 *  · 탭마다 AA 라이트/다크 · 다크 밝은 판 0 · 390 넘침 0
 */

const TABS = ["overview", "indicators", "regime", "valuation"] as const;
type Tab = (typeof TABS)[number];
const panel = (p: Page, t: Tab) => p.locator(`#mc-panel-${t}`);

// 바꾸기 전 화면(BU5a+ `1b2efc0`, mock 데이터)에서 잰 그림 수 — 줄이면 빨강. (RECORD_VIZ=1 로 다시 잴 수 있다)
const VIZ_MIN: Record<Tab, { svg: number; cells: number; bars: number }> = {
  overview: { svg: 5, cells: 24, bars: 0 },
  indicators: { svg: 25, cells: 25, bars: 25 },
  regime: { svg: 7, cells: 108, bars: 16 },
  valuation: { svg: 0, cells: 180, bars: 6 },
};

const WAIT_FOR: Record<Tab, string[]> = {
  overview: ["/api/v1/macro/compare-krus"],
  indicators: ["/api/v1/macro/cb-sentiment"],
  regime: ["/api/v1/macro/regime-trajectory", "/api/v1/macro/cycle-strips", "/api/v1/macro/axis-history"],
  valuation: ["/api/v1/macro/asset-strips"],
};

async function open(page: Page) {
  await page.goto("/macro", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc, .mc-err")).toBeVisible({ timeout: 30_000 });
}
async function goTab(page: Page, t: Tab, { settle = true } = {}) {
  const waits = settle ? WAIT_FOR[t].map((u) => page.waitForResponse((r) => r.url().includes(u), { timeout: 30_000 }).catch(() => null)) : [];
  if (t !== "overview") await page.locator(`#mc-tab-${t}`).click();
  await expect(panel(page, t)).toBeVisible();
  await Promise.all(waits);
  if (settle) await page.waitForTimeout(900);
}
async function patch(page: Page, path: string, edit: (b: Record<string, unknown>) => void) {
  await page.route(`**/api/v1/macro/${path}`, async (route: Route) => {
    const res = await route.fetch();
    const b = (await res.json()) as Record<string, unknown>;
    edit(b);
    await route.fulfill({ response: res, json: b });
  });
}
const tokenColor = (p: Page, name: string, prop: "color" | "backgroundColor" = "color") => p.evaluate(([n, pr]) => {
  const el = document.createElement("span");
  if (pr === "color") el.style.color = `var(${n})`; else el.style.backgroundColor = `var(${n})`;
  document.querySelector(".mc")!.appendChild(el);
  const c = getComputedStyle(el)[pr as "color"]; el.remove(); return c;
}, [name, prop] as const);

const vizCount = (p: Page, t: Tab) => panel(p, t).evaluate((root) => ({
  svg: root.querySelectorAll("svg:not(.lucide)").length,
  cells: root.querySelectorAll(".mc-heat-cell, .mv-strip-cells > *, .mv-cmp tbody td").length,
  bars: root.querySelectorAll(".mc-zbar, .mc-pb-track, .mc-sc-bar, .mc-tilt-track, .mc-ind-pct, .mc-cbg-track").length,
}));

// ── 시각화 보존 ─────────────────────────────────────────────────────────────
for (const t of TABS) {
  test(`그림 수 보존 — ${t} (바꾸기 전 화면 이상)`, async ({ page }) => {
    await open(page);
    await goTab(page, t);
    const n = await vizCount(page, t);
    if (process.env.RECORD_VIZ) console.log(`VIZ ${t} ${JSON.stringify(n)}`);
    expect(n.svg, "차트 svg").toBeGreaterThanOrEqual(VIZ_MIN[t].svg);
    expect(n.cells, "격자 칸").toBeGreaterThanOrEqual(VIZ_MIN[t].cells);
    expect(n.bars, "막대").toBeGreaterThanOrEqual(VIZ_MIN[t].bars);
    expect(n.svg + n.cells + n.bars, "그림이 하나도 없으면 비교가 공허하다").toBeGreaterThan(0);
  });
}

// ── 글 ──────────────────────────────────────────────────────────────────────
const BANNED_EN = /\b(Goldilocks|Reflation|Stagflation|Disinflation|GOLDILOCKS|REFLATION|STAGFLATION|DISINFLATION|REFLATE|STAGFLATE|DISINFLATE|GOLD|REFL|STAG|DISI|STRESS|CAUTIOUS|NORMAL|DEFENSIVE|mock|MOCK|Z-Score|Sentiment|Central Bank|Kill ?Switch|Valuation|YoY|FRED|ECOS|DART|growth_stocks|value_stocks|bonds|commodities|cash)\b/;

for (const t of TABS) {
  test(`글 — ${t}: em-dash 0 · 영어 열거값 0 · 툴팁 0 · 제목 17/700 대문자 없음 · 고정폭은 티커만`, async ({ page }) => {
    await open(page);
    await goTab(page, t);
    const r = await panel(page, t).evaluate((root) => {
      const texts: string[] = [];
      const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let n: Node | null;
      const mono: string[] = [];
      while ((n = walk.nextNode())) {
        const el = n.parentElement!;
        const s = (n.textContent ?? "").trim();
        if (!s) continue;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden" || !el.getClientRects().length) continue;
        if (el.closest(".sr-only")) continue;
        if (!el.closest("[data-server]")) texts.push(s);
        if (/mono/i.test(cs.fontFamily) && !el.closest("[data-mono]")) mono.push(s.slice(0, 24));
      }
      const heads = Array.from(root.querySelectorAll(".mc-card-h")).map((h) => {
        const cs = getComputedStyle(h);
        return { tt: cs.textTransform, fs: cs.fontSize, fw: cs.fontWeight };
      });
      return {
        texts, mono,
        // 차트 라이브러리가 넣는 빈 <title> 은 툴팁을 띄우지 않는다 — 글자가 있는 것만 센다.
        titles: Array.from(root.querySelectorAll("[title]")).filter((e) => e.getAttribute("title")?.trim()).length
          + Array.from(root.querySelectorAll("svg title")).filter((e) => e.textContent?.trim()).length,
        heads,
      };
    });
    const dash = r.texts.filter((s) => s.includes("—"));
    expect(dash, "보이는 em-dash").toEqual([]);
    const en = r.texts.filter((s) => BANNED_EN.test(s));
    expect(en, "영어 열거값·꼬리표").toEqual([]);
    expect(r.titles, "title 툴팁").toBe(0);
    expect(r.mono, "고정폭(티커 밖)").toEqual([]);
    expect(r.heads.length).toBeGreaterThan(0);
    for (const h of r.heads) {
      expect(h.tt).toBe("none");
      expect(h.fs).toBe("17px");
      expect(h.fw).toBe("700");
    }
  });
}

// ── 색의 뜻 ─────────────────────────────────────────────────────────────────
type Ind = { id: string; name: string; z_score: number | null; delta: number | null };
type Theme = { key: string; label: string; indicators: Ind[] };

test("등락(지표 전월비) = 빨강 ▲ / 파랑 ▼ — 응답 부호를 뒤집으면 색도 뒤집힌다", async ({ page }) => {
  let flip = false;
  await patch(page, "dashboard", (b) => {
    const inds = (b.themes as Theme[]).flatMap((t) => t.indicators);
    inds[0].delta = flip ? -1.5 : 1.5; inds[1].delta = flip ? 2.5 : -2.5;
  });
  await open(page);
  await goTab(page, "indicators");
  const up = await tokenColor(page, "--tx-up-ink"), down = await tokenColor(page, "--tx-down-ink");
  const d = () => panel(page, "indicators").locator(".mc-ind .mc-ind-d");
  await expect(d().nth(0)).toContainText("▲");
  expect(await d().nth(0).evaluate((e) => getComputedStyle(e).color)).toBe(up);
  expect(await d().nth(1).evaluate((e) => getComputedStyle(e).color)).toBe(down);
  flip = true;
  await page.reload({ waitUntil: "domcontentloaded" });
  await goTab(page, "indicators");
  await expect(d().nth(0)).toContainText("▼");
  expect(await d().nth(0).evaluate((e) => getComputedStyle(e).color)).toBe(down);
  expect(await d().nth(1).evaluate((e) => getComputedStyle(e).color)).toBe(up);
});

test("수준(z) = 주황/청록 양쪽 색 — 등락색이 아니고 부호에 따라 쪽이 바뀐다(짝)", async ({ page }) => {
  await patch(page, "dashboard", (b) => {
    const inds = (b.themes as Theme[]).flatMap((t) => t.indicators);
    inds[0].z_score = 2.6; inds[1].z_score = -2.6; inds[2].z_score = 0.1;
  });
  await open(page);
  await goTab(page, "indicators");
  const cells = panel(page, "indicators").locator(".mc-heat-cell");
  const bg = (i: number) => cells.nth(i).evaluate((e) => getComputedStyle(e).backgroundColor);
  const [pos, neg, mid] = [await bg(0), await bg(1), await bg(2)];
  expect(pos).toBe(await tokenColor(page, "--mc-lv-pos-3", "backgroundColor"));
  expect(neg).toBe(await tokenColor(page, "--mc-lv-neg-3", "backgroundColor"));
  expect(mid).toBe(await tokenColor(page, "--mc-lv-mid", "backgroundColor"));
  for (const tok of ["--tx-up", "--tx-down", "--tx-up-ink", "--tx-down-ink"]) {
    const c = await tokenColor(page, tok, "backgroundColor");
    expect(pos).not.toBe(c); expect(neg).not.toBe(c);
  }
  expect(pos).not.toBe(neg);
});

test("판단(자산 틸트) = 비중을 늘려도 줄여도 같은 색 — 방향은 막대 쪽과 글자로(짝)", async ({ page }) => {
  await patch(page, "regime", (b) => { b.asset_tilts = { growth_stocks: "++", bonds: "--", cash: "0" }; });
  await open(page);
  await goTab(page, "regime");
  const rows = panel(page, "regime").locator(".mc-tilt-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("성장주");
  await expect(rows.nth(0)).toContainText("강한 비중확대");
  await expect(rows.nth(1)).toContainText("강한 비중축소");
  const fill = (i: number) => rows.nth(i).locator(".mc-tilt-fill").evaluate((e) => ({ c: getComputedStyle(e).backgroundColor, l: (e as HTMLElement).style.left, r: (e as HTMLElement).style.right }));
  const a = await fill(0), b = await fill(1);
  expect(a.c).toBe(b.c);
  expect(a.l).toBe("50%"); expect(b.r).toBe("50%");
});

test("판단(스트레스 게이지) = 값이 달라도 같은 색 · 숫자는 서버 값", async ({ page }) => {
  const colorAt = async (score: number) => {
    await page.unroute("**/api/v1/macro/regime");
    await patch(page, "regime", (b) => { b.stress_score = score; });
    await open(page);
    await goTab(page, "regime");
    const g = panel(page, "regime").locator(".mc-gauge").first();
    await expect(g).toContainText(String(score));
    return g.locator(".mc-gauge-fill").evaluate((e) => getComputedStyle(e).stroke);
  };
  const low = await colorAt(12), high = await colorAt(91);
  expect(low).toBe(high);
});

test("판단(추천 신호) = 공격이든 방어든 같은 색(짝: 글자는 서버 값 그대로)", async ({ page }) => {
  let sig = "공격";
  await patch(page, "recommend?market=kr", (b) => { const top = b.top as Record<string, unknown> | null; if (top) top.signal = sig; });
  await open(page);
  const badge = panel(page, "overview").locator(".mc-sig").first();
  await expect(badge).toContainText("공격");
  const c1 = await badge.evaluate((e) => getComputedStyle(e).color);
  sig = "방어";
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(badge).toContainText("방어", { timeout: 30_000 });
  expect(await badge.evaluate((e) => getComputedStyle(e).color)).toBe(c1);
});

test("국면 확률 막대 = 국면 색(`--mc-q-*`) · 이름은 한국어", async ({ page }) => {
  await open(page);
  await goTab(page, "regime");
  const rows = panel(page, "regime").locator(".mc-probbars .mc-pb-row");
  await expect(rows).toHaveCount(4);
  const ko = ["골디락스", "리플레이션", "스태그플레이션", "디스인플레이션"];
  const tok = ["--mc-q-goldilocks", "--mc-q-reflation", "--mc-q-stagflation", "--mc-q-disinflation"];
  for (let i = 0; i < 4; i++) {
    await expect(rows.nth(i)).toContainText(ko[i]);
    const c = await rows.nth(i).locator(".mc-pb-track i").evaluate((e) => getComputedStyle(e).backgroundColor);
    expect(c).toBe(await tokenColor(page, tok[i], "backgroundColor"));
  }
});

// ── 읽기 줄 (툴팁 대신) ─────────────────────────────────────────────────────
test("히트맵 칸에 초점 → 아래 읽기 줄이 그 칸의 지표·값을 말한다(짝: 다른 칸 → 다른 글)", async ({ page }) => {
  const seen = page.waitForResponse((r) => r.url().endsWith("/api/v1/macro/dashboard"));
  await open(page);
  const b = (await (await seen).json()) as { themes: Theme[] };
  const inds = b.themes.flatMap((t) => t.indicators);
  await goTab(page, "indicators");
  const cells = panel(page, "indicators").locator(".mc-heat-cell");
  const line = panel(page, "indicators").locator(".mc-readout").first();
  await cells.nth(0).focus();
  await expect(line).toContainText(inds[0].name);
  const t0 = await line.innerText();
  await cells.nth(1).focus();
  await expect(line).toContainText(inds[1].name);
  expect(await line.innerText()).not.toBe(t0);
});

// ── 실패는 실패로 (지연 로더 넷 + 드릴다운) ─────────────────────────────────
const LOADERS: Array<{ tab: Tab; path: string; ok: string }> = [
  { tab: "indicators", path: "cb-sentiment", ok: ".mc-cbg-grid" },
  { tab: "regime", path: "cycle-strips**", ok: ".mv-strips" },
  { tab: "regime", path: "axis-history**", ok: ".mc-axstack svg" },
  { tab: "valuation", path: "asset-strips**", ok: ".mv-strips" },
];
for (const L of LOADERS) {
  test(`${L.path} 500 → 그 카드 안 alert + 다시 시도 → 풀리면 그림`, async ({ page }) => {
    await page.route(`**/api/v1/macro/${L.path}`, (r) => r.fulfill({ status: 500, body: "x" }));
    await open(page);
    await goTab(page, L.tab, { settle: false });
    const alert = panel(page, L.tab).locator('.mc-card [role="alert"]');
    await expect(alert).toHaveCount(1, { timeout: 30_000 });
    await expect(panel(page, L.tab).locator(L.ok)).toHaveCount(0);
    await page.unroute(`**/api/v1/macro/${L.path}`);
    await alert.getByRole("button", { name: "다시 시도" }).click();
    await expect(panel(page, L.tab).locator(L.ok).first()).toBeVisible({ timeout: 30_000 });
    await expect(alert).toHaveCount(0);
  });
}
test("축 분해 기록이 실패해도 성장·물가 하위요인 카드는 남아서 실패를 말한다", async ({ page }) => {
  await page.route("**/api/v1/macro/axis-history**", (r) => r.fulfill({ status: 500, body: "x" }));
  await open(page);
  await goTab(page, "regime", { settle: false });
  const card = panel(page, "regime").locator(".mc-card", { has: page.locator(".mc-card-h", { hasText: "성장 축" }) }).first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.locator('[role="alert"]')).toHaveCount(1);
});
for (const t of TABS) {
  test(`정상이면 alert 0 — ${t}(짝)`, async ({ page }) => {
    await open(page);
    await goTab(page, t);
    await expect(panel(page, t).locator('[role="alert"]')).toHaveCount(0);
  });
}
test("드릴다운 시계열 500 → 창 안 alert + 다시 시도 → 풀리면 통계", async ({ page }) => {
  await page.route("**/api/v1/macro/series/**", (r) => r.fulfill({ status: 500, body: "x" }));
  await open(page);
  await goTab(page, "indicators");
  await panel(page, "indicators").locator(".mc-heat-cell").first().click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.locator('[role="alert"]')).toHaveCount(1, { timeout: 30_000 });
  await page.unroute("**/api/v1/macro/series/**");
  await dlg.getByRole("button", { name: "다시 시도" }).click();
  await expect(dlg.locator(".mc-modal-stats")).toBeVisible({ timeout: 30_000 });
  await expect(dlg.locator('[role="alert"]')).toHaveCount(0);
});

// ── AA · 다크 밝은 판 · 390 ─────────────────────────────────────────────────
for (const mode of ["light", "dark"] as const) {
  for (const t of TABS) {
    test(`AA ${mode} — ${t}`, async ({ page }) => {
      await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, mode);
      await open(page);
      await goTab(page, t);
      const r = await page.evaluate<AuditResult>(contrastAudit(`#mc-panel-${t}`));
      expect(r.checked).toBeGreaterThan(10);
      expect(r.low, `${mode} ${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
      if (mode === "dark") expect(r.bright, `${t} 밝은 판`).toEqual([]);
    });
  }
}
for (const t of TABS) {
  test(`390 — ${t} 가로 넘침 없음`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page);
    await goTab(page, t);
    const over = await page.evaluate(() => {
      const m = document.querySelector(".terminal-main") as HTMLElement;
      return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
    });
    expect(over).toBeLessThanOrEqual(0);
  });
}
