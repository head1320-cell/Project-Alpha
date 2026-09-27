import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { contrastAudit, trackErrors, uniq, type AuditResult } from "./helpers";
import { TEMPLATES } from "../src/entities/portfolio-graph/templates";
import { WIZARD_NODE_MAP } from "../src/app/allocation/wizardNodeMap";

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

test("정리(BK W6): 템플릿 다섯이 서버 검증을 통과하고 돈다 · 단계 접기 · 마법사 화면 이름으로 찾기", async ({ page }) => {
  await openCanvas(page);
  const catalog = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  const types = new Set(catalog.nodes.map((c: { type: string }) => c.type));
  // 대응표의 모든 노드 종류가 카탈로그에 실제로 있다 — 이름만 적힌 대응은 없다.
  for (const [href, kinds] of Object.entries(WIZARD_NODE_MAP)) {
    for (const k of kinds) expect(types.has(k), `${href} → ${k}`).toBe(true);
  }

  await expect(page.locator(".pg-template")).toHaveCount(TEMPLATES.length);
  for (const t of TEMPLATES) {
    await page.locator(`.pg-template[data-template="${t.key}"]`).click();
    await expect(page.locator(".pg-node")).toHaveCount(t.doc.nodes.length);
    const doc = await exportDoc(page);
    const v = await (await page.request.post("http://localhost:8000/api/v1/allocation/graph/validate", { data: doc })).json();
    expect(v.errors, `${t.key}: ${JSON.stringify(v.errors)}`).toEqual([]);
    if (t.key === "stress" || t.key === "screener" || t.key === "risk") {
      const body = await run(page);
      for (const [id, r] of Object.entries(body.nodes as Record<string, { status: string; reason: string }>)) {
        expect(r.status, `${t.key}.${id}: ${r.reason}`).toBe("ok");
      }
    }
  }

  // 단계 접기 — 개수는 그대로 보이고, 항목은 숨는다. 찾는 중에는 늘 펼친다.
  const check = page.locator('.pg-palette-group[data-stage="check"]');
  const toggle = check.locator(".pg-palette-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const n = await check.locator(".pg-palette-item").count();
  await expect(check.locator(".pg-palette-count")).toHaveText(String(n));
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(check.locator(".pg-palette-item").first()).toBeHidden();

  // 마법사 화면 이름으로 찾는다 — "THESIS" 는 어느 노드의 이름·설명·종류에도 없고 대응표로만 닿는다.
  await page.getByLabel("노드 찾기").fill("THESIS");
  await expect(page.locator('.pg-palette-item[data-kind="company_views"]')).toBeVisible();
  await expect(page.locator('.pg-palette-item[data-kind="views"]')).toBeVisible();
  await expect(page.locator('.pg-palette-item[data-kind="screener"]')).toBeHidden();
  await expect(check.locator(".pg-palette-count")).toHaveCount(0);   // 맞는 것이 없는 단계는 숨는다
});

// ─────────────────────────────────────────────────────────────────────────────
// BL1 — 노드 링크 UI 고도화 (조사: n8n Execute step · KNIME 메타노드 · React Flow 편집 도구)
// ─────────────────────────────────────────────────────────────────────────────
const mod = process.platform === "darwin" ? "Meta" : "Control";

test("여기까지 계산(BL1): 올리면 돌 경로가 밝아지고, 누르면 조상만 계산 · 나머지는 이전 계산으로 표시", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  const btn = page.locator(".pg-run-to");
  await btn.hover();
  for (const id of ["universe", "returns", "estimate", "views", "optimizer"]) {
    await expect(page.locator(`.react-flow__node[data-id="${id}"]`), id).toHaveClass(/pg-on-path/);
  }
  await expect(page.locator('.react-flow__node[data-id="backtest"]'), "짝 — 하류는 밝히지 않는다").not.toHaveClass(/pg-on-path/);
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"));
  await btn.click();
  const r = await resp;
  expect(r.url()).toContain("targets=optimizer");
  const body = await r.json();
  expect(Object.keys(body.nodes).sort()).toEqual(["estimate", "optimizer", "returns", "universe", "views"]);
  expect(body.gates).toBeNull();
  await expect(page.locator(".pg-summary--partial")).toContainText("여기까지 계산 · 5개");
  await expect(page.locator(".pg-rail-summary")).toContainText("전체를 계산할 때");

  // 전체 계산 뒤 한 곳만 다시 계산하면, 계산하지 않은 노드는 이전 결과로 남되 그렇다고 말한다.
  await run(page);
  await node(page, "risk").click();
  await page.keyboard.press("Shift+Enter");
  await expect(page.locator(".pg-summary--partial")).toBeVisible();
  await expect(node(page, "backtest")).toHaveClass(/pg-node--previous/);
  await expect(node(page, "backtest")).toContainText("이전 계산 결과예요");
  await expect(node(page, "risk"), "짝 — 이번에 계산한 노드는 이전 표시가 없다").not.toHaveClass(/pg-node--previous/);
});

test("편집 도구(BL1): 되돌리기·다시하기 · 복사·붙여넣기(링크는 고른 것끼리) · 자동 정리", async ({ page }) => {
  await openCanvas(page);
  const count = () => page.locator(".pg-node").count();
  const n0 = await count();
  await node(page, "risk").click();
  await page.keyboard.press("Delete");
  await expect(page.locator(".pg-node")).toHaveCount(n0 - 1);
  await page.keyboard.press(`${mod}+z`);
  await expect(page.locator(".pg-node")).toHaveCount(n0);
  await page.keyboard.press(`${mod}+Shift+z`);
  await expect(page.locator(".pg-node")).toHaveCount(n0 - 1);
  await page.keyboard.press(`${mod}+z`);

  // 두 노드(종목 고르기 → 수익률 불러오기)를 함께 골라 복사 → 붙이면 둘과 그 사이 링크 하나만 따라온다.
  await node(page, "universe").click();
  await node(page, "returns").click({ modifiers: [mod === "Meta" ? "Meta" : "Control"] });
  await expect(page.locator(".pg-hint")).toContainText("2개 골랐어요");
  const before = await exportDoc(page);
  await page.keyboard.press(`${mod}+c`);
  await page.keyboard.press(`${mod}+v`);
  await expect(page.locator(".pg-node")).toHaveCount(n0 + 2);
  const after = await exportDoc(page);
  const fresh = after.nodes.filter((n: { id: string }) => !before.nodes.some((b: { id: string }) => b.id === n.id));
  expect(fresh.map((n: { type: string }) => n.type).sort()).toEqual(["returns", "universe"]);
  const freshIds = new Set(fresh.map((n: { id: string }) => n.id));
  const newEdges = after.edges.filter((e: { id: string }) => !before.edges.some((b: { id: string }) => b.id === e.id));
  expect(newEdges).toHaveLength(1);
  expect(freshIds.has(newEdges[0].source) && freshIds.has(newEdges[0].target)).toBe(true);

  // 자동 정리 — 흐름 순서가 왼쪽 → 오른쪽. ★먼저 뒤집어 놓는다★ 기본 템플릿은 이미 정리돼 있어 그대로 두면
  // 정리 버튼이 아무것도 안 해도 통과한다(변이 D 가 실제로 살아남았다).
  const messy = await exportDoc(page);
  messy.nodes = messy.nodes.map((n: { position: { x: number; y: number } }) => ({ ...n, position: { x: -n.position.x, y: n.position.y } }));
  await importText(page, "messy.json", JSON.stringify(messy));
  const before2 = await exportDoc(page);
  const bx = (id: string) => before2.nodes.find((n: { id: string }) => n.id === id).position.x;
  expect(bx("universe"), "뒤집힌 상태에서 출발").toBeGreaterThan(bx("backtest"));
  await page.getByRole("button", { name: "자동 정리" }).click();
  const laid = await exportDoc(page);
  const x = (id: string) => laid.nodes.find((n: { id: string }) => n.id === id).position.x;
  expect(x("universe")).toBeLessThan(x("returns"));
  expect(x("returns")).toBeLessThan(x("optimizer"));
  expect(x("optimizer")).toBeLessThan(x("backtest"));
});

