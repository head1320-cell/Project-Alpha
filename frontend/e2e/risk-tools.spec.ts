import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BU7a — 위험 점검 `/risk-tools` (계획 "BU7 상세", 사용자 결정: ★네 시나리오 한눈에 + 고른 것 자세히★)
// ─────────────────────────────────────────────────────────────────────────────
// ★먼저 써서 옛 화면(칩 하나씩 · 영어 대문자 · 실패 삼킴)에서 빨강을 기록한다★ 지키는 것:
//   · 답 한 문장 = 서버 값(시나리오별 n_casualties·n_stocks 를 세어 가장 많은 충격을 말할 뿐 — 새 판단 없음)
//   · 실패(닿지 못함) ≠ 서버가 못 했다고 답함(`available:false`) ≠ 값 — 옛 화면은 앞의 둘을 삼키거나 "undefined%"·"전 종목 생존"으로 그렸다
//   · ★서버 목록(취약 ≤10 · 생존 ≤5 · 버틴 ≤5)에 없는 종목 칸은 "목록 밖" — 생존으로 지어내지 않는다★
//   · 점수 충격(부호 있는 변화)은 한국식 등락색 + 부호 · 그림은 바꾸되 지우지 않는다
// ═══════════════════════════════════════════════════════════════════════════════

const API = "**/api/backend/api/v1";
const RUN = `${API}/screener/run-advanced`;
const fail500 = { status: 500, contentType: "application/json", body: '{"detail":"boom"}' };
type Stress = { available: boolean; scenario?: string; scenario_label?: string; n_stocks?: number; n_survivors?: number; n_casualties?: number;
  avg_shock_pct?: number; casualties?: { stock_code: string; corp_name: string; shock_pct: number }[]; most_resilient?: { stock_code: string; shock_pct: number }[]; error?: string };

async function open(page: Page) {
  await page.goto("/risk-tools", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".rk")).toBeVisible({ timeout: 40_000 });
}
const scenarioOf = (route: Route) => ((route.request().postDataJSON() as { analyzer_params?: { stress_test?: { scenario?: string } } }).analyzer_params?.stress_test?.scenario ?? "");
/** 시나리오별 응답 고치기 — fn 이 그 시나리오의 stress_test 를 바꾼다. */
async function patchStress(page: Page, fn: (sc: string, s: Stress) => Stress | void) {
  await page.route(RUN, async (route) => {
    const res = await route.fetch(); const body = await res.json();
    const sc = scenarioOf(route);
    const out = fn(sc, body.analyzers.stress_test);
    if (out) body.analyzers.stress_test = out;
    await route.fulfill({ response: res, json: body });
  });
}
const probe = (page: Page, v: string) => page.evaluate((vv) => {
  const s = document.createElement("span"); s.style.color = `var(${vv})`; document.body.appendChild(s);
  const c = getComputedStyle(s).color; s.remove(); return c;
}, v);

test("답 = 서버 값 — 취약 종목이 가장 많은 충격과 그 수(응답을 고치면 따라간다)", async ({ page }) => {
  await patchStress(page, (sc, s) => { if (sc === "oil_spike_50") { s.n_casualties = 29; s.n_stocks = 30; s.n_survivors = 1; } else { s.n_casualties = 2; } });
  await open(page);
  const a = page.locator(".rk .tx-answer-s");
  await expect(a).toContainText("유가 +50%", { timeout: 40_000 });
  await expect(a).toContainText("30종목 중 29종목");
  await page.unroute(RUN);
  await patchStress(page, (sc, s) => { if (sc === "recession") { s.n_casualties = 27; s.n_stocks = 30; } else { s.n_casualties = 1; } });
  await open(page);
  await expect(page.locator(".rk .tx-answer-s")).toContainText("경기 침체", { timeout: 40_000 });
});

test("네 충격 한눈에 — 줄 = 시나리오 수 · 생존 막대 폭 = 서버 비율 · 누르면 아래 자세히가 그 충격으로", async ({ page }) => {
  const got: Record<string, Stress> = {};
  page.on("response", async (r) => {
    if (!r.url().includes("/screener/run-advanced") || r.request().method() !== "POST") return;
    const sc = (r.request().postDataJSON() as { analyzer_params?: { stress_test?: { scenario?: string } } }).analyzer_params?.stress_test?.scenario;
    if (sc) got[sc] = (await r.json()).analyzers.stress_test;
  });
  await open(page);
  const rows = page.locator(".rk-sum-row");
  await expect(rows).toHaveCount(4, { timeout: 40_000 });
  await expect(page.locator(".rk-sum-bar i")).toHaveCount(4, { timeout: 40_000 });
  for (const sc of Object.keys(got)) {
    const s = got[sc];
    const w = await page.locator(`.rk-sum-row[data-sc="${sc}"] .rk-sum-bar i`).evaluate((e) => parseFloat((e as HTMLElement).style.width));
    expect(w).toBeCloseTo(((s.n_survivors ?? 0) / (s.n_stocks ?? 1)) * 100, 0);
  }
  const second = rows.nth(1);
  const label = (await second.locator(".rk-sum-name").innerText()).trim();
  await second.click();
  await expect(second).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".rk-detail-h")).toContainText(label);
  await expect(rows.nth(0)).toHaveAttribute("aria-pressed", "false");
});

