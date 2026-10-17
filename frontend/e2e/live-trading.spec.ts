import { test, expect, type Page } from "@playwright/test";
import { cardsOverflow, contrastAudit, type AuditResult } from "./helpers";
import {
  GATE_OPEN, LIVE_BALANCE, LIVE_REFUSED, liveState, routeConnection, routeGate, routeLive, signIn, type LiveState,
} from "./fixtures/admin";

// ═══════════════════════════════════════════════════════════════════════════════
// BU9b — 실거래 `/admin/live-trading` (운영 계좌)
// ─────────────────────────────────────────────────────────────────────────────
// 요청 바이트는 `admin-requests.spec`(BU9a 골든)이 건다. 여기는 ★화면이 말하는 것★:
//  · 세션 넷(로그아웃 · 임시 비밀번호 · 분석가 · 관리자) — 관리자가 아니면 쓰기 단추 0, 읽기는 그대로
//  · ★답 문장 = 서버 값★(모드 · 연습용 · 비상 정지) — 응답을 바꾸면 문장이 바뀐다(짝) · 불러오는 중은 '기록만'이 아니다
//  · 미상 ≠ 0 · 실패는 사유와 함께 · 모의 체결·풀기는 확인을 거친다(취소면 요청 0) · 기록만은 바로
//  · 켜진 모드 단추는 눌린 채 잠김 · 실계좌·비상 정지·풀기는 공용 시트(dialog, Esc) · 거절은 서버 사유 그대로
//  · 주문이 가는 길 네 역 순서 · 손익 등락색(짝) · AA 라이트/다크 · 390
// ═══════════════════════════════════════════════════════════════════════════════

const root = (page: Page) => page.locator(".lv");
const act = (page: Page, a: string) => page.locator(`[data-act="${a}"]`);
const sentence = (page: Page) => page.locator(".lv .tx-answer-s");

type Posts = { path: string; body: unknown }[];
function watchPosts(page: Page): Posts {
  const out: Posts = [];
  page.on("request", (req) => {
    if (req.method() === "GET") return;
    const p = new URL(req.url()).pathname.replace(/^\/api\/backend(?=\/)/, "");
    if (p.startsWith("/api/v1/live/") || p.startsWith("/api/v1/admin/live-gate")) out.push({ path: `${req.method()} ${p}`, body: req.postDataJSON() });
  });
  return out;
}

async function open(page: Page, o: { role?: "admin" | "analyst" | null; mustChange?: boolean; st?: LiveState; mock?: boolean | "fail" } = {}) {
  const st = o.st ?? liveState();
  await signIn(page, o.role === undefined ? "admin" : o.role, { mustChange: o.mustChange });
  await routeConnection(page, o.mock ?? true);
  await routeGate(page, { current: null, history: [] });
  await routeLive(page, st);
  const posts = watchPosts(page);
  await page.goto("/admin/live-trading", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".lv")).toBeVisible({ timeout: 20_000 });
  return { st, posts };
}

// ── 세션 ───────────────────────────────────────────────────────────────────

test("BU9b: 관리자는 모드·비상 정지 단추가 있고, 분석가·임시 비밀번호·로그아웃은 없다(읽기는 그대로)", async ({ page }) => {
  await open(page);
  await expect(act(page, "mode-paper")).toBeVisible();
  await expect(act(page, "kill-open")).toBeVisible();
  await expect(page.locator(".lvg"), "관문 절은 [지금] 탭에 없다(ST3b — [안전] 탭)").toHaveCount(0);
  await page.locator('.tx-tab[data-tab="safety"]').click();
  await expect(page.locator(".lvg")).toBeVisible();
  await page.locator('.tx-tab[data-tab="now"]').click();

  for (const [role, mustChange, mark] of [["analyst", false, ".lv-readonly"], ["admin", true, ".lv-must"], [null, false, ".live-auth-banner"]] as const) {
    const p = await page.context().newPage();
    let modeReads = 0;
    p.on("request", (r) => { if (r.method() === "GET" && new URL(r.url()).pathname.replace(/^\/api\/backend(?=\/)/, "") === "/api/v1/live/mode") modeReads += 1; });
    await open(p, { role, mustChange });
    await expect(p.locator(mark)).toBeVisible();
    await expect(p.locator('[data-act^="mode-"], [data-act="kill-open"], [data-act="resolve"]'), `${role}${mustChange ? " 임시" : ""}: 쓰기 단추 0`).toHaveCount(0);
    await p.locator('.tx-tab[data-tab="safety"]').click();
    await expect(p.locator(".lvs")).toBeVisible();
    await expect(p.locator(".lvg"), "관문 절은 관리자만").toHaveCount(0);
    await expect.poll(() => modeReads, "읽기는 세션과 상관없이 나간다").toBeGreaterThan(0);
    await p.close();
  }
});

