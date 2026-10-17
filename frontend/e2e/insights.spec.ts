import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "fs";
import path from "path";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BU6 — 기업 분석 `/insights` 한 흐름 + 붙는 목차 (계획 "BU6 상세", 사용자 결정 2026-10-03)
// ─────────────────────────────────────────────────────────────────────────────
// ★먼저 써서 옛 화면(왼쪽 패널 + 영어 탭 7)에서 빨간 것을 기록한다★ 지키는 것:
//   · 답 한 문장 = 서버 값(evaluate 의 intrinsic_value·gap_pct) — 내재가치가 없으면 판단 없이 "계산하지 못했어요"
//   · ★시세가 없으면 주가 선을 지어 그리지 않는다★(옛 화면은 난수 경로를 "합성"으로 그렸다 — CLAUDE.md 위반)
//   · 실패(서버에 닿지 못함)와 "값이 없음"을 가른다 — evaluate 500 은 "재무 데이터 부족"이 아니다
//   · 판단(판정·괴리·점수)은 색으로 말하지 않는다 · 백분위는 수준 색 · 등락만 한국식 등락색
//   · 0 과 미상을 섞지 않는다(배당 0% ≠ 몰라요)
//   · 그림은 더할 뿐 지우지 않는다(옛 탭 일곱의 그림 수 이상)
// ═══════════════════════════════════════════════════════════════════════════════

const API = "**/api/backend/api/v1";
const SECS = ["value", "models", "numbers", "money", "risk", "peers", "factors", "ai"] as const;
const TOC = ["가치", "여러 모형", "핵심 숫자", "돈 버는 힘", "위험", "같은 업종", "팩터", "AI"];

