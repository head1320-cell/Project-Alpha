import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";
import { GATE_OPEN, liveState, routeConnection, routeGate, routeLive, signIn, type GateRecord, type GateState } from "./fixtures/admin";

// ═══════════════════════════════════════════════════════════════════════════════
// BU9b — 실계좌 관문 절 (`/admin/live-trading` 안 · 서버 BV7 `/api/v1/admin/live-gate`)
// ─────────────────────────────────────────────────────────────────────────────
//  · 닫힘/열림을 서버 기록 그대로 · 선언은 여섯 칸이 다 차야 켜진다(짝) · 본문은 정확히 여섯 키(사용자 = 배열)
//  · 사용자 칩: 더하기·Enter·중복 없음·빼기 · 모두에게 여는 값은 화면이 막지 않고 서버 사유를 보인다
//  · 422 → 사유 그대로 + 칸 이름 · 시트 유지 · 201 → 선언했어요(+ 실계좌에서 내려온 줄)
//  · 거두기는 확인(취소 0 · 확인 DELETE 1) · 404 사유 · 지난 선언 최신 먼저 · 분석가·로그아웃은 관문 요청 0
// ═══════════════════════════════════════════════════════════════════════════════

async function open(page: Page, gate: GateState, role: "admin" | "analyst" | null = "admin") {
  await signIn(page, role);
  await routeConnection(page);
  await routeGate(page, gate);
  await routeLive(page, liveState());
  const calls: { m: string; body: unknown }[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.replace(/^\/api\/backend(?=\/)/, "") === "/api/v1/admin/live-gate") calls.push({ m: r.method(), body: r.method() === "POST" ? r.postDataJSON() : null });
  });
  // ST3b — 관문 절은 [안전] 탭에 있다.
  await page.goto("/admin/live-trading?tab=safety", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".lv")).toBeVisible({ timeout: 20_000 });
  return calls;
}

const OLD: GateRecord = { ...GATE_OPEN, basis: "옛 근거", declared_at: "2026-10-01T00:00:00+00:00", revoked_by: "admin", revoked_at: "2026-10-09T12:00:00+00:00" };

async function fill(page: Page, o: Partial<Record<"basis" | "authority" | "reference_no" | "verified_at" | "scope", string>> = {}) {
  const v = { basis: "본인 계좌 운영", authority: "증권사 약관", reference_no: "REF-1", verified_at: "2026-10-10", scope: "운영 계좌", ...o };
  for (const [k, x] of Object.entries(v)) await page.locator(`[name="gate-${k}"]`).fill(x);
}

test("BU9b 관문: 닫힘 · 지난 선언 최신 먼저 · 거둔 사람과 때", async ({ page }) => {
  await open(page, { current: null, history: [OLD] });
  await expect(page.locator(".lvg-now")).toHaveAttribute("data-open", "false");
  await expect(page.locator(".lvg-now")).toContainText("지금 닫혀 있어요");
  await expect(page.locator(".lvg-revoke-open"), "닫혀 있으면 거둘 것이 없다").toHaveCount(0);
  await expect(page.locator(".lvg-h")).toHaveCount(1);
  await expect(page.locator(".lvg-h").first()).toContainText("10월 9일 21:00에 admin 님이 거둠");
});

test("BU9b 관문: 열림 — 근거·허용 사용자를 서버 값 그대로 (짝: 선언 시각은 한국 시간)", async ({ page }) => {
  await open(page, { current: GATE_OPEN, history: [GATE_OPEN, OLD] });
  await expect(page.locator(".lvg-now")).toHaveAttribute("data-open", "true");
  await expect(page.locator(".lvg-now")).toContainText("10월 9일 21:00에 선언했어요");
  await expect(page.locator('.lvg-now + .lvg-facts [data-k="basis"] dd')).toHaveText(GATE_OPEN.basis);
  await expect(page.locator('.lvg-now + .lvg-facts [data-k="allowed_users"] li')).toHaveText(["admin"]);
  const t = await page.locator(".lvg-h-t").allTextContents();
  expect(t[0], "최신 선언이 먼저").toContain("지금 열려 있어요");
  expect(t[1]).toContain("거둠");
});

test("BU9b 관문: 선언 — 여섯 칸이 다 차야 켜지고, 본문은 정확히 여섯 키", async ({ page }) => {
  const calls = await open(page, { current: null, history: [] });
  await page.locator(".lvg-declare-open").click();
  const go = page.locator(".lvg-declare-go");
  await expect(go).toBeDisabled();
  await fill(page);
  await expect(go, "사용자가 없으면 아직 꺼짐").toBeDisabled();
  const user = page.locator('[name="gate-user"]');
  await user.fill("minji");
  await user.press("Enter");
  await user.fill("minji");
  await page.locator(".lvg-user-add").click();
  await user.fill("admin");
  await user.press("Enter");
  await expect(page.locator(".lvg-users--edit .lvg-user")).toHaveText(["minji", "admin"]);
  await page.getByRole("button", { name: "‘admin’ 빼기" }).click();
  await expect(page.locator(".lvg-users--edit .lvg-user")).toHaveText(["minji"]);
  await expect(go).toBeEnabled();
  await page.locator('[name="gate-scope"]').fill("  ");
  await expect(go, "짝: 한 칸이라도 비면 꺼짐").toBeDisabled();
  await page.locator('[name="gate-scope"]').fill("운영 계좌");
  await go.click();
  await expect(page.locator(".lvg-said")).toHaveText("선언했어요.");
  const post = calls.find((c) => c.m === "POST")!;
  expect(post.body).toEqual({ basis: "본인 계좌 운영", authority: "증권사 약관", reference_no: "REF-1", verified_at: "2026-10-10", scope: "운영 계좌", allowed_users: ["minji"] });
  await expect(page.locator(".lvg-now")).toHaveAttribute("data-open", "true");
});

