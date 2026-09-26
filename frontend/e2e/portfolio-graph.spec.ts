import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { contrastAudit, trackErrors, uniq, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// AAS 노드 캔버스 (BI3·BI4 · ADR 002) — `/allocation`
// ─────────────────────────────────────────────────────────────────────────────
// 거는 것:
//  · 팔레트는 서버 카탈로그에서 온다 · 기본 사슬 실행 → 노드 7개 모두 완료, 404·콘솔 오류 0
//  · 타입이 다른 포트끼리는 연결되지 않는다 — ★짝★ 같은 타입은 연결된다
//  · 상류 실패 → 하류는 "막힘" + 어느 상류 때문인지 (기본값으로 돌지 않는다)
//  · ★내보내기 → 새 탭에서 불러오기 → 같은 문서★ (왕복) — 불러오면 즉시 캔버스에 뜬다
//  · 모르는 노드는 버리지 않는다(빨간 미상 노드, 다시 내보내면 그대로) · 다른 포맷은 거부
//  · 마법사로 넘기기 → 마법사가 같은 /analyze 로 **같은 최적 비중**을 다시 구한다
//  BJ(토스식 UX · 스펙 2026-09-25-aas-workflow-ux):
//  · 이야기 탭 = 서버 explain 을 노드 번호 순서로 · 연습용이면 맨 위 경고 · 카드 ↔ 노드 선택
//  · 증거 관문 레일 — 계산 전엔 판정 없음, 계산 뒤 ★건너뛴 관문은 선이 끊긴다★(짝: 이어진 구간)
//  · 설정 기본(질문형 카드·칩) → 파라미터가 실제로 바뀐다 · 전문가 토글 = 모든 파라미터
//  · 라이트·다크 AA 대비 · 다크에 밝은 배경 0
// ═══════════════════════════════════════════════════════════════════════════════

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const status = (page: Page, id: string) => node(page, id).locator(".pg-node-status-k");
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();
const handle = (page: Page, id: string, port: string, kind: "source" | "target") =>
  page.locator(`.react-flow__handle.${kind}[data-nodeid="${id}"][data-handleid="${port}"]`);

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}

async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await resp).json();
  // 결과 요약 칸 — 검증 오류·낡음 알림(같은 .pg-summary)과 구별한다.
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}

