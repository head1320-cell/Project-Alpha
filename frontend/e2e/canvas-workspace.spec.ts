import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
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

// ═══════════════════════════════════════════════════════════════════════════════
// C2 · 여러 전략 → 한 포트폴리오 — 거는 것:
//  · 전략 추가: 지금 흐름을 첫 전략으로 묶고 새 전략 띠를 넣어 '전략 합치기'에 잇는다 · 이름은 겹치지 않는다(짝)
//  · 포트폴리오 노드의 전략 이름 = 전략 상자 이름(이름을 바꾸면 파라미터도) · 계산하면 서버의 전략별 몫이 표로
//  · 전략 지도 정리: 단계 레인 + 포트폴리오 레인, 전략은 띠마다 아래로 · 접으면 대리 포트, 펼치면 사라짐 · 들어가기/나가기
//  · 상태 필터(서버 결과 그대로 셈) · 한 노드를 고르면 닿지 않은 선은 옅게
//  · 내 블록: 이 브라우저에 저장 → 새로고침해도 남음 → 넣기 · 파일 받기/불러오기 · 다른 포맷 거부 · 저장소가 막히면 파일만(말함)
// ═══════════════════════════════════════════════════════════════════════════════

type Doc = { nodes: { id: string; type: string; params: Record<string, unknown>; position: { x: number; y: number } }[];
             edges: { source: string; target: string; source_port: string; target_port: string }[];
             groups?: { id: string; label: string; members: string[]; kind?: string; output?: string | null; color?: number }[] };
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;

/** 헤드리스 Chromium 은 blob 내려받기의 이름을 "download" 로 보고한다(그래프 내보내기도 같다) — 페이지가 붙인 이름을 직접 적어 둔다. */
async function recordDownloadNames(page: Page) {
  await page.addInitScript(() => {
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      const w = window as unknown as { __dlNames?: string[] };
      if (this.download) (w.__dlNames ??= []).push(this.download);
      return click.call(this);
    };
  });
}
const lastDownloadName = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __dlNames?: string[] }).__dlNames ?? []).slice(-1)[0] ?? "");

async function addStrategy(page: Page, source: string) {
  await page.locator(".pg-strat-add").click();
  await page.locator(`.pg-strat-item[data-source="${source}"]`).click();
  await expect(page.locator(".pg-note")).toBeVisible();
}

test("전략 추가(BM C2): 지금 흐름이 첫 전략이 되고 새 전략이 띠로 들어와 '전략 합치기'에 이어진다 · 계산하면 서버의 전략별 몫", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  await expect(page.locator(".pg-group--strategy")).toHaveCount(2);
  let doc = await wip(page);
  const strategies = (doc.groups ?? []).filter((g) => g.kind === "strategy");
  const pf = doc.nodes.find((n) => n.type === "portfolio_combine")!;
  expect(pf, "포트폴리오 노드가 생겼다").toBeTruthy();
  const into = doc.edges.filter((e) => e.target === pf.id);
  expect(into.map((e) => e.source).sort()).toEqual(strategies.map((g) => g.output).sort());
  const labels = pf.params.labels as Record<string, string>;
  expect(into.map((e) => labels[e.target_port]).sort()).toEqual(strategies.map((g) => g.label).sort());

  // 짝 — 같은 전략을 또 넣으면 이름이 겹치지 않는다.
  await addStrategy(page, "tpl:stress");
  doc = await wip(page);
  const names = (doc.groups ?? []).filter((g) => g.kind === "strategy").map((g) => g.label);
  expect(new Set(names).size).toBe(names.length);
  expect(names).toContain("충격 점검 2");

  const body = await run(page);
  const r = body.nodes[pf.id] as NodeRes & { view: { result: { sleeve_allocation: Record<string, number> } } };
  expect(r.status, String(r.reason)).toBe("ok");
  expect(Object.keys(r.view.result.sleeve_allocation).sort()).toEqual([...names].sort());
  await page.locator(`.pg-step[data-node-id="${pf.id}"] .pg-step-num`).click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await expect(page.locator(".pg-strat-table tbody tr")).toHaveCount(3);
  for (const [label, share] of Object.entries(r.view.result.sleeve_allocation)) {
    const row = page.locator(".pg-strat-table tbody tr", { hasText: label });
    await expect(row.locator("td").nth(1)).toHaveText(`${share.toFixed(1)}%`);
  }
});