test("BU9b 관문: 422 는 사유 그대로 + 칸 이름, 시트는 남는다 · 실계좌에서 내려왔으면 그렇다고", async ({ page }) => {
  const gate: GateState = { current: null, history: [], declareReply: { status: 422, json: { detail: "확인 기록이 불완전해요. 빠진 항목: allowed_users" } } };
  await open(page, gate);
  await page.locator(".lvg-declare-open").click();
  await fill(page);
  await page.locator('[name="gate-user"]').fill("*");
  await page.locator(".lvg-user-add").click();
  await expect(page.locator('[data-sheet="gate-declare"] .lv-hint').last()).toContainText("모두에게 여는 값(예: *, 모두)은 서버가 받지 않아요");
  await page.locator(".lvg-declare-go").click();
  const alert = page.locator('[data-sheet="gate-declare"] [role="alert"]');
  await expect(alert).toContainText("빠진 항목: allowed_users");
  await expect(alert).toContainText("다시 볼 칸: 허용할 사용자");
  await expect(page.locator('[data-sheet="gate-declare"]')).toBeVisible();
  gate.declareReply = { status: 201, json: { current: GATE_OPEN, live_dropped_to_shadow: true } };
  await page.locator(".lvg-declare-go").click();
  await expect(page.locator(".lvg-said")).toContainText("실계좌로 돌던 운영 계좌를 기록만으로 돌려놨어요");
});

test("BU9b 관문: 거두기는 확인 — 취소 0 · 확인 DELETE 1 · 404 사유", async ({ page }) => {
  const gate: GateState = { current: GATE_OPEN, history: [GATE_OPEN] };
  const calls = await open(page, gate);
  await page.locator(".lvg-revoke-open").click();
  await page.locator(".lvg-revoke-no").click();
  await page.waitForTimeout(400);
  expect(calls.filter((c) => c.m === "DELETE")).toHaveLength(0);
  await page.locator(".lvg-revoke-open").click();
  await page.locator(".lvg-revoke-yes").click();
  await expect(page.locator(".lvg-said")).toContainText("관문을 거뒀어요");
  expect(calls.filter((c) => c.m === "DELETE")).toHaveLength(1);
  await expect(page.locator(".lvg-now")).toHaveAttribute("data-open", "false");
  // 404 — 그사이 다른 관리자가 거뒀다면 서버 사유 그대로
  const p = await page.context().newPage();
  const g2: GateState = { current: GATE_OPEN, history: [GATE_OPEN] };
  await open(p, g2);
  await expect(p.locator(".lvg-revoke-open"), "화면이 열린 관문을 먼저 읽는다").toBeVisible();
  g2.current = null;   // 그사이 다른 관리자가 거뒀다
  await p.locator(".lvg-revoke-open").click();
  await p.locator(".lvg-revoke-yes").click();
  await expect(p.locator('[data-sheet="gate-revoke"] [role="alert"]')).toContainText("지금 열려 있는 실계좌 관문이 없어요.");
  await p.close();
});

test("BU9b 관문: 읽기 실패는 다시 시도 · 분석가·로그아웃은 관문 요청 0 (짝: 관리자는 1)", async ({ page }) => {
  const calls = await open(page, { current: null, history: [], fail: 500 });
  await expect(page.locator('.lvg [role="alert"]')).toContainText("관문 기록을 읽지 못했어요");
  expect(calls.filter((c) => c.m === "GET").length).toBeGreaterThan(0);
  for (const role of ["analyst", null] as const) {
    const p = await page.context().newPage();
    const c = await open(p, { current: null, history: [] }, role);
    await p.waitForTimeout(1500);
    expect(c, `${role}: 관문을 묻지 않는다`).toEqual([]);
    await p.close();
  }
});

test("BU9b 관문: 선언 시트 라이트/다크 AA", async ({ page }) => {
  for (const scheme of ["light", "dark"] as const) {
    const p = await page.context().newPage();
    await p.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* 없음 */ } }, scheme);
    await open(p, { current: GATE_OPEN, history: [GATE_OPEN, OLD], declareReply: { status: 422, json: { detail: "확인 기록이 불완전해요. 빠진 항목: scope" } } });
    await p.locator(".lvg-declare-open").click();
    await fill(p);
    await p.locator('[name="gate-user"]').fill("minji");
    await p.locator(".lvg-user-add").click();
    await p.locator(".lvg-declare-go").click();
    await expect(p.locator('[data-sheet="gate-declare"] [role="alert"]')).toBeVisible();
    const a = await p.evaluate<AuditResult>(contrastAudit('[data-sheet="gate-declare"]'));
    expect(a.checked).toBeGreaterThan(10);
    expect(a.low, `${scheme} 선언 시트 대비`).toEqual([]);
    if (scheme === "dark") expect(a.bright).toEqual([]);
    await p.close();
  }
});