test("묶음 상자(BL1): 고른 노드를 묶고 접으면 숨고 요약만 · 파일에 남고 다시 불러와도 그대로", async ({ page }) => {
  await openCanvas(page);
  await node(page, "risk").click();
  await node(page, "backtest").click({ modifiers: [mod === "Meta" ? "Meta" : "Control"] });
  await page.keyboard.press(`${mod}+g`);
  const frame = page.locator(".pg-group");
  await expect(frame).toHaveCount(1);
  await expect(frame).toContainText("노드 2개");
  await frame.getByLabel("묶음 이름").fill("확인 묶음");
  await frame.getByRole("button", { name: "묶음 접기" }).click();
  await expect(node(page, "risk")).toBeHidden();
  await expect(frame).toHaveClass(/pg-group--collapsed/);
  const doc = await exportDoc(page);
  expect(doc.groups).toEqual([expect.objectContaining({ label: "확인 묶음", members: ["risk", "backtest"], collapsed: true })]);
  // 접어도 계산은 그대로 — 서버로 가는 그래프에는 묶음이 없다.
  const body = await run(page);
  expect(body.nodes.risk.status).toBe("ok");
  await importText(page, "grouped.json", JSON.stringify(doc));
  await expect(page.locator(".pg-group").getByLabel("묶음 이름"), "이름은 입력칸 값이다").toHaveValue("확인 묶음");
  await page.locator(".pg-group").getByRole("button", { name: "묶음 펼치기" }).click();
  await expect(node(page, "risk")).toBeVisible();
});

test("명령 팔레트·계산 기록(BL1): Ctrl+K 로 노드 추가 · 두 번 계산하면 노드별 기록 두 줄 · 대비 AA", async ({ page }) => {
  await openCanvas(page);
  await page.keyboard.press(`${mod}+k`);
  const dlg = page.getByRole("dialog", { name: "명령 찾기" });
  await expect(dlg).toBeVisible();
  await dlg.getByLabel("명령 찾기").fill("상관이");
  await expect(dlg.locator(".pg-cmd-item").first()).toContainText("상관이 치솟으면 추가");
  await page.keyboard.press("Enter");
  await expect(dlg).toBeHidden();
  await expect(page.locator('.pg-node[data-kind="corr_stress"]')).toHaveCount(1);
  await page.keyboard.press(`${mod}+z`);
  await expect(page.locator('.pg-node[data-kind="corr_stress"]')).toHaveCount(0);

  await run(page);
  await run(page);
  await node(page, "optimizer").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-history tbody tr")).toHaveCount(2);
  await expect(page.locator(".pg-history tbody tr").first(), "가장 최근 줄이 앞 계산과 비교한다").toContainText("같음");

  // 대비 — 기록 표는 팔레트를 닫은 채로, 팔레트는 연 채로(열면 뒤는 가림막 아래라 재지 않는다).
  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.waitForTimeout(150);
    for (const scope of [".pg-side", ".pg-cmd"]) {
      if (scope === ".pg-cmd") await page.keyboard.press(`${mod}+k`);
      const audit = await page.evaluate<AuditResult>(contrastAudit(scope));
      expect(audit.checked, scope).toBeGreaterThan(5);
      expect(audit.low, `${scope} ${dark ? "dark" : "light"}`).toEqual([]);
      if (scope === ".pg-cmd") await page.keyboard.press("Escape");
    }
  }
});

// ── BL2 · 마법사에만 있던 기능을 캔버스로 ─────────────────────────────────────
const API = "http://localhost:8000/api/v1";
const sheet = (page: Page, k: "execution" | "records" | "alphas") => page.locator(`dialog.pg-sheet[data-sheet="${k}"]`);
const openSheet = (page: Page, label: string) => page.locator(".pg-drawers .pg-drawer-open", { hasText: label }).click();

