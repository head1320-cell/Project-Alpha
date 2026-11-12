import { test, expect, type Page } from "./fixtures";
import { cardsOverflow, contrastAudit, type AuditResult } from "./helpers";
import { liveState, realismState, routeConnection, routeGate, routeLive, routeRealism, signIn, type RealismState } from "./fixtures/admin";
import REALISM from "./fixtures/realism.json";

// ═══════════════════════════════════════════════════════════════════════════════
// ST3c — 실거래 [현실성 점검] 탭 (옛 `/admin/realism` 을 옮김)
// ─────────────────────────────────────────────────────────────────────────────
//  · ★[계산하기] 전 요청 0★ · 옛 MOCK 글자 0 · 전략 0 → 계산을 보내지 않고 등록 안내
//  · 답 = 서버 총수익률 둘(응답을 바꾸면 문장이 바뀐다 — 짝) · 두 곡선은 ★날짜로★ 맞춘다(한쪽에 없는 날을 센다)
//  · 폭포는 서버 원화 둘만 세우고 합 = 현실 끝 자산(0.55/0.45 같은 지어낸 분배 없음) · 한쪽 실패는 그쪽 사유만, 그림 없음
//  · 수용량은 몰라요 + 사유 · AA 라이트/다크 · 390
// ═══════════════════════════════════════════════════════════════════════════════

const sec = (page: Page, id: string) => page.locator(`.rl [data-sec="${id}"]`);
type R = typeof REALISM.real;

async function open(page: Page, st: RealismState = realismState()) {
  await signIn(page, "admin");
  await routeConnection(page);
  await routeGate(page, { current: null, history: [] });
  await routeLive(page, liveState());
  await routeRealism(page, st);
  const calls: string[] = [];
  page.on("request", (r) => {
    const p = new URL(r.url()).pathname.replace(/^\/api\/backend(?=\/)/, "");
    if (p.startsWith("/api/v1/realism/") || p.startsWith("/api/v1/multibacktest/")) calls.push(`${r.method()} ${p}`);
  });
  await page.goto("/admin/live-trading?tab=realism", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".rl-calc")).toBeVisible({ timeout: 20_000 });
  return calls;
}

test("ST3c: 계산하기 전에는 요청 0 · 옛 MOCK 숫자 0 · 조리법은 요청 상수 그대로", async ({ page }) => {
  const calls = await open(page);
  await page.waitForTimeout(1500);
  expect(calls).toEqual([]);
  const text = await page.locator(".rl").innerText();
  for (const mock of ["77.57", "Mock", "A+", "WATCH", "24회", "Realism Panel"]) expect(text, mock).not.toContain(mock);
  await expect(page.locator(".rl-intro")).toContainText("2023-01-01 ~ 2024-12-31, 초기 자본 100억원");
  await expect(page.locator(".rl-empty")).toBeVisible();
});

test("ST3c: 전략이 없으면 계산을 보내지 않고 등록 안내 · 짝: 있으면 두 번 보낸다", async ({ page }) => {
  const st = realismState({ strategies: [] });
  const calls = await open(page, st);
  await page.locator(".rl-calc").click();
  await expect(page.locator(".rl-none")).toContainText("등록한 전략 없음");
  await expect(page.locator('.rl-none a[href="/backtest"]')).toBeVisible();
  expect(calls.filter((c) => c.startsWith("POST"))).toEqual([]);
  st.strategies = realismState().strategies;
  await page.locator(".rl-calc").click();
  await expect(sec(page, "answer")).toBeVisible({ timeout: 20_000 });
  expect(calls.filter((c) => c.startsWith("POST"))).toEqual(["POST /api/v1/realism/backtest", "POST /api/v1/realism/backtest"]);
});

test("ST3c: 답 = 서버 총수익률 둘(짝) · 차이 %p", async ({ page }) => {
  await open(page);
  await page.locator(".rl-calc").click();
  await expect(sec(page, "answer").locator(".rl-ans-s"))
    .toHaveText("현실 조건을 반영한 총수익률은 −6.72%로, 이상적 조건 −11.82%보다 5.10%p 높습니다.");
  const p2 = await page.context().newPage();
  const real = JSON.parse(JSON.stringify(REALISM.real)) as R;
  real.summary.total_return_pct = -15;
  await open(p2, realismState({ realityReply: { ...real, config: {} } }));
  await p2.locator(".rl-calc").click();
  await expect(sec(p2, "answer").locator(".rl-ans-s")).toHaveText("현실 조건을 반영한 총수익률은 −15.00%로, 이상적 조건 −11.82%보다 3.18%p 낮습니다.");
  await p2.close();
});