test("BU9b: 로그아웃이면 로그인 링크가 이 화면으로 돌아온다", async ({ page }) => {
  await open(page, { role: null });
  await expect(page.locator(".live-auth-banner__link")).toHaveAttribute("href", /\/login\?next=%2Fadmin%2Flive-trading/);
});

// ── 답 문장 ────────────────────────────────────────────────────────────────

test("BU9b: 답 문장은 서버 모드·연습용 값을 따른다 (기록만 / 모의+연습용 / 모의+실 / 모의+모름 / 실계좌)", async ({ page }) => {
  const cases: [Partial<LiveState>, boolean | "fail", RegExp][] = [
    [{ mode: "SHADOW" }, true, /기록만 돼요\. 증권사로 보내지 않아요/],
    [{ mode: "PAPER" }, true, /연습용 체결기로 가요/],
    [{ mode: "PAPER" }, false, /모의 체결로 가요\. 서버의 증권사 연결이 모의투자가 아니면 서버가 거절해요/],
    [{ mode: "PAPER" }, "fail", /지금 모의 체결로 가요\.$/],
    [{ mode: "LIVE" }, true, /실제 돈으로 나가요/],
  ];
  for (const [o, mock, want] of cases) {
    const p = await page.context().newPage();
    await open(p, { st: liveState(o), mock });
    await expect(sentence(p)).toHaveText(want);
    await expect(p.locator(".lv-live-on"), "실계좌일 때만 늘 붙는 경고").toHaveCount(o.mode === "LIVE" ? 1 : 0);
    await p.close();
  }
});

test("BU9b: 비상 정지 — 이벤트가 있으면 '모든 사용자 계좌' 까지, 없으면 '어떤 정지인지 읽지 못했어요' (짝)", async ({ page }) => {
  const ev = { event_id: "K-1", trigger_reason: "Manual emergency stop from cockpit", triggered_at: "2026-10-09T12:05:00+00:00" };
  await open(page, { st: liveState({ kill: { is_active: true, active_event: ev } }) });
  await expect(sentence(page)).toContainText("모든 사용자 계좌의 새 주문이 나가지 않아요");
  await expect(page.locator('.tx-st[data-st="kill"]')).toHaveAttribute("data-blocked", "true");
  await expect(page.locator('.tx-st[data-st="kill"]')).toContainText("10월 9일 21:05");   // UTC → 한국 시간
  await expect(act(page, "resolve")).toBeVisible();
  await expect(act(page, "kill-open")).toHaveCount(0);
  const p = await page.context().newPage();
  await open(p, { st: liveState({ kill: { is_active: true, active_event: null } }) });
  await expect(sentence(p)).toContainText("어떤 정지인지 읽지 못했어요");
  await p.close();
});