test("실행실 서랍(BL2): 저장된 실행 목표에서만 계획 · 연구용 목표는 고를 수 없다 · 사전 점검 · 상태 전이", async ({ page }) => {
  const sink = trackErrors(page);
  // 실행 가능한 목표 하나(연습용 계보가 붙지 않은 API 경로)와 연구용 목표 하나를 심는다.
  const ok = await (await page.request.post(`${API}/allocation/target-versions`, {
    data: { base_weights: { "005930": 40, "000660": 35, "035420": 25 }, note: "E2E BL2 실행 가능" } })).json();
  expect(ok.saved, ok.message).toBe(true);
  expect(ok.status).toBe("executable");
  await openCanvas(page);
  await openSheet(page, "실행실");
  const s = sheet(page, "execution");
  await expect(s).toBeVisible();
  await s.getByRole("tab", { name: "새 계획 만들기" }).click();
  const row = s.locator(`.pg-pick-row[data-tpv="${ok.tpv_id}"]`);
  await expect(row).toBeEnabled();
  // ★짝★ 연구용 목표는 목록에 있되 고를 수 없고 사유가 보인다(있을 때).
  const research = s.locator(".pg-pick-row:disabled");
  if (await research.count()) await expect(research.first()).toContainText("연구용");
  await row.click();
  await s.getByRole("button", { name: "주문 목록 미리 보기" }).click();
  await expect(s.locator(".pg-kv")).toContainText("주문");
  await expect(s.locator(".pg-checks li").first()).toBeVisible();
  await expect(s.locator(".pg-note", { hasText: "현금에서 시작" })).toBeVisible();
  await s.getByRole("textbox", { name: "계획 이름" }).fill("E2E BL2 계획");
  const saved = page.waitForResponse((r) => r.url().includes("/execution-plan/save"));
  await s.getByRole("button", { name: "계획 저장" }).click();
  const sb = await (await saved).json();
  expect(sb.saved, sb.reason ?? sb.message).toBe(true);
  // 저장하면 목록으로 돌아가 그 계획이 열린다 — 초안에서 검토로.
  const flow = s.locator(`[data-plan="${sb.plan_id}"]`);
  await expect(flow).toContainText("초안");
  await flow.locator('button[data-to="reviewed"]').click();
  await expect(flow.locator(".pg-save-msg")).toContainText("검토됨");
  // 사전 점검이 막았다면 승인 버튼이 잠기고 사유가 보인다(짝: 막히지 않았다면 열려 있다).
  const approve = flow.locator('button[data-to="approved"]');
  if (sb.pretrade.can_approve) await expect(approve).toBeEnabled();
  else { await expect(approve).toBeDisabled(); await expect(flow.locator(".pg-warn")).toContainText("승인할 수 없어요"); }
  await expect(flow.locator(".pg-note")).toContainText("실제 주문은 나가지 않아요");
  // Esc 로 닫힌다.
  await page.keyboard.press("Escape");
  await expect(s).toBeHidden();
  // 뒷정리 — E2E DB 는 스펙끼리 공유된다(마법사 실행실 스펙이 목록을 센다).
  expect((await page.request.delete(`${API}/allocation/execution-plan/${sb.plan_id}`)).ok()).toBe(true);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("실행실 서랍(BL2): 서버가 막은 목표는 계획을 만들지 않고 사유를 그대로 보인다", async ({ page }) => {
  await openCanvas(page);
  // 목록을 가로채 연구용 목표를 '실행 가능' 으로 속여 보인다 — 그래도 서버의 R0 차단선이 막아야 한다.
  const fake = await (await page.request.post(`${API}/allocation/target-versions`, {
    data: { base_weights: { "005930": 60, "000660": 40 }, note: "E2E BL2 차단", dry_run: true } })).json();
  await page.route(/\/allocation\/target-versions\?/, (r) => r.request().method() === "GET"
    ? r.fulfill({ json: { available: true, versions: [{ ...fake, tpv_id: "tpv_missing_e2e", status: "executable", created_at: 0 }] } })
    : r.continue());
  await openSheet(page, "실행실");
  const s = sheet(page, "execution");
  await s.getByRole("tab", { name: "새 계획 만들기" }).click();
  await s.locator('.pg-pick-row[data-tpv="tpv_missing_e2e"]').click();
  await s.getByRole("button", { name: "주문 목록 미리 보기" }).click();
  await expect(s.locator(".pg-warn")).toContainText("목표 버전을 찾을 수 없습니다");
  await expect(s.getByRole("button", { name: "계획 저장" })).toHaveCount(0);
});

test("기록함 서랍(BL2): 판단 기록 회고 쓰기·지우기 · 연구 기록 대조 · 스냅샷 · 못 읽음 ≠ 없음", async ({ page }) => {
  const j = await (await page.request.post(`${API}/allocation/journal`, {
    data: { title: "E2E BL2 판단", record: { decision: "비중을 유지" } } })).json();
  expect(j.saved).toBe(true);
  await openCanvas(page);
  await openSheet(page, "기록함");
  const s = sheet(page, "records");
  const item = s.locator(`[data-entry="${j.entry_id}"]`);
  await expect(item).toContainText("E2E BL2 판단");
  await expect(item).toContainText("연구 기록과 이어지지 않았어요");
  await item.getByRole("button", { name: "회고 쓰기" }).click();
  await item.getByRole("textbox").fill("석 달 뒤 확인");
  await item.locator("select").selectOption("too_early");
  await item.getByRole("button", { name: "회고 저장" }).click();
  await expect(item).toContainText("회고: 석 달 뒤 확인");
  await expect(item).toContainText("판단하기 일러요");
  page.once("dialog", (d) => d.accept());
  await item.getByRole("button", { name: "E2E BL2 판단 삭제" }).click();
  await expect(item).toHaveCount(0);

  await s.getByRole("tab", { name: "국면 스냅샷" }).click();
  await expect(s.locator(".pg-note", { hasText: "과거 백테스트에는 쓸 수 없어요" })).toBeVisible();

  // ★못 읽은 것과 없는 것은 다른 문장★ — 목록 요청을 실패시키면 '없어요' 가 아니라 '불러오지 못했어요'.
  await page.route("**/research-runs?**", (r) => r.fulfill({ status: 500, body: "x" }));
  await s.getByRole("tab", { name: "연구 기록" }).click();
  await expect(s.locator(".pg-field-err")).toContainText("불러오지 못했어요");
  await expect(s.locator(".pg-help", { hasText: "연구 기록이 없어요" })).toHaveCount(0);
});

test("알파 목록 서랍(BL2): 식 점검 → 초안 등록 → 실험으로 올리기 · 검증 단계는 검증 기록 없이 거절 · 지우기", async ({ page }) => {
  await openCanvas(page);
  await openSheet(page, "알파");
  const s = sheet(page, "alphas");
  await s.locator(".pg-rec-add summary").click();
  await s.getByLabel("이름").fill("E2E BL2 알파");
  await s.getByLabel("식").fill("zscore(roe) - zscore(debt_ratio)");
  await s.getByRole("button", { name: "식 점검" }).click();
  await expect(s.locator(".pg-rec-add [role=status]")).toBeVisible();
  const created = page.waitForResponse((r) => r.url().endsWith("/alpha-registry") && r.request().method() === "POST");
  await s.getByRole("button", { name: "초안으로 등록" }).click();
  const a = (await (await created).json()).alpha;
  const row = s.locator(`[data-alpha="${a.alpha_id}"]`);
  await expect(row).toContainText("초안");
  await row.getByRole("button", { name: /실험.*올리기/ }).click();
  await row.getByRole("button", { name: "올리기", exact: true }).click();
  await expect(row).toContainText("실험");
  // ★짝★ 서버 요건: 검증 기록(run) 없이는 검증 단계로 못 올린다 — 사유를 그대로.
  await row.getByRole("button", { name: /검증 단계.*올리기/ }).click();
  await row.getByRole("button", { name: "올리기", exact: true }).click();
  await expect(row.locator(".pg-warn")).toContainText("검증");
  await expect(row.locator(".pg-rec-row .pg-tag").last()).toContainText("실험");
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: "E2E BL2 알파 삭제" }).click();
  await expect(row).toHaveCount(0);
});

test("저장 버튼(BL2): 비중 계산은 '연구 기록 남기기' · 기록함에서 그 기록을 다시 계산해 대조", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await node(page, "optimizer").click();
  await tab(page, "settings");
  const btn = page.locator(".pg-save-btn");
  await expect(btn).toHaveText("연구 기록 남기기");
  await btn.click();
  const msg = page.locator(".pg-save-msg");
  await expect(msg).toContainText("연구 기록으로 남겼어요");
  const rid = /·\s*(\S+)\s*$/.exec((await msg.textContent()) ?? "")?.[1];
  expect(rid).toBeTruthy();
  await openSheet(page, "기록함");
  const s = sheet(page, "records");
  await s.getByRole("tab", { name: "연구 기록" }).click();
  const item = s.locator(`[data-run="${rid}"]`);
  await item.getByRole("button", { name: "다시 계산해 대조" }).click();
  await expect(item.locator(".pg-rec-verdict, .pg-warn")).toBeVisible({ timeout: 60_000 });
  page.once("dialog", (d) => d.accept());
  await item.getByRole("button", { name: `${rid} 삭제` }).click();
  await expect(item).toHaveCount(0);
});

test("서랍 대비(BL2): 세 서랍 라이트·다크 AA", async ({ page }) => {
  await openCanvas(page);
  for (const [label, k] of [["실행실", "execution"], ["기록함", "records"], ["알파", "alphas"]] as const) {
    for (const scheme of ["light", "dark"] as const) {
      await page.evaluate((d) => document.documentElement.classList.toggle("dark", d), scheme === "dark");
      await openSheet(page, label);
      await expect(sheet(page, k)).toBeVisible();
      await page.waitForTimeout(400);
      const audit = await page.evaluate<AuditResult>(contrastAudit(`dialog.pg-sheet[data-sheet="${k}"]`));
      expect(audit.checked, `${label}: 검사한 텍스트 수`).toBeGreaterThan(4);
      expect(audit.low, `${label} ${scheme} AA 미달`).toEqual([]);
      if (scheme === "dark") expect(audit.bright, `${label} 다크인데 밝은 배경`).toEqual([]);
      await page.keyboard.press("Escape");
    }
  }
});

