import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════════════════════════
// 캔버스 '분봉 결과 조회' 판의 '시장 국면별로 나눠 보기'(K2c · 2026-11-17 · 구현 계획 §7.3)
// 화면(백테스트 › 분봉 규칙)의 K2a · K2b 와 ★같은 부품 · 같은 문★을 결과 노드의 판에 싣는다 — 그리기 계약 자체는 화면의 두 스펙이 건다
// (`intraday-regime-split.spec.ts` · `intraday-regime-day-types.spec.ts`). 여기서 거는 것은 캔버스에 실은 길이다:
//  · 그래프 실행 · 판 열기는 두 문을 부르지 않는다(캔버스 규칙 6 — 계산은 쓰지 않는다 · 시작은 단추) · 국면 수 · 모형은 비어서 시작
//  · 물을 때는 ★그 노드의 시행 열쇠★ · 폼의 지수 · 국면 수 · 고른 모형 · 답 = 서버(실제 서버 · 판정 날 넷 × 두 종목 = 표본 8 손 계산)
//  · 다른 결과 노드를 고르면 앞의 답과 고른 칸을 지운다 · 열쇠가 없는 결과면 묻지 않는다
//  · 거절은 재시도 없음 · 실패는 재시도 · 로그인 만료의 링크는 캔버스(`/allocation`)로 돌아온다
//  · 판은 넘치지 않는다(1280px 화면의 344px · 가장 좁은 300px) — 표는 키보드로 닿는 상자 안에서만 옆으로 넘는다 ·
//    좁은 판의 모형 칸은 이름이 잘릴 수 있어 고른 이름 전체를 칸 아래 줄로 다시 적는다(줄을 바꿔 판 안에 든다) · 라이트/다크 AA · 문체
// 분봉: `seed_day_types.py`(학습 — 005380 · 035420 · 2026-05-04 ~ 05-19 · 5분 · 유형 넷) + `seed_day_type_rules.py`(판정 날 넷 07-01 ~ 07-06).
// ════════════════════════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const TRAIN = { tickers: ["005380", "035420"], from: "2026-05-04", to: "2026-05-19", minutes: 5, k: 4 };
/** 판정 날 넷 × 두 종목 — 규칙은 무엇이든 된다(나눔은 규칙이 아니라 시행의 종목 · 기간 · 일별 값을 읽는다). */
const JUDGE = { tickers: ["005380", "035420"], start_date: "2026-07-01", end_date: "2026-07-06", rule: "opening_range_breakout",
  opening_range_breakout__minutes: 1, amount: 1_000_000, commission_bp: 1.5, slippage_ticks: 1, unknown_market: "KOSPI", unknown_instrument: "stock" };
/** 다른 시행 하나 — 노드를 바꾸면 답이 바뀌는지 보려고(종목 하나만). */
const OTHER = { ...JUDGE, tickers: ["005380"] };
const IS_RS = (u: string) => /\/intraday\/trials\/[^/]+\/regime-split$/.test(new URL(u).pathname);
const IS_RDT = (u: string) => /\/intraday\/trials\/[^/]+\/regime-day-types$/.test(new URL(u).pathname);
const SIDE = ".pg-side .pg-itd-load";
const n = (v: number) => v.toLocaleString("ko-KR");