test("BU9b: 읽기 실패는 사유와 함께 · 불러오는 중은 '기록만'이 아니다 · 잔고 미상은 0 이 아니다", async ({ page }) => {
  const st = liveState({ fail: { mode: 500, balance: 500 } });
  await signIn(page, "admin");
  await routeConnection(page);
  await routeGate(page, { current: null, history: [] });
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  await routeLive(page, st);
  // ★routeLive 뒤에★ — 나중에 건 경로가 먼저 받는다. 모드 읽기를 붙잡아 '불러오는 중'을 본다.
  await page.route("**/api/v1/live/mode", async (r) => { await gate; return r.fallback(); });
  await page.goto("/admin/live-trading", { waitUntil: "domcontentloaded" });
  await expect(sentence(page)).toHaveText("운영 계좌 상태를 확인하는 중이에요.");
  await expect(page.locator('.tx-mode-b[aria-pressed="true"]'), "모르는 동안 눌린 모드가 없다").toHaveCount(0);
  release();
  await expect(sentence(page)).toHaveText("운영 계좌의 실행 모드를 확인하지 못했어요.");
  await expect(page.locator(".lv .tx-notice[data-tone=\"danger\"]").first()).toContainText("모드를 읽지 못했어요");
  await expect(page.locator(".lv-hold")).toContainText("잔고를 읽지 못했어요");
  await expect(page.locator(".tx-fig", { hasText: "평가 자산" })).toContainText("몰라요");
  // 짝 — 정상이면 서버 숫자 그대로(0 이나 몰라요가 아니다)
  st.fail = {};
  await act(page, "refresh").click();
  await expect(page.locator(".tx-fig", { hasText: "평가 자산" })).toContainText("100,046,983원");
  // 칸이 빠진 잔고 → 몰라요(0 아님)
  st.balance = { ...LIVE_BALANCE, evaluated_total: null };
  await act(page, "refresh").click();
  await expect(page.locator(".tx-fig", { hasText: "평가 자산" })).toContainText("몰라요");
  await expect(page.locator(".tx-fig", { hasText: "평가 자산" })).not.toContainText("0원");
});

// ── 모드 ───────────────────────────────────────────────────────────────────

test("BU9b: 모의 체결로는 확인을 거친다(취소 0 · 바꾸기 1) · 기록만으로는 바로 · 켜진 단추는 잠김", async ({ page }) => {
  const { st, posts } = await open(page);
  await expect(act(page, "mode-shadow")).toBeDisabled();
  await expect(act(page, "mode-shadow")).toHaveAttribute("aria-pressed", "true");
  await expect(act(page, "mode-paper"), "짝: 다른 모드는 켜져 있다").toBeEnabled();
  await act(page, "mode-paper").click();
  await expect(page.locator(".lv-paper-confirm")).toContainText("연습용 체결기로 보내요");
  await act(page, "paper-no").click();
  await page.waitForTimeout(500);
  expect(posts, "취소면 아무것도 보내지 않는다").toEqual([]);
  await act(page, "mode-paper").click();
  await act(page, "paper-yes").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toEqual({ path: "POST /api/v1/live/mode", body: { mode: "PAPER" } });
  await expect(act(page, "mode-paper")).toHaveAttribute("aria-pressed", "true");
  await expect(act(page, "mode-paper")).toBeDisabled();
  await act(page, "mode-shadow").click();
  await expect.poll(() => posts.length, "기록만으로는 확인 없이 바로").toBe(2);
  expect(posts[1].body).toEqual({ mode: "SHADOW" });
  expect(st.mode).toBe("SHADOW");
});

test("BU9b: 모드 바꾸기 실패는 서버 사유와 함께 (조용히 넘기지 않는다)", async ({ page }) => {
  const { st } = await open(page);
  st.modeReply = { status: 500, json: { detail: "실행기를 만들지 못했어요" } };
  await act(page, "mode-paper").click();
  await act(page, "paper-yes").click();
  const alert = page.locator('.live-mode-refused[data-mode="PAPER"]');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("모의 체결로 바꾸지 못했어요");
  await expect(alert).toContainText("실행기를 만들지 못했어요");
});

test("BU9b: 실계좌 시트 — dialog · Esc · 취소면 0 · 관문 닫힘이면 서버 거절 사유 (짝: 받아들이면 문구 없음)", async ({ page }) => {
  const { st, posts } = await open(page);
  await act(page, "mode-live").click();
  const sheet = page.locator('[data-sheet="live"]');
  await expect(sheet).toBeVisible();
  await expect(page.getByRole("dialog", { name: "실계좌로 바꾸기" })).toBeVisible();
  await expect(sheet.locator(".lv-gate-line")).toContainText("관문이 닫혀 있어요");
  expect(await page.evaluate(() => !!document.activeElement?.closest('[data-sheet="live"]')), "초점이 시트 안").toBe(true);
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await act(page, "mode-live").click();
  await act(page, "live-no").click();
  await page.waitForTimeout(400);
  expect(posts).toEqual([]);
  await act(page, "mode-live").click();
  await act(page, "live-yes").click();
  const refused = page.locator('.live-mode-refused[data-mode="LIVE"]');
  await expect(refused).toContainText("실계좌로 바꾸지 못했어요");
  await expect(refused).toContainText(LIVE_REFUSED);
  expect(posts[0].body).toEqual({ mode: "LIVE", confirm_token: "EXPLICIT_LIVE_CONFIRMED" });
  // 짝 — 받아들이면 거절 문구가 없고 모드가 실계좌로
  st.modeReply = { status: 200, json: { old_mode: "SHADOW", new_mode: "LIVE" } };
  st.mode = "LIVE";   // 받아들인 뒤 다시 읽으면 실계좌
  await act(page, "mode-live").click();
  await act(page, "live-yes").click();
  await expect(page.locator(".live-mode-refused")).toHaveCount(0);
  await expect(act(page, "mode-live")).toHaveAttribute("aria-pressed", "true");
});

