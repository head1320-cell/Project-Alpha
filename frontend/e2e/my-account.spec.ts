import { test, expect, type Page, type Route } from "@playwright/test";
import { cardsOverflow, contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BV9 — "내 계좌" `/my-account` · 주문이 가는 길 · 잔고 · 주문 내기 · 최근 주문 · 비상 정지
// ─────────────────────────────────────────────────────────────────────────────
// 서버(BV6·BV7·BV9a)는 그대로. 개발 서버에는 금고 키(BROKER_CRED_KEY)가 없어 실제 계좌를 만들 수 없으므로
// `/api/v1/broker-accounts*`·connection-status·resolve-names 는 이 스펙이 응답을 정한다(세션도 `/auth/me` 로).
// 거는 것:
//  · ★답 문장 = 서버 값★(모드·연습용·비상 정지) — 응답을 바꾸면 문장이 바뀐다(짝)
//  · ★주문이 가는 길★ 네 역이 서버 순서 그대로 · 주문을 내면 서버가 멈춘 역을 표시한다
//  · 실계좌 칸은 요청을 보내지 않는다(펼침만) · 모의 체결로 바꾸기는 확인을 거친다 · 실계좌 계좌에선 꺼짐
//  · 잔고 미상 ≠ 0 · 연습용 잔고는 그렇다고 말한다 · 실패와 '증권사가 거절'을 가른다
//  · 주문 본문이 서버 계약 그대로 · 사기/팔기 기본값 없음 · stock_master 로 확인된 코드만
//  · 비상 정지는 '그대로 두기'(hold)만 · 이 계좌가 건 정지만 다시 열 수 있다
//  · 계좌를 바꾸면 옛 계좌 숫자가 새 계좌 자리에 남지 않는다 · AA 라이트/다크 · 390
// ═══════════════════════════════════════════════════════════════════════════════

type Acc = {
  account_id: string; label: string; is_paper: boolean; account_prdt: string;
  app_key_last4: string; account_no_masked: string; created_at: string;
};
const acc = (id: string, label: string, is_paper = true): Acc => ({
  account_id: id, label, is_paper, account_prdt: "01", app_key_last4: "cdef",
  account_no_masked: "****5678", created_at: "2026-10-09T08:00:00",
});

type Item = { key: string; ok: boolean; reason: string };
const READY_ITEMS: Item[] = [
  { key: "gate", ok: false, reason: "운영자가 실계좌 관문을 열지 않았어요(선언 없음)." },
  { key: "real_account", ok: false, reason: "모의투자 계좌예요. 실계좌 주문은 실계좌로 연결한 계좌에서만 해요." },
  { key: "connection", ok: true, reason: "증권사가 이 계좌의 잔고 조회를 받아 줬어요." },
  { key: "paper_practice", ok: true, reason: "내 모의투자 계좌에서 증권사 모의 서버가 받은 주문이 2건 있어요." },
  { key: "reconciliation", ok: false, reason: "이 계좌를 증권사 잔고와 맞춰 보는 대조 감시가 아직 없어요. 그래서 실계좌 전환은 열지 않아요." },
];

const okBalance = (o: Partial<{ cash: number | null; total: number | null; practice: boolean; positions: unknown[] }> = {}) => ({
  account_id: "x", practice: o.practice ?? true, as_of: "2026-10-09T12:04:00+00:00", state: "ok",
  cash_krw: o.cash === undefined ? 100_000_000 : o.cash,
  evaluated_total: o.total === undefined ? 102_000_000 : o.total,
  positions: o.positions ?? [
    { ticker: "005930", quantity: 3, avg_price: 70100, current_price: 71000, eval_amount: 213000, pnl_pct: 1.28 },
    { ticker: "000660", quantity: 2, avg_price: 132000, current_price: 130000, eval_amount: 260000, pnl_pct: -1.52 },
  ],
});

const order = (coid: string, status: string, extra: Record<string, unknown> = {}) => ({
  client_order_id: coid, ticker: "005930", side: "BUY", quantity: 10, price: 71000, status,
  execution_mode: "SHADOW", reason_code: null, error_message: null, created_at: "2026-10-09 12:01:00", ...extra,
});

type Kill = { active: boolean; event: Record<string, unknown> | null };
type Reply = { status?: number; json: unknown };
type St = {
  accounts: Acc[];
  mode: Record<string, string>;
  kill: Record<string, Kill>;
  balance: Record<string, unknown>;
  orders: Record<string, unknown[]>;
  ready: Item[];
  mockAllowed: boolean | "fail";
  names: Record<string, string>;
  fail: Partial<Record<"list" | "mode" | "balance" | "names" | "orders", number>>;
  delay: Record<string, number>;
  orderReply: Reply;
  modeReply: Reply | null;
  cancelReply: Reply;
  triggerReply: Reply;
};

type Sent = { method: string; path: string; body: unknown };

async function setup(page: Page, o: Partial<St> & { signedIn?: boolean; mustChange?: boolean } = {}) {
  const st: St = {
    accounts: [acc("ba_1", "내 모의 계좌")],
    mode: {}, kill: {}, balance: {}, orders: {}, ready: READY_ITEMS,
    mockAllowed: true, names: { "005930": "삼성전자", "000660": "SK하이닉스" }, fail: {}, delay: {},
    orderReply: { json: { client_order_id: "CO-new", status: "SHADOW_LOGGED", mode: "SHADOW", message: "SHADOW mode — 주문 발송하지 않음 (신호만 기록)" } },
    modeReply: null,
    cancelReply: { json: { status: "cancelled" } },
    triggerReply: { json: { event_id: "K-1", n_orders_cancelled: 2, liquidation_mode: "hold" } },
    ...o,
  };
  const sent: Sent[] = [];
  if (o.signedIn !== false) {
    await page.addInitScript(() => localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"));
    await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
      principal: { username: "minji", role: "analyst" },
      must_change_password: !!o.mustChange, password_changed_at: "2026-10-01T00:00:00",
    } }));
  }
  page.on("request", (req) => {
    const url = new URL(req.url());
    const i = url.pathname.indexOf("/api/v1/broker-accounts");
    if (i < 0) return;
    let body: unknown = null;
    try { body = req.postDataJSON(); } catch { body = null; }
    sent.push({ method: req.method(), path: url.pathname.slice(i + "/api/v1/broker-accounts".length), body });
  });
  await page.route("**/api/v1/macro/connection-status", (r) => st.mockAllowed === "fail"
    ? r.fulfill({ status: 500, json: { detail: "x" } })
    : r.fulfill({ json: { mock_allowed: st.mockAllowed, real_mode: !st.mockAllowed, bok_configured: false, fred_configured: false } }));
  await page.route("**/api/v1/allocation/resolve-names", (r) => {
    if (st.fail.names) return r.fulfill({ status: st.fail.names, json: { detail: "x" } });
    const codes = (r.request().postDataJSON() as { codes: string[] }).codes;
    return r.fulfill({ json: { labels: Object.fromEntries(codes.map((c) => [c, st.names[c] ?? c])) } });
  });
  const reply = (r: Route, x: Reply) => r.fulfill({ status: x.status ?? 200, json: x.json });
  await page.route("**/api/v1/broker-accounts**", async (r) => {
    const req = r.request();
    const url = new URL(req.url());
    const p = url.pathname.slice(url.pathname.indexOf("/api/v1/broker-accounts") + "/api/v1/broker-accounts".length);
    const m = req.method();
    if (p === "" && m === "GET") {
      return st.fail.list ? r.fulfill({ status: st.fail.list, json: { detail: "목록 테스트 실패" } }) : r.fulfill({ json: { accounts: st.accounts } });
    }
    const [, id, ...rest] = p.split("/");
    const tail = rest.join("/");
    const wait = st.delay[`${tail}:${id}`];
    if (wait) await new Promise((res) => setTimeout(res, wait));
    if (tail === "mode" && m === "GET") {
      if (st.fail.mode) return r.fulfill({ status: st.fail.mode, json: { detail: "x" } });
      return r.fulfill({ json: { mode: st.mode[id] ?? "SHADOW", changed_by: null, last_mode_change: null } });
    }
    if (tail === "mode" && m === "POST") {
      if (st.modeReply) return reply(r, st.modeReply);
      st.mode[id] = (req.postDataJSON() as { mode: string }).mode;
      return r.fulfill({ json: { old_mode: "SHADOW", new_mode: st.mode[id], changed_by: "minji" } });
    }
    if (tail === "kill-switch" && m === "GET") return r.fulfill({ json: st.kill[id] ?? { active: false, event: null } });
    if (tail === "kill-switch/trigger") {
      st.kill[id] = { active: true, event: { event_id: "K-1", trigger_reason: "잠깐 멈춤", triggered_at: "2026-10-09T12:05:00", trigger_source: "manual_minji" } };
      return reply(r, st.triggerReply);
    }
    if (tail === "kill-switch/resolve") {
      st.kill[id] = { active: false, event: null };
      return r.fulfill({ json: { status: "resolved", resolved_by: "minji" } });
    }
    if (tail === "live-readiness") {
      return r.fulfill({ json: { account_id: id, ready: st.ready.every((i) => i.ok), items: st.ready } });
    }
    if (tail === "balance") {
      if (st.fail.balance) return r.fulfill({ status: st.fail.balance, json: { detail: "x" } });
      return r.fulfill({ json: st.balance[id] ?? okBalance() });
    }
    if (tail === "orders" && m === "GET") {
      if (st.fail.orders) return r.fulfill({ status: st.fail.orders, json: { detail: "x" } });
      const list = st.orders[id] ?? [];
      return r.fulfill({ json: { count: list.length, orders: list } });
    }
    if (tail === "orders" && m === "POST") return reply(r, st.orderReply);
    if (tail.startsWith("orders/") && m === "DELETE") return reply(r, st.cancelReply);
    return r.fulfill({ status: 404, json: { detail: "이 스펙이 정하지 않은 경로" } });
  });
  return { st, sent };
}