async function open(page: Page, code = "005930") {
  await page.goto(`/insights?code=${code}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ci .ci-head h1")).toBeVisible({ timeout: 40_000 });
}

/** evaluate 기본 호출(영구성장 2% · 시장프리미엄 6%)의 응답만 고친다 — 낙관/보수 시나리오 호출은 그대로. */
async function patchBaseEval(page: Page, fn: (b: Record<string, unknown>) => void) {
  await page.route(`${API}/valuation/evaluate`, async (route) => {
    const req = route.request().postDataJSON() as { terminal_growth: number; market_premium: number };
    const res = await route.fetch();
    const body = await res.json();
    if (req.terminal_growth === 0.02 && req.market_premium === 0.06) fn(body);
    await route.fulfill({ response: res, json: body });
  });
}
const fail500 = { status: 500, contentType: "application/json", body: '{"detail":"boom"}' };

/** 흐름 끝까지 한 번 내려갔다가 올라온다 — 절은 화면에 들어올 때 불러온다. */
/** 절마다 차례로 화면에 넣는다(마우스 휠은 스크롤 상자 밖에서 구르면 아무것도 안 움직인다 — 그래서 직접 넣는다). */
async function scrollAll(page: Page) {
  for (const s of SECS) {
    await page.locator(`.ci-sec[data-sec=${s}]`).evaluate((e) => e.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(400);
  }
  await page.waitForTimeout(1500);
}

// ── 답 ──
test("답 = 서버 값 — evaluate 의 내재가치·괴리를 고치면 문장이 따라간다", async ({ page }) => {
  await patchBaseEval(page, (b) => { b.intrinsic_value = 92400; b.gap_pct = -23.16; b.verdict = "저평가"; });
  await open(page);
  const s = page.locator(".ci .tx-answer-s");
  await expect(s).toContainText("92,400원", { timeout: 40_000 });
  await expect(s).toContainText("23% 낮게");
});
test("답 짝 — 원래 응답 그대로면 그 값", async ({ page }) => {
  const evP = page.waitForResponse((r) => r.url().endsWith("/valuation/evaluate")
    && (r.request().postDataJSON() as { terminal_growth: number }).terminal_growth === 0.02
    && (r.request().postDataJSON() as { market_premium: number }).market_premium === 0.06);
  await open(page);
  const ev = (await (await evP).json()) as { intrinsic_value: number; gap_pct: number };
  const s = page.locator(".ci .tx-answer-s");
  await expect(s).toContainText(`${Math.round(ev.intrinsic_value).toLocaleString("ko-KR")}원`, { timeout: 40_000 });
  await expect(s).toContainText(`${Math.round(Math.abs(ev.gap_pct))}% ${ev.gap_pct < 0 ? "낮게" : "높게"}`);
});
test("내재가치가 없으면(0) 판단 없이 '계산하지 못했어요' — 0% 를 지어내지 않는다", async ({ page }) => {
  await patchBaseEval(page, (b) => { b.intrinsic_value = 0; b.gap_pct = 0; b.models = []; });
  await page.route(`${API}/screener/run-advanced`, async (route) => {
    const res = await route.fetch(); const body = await res.json();
    for (const it of body.items ?? []) { it.intrinsic_value = 0; it.gap_pct = 0; }
    await route.fulfill({ response: res, json: body });
  });
  await open(page);
  const s = page.locator(".ci .tx-answer-s");
  await expect(s).toContainText("계산하지 못했어요", { timeout: 40_000 });
  expect(await s.innerText()).not.toMatch(/%/);
});

// ── 연습용 표시 ──
// BU6a+: 연습용 칩 = connection-status ∨ evaluate is_mock(아래 BU6a+ 테스트가 is_mock 쪽을 건다). 여기서는 is_mock 을 false 로 묶고 connection-status 만 본다.
test("연습용 칩 — connection-status mock_allowed true 면 있다(짝: false 이고 응답도 연습용이 아니면 없다)", async ({ page }) => {
  await patchBaseEval(page, (b) => { b.is_mock = false; });
  await page.route(`${API}/macro/connection-status`, (r) => r.fulfill({ json: { mock_allowed: true, bok_configured: false, fred_configured: false } }));
  await open(page);
  await expect(page.locator(".ci .tx-answer .tx-chip[data-tone=practice]")).toHaveCount(1, { timeout: 30_000 });
  await page.unroute(`${API}/macro/connection-status`);
  await page.route(`${API}/macro/connection-status`, (r) => r.fulfill({ json: { mock_allowed: false, bok_configured: true, fred_configured: true } }));
  await open(page);
  await expect(page.locator(".ci .tx-answer")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  await expect(page.locator(".ci .tx-answer .tx-chip[data-tone=practice]")).toHaveCount(0);
});

// ── ★주가를 지어 그리지 않는다★ ──
test("★시세가 비면 주가 선이 없다★ — 합성 경로 대신 '시세가 아직 적재되지 않았어요'(짝: 정상은 선 1)", async ({ page }) => {
  await open(page);
  const fig = page.locator(".ci-sec[data-sec=value] .ci-pv");
  await expect(fig.locator(".recharts-line")).toHaveCount(1, { timeout: 40_000 });
  await page.route(`${API}/prices/**`, (r) => r.fulfill({ json: { ticker: "005930", count: 0, prices: [] } }));
  await open(page);
  await expect(page.locator(".ci-sec[data-sec=value] .ci-pv-noprice")).toContainText("시세가 아직 적재되지 않았어요", { timeout: 40_000 });
  expect(await page.locator(".ci-sec[data-sec=value] .ci-pv .recharts-line").count()).toBe(0);
  // 그림 자리에 "합성" 표시가 없다(서버가 보낸 출처 글 — 예: 무위험수익률 "연습용 합성 (mock)" — 은 `data-server` 라 여기서 보지 않는다).
  expect(await page.locator(".ci-sec[data-sec=value] .ci-pv").innerText()).not.toContain("합성");
  expect(await page.locator(".ca-mockbadge").count()).toBe(0);
});
test("시세 요청 실패(500) 는 '없음'이 아니라 실패 — 가치 절에 alert + 다시 시도", async ({ page }) => {
  await page.route(`${API}/prices/**`, (r) => r.fulfill(fail500));
  await open(page);
  const alert = page.locator(".ci-sec[data-sec=value] [role=alert]");
  await expect(alert.first()).toBeVisible({ timeout: 40_000 });
  await expect(alert.first().getByRole("button", { name: "다시 시도" })).toBeVisible();
});

// ── 실패 ≠ 값 없음 ──
test("★evaluate 500 → 가치 절 alert('데이터 부족'이 아니다)★ · 짝: 모형이 값을 못 낸 정상 응답은 사유 문장이고 alert 0", async ({ page }) => {
  await page.route(`${API}/valuation/evaluate`, (r) => r.fulfill(fail500));
  await open(page);
  const sec = page.locator(".ci-sec[data-sec=value]");
  await expect(sec.locator("[role=alert]").first()).toBeVisible({ timeout: 40_000 });
  expect(await sec.innerText()).not.toContain("재무 데이터 부족");
  await page.unroute(`${API}/valuation/evaluate`);
  await patchBaseEval(page, (b) => { b.models = []; });
  await open(page);
  await expect(sec.locator(".ci-models-none")).toBeVisible({ timeout: 40_000 });
  expect(await sec.locator(".ci-models [role=alert], .ci-models-none[role=alert]").count()).toBe(0);
});

// ── 목차 ──
test("붙는 목차 — 절 8개 · 누르면 그 절로 · 스크롤하면 지금 절 표시가 바뀐다", async ({ page }) => {
  await open(page);
  const items = page.locator(".ci-toc .ci-toc-item");
  await expect(items).toHaveCount(TOC.length);
  expect(await items.allInnerTexts()).toEqual(TOC);
  await expect(page.locator(".ci-sec")).toHaveCount(SECS.length);
  await items.filter({ hasText: "위험" }).click();
  await page.waitForTimeout(1200);
  const top = await page.locator(".ci-sec[data-sec=risk]").evaluate((e) => e.getBoundingClientRect().top);
  expect(top).toBeLessThan(260);
  await expect(page.locator(".ci-toc-item[aria-current=true]")).toHaveText("위험");
  await page.locator(".ci-sec[data-sec=factors]").scrollIntoViewIfNeeded();
  await page.locator(".ci-sec[data-sec=factors]").evaluate((e) => e.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(800);
  await expect(page.locator(".ci-toc-item[aria-current=true]")).toHaveText("팩터");
  // 목차는 붙어 있다(스크롤해도 화면 안)
  const tocTop = await page.locator(".ci-toc").evaluate((e) => e.getBoundingClientRect().top);
  expect(tocTop).toBeGreaterThanOrEqual(0);
  expect(tocTop).toBeLessThan(200);
});

// ── 겹친 그림 ──
test("주가와 가치 겹친 그림 — 가치 띠 수 + 그림 밖 목록 = 서버가 가용으로 낸 밴드 수, 주가 선 1", async ({ page }) => {
  const sbP = page.waitForResponse((r) => r.url().includes("/valuation-sandbox") || r.url().includes("/sandbox"));
  await open(page);
  const sb = (await (await sbP).json()) as { football_field: { bands: { available?: boolean; lo: number | null; hi: number | null }[] } };
  const avail = sb.football_field.bands.filter((b) => b.available !== false && b.lo != null && b.hi != null).length;
  const fig = page.locator(".ci-pv");
  await expect(fig.locator(".recharts-line")).toHaveCount(1, { timeout: 40_000 });
  const areas = await fig.locator(".recharts-reference-area").count();
  const outs = await fig.locator(".ci-pv-out li").count();
  expect(areas).toBeGreaterThan(0);
  expect(areas + outs).toBe(avail);
  await expect(fig.locator(".ci-pv-leg li")).toHaveCount(areas);
});

// ── 색 ──
const probe = (page: Page, v: string) => page.evaluate((vv) => {
  const s = document.createElement("span"); s.style.color = `var(${vv})`; document.body.appendChild(s);
  const c = getComputedStyle(s).color; s.remove(); return c;
}, v);
test("판정은 색으로 말하지 않는다 — 고평가·저평가 두 응답에서 판정 칩 색이 같다", async ({ page }) => {
  await open(page);
  const a = await page.locator(".ci-head .ci-verdict").evaluate((e) => getComputedStyle(e).color);
  await patchBaseEval(page, (b) => { b.intrinsic_value = 120000; b.gap_pct = -40.8; b.verdict = "저평가"; });
  await open(page);
  await expect(page.locator(".ci-head .ci-verdict")).toContainText("저평가", { timeout: 40_000 });
  const b = await page.locator(".ci-head .ci-verdict").evaluate((e) => getComputedStyle(e).color);
  expect(a).toBe(b);
  expect([await probe(page, "--tx-up-ink"), await probe(page, "--tx-down-ink"), await probe(page, "--color-bull"), await probe(page, "--color-bear")]).not.toContain(a);
});
test("팩터 백분위 막대는 수준 색(--mc-lv-*) — 등락·신호등 색이 아니다", async ({ page }) => {
  await open(page);
  await scrollAll(page);
  const fills = page.locator(".ci .ca-fbar-fill");
  await expect(fills.first()).toBeVisible({ timeout: 30_000 });
  const lv = await Promise.all(["neg-3", "neg-2", "neg-1", "mid", "pos-1", "pos-2", "pos-3"].map((k) => page.evaluate((kk) => {
    const s = document.createElement("span"); s.style.background = `var(--mc-lv-${kk})`; document.body.appendChild(s);
    const c = getComputedStyle(s).backgroundColor; s.remove(); return c;
  }, k)));
  const got = await fills.evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
  expect(got.length).toBeGreaterThan(3);
  for (const c of got) expect(lv, `수준 색이어야 한다: ${c}`).toContain(c);
});
test("추세 스파크라인은 등락색 — 오름 = --tx-up, 내림 = --tx-down", async ({ page }) => {
  await open(page);
  const sparks = page.locator(".ci-sec[data-sec=numbers] svg.ca-spark");
  await expect(sparks.first()).toBeVisible({ timeout: 30_000 });
  const up = await probe(page, "--tx-up"), dn = await probe(page, "--tx-down");
  const got = await sparks.evaluateAll((els) => els.map((e) => ({ dir: e.getAttribute("data-dir"), c: getComputedStyle(e.querySelector("polyline")!).stroke })));
  expect(got.length).toBeGreaterThan(0);
  for (const g of got) {
    if (g.dir === "up") expect(g.c).toBe(up);
    else if (g.dir === "down") expect(g.c).toBe(dn);
  }
});

// ── 0 ≠ 미상 ──
test("배당 0% 는 '0%'(짝: 값이 없으면 '몰라요') — 0 과 미상을 섞지 않는다", async ({ page }) => {
  await page.route(`${API}/screener/run-advanced`, async (route) => {
    const res = await route.fetch(); const body = await res.json();
    for (const it of body.items ?? []) { if (it.stock_code === "005930") { it.dividend_yield_pct = 0; it.debt_ratio_pct = null; } }
    await route.fulfill({ response: res, json: body });
  });
  await patchBaseEval(page, (b) => { const fs = (b.financial_summary ?? {}) as Record<string, unknown>; fs.debt_ratio_pct = null; b.financial_summary = fs; });
  await open(page);
  const nums = page.locator(".ci-sec[data-sec=numbers] .ci-num");
  await expect(nums.filter({ hasText: "배당" }).locator("dd")).toHaveText("0%", { timeout: 30_000 });
  await expect(nums.filter({ hasText: "부채비율" }).locator("dd")).toContainText("몰라요");
});

// ── 이동 ──
test("?code= 로 연 종목이 h1 · 설계에 넣기 = /allocation?tickers=그 코드 · 같은 업종 행을 누르면 그 종목", async ({ page }) => {
  await open(page, "000660");
  await expect(page.locator(".ci-head h1")).toContainText("SK하이닉스", { timeout: 40_000 });
  await expect(page.locator(".ci-head a.ci-bridge")).toHaveAttribute("href", "/allocation?tickers=000660");
  await page.locator(".ci-toc-item", { hasText: "같은 업종" }).click();
  const row = page.locator(".ci-sec[data-sec=peers] tr[data-code]:not(.self)").first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  const code = await row.getAttribute("data-code");
  await row.click();
  await expect(page.locator(".ci-head .ci-code")).toHaveText(code!, { timeout: 40_000 });
});

// ── 글 · 대비 · 390 ──
const BANNED = /\b(Overview|Valuation|Financials|Factors|Peers|Network|Football Field|Bull|Base|Bear|Comps|HOLD|BUY|SELL|Claude|ANTHROPIC_API_KEY|mock)\b/;
test("글 — 머리·답·가치·핵심 숫자 절: em-dash 0 · 영어 꼬리표 0 · 툴팁 0 · 고정폭은 식별자만", async ({ page }) => {
  await open(page);
  await expect(page.locator(".ci-pv .recharts-line")).toHaveCount(1, { timeout: 40_000 });
  await page.waitForTimeout(2500);
  const r = await page.locator(".ci").evaluate((root) => {
    const scope = Array.from(root.querySelectorAll(".ci-head, .tx-answer, .ci-toc, .ci-sec[data-sec=value], .ci-sec[data-sec=numbers]"));
    const texts: string[] = []; const mono: string[] = [];
    for (const sc of scope) {
      const walk = document.createTreeWalker(sc, NodeFilter.SHOW_TEXT);
      let n: Node | null;
      while ((n = walk.nextNode())) {
        const el = n.parentElement!; const s = (n.textContent ?? "").trim();
        if (!s || !el.getClientRects().length) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === "hidden") continue;
        if (!el.closest("[data-server]")) texts.push(s);
        if (/mono/i.test(cs.fontFamily) && !el.closest("[data-mono]")) mono.push(s.slice(0, 24));
      }
    }
    const titles = scope.reduce((k, sc) => k + Array.from(sc.querySelectorAll("[title]")).filter((e) => e.getAttribute("title")?.trim()).length
      + Array.from(sc.querySelectorAll("svg title")).filter((e) => e.textContent?.trim()).length, 0);
    return { texts, mono, titles, n: scope.length };
  });
  expect(r.n).toBeGreaterThanOrEqual(5);
  expect(r.texts.filter((s) => s.includes("—")), "보이는 em-dash").toEqual([]);
  expect(r.texts.filter((s) => BANNED.test(s)), "영어 꼬리표").toEqual([]);
  expect(r.titles, "title 툴팁").toBe(0);
  expect(r.mono, "고정폭(식별자 밖)").toEqual([]);
});
test("대비 — 라이트/다크 AA 미달 0 · 다크 밝은 판 0 (머리·답·가치·핵심 숫자)", async ({ page }) => {
  await open(page);
  await expect(page.locator(".ci-pv .recharts-line")).toHaveCount(1, { timeout: 40_000 });
  await page.waitForTimeout(2000);
  for (const sel of [".ci-head", ".ci .tx-answer", ".ci-sec[data-sec=value]", ".ci-sec[data-sec=numbers]"]) {
    const light = await page.evaluate<AuditResult>(contrastAudit(sel));
    expect(light.low, `${sel} 라이트`).toEqual([]);
  }
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(250);
  for (const sel of [".ci-head", ".ci .tx-answer", ".ci-sec[data-sec=value]", ".ci-sec[data-sec=numbers]"]) {
    const dark = await page.evaluate<AuditResult>(contrastAudit(sel));
    expect(dark.low, `${sel} 다크`).toEqual([]);
    expect(dark.bright, `${sel} 다크 밝은 판`).toEqual([]);
  }
});
test("390 — 가로 넘침 없음 · 목차는 가로로 밀리는 한 줄", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await expect(page.locator(".ci-pv")).toBeVisible({ timeout: 40_000 });
  await page.waitForTimeout(2000);
  const over = await page.evaluate(() => {
    const m = document.querySelector(".terminal-main") as HTMLElement;
    return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
  });
  expect(over).toBeLessThanOrEqual(0);
  const rows = await page.locator(".ci-toc .ci-toc-item").evaluateAll((els) => new Set(els.map((e) => Math.round(e.getBoundingClientRect().top))).size);
  expect(rows).toBe(1);
});

// ── 그림 보존(사용자 규칙 2: 시각화는 더하거나 바꿀 뿐 지우지 않는다) ──
// 옛 화면(왼쪽 패널 + 탭 7)을 탭마다 눌러 잰 값: svg 20 + 패널 1 = 21 · 막대 160 (`scratchpad/bu6/viz_old.txt`).
// 겹친 그림(주가 + 가치 띠)이 더해졌고 종합점수 링은 게이지와 같은 값이라 합쳤다 — 그래도 합계가 옛 값 이상이어야 한다.
test("그림 보존 — 흐름 전체(자세히 펼침)의 그림·막대 수가 옛 탭 일곱의 합 이상", async ({ page }) => {
  await open(page);
  await expect(page.locator(".ci-pv .recharts-line")).toHaveCount(1, { timeout: 40_000 });
  await scrollAll(page);
  await expect(page.locator(".ci-sec[data-sec=risk] .ca-cp-riskcard").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".ci-sec[data-sec=models] .ci-mcard[data-model=eva] .ci-eva-col").first()).toBeVisible({ timeout: 40_000 });
  await expect(page.locator(".ci-sec[data-sec=risk] .ci-torn-row").first()).toBeVisible({ timeout: 40_000 });
  await page.evaluate(() => document.querySelectorAll(".ci details").forEach((d) => { (d as HTMLDetailsElement).open = true; }));
  await scrollAll(page);
  await page.waitForTimeout(3000);
  const n = await page.evaluate(() => {
    const root = document.querySelector(".ci")!;
    const svg = Array.from(root.querySelectorAll("svg")).filter((s) => !s.classList.contains("lucide") && !s.closest(".ci-toc")).length;
    // BU6b: 알트만 기여 막대는 .ca-fd-wf-bar(옛 재무 막대 클래스 재사용)에서 .ci-alt-bar 로 — 같은 막대를 이름만 바꿔 센다.
    const bars = root.querySelectorAll(".ca-fbar-track, .ca-ff2-bar, .ca-fd-wf-bar, .ci-alt-bar, .ca-heat-c, .ca-cp-catbar i, .ca-cp-judge-row i, .ca-band-track").length;
    return { svg, bars };
  });
  expect(n.svg, `svg ${JSON.stringify(n)}`).toBeGreaterThanOrEqual(21);
  expect(n.bars, `막대 ${JSON.stringify(n)}`).toBeGreaterThanOrEqual(160);
  // BU6a+ 에서 더한 그림 — 하나라도 사라지면 빨강(모형 한눈에 12줄 · 분위 띠 · 히스토그램 · 층/성장률 막대 · 연도별 EVA · 배수 점 줄 · 시나리오 · 매크로 토네이도 · 레일 미니).
  const added = await page.evaluate(() => Object.fromEntries([
    ".ci-sec[data-sec=value] .ci-lad-row", ".ci-q-row", ".ci-histo-bars i", ".ci-hbar", ".ci-eva-col", ".ci-strip", ".ci-scen-row", ".ci-torn-row", ".ci-rail .ci-lad-row",
    // BU6b 에서 더한 그림 — 이야기 그림 막대 · 요약 카드 추세 · 알트만 구간 점 · 팩터 점 지도
    ".ci-story .recharts-bar-rectangle", ".ci-sumcard svg.ca-spark", ".ci-alt-dot", ".ci-fmap-dot",
  ].map((sel) => [sel, document.querySelectorAll(sel).length])));
  expect(added[".ci-sec[data-sec=value] .ci-lad-row"], JSON.stringify(added)).toBeGreaterThanOrEqual(12);
  for (const [sel, k] of Object.entries(added)) expect(k, `${sel} ${JSON.stringify(added)}`).toBeGreaterThan(0);
});

// ═══════════════════════════════════════════════════════════════════════════════
// BU6a+ — 백엔드 가치 모형 여덟 · 모형 한눈에 · 미니 머리 · 오른쪽 레일 · 매크로 민감도 (사용자 피드백 2026-10-03)
// ★먼저 써서 BU6a 화면에서 빨강을 본다★ 지키는 것: 모형 문장 = 서버 값 · 못 낸 모형은 사유(지우지 않음) · 실패는 그 카드 alert ·
// 가정형 셋(의사결정 나무·SOTP·실물옵션)은 여기서 돌리지 않는다(기본값이 회사와 무관한 숫자) · 전일 대비는 시세 두 종가에서만
// ═══════════════════════════════════════════════════════════════════════════════
const CO = `${API}/company/*`;
async function openModels(page: Page, code = "005930") {
  await open(page, code);
  await page.locator(".ci-toc-item", { hasText: "여러 모형" }).click();
  await expect(page.locator(".ci-sec[data-sec=models] .ci-mcard").first()).toBeVisible({ timeout: 40_000 });
}
async function patchJson(page: Page, pattern: string, fn: (b: Record<string, unknown>) => void) {
  await page.route(pattern, async (route) => {
    const res = await route.fetch(); const body = await res.json(); fn(body);
    await route.fulfill({ response: res, json: body });
  });
}
const card = (page: Page, m: string) => page.locator(`.ci-sec[data-sec=models] .ci-mcard[data-model=${m}]`);

test("여러 모형 — 역DCF 문장 = 서버 implied·current 성장률(고치면 따라간다)", async ({ page }) => {
  await patchJson(page, `${CO}/reverse-dcf*`, (b) => { b.available = true; b.implied_growth_pct = 12.34; b.current_growth_pct = 2.5; });
  await openModels(page);
  const ans = card(page, "rdcf").locator(".ci-mcard-ans");
  await expect(ans).toContainText("12.3%", { timeout: 40_000 });
  await expect(ans).toContainText("2.5%");
});
test("여러 모형 — 가치 분포: 현재가 백분위 문장 = 서버 값 · 흔든 폭이 잰 값이 아니면 '가정' 칩", async ({ page }) => {
  await patchJson(page, `${CO}/valuation-distribution*`, (b) => { (b.unified as Record<string, unknown>).price_percentile = 37.6; });
  await openModels(page);
  const c = card(page, "dist");
  await expect(c.locator(".ci-mcard-ans")).toContainText("38번째", { timeout: 40_000 });
  await expect(c.locator(".tx-chip[data-tone=assumed]")).toHaveCount(1);
});
test("여러 모형 — 시나리오 가중: '현재가보다 높을 확률' = 서버 값 · 확률은 사람이 정한 값(가정 칩)", async ({ page }) => {
  await patchJson(page, `${CO}/models/scenarios`, (b) => { b.prob_above_price = 0.25; });
  await openModels(page);
  const c = card(page, "scenarios");
  await expect(c.locator(".ci-mcard-ans")).toContainText("25%", { timeout: 40_000 });
  await expect(c.locator(".tx-chip[data-tone=assumed]").first()).toBeVisible();
});
test("★못 낸 모형은 사유 — 숫자를 지어내지 않고 alert 도 아니다★ (EVA available:false)", async ({ page }) => {
  await page.route(`${CO}/models/eva`, (r) => r.fulfill({ json: { available: false, reason: "재무 연도가 둘보다 적어 EVA 를 재지 못했어요", code: "005930", is_mock: true } }));
  await openModels(page);
  const c = card(page, "eva");
  await expect(c.locator(".ci-mcard-reason")).toContainText("재무 연도가 둘보다 적어", { timeout: 40_000 });
  expect(await c.locator("[role=alert]").count()).toBe(0);
  expect(await c.locator(".ci-mcard-ans").count()).toBe(0);
});
test("★모형 요청 실패(500)는 그 카드 alert + 다시 시도 → 풀면 회복★ · 짝: 다른 카드는 alert 0", async ({ page }) => {
  let fail = true;
  await page.route(`${CO}/models/multiples`, (r) => (fail ? r.fulfill(fail500) : r.continue()));
  await openModels(page);
  const c = card(page, "multiples");
  await expect(c.locator("[role=alert]")).toBeVisible({ timeout: 40_000 });
  expect(await card(page, "rdcf").locator("[role=alert]").count()).toBe(0);
  fail = false;
  await c.getByRole("button", { name: "다시 시도" }).click();
  await expect(c.locator(".ci-mcard-ans, .ci-mcard-reason").first()).toBeVisible({ timeout: 40_000 });
  expect(await c.locator("[role=alert]").count()).toBe(0);
});
test("★가정형 셋은 여기서 돌리지 않는다★ — 라우트 요청 0 · [캔버스에서 넣기] = /allocation?company=그 코드", async ({ page }) => {
  const hits: string[] = [];
  page.on("request", (r) => { if (/\/models\/(sotp|decision-tree|real-option)/.test(r.url())) hits.push(r.url()); });
  await openModels(page);
  await page.waitForTimeout(3000);
  const need = page.locator(".ci-sec[data-sec=models] .ci-mneed");
  await expect(need.locator("li")).toHaveCount(3);
  await expect(need.locator("a.ci-mneed-go")).toHaveAttribute("href", "/allocation?company=005930");
  expect(hits).toEqual([]);
});
test("캔버스 다리 ?company= — 기업 하나 깊게 흐름이 그 코드로 열린다(짝: 모르는 코드는 싣지 않는다)", async ({ page }) => {
  await page.goto("/allocation?company=005930", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node[data-kind=company_valuation]")).toHaveCount(1, { timeout: 40_000 });
  await expect(page.locator(".pg-file-note")).toContainText("기업 하나 깊게");
  // 짝 — 캔버스는 작업 중 문서를 이 탭(sessionStorage)에 저장해 둔다. 비우고 모르는 코드로 열면 그 흐름이 실리지 않고 메모가 말한다.
  await page.evaluate(() => { try { sessionStorage.clear(); localStorage.clear(); } catch { /* noop */ } });
  await page.goto("/allocation?company=999999", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-file-note")).toContainText("알 수 없는 코드 999999", { timeout: 40_000 });
  expect(await page.locator(".pg-node[data-kind=company_valuation]").count()).toBe(0);
});