// ── BL2b · 마법사에서 옮긴 계산 노드 · 매크로 스냅샷 다리 ────────────────────
test("새 계산 노드(BL2b): 프런티어·국면 앙상블·세 갈래·직접 만든 시나리오·묶음 분석이 돌고 결과가 그림으로 · 대비 AA", async ({ page }) => {
  const sink = trackErrors(page);
  await openCanvas(page);
  const doc = await exportDoc(page);
  const rules = [{ factor_id: "abs_mom" }, { factor_id: "ma_month" }];
  doc.nodes.push(
    { id: "fr", type: "frontier", params: {}, position: { x: 1000, y: 0 } },
    { id: "en", type: "regime_ensemble", params: { market: "kr" }, position: { x: 1000, y: 160 } },
    { id: "tm", type: "timing_signal", params: { rules }, position: { x: 800, y: 480 } },
    { id: "tw", type: "scenario_three_way", params: { scenario: "rate_hike_200bp" }, position: { x: 1000, y: 480 } },
    { id: "cs", type: "custom_scenario", params: { market_shock: -8, momentum: -3 }, position: { x: 1000, y: 640 } },
    { id: "o2", type: "optimizer", params: { model: "hrp" }, position: { x: 800, y: 320 } },
    { id: "sa", type: "sleeve_analytics", params: {}, position: { x: 1000, y: 320 } },
  );
  doc.edges.push(
    { id: "b1", source: "returns", source_port: "returns", target: "fr", target_port: "returns" },
    { id: "b2", source: "optimizer", source_port: "weights", target: "fr", target_port: "weights" },
    { id: "b3", source: "optimizer", source_port: "weights", target: "tw", target_port: "weights" },
    { id: "b4", source: "tm", source_port: "signal", target: "tw", target_port: "signal" },
    { id: "b5", source: "optimizer", source_port: "weights", target: "cs", target_port: "weights" },
    { id: "b6", source: "returns", source_port: "returns", target: "o2", target_port: "returns" },
    { id: "b7", source: "estimate", source_port: "belief", target: "o2", target_port: "belief" },
    { id: "b8", source: "optimizer", source_port: "weights", target: "sa", target_port: "a" },
    { id: "b9", source: "o2", source_port: "weights", target: "sa", target_port: "b" },
  );
  await importText(page, "bl2b.json", JSON.stringify(doc));
  const body = await run(page);
  for (const id of ["fr", "en", "tw", "cs", "sa"]) expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
  // 개발 모드의 국면은 연습용 계보다(운영은 저장된 관측만 — 백엔드 테스트가 가른다).
  expect(body.nodes.en.lineage.practice).toBe(true);

  for (const [id, sel] of [["fr", ".pg-frontier"], ["en", ".pg-ensemble"], ["tw", ".pg-threeway"], ["cs", ".pg-shock"], ["sa", ".pg-corr"]] as const) {
    await node(page, id).click();
    await tab(page, "detail");
    await expect(page.locator(`.pg-side ${sel}`), id).toBeVisible();
  }
  // ★구름과 곡선은 같은 단위(%)★ — 한쪽만 100배면 곡선이 축 끝에 눌려 안 보인다(실측으로 잡은 결함).
  await node(page, "fr").click();
  const ticks = await page.locator(".pg-frontier .recharts-xAxis .recharts-cartesian-axis-tick-value").allTextContents();
  const xs = ticks.map((t) => parseFloat(t)).filter((x) => Number.isFinite(x));
  expect(xs.length).toBeGreaterThan(2);
  expect(Math.max(...xs), `x축 눈금 ${ticks.join(",")}`).toBeLessThan(300);
  await node(page, "en").click();
  await expect(page.locator(".pg-ensemble thead th")).toHaveCount(4);          // 국면 + 세 방법
  await expect(page.locator(".pg-ensemble tbody tr")).toHaveCount(4);          // 네 국면
  await node(page, "tw").click();
  await expect(page.locator(".pg-threeway tbody tr")).toHaveCount(3);
  // 국면을 잇지 않았으니 '타이밍 + 국면' 갈래는 손실을 적지 않는다(0 으로 채우지 않는다).
  await expect(page.locator(".pg-threeway tbody tr").nth(2)).toContainText("미계산");
  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    await node(page, "fr").click();
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
    expect(audit.checked).toBeGreaterThan(10);
    expect(audit.low, dark ? "dark" : "light").toEqual([]);
  }
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("매크로 다리(BL2b): ?snapshot= 으로 열면 국면 노드가 그 스냅샷을 쓰고 케이스 바가 보인다 · 없는 스냅샷은 사유", async ({ page }) => {
  const snap = await (await page.request.post(`${API}/regime-snapshots/from-current?market=kr`)).json();
  expect(snap.recorded, snap.message).toBe(true);
  await page.goto(`/allocation?snapshot=${snap.snapshot_id}`, { waitUntil: "domcontentloaded" });
  await expect(node(page, "regime")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".pg-file-note")).toContainText(snap.snapshot_id);
  await page.locator(".pg-casebox > summary").click();
  await expect(page.locator(".pg-casebox .as-case")).toBeVisible();
  const body = await run(page);
  expect(body.nodes.regime.status, body.nodes.regime.reason).toBe("ok");
  expect(body.nodes.regime.view.snapshot_id).toBe(snap.snapshot_id);
  // 노출 조절은 국면을 받았다 — 막히지 않았다(이 환경은 타이밍 신호 데이터가 없어 정직하게 실패할 수 있다).
  expect(body.nodes.overlay.status, body.nodes.overlay.reason).not.toBe("blocked");
  // 짝: 없는 스냅샷이면 국면 노드가 사유와 함께 실패하고 하류는 막힌다(다른 스냅샷으로 바꿔치지 않는다).
  await page.goto("/allocation?snapshot=rgs_0_missing", { waitUntil: "domcontentloaded" });
  await expect(node(page, "regime")).toBeVisible({ timeout: 30_000 });
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const bad = await (await resp).json();
  expect(bad.nodes.regime.status).toBe("failed");
  expect(bad.nodes.regime.reason).toContain("rgs_0_missing");
  expect(bad.nodes.overlay.status).toBe("blocked");
});

test("알파 검증 → 알파 서랍(BL2b): 검증 기록 전엔 '검증 단계'로 못 올리고, 기록을 남기면 올라간다", async ({ page }) => {
  const up = await (await page.request.post(`${API}/alpha-registry`, {
    data: { name: "E2E BL2b 알파", expr: "zscore(mom_6m) - zscore(vol_60d)" } })).json();
  const aid = up.alpha.alpha_id as string;
  expect((await (await page.request.post(`${API}/alpha-registry/${aid}/promote`, { data: { to_status: "experimental" } })).json()).ok).toBe(true);
  await openCanvas(page);
  // 짝(먼저): 기록 없이 올리면 서버가 사유와 함께 거절한다.
  await openSheet(page, "알파");
  const row = sheet(page, "alphas").locator(`[data-alpha="${aid}"]`);
  await row.getByRole("button", { name: /검증 단계.*올리기/ }).click();
  await row.getByRole("button", { name: "올리기", exact: true }).click();
  await expect(row.locator(".pg-warn")).toContainText("검증");
  await page.keyboard.press("Escape");

  const doc = await exportDoc(page);
  doc.nodes.push({ id: "av", type: "alpha_validate", params: { alpha_id: aid, universe: "kospi50", months: 12 }, position: { x: 1000, y: 0 } });
  await importText(page, "av.json", JSON.stringify(doc));
  const body = await run(page);
  expect(body.nodes.av.status, body.nodes.av.reason).toBe("ok");
  await node(page, "av").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-kv")).toContainText("평균 IC");
  await tab(page, "settings");
  await expect(page.locator(".pg-save-btn")).toHaveText("검증 기록 남기기");
  await page.locator(".pg-save-btn").click();
  await expect(page.locator(".pg-save-msg")).toContainText("알파에 붙였어요");
  const rid = /·\s*(\S+)\s*·/.exec((await page.locator(".pg-save-msg").textContent()) ?? "")?.[1];

  await openSheet(page, "알파");
  await expect(row).toContainText("검증 기록");
  await row.getByRole("button", { name: /검증 단계.*올리기/ }).click();
  await row.getByRole("button", { name: "올리기", exact: true }).click();
  await expect(row.locator(".pg-rec-row .pg-tag").last()).toContainText("검증 단계");
  // 뒷정리 — E2E DB 는 스펙끼리 공유된다.
  expect((await page.request.delete(`${API}/alpha-registry/${aid}`)).ok()).toBe(true);
  if (rid) await page.request.delete(`${API}/research-runs/${rid}`);
});