const root = (page: Page) => page.locator(".ma");
const sentence = (page: Page) => page.locator(".ma .tx-answer-s");
const station = (page: Page, k: string) => page.locator(`.ma-st[data-st="${k}"]`);

async function fillOrder(page: Page, { code = "005930", side = "BUY" as "BUY" | "SELL" | null, qty = "10", price = "71000" } = {}) {
  const f = page.locator("form.ma-order");
  await f.locator('input[name="ma-ticker"]').fill(code);
  if (side) await f.locator(`.ma-side [data-side="${side}"]`).click();
  await f.locator('input[name="ma-qty"]').fill(qty);
  await f.locator('input[name="ma-price"]').fill(price);
}

// ── 세션 ──────────────────────────────────────────────────────────────────

test("BV9: 로그아웃이면 로그인으로 보내고 계좌 요청이 없다", async ({ page }) => {
  const { sent } = await setup(page, { signedIn: false });
  await page.goto("/my-account");
  await expect(page.locator(".ma-signed-out a")).toHaveAttribute("href", "/login?next=%2Fmy-account");
  await page.waitForTimeout(300);
  expect(sent).toEqual([]);
});

test("BV9: 임시 비밀번호면 바꾸라고 하고 계좌 요청이 없다 (짝: 정상 로그인은 묻는다)", async ({ page }) => {
  const { sent } = await setup(page, { mustChange: true });
  await page.goto("/my-account");
  await expect(page.locator(".ma-must")).toBeVisible();
  await expect(page.locator('.ma-must a[href="/settings#password"]')).toBeVisible();
  await page.waitForTimeout(300);
  expect(sent).toEqual([]);
});

test("BV9: 메뉴에 '내 계좌'가 있고 들어가면 계좌를 묻는다", async ({ page }) => {
  const { sent } = await setup(page);
  await page.goto("/dashboard");
  await page.locator('.terminal-nav .nav-item[aria-label="내 계좌"]').click();
  await expect(page).toHaveURL(/\/my-account/);
  await expect(sentence(page)).toBeVisible();
  expect(sent.some((s) => s.method === "GET" && s.path === "")).toBe(true);
});