test("BU9b: 관문이 열려 있으면 실계좌 시트가 허용한 사용자를 말한다", async ({ page }) => {
  await signIn(page, "admin");
  await routeConnection(page);
  await routeGate(page, { current: GATE_OPEN, history: [GATE_OPEN] });
  await routeLive(page, liveState());
  await page.goto("/admin/live-trading");
  await expect(act(page, "mode-live")).toContainText("관문 열림");
  await act(page, "mode-live").click();
  await expect(page.locator('[data-sheet="live"] .lv-gate-line')).toContainText("열려 있어요");
  await expect(page.locator('[data-sheet="live"] .lv-user')).toHaveText(["admin"]);
});

// ── 비상 정지 ──────────────────────────────────────────────────────────────

test("BU9b: 비상 정지 걸기·풀기 — 취소면 0 · 본문 바이트 그대로 · 결과와 실패를 말한다", async ({ page }) => {
  const { st, posts } = await open(page);
  await act(page, "kill-open").click();
  await expect(page.locator('[data-sheet="kill"]')).toContainText("모든 사용자 계좌의 새 주문을 멈춰요");
  await act(page, "kill-no").click();
  await page.waitForTimeout(400);
  expect(posts).toEqual([]);
  st.triggerReply = { status: 500, json: { detail: "잔고를 읽지 못해 정지 기록을 남기지 못했어요" } };
  await act(page, "kill-open").click();
  await act(page, "kill-yes").click();
  await expect(page.locator('[data-sheet="kill"] [role="alert"]')).toContainText("잔고를 읽지 못해");
  await expect(page.locator('[data-sheet="kill"]'), "실패하면 시트를 닫지 않는다").toBeVisible();
  st.triggerReply = null;
  await act(page, "kill-yes").click();
  await expect(page.locator(".lv-done")).toHaveText("비상 정지를 걸었어요. 운영 계좌의 미체결 1건을 취소했어요.");
  expect(posts.at(-1)).toEqual({ path: "POST /api/v1/live/kill-switch/trigger", body: { reason: "Manual emergency stop from cockpit", liquidation_mode: "hold" } });
  await expect(act(page, "resolve")).toBeVisible();
  const before = posts.length;
  await act(page, "resolve").click();
  await act(page, "resolve-no").click();
  await page.waitForTimeout(400);
  expect(posts.length, "풀기도 취소면 0").toBe(before);
  await act(page, "resolve").click();
  await act(page, "resolve-yes").click();
  await expect(page.locator(".lv-done")).toHaveText("비상 정지를 풀었어요. 새 주문을 다시 받아요.");
  expect(posts.at(-1)).toEqual({ path: "POST /api/v1/live/kill-switch/resolve", body: { notes: "Manual resolution from cockpit" } });
  // 짝 — 서버가 이미 풀려 있었다고 답하면 그대로
  st.kill = { is_active: true, active_event: null };
  st.resolveReply = { status: 200, json: { status: "no_active_event" } };
  await act(page, "refresh").click();
  await act(page, "resolve").click();
  await act(page, "resolve-yes").click();
  await expect(page.locator(".lv-done")).toHaveText("이미 풀려 있었어요.");
});

// ── 길 · 표 ────────────────────────────────────────────────────────────────

