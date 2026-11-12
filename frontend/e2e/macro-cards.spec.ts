import { test, expect, type Page, type Route } from "./fixtures";
import { CAT_N } from "../src/shared/ui/vizColor";
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
// 중앙은행 말투 게이지는 서버가 ★외부 정책문★을 받아야 그려진다(mock 모드에서도 실제 수집). 네트워크가 열린 CI 에서만 그려져
// 같은 시험이 두 곳에서 다른 화면을 봤다(2026-11-12 · 'AA dark — indicators' 가 CI 에서만 실패). 그래서 응답을 고정한다 —
// 연준은 수집됨, 한국은행은 수집 실패: 두 갈래가 한 화면에 있다. 값은 시험 고정값이지 관측이 아니다.
const CB = {
  as_of: "2026-11-12 09:00",
  method: "렉시콘 기반 매파/비둘기 용어 밀도",
  banks: {
    fed: { available: true, source: "https://example.invalid/fed", score: 0.5, label: "매파 (긴축)", hawkish_hits: 6, dovish_hits: 2, terms: ["inflation", "restrictive"] },
    bok: { available: false, note: "정책문 수집 실패(네트워크/구조 변경) — 점수 미산출(정직)" },
  },
};
const fixCb = (page: Page, body: unknown = CB) => page.route("**/api/v1/macro/cb-sentiment", (r) => r.fulfill({ json: body }));
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

// ── 중앙은행 말투 게이지 — 바늘 자리 = 서버 점수 · 못 받은 쪽은 사유 ─────────
test("중앙은행 게이지: 바늘 자리는 서버 점수(−1~+1 → 0~100%) · 수집 실패는 사유(짝) · 점수를 바꾸면 자리가 바뀐다", async ({ page }) => {
  await fixCb(page);
  await open(page);
  await goTab(page, "indicators");
  const grid = panel(page, "indicators").locator(".mc-cbg-grid");
  const fed = grid.locator(".mc-cbg").nth(0), bok = grid.locator(".mc-cbg").nth(1);
  await expect(fed.locator(".mc-cbg-h b")).toHaveText("매파 (긴축)");
  await expect(fed.locator(".mc-cbg-marker")).toHaveAttribute("style", /left:\s*75%/);
  await expect(fed.locator(".mc-cbg-meta")).toContainText("6번");
  await expect(bok.locator(".mc-cbg-none")).toContainText("점수 산출 실패");
  await expect(bok.locator(".mc-cbg-none [data-server]")).toHaveText(CB.banks.bok.note);
  await expect(bok.locator(".mc-cbg-marker"), "못 받은 쪽에 바늘을 지어내지 않는다").toHaveCount(0);

  const p2 = await page.context().newPage();
  await fixCb(p2, { ...CB, banks: { ...CB.banks, fed: { ...CB.banks.fed, score: -1, label: "비둘기 (완화)" } } });
  await open(p2);
  await goTab(p2, "indicators");
  await expect(panel(p2, "indicators").locator(".mc-cbg-marker")).toHaveAttribute("style", /left:\s*0%/);
  await p2.close();
});