// ── 계좌 목록 ──────────────────────────────────────────────────────────────

test("BV9: 계좌가 없으면 설정에서 연결하라고 한다", async ({ page }) => {
  await setup(page, { accounts: [] });
  await page.goto("/my-account");
  await expect(page.locator('.ma-empty a[href="/settings#broker"]')).toBeVisible();
  await expect(page.locator(".ma-path")).toHaveCount(0);
});

test("BV9: 목록 실패는 alert + 다시 시도 → 회복 (짝: 정상엔 alert 없음)", async ({ page }) => {
  const { st } = await setup(page, { fail: { list: 500 } });
  await page.goto("/my-account");
  const fail = root(page).getByRole("alert").filter({ hasText: "증권 계좌 목록을 불러오지 못했어요" });
  await expect(fail).toBeVisible();
  delete st.fail.list;
  await fail.getByRole("button", { name: "다시 시도" }).click();
  await expect(sentence(page)).toContainText("내 모의 계좌");
  await expect(root(page).getByRole("alert")).toHaveCount(0);
});

test("BV9: 주소의 계좌가 내 목록에 없으면 그렇다고 말하고 첫 계좌를 보인다", async ({ page }) => {
  await setup(page, { accounts: [acc("ba_1", "첫 계좌"), acc("ba_2", "둘째 계좌")] });
  await page.goto("/my-account?account=ba_nope");
  await expect(page.locator(".ma-fallback")).toContainText("주소의 계좌를 찾지 못해");
  await expect(sentence(page)).toContainText("첫 계좌");
});

// ── 답 문장 = 서버 값 ──────────────────────────────────────────────────────

test("BV9: 답 문장은 모드·연습용 여부를 따른다 (짝 넷)", async ({ page }) => {
  const { st } = await setup(page);
  await page.goto("/my-account");
  await expect(sentence(page)).toHaveText("‘내 모의 계좌’에서 내는 주문은 지금 기록만 돼요. 증권사로 보내지 않아요.");

  st.mode.ba_1 = "PAPER";
  await page.reload();
  await expect(sentence(page)).toContainText("연습용 체결기로 가요");

  st.mockAllowed = false;
  await page.reload();
  await expect(sentence(page)).toContainText("증권사 모의 서버로 가요");
  await expect(sentence(page)).not.toContainText("연습용");

  st.mockAllowed = "fail";
  await page.reload();
  await expect(sentence(page)).toContainText("모의 체결로 가요");
  await expect(sentence(page)).not.toContainText("연습용 체결기");
  await expect(sentence(page)).not.toContainText("증권사 모의 서버");
});

test("BV9: 비상 정지 — 내가 건 정지와 그 밖의 정지를 가른다", async ({ page }) => {
  const { st } = await setup(page);
  st.kill.ba_1 = { active: true, event: { event_id: "K-1", trigger_reason: "잠깐 멈춤", triggered_at: "2026-10-09T12:05:00" } };
  await page.goto("/my-account");
  await expect(sentence(page)).toContainText("비상 정지 중이라 주문이 나가지 않아요");
  await expect(page.locator(".ma-kill-resolve-open")).toBeVisible();
  await expect(station(page, "kill")).toContainText("잠깐 멈춤");
  await expect(station(page, "kill")).toHaveAttribute("data-blocked", "true");

  st.kill.ba_1 = { active: true, event: null };
  await page.reload();
  await expect(sentence(page)).toContainText("이 계좌가 건 정지가 아니에요");
  await expect(page.locator(".ma-kill-resolve-open")).toHaveCount(0);
  await expect(page.locator(".ma-kill-open")).toHaveCount(0);
});

test("BV9: 모드를 못 읽으면 그렇게 말하고 주문을 막는다", async ({ page }) => {
  const { st } = await setup(page, { fail: { mode: 500 } });
  await page.goto("/my-account");
  await expect(sentence(page)).toContainText("실행 모드를 확인하지 못했어요");
  await fillOrder(page);
  await expect(page.locator(".ma-order-check")).toBeDisabled();
  delete st.fail.mode;
  await root(page).getByRole("alert").filter({ hasText: "실행 모드" }).getByRole("button", { name: "다시 시도" }).click();
  await expect(sentence(page)).toContainText("기록만 돼요");
  await expect(page.locator(".ma-order-check")).toBeEnabled();
});

// ── 주문이 가는 길 ────────────────────────────────────────────────────────

test("BV9: 길은 서버 순서대로 네 역이고 지금 상태를 말한다", async ({ page }) => {
  await setup(page);
  await page.goto("/my-account");
  await expect(page.locator(".ma-st")).toHaveCount(4);
  const keys = await page.locator(".ma-st").evaluateAll((els) => els.map((e) => e.getAttribute("data-st")));
  expect(keys).toEqual(["kill", "risk", "mode", "broker"]);
  await expect(station(page, "kill")).toContainText("꺼져 있어요");
  await expect(station(page, "kill")).not.toHaveAttribute("data-blocked", /.*/);   // 짝: 꺼져 있으면 막힘 표시 없음
  await expect(station(page, "broker")).toContainText("보내지 않아요");
  await expect(page.locator('.ma-mode-b[data-mode="SHADOW"]')).toHaveAttribute("aria-pressed", "true");
  await expect(station(page, "broker")).toContainText("잔고 조회를 받아 줬어요"); // 마지막 연결 확인 = 서버 준비 목록의 connection
});

test("BV9: 실계좌 칸은 준비 목록만 펼치고 요청을 보내지 않는다", async ({ page }) => {
  const { sent } = await setup(page);
  await page.goto("/my-account");
  const live = page.locator('.ma-mode-b[data-mode="LIVE"]');
  await expect(live).toContainText("준비 2/5");
  await live.click();
  const items = page.locator(".ma-ready-i");
  await expect(items).toHaveCount(READY_ITEMS.length);
  for (const [i, it] of READY_ITEMS.entries()) {
    await expect(items.nth(i)).toHaveAttribute("data-ok", String(it.ok));
    await expect(items.nth(i)).toContainText(it.reason);
  }
  await expect(page.locator(".ma-ready")).toContainText("실계좌 전환은 아직 열리지 않아요");
  expect(sent.filter((s) => s.method === "POST")).toEqual([]);
});

