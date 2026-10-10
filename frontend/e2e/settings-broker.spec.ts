import { test, expect, type Page, type Route } from "@playwright/test";
import { cardsOverflow, contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BV8 — 설정 "내 증권 계좌" · 연결 · 목록 · 연결 확인 · 지우기
// ─────────────────────────────────────────────────────────────────────────────
// 서버(BV3·BV4)는 그대로. 개발 서버에는 금고 키(BROKER_CRED_KEY)가 없어 실제 연결은 503 이므로
// `/api/v1/broker-accounts*` 는 이 스펙이 응답을 정해 준다(세션도 `/auth/me` 로 정한다).
// 거는 것:
//  · ★비밀은 화면에 다시 나타나지 않는다★ — 보낸 뒤 칸이 비고, 목록은 서버가 가린 값만(짝: 끝 네 자리는 보인다)
//  · 본문이 서버 계약 그대로(is_paper 는 참·거짓) · 계좌 종류는 기본 선택 없음(고르기 전엔 단추 꺼짐)
//  · 실패 사유는 서버 문구 그대로 · 금고 키 없음(503)은 따로 · 목록 실패는 alert + 다시 시도
//  · 연습용 확인을 '연결됨'으로 말하지 않는다 · 지우기는 확인을 거친다(취소면 요청 0)
//  · 임시 비밀번호 상태면 절이 없다(짝: 분석가도 있다) · AA 라이트/다크 · 390
// ═══════════════════════════════════════════════════════════════════════════════

const KEY = "PSkey-0123456789abcdef";
const SECRET = "secret-0123456789abcdefghijklmnop";
const ACCOUNT_NO = "50123456";

type Acc = {
  account_id: string; label: string; is_paper: boolean; account_prdt: string;
  app_key_last4: string; account_no_masked: string; created_at: string;
};
const acc = (id: string, label: string, is_paper: boolean, last4 = "5678"): Acc => ({
  account_id: id, label, is_paper, account_prdt: "01", app_key_last4: "cdef",
  account_no_masked: `****${last4}`, created_at: "2026-10-09T08:00:00",
});

type Opts = { role?: string; mustChange?: boolean; accounts?: Acc[] };

/** 세션과 계좌 경로를 정한다. 보낸 요청을 돌려준다. */
async function setup(page: Page, o: Opts = {}) {
  const sent: { method: string; url: string; body: unknown }[] = [];
  let accounts = [...(o.accounts ?? [])];
  await page.addInitScript(() => localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"));
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "minji", role: o.role ?? "analyst" },
    must_change_password: !!o.mustChange, password_changed_at: "2026-10-01T00:00:00",
  } }));
  const handler = { list: (r: Route) => r.fulfill({ json: { accounts } }) } as { list: (r: Route) => Promise<void> | void };
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (!url.pathname.includes("/api/v1/broker-accounts")) return;
    let body: unknown = null;
    try { body = req.postDataJSON(); } catch { body = null; }
    sent.push({ method: req.method(), url: url.pathname.replace(/^\/api\/backend/, ""), body });
  });
  await page.route("**/api/v1/broker-accounts**", async (r) => {
    const req = r.request();
    if (req.method() === "GET" && new URL(req.url()).pathname.endsWith("/broker-accounts")) return handler.list(r);
    return r.fulfill({ status: 404, json: { detail: "이 스펙이 정하지 않은 경로" } });
  });
  return {
    sent,
    setAccounts: (a: Acc[]) => { accounts = a; },
    failList: (status = 500) => { handler.list = (r) => r.fulfill({ status, json: { detail: "목록 테스트 실패" } }); },
    okList: () => { handler.list = (r) => r.fulfill({ json: { accounts } }); },
  };
}

const sec = (page: Page) => page.locator(".set-broker");

async function fillForm(page: Page, { kind = "paper" as "paper" | "real" | null, accountNo = ACCOUNT_NO } = {}) {
  const f = page.locator(".set-broker-form");
  await f.locator('input[name="broker-label"]').fill("내 모의 계좌");
  await f.locator('input[name="broker-app-key"]').fill(KEY);
  await f.locator('input[name="broker-app-secret"]').fill(SECRET);
  await f.locator('input[name="broker-account-no"]').fill(accountNo);
  if (kind) await f.locator(`.set-broker-kind [data-kind="${kind}"]`).click();
}