test("★서버가 못 했다고 답하면(available:false) 사유 — 'undefined'·'전 종목 생존'을 지어내지 않는다★ · alert 도 아니다", async ({ page }) => {
  await patchStress(page, (sc) => (sc === "rate_hike_200bp" ? { available: false, error: "통과 종목 없음" } : undefined));
  await open(page);
  const row = page.locator('.rk-sum-row[data-sc="rate_hike_200bp"]');
  await expect(row.locator(".rk-sum-reason")).toContainText("통과 종목 없음", { timeout: 40_000 });
  await row.click();
  await expect(page.locator(".rk-detail .rk-reason")).toBeVisible();
  const t = await page.locator(".rk").innerText();
  expect(t).not.toContain("undefined");
  expect(t).not.toContain("전 종목 생존");
  await expect(page.locator(".rk [role=alert]")).toHaveCount(0);
});

test("★시나리오 목록 500 → alert + 다시 시도 → 풀면 회복★(옛 화면은 빈 칩 줄) · 짝: 정상은 alert 0", async ({ page }) => {
  await page.route(`${API}/screener/stress-scenarios`, (r) => r.fulfill(fail500));
  await open(page);
  await expect(page.locator(".rk [role=alert]")).toBeVisible({ timeout: 40_000 });
  await page.unroute(`${API}/screener/stress-scenarios`);
  await page.locator(".rk").getByRole("button", { name: "다시 시도" }).click();
  await expect(page.locator(".rk-sum-row")).toHaveCount(4, { timeout: 40_000 });
  await expect(page.locator(".rk [role=alert]")).toHaveCount(0);
});

test("★한 충격만 500 → 그 줄만 alert, 다른 줄은 정상★(옛 화면은 옛 결과를 새 칩 아래 남겼다)", async ({ page }) => {
  await page.route(RUN, (route) => (scenarioOf(route) === "oil_spike_50" ? route.fulfill(fail500) : route.continue()));
  await open(page);
  await expect(page.locator('.rk-sum-row[data-sc="oil_spike_50"] [role=alert], .rk-sum-fail[data-sc="oil_spike_50"]').first()).toBeVisible({ timeout: 40_000 });
  await expect(page.locator(".rk-sum-bar i")).toHaveCount(3, { timeout: 40_000 });
});

test("종목 × 충격 칸 지도 — 값 = 서버 점수 충격(부호) · ★목록에 없는 칸은 '목록 밖'★(짝: 목록에 있으면 값)", async ({ page }) => {
  let first: { code: string; shock: number } | null = null;
  page.on("response", async (r) => {
    if (!r.url().includes("/screener/run-advanced")) return;
    const sc = (r.request().postDataJSON() as { analyzer_params?: { stress_test?: { scenario?: string } } }).analyzer_params?.stress_test?.scenario;
    if (sc !== "rate_hike_200bp") return;
    const c = (await r.json()).analyzers.stress_test.casualties?.[0];
    if (c) first = { code: c.stock_code, shock: c.shock_pct };
  });
  await open(page);
  const map = page.locator(".rk-map");
  await expect(map.locator(".rk-cell").first()).toBeVisible({ timeout: 40_000 });
  expect(first).not.toBeNull();
  const f = first as unknown as { code: string; shock: number };
  const cell = map.locator(`.rk-cell[data-sc="rate_hike_200bp"][data-code="${f.code}"]`);
  await expect(cell).toHaveAttribute("data-v", String(f.shock));
  await expect(cell).toContainText(`${f.shock < 0 ? "−" : "+"}${Math.abs(f.shock).toFixed(1)}`);
  const out = map.locator(".rk-cell[data-out]");
  if (await out.count()) {
    await expect(out.first()).toContainText("목록 밖");
    expect(await out.first().getAttribute("data-v")).toBeNull();
  }
  // 칸 수 = 행 × 시나리오(빈칸 없이)
  const rows = await map.locator("tbody tr").count();
  await expect(map.locator(".rk-cell")).toHaveCount(rows * 4);
});