test("BV9: 모의 체결로 바꾸기는 확인을 거친다 — 취소면 요청 0, 바꾸면 PAPER 1", async ({ page }) => {
  const { sent } = await setup(page);
  await page.goto("/my-account");
  await page.locator('.ma-mode-b[data-mode="PAPER"]').click();
  await expect(page.locator(".ma-mode-confirm")).toContainText("연습용 체결기로 보내요");
  await page.locator(".ma-mode-no").click();
  expect(sent.filter((s) => s.method === "POST")).toEqual([]);
  await page.locator('.ma-mode-b[data-mode="PAPER"]').click();
  await page.locator(".ma-mode-yes").click();
  await expect(sentence(page)).toContainText("연습용 체결기로 가요");
  expect(sent.filter((s) => s.method === "POST")).toEqual([{ method: "POST", path: "/ba_1/mode", body: { mode: "PAPER" } }]);
});

test("BV9: 실계좌 계좌에선 모의 체결이 꺼져 있고 이유를 말한다 (짝: 서버가 거절하면 서버 사유)", async ({ page }) => {
  const { st } = await setup(page, { accounts: [acc("ba_r", "실계좌 하나", false), acc("ba_p", "모의 하나")] });
  await page.goto("/my-account?account=ba_r");
  // ★모드를 다 읽은 뒤에 본다★ — 읽는 동안에는 모든 칸이 꺼져 있어 '꺼짐' 단언이 공허하다(변이가 살아남았다).
  await expect(page.locator('.ma-mode-b[data-mode="SHADOW"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('.ma-mode-b[data-mode="SHADOW"]')).toBeEnabled();
  await expect(page.locator('.ma-mode-b[data-mode="PAPER"]')).toBeDisabled();
  await expect(page.locator(".ma-mode-why")).toContainText("모의투자 계좌에서만");
  await page.goto("/my-account?account=ba_p");
  await expect(page.locator('.ma-mode-b[data-mode="PAPER"]')).toBeEnabled();
  st.modeReply = { status: 400, json: { detail: "서버가 정한 거절 사유예요." } };
  await page.locator('.ma-mode-b[data-mode="PAPER"]').click();
  await page.locator(".ma-mode-yes").click();
  await expect(page.locator(".ma-mode-err")).toContainText("서버가 정한 거절 사유예요.");
});

// ── 잔고 ───────────────────────────────────────────────────────────────────

test("BV9: 잔고는 서버 숫자 그대로 · 손익은 등락색 + 부호 · 연습용이면 그렇다고", async ({ page }) => {
  await setup(page);
  await page.goto("/my-account");
  const bal = page.locator(".ma-bal");
  await expect(bal.locator(".ma-bal-cash")).toHaveText("100,000,000원");
  await expect(bal.locator(".ma-bal-total")).toHaveText("102,000,000원");
  await expect(bal.locator(".ma-bal-practice")).toBeVisible();
  const up = bal.locator('.ma-pos[data-ticker="005930"]');
  await expect(up).toContainText("삼성전자");
  await expect(up).toContainText("3주");
  await expect(up.locator(".tx-delta")).toHaveAttribute("data-dir", "up");
  await expect(up.locator(".tx-delta")).toContainText("+1.3%");
  const down = bal.locator('.ma-pos[data-ticker="000660"] .tx-delta');
  await expect(down).toHaveAttribute("data-dir", "down");
  const [cu, cd] = await Promise.all([up.locator(".tx-delta").evaluate((e) => getComputedStyle(e).color), down.evaluate((e) => getComputedStyle(e).color)]);
  expect(cu).not.toBe(cd);
});

test("BV9: 실데이터 잔고엔 연습용 표시가 없다 · 모르는 잔고는 0 이 아니라 몰라요", async ({ page }) => {
  await setup(page, { balance: { ba_1: okBalance({ practice: false, cash: null, total: null, positions: [] }) } });
  await page.goto("/my-account");
  const bal = page.locator(".ma-bal");
  await expect(bal.locator(".ma-bal-cash")).toContainText("몰라요");
  await expect(bal.locator(".ma-bal-practice")).toHaveCount(0);
  await expect(bal).toContainText("보유 종목이 없어요");
  await expect(bal.locator(".ma-bal-cash")).not.toContainText("0원");
});

test("BV9: 증권사가 거절한 잔고는 사유 + 닫힌 원래 사유 · 닿지 못하면 다시 시도", async ({ page }) => {
  const { st } = await setup(page, { balance: { ba_1: { account_id: "ba_1", practice: false, as_of: "x", state: "failed",
    reason: "증권사에 닿지 못했어요. 잠시 뒤 다시 해 주세요.", detail: "connection refused" } } });
  await page.goto("/my-account");
  const bal = page.locator(".ma-bal");
  await expect(bal.locator(".ma-bal-failed")).toContainText("증권사에 닿지 못했어요");
  await expect(bal.locator("details.ma-raw")).not.toHaveAttribute("open", "");
  await expect(bal.locator("details.ma-raw")).toContainText("connection refused");
  await expect(bal.locator(".ma-bal-cash")).toHaveCount(0);
  st.fail.balance = 500;
  await page.reload();
  await expect(bal.getByRole("alert")).toContainText("잔고를 불러오지 못했어요");
});

// ── 주문 내기 ──────────────────────────────────────────────────────────────

test("BV9: 주문 단추는 확인된 종목·사기/팔기·수량·가격이 다 있어야 켜진다", async ({ page }) => {
  const { st } = await setup(page);
  await page.goto("/my-account");
  const go = page.locator(".ma-order-check");
  await fillOrder(page, { side: null });
  await expect(page.locator(".ma-ticker-name")).toHaveText("삼성전자");
  await expect(go).toBeDisabled();                                         // 사기/팔기 기본값 없음
  await page.locator('.ma-side [data-side="BUY"]').click();
  await expect(go).toBeEnabled();
  await page.locator('input[name="ma-price"]').fill("");
  await expect(go).toBeDisabled();                                         // 가격은 늘 필요(서버 규칙)
  await fillOrder(page, { code: "999999" });
  await expect(page.locator(".ma-ticker-bad")).toContainText("알 수 없는 종목 코드");
  await expect(go).toBeDisabled();
  st.fail.names = 500;
  await fillOrder(page, { code: "000660" });
  await expect(page.locator(".ma-ticker-bad")).toContainText("종목을 확인하지 못했어요");
  await expect(go).toBeDisabled();
});

test("BV9: 확인 줄을 거쳐 내고 본문은 서버 계약 그대로 (고치기면 요청 0)", async ({ page }) => {
  const { sent } = await setup(page);
  await page.goto("/my-account");
  await fillOrder(page);
  await page.locator(".ma-order-check").click();
  await expect(page.locator(".ma-order-confirm")).toContainText("삼성전자(005930) 10주를 지정가 71,000원에 사요.");
  await expect(page.locator(".ma-order-confirm")).toContainText("기록만");
  await page.locator(".ma-order-edit").click();
  expect(sent.filter((s) => s.method === "POST")).toEqual([]);
  await page.locator(".ma-order-check").click();
  await page.locator(".ma-order-send").click();
  await expect(page.locator(".ma-order-result")).toBeVisible();
  expect(sent.filter((s) => s.method === "POST")).toEqual([{ method: "POST", path: "/ba_1/orders", body: {
    strategy_id: 0, ticker: "005930", side: "BUY", quantity: 10, price: 71000, order_type: "LIMIT", source: "manual",
  } }]);
});

test("BV9: 주문 결과는 서버가 멈춘 역에 표시된다", async ({ page }) => {
  const { st } = await setup(page);
  await page.goto("/my-account");
  const cases: [Reply["json"], string, string][] = [
    [{ client_order_id: "CO-1", status: "SHADOW_LOGGED", mode: "SHADOW", message: "SHADOW mode — 주문 발송하지 않음 (신호만 기록)" }, "mode", "기록만"],
    [{ client_order_id: "CO-2", status: "REJECTED", reason: "risk_check_failed", message: "Tier1: 장 외 시간 (09:00-15:30 KST)" }, "risk", "Tier1: 장 외 시간 (09:00-15:30 KST)"],
    [{ client_order_id: "CO-3", status: "SUBMITTED", mode: "PAPER", kis_order_id: "MOCK-1", message: "PAPER mode — KIS 모의투자 발주 완료" }, "broker", "MOCK-1"],
    [{ client_order_id: "CO-4", status: "FAILED", mode: "PAPER", error: "Mock 잔고 부족" }, "broker", "Mock 잔고 부족"],
    [{ client_order_id: "CO-5", status: "REJECTED", reason: "kill_switch_active", message: "Kill switch 활성 — 모든 거래 차단됨" }, "kill", "Kill switch 활성"],
  ];
  for (const [json, stop, text] of cases) {
    st.orderReply = { json };
    await fillOrder(page);
    await page.locator(".ma-order-check").click();
    await page.locator(".ma-order-send").click();
    await expect(page.locator(".ma-path")).toHaveAttribute("data-stop", stop);
    await expect(station(page, stop)).toHaveAttribute("data-hit", "stop");
    await expect(page.locator(".ma-stop-why")).toContainText(text);
  }
});

test("BV9: 주문 요청이 실패하면 alert — 결과처럼 그리지 않는다", async ({ page }) => {
  const { st } = await setup(page);
  st.orderReply = { status: 500, json: { detail: "서버 오류" } };
  await page.goto("/my-account");
  await fillOrder(page);
  await page.locator(".ma-order-check").click();
  await page.locator(".ma-order-send").click();
  await expect(page.locator("form.ma-order").getByRole("alert")).toContainText("주문을 보내지 못했어요");
  await expect(page.locator(".ma-path")).not.toHaveAttribute("data-stop", /.+/);
});

test("BV9: 비상 정지 중이면 주문 단추가 꺼져 있고 이유를 말한다", async ({ page }) => {
  const { st } = await setup(page);
  st.kill.ba_1 = { active: true, event: null };
  await page.goto("/my-account");
  await fillOrder(page);
  await expect(page.locator(".ma-order-check")).toBeDisabled();
  await expect(page.locator(".ma-order-why")).toContainText("비상 정지");
});

// ── 최근 주문 ──────────────────────────────────────────────────────────────

test("BV9: 최근 주문은 서버 행 그대로 · 상태 번역 · 멈춘 곳 · 취소는 취소 가능한 것만", async ({ page }) => {
  const { st, sent } = await setup(page);
  st.orders.ba_1 = [
    order("CO-1", "SHADOW_LOGGED"),
    order("CO-2", "SUBMITTED", { execution_mode: "PAPER" }),
    order("CO-3", "REJECTED", { reason_code: "risk_check_failed", error_message: "Tier1: 장 외 시간" }),
    order("CO-4", "WEIRD_STATE"),
  ];
  await page.goto("/my-account");
  const rows = page.locator(".ma-ord");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0).locator(".ma-ord-status")).toHaveText("기록만");
  await expect(rows.nth(1).locator(".ma-ord-status")).toHaveText("보냈어요");
  await expect(rows.nth(2).locator(".ma-ord-status")).toHaveText("주문하지 않았어요");
  await expect(rows.nth(2).locator(".ma-ord-stop")).toHaveAttribute("data-stop", "risk");
  await expect(rows.nth(3).locator(".ma-ord-status")).toContainText("WEIRD_STATE");
  await expect(page.locator(".ma-ord-cancel")).toHaveCount(1);
  await rows.nth(1).locator(".ma-ord-cancel").click();
  await rows.nth(1).locator(".ma-ord-cancel-no").click();
  expect(sent.filter((s) => s.method === "DELETE")).toEqual([]);
  st.cancelReply = { json: { status: "not_cancellable", current: "FILLED" } };
  await rows.nth(1).locator(".ma-ord-cancel").click();
  await rows.nth(1).locator(".ma-ord-cancel-yes").click();
  await expect(page.locator(".ma-ord-msg")).toContainText("취소할 수 없어요");
  expect(sent.filter((s) => s.method === "DELETE").map((s) => s.path)).toEqual(["/ba_1/orders/CO-2"]);
});