async function noSecretsInDom(page: Page) {
  const html = await page.content();
  const values = await page.locator(".set-broker input").evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
  const all = html + values.join("|");
  expect(all).not.toContain(SECRET);
  expect(all).not.toContain(KEY);
  expect(all).not.toContain(ACCOUNT_NO);
}

// ── 목록 ───────────────────────────────────────────────────────────────────

test("BV8: 계좌가 없으면 빈 상태 문장과 연결 폼", async ({ page }) => {
  await setup(page);
  await page.goto("/settings");
  await expect(sec(page)).toContainText("아직 연결한 증권 계좌가 없어요");
  await expect(page.locator(".set-broker-form")).toBeVisible();
  await expect(page.locator(".set-broker-row")).toHaveCount(0);
});

test("BV8: 계좌 둘 → 줄 둘 · 종류 칩 · 가린 번호만 (짝: 빈 상태 문장 없음)", async ({ page }) => {
  await setup(page, { accounts: [acc("ba_1", "모의 하나", true), acc("ba_2", "실계좌 하나", false, "9012")] });
  await page.goto("/settings");
  const rows = page.locator(".set-broker-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("모의 하나");
  await expect(rows.nth(0).locator(".set-broker-kind-chip")).toHaveText("모의투자");
  await expect(rows.nth(1).locator(".set-broker-kind-chip")).toHaveText("실계좌");
  await expect(rows.nth(0)).toContainText("****5678");
  await expect(rows.nth(1)).toContainText("****9012");
  await expect(sec(page)).not.toContainText("아직 연결한 증권 계좌가 없어요");
});

test("BV8: 목록 500 → alert + 다시 시도 → 회복 (짝: 정상이면 alert 0)", async ({ page }) => {
  const s = await setup(page, { accounts: [acc("ba_1", "모의 하나", true)] });
  s.failList();
  await page.goto("/settings");
  const alert = sec(page).locator('[role="alert"]');
  await expect(alert).toContainText("목록 테스트 실패");
  s.okList();
  await sec(page).locator(".set-broker-retry").click();
  await expect(page.locator(".set-broker-row")).toHaveCount(1);
  await expect(sec(page).locator('[role="alert"]')).toHaveCount(0);
});

// ── 연결 ───────────────────────────────────────────────────────────────────

test("BV8: 연결 — 본문이 서버 계약 그대로 · 보낸 뒤 칸이 비고 비밀이 화면에 없다", async ({ page }) => {
  const s = await setup(page);
  await page.route("**/api/v1/broker-accounts", async (r) => {
    if (r.request().method() !== "POST") return r.fallback();
    s.setAccounts([acc("ba_new", "내 모의 계좌", true, "3456")]);
    return r.fulfill({ status: 201, json: acc("ba_new", "내 모의 계좌", true, "3456") });
  });
  await page.goto("/settings");
  await fillForm(page);
  await page.locator(".set-broker-submit").click();
  await expect(page.locator(".set-broker-row")).toHaveCount(1);
  const post = s.sent.find((x) => x.method === "POST");
  expect(post?.body).toEqual({ label: "내 모의 계좌", app_key: KEY, app_secret: SECRET, account_no: ACCOUNT_NO,
                               is_paper: true, account_prdt: "01" });
  await noSecretsInDom(page);
  await expect(page.locator(".set-broker-row")).toContainText("****3456");   // ★짝★ 끝 네 자리는 보인다
});

test("BV8: 계좌 종류를 고르기 전·8자리가 아니면 단추가 꺼진다 (짝: 다 맞으면 켜짐)", async ({ page }) => {
  await setup(page);
  await page.goto("/settings");
  const submit = page.locator(".set-broker-submit");
  await fillForm(page, { kind: null });
  await expect(submit).toBeDisabled();
  await page.locator('.set-broker-kind [data-kind="real"]').click();
  await expect(sec(page)).toContainText("실계좌 관문");
  await expect(submit).toBeEnabled();
  await page.locator('input[name="broker-account-no"]').fill("5012345");
  await expect(submit).toBeDisabled();
  await expect(sec(page)).toContainText("숫자 8자리");
});

test("BV8: 실계좌를 고르면 본문 is_paper 는 false", async ({ page }) => {
  const s = await setup(page);
  await page.route("**/api/v1/broker-accounts", (r) =>
    r.request().method() === "POST" ? r.fulfill({ status: 201, json: acc("ba_r", "실", false) }) : r.fallback());
  await page.goto("/settings");
  await fillForm(page, { kind: "real" });
  await page.locator(".set-broker-submit").click();
  await expect.poll(() => s.sent.filter((x) => x.method === "POST").length).toBe(1);
  expect((s.sent.find((x) => x.method === "POST")?.body as { is_paper: unknown }).is_paper).toBe(false);
});

test("BV8: 422 → 서버 사유 그대로 · 줄이 늘지 않는다", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/broker-accounts", (r) =>
    r.request().method() === "POST" ? r.fulfill({ status: 422, json: { detail: "계좌번호는 숫자 8자리여야 해요(테스트)." } }) : r.fallback());
  await page.goto("/settings");
  await fillForm(page);
  await page.locator(".set-broker-submit").click();
  await expect(page.locator(".set-broker-form [role=alert]")).toContainText("계좌번호는 숫자 8자리여야 해요(테스트).");
  await expect(page.locator(".set-broker-row")).toHaveCount(0);
  await expect(page.locator(".set-broker-vault")).toHaveCount(0);
});

