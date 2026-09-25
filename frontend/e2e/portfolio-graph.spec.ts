import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { trackErrors, uniq } from "./helpers";

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
// ═══════════════════════════════════════════════════════════════════════════════

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const status = (page: Page, id: string) => node(page, id).locator(".pg-node-status-k");
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
  await expect(page.locator(".pg-summary").first()).toContainText("완료", { timeout: 30_000 });
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
  await expect(page.locator(".pg-palette-item")).toHaveCount(7);
  await expect(page.locator(".pg-node")).toHaveCount(7);
  const body = await run(page);
  expect(body.ok).toBe(true);
  for (const id of ["universe", "returns", "estimate", "views", "optimizer", "risk", "backtest"]) {
    await expect(status(page, id), id).toHaveText("완료");
  }
  // mock 수익률은 합성이다 — 등급 배지가 그렇게 말해야 한다(실데이터처럼 보이면 안 된다).
  await expect(node(page, "returns").locator(".pg-node-grade")).toContainText("합성");
  await node(page, "optimizer").click();
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
  const head = (await added.locator(".pg-node-head").boundingBox())!;
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
  const tickers = page.locator(".pg-inspector .pg-field", { hasText: "Tickers" }).locator("input");
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
  await expect(page2.locator(".pg-file-note")).toContainText("불러왔습니다");
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
  await expect(page.locator(".pg-file-note")).toContainText("불러오지 않았습니다");
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
  await page.locator(".pg-wizard-link", { hasText: "목표 선택" }).click();
  await expect(page).toHaveURL(/\/allocation\/wizard/);
  await expect(page.locator(".aas-goal").first()).toBeVisible({ timeout: 20_000 });
});