// ── 비상 정지 ──────────────────────────────────────────────────────────────

test("BV9: 비상 정지는 사유 4자 이상 · 보유는 그대로(hold)만 · 결과를 말한다", async ({ page }) => {
  const { sent } = await setup(page);
  await page.goto("/my-account");
  await page.locator(".ma-kill-open").click();
  const sheet = page.locator('[data-sheet="kill"]');
  await expect(sheet).toContainText("보유 종목은 팔지 않아요");
  await expect(sheet).not.toContainText("즉시");
  await expect(sheet).not.toContainText("분할");
  await sheet.locator('textarea[name="ma-kill-reason"]').fill("멈춰");
  await expect(sheet.locator(".ma-kill-go")).toBeDisabled();
  await sheet.locator('textarea[name="ma-kill-reason"]').fill("잠깐 멈춤");
  await sheet.locator(".ma-kill-go").click();
  await expect(page.locator(".ma-kill-done")).toContainText("미체결 2건을 취소했어요");
  await expect(sentence(page)).toContainText("비상 정지 중이라");
  expect(sent.filter((s) => s.method === "POST")).toEqual([
    { method: "POST", path: "/ba_1/kill-switch/trigger", body: { reason: "잠깐 멈춤", liquidation_mode: "hold" } },
  ]);
});