test("BV8: 503(금고 키 없음) → 서버 사유 + 운영자에게 알리라는 줄", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/broker-accounts", (r) =>
    r.request().method() === "POST" ? r.fulfill({ status: 503, json: { detail: "BROKER_CRED_KEY 가 없어 저장하지 않았습니다." } }) : r.fallback());
  await page.goto("/settings");
  await fillForm(page);
  await page.locator(".set-broker-submit").click();
  await expect(page.locator(".set-broker-form [role=alert]")).toContainText("BROKER_CRED_KEY 가 없어 저장하지 않았습니다.");
  await expect(page.locator(".set-broker-vault")).toBeVisible();
});

// ── 연결 확인 ──────────────────────────────────────────────────────────────

const checkReply = (state: string, reason: string, detail?: string) =>
  ({ account_id: "ba_1", state, reason, checked_at: "2026-10-09T08:00:00Z", ...(detail ? { detail } : {}) });

test("BV8: 연습용 확인은 '연결됐어요'로 말하지 않는다", async ({ page }) => {
  await setup(page, { accounts: [acc("ba_1", "모의 하나", true)] });
  await page.route("**/api/v1/broker-accounts/ba_1/check", (r) =>
    r.fulfill({ json: checkReply("practice", "연습용 모드라 증권사에 묻지 않았어요. 키가 맞는지는 아직 몰라요.") }));
  await page.goto("/settings");
  await page.locator(".set-broker-row .set-broker-check").click();
  const out = page.locator(".set-broker-result");
  await expect(out).toContainText("연습용 모드라 증권사에 묻지 않았어요");
  await expect(out).toHaveAttribute("data-state", "practice");
  await expect(out).not.toContainText("연결됐어요");
});

test("BV8: 확인 성공은 서버 사유 · 실패는 사유 + 닫힌 원래 사유", async ({ page }) => {
  await setup(page, { accounts: [acc("ba_1", "실계좌", false)] });
  let reply = checkReply("ok", "증권사가 이 키와 계좌로 잔고 조회를 받아 줬어요.");
  await page.route("**/api/v1/broker-accounts/ba_1/check", (r) => r.fulfill({ json: reply }));
  await page.goto("/settings");
  await page.locator(".set-broker-check").click();
  await expect(page.locator(".set-broker-result")).toHaveAttribute("data-state", "ok");
  await expect(page.locator(".set-broker-result")).toContainText("잔고 조회를 받아 줬어요");

  reply = checkReply("failed", "증권사가 토큰을 내주지 않았어요.", "EGW00123 ****");
  await page.locator(".set-broker-check").click();
  const out = page.locator(".set-broker-result");
  await expect(out).toHaveAttribute("data-state", "failed");
  await expect(out).toContainText("증권사가 토큰을 내주지 않았어요.");
  const raw = out.locator("details");
  await expect(raw).not.toHaveAttribute("open", "");
  await raw.locator("summary").click();
  await expect(raw).toContainText("EGW00123");
});