test("전략 이름을 바꾸면 포트폴리오 노드의 전략 이름도 바뀌고 결과는 낡음 · 비중 없는 노드는 전략으로 못 묶음(사유)", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  await run(page);
  const label = page.locator(".pg-group--strategy .pg-group-label").last();
  await label.fill("모멘텀");
  const doc = await wip(page);
  const pf = doc.nodes.find((n) => n.type === "portfolio_combine")!;
  expect(Object.values(pf.params.labels as Record<string, string>)).toContain("모멘텀");
  await expect(page.locator(".pg-summary--stale")).toBeVisible();

  // 짝 — 비중을 내지 않는 노드만 골라 전략으로 묶으면 묶지 않고 사유를 말한다.
  await node(page, "s2_universe").click();
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("전략으로 묶기");
  await page.keyboard.press("Enter");
  await expect(page.locator(".pg-note")).toContainText("비중을 내는 노드가 없어요");
});

test("전략 지도(BM C2): 자동 정리 = 단계 레인 + 포트폴리오 레인 · 전략은 띠마다 아래로 · 포트폴리오는 맨 오른쪽", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  await page.locator('button[aria-label="자동 정리"]').click();
  await expect(page.locator(".pg-lane--portfolio")).toHaveCount(1);
  const stages = (await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json()).stages as unknown[];
  await expect(page.locator(".pg-lane")).toHaveCount(stages.length + 1);
  const doc = await wip(page);
  const [a, b] = (doc.groups ?? []).filter((g) => g.kind === "strategy");
  const y = (id: string) => doc.nodes.find((n) => n.id === id)!.position.y;
  const x = (id: string) => doc.nodes.find((n) => n.id === id)!.position.x;
  expect(Math.min(...b.members.map(y)), "두 번째 전략 띠는 첫 띠 아래").toBeGreaterThan(Math.max(...a.members.map(y)));
  const pf = doc.nodes.find((n) => n.type === "portfolio_combine")!;
  expect(pf.position.x).toBeGreaterThan(Math.max(...[...a.members, ...b.members].map(x)));
  // 짝 — 전략이 없으면 예전 정리(레인 없음).
  await page.locator('.pg-template[data-template="core"]').click();
  await page.locator('button[aria-label="자동 정리"]').click();
  await expect(page.locator(".pg-lane")).toHaveCount(0);
});

test("접으면 대리 포트 · 펼치면 사라짐 · 들어가기는 그 전략만 밝히고 Esc 로 나옴(BM C2)", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const frame = page.locator(".pg-group--strategy").last();
  const gid = await frame.getAttribute("data-group-id");
  const doc = await wip(page);
  const members = doc.groups!.find((g) => g.id === gid)!.members;
  await frame.locator(".pg-group-toggle").click();
  for (const m of members.slice(0, 3)) await expect(node(page, m)).toBeHidden();
  await expect(frame.locator(".pg-proxy--out")).toHaveCount(1);             // 비중 출력 하나가 포트폴리오로
  // 선은 상자의 대리 포트에서 포트폴리오로 이어져 보인다.
  await expect(page.locator(`.react-flow__handle[data-nodeid="frame:${gid}"].source`)).toHaveCount(1);
  await frame.locator(".pg-group-toggle").click();
  await expect(frame.locator(".pg-proxy")).toHaveCount(0);
  await expect(node(page, members[0])).toBeVisible();

  await frame.locator(".pg-group-dive").click();
  await expect(page.locator(".pg-crumb")).toContainText("충격 점검");
  const other = doc.groups!.find((g) => g.kind === "strategy" && g.id !== gid)!;
  await expect(rfNode(page, other.members[0])).toHaveClass(/pg-dim/);
  await expect(rfNode(page, members[0])).not.toHaveClass(/pg-dim/);
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-crumb")).toHaveCount(0);
  await expect(page.locator(".react-flow__node.pg-dim")).toHaveCount(0);
});