test("BV9: 내가 건 정지는 다시 열 수 있다", async ({ page }) => {
  const { st, sent } = await setup(page);
  st.kill.ba_1 = { active: true, event: { event_id: "K-1", trigger_reason: "잠깐 멈춤", triggered_at: "2026-10-09T12:05:00" } };
  await page.goto("/my-account");
  await page.locator(".ma-kill-resolve-open").click();
  await page.locator('[data-sheet="resolve"] .ma-kill-resolve').click();
  await expect(sentence(page)).toContainText("기록만 돼요");
  expect(sent.filter((s) => s.method === "POST").map((s) => s.path)).toEqual(["/ba_1/kill-switch/resolve"]);
});

// ── 계좌 바꾸기 ────────────────────────────────────────────────────────────

test("BV9: 계좌를 바꾸면 주소가 따라가고 옛 계좌 숫자가 남지 않는다", async ({ page }) => {
  await setup(page, {
    accounts: [acc("ba_1", "첫 계좌"), acc("ba_2", "둘째 계좌")],
    balance: { ba_2: okBalance({ cash: 77_770_000 }), ba_1: okBalance({ cash: 100_000_000 }) },
    delay: { "balance:ba_1": 2500 },
  });
  await page.goto("/my-account?account=ba_2");
  await expect(page.locator(".ma-bal-cash")).toHaveText("77,770,000원");
  await page.locator("select.ma-acct").selectOption("ba_1");
  await expect(page).toHaveURL(/account=ba_1/);
  await expect(sentence(page)).toContainText("첫 계좌");
  await expect(page.locator(".ma-bal")).not.toContainText("77,770,000원");
  await expect(page.locator(".ma-bal-cash")).toHaveText("100,000,000원", { timeout: 6000 });
});

// ── 더한 도구: 자산 구성 · 보유에서 고르기 · 수량 칩 · 주문 금액 · 주문 거르기 · 자주 쓰는 사유 · 멈춘 역 ──────────

const pos = (ticker: string, quantity: number | null, current: number | null, evalAmount: number | null) => ({
  ticker, quantity, avg_price: current, current_price: current, eval_amount: evalAmount, pnl_pct: 1.0,
});

test("BV9: 자산 구성 막대 = 서버 숫자의 비율 · 모르는 값이 하나라도 있으면 그리지 않는다 (짝)", async ({ page }) => {
  const { st } = await setup(page, { balance: { ba_1: okBalance({ cash: 600_000, total: 1_000_000,
    positions: [pos("005930", 3, 71000, 300_000), pos("000660", 2, 130000, 100_000)] }) } });
  await page.goto("/my-account");
  const segs = page.locator(".ma-mix-seg");
  await expect(segs).toHaveCount(3);
  expect(await segs.evaluateAll((els) => els.map((e) => [e.getAttribute("data-key"), (e as HTMLElement).style.width])))
    .toEqual([["cash", "60%"], ["005930", "30%"], ["000660", "10%"]]);
  const w = await segs.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().width));
  expect(w[0] / w[2]).toBeGreaterThan(5.4);                                // 그려진 폭도 6 : 3 : 1
  expect(w[0] / w[2]).toBeLessThan(6.6);
  expect(w[1] / w[2]).toBeGreaterThan(2.7);
  expect(w[1] / w[2]).toBeLessThan(3.3);
  await expect(page.locator('.ma-mix-l li[data-key="cash"]')).toContainText("예수금");
  await expect(page.locator('.ma-mix-l li[data-key="cash"] .ma-mix-v')).toHaveText("60.0%");
  await expect(page.locator('.ma-mix-l li[data-key="005930"]')).toContainText("삼성전자");
  await expect(page.locator(".ma-mix-bar")).toHaveAttribute("aria-label", /예수금 60\.0%.*삼성전자 30\.0%.*SK하이닉스 10\.0%/);
  // 짝: 숫자를 바꾸면 비율이 따라간다(상수 배제)
  st.balance.ba_1 = okBalance({ cash: 200_000, total: 1_000_000, positions: [pos("005930", 3, 71000, 400_000), pos("000660", 2, 130000, 400_000)] });
  await page.reload();
  await expect.poll(() => segs.evaluateAll((els) => els.map((e) => (e as HTMLElement).style.width))).toEqual(["20%", "40%", "40%"]);
  // 다 판 종목(평가액 0 — 아는 값)은 칸을 그리지 않는다. 짝: 이건 '모름'이 아니라 그림은 그대로 있다
  st.balance.ba_1 = okBalance({ cash: 600_000, positions: [pos("005930", 0, 71000, 0), pos("000660", 2, 130000, 400_000)] });
  await page.reload();
  await expect.poll(() => segs.evaluateAll((els) => els.map((e) => e.getAttribute("data-key")))).toEqual(["cash", "000660"]);
  await expect(page.locator(".ma-mix-none")).toHaveCount(0);
  // 짝: 한 종목의 평가액을 모르면 그림 대신 사유 — 0 으로 메워 비율을 지어내지 않는다
  st.balance.ba_1 = okBalance({ cash: 600_000, positions: [pos("005930", 3, 71000, null), pos("000660", 2, 130000, 100_000)] });
  await page.reload();
  await expect(page.locator(".ma-mix-none")).toContainText("그리지 않았어요");
  await expect(segs).toHaveCount(0);
  st.balance.ba_1 = okBalance({ cash: null });
  await page.reload();
  await expect(page.locator(".ma-mix-none")).toBeVisible();
});