// ── 실패는 실패로 (지연 로더 넷 + 드릴다운) ─────────────────────────────────
const LOADERS: Array<{ tab: Tab; path: string; ok: string }> = [
  { tab: "indicators", path: "cb-sentiment", ok: ".mc-cbg-grid" },
  { tab: "regime", path: "cycle-strips**", ok: ".mv-strips" },
  { tab: "regime", path: "axis-history**", ok: ".mc-axstack svg" },
  { tab: "valuation", path: "asset-strips**", ok: ".mv-strips" },
];
for (const L of LOADERS) {
  test(`${L.path} 500 → 그 카드 안 alert + 재시도 → 풀리면 그림`, async ({ page }) => {
    await page.route(`**/api/v1/macro/${L.path}`, (r) => r.fulfill({ status: 500, body: "x" }));
    await open(page);
    await goTab(page, L.tab, { settle: false });
    const alert = panel(page, L.tab).locator('.mc-card [role="alert"]');
    await expect(alert).toHaveCount(1, { timeout: 30_000 });
    await expect(panel(page, L.tab).locator(L.ok)).toHaveCount(0);
    await page.unroute(`**/api/v1/macro/${L.path}`);
    await alert.getByRole("button", { name: "재시도" }).click();
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
test("드릴다운 시계열 500 → 창 안 alert + 재시도 → 풀리면 통계", async ({ page }) => {
  await page.route("**/api/v1/macro/series/**", (r) => r.fulfill({ status: 500, body: "x" }));
  await open(page);
  await goTab(page, "indicators");
  await panel(page, "indicators").locator(".mc-heat-cell").first().click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.locator('[role="alert"]')).toHaveCount(1, { timeout: 30_000 });
  await page.unroute("**/api/v1/macro/series/**");
  await dlg.getByRole("button", { name: "재시도" }).click();
  await expect(dlg.locator(".mc-modal-stats")).toBeVisible({ timeout: 30_000 });
  await expect(dlg.locator('[role="alert"]')).toHaveCount(0);
});

// ── AA · 다크 밝은 판 · 390 ─────────────────────────────────────────────────
for (const mode of ["light", "dark"] as const) {
  for (const t of TABS) {
    test(`AA ${mode} — ${t}`, async ({ page }) => {
      await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, mode);
      if (t === "indicators") await fixCb(page);
      await open(page);
      await goTab(page, t);
      if (t === "indicators") await expect(panel(page, t).locator(".mc-cbg-marker")).toHaveCount(1);   // 게이지가 그려진 채로 잰다(공허하지 않게)
      const r = await page.evaluate<AuditResult>(contrastAudit(`#mc-panel-${t}`));
      expect(r.checked).toBeGreaterThan(10);
      expect(r.low, `${mode} ${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
      if (mode === "dark") {
        // 게이지 바늘은 판이 아니라 표식이다 — 폭 4px 의 잉크색 막대라 다크에서 밝은 것이 맞다(화면으로 확인 2026-11-12).
        // 예외는 이 요소 하나에만, 그리고 ★가는 표식일 때만★ — 폭이 6px 을 넘으면 표식이 아니라 밝은 판이다.
        const needle = (b: string) => b.startsWith("I.mc-cbg-marker ");
        if (r.bright.some(needle)) {
          const w = await panel(page, t).locator(".mc-cbg-marker").evaluateAll((els) => Math.max(...els.map((e) => e.getBoundingClientRect().width)));
          expect(w, "게이지 바늘 폭 — 넓으면 예외가 아니다").toBeLessThanOrEqual(6);
        }
        expect(r.bright.filter((b) => !needle(b)), `${t} 밝은 판`).toEqual([]);
      }
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

// ═══════════════════════════════════════════════════════════════════════════════
// BU5b-2 · 전략·추천·상관·타이밍 탭 + 전략 창 (계획 "BU5b-2 상세")
// ═══════════════════════════════════════════════════════════════════════════════
const TABS2 = ["strategies", "recommend", "correlations", "timing"] as const;
type Tab2 = (typeof TABS2)[number];
const panel2 = (p: Page, t: Tab2) => p.locator(`#mc-panel-${t}`);
const WAIT2: Record<Tab2, string[]> = {
  strategies: [], recommend: [],
  correlations: ["/api/v1/macro/correlations", "/api/v1/macro/causal-graph"],
  timing: ["/api/v1/macro/timing"],
};
// 바꾸기 전 화면(BU5b-1 `b421ee5`)에서 잰 그림 수 — 줄이면 빨강. (RECORD_VIZ=1)
const VIZ_MIN2: Record<Tab2 | "modal", { svg: number; cells: number; bars: number }> = {
  strategies: { svg: 22, cells: 73, bars: 73 },
  recommend: { svg: 3, cells: 24, bars: 56 },
  correlations: { svg: 8, cells: 169, bars: 0 },
  timing: { svg: 2, cells: 78, bars: 18 },
  modal: { svg: 2, cells: 8, bars: 4 },
};
async function goTab2(page: Page, t: Tab2, { settle = true } = {}) {
  const waits = settle ? WAIT2[t].map((u) => page.waitForResponse((r) => r.url().includes(u), { timeout: 30_000 }).catch(() => null)) : [];
  await page.locator(`#mc-tab-${t}`).click();
  await expect(panel2(page, t)).toBeVisible();
  await Promise.all(waits);
  if (settle) await page.waitForTimeout(900);
}
const vizIn = (loc: ReturnType<Page["locator"]>) => loc.evaluate((root) => ({
  svg: root.querySelectorAll("svg:not(.lucide)").length,
  cells: root.querySelectorAll(".mca-mx-cell, .mca-trend tbody td, .mc-rankrow, .mc-hold-row, .sm-hold").length,
  bars: root.querySelectorAll(".mc-pb-track, .mc-attr-term, .mc-band-track, .mca-comp-track, .mca-rsi-track, .mc-hold-bar, .mc-rank-bar, .sm-fit-track").length,
}));
async function openModal(page: Page) {
  await open(page);
  await goTab2(page, "strategies");
  await panel2(page, "strategies").locator(".mc-stratcard").first().click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.locator(".sm-body, [role=alert]").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(700);
  return dlg;
}

for (const t of TABS2) {
  test(`그림 수 보존 — ${t} (BU5b-2)`, async ({ page }) => {
    // ★전략 탭의 보유 줄 수는 데이터다★ 서버가 그날의 (연습용) 시세로 보유 종목을 다시 고르므로
    // 10-03 에 잰 73 은 10-08 에 68 이 됐다(화면 변경 0 — 같은 빌드로 확인). 그래서 이 탭은 고정 하한 대신
    // 받은 응답에서 기대값을 센다: 카드마다 보유 상위 6줄(`StrategyCard` 의 `slice(0, 6)`) · 카드마다 도넛 하나.
    const stratResp = t === "strategies"
      ? page.waitForResponse((r) => r.url().includes("/api/v1/macro/strategies?market=kr"), { timeout: 30_000 }) : null;
    await open(page);
    await goTab2(page, t);
    const n = await vizIn(panel2(page, t));
    if (process.env.RECORD_VIZ) console.log(`VIZ2 ${t} ${JSON.stringify(n)}`);
    if (stratResp) {
      const body = await (await stratResp).json() as { strategies: { holdings: unknown[] }[] };
      const rows = body.strategies.reduce((a, s) => a + Math.min(6, s.holdings.length), 0);
      expect(body.strategies.length, "전략이 하나도 없으면 이 검사는 공허하다").toBeGreaterThan(0);
      expect(n.cells, "보유 줄 = 서버 보유 종목(카드마다 상위 6)").toBe(rows);
      expect(n.bars, "보유 막대 = 보유 줄").toBe(rows);
      expect(n.svg, "카드마다 도넛 하나 이상").toBeGreaterThanOrEqual(body.strategies.length);
      return;
    }
    expect(n.svg).toBeGreaterThanOrEqual(VIZ_MIN2[t].svg);
    expect(n.cells).toBeGreaterThanOrEqual(VIZ_MIN2[t].cells);
    expect(n.bars).toBeGreaterThanOrEqual(VIZ_MIN2[t].bars);
    expect(n.svg + n.cells + n.bars).toBeGreaterThan(0);
  });
}
test("그림 수 보존 — 전략 창 (BU5b-2)", async ({ page }) => {
  const dlg = await openModal(page);
  const n = await vizIn(dlg);
  if (process.env.RECORD_VIZ) console.log(`VIZ2 modal ${JSON.stringify(n)}`);
  expect(n.svg).toBeGreaterThanOrEqual(VIZ_MIN2.modal.svg);
  expect(n.cells).toBeGreaterThanOrEqual(VIZ_MIN2.modal.cells);
  expect(n.bars).toBeGreaterThanOrEqual(VIZ_MIN2.modal.bars);
});

/** 글 검사 — 패널(또는 창) 안 보이는 글. 서버 글(`[data-server]`)은 뺀다. */
const copyAudit = (loc: ReturnType<Page["locator"]>) => loc.evaluate((root) => {
  const texts: string[] = []; const mono: string[] = [];
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n: Node | null;
  while ((n = walk.nextNode())) {
    const el = n.parentElement!; const s = (n.textContent ?? "").trim();
    if (!s) continue;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || !el.getClientRects().length || el.closest(".sr-only")) continue;
    if (!el.closest("[data-server]")) texts.push(s);
    if (/mono/i.test(cs.fontFamily) && !el.closest("[data-mono]")) mono.push(s.slice(0, 24));
  }
  const heads = Array.from(root.querySelectorAll(".mc-card-h, .mc-strat-title, .sm-sec-h")).map((h) => {
    const cs = getComputedStyle(h); return { tt: cs.textTransform, fw: cs.fontWeight };
  });
  return {
    texts, mono, heads,
    // PerfLabel 의 title 은 BU4 에서 정한 예외(사유를 접어 둔 compact 라벨 — backtest-results.spec 과 같은 규칙)
    titles: Array.from(root.querySelectorAll("[title]:not(.perf-label)")).filter((e) => e.getAttribute("title")?.trim()).length
      + Array.from(root.querySelectorAll("svg title")).filter((e) => e.textContent?.trim()).length,
  };
});
const BANNED_EN2 = /\b(Goldilocks|Reflation|Stagflation|Disinflation|STRESS|Stress|CAUTIOUS|mock|MOCK|US ETF|Weight Attribution|Causal Graph|lag|12M|MC|ANTHROPIC_API_KEY|Claude)\b/;
async function expectCopy(loc: ReturnType<Page["locator"]>) {
  const r = await copyAudit(loc);
  expect(r.texts.filter((s) => s.includes("—")), "보이는 em-dash").toEqual([]);
  expect(r.texts.filter((s) => BANNED_EN2.test(s)), "영어 꼬리표").toEqual([]);
  expect(r.titles, "title 툴팁").toBe(0);
  expect(r.mono, "고정폭(티커 밖)").toEqual([]);
  expect(r.heads.length).toBeGreaterThan(0);
  for (const h of r.heads) { expect(h.tt).toBe("none"); expect(h.fw).toBe("700"); }
}
for (const t of TABS2) {
  test(`글 — ${t}: em-dash 0 · 영어 꼬리표 0 · 툴팁 0 · 대문자 없음 · 고정폭은 티커만`, async ({ page }) => {
    await open(page);
    await goTab2(page, t);
    await expectCopy(panel2(page, t));
  });
}
test("글 — 전략 창", async ({ page }) => {
  await expectCopy(await openModal(page));
});

// ── 게이지 끝 글자: 스트레스만 "잔잔해요/불안해요"(BU5b-1 버그 짝) ──
test("적합도·위험 선호도 게이지에는 스트레스 끝 글자가 없다(짝: 국면 탭 스트레스 게이지엔 있다)", async ({ page }) => {
  await open(page);
  await goTab2(page, "recommend");
  await expect(panel2(page, "recommend").locator(".mc-gauge").first()).toBeVisible();
  await expect(panel2(page, "recommend").locator(".mc-gauge")).not.toContainText("100 · 불안");
  await goTab2(page, "timing");
  await expect(panel2(page, "timing").locator(".mc-gauge").first()).toBeVisible();
  await expect(panel2(page, "timing").locator(".mc-gauge")).not.toContainText("100 · 불안");
  await page.locator("#mc-tab-regime").click();
  await expect(page.locator("#mc-panel-regime .mc-gauge").first()).toContainText("100 · 불안");
});

// ── 색의 뜻 ──
test("등락(12개월 성과·이동평균 대비·추세) = 빨강/파랑 — 부호를 뒤집으면 색도 뒤집힌다", async ({ page }) => {
  await patch(page, "recommend?market=kr", (b) => {
    const r = b.ranking as Array<Record<string, unknown>>; r[0].recent_return_12m = 7.5; r[1].recent_return_12m = -4.2;
  });
  await patch(page, "timing?market=kr", (b) => {
    const a = b.assets as Array<Record<string, unknown>>;
    a[0].vs_ma200_pct = 3.1; a[0].trend = "상승"; a[1].vs_ma200_pct = -2.4; a[1].trend = "하락";
  });
  await open(page);
  const up = await tokenColor(page, "--tx-up-ink"), down = await tokenColor(page, "--tx-down-ink");
  await goTab2(page, "recommend");
  const perf = panel2(page, "recommend").locator(".mc-rankrow .mc-rank-perf");
  expect(await perf.nth(0).evaluate((e) => getComputedStyle(e).color)).toBe(up);
  expect(await perf.nth(1).evaluate((e) => getComputedStyle(e).color)).toBe(down);
  await goTab2(page, "timing");
  const rows = panel2(page, "timing").locator(".mca-trend tbody tr");
  const ma = (i: number) => rows.nth(i).locator("td").nth(1).evaluate((e) => getComputedStyle(e).color);
  expect(await ma(0)).toBe(up); expect(await ma(1)).toBe(down);
  const pill = (i: number) => rows.nth(i).locator(".mca-trend-pill").evaluate((e) => getComputedStyle(e).color);
  expect(await pill(0)).toBe(up); expect(await pill(1)).toBe(down);
});

test("상관 행렬 = 주황/청록 양쪽 색(등락색 아님) · 칸에 올리면 읽기 줄", async ({ page }) => {
  await patch(page, "correlations?market=kr", (b) => {
    const m = b.matrix as { values: number[][] };
    m.values[0][1] = 0.85; m.values[0][2] = -0.85; m.values[0][3] = 0.05;
  });
  await open(page);
  await goTab2(page, "correlations");
  const row0 = panel2(page, "correlations").locator(".mca-mx-cell").filter({ hasNot: page.locator("x") });
  const bg = (j: number) => row0.nth(j).evaluate((e) => getComputedStyle(e).backgroundColor);
  expect(await bg(1)).toBe(await tokenColor(page, "--mc-lv-pos-3", "backgroundColor"));
  expect(await bg(2)).toBe(await tokenColor(page, "--mc-lv-neg-3", "backgroundColor"));
  expect(await bg(3)).toBe(await tokenColor(page, "--mc-lv-mid", "backgroundColor"));
  for (const tok of ["--tx-up", "--tx-down"]) expect(await bg(1)).not.toBe(await tokenColor(page, tok, "backgroundColor"));
  const line = panel2(page, "correlations").locator(".mc-readout").first();
  await row0.nth(1).hover();
  await expect(line).toContainText("+0.85");
  await row0.nth(2).hover();
  await expect(line).toContainText("−0.85");
});

test("판단(헤지 판정·타이밍 점수) = 값이 달라도 같은 색", async ({ page }) => {
  let verdict = "헤지", score = 85;
  await patch(page, "correlations?market=kr", (b) => { (b.stock_bond_now as Record<string, unknown>).verdict = verdict; });
  await patch(page, "timing?market=kr", (b) => {
    (b.composite as Record<string, unknown>).score = score;
    const c = b.components as Array<Record<string, unknown>>; c[0].score = 90; c[1].score = 10;
  });
  await open(page);
  await goTab2(page, "correlations");
  const v = panel2(page, "correlations").locator(".mc-verdict");
  await expect(v).toContainText("헤지");
  const c1 = await v.evaluate((e) => getComputedStyle(e).color);
  await goTab2(page, "timing");
  const fill = () => panel2(page, "timing").locator(".mc-gauge-fill").evaluate((e) => getComputedStyle(e).stroke);
  const g1 = await fill();
  const bars = panel2(page, "timing").locator(".mca-comp-track i");
  expect(await bars.nth(0).evaluate((e) => getComputedStyle(e).backgroundColor)).toBe(await bars.nth(1).evaluate((e) => getComputedStyle(e).backgroundColor));
  verdict = "동조"; score = 15;
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".mc")).toBeVisible({ timeout: 30_000 });
  await goTab2(page, "correlations");
  await expect(v).toContainText("동조");
  expect(await v.evaluate((e) => getComputedStyle(e).color)).toBe(c1);
  await goTab2(page, "timing");
  expect(await fill()).toBe(g1);
});

test("롤링 상관 선 = 범주색(등락색 아님) · 전략 창 보유 목록 색 = 도넛 조각 색(기타 접기 일치)", async ({ page }) => {
  await open(page);
  await goTab2(page, "correlations");
  const strokes = await panel2(page, "correlations").locator(".recharts-line-curve").evaluateAll((els) => els.map((e) => getComputedStyle(e).stroke));
  expect(strokes.length).toBeGreaterThan(1);
  const up = await tokenColor(page, "--tx-up"), down = await tokenColor(page, "--tx-down");
  for (const s of strokes) { expect(s).not.toBe(up); expect(s).not.toBe(down); }
  expect(strokes[0]).toBe(await tokenColor(page, "--mc-c-1"));
  const dlg = await openModal(page);
  // 조각 색은 고리 조각(circle)의 stroke 속성(var(--mc-c-n))에 있다 — 계산 색으로 풀어서 범례 칸 바탕과 견준다(도넛은 직접 SVG · ADR 004).
  const slices = await dlg.locator("svg.tx-donut circle[data-slice]").evaluateAll((els) => els.map((e) => {
    const t = document.createElement("span"); t.style.color = e.getAttribute("stroke") ?? ""; document.body.appendChild(t);
    const c = getComputedStyle(t).color; t.remove(); return c;
  }));
  expect(slices.length).toBeGreaterThan(1);
  const legend = await dlg.locator(".sm-hold i").evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
  for (const c of legend) expect(slices).toContain(c);
});

// ── 값은 호버가 아니라 늘 보이는 읽는 줄에 (ADR 004 §2.4 · 2026-11-10) ──
// 분석 탭의 그림 넷과 지표 흐름 창은 recharts 그대로지만 `<Tooltip>` 이 없다. 값은 읽는 줄(`.cr-read` · 처음 자리 = 마지막 점 ·
// ←→ Home End · 마우스를 올려도 옮겨진다)과 표 쌍둥이(`.cr-table` — 솎지 않은 전부)에 있다. 글자 = 서버 값을 화면 서식으로.
const sgn2 = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`;       // macroKo.signed 와 같은 서식
const frame = (root: ReturnType<Page["locator"]>, id: string) => root.locator(`.cr[data-chart="${id}"]`);

test("읽는 줄 — 상관 탭(롤링·평균): 툴팁 0 · 처음 자리 = 서버 마지막 점 · ← 로 앞 날짜 · 마우스로도 · 표 쌍둥이 = 전부", async ({ page }) => {
  const corrP = page.waitForResponse((r) => r.url().includes("/api/v1/macro/correlations"), { timeout: 30_000 });
  await open(page);
  await goTab2(page, "correlations");
  const corr = await (await corrP).json() as { pairs: { key: string; label: string; series: { t: string; corr: number | null }[] }[]; avg_corr: { t: string; corr: number }[] };
  const pnl = panel2(page, "correlations");
  const len = Math.max(...corr.pairs.map((p) => p.series.length));
  expect(len, "롤링 상관 점이 없으면 이 검사는 공허하다").toBeGreaterThan(3);
  const roll = frame(pnl, "rolling-corr");
  await expect(roll.locator(".recharts-line-curve").first()).toBeVisible({ timeout: 30_000 });
  await expect(pnl.locator(".recharts-tooltip-wrapper")).toHaveCount(0);
  const dates = corr.pairs[0].series.map((x) => x.t);
  await expect(roll.locator(".cr-head")).toHaveText(dates[len - 1]);
  await expect(roll.locator(".cr-item")).toHaveCount(corr.pairs.length);
  for (const p of corr.pairs) {
    const v = p.series[len - 1]?.corr;
    if (v != null) await expect(roll.locator(".cr-read")).toContainText(`${p.label} ${sgn2(v)}`);
  }
  await roll.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(roll.locator(".cr-head")).toHaveText(dates[len - 2]);
  // ★마우스로도★ — 툴팁 없이 그림 왼쪽에 올리면 읽는 줄이 앞쪽 날짜로 간다(차트 이벤트 → 자리)
  const box = (await roll.locator(".recharts-wrapper > svg.recharts-surface").boundingBox())!;     // 범례 칸의 작은 svg 도 같은 class 다
  await page.mouse.move(box.x + box.width * 0.15, box.y + box.height * 0.4);
  await expect.poll(async () => dates.indexOf((await roll.locator(".cr-head").textContent()) ?? ""), { message: "왼쪽에 올리면 앞쪽 날짜" }).toBeLessThan(len / 2);
  await roll.locator(".cr-table summary").click();
  await expect(roll.locator(".cr-table tbody tr")).toHaveCount(len);
  // 평균 상관
  const avg = frame(pnl, "avg-corr");
  const lastA = corr.avg_corr[corr.avg_corr.length - 1];
  await expect(avg.locator(".cr-head")).toHaveText(lastA.t);
  await expect(avg.locator(".cr-read")).toContainText(`평균 상관 ${lastA.corr.toFixed(2)}`);
  await avg.locator(".cr-table summary").click();
  await expect(avg.locator(".cr-table tbody tr")).toHaveCount(corr.avg_corr.length);
  await expect(pnl.locator("[title]")).toHaveCount(0);
});

test("읽는 줄 — 타이밍 탭(위험 선호도 추이): 툴팁 0 · 처음 자리 = 서버 마지막 점 · Home 으로 첫 점 · 표 쌍둥이 = 전부", async ({ page }) => {
  const timP = page.waitForResponse((r) => r.url().includes("/api/v1/macro/timing"), { timeout: 30_000 });
  await open(page);
  await goTab2(page, "timing");
  const hist = ((await (await timP).json()) as { history: { t: string; score: number }[] }).history;
  expect(hist.length, "추이 점이 없으면 이 검사는 공허하다").toBeGreaterThan(3);
  const pnl = panel2(page, "timing");
  const f = frame(pnl, "timing-history");
  await expect(f.locator(".recharts-area-curve").first()).toBeVisible({ timeout: 30_000 });
  await expect(pnl.locator(".recharts-tooltip-wrapper")).toHaveCount(0);
  const last = hist[hist.length - 1];
  await expect(f.locator(".cr-head")).toHaveText(last.t);
  await expect(f.locator(".cr-read")).toContainText(`위험 선호도 ${last.score.toFixed(0)}`);
  await f.focus();
  await page.keyboard.press("Home");
  await expect(f.locator(".cr-head")).toHaveText(hist[0].t);
  await f.locator(".cr-table summary").click();
  await expect(f.locator(".cr-table tbody tr")).toHaveCount(hist.length);
});

test("읽는 줄 — 국면 궤적(산점도): 툴팁 0 · 처음 자리 = 지금 달 · ← 로 앞 달(성장·물가·국면 이름) · 표 쌍둥이 = 전부", async ({ page }) => {
  const trP = page.waitForResponse((r) => r.url().includes("/api/v1/macro/regime-trajectory"), { timeout: 30_000 });
  await open(page);
  await goTab(page, "regime");
  const path = ((await (await trP).json()) as { path: { t: string; growth: number; inflation: number }[] }).path;
  expect(path.length, "궤적 점이 없으면 이 검사는 공허하다").toBeGreaterThan(2);
  const f = frame(panel(page, "regime"), "regime-trajectory");
  await expect(f.locator(".recharts-scatter").first()).toBeVisible({ timeout: 30_000 });
  await expect(f.locator(".recharts-tooltip-wrapper")).toHaveCount(0);
  const last = path[path.length - 1], prev = path[path.length - 2];
  await expect(f.locator(".cr-head")).toHaveText(last.t);
  await expect(f.locator(".cr-read")).toContainText(`성장 ${last.growth.toFixed(2)}`);
  await expect(f.locator(".cr-read")).toContainText(`물가 ${last.inflation.toFixed(2)}`);
  await f.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(f.locator(".cr-head")).toHaveText(prev.t);
  await expect(f.locator(".cr-read")).toContainText(`성장 ${prev.growth.toFixed(2)}`);
  await f.locator(".cr-table summary").click();
  await expect(f.locator(".cr-table tbody tr")).toHaveCount(path.length);
});

test("읽는 줄 — 지표 흐름 창: 툴팁 0 · 처음 자리 = 서버 마지막 값 · ← 로 앞 달 · 표 쌍둥이 = 전부", async ({ page }) => {
  await open(page);
  await goTab(page, "indicators");
  const serP = page.waitForResponse((r) => r.url().includes("/api/v1/macro/series/") && r.status() === 200, { timeout: 30_000 });
  await panel(page, "indicators").locator(".mc-heat-cell").first().click();
  const ser = await (await serP).json() as { timestamps: string[]; values: number[] };
  expect(ser.values.length, "시계열이 없으면 이 검사는 공허하다").toBeGreaterThan(3);
  const dlg = page.getByRole("dialog");
  const f = frame(dlg, "drill-series");
  await expect(f.locator(".recharts-area-curve").first()).toBeVisible({ timeout: 30_000 });
  await expect(dlg.locator(".recharts-tooltip-wrapper")).toHaveCount(0);
  const lab = (t: string) => (t.length > 6 ? t.slice(0, 7).replace("-", ".") : t);                         // 창의 가로축 글자와 같은 서식
  const num = (v: number) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(2));         // cockpitParts.fmtNum
  const n = ser.values.length;
  await expect(f.locator(".cr-head")).toHaveText(lab(ser.timestamps[n - 1]));
  await expect(f.locator(".cr-read")).toContainText(num(ser.values[n - 1]));
  await f.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(f.locator(".cr-head")).toHaveText(lab(ser.timestamps[n - 2]));
  await expect(f.locator(".cr-read")).toContainText(num(ser.values[n - 2]));
  await f.locator(".cr-table summary").click();
  await expect(f.locator(".cr-table tbody tr")).toHaveCount(n);
});

// ── 보유 도넛 = 직접 SVG 고리 (ADR 004 · 2026-11-10) ──
// 예전에는 recharts Pie 였고 이름·비중은 호버 툴팁에만 있었다. 이제 공용 고리(`shared/ui/Donut.tsx`)라 차트 조각을 기다리지 않고,
// 조각 전부의 이름·비중은 `aria-label` 에(보이는 값은 옆 목록에) 있다. 분모는 ★값의 합★ — 비중 합이 100 이 아니어도 고리는 한 바퀴다.
test("보유 도넛 — 직접 SVG 고리: 조각 수 = 접은 보유 수 · 조각 길이의 합 = 한 바퀴(비중 합 50 이어도) · 이름·비중은 aria-label · recharts 0", async ({ page }) => {
  // 전략 상세의 보유 비중을 절반으로 고친다(합 ≈ 50) — 분모를 100 으로 두면 고리가 반만 찬다.
  await page.route(/\/api\/v1\/macro\/strategy\/[^/?]+(\?.*)?$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json() as { holdings?: { weight: number }[] };
    for (const h of body.holdings ?? []) h.weight = Math.round(h.weight * 5) / 10;
    await route.fulfill({ response: res, json: body });
  });
  const detailP = page.waitForResponse((r) => /\/api\/v1\/macro\/strategy\/[^/?]+(\?|$)/.test(r.url()), { timeout: 30_000 });
  const dlg = await openModal(page);
  const detail = await (await detailP).json() as { holdings: { label: string; weight: number }[] };
  expect(detail.holdings.length, "보유가 하나뿐이면 이 검사는 공허하다").toBeGreaterThan(1);
  expect(detail.holdings.reduce((a, h) => a + h.weight, 0), "비중 합을 100 아래로 고쳤어야 한다").toBeLessThan(60);
  const donut = dlg.locator("svg.tx-donut");
  await expect(donut).toHaveCount(1);
  const arcs = donut.locator("circle[data-slice]");
  await expect(arcs).toHaveCount(Math.min(detail.holdings.length, CAT_N));
  const label = (await donut.getAttribute("aria-label")) ?? "";
  expect(label).toContain(detail.holdings[0].label);
  expect(label).toContain(`${detail.holdings[0].weight}%`);
  // 조각마다 (그린 길이 + 틈 1.5) 를 더하면 고리 둘레 — 조각이 아주 작아 길이가 0 으로 잘린 만큼만 어긋난다(3px 안)
  const geo = await arcs.evaluateAll((els) => els.map((e) => ({
    r: Number(e.getAttribute("r")), dash: parseFloat((e.getAttribute("stroke-dasharray") ?? "0").split(/[ ,]+/)[0]) })));
  const round = 2 * Math.PI * geo[0].r;
  expect(Math.abs(geo.reduce((a, g) => a + g.dash + 1.5, 0) - round), `조각 길이 합 대 둘레 ${round.toFixed(1)}`).toBeLessThan(3);
  await expect(dlg.locator(".recharts-pie-sector, .recharts-tooltip-wrapper")).toHaveCount(0);
  await expect(donut.locator("title")).toHaveCount(0);
});

// ── 실패는 실패로 ──
test("미국 전략 500 → alert + 재시도('데이터 없음' 아님) → 풀리면 전략 카드", async ({ page }) => {
  await page.route("**/api/v1/macro/strategies?market=us", (r) => r.fulfill({ status: 500, body: "x" }));
  await open(page);
  await goTab2(page, "strategies");
  await panel2(page, "strategies").getByRole("button", { name: "미국 ETF" }).click();
  const alert = panel2(page, "strategies").locator('[role="alert"]');
  await expect(alert).toHaveCount(1, { timeout: 30_000 });
  await expect(panel2(page, "strategies")).not.toContainText("데이터 없음");
  await page.unroute("**/api/v1/macro/strategies?market=us");
  await alert.getByRole("button", { name: "재시도" }).click();
  await expect(panel2(page, "strategies").locator(".mc-stratcard").first()).toBeVisible({ timeout: 30_000 });
});
for (const [tab, path, ok] of [["correlations", "correlations?market=kr", ".mca-matrix"], ["timing", "timing?market=kr", ".mca-trend"], ["correlations", "causal-graph", ".mc-causal"]] as const) {
  test(`${path} 500 → 그 자리 alert + 재시도 → 풀리면 그림`, async ({ page }) => {
    await page.route(`**/api/v1/macro/${path}`, (r) => r.fulfill({ status: 500, body: "x" }));
    await open(page);
    await goTab2(page, tab, { settle: false });
    const alert = panel2(page, tab).locator('[role="alert"]');
    await expect(alert).toHaveCount(1, { timeout: 30_000 });
    await expect(panel2(page, tab).locator(ok)).toHaveCount(0);
    await page.unroute(`**/api/v1/macro/${path}`);
    await alert.getByRole("button", { name: "재시도" }).click();
    await expect(panel2(page, tab).locator(ok).first()).toBeVisible({ timeout: 30_000 });
  });
}
test("시장을 바꾸면 옛 시장 상관 행렬이 남지 않는다 — 새 시장을 기다리는 동안에도, 실패하면 실패만 보인다", async ({ page }) => {
  // 새 시장 응답을 3초 늦춘다 — 기다리는 동안 옛(국내) 행렬이 새 시장 값처럼 보이면 안 된다.
  await page.route("**/api/v1/macro/correlations?market=us", async (r) => { await new Promise((ok) => setTimeout(ok, 3000)); await r.fulfill({ status: 500, body: "x" }); });
  await open(page);
  await goTab2(page, "correlations");
  await expect(panel2(page, "correlations").locator(".mca-matrix")).toBeVisible();
  await panel2(page, "correlations").getByRole("button", { name: "미국 ETF" }).click();
  await expect(panel2(page, "correlations").locator(".mca-matrix")).toHaveCount(0, { timeout: 1500 });
  await expect(panel2(page, "correlations")).toContainText("계산 중");
  await expect(panel2(page, "correlations").locator('[role="alert"]')).toHaveCount(1, { timeout: 30_000 });
  await expect(panel2(page, "correlations").locator(".mca-matrix")).toHaveCount(0);
});
test("전략 상세 500 → 창 안 alert + 재시도 → 풀리면 상세", async ({ page }) => {
  await page.route("**/api/v1/macro/strategy/*?market=kr", (r) => r.fulfill({ status: 500, body: "x" }));
  const dlg = await openModal(page);
  await expect(dlg.locator('[role="alert"]')).toHaveCount(1, { timeout: 30_000 });
  await page.unroute("**/api/v1/macro/strategy/*?market=kr");
  await dlg.getByRole("button", { name: "재시도" }).click();
  await expect(dlg.locator(".sm-body")).toBeVisible({ timeout: 30_000 });
});
test("전략 AI 500 → 그 자리 alert(조용히 단추로 돌아가지 않는다)", async ({ page }) => {
  await page.route("**/api/v1/macro/strategy/*/ai**", (r) => r.fulfill({ status: 500, body: "x" }));
  const dlg = await openModal(page);
  await dlg.getByRole("button", { name: /AI 분석/ }).click();
  await expect(dlg.locator('.sm-ai [role="alert"]')).toHaveCount(1, { timeout: 30_000 });
});
for (const t of TABS2) {
  test(`정상이면 alert 0 — ${t}(짝)`, async ({ page }) => {
    await open(page);
    await goTab2(page, t);
    await expect(panel2(page, t).locator('[role="alert"]')).toHaveCount(0);
  });
}

// ── AA · 390 ──
for (const mode of ["light", "dark"] as const) {
  for (const t of TABS2) {
    test(`AA ${mode} — ${t}`, async ({ page }) => {
      await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, mode);
      await open(page);
      await goTab2(page, t);
      const r = await page.evaluate<AuditResult>(contrastAudit(`#mc-panel-${t}`));
      expect(r.checked).toBeGreaterThan(10);
      expect(r.low, `${mode} ${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
      if (mode === "dark") expect(r.bright, `${t} 밝은 판`).toEqual([]);
    });
  }
  test(`AA ${mode} — 전략 창`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, mode);
    await openModal(page);
    const r = await page.evaluate<AuditResult>(contrastAudit(".sm-modal"));
    expect(r.checked).toBeGreaterThan(10);
    expect(r.low, `${mode} 창: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (mode === "dark") expect(r.bright, "창 밝은 판").toEqual([]);
  });
}
for (const t of TABS2) {
  test(`390 — ${t} 가로 넘침 없음`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page);
    await goTab2(page, t);
    const over = await page.evaluate(() => {
      const m = document.querySelector(".terminal-main") as HTMLElement;
      return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
    });
    expect(over).toBeLessThanOrEqual(0);
  });
}