test.beforeAll(() => {
  for (const script of ["seed_day_types.py", "seed_day_type_rules.py"]) {
    execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", script)],
      { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
  }
});

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

/** 학습 문으로 모형 하나를 짓는다(같은 입력은 같은 열쇠). */
async function trainModel(page: Page, token: string): Promise<string> {
  const r = await page.request.post(`${API}/intraday/day-types`, { data: TRAIN, headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()).model.key as string;
}

/** 캔버스의 단추와 같은 두 문(계산 → 저장)으로 실행 하나를 남기고 그 시행 열쇠를 돌려준다 — 화면을 거치지 않는 준비. */
async function keptTrial(page: Page, token: string, params: object): Promise<string> {
  const headers = { Authorization: `Bearer ${token}` };
  const graph = { format: "project-alpha.portfolio-graph", version: 1, edges: [], nodes: [{ id: "is", type: "intraday_setup", params }] };
  const ran = await page.request.post(`${API}/allocation/graph/run`, { data: graph, headers, timeout: 120_000 });
  expect(ran.ok(), await ran.text()).toBe(true);
  const hash = (await ran.json()).nodes.is.view_hash as string;
  const saved = await page.request.post(`${API}/allocation/graph/save`, { data: { graph, node_id: "is", preview_hash: hash }, headers, timeout: 120_000 });
  const body = await saved.json();
  expect(body.ok, body.message).toBe(true);
  return body.saved_id as string;
}

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const load = (id: string, key: string, x = 0) => ({ id, type: "intraday_load", position: { x, y: 0 }, params: { trial_key: key } });

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function importDoc(page: Page, nodes: object[]) {
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: { name: "국면 나눔" }, edges: [], nodes };
  await page.locator(".pg-import-input").setInputFiles({ name: "regime.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
}

/** 결과 노드들을 들여와 계산하고(모두 ok 여야 한다) 첫 노드의 자세히 탭을 연다. */
async function openLoads(page: Page, nodes: { id: string }[]) {
  await openCanvas(page);
  await importDoc(page, nodes);
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const ran = await (await resp).json();
  for (const x of nodes) expect(ran.nodes[x.id].status, ran.nodes[x.id].reason).toBe("ok");
  await pick(page, nodes[0].id);
  return ran;
}

async function pick(page: Page, id: string) {
  await node(page, id).click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await expect(page.locator(SIDE)).toBeVisible();
}

async function split(page: Page, k: string, index?: string) {
  if (index) await page.locator(`${SIDE} .itd-rs-index`).selectOption(index);
  await page.locator(`${SIDE} .itd-rs-k`).selectOption(k);
  const sent = page.waitForRequest((r) => IS_RS(r.url()));
  const got = page.waitForResponse((r) => IS_RS(r.url()), { timeout: 60_000 });
  await page.locator(`${SIDE} .itd-rs-run`).click();
  const url = new URL((await sent).url());
  const res = await got;
  return { url, status: res.status(), js: await res.json() };
}

/** 하루 유형 비율을 묻는다 — 국면 수는 부르는 쪽이 먼저 고른다(같은 값을 다시 고르면 Playwright 가 change 를 내어 위의 국면별 답이 지워진다 · 실제 칸은 같은 값에 이벤트가 없다). */
async function count(page: Page, model: string) {
  await page.locator(`${SIDE} .itd-rdt-model`).selectOption(model);
  const sent = page.waitForRequest((r) => IS_RDT(r.url()));
  const got = page.waitForResponse((r) => IS_RDT(r.url()), { timeout: 60_000 });
  await page.locator(`${SIDE} .itd-rdt-run`).click();
  const url = new URL((await sent).url());
  const res = await got;
  return { url, status: res.status(), js: await res.json() };
}

test("결과 판의 국면 나눔: 계산 · 판 열기는 묻지 않고 국면 수가 비면 단추가 꺼져 있다 — 고르면 그 노드의 시행 열쇠로 한 번 묻고 표 = 서버", async ({ page }) => {
  test.setTimeout(180_000);
  const asked: string[] = [];
  page.on("request", (r) => { if (IS_RS(r.url()) || IS_RDT(r.url())) asked.push(r.url()); });
  const token = await login(page);
  const key = await keptTrial(page, token, JUDGE);
  await openLoads(page, [load("il", key)]);
  const sec = page.locator(`${SIDE} .itd-rs`);
  await expect(sec).toBeVisible();
  // 머리 단계: 판 제목(h2) 아래의 절은 h3 · 하위 절은 h4(짝 — 화면에서는 h2 · h3 · `intraday-regime-day-types.spec.ts`)
  await expect(page.locator(`${SIDE} .pg-itd-rs h3.tx-sec-t`)).toHaveText("시장 국면별로 나눠 보기");
  await expect(page.locator(`${SIDE} .pg-itd-rs h4.tx-sec-t`)).toHaveText("하루 유형 비율");
  await expect(page.locator(`${SIDE} .itd-rs-k`)).toHaveValue("");
  await expect(page.locator(`${SIDE} .itd-rs-run`)).toBeDisabled();
  await expect(page.locator(`${SIDE} .itd-rs-problems`)).toHaveText("국면 수를 고르십시오.");
  await expect(page.locator(`${SIDE} .itd-rdt-model`)).toHaveValue("");
  expect(asked, "그래프 계산 · 판 열기는 나눔 문을 부르지 않는다").toEqual([]);

  // 잰 값(E2E 서버의 합성 지수): 코스피 · 국면 3개면 판정 날 넷이 국면 2 · 3 으로 갈린다(화면 K2b 스펙과 같은 자료)
  const { url, js } = await split(page, "3", "KOSPI");
  expect(url.pathname).toBe(`${API}/intraday/trials/${key}/regime-split`);
  expect(Object.fromEntries(url.searchParams)).toEqual({ index: "KOSPI", k: "3" });
  expect(asked).toHaveLength(1);
  const s = js.split as { states: { state: number; days: number }[]; unknown: { days: number }; total: { days: number } };
  expect(s, "전제 — 나눴다").not.toBeNull();
  expect(s.states.filter((x) => x.days > 0).length, "전제 — 둘 이상의 국면에 날이 있다(공허하지 않다)").toBeGreaterThan(1);
  const res = page.locator(`${SIDE} .itd-rs-result`);
  await expect(res).toHaveAttribute("data-k", "3");
  await expect(res).toHaveAttribute("data-index", "KOSPI");
  await expect(page.locator(`${SIDE} .itd-rs-head`)).toContainText(`${js.from} ~ ${js.to}`);
  for (const st of s.states) {
    await expect(page.locator(`${SIDE} .itd-rs-table tbody tr[data-state="${st.state}"] td`).nth(1)).toHaveText(`${n(st.days)}일`);
  }
  await expect(page.locator(`${SIDE} .itd-rs-table tfoot tr[data-state="total"] > *`).nth(1)).toHaveText(`${n(s.total.days)}일`);
  await expect(page.locator(`${SIDE} .itd-rs-notes li`)).toHaveText(js.notes as string[]);
});

test("결과 판의 하루 유형 비율: 모형이 비면 묻지 않는다 — 고르면 노드의 열쇠 · 지수 · 국면 수 · 모형으로 묻고 합계 열은 손 계산(표본 8 · 유형마다 2 · 25.0%)", async ({ page }) => {
  test.setTimeout(180_000);
  const asked: string[] = [];
  page.on("request", (r) => { if (IS_RDT(r.url())) asked.push(r.url()); });
  const token = await login(page);
  const model = await trainModel(page, token);
  const key = await keptTrial(page, token, JUDGE);
  await openLoads(page, [load("il", key)]);
  await page.locator(`${SIDE} .itd-rs-k`).selectOption("3");
  await expect(page.locator(`${SIDE} .itd-rdt-run`)).toBeDisabled();
  await expect(page.locator(`${SIDE} .itd-rdt-problems li`)).toHaveText(["하루 유형 모형을 고르십시오."]);
  expect(asked).toEqual([]);
  const { url, js } = await count(page, model);
  expect(url.pathname).toBe(`${API}/intraday/trials/${key}/regime-day-types`);
  expect(Object.fromEntries(url.searchParams)).toEqual({ index: "KOSPI", k: "3", model });
  expect(asked, "모형을 고른 것만으로는 묻지 않는다 — 단추 한 번에 한 번").toHaveLength(1);
  const t = js.table as { total: { samples: number; classified: number; in_sample: number; types: { n: number; share: number | null }[] } };
  expect(t, "전제 — 셌다").not.toBeNull();
  expect([t.total.samples, t.total.classified, t.total.in_sample]).toEqual([8, 8, 0]);
  for (const ty of [1, 2, 3, 4]) {
    await expect(page.locator(`${SIDE} .itd-rdt-table tbody tr[data-type="${ty}"] > *`).last()).toHaveText("25.0% 2개");
  }
  await expect(page.locator(`${SIDE} .itd-rdt-result`)).toHaveAttribute("data-model", model);
  await expect(page.locator(`${SIDE} .itd-rdt-facts li`)).toHaveText(js.model.facts as string[]);
  // 고른 모형의 이름(열쇠 · 학습 기간 · 유형 수 · 분 수)이 판에 다 보인다 — 판의 칸은 좁아(1280px 화면에서 판 344px · 판은 300px 까지 좁아진다)
  // 칸의 글은 잘릴 수 있으므로 이름 전체를 칸 아래 줄이 보인다(줄을 바꿔 판 안에 든다). 짝: 넓은 화면의 칸에는 이 줄이 없다(`intraday-regime-day-types.spec.ts`).
  const chosen = await page.locator(`${SIDE} .itd-rdt-model`).evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.text ?? "");
  expect(chosen, "전제 — 모형의 이름이 다 적혔다").toContain("유형 4개 · 5분");
  const full = page.locator(`${SIDE} .itd-rdt-model-full`);
  await expect(full).toHaveText(chosen);
  expect(await full.evaluate((e) => e.scrollWidth <= e.clientWidth + 1), "이름 줄이 판 밖으로 넘친다").toBe(true);
});

test("다른 결과 노드를 고르면 앞의 답과 고른 칸을 지운다 — 그 노드의 열쇠로 다시 묻는다", async ({ page }) => {
  test.setTimeout(240_000);
  const token = await login(page);
  const first = await keptTrial(page, token, JUDGE);
  const second = await keptTrial(page, token, OTHER);
  expect(second, "전제 — 두 시행").not.toBe(first);
  await openLoads(page, [load("a", first), load("b", second, 420)]);
  await split(page, "2");
  await expect(page.locator(`${SIDE} .itd-rs-result`)).toBeVisible();
  await pick(page, "b");
  await expect(page.locator(`${SIDE} .itd-rs-result`)).toHaveCount(0);
  await expect(page.locator(`${SIDE} .itd-rs-k`)).toHaveValue("");
  const { url } = await split(page, "2");
  expect(url.pathname).toBe(`${API}/intraday/trials/${second}/regime-split`);
});

test("열쇠가 없는 결과면 묻지 않는다 · 거절은 재시도 없음 · 실패는 재시도 · 로그인 만료는 캔버스로 돌아오는 링크", async ({ page }) => {
  test.setTimeout(180_000);
  const asked: string[] = [];
  page.on("request", (r) => { if (IS_RS(r.url())) asked.push(r.url()); });
  const token = await login(page);
  const key = await keptTrial(page, token, JUDGE);
  // 결과에 열쇠가 없다고 답한 때(대역 — 실제 답에서 열쇠만 걷는다)
  await page.route("**/allocation/graph/run", async (route) => {
    const resp = await route.fetch();
    const body = await resp.json();
    delete body.nodes.il.view.trial_key;
    await route.fulfill({ response: resp, json: body });
  });
  await openLoads(page, [load("il", key)]);
  // 화면 문장은 용어집의 낱말로(시행 · 결과) — 안의 이름(시행 열쇠)을 화면에 쓰지 않는다
  await expect(page.locator(`${SIDE} .itd-rs-no-trial`)).toHaveText("이 결과가 어느 시행의 것인지 적혀 있지 않아 국면별로 나눌 수 없습니다.");
  await expect(page.locator(`${SIDE} .itd-rs-k`)).toHaveCount(0);
  expect(asked).toEqual([]);
  await page.unroute("**/allocation/graph/run");

  await page.locator(".pg-run").click();
  await expect(page.locator(`${SIDE} .itd-rs-k`)).toBeVisible({ timeout: 60_000 });
  const refusal = "심은 거절: 그 시행을 찾지 못했습니다.";
  await page.route((u) => IS_RS(u.toString()), (route) => route.fulfill({ status: 404, json: { detail: { code: "not_found", reason: refusal } } }));
  await page.locator(`${SIDE} .itd-rs-k`).selectOption("2");
  await page.locator(`${SIDE} .itd-rs-run`).click();
  await expect(page.locator(`${SIDE} .itd-rs .tx-notice [data-server]`).first()).toHaveText(refusal);
  await expect(page.locator(`${SIDE} .itd-rs`).getByRole("button", { name: "재시도" })).toHaveCount(0);
  await page.unroute((u) => IS_RS(u.toString()));

  await page.route((u) => IS_RS(u.toString()), (route) => route.fulfill({ status: 401, json: { detail: "로그인이 필요합니다." } }));
  await page.locator(`${SIDE} .itd-rs-k`).selectOption("3");
  await page.locator(`${SIDE} .itd-rs-run`).click();
  await expect(page.locator(`${SIDE} .itd-rs .tx-notice a`).first()).toHaveAttribute("href", "/login?next=%2Fallocation");
  await page.unroute((u) => IS_RS(u.toString()));

  let fail = true;
  await page.route((u) => IS_RS(u.toString()), async (route) => {
    if (fail) { fail = false; await route.fulfill({ status: 500, json: { detail: "서버 오류" } }); } else await route.continue();
  });
  await page.locator(`${SIDE} .itd-rs-k`).selectOption("2");
  await page.locator(`${SIDE} .itd-rs-run`).click();
  const retry = page.locator(`${SIDE} .itd-rs`).getByRole("button", { name: "재시도" });
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(page.locator(`${SIDE} .itd-rs-result`)).toBeVisible({ timeout: 60_000 });
});

test("판이 가장 좁을 때(300px): 모형 이름 줄은 줄을 바꿔 판 안에 들고 판은 넘치지 않는다 — 표만 상자 안에서 넘는다", async ({ page }) => {
  test.setTimeout(180_000);
  // 판의 폭은 사용자가 끌어 바꾸고 이 브라우저에 남는다(300 ~ 600px · `panels.ts`) — 가장 좁은 폭으로 연다
  await page.addInitScript(() => {
    try { localStorage.setItem("alpha_pg_panels", JSON.stringify({ left: true, right: true, rightW: 300 })); } catch { /* */ }
  });
  const token = await login(page);
  const model = await trainModel(page, token);
  const key = await keptTrial(page, token, JUDGE);
  await openLoads(page, [load("il", key)]);
  expect(Math.round((await page.locator(".pg-side").boundingBox())?.width ?? 0), "전제 — 판이 가장 좁은 폭으로 열렸다").toBe(300);
  await split(page, "3", "KOSPI");
  await count(page, model);
  const full = page.locator(`${SIDE} .itd-rdt-model-full`);
  const chosen = await page.locator(`${SIDE} .itd-rdt-model`).evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.text ?? "");
  await expect(full).toHaveText(chosen);
  const box = await full.evaluate((e) => {
    const range = document.createRange();
    range.selectNodeContents(e);
    const tops = new Set([...range.getClientRects()].map((r) => Math.round(r.top)));
    return { lines: tops.size, fits: e.scrollWidth <= e.clientWidth + 1 };
  });
  expect(box.fits, "이름 줄이 판 밖으로 넘친다").toBe(true);
  expect(box.lines, "전제 — 이 폭에서는 이름이 한 줄에 들지 않는다(줄을 바꿔 든 것이다 — 공허하지 않다)").toBeGreaterThan(1);
  // 어절에서 꺾는다(keep-all — 캔버스의 노드 이름과 같은 규칙) — '4개'가 '4 / 개'로 갈라지면 읽기 어렵다(스크린샷 검수에서 찾음)
  const torn = await full.evaluate((e) => {
    const text = e.firstChild;
    if (!(text instanceof Text)) return ["(글 마디가 하나가 아니다)"];
    const out: string[] = [];
    let at = 0;
    for (const word of (text.textContent ?? "").split(" ")) {
      const r = document.createRange();
      r.setStart(text, at);
      r.setEnd(text, at + word.length);
      if (new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size > 1) out.push(word);
      at += word.length + 1;
    }
    return out;
  });
  expect(torn, "어절이 줄 끝에서 쪼개진다").toEqual([]);
  const panel = page.locator(".pg-side .pg-panel");
  expect(await panel.evaluate((e) => e.scrollWidth <= e.clientWidth + 1), "판이 옆으로 넘친다").toBe(true);
  for (const b of [`${SIDE} .itd-rs-scroll`, `${SIDE} .itd-rdt-scroll`]) {
    expect(await page.locator(b).evaluate((e) => e.scrollWidth > e.clientWidth), `${b} — 표는 상자 안에서 옆으로 넘는다`).toBe(true);
  }
});

for (const theme of ["light", "dark"] as const) {
  test(`판(${theme}): 대비 AA · 문체 · 판은 넘치지 않고 표만 키보드로 닿는 상자 안에서 옆으로 넘는다`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    const token = await login(page);
    const model = await trainModel(page, token);
    const key = await keptTrial(page, token, JUDGE);
    await openLoads(page, [load("il", key)]);
    await split(page, "3", "KOSPI");
    await count(page, model);
    for (const scope of [`${SIDE} .itd-rs`]) {
      const a = (await page.evaluate(contrastAudit(scope))) as AuditResult;
      expect(a.checked).toBeGreaterThan(20);
      expect(a.low, theme).toEqual([]);
      const v = (await page.evaluate(voiceAudit(scope))) as VoiceResult;
      expect(v.haeyo).toEqual([]);
      expect(v.dash).toEqual([]);
      expect(v.banned).toEqual([]);
    }
    const panel = page.locator(".pg-side .pg-panel");
    expect(await panel.evaluate((e) => e.scrollWidth <= e.clientWidth + 1), "판이 옆으로 넘친다").toBe(true);
    for (const box of [`${SIDE} .itd-rs-scroll`, `${SIDE} .itd-rdt-scroll`]) {
      const scroll = page.locator(box);
      expect(await scroll.evaluate((e) => e.scrollWidth > e.clientWidth), `${box} — 좁은 판에서는 표가 옆으로 넘는다`).toBe(true);
      await scroll.focus();
      await page.keyboard.press("ArrowRight");
      await expect.poll(() => scroll.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0);
    }
  });
}