test("BV9: 보유에서 고르면 코드와 지금 값이 채워지고 사기/팔기는 비어 있다 (짝: 보유가 없으면 칸이 없다)", async ({ page }) => {
  const { st } = await setup(page);
  await page.goto("/my-account");
  const f = page.locator("form.ma-order");
  await expect(f.locator(".ma-hold")).toHaveCount(2);
  await f.locator('.ma-hold[data-ticker="000660"]').click();
  await expect(f.locator('input[name="ma-ticker"]')).toHaveValue("000660");
  await expect(f.locator('input[name="ma-price"]')).toHaveValue("130000");
  await expect(f.locator(".ma-price-from")).toContainText("잔고의 지금 값");
  await expect(f.locator('.ma-hold[data-ticker="000660"]')).toHaveAttribute("aria-pressed", "true");
  await expect(f.locator('.ma-hold[data-ticker="005930"]')).toHaveAttribute("aria-pressed", "false");
  await expect(f.locator('.ma-side [aria-pressed="true"]')).toHaveCount(0);  // 돈이 걸린 선택은 대신 고르지 않는다
  await expect(page.locator(".ma-order-check")).toBeDisabled();
  await f.locator('input[name="ma-price"]').fill("129000");                // 손으로 고치면 '채웠어요' 표시가 사라진다
  await expect(f.locator(".ma-price-from")).toHaveCount(0);
  st.balance.ba_1 = okBalance({ positions: [] });
  await page.reload();
  await expect(f.locator(".ma-holds")).toHaveCount(0);
});

test("BV9: 수량 칩은 더하고 '보유 전부'는 보유 수량 그대로 (짝: 보유하지 않은 종목엔 없다)", async ({ page }) => {
  await setup(page);
  await page.goto("/my-account");
  const f = page.locator("form.ma-order");
  const qty = f.locator('input[name="ma-qty"]');
  await f.locator('input[name="ma-ticker"]').fill("005930");
  await f.locator('.ma-chip-b[data-add="10"]').click();
  await f.locator('.ma-chip-b[data-add="1"]').click();
  await f.locator('.ma-chip-b[data-add="100"]').click();
  await expect(qty).toHaveValue("111");
  await expect(f.locator(".ma-qty-all")).toHaveText("보유 전부 3주");
  await f.locator(".ma-qty-all").click();
  await expect(qty).toHaveValue("3");
  await f.locator('input[name="ma-ticker"]').fill("035720");
  await expect(f.locator(".ma-qty-all")).toHaveCount(0);
});

test("BV9: 주문 금액 어림 = 수량 × 가격 · 예수금 비율 (짝: 예수금을 모르면 비율을 보이지 않는다)", async ({ page }) => {
  const { st } = await setup(page, { balance: { ba_1: okBalance({ cash: 1_000_000 }) } });
  await page.goto("/my-account");
  const amount = page.locator(".ma-amount");
  await expect(amount).toHaveCount(0);                                     // 수량·가격 전엔 없다
  await fillOrder(page, { qty: "10", price: "71000" });
  await expect(amount.locator(".ma-amount-v")).toHaveText("710,000원");
  await expect(amount.locator(".ma-amount-r")).toHaveText("예수금의 71.0%");
  await expect(amount).toContainText("수수료와 세금은 빠졌어요");
  await page.locator('input[name="ma-qty"]').fill("2");
  await expect(amount.locator(".ma-amount-v")).toHaveText("142,000원");
  st.balance.ba_1 = okBalance({ cash: null });
  await page.reload();
  await fillOrder(page, { qty: "10", price: "71000" });
  await expect(amount.locator(".ma-amount-v")).toHaveText("710,000원");
  await expect(amount.locator(".ma-amount-r")).toHaveCount(0);
});

test("BV9: 주문 거르기 — 수는 서버 행을 센 값 · 누르면 그 무리만 (짝: 빈 무리는 문장)", async ({ page }) => {
  const { st } = await setup(page);
  st.orders.ba_1 = [
    order("CO-1", "SHADOW_LOGGED"), order("CO-2", "SUBMITTED"), order("CO-3", "FILLED"),
    order("CO-4", "REJECTED", { reason_code: "risk_check_failed" }), order("CO-5", "FAILED"), order("CO-6", "WEIRD_STATE"),
  ];
  await page.goto("/my-account");
  const chip = (f: string) => page.locator(`.ma-ord-filter .ma-chip-b[data-f="${f}"]`);
  const coids = () => page.locator(".ma-ord").evaluateAll((els) => els.map((e) => e.getAttribute("data-coid")));
  await expect(page.locator(".ma-ord")).toHaveCount(6);
  for (const [f, n] of [["all", "6"], ["sent", "2"], ["stopped", "2"], ["shadow", "1"]]) await expect(chip(f).locator(".ma-chip-n")).toHaveText(n);
  await expect(chip("all")).toHaveAttribute("aria-pressed", "true");
  await chip("stopped").click();
  await expect(chip("stopped")).toHaveAttribute("aria-pressed", "true");
  await expect(chip("all")).toHaveAttribute("aria-pressed", "false");
  await expect.poll(coids).toEqual(["CO-4", "CO-5"]);
  await chip("sent").click();
  await expect.poll(coids).toEqual(["CO-2", "CO-3"]);
  await chip("all").click();
  await expect(page.locator(".ma-ord")).toHaveCount(6);                  // 모르는 상태도 '전체'에는 있다
  st.orders.ba_1 = [order("CO-1", "SHADOW_LOGGED")];
  await page.reload();
  await chip("stopped").click();
  await expect(page.locator(".ma-ord")).toHaveCount(0);
  await expect(page.locator(".ma-ord-none")).toBeVisible();
});

