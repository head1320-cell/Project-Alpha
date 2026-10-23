import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * AI3 · 노드·선에게 묻기 — 오른쪽 창 아래에 붙은 묻기 칸(스펙 §AI3 설계, 사용자 결정 2026-10-23)
 *  · 노드나 선을 고르면 칸이 있다(짝: 아무것도 고르지 않으면 없다) · 계산 전·낡음이면 안내 + [여기까지 계산] · 로그아웃이면 로그인 링크, 요청 0
 *  · 보내는 것 = 대상 · 질문 · 직전 문답 하나 · 낡지 않은 결과의 설명·봉인 + 전달 점검 기록·봉인 ★`/run` 그대로★(서버가 범위를 고른다)
 *  · 답: 문장마다 사실 칩(번호 + 이름 · 부분) — 누르면 ★그 자리에서 원문을 펼친다★ + [그 노드로]/[그 선으로]
 *  · 답할 수 없으면 서버 고정 문장 · 연습용 경고는 서버가 붙였을 때만 · 못 보임 사유 · 검사에서 빠진 것과 확인 못 한 것은 수와 사유
 *  · 대상마다 문답이 남는다(다른 노드에 갔다 와도) · 결과가 바뀌면 그 대상의 문답을 지우고 말한다(짝: 옮기기만 하면 남는다)
 *  · 이 환경의 실제 서버는 Claude 키가 없다 — 가로채지 않은 길로 ★실제 봉인(설명·기록)이 브라우저 왕복을 견디는지★까지 한 번 돈다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
/** 종목 → 수익률 → 추정 → 비중(수익률은 비중에도 바로): 끝까지 계산된다(연습용 데이터). 흐름 번호 1~4. */
const CORE = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 320, 0),
                             n("estimate", "estimate", 640, 0), n("optimizer", "optimizer", 960, 0)],
               edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                       e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")] };
const RO = "returns.returns->optimizer.returns";
const ASK = "**/api/v1/assist/canvas/ask";
const NOTICE = "연습용 결과예요. 실제 시세가 아니라 합성 데이터로 계산했어요. 투자 판단에 쓰기 전에 실데이터로 다시 계산해 주세요.";
type RunNode = { explain?: unknown; explain_sig?: string };
type RunEdge = Record<string, unknown> & { sig?: string; target: string };
type Report = { nodes: Record<string, RunNode>; edges: Record<string, RunEdge> };
type Sent = { graph: { nodes: { id: string }[] }; target: { kind: string; id: string }; question: string;
              previous: { question: string; answer: string } | null;
              facts: { node_id: string; explain: unknown; sig: string }[]; records: { edge_id: string; record: unknown; sig: string }[] };

const SENTS = [{ text: "기대 수익을 과거 평균으로 잡았어요.", fact_ids: ["f5"] },
               { text: "비중은 수익 대비 위험 최적으로 나눴어요.", fact_ids: ["f9", "f11"] }];
const FACTS = {
  f5: { target_kind: "node", target_id: "estimate", part: "사실", index: 1, text: "기대 수익은 과거 평균이에요" },
  f9: { target_kind: "node", target_id: "optimizer", part: "제목", index: 0, text: "비중을 수익 대비 위험 최적으로 나눴어요" },
  f11: { target_kind: "edge", target_id: RO, part: "건너간 것", index: 0, text: "기간: 756일" },
};
const ok = (extra: Record<string, unknown> = {}) => ({
  available: true, source: "claude", model: "claude-opus-5-5", answer: { answerable: true, cannot: null, sentences: SENTS },
  facts: FACTS, rejected: [], dropped: [], notice: NOTICE, scope: { nodes: ["universe", "returns", "estimate", "optimizer"], edges: [] },
  cached: false, usage: { input_tokens: 1800, output_tokens: 200, cost_usd: 0.0112, cost_note: null }, ...extra });

const dock = (page: Page) => page.locator(".pg-ask");
const box = (page: Page) => page.locator(".pg-ask-text");
const send = (page: Page) => page.locator(".pg-ask-send");