// ── BL3 W1 · 백테스트 웨이브 — 시작은 버튼, 읽기는 노드 ─────────────────────
test("백테스트(BL3 W1): 설정 계산은 아무것도 시작하지 않고 · '백테스트 시작' 한 번 → 불러오기 노드 → 진행 카드 → 결과·라벨 → 귀인·비교", async ({ page }) => {
  test.setTimeout(240_000);
  const sink = trackErrors(page);
  await openCanvas(page);
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: { name: "BL3 W1" }, edges: [],
    nodes: [{ id: "bs", type: "backtest_setup", position: { x: 0, y: 0 },
              params: { universe: "kospi50", strategy_name: "GoldenCross", start_date: "2021-01-01", end_date: "2024-12-31", max_tickers: 3, max_positions: 3 } }] };
  await importText(page, "bl3.json", JSON.stringify(doc));
  const starts: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/v1/backtest/runs") && r.method() === "POST") starts.push(r.url()); });
  const body = await run(page);
  expect(body.nodes.bs.status, body.nodes.bs.reason).toBe("ok");
  expect(starts, "계산은 백테스트를 시작하지 않는다").toEqual([]);

  await node(page, "bs").click();
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-kv")).toContainText("골든크로스");
  await tab(page, "settings");
  await expect(page.locator(".pg-save-btn")).toHaveText("백테스트 시작");
  const saved = page.waitForResponse((r) => r.url().includes("/allocation/graph/save"));
  await page.locator(".pg-save-btn").click();
  const sv = await (await saved).json();
  expect(sv.ok, sv.message).toBe(true);
  await expect(page.locator(".pg-save-msg")).toContainText("백테스트를 시작했어요");
  await page.locator(".pg-save-follow").click();                               // 결과 불러오기 노드 추가
  const loader = page.locator(".pg-node").filter({ hasText: "백테스트 결과 보기" });
  await expect(loader).toHaveCount(1);

  // 계산 — 아직이면 진행 카드가 뜨고, 끝나면 '결과 불러오기' 가 밝아진다(읽기만 한다).
  await page.locator(".pg-run").click();
  await tab(page, "detail");
  const prog = page.locator(".pg-runprog");
  const done = page.locator(".pg-kv", { hasText: "총수익" });
  await expect(prog.or(done)).toBeVisible({ timeout: 60_000 });
  if (await prog.isVisible()) {
    await expect(prog.getByRole("button", { name: "결과 불러오기" })).toBeEnabled({ timeout: 180_000 });
    await prog.getByRole("button", { name: "결과 불러오기" }).click();
  }
  await expect(done).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".pg-side .pg-perf")).toBeVisible();                 // 성과 숫자 옆에 무슨 성과인지

  // 귀인 · 비교(같은 실행 둘 — 조건이 같으니 경고가 없다)
  const cur = await exportDoc(page);
  const lid = cur.nodes.find((n: { type: string }) => n.type === "backtest_load").id as string;
  const rid = cur.nodes.find((n: { type: string }) => n.type === "backtest_load").params.run_id as string;
  cur.nodes.push({ id: "ba", type: "backtest_attribution", params: {}, position: { x: 520, y: 0 } },
                 { id: "l2", type: "backtest_load", params: { run_id: rid }, position: { x: 240, y: 200 } },
                 { id: "bc", type: "backtest_compare", params: {}, position: { x: 520, y: 200 } });
  cur.edges.push({ id: "e1", source: lid, source_port: "run", target: "ba", target_port: "run" },
                 { id: "e2", source: lid, source_port: "run", target: "bc", target_port: "a" },
                 { id: "e3", source: "l2", source_port: "run", target: "bc", target_port: "b" });
  await importText(page, "bl3b.json", JSON.stringify(cur));
  const b2 = await run(page);
  expect(b2.nodes.bc.status, b2.nodes.bc.reason).toBe("ok");
  expect(b2.nodes.bc.view.differences).toEqual([]);
  expect(["ok", "failed"]).toContain(b2.nodes.ba.status);
  if (b2.nodes.ba.status === "ok") {
    await node(page, "ba").click();
    await expect(page.locator(".pg-side .pg-attr")).toBeVisible();
  } else {
    expect(b2.nodes.ba.reason, "귀인을 못 하면 사유가 있다").toContain("귀인");
  }
  await node(page, "bc").click();
  await expect(page.locator(".pg-side .pg-cmp tbody tr")).toHaveCount(7);
  await expect(page.locator(".pg-side .pg-cmp-warn")).toHaveCount(0);
  expect(starts, "백테스트 시작은 버튼 한 번뿐").toHaveLength(0);                // 저장 문(/graph/save)이 시작했다 — /backtest/runs POST 는 없다
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

test("진행 카드(BL3 W1): 아직이면 상태를 읽기만 하며 기다리고, 끝나면 '결과 불러오기'가 밝아진다 · 대비 AA", async ({ page }) => {
  await openCanvas(page);
  // 끝난 실행 하나를 만든다(버튼 경로와 같은 라우트) — 화면이 '아직' 을 받도록 응답만 바꾼다.
  const created = await (await page.request.post(`${API}/backtest/runs`, { data: { strategy_name: "E2E 진행 카드",
    config: { universe: "kospi50", filter_ast: { logic: "AND", conditions: [], groups: [] }, strategy_name: "GoldenCross",
              start_date: "2023-01-01", end_date: "2023-12-31", max_tickers: 2, max_positions: 2 } } })).json();
  const rid = created.run_id as string;
  const doc = { format: "project-alpha.portfolio-graph", version: 1, meta: {}, edges: [],
    nodes: [{ id: "lo", type: "backtest_load", params: { run_id: rid }, position: { x: 0, y: 0 } }] };
  await importText(page, "prog.json", JSON.stringify(doc));
  let step = 0;
  await page.route(/\/backtest\/runs\/[^/]+\/status/, (r) => r.fulfill({ json: step === 0
    ? { run_id: rid, status: "simulating", progress_percent: 45, current_stage: "simulating", status_message: "", strategy_name: "E2E",
        created_at: 0, started_at: 0, completed_at: null, error_code: null, error_message: null, correlation_id: null,
        is_mock_data: true, is_pit_verified: null, engine_version: null }
    : { run_id: rid, status: "completed", progress_percent: 100, current_stage: "completed", status_message: "", strategy_name: "E2E",
        created_at: 0, started_at: 0, completed_at: 1, error_code: null, error_message: null, correlation_id: null,
        is_mock_data: true, is_pit_verified: null, engine_version: null } }));
  await page.route("**/allocation/graph/run**", async (route) => {
    const resp = await route.fetch();
    const j = await resp.json();
    j.nodes.lo = { ...j.nodes.lo, status: "failed", view: null, reason: "아직 끝나지 않았어요 — 45% · 시뮬레이션. 끝나면 다시 계산해 주세요." };
    await route.fulfill({ response: resp, json: j });
  });
  await page.locator(".pg-run").click();
  await node(page, "lo").click();
  await tab(page, "detail");
  const card = page.locator(".pg-runprog");
  await expect(card).toContainText("45%");
  await expect(card.getByRole("button", { name: "결과 불러오기" })).toBeDisabled();
  for (const dark of [false, true]) {
    await page.evaluate((d) => document.documentElement.classList.toggle("dark", d), dark);
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-runprog"));
    expect(audit.checked).toBeGreaterThan(2);
    expect(audit.low, dark ? "dark" : "light").toEqual([]);
  }
  step = 1;                                                               // 다음 읽기에서 끝남
  await expect(card.getByRole("button", { name: "결과 불러오기" })).toBeEnabled({ timeout: 10_000 });
  await expect(card).toContainText("끝났어요");
  await page.unroute("**/allocation/graph/run**");
  await card.getByRole("button", { name: "결과 불러오기" }).click();
  // 이 실행은 진짜로 끝났을 수도, 아직일 수도 있다 — 어느 쪽이든 화면은 그 사실을 말한다.
  await expect(page.locator(".pg-side .pg-kv", { hasText: "총수익" }).or(page.locator(".pg-runprog"))).toBeVisible({ timeout: 60_000 });
});