test("ST3c: 두 곡선은 날짜로 맞춘다 — 현실 쪽에서 앞 3일을 빼면 그만큼 센다(짝: 다 있으면 줄 없음)", async ({ page }) => {
  await open(page);
  await page.locator(".rl-calc").click();
  await expect(sec(page, "gap").locator(".rl-chart")).toHaveAttribute("data-days", String(REALISM.ideal.daily_records.length));
  await expect(sec(page, "gap").locator(".rl-missing")).toHaveCount(0);
  const p2 = await page.context().newPage();
  const real = JSON.parse(JSON.stringify(REALISM.real)) as R;
  real.daily_records = real.daily_records.slice(3);
  await open(p2, realismState({ realityReply: { ...real, config: {} } }));
  await p2.locator(".rl-calc").click();
  await expect(sec(p2, "gap").locator(".rl-chart"), "합집합 날짜").toHaveAttribute("data-days", String(REALISM.ideal.daily_records.length));
  await expect(sec(p2, "gap").locator(".rl-missing")).toContainText("현실 쪽에 없는 날 3일");
  await sec(p2, "gap").getByRole("radio", { name: "현실" }).click();
  await expect(sec(p2, "gap").getByRole("radio", { name: "현실" })).toHaveAttribute("aria-checked", "true");
  await p2.close();
  // 짝 — 이상 쪽에서 빼도 날짜 합집합이다(한쪽 기준 순번으로 맞추면 3일이 사라진다).
  const p3 = await page.context().newPage();
  const ideal = JSON.parse(JSON.stringify(REALISM.ideal)) as R;
  ideal.daily_records = ideal.daily_records.slice(3);
  await open(p3, realismState({ idealReply: { ...ideal, config: {} } }));
  await p3.locator(".rl-calc").click();
  await expect(sec(p3, "gap").locator(".rl-chart")).toHaveAttribute("data-days", String(REALISM.real.daily_records.length));
  await expect(sec(p3, "gap").locator(".rl-missing")).toContainText("이상 쪽에 없는 날 3일");
  await p3.close();
});

test("ST3c: 폭포 = 서버 원화 둘 + 나머지 · 합 = 현실 끝 자산", async ({ page }) => {
  await open(page);
  await page.locator(".rl-calc").click();
  const rows = sec(page, "waterfall").locator(".rl-wf-row");
  await expect(rows).toHaveCount(5);
  const v = await rows.evaluateAll((els) => els.map((e) => Number((e as HTMLElement).dataset.value)));
  const [ideal, impact, cash, rest, real] = v;
  expect(ideal).toBe(Math.round(REALISM.ideal.summary.final_equity));
  expect(impact).toBe(-Math.round(REALISM.real.realism_stats.total_market_impact_cost));
  expect(cash).toBe(Math.round(REALISM.real.realism_stats.total_cash_yield));
  expect(real).toBe(Math.round(REALISM.real.summary.final_equity));
  expect(Math.abs(ideal + impact + cash + rest - real), "단계 합 = 끝 값").toBeLessThanOrEqual(2);
  await expect(rows.nth(1)).toHaveAttribute("data-dir", "down");
  await expect(rows.nth(2)).toHaveAttribute("data-dir", "up");
});

test("ST3c: 현실 조건이 한 일 · 적응 모드 근거는 서버 글 · 운용 가능 규모은 미상입니다", async ({ page }) => {
  await open(page);
  await page.locator(".rl-calc").click();
  const did = sec(page, "did");
  await expect(did.locator('[data-k="impact"] .rl-card-d')).toContainText("10.8bp");
  await expect(did.locator('[data-k="buying"] .rl-card-v')).toHaveText("0번 줄였습니다");
  await expect(did.locator('[data-k="adaptive"] [data-server]')).toContainText("상관붕괴 진단만으로");
  await expect(did.locator(".rl-modes-l li")).toHaveCount(3);
  await expect(sec(page, "capacity").locator(".rl-cap")).toHaveCount(2);
  await expect(sec(page, "capacity").locator(".rl-cap-v").first()).toHaveText("운용 가능 규모 미상");
});

for (const side of ["ideal", "reality"] as const) {
  test(`ST3c: ${side} 쪽 실패 → 그쪽 사유만 · 견주는 그림 0`, async ({ page }) => {
    await open(page, realismState({ fail: { [side]: 500 } }));
    await page.locator(".rl-calc").click();
    const alerts = page.locator(".rl [role=alert]");
    await expect(alerts).toHaveCount(1);
    await expect(alerts.first()).toContainText(side === "ideal" ? "이상 쪽" : "현실 쪽");
    await expect(page.locator(".rl [data-sec]")).toHaveCount(0);
  });
}

test("ST3c: 서버가 200 + success:false 로 답하면 그 사유를 실패로", async ({ page }) => {
  await open(page, realismState({ idealReply: { success: false, message: "전략 1 미존재" } }));
  await page.locator(".rl-calc").click();
  await expect(page.locator(".rl [role=alert] [data-server]")).toHaveText("전략 1 미존재");
});