test("모형 한눈에 — 줄마다 점 또는 사유 · 현재가 선 1 · 'n개 중 m개' = 세어 본 값 · 못 낸 모형도 줄이 남는다", async ({ page }) => {
  await page.route(`${CO}/models/eva`, (r) => r.fulfill({ json: { available: false, reason: "EVA 를 재지 못했어요(시험)", code: "005930", is_mock: true } }));
  await openModels(page);
  const lad = page.locator(".ci-sec[data-sec=value] .ci-ladder");
  await expect(lad.locator(".ci-lad-row[data-key=eva] .ci-lad-reason")).toContainText("재지 못했어요", { timeout: 40_000 });
  await page.waitForTimeout(4000);
  const rows = await lad.locator(".ci-lad-row").evaluateAll((els) => els.map((e) => ({
    dots: e.querySelectorAll(".ci-lad-dot").length, reason: !!e.querySelector(".ci-lad-reason"), wait: !!e.querySelector(".ci-lad-wait"),
  })));
  expect(rows.length).toBeGreaterThanOrEqual(8);
  for (const r of rows) expect(r.dots > 0 || r.reason || r.wait).toBe(true);
  await expect(lad.locator(".ci-lad-price")).toHaveCount(1);
  const price = Number(await lad.getAttribute("data-price"));
  const vals = await lad.locator(".ci-lad-dot[data-main]").evaluateAll((els) => els.map((e) => Number(e.getAttribute("data-v"))));
  const below = vals.filter((v) => v < price).length;
  await expect(lad.locator(".ci-lad-sum")).toContainText(`${vals.length}개 중 ${below}개`);
});