test("BU9b: 주문이 가는 길 네 역 · 보유 손익 등락색(짝) · 최근 주문 번역·멈춘 곳", async ({ page }) => {
  await open(page, { st: liveState({ orders: [
    ...liveState().orders, { client_order_id: "CO-0", ticker: "035420", side: "BUY", quantity: 1, status: "WEIRD_STATE", execution_mode: "SHADOW", created_at: "2026-10-09T11:00:00" },
  ] }) });
  await expect(page.locator(".lv-path .tx-st")).toHaveCount(4);
  expect(await page.locator(".lv-path .tx-st").evaluateAll((els) => els.map((e) => e.getAttribute("data-st")))).toEqual(["kill", "risk", "mode", "broker"]);
  await expect(page.locator('.lv-pos[data-ticker="005930"] .tx-delta')).toHaveAttribute("data-dir", "up");
  await expect(page.locator('.lv-pos[data-ticker="000660"] .tx-delta')).toHaveAttribute("data-dir", "down");
  await expect(page.locator('.lv-pos[data-ticker="005930"]')).toContainText("삼성전자");
  await expect(page.locator(".lv-ord")).toHaveCount(4);
  await expect(page.locator('.lv-ord[data-coid="CO-2"] .lv-ord-status')).toHaveText("주문하지 않았어요");
  await expect(page.locator('.lv-ord[data-coid="CO-2"] .lv-ord-stop')).toHaveAttribute("data-stop", "risk");
  await expect(page.locator('.lv-ord[data-coid="CO-0"] .lv-ord-status [data-server]'), "모르는 상태는 원문").toHaveText("WEIRD_STATE");
  await page.locator('.lv-ord-filter [data-f="stopped"]').click();
  await expect(page.locator(".lv-ord")).toHaveCount(1);
});

// ── 테마 · 글 · 대비 · 390 ─────────────────────────────────────────────────

for (const scheme of ["light", "dark"] as const) {
  test(`BU9b: ${scheme} AA · 390 넘침 없음 · em-dash·툴팁·영어 대문자 없음`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* 없음 */ } }, scheme);
    await signIn(page, "admin");
    await routeConnection(page);
    await routeGate(page, { current: GATE_OPEN, history: [GATE_OPEN, { ...GATE_OPEN, declared_at: "2026-10-01T00:00:00+00:00", revoked_by: "admin", revoked_at: "2026-10-09T12:00:00+00:00" }] });
    await routeLive(page, liveState({ mode: "PAPER" }));
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/admin/live-trading");
      await expect(act(page, "mode-paper")).toHaveAttribute("aria-pressed", "true");
      expect(await page.evaluate(() => document.documentElement.classList.contains("dark")), "테마를 따른다").toBe(scheme === "dark");
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, `${width}px 가로 넘침`).toBeLessThanOrEqual(0);
      const sticking = await page.evaluate<string[]>(cardsOverflow(".lv .tx-sec, .lv .tx-answer"));
      expect(sticking, `${width}px 카드 밖으로 나간 칸`).toEqual([]);
      const a = await page.evaluate<AuditResult>(contrastAudit(".lv"));
      expect(a.checked).toBeGreaterThan(40);
      expect(a.low, `${scheme} ${width} 대비`).toEqual([]);
      if (scheme === "dark") expect(a.bright, "다크인데 밝은 바탕").toEqual([]);
      const own = await root(page).evaluate((el) => {
        const t = Array.from(el.querySelectorAll("*")).filter((n) => !n.closest("[data-server], code, [data-mono]"))
          .flatMap((n) => Array.from(n.childNodes).filter((c) => c.nodeType === 3).map((c) => c.textContent ?? "")).join(" ");
        return { dash: /[—–]/.test(t), caps: (t.match(/\b[A-Z]{4,}\b/g) ?? []), titles: el.querySelectorAll("[title]").length };
      });
      expect(own.dash, "em-dash").toBe(false);
      expect(own.caps, "영어 대문자 낱말").toEqual([]);
      expect(own.titles, "툴팁(title)").toBe(0);
      for (const [opener, sel] of [["kill-open", '[data-sheet="kill"]'], ["mode-live", '[data-sheet="live"]']] as const) {
        await act(page, opener).click();
        const k = await page.evaluate<AuditResult>(contrastAudit(sel));
        expect(k.checked).toBeGreaterThan(4);
        expect(k.low, `${scheme} ${width} ${sel} 대비`).toEqual([]);
        if (scheme === "dark") expect(k.bright, `다크인데 밝은 바탕(${sel})`).toEqual([]);
        await page.keyboard.press("Escape");
      }
    }
  });
}
