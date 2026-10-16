import { test, expect, type Page } from "@playwright/test";
import { cardsOverflow, contrastAudit, type AuditResult } from "./helpers";
import { SAFETY, liveState, routeConnection, routeGate, routeLive, signIn, type LiveState, type SafetyKey } from "./fixtures/admin";

// ═══════════════════════════════════════════════════════════════════════════════
// ST3b — 실거래 탭 둘([지금] · [안전]) + [안전] 탭 절 다섯 (사용자 결정 "탭 셋" — [현실성 점검] 은 ST3c)
// ─────────────────────────────────────────────────────────────────────────────
//  · 답 문장·[비상 정지] 는 탭과 상관없이 늘 보인다 · 탭 = 주소 `?tab=` · 화살표로 옮긴다
//  · ★[안전] 탭을 열기 전에는 안전 읽기 0★(지금 탭의 요청은 BU9a 골든 그대로) — 열면 여섯
//  · 절마다 서버 값 그대로(응답을 바꾸면 화면이 따라간다 — 짝) · 모르는 열거값은 원문 · 미상 ≠ 0
//  · 절 하나가 실패해도 그 절만 alert + 다시 시도 · 감사 0건은 진짜 0건(R1 — 서버가 읽지 못하면 500 + 사유, 빈 목록으로 숨기지 않는다)
//  · 분석가는 관문 없이 나머지 넷 · 로그아웃은 안전 읽기 0 · AA 라이트/다크 · 390
// ═══════════════════════════════════════════════════════════════════════════════

const SAFETY_PATHS = ["/kill-switch/events", "/kill-switch/readiness", "/kill-switch/kis-codes", "/audit", "/audit/summary", "/daily-pnl"];
const sec = (page: Page, id: string) => page.locator(`.lvs-sec[data-sec="${id}"]`);
const tab = (page: Page, t: string) => page.locator(`.tx-tab[data-tab="${t}"]`);

async function open(page: Page, o: { role?: "admin" | "analyst" | null; st?: LiveState; url?: string } = {}) {
  const st = o.st ?? liveState();
  await signIn(page, o.role === undefined ? "admin" : o.role);
  await routeConnection(page);
  await routeGate(page, { current: null, history: [] });
  await routeLive(page, st);
  const reads: string[] = [];
  page.on("request", (r) => {
    const p = new URL(r.url()).pathname.replace(/^\/api\/backend(?=\/)/, "").replace(/^\/api\/v1\/live/, "");
    if (r.method() === "GET" && SAFETY_PATHS.includes(p)) reads.push(p);
  });
  await page.goto(o.url ?? "/admin/live-trading", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".lv")).toBeVisible({ timeout: 20_000 });
  return { st, reads };
}

test("ST3b 탭: 기본은 지금 · 주소와 함께 움직임 · 답과 비상 정지는 두 탭 모두 · 안전 읽기는 탭을 열 때만", async ({ page }) => {
  const { reads } = await open(page);
  await expect(tab(page, "now")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".tx-path-l")).toBeVisible();
  await expect(page.locator(".lv .tx-answer-s")).toContainText("기록만");
  await page.waitForTimeout(1500);
  expect(reads, "[지금] 탭은 안전 읽기를 하지 않는다").toEqual([]);

  await tab(page, "safety").click();
  await expect(page).toHaveURL(/\/admin\/live-trading\?tab=safety$/);
  await expect(page.locator(".lvs-sec")).toHaveCount(4);
  await expect(page.locator(".lv .tx-answer-s"), "답은 탭 위에 그대로").toContainText("기록만");
  await expect(page.locator('[data-act="kill-open"]'), "비상 정지 단추도").toBeVisible();
  await expect(page.locator(".tx-path-l"), "길은 [지금] 탭에만").toHaveCount(0);
  await expect.poll(() => [...new Set(reads)].sort()).toEqual([...SAFETY_PATHS].sort());

  // 화살표 키로 옮긴다(로빙) — 주소도 따라간다.
  await tab(page, "safety").focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(/\/admin\/live-trading$/);
  await expect(tab(page, "now")).toBeFocused();
});

test("ST3b 탭: 주소로 바로 열고, 모르는 탭 이름은 지금으로", async ({ page }) => {
  await open(page, { url: "/admin/live-trading?tab=safety" });
  await expect(tab(page, "safety")).toHaveAttribute("aria-selected", "true");
  await page.goto("/admin/live-trading?tab=weird");
  await expect(tab(page, "now")).toHaveAttribute("aria-selected", "true");
});