test("미니 머리 — 위에선 없고 내려가면 붙는다 · 전일 대비 = 시세 마지막 두 종가(짝: 종가 하나면 표시 없음)", async ({ page }) => {
  await page.route(`${API}/prices/**`, (r) => r.fulfill({ json: { ticker: "005930", count: 3, prices: [
    { date: "2026-09-29", close: 70000 }, { date: "2026-09-30", close: 70000 }, { date: "2026-10-01", close: 71400 }] } }));
  await open(page);
  await page.waitForTimeout(1000);
  await expect(page.locator(".ci-mini")).toBeHidden();
  await page.locator(".ci-sec[data-sec=numbers]").evaluate((e) => e.scrollIntoView({ block: "start" }));
  const mini = page.locator(".ci-mini");
  await expect(mini).toBeVisible({ timeout: 10_000 });
  await expect(mini.locator(".ci-mini-name")).toContainText("삼성전자");
  const chg = mini.locator(".ci-mini-chg");
  await expect(chg).toContainText("+2.00%");
  await expect(chg).toHaveAttribute("data-dir", "up");
  expect(await chg.evaluate((e) => getComputedStyle(e).color)).toBe(await probe(page, "--tx-up-ink"));
  await page.unroute(`${API}/prices/**`);
  await page.route(`${API}/prices/**`, (r) => r.fulfill({ json: { ticker: "005930", count: 1, prices: [{ date: "2026-10-01", close: 71400 }] } }));
  await open(page);
  await page.locator(".ci-sec[data-sec=numbers]").evaluate((e) => e.scrollIntoView({ block: "start" }));
  await expect(page.locator(".ci-mini")).toBeVisible({ timeout: 10_000 });
  expect(await page.locator(".ci-mini .ci-mini-chg").count()).toBe(0);
});