async function drag(page: Page, from: ReturnType<typeof handle>, to: ReturnType<typeof handle>) {
  const a = (await from.boundingBox())!;
  const b = (await to.boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await page.mouse.up();
}

async function exportDoc(page: Page) {
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const file = await (await dl).path();
  return JSON.parse(readFileSync(file!, "utf-8"));
}

async function importText(page: Page, name: string, text: string) {
  await page.locator(".pg-import-input").setInputFiles({ name, mimeType: "application/json", buffer: Buffer.from(text) });
}

const strip = (doc: { meta?: object }) => ({ ...doc, meta: undefined });

test("캔버스: 카탈로그 팔레트 · 기본 사슬 실행 → 7 노드 완료 · 오류 0", async ({ page }) => {
  const sink = trackErrors(page);
  await openCanvas(page);
  // 팔레트 = 서버 카탈로그(핵심 사슬 7 + BK 웨이브 노드).
  const catalog = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  await expect(page.locator(".pg-palette-item")).toHaveCount(catalog.nodes.length);
  expect(catalog.nodes.length).toBeGreaterThan(7);
  await expect(page.locator(".pg-node")).toHaveCount(7);
  const body = await run(page);
  expect(body.ok).toBe(true);
  for (const id of ["universe", "returns", "estimate", "views", "optimizer", "risk", "backtest"]) {
    await expect(status(page, id), id).toHaveText("완료");
  }
  // mock 수익률은 합성이다 — 노드 칩이 그렇게 말해야 한다(실데이터처럼 보이면 안 된다).
  await expect(node(page, "returns").locator(".pg-node-ev")).toContainText("연습용");
  await node(page, "optimizer").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-table tr")).toHaveCount(3);
  await expect(page.locator(".pg-side .perf-label")).toContainText("합성데이터");

  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("연결: 타입이 다르면 거부, 같으면 연결된다(짝)", async ({ page }) => {
  await openCanvas(page);
  await page.locator('.pg-palette-item[data-kind="risk"]').click();
  const added = page.locator('.pg-node[data-kind="risk"]').last();
  const newId = await added.getAttribute("data-node-id");
  expect(newId).not.toBe("risk");
  // 새 노드를 빈 곳(캔버스 왼쪽 아래)으로 옮긴다 — 다른 노드의 포트와 겹치지 않게.
  const box = (await page.locator(".pg-canvas").boundingBox())!;
  const head = (await added.locator(".pg-node-k").boundingBox())!;
  await page.mouse.move(head.x + 20, head.y + 8);
  await page.mouse.down();
  await page.mouse.move(box.x + 140, box.y + box.height - 90, { steps: 10 });
  await page.mouse.up();
  const edges = page.locator(".react-flow__edge");
  const before = await edges.count();

  // Universe → Weights : 거부
  await drag(page, handle(page, "universe", "universe", "source"), handle(page, newId!, "weights", "target"));
  await expect(edges).toHaveCount(before);
  // Weights → Weights : 연결
  await drag(page, handle(page, "optimizer", "weights", "source"), handle(page, newId!, "weights", "target"));
  await expect(edges).toHaveCount(before + 1);
});

test("실패는 번지되 지어내지 않는다: 종목 1개 → 수익률 실패, 하류 막힘 + 사유", async ({ page }) => {
  await openCanvas(page);
  await node(page, "universe").click();
  await tab(page, "settings");
  const tickers = page.locator('.pg-basic-field[data-field="tickers"] input');
  await tickers.fill("005930");
  await tickers.press("Enter");
  await run(page);
  await expect(status(page, "returns")).toHaveText("실패");
  await expect(node(page, "returns").locator(".pg-node-status-why")).toContainText("2개 미만");
  for (const id of ["optimizer", "risk", "backtest", "estimate"]) {
    await expect(status(page, id), id).toHaveText("막힘");
    await expect(node(page, id).locator(".pg-node-status-why")).toContainText("상류");
  }
  await expect(status(page, "views"), "관계없는 가지는 돈다").toHaveText("완료");
});

test("왕복: 내보내기 → 새 탭 불러오기 → 같은 문서가 즉시 캔버스에", async ({ page, context }) => {
  await openCanvas(page);
  await page.locator(".pg-name").fill("왕복 테스트");
  const exported = await exportDoc(page);
  expect(exported.format).toBe("project-alpha.portfolio-graph");
  expect(exported.nodes).toHaveLength(7);
  // 실행 결과는 담지 않는다 — 파라미터·위치만.
  expect(JSON.stringify(exported)).not.toContain("\"status\"");

  // 구별되게 바꾼다 — 위치·파라미터 모두 새 탭에 그대로 나타나야 한다.
  exported.nodes.find((n: { id: string }) => n.id === "optimizer").params = { model: "hrp", delta: 3 };
  exported.nodes.find((n: { id: string }) => n.id === "risk").position = { x: 1500, y: -40 };

  const page2 = await context.newPage();
  await openCanvas(page2);
  await importText(page2, "roundtrip.portfolio-graph.json", JSON.stringify(exported));
  await expect(page2.locator(".pg-file-note")).toContainText("불러왔어요");
  await expect(page2.locator(".pg-name")).toHaveValue("왕복 테스트");
  const again = await exportDoc(page2);
  expect(strip(again)).toEqual(strip(exported));
  await page2.close();
});

test("모르는 노드는 버리지 않는다 · 다른 포맷은 캔버스를 건드리지 않는다", async ({ page }) => {
  await openCanvas(page);
  const doc = await exportDoc(page);
  doc.nodes.push({ id: "future", type: "future_node", params: { k: 1 }, position: { x: 100, y: 500 } });
  doc.edges.push({ id: "f1", source: "future", source_port: "out", target: "risk", target_port: "extra" });
  await importText(page, "future.json", JSON.stringify(doc));
  const unknown = node(page, "future");
  await expect(unknown).toHaveClass(/pg-node--unknown/);
  await expect(unknown).toContainText("future_node");
  await expect(node(page, "risk").locator(".pg-port--unknown")).toContainText("extra");
  const again = await exportDoc(page);
  expect(again.nodes.map((n: { id: string }) => n.id)).toContain("future");
  expect(again.edges.map((e: { id: string }) => e.id)).toContain("f1");
  await run(page);
  await expect(status(page, "future")).toHaveText("막힘");
  await expect(node(page, "future").locator(".pg-node-status-why")).toContainText("future_node");

  // 다른 포맷 — 거부하고, 캔버스는 그대로(노드 8개).
  await importText(page, "comfy.json", JSON.stringify({ format: "comfyui", nodes: [] }));
  await expect(page.locator(".pg-file-note")).toContainText("불러오지 않았어요");
  await expect(page.locator(".pg-node")).toHaveCount(8);
  await importText(page, "broken.json", "{not json");
  await expect(page.locator(".pg-file-note")).toContainText("JSON 이 아닙니다");
  await expect(page.locator(".pg-node")).toHaveCount(8);
});

test("넘기기: 마법사가 같은 /analyze 로 같은 최적 비중을 다시 구한다", async ({ page }) => {
  // ★마법사 세션을 다른 δ·τ 로 미리 채운다★ — 캔버스에서 비워 둔 δ·τ(서버 기본값)를 넘기지
  // 않으면 마법사는 이 값으로 계산해 다른 수가 나온다. 기본값끼리 같으면 이 테스트는 공허하다.
  await page.addInitScript(() => {
    if (sessionStorage.getItem("pg_test_seeded")) return;
    sessionStorage.setItem("pg_test_seeded", "1");
    sessionStorage.setItem("alpha_alloc_wip", JSON.stringify({
      holdings: [{ code: "000270", name: "기아", weight: 100 }], views: [], model: "mvo", delta: 6, tau: 0.5,
    }));
  });
  await openCanvas(page);
  // 뷰 하나 — δ·τ 가 결과에 들어가게(뷰 없는 BL 은 δ 와 무관하다).
  const doc = await exportDoc(page);
  doc.nodes.find((n: { id: string }) => n.id === "views").params = {
    views: [{ assets: ["005930"], direction: 1, magnitude_pct: 6, confidence: 70 }],
  };
  await importText(page, "with-view.json", JSON.stringify(doc));
  const body = await run(page);
  expect(body.nodes.optimizer.view.views_applied, "뷰가 실제로 들어갔다").toBe(true);
  const canvasWeights = body.nodes.optimizer.view.weights;
  await node(page, "optimizer").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-handoff-notcarried")).toContainText("균등 비중");
  const analyze = page.waitForResponse(
    (r) => r.url().includes("/allocation/analyze") && r.request().method() === "POST", { timeout: 60_000 });
  await page.locator('.pg-handoff[data-href="/allocation/stress"]').click();
  await expect(page).toHaveURL(/\/allocation\/stress/, { timeout: 20_000 });
  const req = (await analyze).request().postDataJSON();
  expect([req.delta, req.tau], "캔버스가 실제로 쓴 δ·τ").toEqual([2.5, 0.05]);
  const res = await (await analyze).json();
  expect(res.weights.optimized, "마법사가 다시 구한 최적 비중 == 캔버스").toEqual(canvasWeights);
});

test("마법사는 보존된다: 게이트는 /allocation/wizard, 캔버스 줄에서 열린다", async ({ page }) => {
  await openCanvas(page);
  await page.locator(".pg-wizard > summary").click();
  await page.locator(".pg-wizard-link", { hasText: "목표 선택" }).click();
  await expect(page).toHaveURL(/\/allocation\/wizard/);
  await expect(page.locator(".aas-goal").first()).toBeVisible({ timeout: 20_000 });
});

test("이야기: 노드 번호 순서의 서버 설명 · 연습용 경고 · 카드를 누르면 노드가 선택된다", async ({ page }) => {
  await openCanvas(page);
  await expect(page.locator(".pg-step")).toHaveCount(7);
  await expect(page.locator(".pg-notice"), "계산 전에는 연습용 경고가 없다(짝)").toHaveCount(0);
  const body = await run(page);
  await expect(page.locator(".pg-notice").first()).toContainText("연습용 결과예요");
  // 제목은 서버 explain.title 그대로 — 화면이 문장을 짓지 않는다.
  const first = page.locator(".pg-step").first();
  const id = await first.getAttribute("data-node-id");
  await expect(first.locator(".pg-step-title")).toHaveText(body.nodes[id!].explain.title);
  await expect(page.locator('.pg-step[data-node-id="optimizer"] .pg-bar-row')).toHaveCount(3);
  await expect(page.locator('.pg-step[data-node-id="returns"] .pg-trust')).toContainText("몰라요");
  await page.locator('.pg-step[data-node-id="risk"] .pg-step-title button').click();
  await expect(node(page, "risk")).toHaveClass(/pg-node--selected/);
  await expect(node(page, "optimizer")).not.toHaveClass(/pg-node--selected/);
  await page.locator('.pg-step[data-node-id="risk"] .pg-more').click();
  await expect(page.locator('.pg-tab[data-tab="detail"]')).toHaveClass(/on/);
});

test("관문 레일: 계산 전 판정 없음 · 건너뛴 관문은 끊기고 이어진 구간은 잇는다", async ({ page }) => {
  await openCanvas(page);
  const stn = (k: string) => page.locator(`.pg-stn[data-gate="${k}"]`);
  await expect(page.locator(".pg-stn")).toHaveCount(8);
  await expect(page.locator(".pg-stn--idle")).toHaveCount(8);
  await expect(stn("build").locator("button")).toBeDisabled();
  const body = await run(page);
  const gates = Object.fromEntries(body.gates.gates.map((g: { key: string; state: string }) => [g.key, g.state]));
  for (const [k, st] of Object.entries(gates)) await expect(stn(k), k).toHaveClass(new RegExp(`pg-stn--${st}\\b`));
  // 이 그래프에는 신호 노드가 없다 — 신호는 건너뜀이고, 경제적 가치·실계좌는 이 경로에 없다.
  expect([gates.signal, gates.economic, gates.live]).toEqual(["skipped", "skipped", "skipped"]);
  expect(gates.build, "짝: 모두 건너뜀인 구현이 아니다").toBe("confirmed");
  await expect(stn("build"), "신호(건너뜀) → 비중 계산 구간은 끊긴다").toHaveClass(/pg-stn--link-off/);
  await expect(stn("cost"), "비중 계산(확인) → 거래비용(가정) 구간은 잇는다").toHaveClass(/pg-stn--link-on/);
  await stn("cost").locator("button").click();
  await expect(page.locator(".pg-gate-pop")).toContainText("가정");
  await expect(page.locator(".pg-gate-pop")).toContainText("0.1%");
  await page.locator(".pg-gate-close").click();
  await expect(page.locator(".pg-gate-pop")).toHaveCount(0);
});

test("설정: 기본 질문이 파라미터를 바꾸고, 전문가 토글이 모든 칸을 연다", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await tab(page, "settings");
  await expect(page.locator(".pg-inspector"), "기본 화면에는 전문가 칸이 없다").toHaveCount(0);
  await expect(page.locator(".pg-io")).toContainText("수익률");
  const model = page.locator('.pg-basic-field[data-field="model"]');
  await expect(model.locator(".pg-choice.on")).toHaveText("내 생각 반영");
  await model.locator(".pg-choice", { hasText: "흔들림 최소" }).click();
  await expect(model.locator(".pg-choice.on")).toHaveText("흔들림 최소");
  await page.locator('.pg-basic-field[data-field="constraints"] .pg-chip', { hasText: "30%" }).click();
  const doc = await exportDoc(page);
  const params = doc.nodes.find((n: { id: string }) => n.id === "optimizer").params;
  expect(params.model).toBe("min_var");
  expect(params.constraints).toEqual({ max_weight_pct: 30 });
  // "제한 없음" 은 키를 지운다 — 서버 기본값(빈 칸 = 기본값 규칙).
  await page.locator('.pg-basic-field[data-field="constraints"] .pg-chip', { hasText: "제한 없음" }).click();
  expect((await exportDoc(page)).nodes.find((n: { id: string }) => n.id === "optimizer").params).not.toHaveProperty("constraints");

  await page.locator(".pg-mode input").check();
  await expect(page.locator(".pg-inspector")).toBeVisible();
  await expect(page.locator(".pg-basic")).toHaveCount(0);
  await expect(page.locator(".pg-inspector .pg-field", { hasText: "τ" }), "기본 화면에 없던 칸").toBeVisible();
  await page.locator(".pg-mode input").uncheck();
  await expect(page.locator(".pg-inspector")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비: ${scheme} — AA 미달 0${scheme === "dark" ? " · 밝은 배경 0" : ""}`, async ({ page }) => {
    await openCanvas(page);
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.locator('.pg-stn[data-gate="cost"] button').click();
    await page.waitForTimeout(200);
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-root"));
    expect(audit.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(60);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

test("복제해서 비교: 같은 입력·같은 설정으로 하나 더 · 나가는 링크는 잇지 않는다 · Ctrl+Enter 로 계산", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await tab(page, "settings");
  await page.locator('.pg-basic-field[data-field="model"] .pg-choice', { hasText: "위험 똑같이" }).click();
  await page.locator(".pg-dup").click();
  await expect(page.locator(".pg-node")).toHaveCount(8);
  const doc = await exportDoc(page);
  const dup = doc.nodes.find((n: { id: string; type: string }) => n.type === "optimizer" && n.id !== "optimizer");
  expect(dup.params).toEqual(doc.nodes.find((n: { id: string }) => n.id === "optimizer").params);
  const into = (id: string) => doc.edges.filter((e: { target: string }) => e.target === id)
    .map((e: { source: string; target_port: string }) => `${e.source}.${e.target_port}`).sort();
  expect(into(dup.id)).toEqual(into("optimizer"));
  expect(into(dup.id).length).toBe(3);
  expect(doc.edges.filter((e: { source: string }) => e.source === dup.id), "나가는 링크는 복제하지 않는다").toEqual([]);
  // 복제본만 설정을 바꿔 나란히 — 원본은 그대로.
  await page.locator('.pg-basic-field[data-field="model"] .pg-choice', { hasText: "흔들림 최소" }).click();
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-canvas").click({ position: { x: 20, y: 20 } });
  await page.keyboard.press("Control+Enter");
  const body = await (await resp).json();
  expect(body.nodes[dup.id].status).toBe("ok");
  expect(body.nodes.optimizer.view.model).toBe("risk_parity");
  expect(body.nodes[dup.id].view.model).toBe("min_var");
  await tab(page, "story");
  await expect(page.locator(".pg-step")).toHaveCount(8);
});

test("확인하기 노드(BK W1): 팔레트에서 골라 비중에 잇고 계산 → 이야기·자세히에 서버 결과", async ({ page }) => {
  await openCanvas(page);
  for (const kind of ["scenario_stress", "corr_stress", "sensitivity", "factor_xray"]) {
    await expect(page.locator(`.pg-palette-item[data-kind="${kind}"]`), kind).toBeVisible();
  }
  await page.locator('.pg-palette-item[data-kind="scenario_stress"]').click();
  const added = page.locator('.pg-node[data-kind="scenario_stress"]').last();
  const id = (await added.getAttribute("data-node-id"))!;
  // 빈 곳으로 옮긴 뒤 옵티마이저 비중을 잇는다.
  const box = (await page.locator(".pg-canvas").boundingBox())!;
  const head = (await added.locator(".pg-node-k").boundingBox())!;
  await page.mouse.move(head.x + 20, head.y + 8);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 140, box.y + box.height - 110, { steps: 10 });
  await page.mouse.up();
  await drag(page, handle(page, "optimizer", "weights", "source"), handle(page, id, "weights", "target"));
  // 설정 탭: 시나리오는 목록(19개)에서 고른다 — 과거 위기(실제 시세 재생).
  await tab(page, "settings");
  await page.locator('.pg-basic-field[data-field="scenario"] select').selectOption("hist_2020_covid");
  const body = await run(page);
  const r = body.nodes[id];
  expect(r.status, r.reason).toBe("ok");
  await expect(status(page, id)).toHaveText("완료");
  await tab(page, "story");
  await expect(page.locator(`.pg-step[data-node-id="${id}"] .pg-step-title`)).toHaveText(r.explain.title);
  await page.locator(`.pg-step[data-node-id="${id}"] .pg-more`).click();
  await expect(page.locator(".pg-model-type")).toContainText("역사 리플레이");
  await expect(page.locator(".pg-side .pg-chart")).toBeVisible();
});

test("신호·후보 노드(BK W2): 스크리너 → 알파 점수 → 점수로 비중 · 오늘 값 표시 · 조건 편집기", async ({ page }) => {
  await openCanvas(page);
  const doc = await exportDoc(page);
  doc.nodes = [
    { id: "scr", type: "screener", params: { universe: "kospi50", top_n: 10 }, position: { x: 0, y: 100 } },
    { id: "alp", type: "alpha_score", params: {}, position: { x: 220, y: 100 } },
    { id: "w", type: "scores_to_weights", params: { top_k: 5 }, position: { x: 440, y: 100 } },
  ];
  doc.edges = [
    { id: "e1", source: "scr", source_port: "universe", target: "alp", target_port: "universe" },
    { id: "e2", source: "alp", source_port: "scores", target: "w", target_port: "scores" },
  ];
  await importText(page, "w2.json", JSON.stringify(doc));
  const body = await run(page);
  for (const id of ["scr", "alp", "w"]) expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
  expect(body.nodes.scr.lineage.pit).toBe("forward_only");
  await expect(node(page, "scr").locator(".pg-node-ev")).toContainText("지금 시점 전용");
  await node(page, "w").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-table tr")).toHaveCount(5);

  // 조건 편집기 — 프리셋으로 시작해 한 줄 더한다. 필드 목록은 서버 카탈로그에서 온다.
  await node(page, "scr").click();
  await tab(page, "settings");
  const f = page.locator('.pg-basic-field[data-field="filter_ast"]');
  await f.locator(".pg-chip", { hasText: "꾸준히 버는" }).click();
  await expect(f.locator(".pg-filter-row")).toHaveCount(1);
  await f.locator(".pg-add").click();
  await expect(f.locator(".pg-filter-row")).toHaveCount(2);
  await expect(f.locator(".pg-filter-row").first().locator("select").first().locator('option[value="roe"]')).toHaveCount(1);
  await f.locator(".pg-filter-row").nth(1).locator("input").fill("5");
  const saved = await exportDoc(page);
  const conds = saved.nodes.find((n: { id: string }) => n.id === "scr").params.filter_ast.conditions;
  expect(conds).toHaveLength(2);
  expect(conds[0]).toMatchObject({ field: "roe", op: "gt", value: 10 });
  expect(conds[1].value).toBe(5);
});

test("노출 조절(BK W3): 직접 정한 노출 60% → 조절 후 막대에 현금 칸 · 조절한 비중의 백테스트는 막힘", async ({ page }) => {
  await openCanvas(page);
  const doc = await exportDoc(page);
  doc.nodes.push({ id: "x", type: "exposure_overlay", params: { follow: "manual", manual_exposure_pct: 60 }, position: { x: 1000, y: 400 } });
  doc.nodes.push({ id: "b2", type: "backtest", params: {}, position: { x: 1200, y: 400 } });
  doc.edges.push({ id: "ex1", source: "optimizer", source_port: "weights", target: "x", target_port: "weights" });
  doc.edges.push({ id: "ex2", source: "x", source_port: "weights", target: "b2", target_port: "weights" });
  doc.edges.push({ id: "ex3", source: "returns", source_port: "returns", target: "b2", target_port: "returns" });
  await importText(page, "w3.json", JSON.stringify(doc));
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await resp).json();
  expect(body.nodes.x.status, body.nodes.x.reason).toBe("ok");
  expect(body.nodes.x.view.exposure).toBeCloseTo(0.6, 6);
  expect(body.nodes.x.lineage.overlay).toBe(true);
  expect(body.nodes.b2.status).toBe("failed");
  expect(body.nodes.b2.reason).toContain("노출");
  expect(body.nodes.backtest.status, "짝 — 조절 전 비중의 백테스트는 그대로").toBe("ok");
  await expect(node(page, "x").locator(".pg-node-ev")).toContainText("노출 조절됨");
  await node(page, "x").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-stack")).toHaveCount(2);
  await expect(page.locator(".pg-stack").nth(1).locator(".pg-stack-cash")).toHaveCount(1);
  await expect(page.locator(".pg-exposure-sum")).toContainText("주식 60%");
  await expect(page.locator(".pg-exposure-sum")).toContainText("현금 40%");
  // 새 렌더러의 대비 — 라이트·다크 모두 AA(패널 안만 잰다).
  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.waitForTimeout(150);
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
    expect(audit.checked).toBeGreaterThan(10);
    expect(audit.low, dark ? "dark" : "light").toEqual([]);
  }
});

test("실행·기록(BK W4): 계산은 쓰지 않고 저장은 버튼으로 한 번 · 연습용 데이터 목표는 연구용 · 낡으면 잠김", async ({ page }) => {
  await openCanvas(page);
  const doc = await exportDoc(page);
  doc.nodes.push({ id: "q", type: "order_preview", params: { portfolio_value: 100000000 }, position: { x: 1000, y: 380 } });
  doc.nodes.push({ id: "tv", type: "target_version", params: { note: "E2E" }, position: { x: 1000, y: 520 } });
  doc.nodes.push({ id: "jr", type: "decision_journal", params: { title: "E2E 결정", thesis: "테스트", decision: "hold" }, position: { x: 1220, y: 520 } });
  doc.edges.push({ id: "w1", source: "optimizer", source_port: "weights", target: "q", target_port: "weights" });
  doc.edges.push({ id: "w2", source: "optimizer", source_port: "weights", target: "tv", target_port: "weights" });
  doc.edges.push({ id: "w3", source: "tv", source_port: "target", target: "jr", target_port: "target" });
  doc.edges.push({ id: "w4", source: "q", source_port: "trades", target: "jr", target_port: "trades" });
  await importText(page, "w4.json", JSON.stringify(doc));

  // 저장 전: 계산만으로는 아무것도 쓰지 않는다 — /graph/save 요청이 없어야 한다.
  const saves: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/allocation/graph/save")) saves.push(r.url()); });
  const body = await run(page);
  for (const id of ["q", "tv", "jr"]) expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
  expect(saves).toEqual([]);
  expect(body.nodes.tv.view.target.status, "mock 수익률 → 연습용 계보 → 연구용 목표").toBe("research_only");
  expect(body.nodes.tv.view.target.status_reason).toContain("연습용");

  await node(page, "tv").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-model-type")).toContainText("연구용 목표");
  await tab(page, "settings");
  const save = page.locator(".pg-save-btn");
  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.locator(".pg-save-msg")).toContainText("연구용 실행 목표로 저장했어요");
  expect(saves).toHaveLength(1);

  await node(page, "jr").click();
  await page.locator(".pg-save-btn").click();
  await expect(page.locator(".pg-save-msg")).toContainText("결정을 기록했어요");
  expect(saves).toHaveLength(2);
  // 뒷정리 — E2E DB 는 스펙끼리 공유된다. 남기면 마법사 저널 화면 스펙이 이 항목을 보고 달라진다.
  const entryId = /·\s*(\S+)\s*$/.exec((await page.locator(".pg-save-msg").textContent()) ?? "")?.[1];
  expect(entryId).toBeTruthy();
  expect((await page.request.delete(`http://localhost:8000/api/v1/allocation/journal/${entryId}`)).ok()).toBe(true);

  // 설정을 바꾸면 미리보기가 낡는다 — 다시 계산하기 전에는 저장할 수 없다.
  await node(page, "optimizer").click();
  await page.locator('.pg-basic-field[data-field="model"] .pg-choice', { hasText: "흔들림 최소" }).click();
  await node(page, "tv").click();
  await expect(page.locator(".pg-save-btn")).toBeDisabled();
  await expect(page.locator(".pg-save .pg-help")).toContainText("다시 계산한 뒤");
});

test("기업·가치평가(BK W5): 기업 전망은 비중까지 가고 과거 검증은 막힘 · 가치평가 점수 → 비중", async ({ page }) => {
  await openCanvas(page);
  const doc = await exportDoc(page);
  const old = doc.edges.find((e: { target: string; target_port: string }) => e.target === "optimizer" && e.target_port === "views");
  doc.edges = doc.edges.filter((e: { id: string }) => e !== old);
  doc.nodes.push({ id: "c", type: "company_views", params: {}, position: { x: 600, y: 560 } });
  doc.nodes.push({ id: "s", type: "valuation_scores", params: {}, position: { x: 380, y: 700 } });
  doc.nodes.push({ id: "w", type: "scores_to_weights", params: { top_k: 5 }, position: { x: 620, y: 700 } });
  doc.edges.push({ id: "c1", source: "returns", source_port: "returns", target: "c", target_port: "returns" });
  if (old) doc.edges.push({ id: "c2", source: old.source, source_port: old.source_port, target: "c", target_port: "views" });
  doc.edges.push({ id: "c3", source: "c", source_port: "views", target: "optimizer", target_port: "views" });
  doc.edges.push({ id: "s1", source: "universe", source_port: "universe", target: "s", target_port: "universe" });
  doc.edges.push({ id: "s2", source: "s", source_port: "scores", target: "w", target_port: "scores" });
  await importText(page, "w5.json", JSON.stringify(doc));
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = await (await resp).json();
  expect(body.nodes.c.status, body.nodes.c.reason).toBe("ok");
  expect(body.nodes.optimizer.status).toBe("ok");
  expect(body.nodes.optimizer.view.company_views_used, "회사 뷰는 사용자 뷰와 섞이지 않고 따로 센다").toBe(body.nodes.c.view.views.length);
  expect(body.nodes.optimizer.lineage.pit).toBe("forward_only");
  expect(body.nodes.backtest.status, "지금 시점 전용 전망이 섞인 비중은 과거로 돌리지 않는다").toBe("failed");
  expect(body.nodes.backtest.reason).toContain("지금 시점");
  expect(body.nodes.s.status, body.nodes.s.reason).toBe("ok");
  expect(body.nodes.w.status, body.nodes.w.reason).toBe("ok");
  for (const [code, sc] of Object.entries(body.nodes.s.view.scores as Record<string, number>)) {
    const row = body.nodes.s.view.rows.find((r: { ticker: string }) => r.ticker === code);
    expect(sc, `${code}: 점수 = −괴리율`).toBeCloseTo(-row.gap_pct, 4);
    expect(row.verdict).not.toBe("데이터 없음");
  }

  await node(page, "c").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-model-type")).toContainText("지금 시점에만");
  await node(page, "s").click();
  await expect(page.locator(".pg-side .pg-table tbody tr").first()).toBeVisible();
  await expect(page.locator(".pg-side .pg-note")).toContainText("0으로 치지 않고");
  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.waitForTimeout(150);
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
    expect(audit.checked).toBeGreaterThan(10);
    expect(audit.low, dark ? "dark" : "light").toEqual([]);
  }
});

test("저장된 것에서 고르기(BK W5): 연구 기록을 골라 되짚기 · 등록된 전략이 없으면 무엇을 할지 말한다", async ({ page }) => {
  const api = "http://localhost:8000/api/v1/research-runs";
  const made = await (await page.request.post(api, { data: {
    kind: "analyze", name: "E2E 되짚기", inputs: {},
    outputs: { weights: { optimized: { "005930": 60, "000660": 40 } },
               summary: { portfolio: { expected_return_pct: 8, volatility_pct: 20 } } } } })).json();
  expect(made.recorded, made.message).toBe(true);
  try {
    await openCanvas(page);
    const doc = { ...(await exportDoc(page)), nodes: [
      { id: "a", type: "attribution_review", params: {}, position: { x: 80, y: 80 } },
      { id: "m", type: "strategy_backtest", params: {}, position: { x: 80, y: 280 } }], edges: [] };
    await importText(page, "w5b.json", JSON.stringify(doc));

    await node(page, "m").click();
    await tab(page, "settings");
    await expect(page.locator('.pg-basic-field[data-field="strategy_ids"]')).toContainText("등록된 전략이 없어요");

    await node(page, "a").click();
    const row = page.locator('.pg-basic-field[data-field="run_id"] .pg-pick-row', { hasText: "E2E 되짚기" });
    await expect(row).toBeVisible();
    await expect(row).toHaveAttribute("aria-checked", "false");
    await row.click();
    await expect(row).toHaveAttribute("aria-checked", "true");
    const exported = await exportDoc(page);
    expect(exported.nodes.find((n: { id: string }) => n.id === "a").params.run_id, "고른 값이 파라미터가 된다").toBe(made.run_id);

    // 전략 노드는 아직 비어 있다 — 그래프에서 빼고 되짚기만 계산한다.
    await importText(page, "w5c.json", JSON.stringify({ ...exported, nodes: exported.nodes.filter((n: { id: string }) => n.id === "a") }));
    const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
    await page.locator(".pg-run").click();
    const body = await (await resp).json();
    expect(body.nodes.a.status, body.nodes.a.reason).toBe("ok");
    expect(body.nodes.a.view.run_id).toBe(made.run_id);
    await node(page, "a").click();
    await tab(page, "detail");
    await expect(page.locator(".pg-side .pg-chips-static")).toContainText("종목 선택");
    await tab(page, "story");
    await expect(page.locator(".pg-side")).toContainText("되짚");
  } finally {
    await page.request.delete(`${api}/${made.run_id}`);
  }
});
