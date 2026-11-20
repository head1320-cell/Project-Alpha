import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page, type Route } from "./fixtures";
import { cardsOverflow, contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 판 배치(G6 2a-2 · 작업 공간 2단계) — 내 계좌 (설계 `docs/superpowers/specs/2026-11-19-workspace-panels-design.md` §4.2 · 계획 §10)
// ────────────────────────────────────────────────────────────────────────────
// 응답은 이 스펙이 정한다(my-account.spec.ts 와 같은 까닭 — 개발 서버에는 금고 키가 없어 실제 계좌를 만들 수 없다). 증권사 · 서버로 가는 주문은 0 이다.
// 첫 묶음은 ★판 배치를 끈 화면이 2a-2 전과 같다★ — 골든(`golden/account-dom.json`)은 2a-2 코드를 쓰기 전 빌드에서 떴다(`UPDATE_ACCOUNT_GOLDEN=1`).
// 더한 것은 넓은 창 머리 오른쪽의 '배치' 단추(`.ws-open`) 하나(계좌가 하나면 그 자리 `.tx-head-act` 도 그 단추 때문에 선다)뿐이어야 한다.
// 둘째 묶음부터는 판 배치를 켠 화면 — 판 넷(주문 제출 · 최근 주문 · 잔고 · 규칙 가동) · ★붙은 문장 띠★(탭 보기에서 비상 정지 단추 · 모드 문장 · 칩이 굴려도 창 위에 —
// 정지 결과 줄 · 주문 전송 경로는 판 위에서 페이지와 함께 구른다 · 계획 §10.1 의 잰 값) · ★주문 제출 판은 닫지 못한다★ ·
// ★배치 조작은 계좌로 가는 쓰기를 하나도 부르지 않고 주문 폼(입력 · 확인 줄)을 다시 세우지 않는다★ · 처음 배치 둘('주문' · '관제') · 판 이름 = 절 제목 하나 ·
// 저장 열쇠(`ws.account*`) · 계좌 바꾸기 · 계좌가 없을 때 · 좁은 창 쌓기(붙지 않음) · 대비 · 문체 ·
// 띠 높이가 바뀌면(응답 전 '상태 확인 중' · 긴 계좌 이름 · 창 폭) 작업 공간이 따라 맞는다 · 탭 보기는 본문 폭을 다 쓴다 · 1280 × 800(가장 작은 탭 보기)의 한 줄 띠와 '주문 확인' ·
// 끈 화면의 배치 관리 시트에서 가져오면 판 배치가 켜져도 시트 · 결과 문장이 남는다.
// ════════════════════════════════════════════════════════════════════════════

const GOLDEN = path.join(__dirname, "golden", "account-dom.json");
const WRITE = process.env.UPDATE_ACCOUNT_GOLDEN === "1";
const WIDE = { width: 1440, height: 900 };
const HUGE = { width: 1920, height: 1080 };
const PHONE = { width: 390, height: 844 };
const K = { layout: "ws.account", on: "ws.account.on", saved: "ws.account.saved" };
const NAMES: Record<string, string> = { order: "주문 제출", orders: "최근 주문", balance: "잔고", arming: "규칙 가동" };

type Acc = { account_id: string; label: string; is_paper: boolean; account_prdt: string; app_key_last4: string; account_no_masked: string; created_at: string };
const acc = (id: string, label: string, is_paper = true): Acc => ({
  account_id: id, label, is_paper, account_prdt: "01", app_key_last4: "cdef", account_no_masked: "****5678", created_at: "2026-10-09T08:00:00",
});
const READY = [
  { key: "gate", ok: false, reason: "운영자가 실계좌 관문을 열지 않았습니다(선언 없음)." },
  { key: "real_account", ok: false, reason: "모의투자 계좌입니다. 실계좌 주문은 실계좌로 연결한 계좌에서만 합니다." },
  { key: "connection", ok: true, reason: "증권사가 이 계좌의 잔고 조회를 수락했습니다." },
  { key: "paper_practice", ok: true, reason: "내 모의투자 계좌에서 증권사 모의 서버가 받은 주문이 2건 있습니다." },
  { key: "reconciliation", ok: false, reason: "이 계좌를 증권사 잔고와 맞춰 보는 대조 감시가 아직 없습니다. 그래서 실계좌 전환은 열지 않습니다." },
];
const balance = (total: number) => ({
  account_id: "x", practice: true, as_of: "2026-10-09T12:04:00+00:00", state: "ok", cash_krw: 100_000_000, evaluated_total: total,
  positions: [
    { ticker: "005930", quantity: 3, avg_price: 70100, current_price: 71000, eval_amount: 213000, pnl_pct: 1.28 },
    { ticker: "000660", quantity: 2, avg_price: 132000, current_price: 130000, eval_amount: 260000, pnl_pct: -1.52 },
  ],
});
const order = (coid: string, status: string, extra: Record<string, unknown> = {}) => ({
  client_order_id: coid, ticker: "005930", side: "BUY", quantity: 10, price: 71000, status,
  execution_mode: "SHADOW", reason_code: null, error_message: null, created_at: "2026-10-09 12:01:00", ...extra,
});

type St = {
  accounts: Acc[]; balance: Record<string, unknown>; orders: Record<string, unknown[]>; kill: Record<string, { active: boolean; event: unknown }>;
  /** 모드 · 비상 정지 응답을 늦추는 ms — 문장 띠가 '상태 확인 중'으로 먼저 서는 때(띠 높이가 바뀌는 길)를 재현한다 */
  slow: number;
};
type Sent = { method: string; path: string };

/** 응답을 정하고, 계좌로 가는 요청을 모두 적는다(배치 조작이 상태를 바꾸는 부름을 하나도 하지 않는다는 것을 건다). */
async function setup(page: Page, o: Partial<St> = {}) {
  const st: St = {
    accounts: [acc("ba_1", "내 모의 계좌")],
    balance: { ba_1: balance(102_000_000), ba_2: balance(55_500_000) },
    orders: { ba_1: [order("CO-1", "SHADOW_LOGGED"), order("CO-2", "SUBMITTED"), order("CO-3", "REJECTED", { reason_code: "risk_check_failed" })], ba_2: [] },
    kill: {},
    slow: 0,
    ...o,
  };
  const sent: Sent[] = [];
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "minji", role: "analyst" }, must_change_password: false, password_changed_at: "2026-10-01T00:00:00",
  } }));
  page.on("request", (req) => {
    const url = new URL(req.url());
    const i = url.pathname.indexOf("/api/v1/broker-accounts");
    if (i >= 0) sent.push({ method: req.method(), path: url.pathname.slice(i + "/api/v1/broker-accounts".length) });
  });
  await page.route("**/api/v1/macro/connection-status", (r) => r.fulfill({ json: { mock_allowed: true, real_mode: false, bok_configured: false, fred_configured: false } }));
  await page.route("**/api/v1/allocation/resolve-names", (r) => {
    const codes = (r.request().postDataJSON() as { codes: string[] }).codes;
    const names: Record<string, string> = { "005930": "삼성전자", "000660": "SK하이닉스" };
    return r.fulfill({ json: { labels: Object.fromEntries(codes.map((c) => [c, names[c] ?? c])) } });
  });
  await page.route("**/api/v1/intraday/arm-requests", (r) => r.fulfill({ json: { available: true, reason: null, requests: [], gate: { mock: true } } }));
  await page.route("**/api/v1/intraday/templates", (r) => r.fulfill({ json: { templates: [], position: [], costs: [], limits: {}, session_rules: {}, unknowns: [], gate: { mock: true } } }));
  await page.route("**/api/v1/broker-accounts**", async (r: Route) => {
    const req = r.request();
    const url = new URL(req.url());
    const p = url.pathname.slice(url.pathname.indexOf("/api/v1/broker-accounts") + "/api/v1/broker-accounts".length);
    const m = req.method();
    if (p === "" && m === "GET") return r.fulfill({ json: { accounts: st.accounts } });
    const [, id, ...rest] = p.split("/");
    const tail = rest.join("/");
    if ((tail === "mode" || tail === "kill-switch") && m === "GET" && st.slow > 0) await new Promise((res) => setTimeout(res, st.slow));
    if (tail === "mode" && m === "GET") return r.fulfill({ json: { mode: "SHADOW", changed_by: null, last_mode_change: null } });
    if (tail === "kill-switch" && m === "GET") return r.fulfill({ json: st.kill[id] ?? { active: false, event: null } });
    if (tail === "live-readiness") return r.fulfill({ json: { account_id: id, ready: false, items: READY } });
    if (tail === "balance") return r.fulfill({ json: st.balance[id] ?? balance(1) });
    if (tail === "orders" && m === "GET") { const l = st.orders[id] ?? []; return r.fulfill({ json: { count: l.length, orders: l } }); }
    if (tail === "rule-runs" && m === "GET") {
      return r.fulfill({ json: { available: true, reason: null, runs: [], mode: "SHADOW", kill_switch: false, gate: { mock: true }, limits: { runs: 3, tickers: 10, gap_minutes: 5 } } });
    }
    if (tail === "orders" && m === "POST") {
      return r.fulfill({ json: { client_order_id: "CO-new", status: "SHADOW_LOGGED", mode: "SHADOW", message: "SHADOW mode — 주문 발송하지 않음 (신호만 기록)" } });
    }
    return r.fulfill({ status: 404, json: { detail: "이 스펙이 정하지 않은 경로" } });
  });
  return { st, sent };
}