for (const scheme of ["light", "dark"] as const) {
  test(`ST3c: ${scheme} AA · 390 넘침 없음 · em-dash·툴팁·영어 대문자 없음`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* 없음 */ } }, scheme);
    await open(page);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.locator(".rl-calc").click();
      // 두 번째 누름은 결과를 잠시 내렸다가 다시 그린다 — 단추 글이 돌아오고 틈 그림까지 그려진 뒤에 재야 '3 요소만' 감사가 안 난다
      // (이전부터의 간헐 원인 · HISTORY 2026-11-08). 2026-11-09 틈 그림이 서버 `/perf/compare` 를 한 번 더 기다리므로 그것도 기다린다.
      await expect(page.locator(".rl-calc")).toHaveText("재계산", { timeout: 20_000 });
      await expect(sec(page, "capacity")).toBeVisible({ timeout: 20_000 });
      await expect(sec(page, "gap").locator(".pf-cmp")).toBeVisible({ timeout: 20_000 });
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, `${width}px 가로 넘침`).toBeLessThanOrEqual(0);
      expect(await page.evaluate<string[]>(cardsOverflow(".rl .tx-sec")), `${width}px 카드 밖`).toEqual([]);
      const a = await page.evaluate<AuditResult>(contrastAudit(".rl"));
      expect(a.checked).toBeGreaterThan(30);
      expect(a.low, `${scheme} ${width} 대비`).toEqual([]);
      if (scheme === "dark") expect(a.bright, "다크인데 밝은 바탕").toEqual([]);
      const own = await page.locator(".rl").evaluate((el) => {
        const t = Array.from(el.querySelectorAll("*")).filter((n) => !n.closest("[data-server], code, [data-mono], .perf-label"))
          .flatMap((n) => Array.from(n.childNodes).filter((c) => c.nodeType === 3).map((c) => c.textContent ?? "")).join(" ");
        return { dash: /[—–]/.test(t), caps: (t.match(/\b[A-Z]{4,}\b/g) ?? []),
          titles: Array.from(el.querySelectorAll("[title]")).filter((n) => !n.closest(".perf-label")).length };
      });
      expect(own.dash, "em-dash").toBe(false);
      expect(own.caps, "영어 대문자 낱말").toEqual([]);
      expect(own.titles, "툴팁(title)").toBe(0);
    }
  });
}

// ── 둘 겹쳐 보기 (2026-11-09 · 성과 그림 문법 ③) — 틈 그림은 서버 `/perf/compare` 가 맞춘 두 곡선 + 차이 띠 ──────────────
test("ST3c: 틈 그림 = 두 곡선 + 차이 띠 · 읽는 줄 차이 %p 는 서버 값 · 합성 빗금 · '현실' 강조(짝: 둘 다) · recharts 0", async ({ page }) => {
  await open(page);
  await page.locator(".rl-calc").click();
  const gap = sec(page, "gap");
  const fig = gap.locator(".rl-chart .pf-cmp");
  await expect(fig).toBeVisible({ timeout: 20_000 });
  await expect(fig.locator(".pf-line-a")).toHaveCount(1);
  await expect(fig.locator(".pf-line-b")).toHaveCount(1);
  await expect(fig.locator(".pf-diff-line")).toHaveCount(1);
  // 마지막 날 차이 = (현실 끝/현실 처음 − 이상 끝/이상 처음) × 100 — 픽스처에서 셈한 값과 서버가 뺀 값이 같아야 한다.
  const i = REALISM.ideal.daily_records; const r = REALISM.real.daily_records;
  const want = (r[r.length - 1].portfolio_equity / r[0].portfolio_equity - i[i.length - 1].portfolio_equity / i[0].portfolio_equity) * 100;
  await expect(fig.locator(".pf-read-diff")).toContainText(`${want >= 0 ? "+" : "−"}${Math.abs(want).toFixed(1)}%p`);
  await expect(fig.locator(".pf-read-date")).toHaveText(i[i.length - 1].date);
  await expect(fig.locator(".pf-strip-legend-practice")).toContainText("합성 데이터");       // 픽스처 perf_label.data_real = false
  await expect(fig.locator(".pf-strip-legend-align")).toHaveCount(0);                         // 같은 날짜 — 순번 아님
  await expect(fig.locator(".pf-strip-legend-missing")).toHaveCount(0);
  await expect(fig).toHaveAttribute("data-alignment", "date");
  await expect(gap.locator(".recharts-wrapper")).toHaveCount(0);
  await gap.getByRole("radio", { name: "현실" }).click();
  await expect(fig).toHaveClass(/pf-cmp--focus-b/);
  await gap.getByRole("radio", { name: "둘 다" }).click();
  await expect(fig).toHaveClass(/pf-cmp--focus-both/);
});