test("상태 필터(BM C2): 칩 수 = 서버 결과로 센 수 · 켜면 맞지 않는 노드는 흐림 · 끄면 원래대로(짝) · 한 노드를 고르면 닿지 않은 선은 옅게", async ({ page }) => {
  await openCanvas(page);
  await failOneTicker(page);
  const body = await run(page);
  const failed = Object.entries(body.nodes).filter(([, r]) => r.status === "failed").map(([id]) => id);
  const blocked = Object.entries(body.nodes).filter(([, r]) => r.status === "blocked").map(([id]) => id);
  await expect(page.locator(".pg-filter")).toHaveCount(0);                  // 접혀 있다 — 노드를 가리지 않는다
  await page.locator(".pg-filters-toggle").click();
  await expect(page.locator('.pg-filter[data-filter="failed"] .pg-filter-n')).toHaveText(String(failed.length));
  await expect(page.locator('.pg-filter[data-filter="blocked"] .pg-filter-n')).toHaveText(String(blocked.length));
  await page.locator('.pg-filter[data-filter="failed"]').click();
  for (const id of failed) await expect(rfNode(page, id)).not.toHaveClass(/pg-dim/);
  for (const id of blocked) await expect(rfNode(page, id)).toHaveClass(/pg-dim/);
  await page.locator('.pg-filter[data-filter="failed"]').click();
  await expect(page.locator(".react-flow__node.pg-dim")).toHaveCount(0);

  await node(page, "views").click();
  const faint = await page.locator(".react-flow__edge").evaluateAll((es) => es.map((e) => ({
    id: e.getAttribute("data-testid") ?? "", faint: (e.getAttribute("class") ?? "").includes("pg-edge--faint") })));
  for (const e of faint) expect(e.faint, e.id).toBe(!e.id.includes("views"));
});

