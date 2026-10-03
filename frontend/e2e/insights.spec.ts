import { test, expect, type Page } from "@playwright/test";
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
    const bars = root.querySelectorAll(".ca-fbar-track, .ca-ff2-bar, .ca-fd-wf-bar, .ca-heat-c, .ca-cp-catbar i, .ca-cp-judge-row i, .ca-band-track").length;
    return { svg, bars };
  });
  expect(n.svg, `svg ${JSON.stringify(n)}`).toBeGreaterThanOrEqual(21);
  expect(n.bars, `막대 ${JSON.stringify(n)}`).toBeGreaterThanOrEqual(160);
  // BU6a+ 에서 더한 그림 — 하나라도 사라지면 빨강(모형 한눈에 12줄 · 분위 띠 · 히스토그램 · 층/성장률 막대 · 연도별 EVA · 배수 점 줄 · 시나리오 · 매크로 토네이도 · 레일 미니).
  const added = await page.evaluate(() => Object.fromEntries([
    ".ci-sec[data-sec=value] .ci-lad-row", ".ci-q-row", ".ci-histo-bars i", ".ci-hbar", ".ci-eva-col", ".ci-strip", ".ci-scen-row", ".ci-torn-row", ".ci-rail .ci-lad-row",
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