test("매크로 노드(BL3 W2): 곡선·대시보드·합의·예측 적중률·장기 관계·스튜디오가 돌고 그림으로 · 못 돌면 사유 · 대비 AA", async ({ page }) => {
  const sink = trackErrors(page);
  // 노드 아홉 개와 옆 패널이 한 화면에 들어오도록 — 가려진 노드를 억지로 누르지 않는다.
  await page.setViewportSize({ width: 1440, height: 1500 });
  await openCanvas(page);
  const doc = await exportDoc(page);
  const eight = "KR_BASE_RATE,KR_TERM_SPREAD,KR_CPI,USD_KRW,KOSPI,KR_CREDIT_SPREAD,KR_IP,KR_10Y";
  doc.nodes.push(
    { id: "yc", type: "yield_curve", params: {}, position: { x: 1100, y: 0 } },
    { id: "db", type: "macro_dashboard", params: {}, position: { x: 1100, y: 260 } },
    { id: "dr", type: "macro_dashboard", params: { theme: "rates" }, position: { x: 1400, y: 260 } },
    { id: "rc", type: "regime_consensus", params: { market: "kr" }, position: { x: 1100, y: 520 } },
    { id: "fc", type: "regime_forecast_coverage", params: { market: "kr", months: 120 }, position: { x: 1400, y: 520 } },
    { id: "lr", type: "long_run", params: { months: 120 }, position: { x: 1100, y: 780 } },
    { id: "l8", type: "long_run", params: { vars: eight }, position: { x: 1400, y: 780 } },
    { id: "st", type: "macro_studio", params: { studio: "neural-sde" }, position: { x: 1100, y: 1040 } },
    { id: "pt", type: "macro_studio", params: { studio: "pinn-tail" }, position: { x: 1400, y: 1040 } },
  );
  await importText(page, "bl3w2.json", JSON.stringify(doc));
  const body = await run(page);
  // 노드가 아홉 개 더 붙어 옆 패널이 열리면 일부가 화면 밖으로 밀린다 — 고르기 전에 화면에 맞춘다.
  const pick = async (id: string) => {
    await page.locator(".react-flow__controls-fitview").click();
    await node(page, id).click();
  };
  for (const id of ["yc", "db", "dr", "rc", "fc", "lr", "st"]) {
    expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
    // 개발 모드의 매크로는 연습용 계보다(운영은 저장된 관측만 — 백엔드 테스트가 가른다).
    expect(body.nodes[id].lineage.practice, id).toBe(true);
  }
  // ★못 돌면 숫자 대신 사유★ — 상한 초과는 거부, 표본이 모자란 꼬리 모델은 엔진 사유 그대로
  expect(body.nodes.l8.status).toBe("failed");
  expect(body.nodes.l8.reason).toContain("최대 7개");
  expect(body.nodes.pt.status).toBe("failed");
  expect(body.nodes.pt.reason).toContain("돌리지 못했어요");

  // 곡선: mock 곡선은 역전이다 — 칠한 구간과 '경험칙' 라벨
  await pick("yc");
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-curve--inv")).toBeVisible();
  expect(await page.locator(".pg-side .pg-curve .recharts-reference-area").count()).toBeGreaterThan(0);
  await expect(page.locator(".pg-side .pg-tag", { hasText: "경험칙" })).toBeVisible();
  // 대시보드: 전부면 여섯 테마, 테마를 고르면 하나
  await pick("db");
  await expect(page.locator(".pg-side .pg-dash-theme")).toHaveCount(6);
  expect(await page.locator(".pg-side .pg-zbar:not(.pg-zbar--none) i").count(), "잰 z 는 막대로(모름으로 접지 않는다)").toBeGreaterThan(10);
  await pick("dr");
  await expect(page.locator(".pg-side .pg-dash-theme")).toHaveCount(1);
  await expect(page.locator(".pg-side .pg-dash-h")).toHaveText("금리·통화");
  // 합의: 세 방법이 한 줄씩(평균 한 줄이 아니다)
  await pick("rc");
  await expect(page.locator(".pg-side .pg-consensus tbody tr")).toHaveCount(3);
  // 적중률: 목표·실측과 집합 크기 두 묶음
  await pick("fc");
  await expect(page.locator(".pg-side .pg-bars")).toHaveCount(2);
  // 장기 관계: 검정표 줄 수 = 쓴 계열 수 · 빠진 계열은 경고로
  await pick("lr");
  const used = (body.nodes.lr.view.result.used as string[]).length;
  await expect(page.locator(".pg-side .pg-trace tbody tr")).toHaveCount(used);
  if ((body.nodes.lr.view.result.missing ?? []).length) await expect(page.locator(".pg-side .pg-warn")).toContainText("빠졌습니다");
  // 스튜디오: 대체 엔진이 낸 수열 · 프런티어는 돌리지 않는다고 적는다
  await pick("st");
  expect(await page.locator(".pg-side .pg-spark-cell").count()).toBeGreaterThan(0);
  await expect(page.locator(".pg-side .pg-studio-frontier")).toContainText("이 노드는 돌리지 않아요");

  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    for (const id of ["yc", "db"]) {
      await pick(id);
      const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
      expect(audit.checked).toBeGreaterThan(10);
      expect(audit.low, `${id} ${dark ? "dark" : "light"}`).toEqual([]);
    }
  }
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("기업 노드(BL3 W3): 일곱 노드가 돌고 풋볼필드·분포·표로 · 모르는 종목·검증 못 할 테제는 사유 · 대비 AA", async ({ page }) => {
  const sink = trackErrors(page);
  await page.setViewportSize({ width: 1440, height: 1500 });
  await openCanvas(page);
  const doc = await exportDoc(page);
  const kill = { logic: "AND", conditions: [{ field: "roe", op: "lt", value: 8 }], groups: [] };
  const bad = { logic: "AND", conditions: [{ field: "no_such_field", op: "gt", value: 1 }], groups: [] };
  const at = (i: number) => ({ x: 1100 + (i % 2) * 300, y: Math.floor(i / 2) * 260 });
  const add: [string, string, Record<string, unknown>][] = [
    ["cv", "company_valuation", { code: "005930" }], ["rd", "reverse_dcf", { code: "005930" }],
    ["vd", "valuation_distribution", { code: "005930", n: 500 }], ["fd", "financial_deep", { code: "005930" }],
    ["rk", "risk_deep", { code: "005930" }], ["ms", "company_macro_sensitivity", { code: "005930" }],
    ["th", "thesis_check", { code: "005930", claim: "메모리 업황 회복", kill_conditions: kill }],
    ["uk", "company_valuation", { code: "999999" }], ["tb", "thesis_check", { code: "005930", claim: "x", kill_conditions: bad }],
  ];
  add.forEach(([id, type, params], i) => doc.nodes.push({ id, type, params, position: at(i) }));
  await importText(page, "bl3w3.json", JSON.stringify(doc));
  const body = await run(page);
  for (const id of ["cv", "rd", "vd", "rk", "ms", "th"]) {
    expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
    expect(body.nodes[id].lineage.practice, id).toBe(true);
    expect(body.nodes[id].view.name, id).toBe("삼성전자");
  }
  // ★못 하면 사유★ — 재무 미적재(mock) · 모르는 코드 · 레지스트리에 없는 필드
  expect(body.nodes.fd.status).toBe("failed");
  expect(body.nodes.fd.reason).toContain("재무");
  expect(body.nodes.uk.status).toBe("failed");
  expect(body.nodes.uk.reason).toContain("999999");
  expect(body.nodes.tb.status).toBe("failed");
  expect(body.nodes.tb.reason).toContain("no_such_field");

  const pick = async (id: string) => {
    await page.locator(".react-flow__controls-fitview").click();
    await node(page, id).click();
  };
  await pick("cv");
  await tab(page, "detail");
  // 풋볼필드: 방법마다 한 줄 · 현재가 세로선이 줄마다 · 가정 표의 출처 칩(연습용은 '모름' 톤)
  const bands = (body.nodes.cv.view.result.football_field.bands as unknown[]).length;
  await expect(page.locator(".pg-side .pg-ff-row")).toHaveCount(bands);
  await expect(page.locator(".pg-side .pg-ff-row .pg-ff-price")).toHaveCount(bands);
  await expect(page.locator(".pg-side .pg-assume .pg-tag--unknown").first()).toContainText("연습용");
  await expect(page.locator(".pg-side .pg-sens-base")).toHaveCount(1);
  await pick("vd");
  await expect(page.locator(".pg-side .pg-q-row")).toHaveCount(1 + Object.keys(body.nodes.vd.view.result.by_model).length);
  await pick("rd");
  await expect(page.locator(".pg-side .pg-bar-row")).toHaveCount(2);
  await pick("ms");
  await expect(page.locator(".pg-side .pg-msens-stat caption")).toContainText("상관 ≠ 인과");
  await pick("th");
  await expect(page.locator(".pg-side .pg-thesis tbody tr")).toHaveCount(1);
  await expect(page.locator(".pg-side .pg-thesis .pg-tag")).not.toHaveClass(/pg-tag--failed/);

  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    for (const id of ["cv", "vd"]) {
      await pick(id);
      const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
      expect(audit.checked).toBeGreaterThan(10);
      expect(audit.low, `${id} ${dark ? "dark" : "light"}`).toEqual([]);
    }
  }
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("기업 분석 모델(BL3 W3b-C1): EVA·가치의 층·배수 PEG·영업 MC · 입력 표 · 가중 합 틀리면 사유 · 대비 AA", async ({ page }) => {
  const sink = trackErrors(page);
  await page.setViewportSize({ width: 1440, height: 1500 });
  await openCanvas(page);
  const doc = await exportDoc(page);
  const add: [string, string, Record<string, unknown>][] = [
    ["ev", "company_eva", { code: "005930" }], ["vl", "company_value_layers", { code: "005930" }],
    ["mu", "company_multiples", { code: "005930", peers: false }], ["mc", "company_driver_mc", { code: "005930", n: 500 }],
    ["bw", "company_value_layers", { code: "005930", w_asset: 0.5, w_epv: 0.5, w_full: 0.5 }],
  ];
  add.forEach(([id, type, params], i) => doc.nodes.push({ id, type, params, position: { x: 1100 + (i % 2) * 300, y: Math.floor(i / 2) * 260 } }));
  await importText(page, "bl3w3b.json", JSON.stringify(doc));
  const body = await run(page);
  for (const id of ["ev", "vl", "mu", "mc"]) {
    expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
    expect(body.nodes[id].lineage.practice, id).toBe(true);
  }
  // ★가중을 나눠 맞추지 않는다★
  expect(body.nodes.bw.status).toBe("failed");
  expect(body.nodes.bw.reason).toContain("합");

  const pick = async (id: string) => {
    await page.locator(".react-flow__controls-fitview").click();
    await node(page, id).click();
  };
  await pick("vl");
  await tab(page, "detail");
  // 가치의 층: 잰 층마다 선 하나 + 현재가 선 하나 · 입력 표의 칩
  const measured = (body.nodes.vl.view.result.layers as { key: string; per_share: number | null }[])
    .filter((l) => l.key !== "growth" && l.per_share !== null).length + (body.nodes.vl.view.result.full_per_share !== null ? 1 : 0);
  await expect(page.locator(".pg-side .pg-floors-line")).toHaveCount(measured);
  await expect(page.locator(".pg-side .pg-floors-price")).toHaveCount(1);
  await expect(page.locator(".pg-side .pg-inputs .pg-tag", { hasText: "근사" }).first()).toBeVisible();
  await pick("ev");
  const evYears = (body.nodes.ev.view.result.years as { available: boolean }[]).filter((y) => y.available).length;
  await expect(page.locator(".pg-side .pg-eva tbody tr")).toHaveCount(evYears);
  await expect(page.locator(".pg-side .pg-kv").first()).toContainText("성장이 가치를");
  await pick("mu");
  await expect(page.locator(".pg-side .pg-peg tbody tr")).toHaveCount(5);
  await expect(page.locator(".pg-side .pg-peg .pg-sens-base")).toHaveCount(1);
  await pick("mc");
  await expect(page.locator(".pg-side .pg-hist-bar")).toHaveCount(20);
  await expect(page.locator(".pg-side .pg-inputs .pg-tag", { hasText: "관측" }).first()).toBeVisible();

  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    for (const id of ["vl", "mc", "mu"]) {
      await pick(id);
      const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
      expect(audit.checked).toBeGreaterThan(10);
      expect(audit.low, `${id} ${dark ? "dark" : "light"}`).toEqual([]);
    }
  }
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("기업 분석 모델(BL3 W3b-C2): 시나리오·나무·SOTP·실물옵션 · 기본 시나리오가 설정에 보인다 · 확률 합 틀리면 사유 · 대비 AA", async ({ page }) => {
  const sink = trackErrors(page);
  await page.setViewportSize({ width: 1440, height: 1500 });
  await openCanvas(page);
  const doc = await exportDoc(page);
  const add: [string, string, Record<string, unknown>][] = [
    ["sc", "company_scenarios", { code: "005930" }], ["dt", "company_decision_tree", { code: "005930" }],
    ["so", "company_sotp", { code: "005930", segments: [{ name: "반도체", metric: 200000, multiple: 6 }],
      subsidiaries: [{ code: "000660", stake_pct: 20 }, { code: "999999", stake_pct: 10 }], holding_discount_pct: 30 }],
    ["ro", "company_real_option", { code: "005930", kind: "put", S: 900, K: 1000, T: 2, sigma: 0.3 }],
    ["bp", "company_scenarios", { code: "005930", scenarios: [{ name: "a", prob: 0.3 }, { name: "b", prob: 0.3 }] }],
    ["bt", "company_decision_tree", { code: "005930", branches: [{ id: "A", prob: 0.5, value: 1 }, { id: "B", prob: 0.3, value: 2 }] }],
  ];
  add.forEach(([id, type, params], i) => doc.nodes.push({ id, type, params, position: { x: 1100 + (i % 2) * 300, y: Math.floor(i / 2) * 260 } }));
  await importText(page, "bl3w3c2.json", JSON.stringify(doc));
  const body = await run(page);
  for (const id of ["sc", "dt", "so", "ro"]) {
    expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
    expect(body.nodes[id].lineage.practice, id).toBe(true);
  }
  expect(body.nodes.bp.status).toBe("failed");
  expect(body.nodes.bp.reason).toContain("합");
  expect(body.nodes.bt.status).toBe("failed");
  expect(body.nodes.bt.reason).toContain("합");
  expect(body.nodes.dt.view.result.expected_value).toBeCloseTo(58700, 0);

  const pick = async (id: string) => {
    await page.locator(".react-flow__controls-fitview").click();
    await node(page, id).click();
  };
  await pick("sc");
  // ★설정에 보이는 것 = 서버가 계산에 쓴 것★ — 기본 시나리오 셋이 설정 화면에 그대로 보인다
  await tab(page, "settings");
  await expect(page.locator('.pg-side [data-field="scenarios"] .pg-objrow')).toHaveCount(3);
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-scen tbody tr")).toHaveCount(3);
  await pick("dt");
  await expect(page.locator(".pg-side .pg-tree-row")).toHaveCount(4);
  await expect(page.locator(".pg-side .pg-paths tbody tr")).toHaveCount(3);
  await pick("so");
  await expect(page.locator(".pg-side .pg-warn", { hasText: "999999" })).toBeVisible();
  await expect(page.locator(".pg-side .pg-sotp-total")).toContainText("남는 지분가치");
  await pick("ro");
  await expect(page.locator(".pg-side .pg-opt-cell")).toHaveCount(2);
  await expect(page.locator(".pg-side .pg-inputs .pg-tag", { hasText: "가정" }).first()).toBeVisible();

  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    for (const id of ["sc", "so", "ro"]) {
      await pick(id);
      const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
      expect(audit.checked).toBeGreaterThan(10);
      expect(audit.low, `${id} ${dark ? "dark" : "light"}`).toEqual([]);
    }
  }
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("리스크 노드(BL3 W4): VaR·MC·변동성·보유기간·FRTB·롤링 샤프·동적 상관 · 손실 꼬리 · 비중 없음·짧은 창은 사유 · 대비 AA", async ({ page }) => {
  const sink = trackErrors(page);
  await page.setViewportSize({ width: 1440, height: 1500 });
  await openCanvas(page);
  const doc = await exportDoc(page);
  const add: [string, string, Record<string, unknown>, boolean][] = [
    ["vr", "var_es", {}, true], ["mc", "mc_var", { n_simulations: 5000 }, true], ["vm", "vol_models", {}, true],
    ["hv", "holding_var", {}, true], ["fr", "frtb_es", {}, true], ["rs", "rolling_sharpe", { window: 126 }, true],
    ["dc", "dcc_corr", {}, false],
    ["nw", "var_es", {}, false],                              // 비중을 잇지 않은 포트폴리오 — 사유로 실패
    ["lw", "rolling_sharpe", { window: 756 }, true],          // 창이 표본보다 길다 — 0 을 내지 않고 실패
  ];
  add.forEach(([id, type, params, withW], i) => {
    doc.nodes.push({ id, type, params, position: { x: 1100 + (i % 3) * 260, y: Math.floor(i / 3) * 240 } });
    doc.edges.push({ id: `returns.returns->${id}.returns`, source: "returns", source_port: "returns", target: id, target_port: "returns" });
    if (withW) doc.edges.push({ id: `optimizer.weights->${id}.weights`, source: "optimizer", source_port: "weights", target: id, target_port: "weights" });
  });
  await importText(page, "bl3w4.json", JSON.stringify(doc));
  const body = await run(page);
  for (const id of ["vr", "mc", "vm", "hv", "fr", "rs", "dc"]) {
    expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
    expect(body.nodes[id].lineage.practice, id).toBe(true);      // mock 수익률 → 위험 수치도 연습용
  }
  expect(body.nodes.nw.status).toBe("failed");
  expect(body.nodes.nw.reason).toContain("비중");
  expect(body.nodes.lw.status).toBe("failed");
  expect(body.nodes.lw.reason).toContain("756일 창");

  const pick = async (id: string) => {
    await page.locator(".react-flow__controls-fitview").click();
    await node(page, id).click();
  };
  await pick("vr");
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-risk-big")).toContainText("원");
  // 세 방법 + 종목 셋(구성)
  await expect(page.locator(".pg-side .pg-risk-bars .pg-bar-row")).toHaveCount(3 + 3);
  await expect(page.locator(".pg-side .pg-inputs .pg-tag", { hasText: "관측" }).first()).toBeVisible();

  // ★손실 꼬리★ — VaR 선보다 더 잃은 칸만 진하다(서버 히스토그램 그대로 세어 대조).
  await pick("mc");
  const r = body.nodes.mc.view.result;
  const tail = (r.histogram.bin_centers as number[]).filter((c) => c <= -r.mc_var_amount).length;
  await expect(page.locator(".pg-side .pg-risk-bin")).toHaveCount(r.histogram.counts.length);
  await expect(page.locator(".pg-side .pg-risk-bin--tail")).toHaveCount(tail);
  expect(tail).toBeGreaterThan(0);
  expect(tail).toBeLessThan(r.histogram.counts.length);
  await expect(page.locator(".pg-side .pg-risk-var")).toHaveCount(1);

  await pick("vm");
  await expect(page.locator(".pg-side .pg-risk-line")).toHaveCount(2);
  await expect(page.locator(".pg-side .pg-note").first()).toContainText("앞날을 더 잘 맞힌다는 뜻이 아니에요");
  await pick("hv");
  await expect(page.locator(".pg-side .pg-scen tbody tr")).toHaveCount(8);
  await pick("fr");
  await expect(page.locator(".pg-side .pg-warn")).toHaveCount(0);           // 756일 표본 — 스트레스 구간을 찾았다
  await pick("dc");
  await expect(page.locator(".pg-side .pg-scen tbody tr")).toHaveCount(3);  // 종목 셋 → 쌍 셋

  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    for (const id of ["vr", "mc", "fr"]) {
      await pick(id);
      const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
      expect(audit.checked).toBeGreaterThan(10);
      expect(audit.low, `${id} ${dark ? "dark" : "light"}`).toEqual([]);
    }
  }
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});

test("파생·신용 계산기(BL3 W4): 옵션·채권·헤지·CVA·IRC · 모든 칸이 가정 · /derivatives 옵션 탭이 실제 라우트로 그린다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.setViewportSize({ width: 1440, height: 1500 });
  await openCanvas(page);
  const doc = await exportDoc(page);
  const add: [string, string, Record<string, unknown>][] = [
    ["op", "option_calc", { S: 100, K: 100, T: 1, r: 0.05, sigma: 0.2 }], ["bd", "bond_calc", {}],
    ["hg", "futures_hedge", { current_beta: 1.2 }], ["cv", "cva_calc", {}], ["ir", "irc_calc", { n_simulations: 5000 }],
    ["hz", "futures_hedge", { current_beta: 0 }],
  ];
  add.forEach(([id, type, params], i) => doc.nodes.push({ id, type, params, position: { x: 1100 + (i % 2) * 300, y: Math.floor(i / 2) * 260 } }));
  await importText(page, "bl3w4c.json", JSON.stringify(doc));
  const body = await run(page);
  for (const [id] of add) expect(body.nodes[id].status, `${id}: ${body.nodes[id].reason}`).toBe("ok");
  expect(body.nodes.op.view.result.Price).toBeCloseTo(10.4506, 4);
  expect(body.nodes.cv.view.result.bcva_spread).toBeUndefined();          // 단위가 맞지 않는 모델 출력은 싣지 않는다
  expect(body.nodes.hz.view.result.expected_var_reduction_pct).toBeNull(); // β=0 에서 '0% 감소' 라고 말하지 않는다

  const pick = async (id: string) => {
    await page.locator(".react-flow__controls-fitview").click();
    await node(page, id).click();
  };
  await pick("op");
  await tab(page, "detail");
  await expect(page.locator(".pg-side .pg-opt-v").first()).toHaveText("10.4506");
  await expect(page.locator(".pg-side .pg-inputs .pg-tag", { hasText: "관측" })).toHaveCount(0);   // 계산기는 아무것도 관측하지 않는다
  await pick("cv");
  await expect(page.locator(".pg-side .pg-h4 .pg-tag--assumed")).toHaveText("양식화");
  await pick("hz");
  await expect(page.locator(".pg-side .pg-kv")).toContainText("계산 안 함");
  await pick("ir");
  await expect(page.locator(".pg-side .pg-scen tbody tr")).toHaveCount(2);
  for (const dark of [false, true]) {
    if (dark) await page.evaluate(() => document.documentElement.classList.add("dark"));
    for (const id of ["op", "cv"]) {
      await pick(id);
      const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side"));
      expect(audit.checked).toBeGreaterThan(8);
      expect(audit.low, `${id} ${dark ? "dark" : "light"}`).toEqual([]);
    }
  }

  // /derivatives — 예전엔 없는 /option-price 를 불러 404 였고, 고쳐도 소문자 키를 읽어 아무것도 안 그렸다.
  await page.evaluate(() => document.documentElement.classList.remove("dark"));
  let calls = 0;
  page.on("request", (q) => { if (q.url().includes("/analyze-option")) calls += 1; });
  await page.goto("/derivatives", { waitUntil: "domcontentloaded" });
  const inputs = page.locator("input.input");
  await inputs.nth(0).fill("100"); await inputs.nth(1).fill("100");
  await inputs.nth(2).fill("0.2"); await inputs.nth(3).fill("0.05"); await inputs.nth(4).fill("1");
  await page.getByRole("button", { name: "프라이싱 실행" }).click();
  await expect(page.getByTestId("option-greeks")).toContainText("10.4506");
  expect(calls).toBe(1);
  // 짝: 만기 0 — 서버는 조용히 0 을 돌려주므로 화면이 보내기 전에 막는다.
  await inputs.nth(4).fill("0");
  await page.getByRole("button", { name: "프라이싱 실행" }).click();
  await expect(page.getByText("0보다 커야")).toBeVisible();
  await expect(page.getByTestId("option-greeks")).toHaveCount(0);
  expect(calls).toBe(1);

  expect(uniq(sink.api404), "404").toEqual([]);
  expect(uniq(sink.apiOther4xx5xx), "4xx/5xx").toEqual([]);
  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
  expect(uniq(sink.consoleErrors), "console errors").toEqual([]);
});