async function signIn(page: Page) {
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "alice", role: "analyst" }, must_change_password: false, password_changed_at: null } }));
}

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("ai3_seeded")) return;
      sessionStorage.setItem("ai3_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      localStorage.removeItem("alpha_pg_view");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
}

async function runAll(page: Page): Promise<Report> {
  const res = page.waitForResponse((r) => r.url().includes("/allocation/graph/run") && r.request().method() === "POST", { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await res).json();
  await expect(page.locator(".pg-run")).toHaveText("계산하기", { timeout: 120_000 });
  return body;
}

function answer(page: Page, body: object | ((route: Route, i: number) => Promise<void>)) {
  const seen: Sent[] = [];
  return page.route(ASK, async (route) => {
    seen.push(route.request().postDataJSON());
    if (typeof body === "function") return body(route, seen.length - 1);
    await route.fulfill({ json: body });
  }).then(() => seen);
}

const pick = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`).click();
const pickEdge = (page: Page, id: string) => page.locator(`.react-flow__edge[data-testid="rf__edge-${id}"]`)
  .evaluate((el) => (el as HTMLElement).dispatchEvent(new MouseEvent("click", { bubbles: true })));

async function askText(page: Page, q: string) {
  await box(page).fill(q);
  await box(page).press("Enter");
}

test.use({ viewport: { width: 1440, height: 900 } });

test("아무것도 고르지 않으면 묻기 칸이 없다 — 짝: 노드를 고르면 '4 비중 계산에게 묻기' · 범위 한 줄", async ({ page }) => {
  await signIn(page);
  await openWith(page, CORE);
  await runAll(page);
  await expect(dock(page)).toHaveCount(0);
  await pick(page, "optimizer");
  await expect(dock(page).locator(".pg-ask-to")).toHaveText("4 비중 계산에게 묻기");                      // ★짝★
  await expect(dock(page).locator(".pg-ask-scope")).toHaveText("이 노드와 위쪽 3의 계산 설명으로 답해요");          // 0 인 쪽은 말하지 않는다
  await pick(page, "estimate");
  await expect(dock(page).locator(".pg-ask-scope")).toHaveText("이 노드와 위쪽 2 · 아래 1의 계산 설명으로 답해요");
  await page.locator(".react-flow__pane").click({ position: { x: 600, y: 600 } });
  await expect(dock(page)).toHaveCount(0);
});

test("계산 전에는 안내 + [여기까지 계산] — 누르면 그 노드까지 계산되고 입력 칸이 생긴다", async ({ page }) => {
  await signIn(page);
  await openWith(page, CORE);
  await pick(page, "estimate");
  await expect(dock(page).locator(".pg-ask-wait")).toHaveText("계산한 뒤에 물을 수 있어요");
  await expect(box(page)).toHaveCount(0);
  const res = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await dock(page).locator(".pg-ask-run").click();
  expect((await res).url()).toContain("targets=estimate");
  await expect(box(page)).toBeVisible({ timeout: 120_000 });
  await expect(dock(page).locator(".pg-ask-wait")).toHaveCount(0);
});

test("로그아웃이면 로그인 링크 · 요청 0", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/assist/canvas/ask")) sent.push(r.url()); });
  await openWith(page, CORE);
  await runAll(page);
  await pick(page, "optimizer");
  await expect(dock(page).locator(".pg-ask-login")).toHaveText("로그인하면 AI 에게 물을 수 있어요");
  await expect(dock(page).locator(".pg-ask-login")).toHaveAttribute("href", "/login");
  await expect(box(page)).toHaveCount(0);
  await page.waitForTimeout(400);
  expect(sent).toEqual([]);
});

test("물으면 /run 의 설명·봉인과 전달 점검·봉인을 그대로 보낸다 → 쓰는 중 잠김 → 문장·사실 칩 · 칩은 원문을 펼치고 [그 노드로]", async ({ page }) => {
  await signIn(page);
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const seen = await answer(page, async (route) => { await gate; await route.fulfill({ json: ok() }); });
  await openWith(page, CORE);
  const rep = await runAll(page);
  await pick(page, "optimizer");
  await askText(page, "왜 이렇게 나눴나요?");
  await expect(send(page)).toHaveText("묻는 중이에요");
  await expect(send(page)).toBeDisabled();
  await expect(box(page)).toBeDisabled();
  release();
  await expect(dock(page).locator(".pg-ask-sent")).toHaveCount(2);
  expect(seen).toHaveLength(1);
  const s = seen[0];
  expect(s.target).toEqual({ kind: "node", id: "optimizer" });
  expect(s.question).toBe("왜 이렇게 나눴나요?");
  expect(s.previous).toBeNull();
  expect(s.facts.map((f) => f.node_id)).toEqual(["universe", "returns", "estimate", "optimizer"]);
  for (const f of s.facts) {
    expect(f.sig).toBe(rep.nodes[f.node_id].explain_sig);
    expect(f.explain).toEqual(rep.nodes[f.node_id].explain);
  }
  expect(s.records.map((r) => r.edge_id).sort()).toEqual(Object.keys(rep.edges).sort());
  for (const r of s.records) {
    const { sig, ...rec } = rep.edges[r.edge_id];
    expect(r.sig).toBe(sig);
    expect(r.record).toEqual(rec);                                                         // 봉인은 `sig` 칸을 뗀 기록에 대한 것
  }
  const turn = dock(page).locator(".pg-ask-turn").first();
  await expect(turn.locator(".pg-ask-q")).toHaveText("왜 이렇게 나눴나요?");
  await expect(turn.locator(".pg-ask-sent-text")).toHaveText(SENTS.map((x) => x.text));
  await expect(turn.locator(".pg-ask-sent").nth(1).locator(".pg-ask-chip")).toHaveText(["4 비중 계산 · 제목", "2→4 선 · 건너간 것 1"]);
  const chip = turn.locator(".pg-ask-sent").first().locator(".pg-ask-chip");
  await expect(chip).toHaveText("3 기대 수익 추정 · 사실 2");
  await expect(chip).toHaveAttribute("aria-expanded", "false");
  await expect(turn.locator(".pg-ask-fact")).toHaveCount(0);
  await chip.click();
  await expect(chip).toHaveAttribute("aria-expanded", "true");
  await expect(turn.locator(".pg-ask-fact-text")).toHaveText("기대 수익은 과거 평균이에요");
  await expect(page.locator(".pg-side-title")).toContainText("비중 계산");                 // 펼치기만 — 고른 것은 그대로
  await turn.locator(".pg-ask-goto").click();
  await expect(page.locator(".pg-side-title")).toContainText("기대 수익 추정");
  await expect(dock(page).locator(".pg-ask-to")).toHaveText("3 기대 수익 추정에게 묻기");
});

test("자주 묻는 질문 칩은 누르면 바로 묻는다 · 노드와 선은 다른 질문", async ({ page }) => {
  await signIn(page);
  const seen = await answer(page, ok());
  await openWith(page, CORE);
  await runAll(page);
  await pick(page, "optimizer");
  await expect(dock(page).locator(".pg-ask-preset")).toHaveText(["이 결과는 어디서 왔나요?", "무엇을 재지 않았나요?", "이 결과를 믿어도 되나요?"]);
  await dock(page).locator(".pg-ask-preset").nth(1).click();
  await expect.poll(() => seen.length).toBe(1);
  expect(seen[0].question).toBe("무엇을 재지 않았나요?");
  await pickEdge(page, RO);
  await expect(dock(page).locator(".pg-ask-to")).toHaveText("2 수익률 불러오기 → 4 비중 계산 선에게 묻기");
  await expect(dock(page).locator(".pg-ask-preset")).toHaveText(["무엇이 건너가나요?", "빠지거나 바뀐 것이 있나요?"]);
  await dock(page).locator(".pg-ask-preset").first().click();
  await expect.poll(() => seen.length).toBe(2);
  expect(seen[1].target).toEqual({ kind: "edge", id: RO });
  expect(seen[1].question).toBe("무엇이 건너가나요?");
});

test("답할 수 없으면 서버 고정 문장 · 연습용 경고는 서버가 붙였을 때만(짝)", async ({ page }) => {
  await signIn(page);
  await answer(page, async (route, i) => {
    await route.fulfill({ json: i === 0
      ? ok({ answer: { answerable: false, cannot: "투자 판단은 말하지 않아요 — 계산이 무엇을 냈는지만 답해요.", sentences: [] }, facts: {} })
      : ok({ notice: null }) });
  });
  await openWith(page, CORE);
  await runAll(page);
  await pick(page, "optimizer");
  await askText(page, "사도 돼요?");
  const first = dock(page).locator(".pg-ask-turn").first();
  await expect(first.locator(".pg-ask-cannot")).toHaveText("투자 판단은 말하지 않아요 — 계산이 무엇을 냈는지만 답해요.");
  await expect(first.locator(".pg-ask-sent")).toHaveCount(0);
  await expect(first.locator(".pg-ask-notice")).toHaveText(NOTICE);
  await askText(page, "그럼 무엇을 냈나요?");
  const second = dock(page).locator(".pg-ask-turn").nth(1);
  await expect(second.locator(".pg-ask-sent")).toHaveCount(2);
  await expect(second.locator(".pg-ask-notice")).toHaveCount(0);                              // ★짝★
  await expect(second.locator(".pg-ask-cannot")).toHaveCount(0);
});

test("못 보이면 서버 사유 · 검사에서 빠진 문장과 확인 못 한 결과는 수와 첫 사유", async ({ page }) => {
  await signIn(page);
  await answer(page, async (route, i) => {
    await route.fulfill({ json: i === 0
      ? { available: false, source: "unavailable", reason_code: "rate_limited", reason: "한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요", dropped: [] }
      : ok({ answer: { answerable: true, cannot: null, sentences: [SENTS[0]] },
             rejected: [{ code: "numbers", reason: "댄 사실 줄에 없는 숫자 9 를 썼어요" }],
             dropped: [{ node_id: "estimate", reason: "서명이 맞지 않아요(그래프가 바뀌었거나 서버가 다시 시작했어요). 다시 계산하면 물을 수 있어요" }] }) });
  });
  await openWith(page, CORE);
  await runAll(page);
  await pick(page, "optimizer");
  await askText(page, "왜요?");
  await expect(dock(page).locator(".pg-ask-turn").first().locator(".pg-ask-note"))
    .toHaveText("AI 답을 보여 줄 수 없어요: 한 시간에 30번까지 물을 수 있어요. 이번 시간에는 다 썼어요");
  await askText(page, "다시 왜요?");
  const note = dock(page).locator(".pg-ask-turn").nth(1).locator(".pg-ask-note");
  await expect(note).toContainText("1문장은 검사에서 빠졌어요: 댄 사실 줄에 없는 숫자 9 를 썼어요");
  await expect(note).toContainText("1개 결과는 확인하지 못해 뺐어요: 서명이 맞지 않아요");
});

test("이어 묻기는 직전 문답 하나만 보낸다 · Enter 는 보내고 Shift+Enter 는 줄을 바꾼다", async ({ page }) => {
  await signIn(page);
  const seen = await answer(page, async (route, i) => {
    await route.fulfill({ json: ok({ answer: { answerable: true, cannot: null, sentences: [{ text: `답 ${i + 1}이에요.`, fact_ids: ["f9"] }] } }) });
  });
  await openWith(page, CORE);
  await runAll(page);
  await pick(page, "optimizer");
  await box(page).fill("첫");
  await box(page).press("Shift+Enter");
  await box(page).type("질문");
  expect(seen).toHaveLength(0);
  await box(page).press("Enter");
  await expect.poll(() => seen.length).toBe(1);
  expect(seen[0].question).toBe("첫\n질문");
  await askText(page, "둘째");
  await expect.poll(() => seen.length).toBe(2);
  await askText(page, "셋째");
  await expect.poll(() => seen.length).toBe(3);
  expect(seen[0].previous).toBeNull();
  expect(seen[1].previous).toEqual({ question: "첫\n질문", answer: "답 1이에요." });
  expect(seen[2].previous).toEqual({ question: "둘째", answer: "답 2이에요." });               // 하나만 — 첫 문답은 없다
  await expect(dock(page).locator(".pg-ask-turn")).toHaveCount(3);
});

test("대상마다 문답이 남는다 — 다른 노드에 갔다 오면 그대로 · 옮기기만 하면 그대로 · 결과가 바뀌면 지우고 말한다", async ({ page }) => {
  await signIn(page);
  await answer(page, ok());
  await openWith(page, CORE);
  await runAll(page);
  await pick(page, "optimizer");
  await askText(page, "왜요?");
  await expect(dock(page).locator(".pg-ask-turn")).toHaveCount(1);
  await pick(page, "returns");
  await expect(dock(page).locator(".pg-ask-turn")).toHaveCount(0);
  await pick(page, "optimizer");
  await expect(dock(page).locator(".pg-ask-turn")).toHaveCount(1);
  const b = (await page.locator('.react-flow__node[data-id="universe"]').boundingBox())!;      // ★짝★ 옮기기
  await page.mouse.move(b.x + 30, b.y + 14);
  await page.mouse.down();
  await page.mouse.move(b.x + 60, b.y + 160, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(600);
  await pick(page, "optimizer");
  await expect(dock(page).locator(".pg-ask-turn")).toHaveCount(1);
  await expect(dock(page).locator(".pg-ask-stale")).toHaveCount(0);
  await page.locator('.react-flow__node[data-id="estimate"]').click();                       // 지운다 — 비중 계산이 낡는다
  await page.keyboard.press("Delete");
  await pick(page, "optimizer");
  await expect(dock(page).locator(".pg-ask-turn")).toHaveCount(0);
  await expect(dock(page).locator(".pg-ask-stale")).toHaveText("계산 결과가 바뀌어 답을 지웠어요");
  await expect(dock(page).locator(".pg-ask-wait")).toHaveText("계산한 뒤에 물을 수 있어요");
});

test("Ctrl+K '고른 것에게 묻기' 는 칸에 초점을 둔다 · Esc 는 초점을 놓는다", async ({ page }) => {
  await signIn(page);
  await openWith(page, CORE);
  await runAll(page);
  await pick(page, "optimizer");
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("묻기");
  await expect(page.locator('.pg-cmd-item[data-cmd="ask-here"]')).toContainText("고른 노드에게 묻기");
  await page.keyboard.press("Enter");
  await expect(box(page)).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(box(page)).not.toBeFocused();
  await expect(dock(page)).toBeVisible();
});

test("가로채지 않은 실제 서버: 실제 계산 → 실제 봉인(설명·기록) → 브라우저 왕복 → 서버 확인(버린 것 0) → 키 없음 사유", async ({ page }) => {
  const login = await page.request.post("/api/backend/api/v1/auth/login", { data: { username: "admin", password: "frm123!" } });
  expect(login.ok(), await login.text()).toBe(true);
  const token = (await login.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  await openWith(page, CORE);
  await runAll(page);
  await pickEdge(page, RO);
  const res = page.waitForResponse((r) => r.url().includes("/assist/canvas/ask"));
  await askText(page, "무엇이 건너가나요?");
  const body = await (await res).json();
  expect(body).toMatchObject({ available: false, source: "unavailable", reason_code: "no_key", dropped: [] });
  await expect(dock(page).locator(".pg-ask-note")).toHaveText("AI 답을 보여 줄 수 없어요: 서버에 Claude 키가 없어요");
});

for (const scheme of ["light", "dark"] as const) {
  test(`묻기 칸 대비(${scheme}) AA`, async ({ page }) => {
    await signIn(page);
    await answer(page, ok());
    await openWith(page, CORE);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await runAll(page);
    await pick(page, "optimizer");
    await askText(page, "왜요?");
    await dock(page).locator(".pg-ask-chip").first().click();
    await expect(dock(page).locator(".pg-ask-fact")).toBeVisible();
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-ask"));
    expect(a.checked).toBeGreaterThanOrEqual(10);
    expect(a.low, scheme).toEqual([]);
  });
}

test.describe("좁은 화면(390)", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("노드를 고르면 아래 시트 맨 아래에 칸 — 화면 안 · 물으면 답", async ({ page }) => {
    await signIn(page);
    await answer(page, ok());
    await openWith(page, CORE);
    await runAll(page);
    await pick(page, "optimizer");
    await expect(page.locator(".pg-side")).toBeVisible();
    await expect(box(page)).toBeVisible();
    for (const loc of [box(page), send(page)]) {
      const b = (await loc.boundingBox())!;
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width).toBeLessThanOrEqual(390);
      expect(b.y + b.height).toBeLessThanOrEqual(844);
    }
    await askText(page, "왜요?");
    await expect(dock(page).locator(".pg-ask-sent")).toHaveCount(2);
  });
});

test.describe("두 창을 연 1024", () => {
  test.use({ viewport: { width: 1024, height: 768 } });
  test("칸이 오른쪽 창 안에 있고 답이 길어도 창 높이의 절반을 넘지 않는다", async ({ page }) => {
    await signIn(page);
    await answer(page, ok({ answer: { answerable: true, cannot: null, sentences: [...SENTS, ...SENTS] } }));
    await openWith(page, CORE);
    await runAll(page);
    // 두 창을 열면 비중 계산 카드는 오른쪽 창 밑이다 — 이야기 탭의 단계로 고른다(사람이 이 폭에서 고르는 길).
    await page.locator('.pg-step[data-node-id="optimizer"] .pg-step-num').click();
    await expect(dock(page).locator(".pg-ask-to")).toHaveText("4 비중 계산에게 묻기");
    await askText(page, "왜요?");
    await askText(page, "또 왜요?");
    await expect(dock(page).locator(".pg-ask-turn")).toHaveCount(2);
    const side = (await page.locator(".pg-side").boundingBox())!;
    const d = (await dock(page).boundingBox())!;
    expect(d.x).toBeGreaterThanOrEqual(side.x);
    expect(d.x + d.width).toBeLessThanOrEqual(side.x + side.width + 1);
    expect(d.height).toBeLessThanOrEqual(side.height / 2 + 2);
    await expect(page.locator(".pg-panel")).toBeVisible();
    // 머리 줄과 입력은 칸 안에 고정 — 문답만 스크롤한다(PNG 검토에서 찾음: 칸 전체가 스크롤되면 입력이 밀려 사라졌다)
    for (const loc of [dock(page).locator(".pg-ask-to"), box(page)]) {
      const b = (await loc.boundingBox())!;
      expect(b.y).toBeGreaterThanOrEqual(d.y - 1);
      expect(b.y + b.height).toBeLessThanOrEqual(d.y + d.height + 1);
    }
    const turns = dock(page).locator(".pg-ask-turns");
    expect(await turns.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    // 같은 연습용 경고는 답마다 되풀이하지 않는다 — 첫 답에만(짝: 첫 답에는 있다) · 자주 묻는 질문 칩은 첫 질문 전에만
    await expect(dock(page).locator(".pg-ask-turn").nth(0).locator(".pg-ask-notice")).toHaveCount(1);
    await expect(dock(page).locator(".pg-ask-turn").nth(1).locator(".pg-ask-notice")).toHaveCount(0);
    await expect(dock(page).locator(".pg-ask-preset")).toHaveCount(0);
  });
});