// ── 과거 성과 = 성과 그림 문법 (2026-11-09 · 성과 그림 문법 ③) ──────────────────────────────────────────────────────
test("전략 창 — 과거 성과는 곡선 + 낙폭 물속 · 낙폭 축 글자 = 서버 drawdown_pct · 실제 월말 날짜(어림 글 0) · 해마다 · 주요 낙폭 구간 · recharts 0", async ({ page }) => {
  await open(page);
  await goTab2(page, "strategies");
  const detailP = page.waitForResponse((r) => /\/api\/v1\/macro\/strategy\/[^/?]+(\?|$)/.test(r.url()), { timeout: 30_000 });
  await panel2(page, "strategies").locator(".mc-stratcard").first().click();
  const dlg = page.getByRole("dialog");
  const detail = await (await detailP).json() as { perf: { curve: unknown[]; drawdown_pct?: number[]; dates?: string[] | null; dates_note?: string | null;
    periods?: { yearly: unknown[] } | null; drawdowns?: unknown[] | null } };
  expect(detail.perf.curve.length, "곡선이 없으면 이 시험은 공허하다").toBeGreaterThan(1);
  const fig = dlg.locator(".sm-perf .pf-curve");
  await expect(fig).toBeVisible({ timeout: 30_000 });
  await expect(fig.locator(".pf-line-port")).toHaveCount(1);
  await expect(fig.locator(".pf-dd-area")).toHaveCount(1);
  // 낙폭 축 글자 = 서버 drawdown_pct 의 바닥(화면이 ×100 하지 않는다 — 비율을 넣으면 "-0%" 가 된다)
  const floor = Math.min(...(detail.perf.drawdown_pct ?? [0]));
  await expect(fig.locator(".pf-dd .pf-ytick")).toHaveText(`${floor.toFixed(0)}%`);
  // 실제 월말 날짜 — 서버가 주면 어림 글은 없고 해마다·낙폭 사건이 서버 행 수 그대로 붙는다(못 줄 때의 짝 — 글만·표 0 — 은 서버 시험 `tests/test_perf_compare.py`)
  expect(detail.perf.dates?.length, "연습 환경은 실제 월말 날짜를 준다 — 없으면 데이터 계층이 바뀐 것").toBe(detail.perf.curve.length);
  expect(detail.perf.dates_note ?? null).toBeNull();
  await expect(dlg.locator(".sm-perf .pf-strip-legend-note")).toHaveCount(0);
  await expect(dlg.locator(".sm-perf .pf-read")).toContainText((detail.perf.dates ?? [])[detail.perf.curve.length - 1].slice(0, 10));
  await expect(dlg.locator(".sm-perf .pf-table-years tbody tr")).toHaveCount(detail.perf.periods?.yearly.length ?? -1);
  await expect(dlg.locator(".sm-perf .pf-table-years th").last()).toHaveText("달");                       // 점이 달이라 '거래일'이 아니다
  await expect(dlg.locator(".sm-perf .pf-dd-eps tbody tr")).toHaveCount((detail.perf.drawdowns ?? []).length);
  if ((detail.perf.drawdowns ?? []).length) await expect(dlg.locator(".sm-perf .pf-dd-eps")).toHaveClass(/pf-dd-eps--compact/);   // 좁은 창 — 짧은 날짜
  await expect(dlg.locator(".sm-perf .pf-legend")).toContainText("시작값 100");
  await expect(dlg.locator(".sm-perf .pf-read")).toContainText("포트폴리오");
  await expect(dlg.locator(".sm-perf-stats .sm-perf-stat")).toHaveCount(5);                 // 지표 5 는 그대로
  await expect(dlg.locator(".sm-perf .recharts-wrapper")).toHaveCount(0);            // 성과 절에는 차트 라이브러리가 없다(보유 도넛도 이제 직접 SVG)
  await expect(dlg.locator(".sm-perf [title]")).toHaveCount(0);
});