test("오른쪽 레일 — 1440 에선 보이고 내려가도 화면 안 · 같은 업종을 누르면 그 종목(짝: 1180 에선 없다)", async ({ page }) => {
  await open(page);
  const rail = page.locator(".ci-rail");
  await expect(rail).toBeVisible({ timeout: 30_000 });
  await page.locator(".ci-sec[data-sec=factors]").evaluate((e) => e.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(500);
  const r = await rail.evaluate((e) => { const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, h: window.innerHeight }; });
  expect(r.top).toBeGreaterThanOrEqual(0);
  expect(r.top).toBeLessThan(r.h);
  const peer = rail.locator(".ci-rail-peer[data-code]:not([aria-current=true])").first();
  await expect(peer).toBeVisible({ timeout: 30_000 });
  const code = await peer.getAttribute("data-code");
  await peer.click();
  await expect(page.locator(".ci-head .ci-code")).toHaveText(code!, { timeout: 40_000 });
  await page.setViewportSize({ width: 1180, height: 900 });
  await page.waitForTimeout(400);
  await expect(rail).toBeHidden();
});

test("매크로 민감도(위험 절) — 막대 수 = 서버 가용 충격 수 · 가치가 오르면 등락 빨강, 내리면 파랑 · 못 잰 충격은 사유", async ({ page }) => {
  const mP = page.waitForResponse((r) => r.url().includes("/macro-sensitivity"), { timeout: 60_000 });
  await open(page);
  await page.locator(".ci-toc-item", { hasText: "위험" }).click();
  const m = (await (await mP).json()) as { rows: { available: boolean; value_pct: number | null }[]; unavailable: unknown[] };
  const box = page.locator(".ci-sec[data-sec=risk] .ci-macro");
  const avail = m.rows.filter((x) => x.available && x.value_pct != null);
  await expect(box.locator(".ci-macro-bar")).toHaveCount(avail.length, { timeout: 30_000 });
  const up = await probe(page, "--tx-up"), dn = await probe(page, "--tx-down");
  const got = await box.locator(".ci-macro-bar").evaluateAll((els) => els.map((e) => ({ d: e.getAttribute("data-dir"), c: getComputedStyle(e).backgroundColor })));
  for (const g of got) expect(g.c).toBe(g.d === "up" ? up : dn);
  await expect(box.locator(".ci-macro-na li")).toHaveCount(m.unavailable.length);
});