/** 상태를 바꾸는 부름(POST · DELETE · PUT · PATCH) — 계좌로 가는 것만. */
const writes = (sent: Sent[]) => sent.filter((s) => s.method !== "GET");

async function open(page: Page, viewport = WIDE): Promise<void> {
  await page.setViewportSize(viewport);
  await page.goto("/my-account", { waitUntil: "domcontentloaded" });
  await settle(page);
}

/** 화면이 다 섰다 — 잔고 보유 · 최근 주문 줄 · 주문 경로 넷 · 준비 수 · 규칙 가동 절. */
async function settle(page: Page): Promise<void> {
  await expect(page.locator(".ma-pos").first()).toBeVisible();
  await expect(page.locator(".ma-ord").first()).toBeVisible();
  await expect(page.locator(".ma-st")).toHaveCount(4);
  await expect(page.locator('.ma-mode-b[data-mode="LIVE"] .tx-mode-d')).toContainText("준비");
  await expect(page.locator(".ma-arm")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

async function fillOrder(page: Page): Promise<void> {
  const f = page.locator("form.ma-order");
  await f.locator('input[name="ma-ticker"]').fill("005930");
  await f.locator('.ma-side [data-side="BUY"]').click();
  await f.locator('input[name="ma-qty"]').fill("10");
  await f.locator('input[name="ma-price"]').fill("71000");
  await expect(page.locator(".ma-ticker-name")).toHaveText("삼성전자");
}

const tab = (page: Page, id: string) => page.locator(`.ws-tab[data-tab="${id}"]`);
const panel = (page: Page, id: string) => page.locator(`.ws-panel[data-panel="${id}"]`);
const head = (page: Page, area: string) => page.locator(`.ws-head[data-area="${area}"]`);
const item = (page: Page, name: string | RegExp) => page.locator(".ws-menu").getByRole("menuitem", { name });
const radio = (page: Page, name: string) => page.locator(".ws-menu").getByRole("menuitemradio", { name });
const stored = async (page: Page, key = K.layout): Promise<unknown> => JSON.parse(await page.evaluate((k) => localStorage.getItem(k) ?? "null", key));

async function wsOn(page: Page): Promise<void> {
  await page.locator(".ws-open").first().click();
  await radio(page, "판 배치").click();
  await expect(page.locator(".ma")).toHaveAttribute("data-ws", "tabs");
}

async function panelMenu(page: Page, area: string, name: string | RegExp, check = false): Promise<void> {
  await head(page, area).locator(".ws-menu-open").click();
  await (check ? page.locator(".ws-menu").getByRole("menuitemcheckbox", { name }) : item(page, name)).click();
}

/** 비상 정지 단추가 판 밖에 있고, 본문을 맨 위로 굴려도 끝까지 굴려도 창 안(머리줄 아래)에 다 보인다. */
async function killInView(page: Page, why: string): Promise<void> {
  const k = page.locator(".ma-kill-open");
  expect(await k.evaluate((el) => !!el.closest(".ws")), `${why} — 판 안에 있다`).toBe(false);
  const main = (await page.locator(".terminal-main").boundingBox())!;
  for (const to of ["top", "end"] as const) {
    await scrollMain(page, to);
    await expect(k, `${why} · ${to}`).toBeVisible();
    const b = (await k.boundingBox())!;
    expect(b.y, `${why} · ${to} — 위로 벗어남`).toBeGreaterThanOrEqual(main.y - 1);
    expect(b.y + b.height, `${why} · ${to} — 아래로 벗어남`).toBeLessThanOrEqual(main.y + main.height + 1);
  }
  await scrollMain(page, "top");
}

// ── 골든 — 판 배치를 끈 화면 ─────────────────────────────────────────────────

type DomState = { skeleton: string[]; boxes?: Record<string, number[]> };
type DomGolden = { note: string; states: Record<string, DomState> };

/** `.ma` 아래 DOM 의 뼈대 — 깊이 3(머리 · 띠 · 그리드의 절과 그 머리) + 머리(`.tx-head`)는 끝까지. '배치' 단추와 그 단추만 든 머리 칸은 뺀다(더한 것). */
function skeleton(page: Page): Promise<string[]> {
  return page.locator(".ma").evaluate((root) => {
    const out: string[] = [];
    const ids = new Map<string, string>();
    const idOf = (v: string) => { if (!ids.has(v)) ids.set(v, `@${ids.size}`); return ids.get(v)!; };
    const REF = new Set(["id", "aria-labelledby", "aria-controls", "aria-describedby", "for", "aria-activedescendant"]);
    const KEEP = (n: string) => n === "role" || n === "hidden" || n === "tabindex" || n === "type" || n === "disabled" || n === "style" || n === "open" ||
      n.startsWith("aria-") || n.startsWith("data-");
    const added = (el: Element) => el.classList.contains("ws-open") ||
      (el.classList.contains("tx-head-act") && el.children.length > 0 && Array.from(el.children).every((c) => c.classList.contains("ws-open")));
    const walk = (el: Element, depth: number, deep: boolean) => {
      if (added(el)) return;
      const attrs: string[] = [];
      for (const a of Array.from(el.attributes).sort((x, y) => x.name.localeCompare(y.name))) {
        if (a.name === "class") continue;
        if (REF.has(a.name)) attrs.push(`${a.name}=${a.value.split(/\s+/).map((v) => (/[«»:]/.test(v) ? idOf(v) : v)).join(" ")}`);
        else if (KEEP(a.name)) attrs.push(`${a.name}=${a.value}`);
      }
      const cls = Array.from(el.classList).join(".");
      out.push(`${"  ".repeat(depth)}${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""}${attrs.length ? ` [${attrs.join(" ")}]` : ""}`);
      const full = deep || el.classList.contains("tx-head");
      if (depth >= 3 && !full) return;
      for (const c of Array.from(el.children)) walk(c, depth + 1, full);
    };
    walk(root, 0, false);
    return out;
  });
}

const BOXES = [".ma > .tx-head", ".ma > .tx-head .tx-head-main", ".ma > .tx-subnav", ".ma > .tx-answer", ".ma > .ma-path", ".ma > .ma-grid",
  ".ma-bal", "form.ma-order", ".ma-orders", ".ma-arm"];

/** ★내용 크기 상자★ — 폭을 정한 규칙이 없는 플렉스 항목이라 폭이 그 안 글자의 폭이다(머리 칸 = 한 줄 설명의 폭). 글자 폭은 브라우저 빌드마다 조금 달라서
 *  (2026-11-20 CI: 460 ↔ 골든을 뜬 로컬 456 — 0.9% · 같은 줄의 x · y · 높이는 같았다) 골든의 절대 px 와 견주면 '2a-2 전과 같은가'가 아니라 '골든을 뜬 기계와 같은가'를 묻게 된다.
 *  그래서 폭만은 ★같은 화면에서 잰 내용 폭★과 견준다 — 눌리지도(줄바꿈 · 잘림) 늘어나지도 않았다는 같은 계약을, 어느 브라우저에서나. x · y · 높이는 골든 그대로. */
const CONTENT_WIDE = new Set([".ma > .tx-head .tx-head-main"]);

/** 그 상자의 자식들 가운데 가장 넓은 글(내용)의 폭 — 상자가 내용 크기라면 상자 폭과 같다. */
function contentWidth(page: Page, sel: string): Promise<number> {
  return page.locator(sel).first().evaluate((el) => {
    let w = 0;
    for (const c of Array.from(el.children)) {
      const r = document.createRange();
      r.selectNodeContents(c);
      w = Math.max(w, r.getBoundingClientRect().width);
    }
    return w;
  });
}

async function boxes(page: Page): Promise<Record<string, number[]>> {
  const out: Record<string, number[]> = {};
  for (const sel of BOXES) {
    const b = await page.locator(sel).first().boundingBox();
    expect(b, sel).not.toBeNull();
    out[sel] = [b!.x, b!.y, b!.width, b!.height].map((v) => Math.round(v));
  }
  return out;
}

const readGolden = (): DomGolden => JSON.parse(fs.readFileSync(GOLDEN, "utf-8")) as DomGolden;
const written: Record<string, DomState> = {};
test.afterAll(() => {
  if (!WRITE || Object.keys(written).length === 0) return;
  const prev: DomGolden = fs.existsSync(GOLDEN) ? readGolden() : { note: "", states: {} };
  fs.writeFileSync(GOLDEN, `${JSON.stringify({
    note: "판 배치(G6 2a-2)를 끈 내 계좌 화면의 DOM 뼈대 · 상자 — 2a-2 코드를 쓰기 전 빌드에서 UPDATE_ACCOUNT_GOLDEN=1 로 떴다. 더한 것은 '배치' 단추(.ws-open)와 그 단추만 든 머리 칸뿐이어야 한다.",
    states: { ...prev.states, ...written },
  }, null, 1)}\n`, "utf-8");
});

async function same(page: Page, name: string, withBoxes: boolean): Promise<void> {
  const got: DomState = { skeleton: await skeleton(page) };
  if (withBoxes) got.boxes = await boxes(page);
  if (WRITE) { written[name] = got; return; }
  const want = readGolden().states[name];
  expect(want, `골든에 ${name} 이 없습니다`).toBeTruthy();
  expect(got.skeleton.join("\n")).toBe(want.skeleton.join("\n"));
  // 어긋난 상자를 한 번에 다 보인다(soft) — 첫 어긋남에서 멈추면 다른 환경(CI)에서 무엇이 더 다른지 한 실행으로 알 수 없다.
  for (const [sel, b] of Object.entries(want.boxes ?? {})) {
    const g = got.boxes?.[sel];
    expect(g, sel).toBeTruthy();
    for (let i = 0; i < 4; i++) {
      if (i === 2 && CONTENT_WIDE.has(sel)) {
        const inner = await contentWidth(page, sel);
        const box = (await page.locator(sel).first().boundingBox())!.width;
        expect.soft(inner, `${sel} — 안에 글이 없다`).toBeGreaterThan(0);
        expect.soft(Math.abs(box - inner), `${sel} 폭 ${box} ↔ 그 안 글의 폭 ${inner} — 내용 크기 상자가 눌리거나 늘어났다`).toBeLessThanOrEqual(1);
        continue;
      }
      expect.soft(Math.abs(g![i] - b[i]), `${sel}[${i}] ${JSON.stringify(g)} ↔ ${JSON.stringify(b)}`).toBeLessThanOrEqual(1);
    }
  }
}

test.describe("판 배치를 끈 화면은 2a-2 전과 같다(골든)", () => {
  test("1440 × 900 · 계좌 하나 · 뼈대와 상자", async ({ page }) => {
    await setup(page);
    await open(page);
    await same(page, "1440-one", true);
  });

  test("1440 × 900 · 저장된 배치 · 이름 붙인 배치가 있어도 켜지 않았으면 같은 화면", async ({ page }) => {
    test.skip(WRITE, "골든을 뜨는 돌림(같은 상태 '1440-one' 을 대조만 한다)");
    await setup(page);
    await page.addInitScript(() => {
      try {
        const lay = { v: 1, screen: "account", cols: [{ w: null, rows: [{ tabs: ["order", "orders", "balance", "arming"], active: "order" }] }], closed: [] };
        localStorage.setItem("ws.account", JSON.stringify(lay));
        localStorage.setItem("ws.account.saved", JSON.stringify({ v: 1, screen: "account", items: [{ name: "한 칸", layout: lay }] }));
      } catch { /* */ }
    });
    await open(page);
    await same(page, "1440-one", true);
  });

  test("1920 × 1080 · 계좌 하나 · 뼈대와 상자", async ({ page }) => {
    await setup(page);
    await open(page, HUGE);
    await same(page, "1920-one", true);
  });

  test("1440 × 900 · 계좌 둘(머리의 계좌 고르기) · 뼈대와 상자", async ({ page }) => {
    await setup(page, { accounts: [acc("ba_1", "내 모의 계좌"), acc("ba_2", "두 번째 계좌")] });
    await open(page);
    await same(page, "1440-two", true);
  });

  test("1440 × 900 · 주문을 낸 뒤(멈춘 역) · 준비 목록을 편 뒤", async ({ page }) => {
    await setup(page);
    await open(page);
    await fillOrder(page);
    await page.locator(".ma-order-check").click();
    await page.locator(".ma-order-send").click();
    await expect(page.locator(".ma-stop-why")).toBeVisible();
    await same(page, "1440-order", false);
    await page.locator('.ma-mode-b[data-mode="LIVE"]').click();
    await expect(page.locator(".ma-ready")).toBeVisible();
    await same(page, "1440-ready", false);
  });

  test("390 × 844 · 한 열", async ({ page }) => {
    await setup(page);
    await open(page, PHONE);
    await same(page, "390-one", false);
  });
});

// ── 판 배치 ─────────────────────────────────────────────────────────────────
// TABS: 탭 보기가 서는 흔한 창(문턱 1280 × 800 — 분봉과 같은 값 · 계획 §10.1) · HUGE: 1920 × 1080 · NARROW: 그 밑(쌓기)

const TABS = WIDE;
const NARROW = { width: 1200, height: 900 };
const MAIN_PAD = 40;                                   // 본문(.terminal-main) 패딩 — 붙는 띠의 top · 작업 공간 높이가 기대는 값

/** 본문을 맨 위 · 끝까지 굴린다(페이지는 .terminal-main 안에서 구른다). */
const scrollMain = (page: Page, to: "top" | "end") =>
  page.locator(".terminal-main").evaluate((el, w) => { el.scrollTop = w === "top" ? 0 : el.scrollHeight; }, to);

test("판 배치를 끈 넓은 창에는 '배치' 단추가 머리 오른쪽에 하나(계좌가 둘이면 고르기 다음) · 좁은 창에는 없다 · 끈 화면에 판 배치 요소 없음", async ({ page }) => {
  test.skip(WRITE, "골든을 뜨는 돌림");
  await setup(page, { accounts: [acc("ba_1", "내 모의 계좌"), acc("ba_2", "두 번째 계좌")] });
  await open(page, TABS);
  const act = page.locator(".ma > .tx-head .tx-head-act");
  await expect(act.locator(".ws-open")).toHaveCount(1);
  await expect(page.locator(".ws-open")).toHaveCount(1);
  expect(await act.evaluate((el) => Array.from(el.children).map((c) => c.className.split(" ").find((k) => k === "ma-acct-l" || k === "ws-open")))).toEqual(["ma-acct-l", "ws-open"]);
  await expect(page.locator(".ws-open")).toHaveText("배치");
  await expect(page.locator(".ws-open")).toHaveAttribute("aria-haspopup", "menu");
  await expect(page.locator(".ws-open")).toHaveAttribute("id", "ws-open-account");
  // 단추는 고르기 칸과 바닥을 맞춘다(머리 칸의 위에 뜨지 않는다)
  const pick = (await page.locator(".ma-acct").boundingBox())!;
  const btn = (await page.locator(".ws-open").boundingBox())!;
  expect(Math.abs((pick.y + pick.height) - (btn.y + btn.height)), "'배치' 단추 바닥 ↔ 고르기 바닥").toBeLessThanOrEqual(1);
  await expect(page.locator(".ws, .ws-grid, .ws-panel, .ws-head, .ws-bar, .ma-stick, .ma-wsf")).toHaveCount(0);
  await expect(page.locator(".ma")).not.toHaveAttribute("data-ws", /.*/);
  await page.setViewportSize(NARROW);
  await expect(page.locator(".ws-open")).toHaveCount(0);
  await page.setViewportSize({ width: 1440, height: 760 });                // 세로가 문턱(800) 밑이어도 없다
  await expect(page.locator(".ws-open")).toHaveCount(0);
});

test("계좌가 없으면 판 배치를 켜 두었어도 판을 세우지 않는다 · '배치' 단추도 없다", async ({ page }) => {
  test.skip(WRITE, "골든을 뜨는 돌림");
  await setup(page, { accounts: [] });
  await page.addInitScript(() => { try { localStorage.setItem("ws.account.on", "1"); } catch { /* */ } });
  await page.setViewportSize(TABS);
  await page.goto("/my-account", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ma-empty")).toBeVisible();
  await expect(page.locator(".ma")).not.toHaveAttribute("data-ws", /.*/);
  await expect(page.locator(".ws, .ws-open, .ma-stick")).toHaveCount(0);
});

test("가장 좁은 탭 보기(1280 × 800)에서도 세 열이 들어간다 — 끈 화면의 '배치' 메뉴가 이름 붙인 세 열을 막지 않고 고르면 합쳐 보이지 않는다(판 최소 폭 · 계획 §10.2a)", async ({ page }) => {
  test.skip(WRITE, "골든을 뜨는 돌림");
  await setup(page);
  // 가장 넓은 세 열 — 규칙 가동(304) | 잔고(144) | 주문 제출(112) · 최근 주문은 첫째 열의 탭
  const three = { v: 1, screen: "account", cols: [
    { w: null, rows: [{ tabs: ["arming", "orders"], active: "arming" }] },
    { w: 400, rows: [{ tabs: ["balance"], active: "balance" }] },
    { w: 520, rows: [{ tabs: ["order"], active: "order" }] }], closed: [] };
  await page.addInitScript((lay) => {
    try { localStorage.setItem("ws.account.saved", JSON.stringify({ v: 1, screen: "account", items: [{ name: "세 열 시험", layout: lay }] })); } catch { /* */ }
  }, three);
  await open(page, { width: 1280, height: 800 });
  await page.locator(".ws-open").click();
  const it = page.locator(".ws-menu").getByRole("menuitem", { name: /세 열 시험/ });
  await expect(it).not.toHaveAttribute("aria-disabled", "true");
  await it.click();
  await expect(page.locator(".ma")).toHaveAttribute("data-ws", "tabs");
  await expect(page.locator(".ws-head")).toHaveCount(3);
  await expect(page.locator(".ws-note")).toHaveCount(0);                 // '창이 좁아 … 합쳐 보입니다' 없음
  await killInView(page, "1280 × 800 세 열");
});

test.describe("판 배치를 켠 내 계좌", () => {
  test.skip(WRITE, "골든을 뜨는 돌림");

  test("켜기: '주문' 처음 배치 — 판 넷 · 그리드 없음 · 문장 띠 · 경로는 판 밖 위 · 주문 제출은 오른쪽 열 · 그 판 메뉴에는 '닫기' 없음 ↔ 다른 판 셋은 있음 · 쓰기 0", async ({ page }) => {
    const { sent } = await setup(page);
    await open(page, TABS);
    await wsOn(page);
    await expect(page.locator(".ma > .ma-grid")).toHaveCount(0);
    await expect(page.locator(".ws-panel")).toHaveCount(4);
    expect(await page.locator(".ws-tab").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.tab))).toEqual(["orders", "balance", "arming", "order"]);
    expect(await panel(page, "order").getAttribute("data-area")).toBe("1:0");
    // 띠는 판 밖 · 작업 공간 위 · 읽는 순서도 띠 → 판
    for (const sel of [".ma-kill-open", ".ma-path", ".tx-answer"]) expect(await page.locator(sel).evaluate((el) => !!el.closest(".ws")), sel).toBe(false);
    const ws = (await page.locator(".ws").boundingBox())!;
    expect((await page.locator(".ma-path").boundingBox())!.y).toBeLessThan(ws.y);
    expect(await page.evaluate(() => {
      const a = document.querySelector(".ma .tx-answer")!;
      const p = document.querySelector(".ma .ma-path")!;
      const w = document.querySelector(".ma .ws")!;
      return !!(a.compareDocumentPosition(p) & Node.DOCUMENT_POSITION_FOLLOWING) && !!(p.compareDocumentPosition(w) & Node.DOCUMENT_POSITION_FOLLOWING);
    })).toBe(true);
    // 판 메뉴 — 주문 제출 판에는 닫기가 없다 ↔ 다른 셋은 있다
    await head(page, "1:0").locator(".ws-menu-open").click();
    await expect(page.locator(".ws-menu").getByRole("menuitem", { name: "닫기" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    for (const id of ["orders", "balance", "arming"]) {
      await tab(page, id).click();
      await head(page, "0:0").locator(".ws-menu-open").click();
      await expect(page.locator(".ws-menu").getByRole("menuitem", { name: "닫기" }), id).toHaveCount(1);
      await page.keyboard.press("Escape");
    }
    expect(writes(sent)).toEqual([]);
  });

  for (const vp of [TABS, HUGE]) {
    test(`붙은 문장 띠(${vp.width} × ${vp.height}): 끝까지 굴리면 띠는 맨 위에 붙고 작업 공간은 띠 바로 아래부터 본문 바닥까지 · 본문 폭을 다 쓴다 · 맨 위에서는 경로가 판 위에 보인다`, async ({ page }) => {
      await setup(page);
      await open(page, vp);
      await wsOn(page);
      const main = (await page.locator(".terminal-main").boundingBox())!;
      await scrollMain(page, "top");
      await expect(page.locator(".ma-path")).toBeInViewport();
      expect(await page.locator(".ma-stick").evaluate((el) => getComputedStyle(el).position)).toBe("sticky");
      await scrollMain(page, "end");
      const stick = (await page.locator(".ma-stick").boundingBox())!;
      const ws = (await page.locator(".ws").boundingBox())!;
      expect(Math.abs(stick.y - main.y), "띠가 본문 맨 위에 붙지 않았다").toBeLessThanOrEqual(1);
      expect(Math.abs(ws.y - (stick.y + stick.height)), `작업 공간 위 ${ws.y} ↔ 띠 아래 ${stick.y + stick.height}`).toBeLessThanOrEqual(1);
      expect(Math.abs((ws.y + ws.height) - (main.y + main.height - MAIN_PAD)), "작업 공간 바닥 ↔ 본문 바닥 − 패딩").toBeLessThanOrEqual(1);
      // 탭 보기에서는 기본 배치의 폭 제한(1080 — 골든의 상자가 건다)을 풀어 판이 본문 폭을 다 쓴다(넓은 모니터의 쓰임)
      const inner = await page.locator(".terminal-main").evaluate((el, pad) => el.clientWidth - 2 * pad, MAIN_PAD);
      expect(Math.abs(ws.width - inner), `작업 공간 폭 ${ws.width} ↔ 본문 안쪽 폭 ${inner}`).toBeLessThanOrEqual(1);
      expect(ws.width).toBeGreaterThan(1080);
      // 띠 안의 문장 · 비상 정지 단추 · 칩이 창 안
      for (const sel of [".ma-stick .tx-answer-s", ".ma-kill-open", ".ma-stick .tx-chips"]) await expect(page.locator(sel), sel).toBeInViewport({ ratio: 1 });
      // 경로는 굴러 올라가 붙은 띠 밑으로 들어갔다(늘 보이지 않는다 — 계획 §10.1): 띠 아래로 나온 부분이 없고 띠는 불투명한 바탕이다
      const path = (await page.locator(".ma-path").boundingBox())!;
      expect(path.y + path.height, "경로가 띠 아래로 보인다").toBeLessThanOrEqual(stick.y + stick.height + 1);
      expect(await page.locator(".ma-stick").evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
    });
  }

  test("1440 × 900 에서 끝까지 굴리면 주문 제출 판 안에 '주문 확인' 단추까지 구르지 않고 보인다", async ({ page }) => {
    await setup(page);
    await open(page, TABS);
    await wsOn(page);
    await scrollMain(page, "end");
    const p = (await panel(page, "order").boundingBox())!;
    const c = (await page.locator(".ma-order-check").boundingBox())!;
    expect(c.y + c.height, `'주문 확인' 바닥 ${c.y + c.height} ↔ 판 바닥 ${p.y + p.height}`).toBeLessThanOrEqual(p.y + p.height);
    expect(await panel(page, "order").evaluate((el) => el.scrollTop)).toBe(0);
  });

  test("가장 작은 탭 보기 창(1280 × 800): 붙은 띠는 한 줄(비상 정지 단추가 문장과 같은 줄) · 주문 제출 판은 판 안에서 굴러 '주문 확인'에 닿는다", async ({ page }) => {
    await setup(page);
    await open(page, { width: 1280, height: 800 });
    await wsOn(page);
    await scrollMain(page, "end");
    const s = (await page.locator(".ma-stick .tx-answer-s").boundingBox())!;
    const k = (await page.locator(".ma-kill-open").boundingBox())!;
    expect(k.y < s.y + s.height && k.y + k.height > s.y, `비상 정지 단추(${k.y} ~ ${k.y + k.height})가 문장(${s.y} ~ ${s.y + s.height})과 같은 줄에 없다`).toBe(true);
    // 잰 값(계획 §10.2a): 이 창에서는 주문 제출 판이 판 안에서 구른다 — 잘리지 않고 판을 굴려 '주문 확인'에 닿는다(1440 × 900 이상은 굴리지 않는다 — 위 시험)
    await page.locator(".ma-order-check").scrollIntoViewIfNeeded();
    const pb = (await panel(page, "order").boundingBox())!;
    const c = (await page.locator(".ma-order-check").boundingBox())!;
    expect(c.y, "'주문 확인'이 판 위로 벗어남").toBeGreaterThanOrEqual(pb.y - 1);
    expect(c.y + c.height, "'주문 확인'이 판 아래로 벗어남").toBeLessThanOrEqual(pb.y + pb.height + 1);
    await expect(page.locator(".ma-order-check")).toBeInViewport({ ratio: 1 });
    await expect(page.locator(".ma-kill-open")).toBeInViewport({ ratio: 1 });
  });

  test("붙은 띠의 높이가 바뀌면 작업 공간이 따라 맞는다 — 응답 전 '상태 확인 중' → 다 온 뒤(긴 계좌 이름 · 1280 × 800) → 넓힌 창(1440 × 900)", async ({ page }) => {
    // 판 배치를 켠 채 새로 여는 흔한 길: 모드 · 비상 정지 응답 전 문장은 짧고(띠가 낮다) 다 오면 길어진다 · 창 폭이 문장의 줄 수를 바꾼다(잰 값 134 → 163 → 134 · 계획 §10.2a)
    await setup(page, { accounts: [acc("ba_1", "장기 보유 종목 연습용으로 따로 만든 두 번째 모의투자 계좌")], slow: 2500 });
    await page.addInitScript(() => { try { localStorage.setItem("ws.account.on", "1"); } catch { /* */ } });
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/my-account", { waitUntil: "domcontentloaded" });
    await expect(page.locator(".ma-stick .tx-answer-s")).toContainText("상태 확인 중");
    const early = (await page.locator(".ma-stick").boundingBox())!.height;
    const fits = async (why: string): Promise<number> => {
      let h = 0;
      await expect(async () => {
        await scrollMain(page, "end");
        const main = (await page.locator(".terminal-main").boundingBox())!;
        const stick = (await page.locator(".ma-stick").boundingBox())!;
        const ws = (await page.locator(".ws").boundingBox())!;
        expect(Math.abs(ws.y - (stick.y + stick.height)), `${why} — 작업 공간 위 ${ws.y} ↔ 띠 아래 ${stick.y + stick.height}`).toBeLessThanOrEqual(1);
        expect(Math.abs((ws.y + ws.height) - (main.y + main.height - MAIN_PAD)), `${why} — 작업 공간 바닥 ↔ 본문 바닥 − 패딩`).toBeLessThanOrEqual(1);
        h = stick.height;
      }).toPass({ timeout: 5_000 });
      return h;
    };
    await expect(page.locator(".ma-stick .tx-answer-s")).toContainText("기록 전용");
    await expect(page.locator(".ma-st")).toHaveCount(4);
    const late = await fits("응답이 다 온 뒤");
    expect(Math.abs(late - early), `띠 높이가 그대로다(${early} → ${late}) — 이 시험이 공허하다`).toBeGreaterThan(8);
    await page.setViewportSize(TABS);
    await expect(page.locator(".ma")).toHaveAttribute("data-ws", "tabs");
    const wide = await fits("1440 × 900 으로 넓힌 뒤");
    expect(Math.abs(wide - late), `넓혀도 띠 높이가 그대로다(${late} → ${wide}) — 이 시험이 공허하다`).toBeGreaterThan(8);
  });

  test("★주문 안전 · 상태 보존★: 입력 · 확인 줄을 둔 채 옮기고 · 닫고 · 다시 열고 · 크게 · 쌓기를 오가도 계좌로 가는 쓰기 0 · 주문 폼 · 목록 노드와 입력 · 확인 줄 · 거르기 그대로", async ({ page }) => {
    const { sent } = await setup(page);
    await open(page, HUGE);
    await wsOn(page);
    await fillOrder(page);
    await page.locator(".ma-order-check").click();
    await expect(page.locator(".ma-order-confirm")).toContainText("삼성전자(005930) 10주를 지정가 71,000원에 매수합니다.");
    await page.locator('.ma-ord-filter .ma-chip-b[data-f="stopped"]').click();
    await page.locator("form.ma-order").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 1; });
    await page.locator(".ma-orders").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 2; });
    // 옮기기(새 열) · 닫기 · 다시 열기 · 이 칸만 크게 · 쌓기 오가기 · 처음 배치 '관제'
    await tab(page, "balance").click();
    await panelMenu(page, "0:0", "새 열(오른쪽 끝)");
    await expect(page.locator(".ws-head")).toHaveCount(3);
    await panelMenu(page, "2:0", "닫기");
    await expect(page.locator(".ws-head")).toHaveCount(2);
    await page.locator(".ws-open").click();
    await item(page, "‘잔고’ 다시 열기").click();
    await panelMenu(page, "1:0", "이 칸만 크게", true);
    await page.keyboard.press("Escape");
    await page.setViewportSize(NARROW);
    await expect(page.locator(".ma")).toHaveAttribute("data-ws", "stack");
    await page.setViewportSize(HUGE);
    await expect(page.locator(".ma")).toHaveAttribute("data-ws", "tabs");
    await page.locator(".ws-open").click();
    await item(page, "관제").click();
    // 확인
    expect(writes(sent), JSON.stringify(writes(sent))).toEqual([]);
    expect(await page.locator("form.ma-order").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(1);
    expect(await page.locator(".ma-orders").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(2);
    await expect(page.locator("form.ma-order")).toHaveCount(1);
    await tab(page, "order").click();
    await expect(page.locator(".ma-order-confirm")).toContainText("삼성전자(005930) 10주를 지정가 71,000원에 매수합니다.");
    await expect(page.locator('input[name="ma-qty"]')).toHaveValue("10");
    await expect(page.locator('.ma-ord-filter .ma-chip-b[data-f="stopped"]')).toHaveAttribute("aria-pressed", "true");
    // 짝: 사람이 '전송'을 누르면 그때만 한 번 간다
    await page.locator(".ma-order-send").click();
    await expect(page.locator(".ma-order-result")).toBeVisible();
    expect(writes(sent).map((s) => `${s.method} ${s.path}`)).toEqual(["POST /ba_1/orders"]);
  });

  test("비상 정지 단추는 판 밖이고 탭 보기에서 맨 위 · 끝까지 굴려도 창 안 — 처음 배치 둘 · 옮긴 뒤 · 이 칸만 크게 · 닫은 뒤 · 끝에서 누르면 확인 시트(쓰기 0)", async ({ page }) => {
    const { sent } = await setup(page);
    await open(page, TABS);
    await wsOn(page);
    await killInView(page, "처음 배치 '주문'");
    await page.locator(".ws-open").click();
    await item(page, "관제").click();
    await killInView(page, "처음 배치 '관제'");
    await panelMenu(page, "1:0", "새 열(오른쪽 끝)");
    await killInView(page, "옮긴 뒤");
    await panelMenu(page, "0:0", "이 칸만 크게", true);
    await killInView(page, "이 칸만 크게");
    await page.keyboard.press("Escape");
    await panelMenu(page, "0:0", "닫기");
    await killInView(page, "닫은 뒤");
    await scrollMain(page, "end");
    await page.locator(".ma-kill-open").click();
    await expect(page.locator('[data-sheet="kill"]')).toBeVisible();
    await page.keyboard.press("Escape");
    expect(writes(sent)).toEqual([]);
  });

  test("처음 배치 둘의 저장 꼴 — '주문'(최근 주문 · 잔고 · 규칙 가동 | 주문 제출) · '관제'(규칙 가동 | 위 최근 주문 · 아래 주문 제출 · 잔고)", async ({ page }) => {
    await setup(page);
    await open(page, TABS);
    await wsOn(page);
    await tab(page, "arming").click();                                      // 고른 탭이 남는다 — 꼴이 저장된다
    let lay = await stored(page) as { cols: { rows: { tabs: string[] }[] }[] };
    expect(lay.cols.map((c) => c.rows.map((r) => r.tabs))).toEqual([[["orders", "balance", "arming"]], [["order"]]]);
    await page.locator(".ws-open").click();
    await item(page, "관제").click();
    lay = await stored(page) as { cols: { rows: { tabs: string[] }[] }[] };
    expect(lay.cols.map((c) => c.rows.map((r) => r.tabs))).toEqual([[["arming"]], [["orders"], ["order", "balance"]]]);
  });

  test("주문을 내면 멈춘 역은 판 위의 주문 전송 경로에 선다 — 주문 판 결과 줄의 '위'가 맞다", async ({ page }) => {
    await setup(page);
    await open(page, TABS);
    await wsOn(page);
    await fillOrder(page);
    await page.locator(".ma-order-check").click();
    await page.locator(".ma-order-send").click();
    await expect(page.locator(".ma-order-result")).toContainText("위 ‘주문 전송 경로’");
    await expect(page.locator(".ma-path")).toHaveAttribute("data-stop", "mode");
    await expect(page.locator(".ma-stop-why")).toHaveCount(1);
    await scrollMain(page, "top");
    const path = (await page.locator(".ma-path").boundingBox())!;
    const ord = (await panel(page, "order").boundingBox())!;
    expect(path.y + path.height).toBeLessThanOrEqual(ord.y);
  });

  test("판 이름 = 판 안 첫 절 제목 하나(탭 · 쌓기) — 주문 제출 · 최근 주문 · 잔고 · 규칙 가동", async ({ page }) => {
    await setup(page);
    await open(page, TABS);
    await wsOn(page);
    for (const id of Object.keys(NAMES)) {
      await tab(page, id).click();
      await expect(panel(page, id).getByRole("heading", { name: NAMES[id], exact: true }), id).toHaveCount(1);
      await expect(panel(page, id).locator(":scope > .ws-panel-name + .tx-sec > .tx-sec-head .tx-sec-t"), id).toHaveText(NAMES[id]);
      await expect(tab(page, id), id).toHaveText(NAMES[id]);
    }
    await page.setViewportSize(NARROW);
    await expect(page.locator(".ma")).toHaveAttribute("data-ws", "stack");
    for (const id of Object.keys(NAMES)) {
      await expect(panel(page, id).getByRole("heading", { name: NAMES[id], exact: true }), id).toHaveCount(1);
      await expect(panel(page, id).locator(":scope > .ws-panel-name"), id).toBeVisible();
    }
  });

  test("저장: 열쇠는 ws.account* — 분봉의 ws.intraday* 와 섞이지 않는다 · 새로 고쳐도 그 배치", async ({ page }) => {
    await setup(page);
    await page.addInitScript(() => {
      if (sessionStorage.getItem("__seeded")) return;
      sessionStorage.setItem("__seeded", "1");
      localStorage.setItem("ws.intraday.on", "1");
      localStorage.setItem("ws.intraday", JSON.stringify({ v: 1, screen: "intraday", cols: [{ w: null, rows: [{ tabs: ["setup", "result", "bars", "verdict", "daytype", "regime"], active: "setup" }] }], closed: [] }));
    });
    await open(page, TABS);
    await expect(page.locator(".ma")).not.toHaveAttribute("data-ws", /.*/);     // 분봉의 켬은 내 계좌를 켜지 않는다
    await wsOn(page);
    expect(await page.evaluate((k) => localStorage.getItem(k), K.on)).toBe("1");
    await tab(page, "balance").click();
    await panelMenu(page, "0:0", "새 열(오른쪽 끝)");
    const saved = await stored(page);
    expect((saved as { screen: string }).screen).toBe("account");
    expect(JSON.parse((await page.evaluate(() => localStorage.getItem("ws.intraday")))!).screen).toBe("intraday");
    await page.reload({ waitUntil: "domcontentloaded" });
    // 판 배치로 다시 선다 — 탭에 가려진 판의 내용은 보이지 않으므로 기본 배치의 settle 대신 판 수와 경로 역으로 기다린다
    await expect(page.locator(".ws-panel")).toHaveCount(4);
    await expect(page.locator(".ma-st")).toHaveCount(4);
    await expect(page.locator(".ws-head")).toHaveCount(3);
    expect(await stored(page)).toEqual(saved);
  });

  test("계좌 바꾸기: 배치는 그대로 · 절은 새 계좌로 다시 선다(옛 계좌 숫자 없음)", async ({ page }) => {
    await setup(page, { accounts: [acc("ba_1", "내 모의 계좌"), acc("ba_2", "두 번째 계좌")] });
    await open(page, TABS);
    await wsOn(page);
    await tab(page, "balance").click();
    await panelMenu(page, "0:0", "새 열(오른쪽 끝)");
    const saved = await stored(page);
    await expect(page.locator(".ma .tx-answer")).toContainText("102,000,000");
    await page.locator(".ma-acct").selectOption("ba_2");
    await expect(page).toHaveURL(/account=ba_2/);
    await expect(page.locator(".ma .tx-answer")).toContainText("55,500,000");
    await expect(page.locator(".ma .tx-answer")).not.toContainText("102,000,000");
    await expect(page.locator(".ws-head")).toHaveCount(3);
    expect(await stored(page)).toEqual(saved);
  });

  test("좁은 창: 같은 상자 안 한 열로 쌓기 — 문장 띠는 붙지 않고 판 밖 맨 위 · 판 넷의 이름 · 노드와 입력 보존 ↔ 넓히면 탭", async ({ page }) => {
    await setup(page);
    await open(page, TABS);
    await wsOn(page);
    await page.locator('input[name="ma-qty"]').fill("7");
    await page.locator("form.ma-order").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 9; });
    await page.locator(".ma-path").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 8; });
    await page.setViewportSize(NARROW);
    await expect(page.locator(".ma")).toHaveAttribute("data-ws", "stack");
    await expect(page.locator(".ws-head, .ws-col-slot, .ws-row-bar")).toHaveCount(0);
    await expect(page.locator(".ws-panel-name")).toHaveText(["최근 주문", "잔고", "규칙 가동", "주문 제출"]);
    expect(await page.locator(".ma-stick").evaluate((el) => getComputedStyle(el).position)).not.toBe("sticky");
    const ws = (await page.locator(".ws").boundingBox())!;
    expect((await page.locator(".ma-kill-open").boundingBox())!.y).toBeLessThan(ws.y);
    expect(await page.locator("form.ma-order").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(9);
    expect(await page.locator(".ma-path").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(8);
    await expect(page.locator('input[name="ma-qty"]')).toHaveValue("7");
    await page.setViewportSize(TABS);
    await expect(page.locator(".ma")).toHaveAttribute("data-ws", "tabs");
    expect(await page.locator("form.ma-order").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(9);
    expect(await page.locator(".ma-path").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(8);
  });

  test("기본 배치로 끄면 지금 화면(그리드) · 쓰기 0 · 다시 켜면 마지막 배치", async ({ page }) => {
    const { sent } = await setup(page);
    await open(page, TABS);
    await wsOn(page);
    await tab(page, "balance").click();
    await panelMenu(page, "0:0", "새 열(오른쪽 끝)");
    const saved = await stored(page);
    await page.locator(".ws-open").click();
    await radio(page, "기본 배치").click();
    await expect(page.locator(".ma")).not.toHaveAttribute("data-ws", /.*/);
    await expect(page.locator(".ma > .ma-grid")).toHaveCount(1);
    await expect(page.locator(".ws, .ma-stick, .ma-wsf")).toHaveCount(0);
    await expect(page.locator(".ma > .tx-head .ws-open")).toBeFocused();
    await wsOn(page);
    await expect(page.locator(".ws-head")).toHaveCount(3);
    expect(await stored(page)).toEqual(saved);
    expect(writes(sent)).toEqual([]);
  });

  test("끈 화면의 '배치 관리'에서 가져오기 — 틀린 파일은 끈 화면 그대로 · 사유 ↔ 맞는 파일은 판 배치가 켜지고 시트와 결과 문장이 남는다 · 쓰기 0", async ({ page }) => {
    const { sent } = await setup(page);
    await open(page, TABS);
    await page.locator(".ws-open").click();
    await item(page, "배치 관리").click();
    const sheet = page.locator('.tx-sheet[data-sheet="ws"]');
    await expect(sheet).toBeVisible();
    const put = (name: string, body: string) => sheet.locator(".ws-import-file").setInputFiles({ name, mimeType: "application/json", buffer: Buffer.from(body) });
    const monitor = { v: 1, screen: "account", closed: [], cols: [
      { w: null, rows: [{ tabs: ["arming"], active: "arming" }] },
      { w: 520, rows: [{ tabs: ["orders"], active: "orders" }, { tabs: ["order", "balance"], active: "order", h: 0.5 }] }] };
    const file = { kind: "project-alpha.workspace", v: 1, screen: "account", saved: [], current: monitor };
    await put("intraday.json", JSON.stringify({ ...file, screen: "intraday", current: { ...monitor, screen: "intraday" } }));
    await expect(sheet.locator(".ws-sheet-reasons")).toContainText("다른 화면(‘intraday’)의 배치 파일입니다.");
    await expect(page.locator(".ma")).not.toHaveAttribute("data-ws", /.*/);
    await expect(page.locator(".ma > .ma-grid")).toHaveCount(1);
    await put("account.json", JSON.stringify(file));
    await expect(page.locator(".ma")).toHaveAttribute("data-ws", "tabs");
    await expect(sheet).toBeVisible();
    await expect(sheet.locator(".ws-sheet-msg")).toHaveText("가져왔습니다. 지금 배치와 이름 붙인 배치 0개를 적용했습니다.");
    await expect(sheet.locator(".ws-sheet-msg")).toHaveAttribute("data-tone", "ok");
    expect(await stored(page)).toEqual(monitor);
    await sheet.locator(".tx-sheet-x").click();
    await expect(page.locator(".ws-head")).toHaveCount(3);
    expect(writes(sent)).toEqual([]);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`${scheme} — 판 배치의 대비 AA · 문체 · 390 × 844 넘침 0`, async ({ page }) => {
      await setup(page);
      await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, scheme);
      await open(page, TABS);
      await wsOn(page);
      const a = await page.evaluate<AuditResult>(contrastAudit(".ma"));
      expect(a.checked).toBeGreaterThan(30);
      expect(a.low, `${scheme} 대비`).toEqual([]);
      if (scheme === "dark") expect(a.bright, "다크인데 밝은 바탕").toEqual([]);
      const v = await page.evaluate<VoiceResult>(voiceAudit(".ma"));
      expect(v.haeyo, "해요체").toEqual([]);
      expect(v.dash, "줄표").toEqual([]);
      await page.setViewportSize(PHONE);
      await expect(page.locator(".ma")).toHaveAttribute("data-ws", "stack");
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, "390 가로 넘침").toBeLessThanOrEqual(0);
      const sticking = await page.evaluate<string[]>(cardsOverflow(".ma .tx-sec, .ma .tx-answer"));
      expect(sticking).toEqual([]);
    });
  }
});