test("내 블록(BM C2): 저장 → 새로고침해도 남음('이 브라우저에만') → 넣으면 새 전략 띠 · 파일 받기·불러오기 · 다른 포맷은 거부", async ({ page }) => {
  await recordDownloadNames(page);
  await page.addInitScript(() => { try { if (!sessionStorage.getItem("__kept")) { localStorage.removeItem("alpha_pg_blocks"); sessionStorage.setItem("__kept", "1"); } } catch { /* noop */ } });
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const frame = page.locator(".pg-group--strategy").last();
  await frame.locator(".pg-group-label").fill("충격 블록");
  await frame.locator(".pg-group-save").click();
  await expect(page.locator(".pg-note")).toContainText("이 브라우저에만");
  await expect(page.locator(".pg-blocks-where")).toHaveText("이 브라우저에만");
  await page.reload();
  await expect(page.locator('.pg-block[data-block="충격 블록"]')).toBeVisible({ timeout: 30_000 });

  const before = (await wip(page)).groups?.filter((g) => g.kind === "strategy").length ?? 0;
  await page.locator('.pg-block[data-block="충격 블록"] .pg-block-add').click();
  const after = await wip(page);
  expect(after.groups!.filter((g) => g.kind === "strategy").length).toBe(before + 1);
  const pf = after.nodes.find((n) => n.type === "portfolio_combine")!;
  // 같은 이름의 전략이 이미 있으니 겹치지 않게 번호가 붙는다.
  expect(Object.values(pf.params.labels as Record<string, string>)).toContain("충격 블록 2");

  // 파일 받기 → 형식 그대로
  const dl = page.waitForEvent("download");
  await page.locator('.pg-block[data-block="충격 블록"] .pg-block-x').first().click();
  const d = await dl;
  expect(await lastDownloadName(page)).toMatch(/^충격_블록\.pgblock\.json$/);
  const file = JSON.parse(readFileSync((await d.path())!, "utf-8"));
  expect(file.format).toBe("project-alpha.pgblock");
  expect(file.kind).toBe("strategy");
  // 다른 포맷은 넣지 않는다 — 캔버스 그대로.
  const n0 = (await wip(page)).nodes.length;
  await page.locator(".pg-block-input").setInputFiles({ name: "graph.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ format: "project-alpha.portfolio-graph", version: 1, nodes: [], edges: [] })) });
  await expect(page.locator(".pg-blocks-note--err")).toContainText("블록 파일이 아니에요");
  expect((await wip(page)).nodes.length).toBe(n0);
  // 받은 블록 파일은 다시 넣을 수 있다(왕복).
  await page.locator(".pg-block-input").setInputFiles({ name: "충격_블록.pgblock.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(file)) });
  expect((await wip(page)).nodes.length).toBeGreaterThan(n0);
});

test("내 블록: 이 브라우저에 저장할 수 없으면 '없음' 이 아니라 '저장할 수 없음' 이라 말하고, 파일로는 받는다(BM C2)", async ({ page }) => {
  await recordDownloadNames(page);
  await page.addInitScript(() => {
    // 이 브라우저의 블록 저장소만 막는다(세션 저장소의 작업 중 문서는 그대로).
    const ls = window.localStorage;
    const set = Storage.prototype.setItem;
    const get = Storage.prototype.getItem;
    Storage.prototype.setItem = function (k: string, v: string) {
      if (this === ls && k === "alpha_pg_blocks") throw new Error("blocked");
      return set.call(this, k, v);
    };
    Storage.prototype.getItem = function (k: string) {
      if (this === ls && k === "alpha_pg_blocks") throw new Error("blocked");
      return get.call(this, k);
    };
  });
  await openCanvas(page);
  await expect(page.locator(".pg-blocks-note")).toContainText("저장할 수 없어요");
  await addStrategy(page, "tpl:stress");
  const dl = page.waitForEvent("download");
  await page.locator(".pg-group--strategy .pg-group-file").last().click();
  await dl;
  expect(await lastDownloadName(page)).toMatch(/\.pgblock\.json$/);
  await expect(page.locator(".pg-note")).toContainText("파일로 받아 두세요");
});

test("옛 문서(전략 칸 없는 묶음)는 그대로 읽히고 · 전략 문서는 내보내기 → 불러오기 왕복에서 전략 칸이 그대로(BM C2)", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const doc = JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
  const strat = doc.groups.filter((g: { kind?: string }) => g.kind === "strategy");
  expect(strat.length).toBe(2);
  await page.locator(".pg-import-input").setInputFiles({ name: "s.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
  await expect(page.locator(".pg-group--strategy")).toHaveCount(2);
  const back = await wip(page);
  expect(back.groups!.map((g) => [g.label, g.kind, g.output])).toEqual(doc.groups.map((g: { label: string; kind: string; output: string }) => [g.label, g.kind, g.output]));
  // 옛 문서 — kind 가 없으면 그냥 묶음.
  const old = { ...doc, groups: doc.groups.map((g: Record<string, unknown>) => ({ id: g.id, label: g.label, members: g.members })) };
  await page.locator(".pg-import-input").setInputFiles({ name: "old.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(old)) });
  await expect(page.locator(".pg-group--strategy")).toHaveCount(0);
  await expect(page.locator(".pg-group")).toHaveCount(2);
});

test("큰 그래프(BM C2): 전략 열여섯(노드 100개 넘게)을 넣고 지도로 정리해도 깨지지 않고 움직인다 — 그림 시간 기록 · 빈 자리가 없으면 말한다", async ({ page }) => {
  test.setTimeout(360_000);
  let err = "";
  page.on("pageerror", (e) => { err = e.message; });
  await openCanvas(page);
  for (let i = 0; i < 15; i++) await addStrategy(page, i % 2 ? "tpl:stress" : "tpl:rebalance");
  // 포트폴리오 노드의 자리는 8개 — 넘치면 잇지 않았다고 말한다(조용히 버리지 않는다).
  await expect(page.locator(".pg-note")).toContainText("잇지 못했어요");
  const n = (await wip(page)).nodes.length;
  expect(n).toBeGreaterThan(100);
  const t0 = Date.now();
  await page.locator('button[aria-label="자동 정리"]').click();
  await expect(page.locator(".pg-lane--portfolio")).toHaveCount(1);
  const ms = Date.now() - t0;
  test.info().annotations.push({ type: "perf", description: `노드 ${n}개 지도 정리 → 그림 ${ms}ms` });
  await page.mouse.move(700, 600);
  await page.mouse.down();
  await page.mouse.move(500, 500, { steps: 10 });
  await page.mouse.up();
  expect(err).toBe("");
  expect(ms).toBeLessThan(10_000);
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BM C2): ${scheme} — 전략 지도 · 전략 추가 메뉴 · 내 블록 · 필터 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    await addStrategy(page, "tpl:stress");
    await page.locator('button[aria-label="자동 정리"]').click();
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await zoomTo(page, "mid");
    await page.locator(".pg-filters-toggle").click();
    await page.locator(".pg-strat-add").click();
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-root"));
    expect(audit.checked).toBeGreaterThan(60);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}