test("ST3b 비상 정지 이력: 서버 행 그대로 · 걸려 있음 · 조치 상태 번역 · 모르는 출처는 원문", async ({ page }) => {
  const st = liveState();
  const ev = JSON.parse(JSON.stringify(SAFETY.events)) as { events: Record<string, unknown>[] };
  ev.events.push({ event_id: "KILL-0", triggered_at: "2026-09-30T09:00:00", trigger_source: "robot_x", trigger_reason: "원인", resolved_at: "2026-09-30T09:10:00", resolved_by: "admin", actions: null });
  st.safety.events = ev;
  await open(page, { st, url: "/admin/live-trading?tab=safety" });
  const rows = sec(page, "kill-events").locator(".lvs-kill");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toHaveAttribute("data-open", "false");
  await expect(rows.nth(0)).toContainText("10월 9일 12:05 · 관리자가 손으로 · 10월 9일 12:30에 admin 님이 풀었어요");
  await expect(rows.nth(0)).toContainText("취소한 미체결 1건");
  await expect(rows.nth(0).locator('.lvs-act[data-state="skipped"] .lvs-act-s')).toHaveText("하지 않았어요");
  await expect(rows.nth(0).locator('.lvs-act[data-state="skipped"] .lvs-act-why')).toContainText("팔지 않았습니다");
  await expect(rows.nth(1)).toHaveAttribute("data-open", "false");
  await expect(rows.nth(1)).toContainText("누적 손실 자동 정지");
  await expect(rows.nth(1)).toContainText("admin 님이 풀었어요");
  await expect(rows.nth(1), "미상 ≠ 0").toContainText("취소한 미체결 몰라요");
  await expect(rows.nth(1).locator(".lvs-act-s")).toHaveText("몰라요");
  await expect(rows.nth(2).locator("[data-server]").first(), "모르는 출처는 원문").toHaveText("robot_x");
  await expect(rows.nth(2)).toContainText("조치를 서버가 기록하지 않았어요");
});

test("ST3b 비상 정지 이력: 풀지 않은 정지는 '지금 걸려 있어요'(짝: 푼 정지는 아님)", async ({ page }) => {
  const st = liveState();
  const ev = JSON.parse(JSON.stringify(SAFETY.events)) as { events: Record<string, unknown>[] };
  ev.events[0] = { ...ev.events[0], resolved_at: null, resolved_by: null };
  st.safety.events = ev;
  st.kill = { is_active: true, active_event: { event_id: "KILL-2", trigger_reason: "Manual emergency stop from cockpit", triggered_at: "2026-10-09T12:05:00" } };
  await open(page, { st, url: "/admin/live-trading?tab=safety" });
  const rows = sec(page, "kill-events").locator(".lvs-kill");
  await expect(rows.nth(0)).toHaveAttribute("data-open", "true");
  await expect(rows.nth(0)).toContainText("지금 걸려 있어요");
  await expect(rows.nth(1)).not.toContainText("지금 걸려 있어요");
});

test("ST3b 비상 정지 이력: 없으면 없다고 · 짝: 있으면 줄", async ({ page }) => {
  const st = liveState();
  st.safety.events = { count: 0, events: [] };
  await open(page, { st, url: "/admin/live-trading?tab=safety" });
  await expect(sec(page, "kill-events")).toContainText("비상 정지를 건 적이 없어요");
  await expect(sec(page, "kill-events").locator(".lvs-kill")).toHaveCount(0);
});

