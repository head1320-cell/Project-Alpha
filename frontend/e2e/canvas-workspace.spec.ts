import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";
import { fmtElapsed, fmtGlance } from "../src/entities/portfolio-graph/glance";

// ═══════════════════════════════════════════════════════════════════════════════
// BM — 캔버스를 "포트폴리오 설계 작업실"로 (설계 docs/superpowers/specs/2026-09-27-canvas-workspace-design.md)
// ─────────────────────────────────────────────────────────────────────────────
// C1 · 결과가 캔버스에 보인다 — 거는 것:
//  · 확대 3단계: 멀리(이름+숫자 하나) · 보통(카드) · 가까이(작은 그림·계산 시간) — 단계마다 보이는 것과 ★안 보이는 것(짝)★
//  · ★작은 그림은 서버 glance 그대로★ — 응답을 바꾸면 카드가 따라 바뀐다(화면이 따로 계산하지 않는다) · null 은 "모름"
//  · 그림 고정(뷰어 플래그) — 보통 확대에서도 그림이 보이고, 풀면 사라진다
//  · 증거 선 모양 = 원천 노드 계보 — 계산 전·낡은 결과엔 모양이 없다(짝) · 막힘은 끊긴 회색
//  · 선 위 한 줄 = 서버 briefs 그대로 — 없으면 라벨도 없다(지어내지 않는다)
//  · 원인 따라가기 — 막힌 노드에서 첫 원인까지 밝히고 나머지는 흐림 · Esc 로 다 보기
//  · 키보드 이동(Alt+방향키) · 라이트·다크 AA
// ═══════════════════════════════════════════════════════════════════════════════

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const rfNode = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);
const canvas = (page: Page) => page.locator(".pg-canvas");

type Glance = { kind: string; points: { label: string; value: number | null }[]; unit: string | null; caption: string | null };
type NodeRes = { status: string; reason: string | null; glance?: Glance | null; elapsed_ms?: number | null;
                 briefs?: Record<string, string>; lineage?: { practice: boolean; pit: string | null } ; [k: string]: unknown };
type RunBody = { nodes: Record<string, NodeRes> };

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}

async function run(page: Page): Promise<RunBody> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}

async function patchRun(page: Page, fn: (body: RunBody) => void) {
  await page.unroute("**/api/v1/allocation/graph/run**");
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as RunBody;
    fn(body);
    await route.fulfill({ response: res, json: body });
  });
}

async function zoomTo(page: Page, level: "far" | "mid" | "near") {
  for (let i = 0; i < 14; i++) {
    const z = await canvas(page).getAttribute("data-zoom");
    if (z === level) return;
    const zoom = await canvas(page).evaluate((el) => Number(getComputedStyle(el).getPropertyValue("--pg-z")));
    const wantIn = level === "near" || (level === "mid" && z === "far");
    await page.locator(wantIn ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
    void zoom;
  }
  await expect(canvas(page)).toHaveAttribute("data-zoom", level);
}

async function failOneTicker(page: Page) {
  await node(page, "universe").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const tickers = page.locator('.pg-basic-field[data-field="tickers"] input');
  await tickers.fill("005930");
  await tickers.press("Enter");
}

test("확대 3단계(BM C1): 멀리는 이름·숫자 하나, 보통은 카드, 가까이는 작은 그림·계산 시간 — 단계마다 안 보이는 것(짝)", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const opt = node(page, "optimizer");
  expect(body.nodes.optimizer.glance?.kind).toBe("bars");

  await zoomTo(page, "mid");
  await expect(opt.locator(".pg-node-t")).toBeVisible();
  await expect(opt.locator(".pg-node-far")).toBeHidden();
  await expect(opt.locator(".pg-node-glance")).toBeHidden();
  await expect(opt.locator(".pg-node-time")).toBeHidden();
  await expect(page.locator(".pg-wire-brief").first()).toBeVisible();

  await zoomTo(page, "far");
  await expect(opt.locator(".pg-node-far")).toBeVisible();
  await expect(opt.locator(".pg-node-t")).toBeHidden();
  await expect(opt.locator(".pg-node-glance")).toBeHidden();
  await expect(page.locator(".pg-wire-brief").first()).toBeHidden();
  // 멀리서도 글자는 화면에서 11px 아래로 줄지 않는다(확대 0.3 까지).
  const px = await opt.locator(".pg-node-far-name").evaluate((el) => {
    const z = Number(getComputedStyle(el.closest(".pg-canvas")!).getPropertyValue("--pg-z"));
    return parseFloat(getComputedStyle(el).fontSize) * z;
  });
  expect(px).toBeGreaterThanOrEqual(10.9);

  await zoomTo(page, "near");
  await expect(opt.locator(".pg-node-glance")).toBeVisible();
  await expect(opt.locator(".pg-node-time")).toBeVisible();
  await expect(opt.locator(".pg-node-far")).toBeHidden();
  // ★그림이 없는 노드는 그림 칸이 없다★ — 빈 그림을 지어내지 않는다.
  for (const [id, r] of Object.entries(body.nodes)) {
    await expect(node(page, id).locator(".pg-node-glance"), id).toHaveCount(r.glance ? 1 : 0);
  }
});