// ── 지우기 ─────────────────────────────────────────────────────────────────

test("BV8: 지우기는 확인을 거친다 — 취소면 요청 0 · 지우면 DELETE 1 + 줄이 사라진다", async ({ page }) => {
  const s = await setup(page, { accounts: [acc("ba_1", "모의 하나", true)] });
  await page.route("**/api/v1/broker-accounts/ba_1", (r) => {
    if (r.request().method() !== "DELETE") return r.fallback();
    s.setAccounts([]);
    return r.fulfill({ json: { deleted: "ba_1" } });
  });
  await page.goto("/settings");
  await page.locator(".set-broker-delete").click();
  await page.locator(".set-broker-confirm .set-broker-cancel").click();
  expect(s.sent.filter((x) => x.method === "DELETE")).toHaveLength(0);
  await expect(page.locator(".set-broker-row")).toHaveCount(1);

  await page.locator(".set-broker-delete").click();
  await page.locator(".set-broker-confirm .set-broker-delete-yes").click();
  await expect(page.locator(".set-broker-row")).toHaveCount(0);
  const del = s.sent.filter((x) => x.method === "DELETE");
  expect(del).toHaveLength(1);
  expect(del[0].url).toBe("/api/v1/broker-accounts/ba_1");
});

// ── 보이는 사람 ────────────────────────────────────────────────────────────

test("BV8: 임시 비밀번호 상태면 절이 없다 (짝: 분석가에게는 있다)", async ({ page }) => {
  await setup(page, { mustChange: true });
  await page.goto("/settings");
  await expect(page.locator(".set-must")).toBeVisible();
  await expect(sec(page)).toHaveCount(0);
});

test("BV8: 분석가도 내 증권 계좌 절이 있다", async ({ page }) => {
  await setup(page, { role: "analyst" });
  await page.goto("/settings");
  await expect(sec(page)).toBeVisible();
});

// ── 대비 · 390 ─────────────────────────────────────────────────────────────

for (const scheme of ["light", "dark"] as const) {
  test(`BV8: ${scheme} AA · 390 가로 넘침 없음 (계좌 둘 + 확인 결과 + 폼 오류)`, async ({ page }) => {
    await setup(page, { accounts: [acc("ba_1", "모의 하나", true), acc("ba_2", "실계좌 하나", false, "9012")] });
    await page.route("**/api/v1/broker-accounts/ba_1/check", (r) =>
      r.fulfill({ json: checkReply("failed", "증권사에 닿지 못했어요. 잠시 뒤 다시 해 주세요.", "timeout") }));
    await page.route("**/api/v1/broker-accounts", (r) =>
      r.request().method() === "POST" ? r.fulfill({ status: 422, json: { detail: "이름을 넣어 주세요." } }) : r.fallback());
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* 없음 */ } }, scheme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/settings");
      await page.locator(".set-broker-check").first().click();
      await expect(page.locator(".set-broker-result")).toBeVisible();
      await fillForm(page, { kind: "real" });
      await page.locator(".set-broker-submit").click();
      await expect(page.locator(".set-broker-form [role=alert]")).toBeVisible();
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, `${width}px 가로 넘침`).toBeLessThanOrEqual(0);
      // ★칸이 카드 밖으로 삐져나가지 않는다★ — 셸이 넘친 부분을 잘라 숨겨서 위 검사로는 안 보인다(실측: 390 에서 칸 오른쪽 끝 442px).
      const sticking = await page.evaluate<string[]>(cardsOverflow(".set .set-card"));
      expect(sticking, `${width}px 카드 밖으로 나간 칸`).toEqual([]);
      const a = await page.evaluate<AuditResult>(contrastAudit(".set-broker"));
      expect(a.checked).toBeGreaterThan(10);
      expect(a.low, `${scheme} ${width} 대비`).toEqual([]);
      if (scheme === "dark") expect(a.bright, "다크인데 밝은 바탕").toEqual([]);
    }
  });
}