test("ST3b 준비 상태: 서버가 센 무장 수 그대로(짝) · 사유 원문 · 코드 표 수", async ({ page }) => {
  await open(page, { url: "/admin/live-trading?tab=safety" });
  const s = sec(page, "readiness");
  await expect(s.locator(".lvs-ready-ans")).toHaveText("조건 4개 중 0개가 지금 걸 수 있어요.");
  await expect(s.locator(".lvs-ready-row")).toHaveCount(4);
  await expect(s.locator('.lvs-ready-row[data-trigger="auto_api"] .lvs-ready-why')).toContainText("mock 클라이언트에는 실패 카운터가 없습니다");
  await expect(s.locator('.lvs-ready-row[data-trigger="auto_dd"] .lvs-ready-n')).toHaveText("누적 손실이 한도를 넘으면");
  await expect(s.locator(".lvs-codes")).toContainText("뜻을 아는 코드 0개 · 본 적 있는 코드 0개 · 그중 뜻을 모르는 코드 0개");
  await expect(s.locator(".lvs-more")).not.toHaveAttribute("open", "");

  const p2 = await page.context().newPage();
  const st = liveState();
  st.safety.readiness = { ...(SAFETY.readiness as object), armed: [{ trigger: "auto_dd", reason: null }],
    inoperable: (SAFETY.readiness as { inoperable: unknown[] }).inoperable.slice(1) };
  await open(p2, { st, url: "/admin/live-trading?tab=safety" });
  await expect(sec(p2, "readiness").locator(".lvs-ready-ans"), "짝: 응답을 바꾸면 문장도").toHaveText("조건 4개 중 1개가 지금 걸 수 있어요.");
  await expect(sec(p2, "readiness").locator('.lvs-ready-row[data-trigger="auto_dd"]')).toHaveAttribute("data-ok", "true");
  await p2.close();
});

test("ST3b 일 손익: 행 그대로 · 등락색 짝 · 미상은 몰라요", async ({ page }) => {
  const st = liveState();
  st.safety.pnl = { count: 3, pnl_history: [...(SAFETY.pnl as { pnl_history: object[] }).pnl_history,
    { trade_date: "2026-10-07", execution_mode: "WEIRD", ending_equity_krw: null, daily_return_pct: null, n_orders: null }] };
  await open(page, { st, url: "/admin/live-trading?tab=safety" });
  const rows = sec(page, "daily-pnl").locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("100,046,983원");
  await expect(rows.nth(0).locator(".tx-delta")).toHaveText("+0.12%");
  await expect(rows.nth(1).locator(".tx-delta")).toHaveText("−0.40%");
  const color = (i: number) => rows.nth(i).locator(".tx-delta").evaluate((e) => getComputedStyle(e).color);
  const up = await page.evaluate(() => { const d = document.createElement("span"); d.style.color = "var(--tx-up-ink)"; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; });
  expect(await color(0), "오른 날 = 오름 색").toBe(up);
  expect(await color(1), "짝: 내린 날은 다른 색").not.toBe(up);
  await expect(rows.nth(2).locator("[data-server]"), "모르는 모드는 원문").toHaveText("WEIRD");
  await expect(rows.nth(2)).toContainText("몰라요");
  await expect(rows.nth(2), "미상을 0 으로 쓰지 않는다").not.toContainText("0원");
});

test("ST3b 감사 기록: 줄 그대로 · 오늘 요약 · 0건은 없다고 말한다 · 읽지 못하면 실패로(R1) · 요약 error 는 실패로", async ({ page }) => {
  await open(page, { url: "/admin/live-trading?tab=safety" });
  const s = sec(page, "audit");
  await expect(s.locator(".lvs-audit-row")).toHaveCount(2);
  await expect(s.locator(".lvs-audit-row").first()).toHaveAttribute("data-sev", "CRITICAL");
  await expect(s.locator(".lvs-audit-row").first()).toContainText("심각");
  await expect(s.locator(".lvs-audit-sum")).toContainText("2026-10-09 기록 2건 · 심각 1 · 오류 0 · 주의 0 · 알림 1");

  const p2 = await page.context().newPage();
  const st = liveState();
  st.safety.audit = { count: 0, events: [] };
  st.safety.auditSummary = { date: "2026-10-09", error: "no such table: live_audit_trail" };
  await open(p2, { st, url: "/admin/live-trading?tab=safety" });
  await expect(sec(p2, "audit").locator(".lvs-empty")).toHaveText("운영 계좌에 남은 감사 기록이 없어요.");
  await expect(sec(p2, "audit"), "R1 — 이제 0 은 진짜 0 이라 얼버무리지 않는다").not.toContainText("가를 수 없어요");
  await expect(sec(p2, "audit").getByRole("alert")).toContainText("오늘 요약을 서버가 읽지 못했어요");
  await expect(sec(p2, "audit").getByRole("alert").locator("[data-server]")).toHaveText("no such table: live_audit_trail");
  await p2.close();

  // 짝 — 서버가 읽지 못했다고 답하면(500 + 사유) 빈 상태가 아니라 실패다
  const p3 = await page.context().newPage();
  await open(p3, { st: liveState({ fail: { audit: 500 } }), url: "/admin/live-trading?tab=safety" });
  const a3 = sec(p3, "audit");
  await expect(a3.getByRole("alert")).toContainText("감사 기록을 불러오지 못했어요");
  await expect(a3.getByRole("alert"), "서버 사유가 그대로").toContainText("audit 를 읽지 못했어요");
  await expect(a3.locator(".lvs-empty"), "실패를 '기록이 없어요'로 쓰지 않는다").toHaveCount(0);
  await p3.close();
});