test("작은 그림 = 서버 glance 그대로(BM C1): 응답을 바꾸면 카드가 따라 바뀌고 null 은 '모름' · 계산 시간도 서버 값", async ({ page }) => {
  await openCanvas(page);
  await patchRun(page, (b) => {
    b.nodes.optimizer.glance = { kind: "bars", unit: "%", caption: "가짜 그림",
      points: [{ label: "가짜가", value: 12.3456 }, { label: "가짜나", value: null }, { label: "가짜다", value: 0 }] };
    b.nodes.optimizer.elapsed_ms = 1234;
    b.nodes.universe.elapsed_ms = 0.2;
  });
  await run(page);
  await zoomTo(page, "near");
  const g = node(page, "optimizer").locator(".pg-glance");
  await expect(g.locator(".pg-gl-cap")).toHaveText("가짜 그림");
  await expect(g.locator(".pg-gl-lab")).toHaveText(["가짜가", "가짜나", "가짜다"]);
  await expect(g.locator(".pg-gl-val")).toHaveText([fmtGlance(12.3456, "%"), "모름", "0%"]);
  expect(fmtGlance(12.3456, "%")).toBe("12.3%");
  // 모르는 값에는 막대가 없다(0 너비 막대로 그리지 않는다) — 0 은 진짜 0 이라 막대 칸이 있다.
  await expect(g.locator("li").nth(1).locator(".pg-gl-track i")).toHaveCount(0);
  await expect(g.locator("li").nth(2).locator(".pg-gl-track i")).toHaveCount(1);
  await expect(node(page, "optimizer").locator(".pg-node-time")).toHaveText(`계산 ${fmtElapsed(1234)}`);
  await expect(node(page, "universe").locator(".pg-node-time")).toHaveText("계산 1ms 미만");
});

test("선 그림은 값을 모르는 구간을 끊는다 · 양 끝 값은 글로도 적는다(BM C1)", async ({ page }) => {
  await openCanvas(page);
  await patchRun(page, (b) => {
    b.nodes.optimizer.glance = { kind: "line", unit: null, caption: "곡선",
      points: [{ label: "a", value: 1 }, { label: "b", value: 1.2 }, { label: "c", value: null }, { label: "d", value: 1.1 }, { label: "e", value: 1.3 }] };
  });
  await run(page);
  await zoomTo(page, "near");
  const g = node(page, "optimizer").locator(".pg-glance");
  await expect(g.locator("polyline")).toHaveCount(2);
  await expect(g.locator(".pg-gl-ends span")).toHaveText(["1.00", "1.30"]);
  await expect(g.locator(".pg-gl-note")).toHaveText("끊긴 곳은 값을 몰라요");
});

test("그림 고정(BM C1): 보통 확대에서도 고정한 노드만 그림이 보이고, 풀면 사라진다", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await zoomTo(page, "mid");
  await node(page, "optimizer").click();
  await expect(node(page, "optimizer").locator(".pg-node-glance")).toBeHidden();
  await page.locator(".pg-pin").click();
  await expect(page.locator(".pg-pin")).toHaveAttribute("aria-pressed", "true");
  await expect(node(page, "optimizer").locator(".pg-node-glance")).toBeVisible();
  await expect(node(page, "risk").locator(".pg-node-glance"), "고정하지 않은 노드는 그대로").toBeHidden();
  await page.locator(".pg-pin").click();
  await expect(node(page, "optimizer").locator(".pg-node-glance")).toBeHidden();
});