test("연습용 칩 — 응답의 is_mock 도 본다(connection-status 가 false 여도) · 짝: 둘 다 false 면 없다", async ({ page }) => {
  await page.route(`${API}/macro/connection-status`, (r) => r.fulfill({ json: { mock_allowed: false, bok_configured: true, fred_configured: true } }));
  await patchBaseEval(page, (b) => { b.is_mock = true; });
  await open(page);
  await expect(page.locator(".ci .tx-answer .tx-chip[data-tone=practice]")).toHaveCount(1, { timeout: 30_000 });
  await page.unroute(`${API}/valuation/evaluate`);
  await patchBaseEval(page, (b) => { b.is_mock = false; });
  await open(page);
  await expect(page.locator(".ci .tx-answer")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  await expect(page.locator(".ci .tx-answer .tx-chip[data-tone=practice]")).toHaveCount(0);
});

test("가정 차이를 말한다 — 머리 문장(무위험 3.5%·베타 1.0 고정)과 아래 모형(실측 기본값)의 가정이 다르다는 줄", async ({ page }) => {
  await open(page);
  const d = page.locator(".ci-sec[data-sec=value] .ci-assume-diff");
  await expect(d).toContainText("3.5%", { timeout: 40_000 });
  await expect(d).toContainText("1.0");
});

test("여러 모형·레일·미니 머리 — 글(em-dash·영어·툴팁) · 라이트/다크 AA · 390 넘침 0", async ({ page }) => {
  await openModels(page);
  await page.waitForTimeout(6000);
  const r = await page.locator(".ci-sec[data-sec=models]").evaluate((root) => {
    const texts: string[] = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n: Node | null;
    while ((n = walk.nextNode())) {
      const el = n.parentElement!; const s = (n.textContent ?? "").trim();
      if (!s || !el.getClientRects().length || el.closest("[data-server]")) continue;
      texts.push(s);
    }
    return { texts, titles: root.querySelectorAll("[title]").length + Array.from(root.querySelectorAll("svg title")).filter((e) => e.textContent?.trim()).length };
  });
  expect(r.texts.filter((s) => s.includes("—"))).toEqual([]);
  expect(r.texts.filter((s) => BANNED.test(s))).toEqual([]);
  expect(r.titles).toBe(0);
  for (const sel of [".ci-sec[data-sec=models]", ".ci-rail", ".ci-mini"]) {
    const light = await page.evaluate<AuditResult>(contrastAudit(sel));
    expect(light.low, `${sel} 라이트`).toEqual([]);
  }
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(250);
  for (const sel of [".ci-sec[data-sec=models]", ".ci-rail", ".ci-mini"]) {
    const dark = await page.evaluate<AuditResult>(contrastAudit(sel));
    expect(dark.low, `${sel} 다크`).toEqual([]);
    expect(dark.bright, `${sel} 다크 밝은 판`).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(600);
  const over = await page.evaluate(() => {
    const m = document.querySelector(".terminal-main") as HTMLElement;
    return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
  });
  expect(over).toBeLessThanOrEqual(0);
});

// ═══════════════════════════════════════════════════════════════════════════════
// BU6b — 돈 버는 힘·위험·같은 업종·팩터·AI 절 안쪽 (계획 "BU6b 상세" · 사용자 결정: 이야기 그림 먼저 + 표는 펼침 · 백분위 점 지도 + 목록은 펼침)
// ★먼저 써서 BU6a+ 화면에서 빨강을 본다★ 지키는 것: 답 문장 = 서버 값 · 실패(닿지 못함)와 없음(서버가 못 했다고 답함)을 가른다 ·
// 0 과 미상을 섞지 않는다 · 비교 표본이 없으면 백분위를 지어내지 않는다(옛 코드는 50) · 판단은 중립, 수준은 수준 색 · 그림은 지우지 않는다
// 재무·위험 심화는 연습용 서버에서 미적재라 `fixtures/*.json` 고정 응답으로 채운다(모양은 `src/engine/company_analytics.py` 와 같다).
// ═══════════════════════════════════════════════════════════════════════════════
const FX_FIN = JSON.parse(readFileSync(path.join(__dirname, "fixtures/financial-deep.json"), "utf8")) as Record<string, unknown>;
const FX_RISK = JSON.parse(readFileSync(path.join(__dirname, "fixtures/risk-deep.json"), "utf8")) as Record<string, unknown>;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const sec = (page: Page, s: string) => page.locator(`.ci-sec[data-sec=${s}]`);
async function goSec(page: Page, s: string, label: string) {
  await page.locator(".ci-toc-item", { hasText: label }).first().click();
  await sec(page, s).evaluate((e) => e.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(500);
}
async function deep(page: Page, fin: unknown = FX_FIN, risk: unknown = FX_RISK) {
  await page.route(`${CO}/financial-deep`, (r) => r.fulfill({ json: fin }));
  await page.route(`${CO}/risk-deep*`, (r) => r.fulfill({ json: risk }));
}
/** 연도 재무 응답(내림차순) 고치기 — 분기 요청은 그대로. */
async function patchAnnual(page: Page, fn: (rows: Record<string, unknown>[]) => void) {
  await page.route(`${API}/valuation/financial/*`, async (route) => {
    const res = await route.fetch(); const body = await res.json();
    if (route.request().url().includes("period=annual")) fn(body.financials ?? []);
    await route.fulfill({ response: res, json: body });
  });
}
const visibleTexts = (root: Element) => {
  const out: string[] = [];
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n: Node | null;
  while ((n = walk.nextNode())) {
    const el = n.parentElement!; const s = (n.textContent ?? "").trim();
    if (!s || !el.getClientRects().length || el.closest("[data-server]")) continue;
    out.push(s);
  }
  return out;
};

// ── 돈 버는 힘 ──
test("돈 버는 힘 — 답 문장 = 서버 첫·마지막 해 매출(고치면 따라간다) · 짝: 줄면 '줄었어요'", async ({ page }) => {
  await patchAnnual(page, (rows) => {
    const ys = rows.map((r) => Number(r.year)); const lo = Math.min(...ys), hi = Math.max(...ys);
    for (const r of rows) { if (Number(r.year) === lo) r["revenue_억"] = 12345; if (Number(r.year) === hi) r["revenue_억"] = 23456; }
  });
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  const a = sec(page, "money").locator(".ci-money-ans");
  await expect(a).toContainText("1.2조원", { timeout: 30_000 });
  await expect(a).toContainText("2.3조원");
  await expect(a).toContainText("늘었어요");
  await page.unroute(`${API}/valuation/financial/*`);
  await patchAnnual(page, (rows) => {
    const ys = rows.map((r) => Number(r.year)); const lo = Math.min(...ys), hi = Math.max(...ys);
    for (const r of rows) { if (Number(r.year) === lo) r["revenue_억"] = 23456; if (Number(r.year) === hi) r["revenue_억"] = 12345; }
  });
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  await expect(sec(page, "money").locator(".ci-money-ans")).toContainText("줄었어요", { timeout: 30_000 });
});
test("돈 버는 힘 — 이야기 그림(매출 막대 = 연도 수 · 이익률 선 둘 + 글자 범례) · 표는 접혀 있고 펼치면 9줄 · '항목(억원)' 거짓 단위 0", async ({ page }) => {
  const finP = page.waitForResponse((r) => r.url().includes("/valuation/financial/") && r.url().includes("period=annual"));
  await open(page);
  const n = ((await (await finP).json()).financials ?? []).length as number;
  await goSec(page, "money", "돈 버는 힘");
  const story = sec(page, "money").locator(".ci-story");
  await expect(story.locator(".recharts-bar-rectangle")).toHaveCount(n, { timeout: 30_000 });
  await expect(story.locator(".recharts-line")).toHaveCount(2);
  await expect(sec(page, "money").locator(".ci-story-key")).toContainText(["매출"]);
  await expect(sec(page, "money").locator(".ci-story-key")).toContainText(["영업이익률"]);
  const more = sec(page, "money").locator("details.ci-fin-more");
  await expect(more).toHaveCount(1);
  expect(await more.evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
  await expect(sec(page, "money").locator("table.ca-cp-fin")).toBeHidden();
  await more.locator("summary").click();
  await expect(sec(page, "money").locator("table.ca-cp-fin tbody tr")).toHaveCount(9);
  await expect(sec(page, "money").locator("table.ca-cp-fin thead th").first()).toHaveText("항목");
  expect(await sec(page, "money").innerText()).not.toContain("억원)");
});
test("돈 버는 힘 — 모르는 해 매출은 '몰라요'(0억 아님) · 연도 재무 500 은 alert + 다시 시도('자료가 없어요' 아님)", async ({ page }) => {
  await patchAnnual(page, (rows) => { rows[1]["revenue_억"] = null; });
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  await sec(page, "money").locator("details.ci-fin-more summary").click();
  const row = sec(page, "money").locator("table.ca-cp-fin tbody tr").first();
  await expect(row.locator("td")).toContainText(["몰라요"], { timeout: 30_000 });
  await page.unroute(`${API}/valuation/financial/*`);
  await page.route(`${API}/valuation/financial/*`, (r) => (r.request().url().includes("period=annual") ? r.fulfill(fail500) : r.continue()));
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  await expect(sec(page, "money").locator("[role=alert]").first()).toBeVisible({ timeout: 30_000 });
  await expect(sec(page, "money").getByRole("button", { name: "다시 시도" }).first()).toBeVisible();
});
test("재무 심화 — 이익의 질 두 선 + 글자 범례 · 경고는 '주의' 칩 + 서버 문장 · 자본비용 대비 이익률은 중립색 + 부호(짝: 음수도 같은 색)", async ({ page }) => {
  const neg = clone(FX_FIN) as { roic_wacc: { spread: number; verdict: string } };
  await deep(page);
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  const fd = sec(page, "money").locator(".ci-fd");
  await expect(fd.locator(".ci-fd-qoe svg.ca-fd-mini polyline")).toHaveCount(2, { timeout: 30_000 });
  await expect(fd.locator(".ci-fd-qoe .ci-fd-key")).toContainText(["순이익", "영업현금흐름"]);
  await expect(fd.locator(".ci-fd-flag")).toHaveCount(1);
  await expect(fd.locator(".ci-fd-flag")).toContainText("주의");
  const sp = fd.locator(".ci-fd-spread");
  await expect(sp).toHaveText("+1.72%p");
  const c1 = await sp.evaluate((e) => getComputedStyle(e).color);
  expect(c1).toBe(await probe(page, "--tx-ink"));
  neg.roic_wacc.spread = -2.4; neg.roic_wacc.verdict = "가치 훼손 (ROIC < WACC)";
  await page.unroute(`${CO}/financial-deep`);
  await page.route(`${CO}/financial-deep`, (r) => r.fulfill({ json: neg }));
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  const sp2 = sec(page, "money").locator(".ci-fd-spread");
  await expect(sp2).toHaveText("−2.40%p", { timeout: 30_000 });
  expect(await sp2.evaluate((e) => getComputedStyle(e).color)).toBe(c1);
});
test("★재무 심화 500 → alert + 다시 시도 → 풀면 그림★ · 짝: 미적재(available:false)는 사람 말 사유이고 alert 0", async ({ page }) => {
  await page.route(`${CO}/financial-deep`, (r) => r.fulfill(fail500));
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  const fd = sec(page, "money").locator(".ci-fd");
  await expect(fd.locator("[role=alert]")).toBeVisible({ timeout: 30_000 });
  expect(await fd.innerText()).not.toMatch(/failed|로드 실패/);
  await page.unroute(`${CO}/financial-deep`);
  await page.route(`${CO}/financial-deep`, (r) => r.fulfill({ json: FX_FIN }));
  await fd.getByRole("button", { name: "다시 시도" }).click();
  await expect(fd.locator(".ci-fd-qoe")).toBeVisible({ timeout: 30_000 });
  await page.unroute(`${CO}/financial-deep`);
  await open(page);
  await goSec(page, "money", "돈 버는 힘");
  await expect(sec(page, "money").locator(".ci-fd .ci-fd-reason")).toContainText("적재되지 않아", { timeout: 30_000 });
  await expect(sec(page, "money").locator(".ci-fd [role=alert]")).toHaveCount(0);
});

// ── 위험 ──
test("부도 위험 점수(알트만 Z) — 구간 막대의 점 위치 = 서버 z · 경계 1.8·3.0 · 짝: z 를 바꾸면 점이 움직인다 · 기여 막대는 한 색", async ({ page }) => {
  await deep(page);
  await open(page);
  await goSec(page, "risk", "위험");
  const alt = sec(page, "risk").locator(".ci-alt");
  const dot = alt.locator(".ci-alt-dot");
  await expect(dot).toHaveAttribute("data-v", "2.09", { timeout: 30_000 });
  const left = (await dot.evaluate((e) => (e as HTMLElement).style.left));
  expect(parseFloat(left)).toBeCloseTo((2.09 / 5) * 100, 0);
  await expect(alt.locator(".ci-alt-tick")).toContainText(["1.8", "3.0"]);
  await expect(alt.locator(".ci-alt-zone[data-server]")).toHaveText("회색지대 (1.8~3.0)");
  const bars = await alt.locator(".ci-alt-bar").evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
  expect(bars.length).toBe(5);
  expect(new Set(bars).size).toBe(1);
  expect(await alt.innerText()).not.toMatch(/\bX[1-5]\b/);
  const r2 = clone(FX_RISK) as { altman: { z: number; zone: string } };
  r2.altman.z = 3.6; r2.altman.zone = "안전 (>3.0)";
  await page.unroute(`${CO}/risk-deep*`);
  await page.route(`${CO}/risk-deep*`, (r) => r.fulfill({ json: r2 }));
  await open(page);
  await goSec(page, "risk", "위험");
  const dot2 = sec(page, "risk").locator(".ci-alt-dot");
  await expect(dot2).toHaveAttribute("data-v", "3.6", { timeout: 30_000 });
  expect(parseFloat(await dot2.evaluate((e) => (e as HTMLElement).style.left))).toBeCloseTo(72, 0);
});
test("위험 심화 — 이익 조작 점검 8줄(근거 칩) · 금리 충격 표는 원 · 모르는 값 '몰라요'(₩·— 0) · 커버리지 범례는 글자", async ({ page }) => {
  await deep(page);
  await open(page);
  await goSec(page, "risk", "위험");
  const rd = sec(page, "risk").locator(".ci-rd");
  await expect(rd.locator(".ci-ben tbody tr")).toHaveCount(8, { timeout: 30_000 });
  await expect(rd.locator(".ci-ben .ci-basis")).toHaveCount(8);
  const st = rd.locator(".ci-stress");
  await expect(st).toContainText("20,596원");
  await expect(st).toContainText("몰라요");
  const t = await rd.innerText();
  expect(t).not.toContain("₩");
  await expect(rd.locator(".ci-cov .ci-fd-key")).toContainText(["이자보상배율", "순부채/EBITDA"]);
  expect(t).not.toMatch(/\((검정|파랑)\)/);
});
test("★위험 심화 500 → alert + 다시 시도 → 회복★ · 시세 500 이면 '시세로 잰 위험'도 alert(계산할 수 없다는 사유가 아니다)", async ({ page }) => {
  await page.route(`${CO}/risk-deep*`, (r) => r.fulfill(fail500));
  await open(page);
  await goSec(page, "risk", "위험");
  const rd = sec(page, "risk").locator(".ci-rd");
  await expect(rd.locator("[role=alert]")).toBeVisible({ timeout: 30_000 });
  await page.unroute(`${CO}/risk-deep*`);
  await page.route(`${CO}/risk-deep*`, (r) => r.fulfill({ json: FX_RISK }));
  await rd.getByRole("button", { name: "다시 시도" }).click();
  await expect(rd.locator(".ci-alt-dot")).toBeVisible({ timeout: 30_000 });
  await page.unroute(`${CO}/risk-deep*`);
  await page.route(`${API}/prices/*`, (r) => r.fulfill(fail500));
  // 시세 다음 차례(백엔드 VaR)는 "그 종목 일봉 없음"(404)으로 묶는다 — 그래야 alert 가 시세 실패에서만 나온다(변이: 시세 실패를 [] 로 삼키면 사유가 되고 alert 0).
  await page.route("**/calculate-var", (r) => r.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"no bars"}' }));
  await open(page);
  await goSec(page, "risk", "위험");
  await expect(sec(page, "risk").locator(".ci-mrisk [role=alert]")).toBeVisible({ timeout: 30_000 });
});

// ── 같은 업종 ──
test("같은 업종 — 괴리를 모르면 '몰라요'(+0.0% 아님) · 시가총액을 하나도 모르면 열 대신 사유 한 줄(짝: 있으면 열) · 업종 피어 500 → alert", async ({ page }) => {
  await page.route(`${API}/screener/run-advanced`, async (route) => {
    const body = route.request().postDataJSON() as { universe: string };
    const res = await route.fetch(); const j = await res.json();
    // 업종 피어는 sector 요청, "지금 보는 기업" 줄은 종목 요청(all_listed)에서 온다 — 시가총액은 둘 다 비우고, 괴리는 피어 줄만 본다.
    if (String(body.universe).startsWith("sector:")) for (const it of j.items ?? []) { it.gap_pct = null; it["market_cap_억"] = null; }
    if (body.universe === "all_listed") for (const it of j.items ?? []) it["market_cap_억"] = null;
    await route.fulfill({ response: res, json: j });
  });
  await open(page);
  await goSec(page, "peers", "같은 업종");
  const pe = sec(page, "peers");
  await expect(pe.locator("tr[data-code]").first()).toBeVisible({ timeout: 30_000 });
  const gaps = await pe.locator("tr[data-code]:not(.self) td.gap").allInnerTexts();
  expect(gaps.length).toBeGreaterThan(1);
  for (const g of gaps) expect(g).toBe("몰라요");
  await expect(pe.locator("thead th", { hasText: "시가총액" })).toHaveCount(0);
  await expect(pe.locator(".ci-peer-note")).toContainText("시가총액");
  await page.unroute(`${API}/screener/run-advanced`);
  await open(page);
  await goSec(page, "peers", "같은 업종");
  await expect(sec(page, "peers").locator("tr[data-code]").first()).toBeVisible({ timeout: 30_000 });
  // 짝은 서버 그대로 — 시가총액을 하나라도 알면 열이 있다
  const anyCap = await sec(page, "peers").locator(".ci-peer-note").count();
  if (anyCap === 0) await expect(sec(page, "peers").locator("thead th", { hasText: "시가총액" })).toHaveCount(1);
  await page.route(`${API}/screener/run-advanced`, async (route) => {
    const body = route.request().postDataJSON() as { universe: string };
    if (String(body.universe).startsWith("sector:")) return route.fulfill(fail500);
    return route.continue();
  });
  await open(page);
  await goSec(page, "peers", "같은 업종");
  await expect(sec(page, "peers").locator("[role=alert]").first()).toBeVisible({ timeout: 30_000 });
});
test("★관계도 500 → alert + 다시 시도★(옛 코드는 '등록된 관계가 없어요'로 삼켰다)", async ({ page }) => {
  await page.route(`${API}/screener/graph-relations/*`, (r) => r.fulfill(fail500));
  await open(page);
  await goSec(page, "peers", "같은 업종");
  const net = sec(page, "peers").locator(".ci-net");
  await expect(net.locator("[role=alert]")).toBeVisible({ timeout: 30_000 });
  await page.unroute(`${API}/screener/graph-relations/*`);
  await net.getByRole("button", { name: "다시 시도" }).click();
  await expect(net.locator(".ca-cp-net-node").first()).toBeVisible({ timeout: 30_000 });
});

// ── 팩터 ──
test("팩터 — 백분위 점 지도: 줄 = 묶음 수 · 점 = 팩터 수 · 점 위치 = 백분위 · 점 색 = 수준 색", async ({ page }) => {
  await open(page);
  await goSec(page, "factors", "팩터");
  const map = sec(page, "factors").locator(".ci-fmap");
  await expect(map.locator(".ci-fmap-dot").first()).toBeVisible({ timeout: 30_000 });
  const rows = await map.locator(".ci-fmap-row").count();
  const groups = await sec(page, "factors").locator(".ca-cp-facgroup").count();
  expect(rows).toBe(groups);
  const nBars = await sec(page, "factors").locator(".ca-fbar:not([data-unknown])").count();
  await expect(map.locator(".ci-fmap-dot")).toHaveCount(nBars);
  const lv = await Promise.all(["neg-3", "neg-2", "neg-1", "mid", "pos-1", "pos-2", "pos-3"].map((k) => page.evaluate((kk) => {
    const s = document.createElement("span"); s.style.background = `var(--mc-lv-${kk})`; document.body.appendChild(s);
    const c = getComputedStyle(s).backgroundColor; s.remove(); return c;
  }, k)));
  const dots = await map.locator(".ci-fmap-dot").evaluateAll((els) => els.map((e) => ({
    p: Number(e.getAttribute("data-pct")), left: parseFloat((e as HTMLElement).style.left), bg: getComputedStyle(e).backgroundColor })));
  for (const d of dots) { expect(d.left).toBeCloseTo(d.p, 0); expect(lv).toContain(d.bg); }
});
test("팩터 — 점에 초점을 두면 읽기 줄이 그 팩터 이름·값·백분위 · → 키로 다음 점(짝: 다른 글) · 툴팁 0", async ({ page }) => {
  await open(page);
  await goSec(page, "factors", "팩터");
  const map = sec(page, "factors").locator(".ci-fmap");
  const first = map.locator(".ci-fmap-dot").first();
  await expect(first).toBeVisible({ timeout: 30_000 });
  await first.focus();
  const read = map.locator(".ci-fmap-read");
  const name = await first.getAttribute("data-name");
  const p = await first.getAttribute("data-pct");
  await expect(read).toContainText(name!);
  await expect(read).toContainText(`백분위 ${p}`);
  const t1 = await read.innerText();
  await page.keyboard.press("ArrowRight");
  await expect(read).not.toHaveText(t1);
  const focused = await page.evaluate(() => document.activeElement?.getAttribute("data-name"));
  await expect(read).toContainText(focused!);
  expect(await map.locator("[title]").count()).toBe(0);
  await expect(read).toHaveAttribute("aria-live", "polite");
});
test("★비교 표본이 없으면 백분위를 지어내지 않는다★ — 표본 요청 둘 다 500 → alert, 점 0, '50' 없음 · 짝: 표본이 3개면 사유(alert 아님)", async ({ page }) => {
  const kill = async (n: number | "fail") => {
    await page.route(`${API}/screener/factor-sample*`, (r) => (n === "fail" ? r.fulfill(fail500) : r.fulfill({ json: { items: [] } })));
    await page.route(`${API}/screener/run-advanced`, async (route) => {
      const b = route.request().postDataJSON() as { universe: string; limit: number };
      if (b.universe === "kospi200" && b.limit === 300) {
        if (n === "fail") return route.fulfill(fail500);
        const res = await route.fetch(); const j = await res.json(); j.items = (j.items ?? []).slice(0, n);
        return route.fulfill({ response: res, json: j });
      }
      return route.continue();
    });
  };
  await kill("fail");
  await open(page);
  await goSec(page, "factors", "팩터");
  const fa = sec(page, "factors");
  await expect(fa.locator("[role=alert]").first()).toBeVisible({ timeout: 30_000 });
  await expect(fa.locator(".ci-fmap-dot")).toHaveCount(0);
  await expect(fa.locator(".ca-fbar-pct", { hasText: /^50$/ })).toHaveCount(0);
  await page.unroute(`${API}/screener/factor-sample*`); await page.unroute(`${API}/screener/run-advanced`);
  await kill(3);
  await open(page);
  await goSec(page, "factors", "팩터");
  await expect(sec(page, "factors").locator(".ci-fmap-reason")).toContainText("3개", { timeout: 30_000 });
  await expect(sec(page, "factors").locator("[role=alert]")).toHaveCount(0);
  await expect(sec(page, "factors").locator(".ci-fmap-dot")).toHaveCount(0);
});
test("팩터 — 카테고리 이름 한국어(quality·safety·composite 0) · 영어 팩터 이름 0 · 카테고리 평균 막대 = 수준 색 · 막대 목록은 펼침 안", async ({ page }) => {
  await open(page);
  await goSec(page, "factors", "팩터");
  const fa = sec(page, "factors");
  await expect(fa.locator(".ci-fmap-dot").first()).toBeVisible({ timeout: 30_000 });
  await fa.locator("details.ci-fac-more summary").click();
  const t = await fa.innerText();
  expect(t).not.toMatch(/\b(quality|safety|composite|Score|Multiple|Formula)\b/);
  expect(await fa.locator("details.ci-fac-more").evaluate((d) => (d as HTMLDetailsElement).open)).toBe(true);
  const avg = fa.locator(".ca-cp-catbar i b").first();
  const pctTxt = await fa.locator(".ca-cp-catbar em").first().innerText();
  const want = await page.evaluate((p) => {
    const t2 = (p - 50) / 50, a = Math.abs(t2); const k = a < 0.2 ? "mid" : `${t2 > 0 ? "pos" : "neg"}-${a < 0.5 ? 1 : a < 0.8 ? 2 : 3}`;
    const s = document.createElement("span"); s.style.background = `var(--mc-lv-${k})`; document.body.appendChild(s);
    const c = getComputedStyle(s).backgroundColor; s.remove(); return c;
  }, Number(pctTxt));
  expect(await avg.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe(want);
});
test("팩터 카탈로그 500 → alert(빈 절이 아니다)", async ({ page }) => {
  await page.route(`${API}/screener/fields`, (r) => r.fulfill(fail500));
  await open(page);
  await goSec(page, "factors", "팩터");
  await expect(sec(page, "factors").locator("[role=alert]").first()).toBeVisible({ timeout: 30_000 });
});

// ── AI ──
test("★AI 요청 500 → alert + 다시 시도★(서버 글로 위장하지 않는다) · 짝: 서버가 사유를 답하면 사유(alert 0)", async ({ page }) => {
  await page.route(`${API}/narrative/stock`, (r) => r.fulfill(fail500));
  await open(page);
  await goSec(page, "ai", "AI");
  await sec(page, "ai").locator(".ca-cp-ai-btn").click();
  await expect(sec(page, "ai").locator("[role=alert]")).toBeVisible({ timeout: 30_000 });
  expect(await sec(page, "ai").innerText()).not.toContain("narrative failed");
  await page.unroute(`${API}/narrative/stock`);
  await page.route(`${API}/narrative/stock`, (r) => r.fulfill({ json: { content: "", total_tokens: 0, cost_krw: 0, cached: false, error: "AI 키가 설정되지 않았어요" } }));
  await sec(page, "ai").getByRole("button", { name: "다시 시도" }).click();
  await expect(sec(page, "ai").locator(".ci-ai-reason")).toContainText("AI 키가 설정되지 않았어요", { timeout: 30_000 });
  await expect(sec(page, "ai").locator("[role=alert]")).toHaveCount(0);
});

// ── 다섯 절 공통: 글 · 대비 · 390 ──
const BANNED_B = /\b(Z-Score|M-Score|QoE|NWC|OCF|CapEx|Value Creation|ANTHROPIC_API_KEY|Data Infra|quality|safety|composite)\b/;
test("돈 버는 힘·위험·같은 업종·팩터·AI — em-dash 0 · 영어 꼬리표 0 · ₩ 0 · 툴팁 0 · 라이트/다크 AA · 390 넘침 0", async ({ page }) => {
  await deep(page);
  await open(page);
  await scrollAll(page);
  await expect(sec(page, "risk").locator(".ci-alt-dot")).toBeVisible({ timeout: 30_000 });
  await page.evaluate(() => document.querySelectorAll(".ci-sec details").forEach((d) => { (d as HTMLDetailsElement).open = true; }));
  await page.waitForTimeout(800);
  for (const s of ["money", "risk", "peers", "factors", "ai"]) {
    const r = await sec(page, s).evaluate((root, fnSrc) => {
      // eslint-disable-next-line no-new-func
      const texts = (new Function(`return ${fnSrc}`)() as (e: Element) => string[])(root);
      return { texts, titles: root.querySelectorAll("[title]").length + Array.from(root.querySelectorAll("svg title")).filter((e) => e.textContent?.trim()).length };
    }, visibleTexts.toString());
    expect(r.texts.filter((x) => x.includes("—")), `${s} em-dash`).toEqual([]);
    expect(r.texts.filter((x) => BANNED_B.test(x) || BANNED.test(x)), `${s} 영어`).toEqual([]);
    expect(r.texts.filter((x) => x.includes("₩")), `${s} ₩`).toEqual([]);
    expect(r.titles, `${s} 툴팁`).toBe(0);
  }
  for (const s of ["money", "risk", "peers", "factors", "ai"]) {
    const light = await page.evaluate<AuditResult>(contrastAudit(`.ci-sec[data-sec=${s}]`));
    expect(light.low, `${s} 라이트`).toEqual([]);
  }
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(300);
  for (const s of ["money", "risk", "peers", "factors", "ai"]) {
    const dark = await page.evaluate<AuditResult>(contrastAudit(`.ci-sec[data-sec=${s}]`));
    expect(dark.low, `${s} 다크`).toEqual([]);
    expect(dark.bright, `${s} 다크 밝은 판`).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(800);
  const over = await page.evaluate(() => {
    const m = document.querySelector(".terminal-main") as HTMLElement;
    return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
  });
  expect(over).toBeLessThanOrEqual(0);
});