test("ST3b 실패: 절 하나가 500 이면 그 절만 alert + 다시 시도로 회복 · 다른 절은 그린다", async ({ page }) => {
  for (const k of ["events", "readiness", "kisCodes", "audit", "auditSummary", "pnl"] as SafetyKey[]) {
    const p = await page.context().newPage();
    const st = liveState({ fail: { [k]: 500 } });
    await open(p, { st, url: "/admin/live-trading?tab=safety" });
    const alerts = p.locator(".lvs [role=alert]");
    await expect(alerts, `${k} 실패`).toHaveCount(1);
    await expect(alerts.first()).toContainText(`${k} 를 읽지 못했어요`);
    await expect(p.locator(".lvs-sec"), "다른 절은 그대로").toHaveCount(4);
    delete st.fail[k];
    await alerts.first().getByRole("button", { name: "다시 시도" }).click();
    await expect(alerts, `${k} 다시 시도 뒤 회복`).toHaveCount(0);
    await p.close();
  }
  // 짝 — 정상이면 alert 0
  await open(page, { url: "/admin/live-trading?tab=safety" });
  await expect(page.locator(".lvs-sec")).toHaveCount(4);
  await expect(page.locator(".lvs [role=alert]")).toHaveCount(0);
});

test("ST3b 세션: 분석가는 관문 없이 넷 · 로그아웃은 안전 읽기 0", async ({ page }) => {
  await open(page, { role: "analyst", url: "/admin/live-trading?tab=safety" });
  await expect(page.locator(".lvs-sec")).toHaveCount(4);
  await expect(page.locator(".lvg")).toHaveCount(0);

  const p2 = await page.context().newPage();
  const { reads } = await open(p2, { role: null, url: "/admin/live-trading?tab=safety" });
  await expect(p2.locator(".lvs-login")).toBeVisible();
  await p2.waitForTimeout(1500);
  expect(reads, "로그아웃이면 부르지 않는다").toEqual([]);
  await p2.close();
});

for (const scheme of ["light", "dark"] as const) {
  test(`ST3b [안전] 탭: ${scheme} AA · 390 넘침 없음 · em-dash·툴팁·영어 대문자 없음`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* 없음 */ } }, scheme);
    const st = liveState();
    await open(page, { st, url: "/admin/live-trading?tab=safety" });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.reload();
      await expect(page.locator(".lvs-kill")).toHaveCount(2);
      await expect(page.locator(".lvs-audit-row")).toHaveCount(2);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, `${width}px 가로 넘침`).toBeLessThanOrEqual(0);
      expect(await page.evaluate<string[]>(cardsOverflow(".lvs .tx-sec")), `${width}px 카드 밖`).toEqual([]);
      const a = await page.evaluate<AuditResult>(contrastAudit(".lvs"));
      expect(a.checked).toBeGreaterThan(40);
      expect(a.low, `${scheme} ${width} 대비`).toEqual([]);
      if (scheme === "dark") expect(a.bright, "다크인데 밝은 바탕").toEqual([]);
      const own = await page.locator(".lvs").evaluate((el) => {
        const t = Array.from(el.querySelectorAll("*")).filter((n) => !n.closest("[data-server], code, [data-mono]"))
          .flatMap((n) => Array.from(n.childNodes).filter((c) => c.nodeType === 3).map((c) => c.textContent ?? "")).join(" ");
        return { dash: /[—–]/.test(t), caps: (t.match(/\b[A-Z]{4,}\b/g) ?? []), titles: el.querySelectorAll("[title]").length };
      });
      expect(own.dash, "em-dash").toBe(false);
      expect(own.caps, "영어 대문자 낱말").toEqual([]);
      expect(own.titles, "툴팁(title)").toBe(0);
    }
  });
}