test("BV9: 자주 쓰는 사유를 누르면 칸이 채워지고, 고쳐 쓴 글이 그대로 간다", async ({ page }) => {
  const { sent } = await setup(page);
  await page.goto("/my-account");
  await page.locator(".ma-kill-open").click();
  const sheet = page.locator('[data-sheet="kill"]');
  const box = sheet.locator('textarea[name="ma-kill-reason"]');
  const preset = sheet.locator(".ma-kill-preset", { hasText: "시장이 크게 흔들려서" });
  await preset.click();
  await expect(box).toHaveValue("시장이 크게 흔들려서");
  await expect(preset).toHaveAttribute("aria-pressed", "true");
  await expect(sheet.locator(".ma-kill-go")).toBeEnabled();
  await box.fill("시장이 크게 흔들려서 오늘은 쉬어요");
  await expect(preset).toHaveAttribute("aria-pressed", "false");
  await sheet.locator(".ma-kill-go").click();
  await expect(page.locator(".ma-kill-done")).toBeVisible();
  expect(sent.filter((s) => s.method === "POST")).toEqual([
    { method: "POST", path: "/ba_1/kill-switch/trigger", body: { reason: "시장이 크게 흔들려서 오늘은 쉬어요", liquidation_mode: "hold" } },
  ]);
});

test("BV9: 멈춘 역에서만 고리가 한 번 퍼지고, 감속 모션이면 움직이지 않는다", async ({ page }) => {
  const { st } = await setup(page);
  st.orderReply = { json: { client_order_id: "CO-9", status: "REJECTED", reason: "risk_check_failed", message: "Tier1: 장 외 시간" } };
  const ring = (k: string) => station(page, k).locator(".ma-st-dot")
    .evaluate((e) => { const c = getComputedStyle(e, "::after"); return `${c.animationName}/${c.animationIterationCount}`; });
  for (const motion of ["no-preference", "reduce"] as const) {
    await page.emulateMedia({ reducedMotion: motion });
    await page.goto("/my-account");
    await expect(page.locator(".ma-st-dot svg")).toHaveCount(4);
    await fillOrder(page);
    await page.locator(".ma-order-check").click();
    await page.locator(".ma-order-send").click();
    await expect(station(page, "risk")).toHaveAttribute("data-hit", "stop");
    if (motion === "no-preference") {
      expect(await ring("risk")).toBe("ma-pulse/1");
      expect(await ring("kill")).toMatch(/^none\//);                    // 지나간 역은 퍼지지 않는다
    } else {
      expect(await ring("risk")).toMatch(/^none\//);
    }
  }
});

// ── 글 · 대비 · 390 ────────────────────────────────────────────────────────

for (const scheme of ["light", "dark"] as const) {
  test(`BV9: ${scheme} AA · 390 넘침 없음 · em-dash·툴팁·영어 대문자 없음`, async ({ page }) => {
    const { st } = await setup(page);
    st.orders.ba_1 = [order("CO-1", "SHADOW_LOGGED"), order("CO-2", "SUBMITTED"), order("CO-3", "REJECTED", { reason_code: "risk_check_failed" })];
    st.orderReply = { json: { client_order_id: "CO-9", status: "REJECTED", reason: "risk_check_failed", message: "Tier1: 장 외 시간" } };
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* 없음 */ } }, scheme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/my-account");
      await page.locator('.ma-mode-b[data-mode="LIVE"]').click();
      await expect(page.locator(".ma-ready")).toBeVisible();
      await fillOrder(page);
      await page.locator(".ma-order-check").click();
      await page.locator(".ma-order-send").click();
      await expect(page.locator(".ma-stop-why")).toBeVisible();
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, `${width}px 가로 넘침`).toBeLessThanOrEqual(0);
      const sticking = await page.evaluate<string[]>(cardsOverflow(".ma .tx-sec, .ma .tx-answer"));
      expect(sticking, `${width}px 카드 밖으로 나간 칸`).toEqual([]);
      const a = await page.evaluate<AuditResult>(contrastAudit(".ma"));
      expect(a.checked).toBeGreaterThan(40);
      expect(a.low, `${scheme} ${width} 대비`).toEqual([]);
      if (scheme === "dark") expect(a.bright, "다크인데 밝은 바탕").toEqual([]);
      const own = await root(page).evaluate((el) => {
        const t = Array.from(el.querySelectorAll("*")).filter((n) => !n.closest("[data-server]"))
          .flatMap((n) => Array.from(n.childNodes).filter((c) => c.nodeType === 3).map((c) => c.textContent ?? "")).join(" ");
        return { dash: /[—–]/.test(t), caps: (t.match(/\b[A-Z]{4,}\b/g) ?? []), titles: el.querySelectorAll("[title]").length };
      });
      expect(own.dash, "em-dash").toBe(false);
      expect(own.caps, "영어 대문자 낱말").toEqual([]);
      expect(own.titles, "툴팁(title)").toBe(0);
      await page.locator(".ma-kill-open").click();
      await page.locator('[data-sheet="kill"] .ma-kill-preset').first().click();
      const k = await page.evaluate<AuditResult>(contrastAudit('[data-sheet="kill"]'));
      expect(k.checked).toBeGreaterThan(5);
      expect(k.low, `${scheme} ${width} 비상 정지 시트 대비`).toEqual([]);
      if (scheme === "dark") expect(k.bright, "다크인데 밝은 바탕(시트)").toEqual([]);
    }
  });
}