test("점수 충격 색 — 오르면 등락 빨강, 내리면 파랑(옛 화면은 늘 빨강)", async ({ page }) => {
  await patchStress(page, (sc, s) => {
    if (sc !== "rate_hike_200bp" || !s.casualties?.length) return;
    s.casualties[0].shock_pct = 4.2; s.casualties[1].shock_pct = -12.3;
  });
  await open(page);
  const up = await probe(page, "--tx-up-ink"), dn = await probe(page, "--tx-down-ink");
  const cells = page.locator('.rk-map .rk-cell[data-sc="rate_hike_200bp"]:not([data-out])');
  await expect(cells.first()).toBeVisible({ timeout: 40_000 });
  const got = await cells.evaluateAll((els) => els.map((e) => ({ v: Number(e.getAttribute("data-v")), c: getComputedStyle(e.querySelector(".rk-cell-v")!).color })));
  const pos = got.find((g) => g.v > 0), neg = got.find((g) => g.v < 0);
  expect(pos?.c).toBe(up);
  expect(neg?.c).toBe(dn);
});

test("자세히 — 취약 종목 표(.trisk-table) 행을 누르면 기업 분석 · 요약 카드(.tstat) 생존율 = 서버 값 · 생존 기준 문장", async ({ page }) => {
  let s0: Stress | null = null;
  page.on("response", async (r) => {
    if (!r.url().includes("/screener/run-advanced")) return;
    const sc = (r.request().postDataJSON() as { analyzer_params?: { stress_test?: { scenario?: string } } }).analyzer_params?.stress_test?.scenario;
    if (sc === "rate_hike_200bp") s0 = (await r.json()).analyzers.stress_test;
  });
  await open(page);
  const d = page.locator(".rk-detail");
  await expect(d.locator(".trisk-table tbody tr").first()).toBeVisible({ timeout: 40_000 });
  const s = s0 as unknown as Stress;
  await expect(d.locator(".tstat").first()).toContainText(`${s.n_survivors}/${s.n_stocks}`);
  await expect(d).toContainText("8%");
  const row = d.locator(".trisk-table tbody tr[data-code]").first();
  const code = await row.getAttribute("data-code");
  await row.click();
  await expect(page).toHaveURL(new RegExp(`/insights\\?code=${code}`), { timeout: 20_000 });
});

test("고르기 경합 — 느린 응답을 고른 뒤 다른 충격을 고르면 화면은 마지막 고른 것", async ({ page }) => {
  await page.route(RUN, async (route) => {
    if (scenarioOf(route) === "recession") await new Promise((r) => setTimeout(r, 4000));
    await route.continue();
  });
  await open(page);
  await expect(page.locator(".rk-sum-row")).toHaveCount(4, { timeout: 40_000 });
  await page.locator('.rk-sum-row[data-sc="recession"]').click();
  await page.locator('.rk-sum-row[data-sc="oil_spike_50"]').click();
  await page.waitForTimeout(5000);
  await expect(page.locator(".rk-detail-h")).toContainText("유가");
  await expect(page.locator('.rk-sum-row[data-sc="oil_spike_50"]')).toHaveAttribute("aria-pressed", "true");
});

test("글 · 대비 · 390 — em-dash·영어 대문자·툴팁·고정폭(종목코드 밖) 0 · 라이트/다크 AA · 가로 넘침 0", async ({ page }) => {
  await open(page);
  await expect(page.locator(".rk-map .rk-cell").first()).toBeVisible({ timeout: 40_000 });
  await page.waitForTimeout(1000);
  const r = await page.locator(".rk").evaluate((root) => {
    const texts: string[] = []; const mono: string[] = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n: Node | null;
    while ((n = walk.nextNode())) {
      const el = n.parentElement!; const s = (n.textContent ?? "").trim();
      if (!s || !el.getClientRects().length) continue;
      if (!el.closest("[data-server]")) texts.push(s);
      if (/mono/i.test(getComputedStyle(el).fontFamily) && !el.closest("[data-mono]")) mono.push(s.slice(0, 20));
    }
    return { texts, mono, titles: root.querySelectorAll("[title]").length };
  });
  expect(r.texts.filter((s) => s.includes("—")), "em-dash").toEqual([]);
  expect(r.texts.filter((s) => /\b(STRESS|SCENARIO|EXPOSURE|SUMMARY|SURVIVAL|CASUALTIES|Survivors|Casualties|Ticker|Company|MOCK_DATA|REAL_DATA|SELECT)\b/i.test(s)), "영어").toEqual([]);
  expect(r.titles, "title 툴팁").toBe(0);
  expect(r.mono, "고정폭").toEqual([]);
  const light = await page.evaluate<AuditResult>(contrastAudit(".rk"));
  expect(light.low, "라이트").toEqual([]);
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(300);
  const dark = await page.evaluate<AuditResult>(contrastAudit(".rk"));
  expect(dark.low, "다크").toEqual([]);
  expect(dark.bright, "다크 밝은 판").toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(600);
  const over = await page.evaluate(() => {
    const m = document.querySelector(".terminal-main") as HTMLElement;
    return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
  });
  expect(over).toBeLessThanOrEqual(0);
});