// ── 읽는 줄 — 남은 매크로 그림(금리곡선 · 축 쌓기) (2026-11-10 · ADR 004 §6 — `<Tooltip>` 은 이제 한 곳도 없다) ──
const sgn3 = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3)}`;         // macroKo.signed(v, 3) 와 같은 서식
const ymS = (s: string) => { const m = /^(\d{4})-?(\d{2})/.exec(s); return m ? `${m[1]}.${m[2]}` : s; };   // macroKo.ym 과 같은 서식
type YcPoint = { label: string; yield_pct: number };
/** 금리곡선을 실은 응답(어느 경로가 싣는지에 묶이지 않는다 — 처음 온 것). */
function captureYield(page: Page): () => YcPoint[] | null {
  let pts: YcPoint[] | null = null;
  page.on("response", async (r) => {
    if (pts || !r.url().includes("/api/v1/macro/")) return;
    try { const p = (await r.json())?.yield_curve?.points; if (Array.isArray(p) && p.length) pts = p; } catch { /* JSON 이 아닌 응답 */ }
  });
  return () => pts;
}

test("읽는 줄 — 금리곡선(개요): 툴팁 0 · 처음 자리 = 서버 마지막 만기 · ← 로 앞 만기 · 표 쌍둥이 = 전부", async ({ page }) => {
  const got = captureYield(page);
  await open(page);
  const pnl = panel(page, "overview");
  const yc = frame(pnl, "yield-curve");
  await expect(yc.locator(".recharts-line-curve")).toBeVisible({ timeout: 30_000 });
  const pts = got();
  expect(pts?.length ?? 0, "곡선 점이 없으면 이 검사는 공허하다").toBeGreaterThan(3);
  await expect(pnl.locator(".recharts-tooltip-wrapper")).toHaveCount(0);
  const last = pts![pts!.length - 1], prev = pts![pts!.length - 2];
  await expect(yc.locator(".cr-head")).toHaveText(last.label);
  await expect(yc.locator(".cr-read")).toContainText(`수익률 ${last.yield_pct.toFixed(2)}%`);
  await yc.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(yc.locator(".cr-head")).toHaveText(prev.label);
  await expect(yc.locator(".cr-read")).toContainText(`수익률 ${prev.yield_pct.toFixed(2)}%`);
  await yc.locator(".cr-table summary").click();
  await expect(yc.locator(".cr-table tbody tr")).toHaveCount(pts!.length);
  await expect(pnl.locator("[title]")).toHaveCount(0);
});

test("읽는 줄 — 축 쌓기(국면 탭 · 성장·물가): 툴팁 0 · 처음 자리 = 서버 마지막 달 · 축 점수와 지표 기여 · ← 로 앞 달 · 표 쌍둥이 = 전부", async ({ page }) => {
  const axP = page.waitForResponse((r) => r.url().includes("/api/v1/macro/axis-history"), { timeout: 30_000 });
  await open(page);
  await goTab(page, "regime");
  type AxPt = { t: string; growth: number; inflation: number; growth_parts: Record<string, number>; inflation_parts: Record<string, number> };
  const ax = await (await axP).json() as { points: AxPt[] };
  expect(ax.points.length, "축 이력이 없으면 이 검사는 공허하다").toBeGreaterThan(3);
  const pnl = panel(page, "regime");
  const last = ax.points[ax.points.length - 1], prev = ax.points[ax.points.length - 2];
  for (const [axis, name] of [["growth", "성장 축"], ["inflation", "물가 축"]] as const) {
    const f = frame(pnl, `axis-stack-${axis}`);
    await expect(f.locator(".recharts-bar-rectangle").first()).toBeVisible({ timeout: 30_000 });
    const pk = `${axis}_parts` as const;
    const keys = [...new Set(ax.points.flatMap((p) => Object.keys(p[pk] ?? {})))];
    expect(keys.length, `${name}: 지표가 없으면 공허하다`).toBeGreaterThan(0);
    await expect(f.locator(".cr-head")).toHaveText(ymS(last.t));
    await expect(f.locator(".cr-read")).toContainText(`${name} 점수 ${sgn3(last[axis])}`);
    await expect(f.locator(".cr-item"), "읽는 줄 칸 = 축 점수 + 지표 수").toHaveCount(keys.length + 1);
    const k0 = keys.find((k) => typeof last[pk]?.[k] === "number")!;
    await expect(f.locator(".cr-read"), "지표 기여 = 서버 값").toContainText(sgn3(last[pk][k0]));
    await f.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(f.locator(".cr-head")).toHaveText(ymS(prev.t));
    await expect(f.locator(".cr-read")).toContainText(`${name} 점수 ${sgn3(prev[axis])}`);
    await f.locator(".cr-table summary").click();
    await expect(f.locator(".cr-table tbody tr")).toHaveCount(ax.points.length);
  }
  await expect(pnl.locator(".recharts-tooltip-wrapper"), "국면 탭의 그림 전부(금리곡선 포함)").toHaveCount(0);
  await expect(pnl.locator("[title]")).toHaveCount(0);
});