test("증거 선(BM C1): 선 모양 = 원천 계보 · 계산 전과 낡은 결과엔 모양이 없다(짝) · 응답 계보를 바꾸면 모양이 따라온다", async ({ page }) => {
  await openCanvas(page);
  const shaped = page.locator(".react-flow__edge.pg-wire--plain, .react-flow__edge.pg-wire--practice, .react-flow__edge.pg-wire--blocked");
  await expect(shaped, "계산 전에는 근거를 주장하지 않는다").toHaveCount(0);
  await expect(page.locator(".pg-wire-legend")).toHaveCount(0);

  // universe 는 연습용이 아니다(종목 목록) → 실선. returns 이하는 mock 이라 연습용 → 점선. 한 곳을 '지금 시점 전용'으로 바꿔 눈금을 본다.
  await patchRun(page, (b) => { b.nodes.estimate.lineage = { ...(b.nodes.estimate.lineage ?? { practice: false }), pit: "forward_only" } as NodeRes["lineage"]; });
  const body = await run(page);
  await expect(page.locator(".pg-wire-legend")).toBeVisible();
  const edges = await page.locator(".react-flow__edge").evaluateAll((es) => es.map((e) => ({
    id: e.getAttribute("data-testid")?.replace("rf__edge-", "") ?? "", cls: e.getAttribute("class") ?? "" })));
  expect(edges.length).toBeGreaterThan(5);
  const doc = await page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}"));
  for (const e of doc.edges as { id: string; source: string }[]) {
    const src = body.nodes[e.source];
    const cls = edges.find((x) => x.id === e.id)?.cls ?? "";
    const want = src.status !== "ok" ? "blocked" : src.lineage?.practice ? "practice" : "plain";
    expect(cls, `${e.id}`).toContain(`pg-wire--${want}`);
    expect(cls.includes("pg-wire--forward"), `${e.id} 눈금`).toBe(src.lineage?.pit === "forward_only");
  }
  expect(edges.some((x) => x.cls.includes("pg-wire--plain")), "실선이 하나는 있다").toBe(true);
  expect(edges.some((x) => x.cls.includes("pg-wire--practice")), "점선이 하나는 있다").toBe(true);
  await expect(page.locator(".pg-wire--forward .pg-wire-ticks").first()).toBeAttached();
  // 범례는 '실데이터' 라고 말하지 않는다.
  await expect(page.locator(".pg-wire-legend")).not.toContainText("실데이터");

  // 낡으면 모양을 거둔다.
  await node(page, "views").click();
  await page.keyboard.press("Control+d");
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  await expect(shaped).toHaveCount(0);
});

test("막힘은 끊긴 회색 선 · 선 위 한 줄은 서버 briefs 그대로 — 없으면 라벨도 없다(BM C1)", async ({ page }) => {
  await openCanvas(page);
  await failOneTicker(page);
  await patchRun(page, (b) => { b.nodes.universe.briefs = { universe: "가짜 한 줄" }; });
  const body = await run(page);
  expect(body.nodes.returns.status).toBe("failed");
  await zoomTo(page, "mid");
  await expect(page.locator(".react-flow__edge[data-testid^='rf__edge-returns']").first()).toHaveClass(/pg-wire--blocked/);
  await expect(page.locator(".pg-wire-brief")).toHaveText(["가짜 한 줄"]);
  // 실패한 노드는 briefs 가 비어 있다 — 나가는 선에 라벨이 없다.
  expect(body.nodes.returns.briefs).toEqual({});
});

test("원인 따라가기(BM C1): 막힌 노드에서 첫 원인까지 밝히고 나머지는 흐림 · 첫 원인을 누르면 그 노드로 · Esc 로 다 보기", async ({ page }) => {
  await openCanvas(page);
  await failOneTicker(page);
  const body = await run(page);
  expect(body.nodes.risk.status).toBe("blocked");
  // 완료 노드에는 버튼이 없다(짝).
  await expect(node(page, "views").locator(".pg-cause-btn")).toHaveCount(0);
  await node(page, "risk").locator(".pg-cause-btn").click();
  await expect(page.locator(".pg-cause-banner")).toContainText("첫 원인");
  await expect(rfNode(page, "returns")).toHaveClass(/pg-cause-root/);
  for (const id of ["risk", "optimizer", "returns"]) await expect(rfNode(page, id), id).toHaveClass(/pg-on-cause/);
  // 완료된 상류(universe)와 관계없는 가지(views)는 원인이 아니다.
  for (const id of ["universe", "views"]) await expect(rfNode(page, id), id).toHaveClass(/pg-dim/);
  await page.locator(".pg-cause-root-btn").first().click();
  await expect(node(page, "returns")).toHaveClass(/pg-node--selected/);
  await page.locator(".react-flow__pane").click({ position: { x: 5, y: 5 } }).catch(() => {});
  await node(page, "risk").locator(".pg-cause-btn").click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-cause-banner")).toHaveCount(0);
  await expect(page.locator(".react-flow__node.pg-dim")).toHaveCount(0);
});

test("키보드 이동(BM C1): Alt+→ 다음 단계 · Alt+← 앞 단계 · Alt+↓ 번호 순서", async ({ page }) => {
  await openCanvas(page);
  await node(page, "universe").click();
  await page.locator(".react-flow__pane").focus().catch(() => {});
  await page.keyboard.press("Alt+ArrowRight");
  await expect(node(page, "returns")).toHaveClass(/pg-node--selected/);
  await page.keyboard.press("Alt+ArrowLeft");
  await expect(node(page, "universe")).toHaveClass(/pg-node--selected/);
  await page.keyboard.press("Alt+ArrowDown");
  await expect(node(page, "universe")).not.toHaveClass(/pg-node--selected/);
  await expect(page.locator(".pg-sr-live")).toContainText("노드를 골랐어요");
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BM C1): ${scheme} — 가까이 확대 · 원인 배너 · 범례 · 선 라벨 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    await failOneTicker(page);
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await node(page, "risk").locator(".pg-cause-btn").click();
    await page.keyboard.press("Escape");
    await zoomTo(page, "near");
    await node(page, "risk").locator(".pg-cause-btn").click();
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-canvas"));
    expect(audit.checked).toBeGreaterThan(20);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}
