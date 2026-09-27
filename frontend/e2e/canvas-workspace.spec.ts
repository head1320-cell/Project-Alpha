import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { contrastAudit, type AuditResult } from "./helpers";
import { fmtElapsed, fmtGlance } from "../src/entities/portfolio-graph/glance";
import { fmtDelta } from "../src/entities/portfolio-graph/branch";

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
  // 선 라벨 = 이음선마다 원천 노드의 서버 briefs[출력 포트] 그대로(완료한 원천만) — 바꿔 보낸 한 줄도, BN N2 에서 더한 요약(생각 n개 등)도.
  const edges = (await page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}"))).edges as { source: string; source_port: string }[];
  const want = edges.map((e) => (body.nodes[e.source]?.status === "ok" ? body.nodes[e.source]?.briefs?.[e.source_port] : undefined))
    .filter((x): x is string => !!x).sort();
  expect(want).toContain("가짜 한 줄");
  await expect.poll(async () => (await page.locator(".pg-wire-brief").allTextContents()).sort()).toEqual(want);
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

test("전략 지도(BM C2 → BN N1): 자동 정리 = 노드와 선만(배경 칸 없음) · 전략마다 한 줄 · 포트폴리오 노드는 오른쪽, 여럿이면 세로로 쌓임", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  await page.locator('button[aria-label="자동 정리"]').click();
  let doc = await wip(page);
  // 그려진 것은 노드 카드와 상자뿐 — 끌 수도 고를 수도 없는 배경 노드(레인)가 없다.
  await expect(page.locator(".react-flow__node")).toHaveCount(doc.nodes.length + doc.groups!.length);
  const [a, b] = (doc.groups ?? []).filter((g) => g.kind === "strategy");
  const y = (id: string) => doc.nodes.find((n) => n.id === id)!.position.y;
  const x = (id: string) => doc.nodes.find((n) => n.id === id)!.position.x;
  expect(Math.min(...b.members.map(y)), "두 번째 전략 줄은 첫 줄 아래").toBeGreaterThan(Math.max(...a.members.map(y)));
  for (const g of [a, b]) {
    // 줄 안은 흐름 순서대로 왼쪽 → 오른쪽: 선은 늘 오른쪽으로 간다.
    for (const e of doc.edges.filter((e) => g.members.includes(e.source) && g.members.includes(e.target))) {
      expect(x(e.target), `${e.source} → ${e.target}`).toBeGreaterThan(x(e.source));
    }
  }
  const pf = doc.nodes.find((n) => n.type === "portfolio_combine")!;
  expect(pf.position.x).toBeGreaterThan(Math.max(...[...a.members, ...b.members].map(x)));

  // 포트폴리오 노드가 둘이면 같은 열에 세로로 쌓인다(겹치지 않는다).
  const two = JSON.parse(JSON.stringify(doc)) as Doc;
  two.nodes.push({ ...pf, id: "pf_two" });
  for (const e of doc.edges.filter((e) => e.target === pf.id)) two.edges.push({ ...e, target: "pf_two" });
  await page.locator(".pg-import-input").setInputFiles({ name: "two.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(two)) });
  await expect(node(page, "pf_two")).toBeVisible();
  await page.locator('button[aria-label="자동 정리"]').click();
  doc = await wip(page);
  const p1 = doc.nodes.find((n) => n.id === pf.id)!.position;
  const p2 = doc.nodes.find((n) => n.id === "pf_two")!.position;
  expect(p2.x).toBe(p1.x);
  expect(Math.abs(p2.y - p1.y)).toBeGreaterThanOrEqual(170);

  // 짝 — 전략이 없으면 예전 정리(깊이 × 230).
  await page.locator('.pg-template[data-template="core"]').click();
  await page.locator('button[aria-label="자동 정리"]').click();
  doc = await wip(page);
  expect(doc.nodes.find((n) => n.id === "optimizer")!.position.x % 230).toBe(0);
  await expect(page.locator(".react-flow__node")).toHaveCount(doc.nodes.length);
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
  await expect.poll(async () => {
    const d = await wip(page);
    const pfx = Math.max(...d.nodes.filter((x) => x.type === "portfolio_combine").map((x) => x.position.x));
    return pfx > Math.max(...d.nodes.filter((x) => x.type !== "portfolio_combine").map((x) => x.position.x));
  }, { timeout: 10_000 }).toBe(true);
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

// ═══════════════════════════════════════════════════════════════════════════════
// C3 · 갈래 만들기 + 차이만 보기 — 거는 것:
//  · 갈래 = 뿌리 + 하류 복제 · 들어오는 선은 원본과 같이 · ★나가는 선은 잇지 않는다★ · 한 뿌리에 4개까지(5번째 거절 + 사유)
//  · 바꾼 설정만 칩 · 비교 표는 ★값이 다른 행만★(서버 결과로 센 수와 같다) · 계산 못 한 칸 "—" · Δ 는 같은 이름·단위일 때만
//  · 다중 비교 정직성 문장 · 추천·순위 없음 · 지우기 · 되돌리기 · 파일 왕복
// ═══════════════════════════════════════════════════════════════════════════════

type BDoc = Doc & { branches?: { id: string; label: string; root: string; of_root: string; map: Record<string, string> }[] };
async function makeBranch(page: Page, id: string, via: "toolbar" | "command" = "toolbar") {
  if (via === "toolbar") {
    await node(page, id).click();
    await page.locator(".pg-branch-make").click();
  } else {
    // 키보드 길 — 이야기에서 고르고 명령 찾기(Ctrl+K)로. 갈래가 쌓여 원본이 화면 밖이어도 된다.
    await page.locator('.pg-tab[data-tab="story"]').click();
    await page.locator(`.pg-step[data-node-id="${id}"] .pg-step-num`).click();
    await page.keyboard.press("Control+k");
    await page.getByLabel("명령 찾기").last().fill("갈래 만들기");
    await page.keyboard.press("Enter");
  }
  await expect(page.locator(".pg-note")).toBeVisible();
}

test("갈래(BM C3): 뿌리와 하류를 복제 · 들어오는 선은 원본과 같이 · 나가는 선은 잇지 않음 · 5번째 갈래는 사유와 함께 거절", async ({ page }) => {
  await openCanvas(page);
  await makeBranch(page, "optimizer");
  let doc = (await wip(page)) as BDoc;
  expect(doc.branches?.length).toBe(1);
  const b = doc.branches![0];
  expect(b.label).toBe("갈래 B");
  expect(new Set(Object.values(b.map))).toEqual(new Set(["optimizer", "risk", "backtest"]));
  const copies = new Set(Object.keys(b.map));
  const into = (id: string) => doc.edges.filter((e) => e.target === id).map((e) => `${copies.has(e.source) ? b.map[e.source] : e.source}.${e.source_port}->${e.target_port}`).sort();
  for (const [c, o] of Object.entries(b.map)) expect(into(c), c).toEqual(into(o));
  expect(doc.edges.filter((e) => copies.has(e.source) && !copies.has(e.target)), "갈래 밖으로 나가는 선").toEqual([]);
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  await expect(page.locator(".pg-branch .pg-branch-same")).toBeVisible();          // 아직 원본과 같다 — 만든 직후 화면은 읽을 수 있는 확대
  const boxes: { y: number; h: number }[] = [];

  for (const l of ["C", "D", "E"]) {
    await makeBranch(page, "optimizer", "command");
    doc = (await wip(page)) as BDoc;
    expect(doc.branches!.map((x) => x.label)).toContain(`갈래 ${l}`);
  }
  // 갈래 틀끼리 겹치지 않는다.
  for (const b of await page.locator(".pg-branch").all()) { const r = (await b.boundingBox())!; boxes.push({ y: r.y, h: r.height }); }
  boxes.sort((a, z) => a.y - z.y);
  for (let i = 1; i < boxes.length; i++) expect(boxes[i].y, "갈래 틀 겹침").toBeGreaterThanOrEqual(boxes[i - 1].y + boxes[i - 1].h - 1);
  await makeBranch(page, "optimizer", "command");
  await expect(page.locator(".pg-note")).toContainText("4개까지");
  expect(((await wip(page)) as BDoc).branches!.length).toBe(4);
});

test("차이만 보기(BM C3): 바꾼 설정 칩 · 표는 값이 다른 행만(서버 결과로 센 수) · Δ = 같은 이름·단위일 때만 · 정직성 문장 · 추천 없음", async ({ page }) => {
  await openCanvas(page);
  await makeBranch(page, "optimizer");
  const doc = (await wip(page)) as BDoc;
  const b = doc.branches![0];
  const copyOf = (o: string) => Object.entries(b.map).find(([, x]) => x === o)![0];
  const opt = doc.nodes.find((n) => n.id === copyOf("optimizer"))!;
  opt.params = { ...opt.params, model: "min_var" };
  await page.locator(".pg-import-input").setInputFiles({ name: "b.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ format: "project-alpha.portfolio-graph", version: 1, ...doc })) });
  await expect(page.locator(".pg-branch-chip").first()).toContainText("→");
  const body = await run(page);
  const head = (id: string) => {
    const r = body.nodes[id] as NodeRes & { explain?: { headline?: { value: number | null; unit: string; label: string } | null } };
    if (r.status !== "ok") return r.status === "blocked" ? "막힘" : "실패";
    const h = r.explain?.headline;
    if (!h || h.value === null) return "—";
    return `${Number.isInteger(h.value) ? h.value : h.value.toFixed(2)}${h.unit ?? ""}`;
  };
  const differing = Object.entries(b.map).filter(([c, o]) => head(c) !== head(o)).length;
  expect(differing, "방식을 바꿨으니 적어도 한 결과는 달라야 한다(빈 표로 통과하지 않게)").toBeGreaterThan(0);
  await page.locator('.pg-tab[data-tab="branches"]').click();
  await expect(page.locator(".pg-branch-honest")).toContainText("우연히 좋아 보이는");
  await expect(page.locator(".pg-branch-row--set")).toHaveCount(1);
  await expect(page.locator(".pg-branch-row--out")).toHaveCount(differing);
  const panel = (await page.locator(".pg-branch-compare").textContent()) ?? "";
  expect(panel).not.toMatch(/추천|가장 좋은|최고|우월|더 나은/);
  // Δ — 복제 카드의 칩은 원본과 같은 이름·단위의 헤드라인일 때만, 값은 서버 두 수의 차.
  let checked = 0;
  for (const [c, o] of Object.entries(b.map)) {
    type H = { value: number | null; unit: string; label: string } | null | undefined;
    const hc = (body.nodes[c] as { explain?: { headline?: H } }).explain?.headline;
    const ho = (body.nodes[o] as { explain?: { headline?: H } }).explain?.headline;
    const same = body.nodes[c].status === "ok" && body.nodes[o].status === "ok" && hc && ho && hc.value !== null && ho.value !== null
      && hc.unit === ho.unit && hc.label === ho.label;
    const chip = node(page, c).locator(".pg-node-delta b");
    if (same) { checked += 1; await expect(chip, c).toHaveText(fmtDelta({ value: hc!.value! - ho!.value!, unit: ho!.unit === "%" ? "%p" : ho!.unit })); }
    else await expect(chip, c).toHaveCount(0);
  }
  expect(checked, "Δ 칩을 적어도 하나는 확인한다").toBeGreaterThan(0);
});

test("갈래 지우기·되돌리기·파일 왕복(BM C3): 지우면 복제도 함께 · Ctrl+Z 로 돌아옴 · 내보내고 불러와도 갈래 그대로", async ({ page }) => {
  await openCanvas(page);
  const n0 = (await wip(page)).nodes.length;
  await makeBranch(page, "optimizer");
  await page.keyboard.press("Escape");
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  expect((await wip(page)).nodes.length).toBe(n0);
  expect(((await wip(page)) as BDoc).branches ?? []).toEqual([]);
  await page.keyboard.press("Control+Shift+z");
  expect(((await wip(page)) as BDoc).branches?.length).toBe(1);

  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const file = JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
  expect(file.branches.length).toBe(1);
  await page.locator(".pg-import-input").setInputFiles({ name: "x.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(file)) });
  await expect(page.locator(".pg-branch")).toHaveCount(1);

  await page.locator(".pg-branch-x").click();
  await expect(page.locator(".pg-branch")).toHaveCount(0);
  expect((await wip(page)).nodes.length).toBe(n0);
  await expect(page.locator('.pg-tab[data-tab="branches"]')).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BM C3): ${scheme} — 갈래 틀 · 비교 표 · 정직성 문장 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    await makeBranch(page, "optimizer");
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.locator('.pg-tab[data-tab="branches"]').click();
    await zoomTo(page, "mid");
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-root"));
    expect(audit.checked).toBeGreaterThan(60);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// C4 · 처음 쓰는 사람 — 목표로 시작 + 간단히 보기. 거는 것:
//  · 목표 → 종목 → 기간(서버 프리셋) → 흐름이 조립되고 곧바로 계산 · 답은 기본 층 파라미터에만(기본값을 고르면 키가 없다 — 짝)
//  · 읽지 못한 종목 코드는 버리지 않고 말함 · 종목 수가 모자라면 다음으로 못 감(짝) · 되돌리기로 이전 캔버스
//  · 자라나는 흐름은 한 번, 감속 모션이면 없음 · 빈 캔버스는 시작하라고 말함
//  · 간단히 보기: 정할 것(설정 탭과 같은 위젯) · 결과(서버 값 그대로) · 바꾸면 노드 설정 · 막힘은 캔버스의 원인 경로로
// ═══════════════════════════════════════════════════════════════════════════════

async function startGoal(page: Page, goal: string, tickers: string, period?: number | "default") {
  await page.locator(".pg-goal-open").click();
  await expect(page.locator(".pg-goal-card")).toHaveCount(4);
  await page.locator(`.pg-goal-card[data-goal="${goal}"]`).click();
  await page.locator(".pg-goal-input").fill(tickers);
  if (period !== undefined) {
    await page.locator(".pg-goal-next").click();
    if (period === "default") await page.locator(".pg-goal-period").first().click();
    else await page.locator(`.pg-goal-period[data-days="${period}"]`).click();
  }
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-goal-go").click();
  return (await (await resp).json()) as RunBody;
}

test("목표로 시작(BM C4): 목표 → 종목 → 서버 프리셋 기간 → 흐름 조립 + 곧바로 계산 · 되돌리기로 이전 캔버스", async ({ page }) => {
  await openCanvas(page);
  const before = (await wip(page)).nodes.map((n) => n.id).sort();
  const cat = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  const presets = (cat.nodes.find((c: { type: string }) => c.type === "returns").params_schema.properties.lookback_days["x-ui"].presets as { value: number }[]);
  const pick = presets[0].value;
  // 읽지 못한 코드는 말하고 뺀다 · 두 개 미만이면 다음으로 못 간다(짝).
  await page.locator(".pg-goal-open").click();
  await page.locator('.pg-goal-card[data-goal="build"]').click();
  await page.locator(".pg-goal-input").fill("005930, 삼성");
  await expect(page.locator(".pg-goal-help")).toContainText("‘삼성’");
  await expect(page.locator(".pg-goal-next")).toBeDisabled();
  await page.locator(".pg-goal-input").fill("005930, 000660");
  await expect(page.locator(".pg-goal-next")).toBeEnabled();
  await page.locator(".pg-goal-next").click();
  await expect(page.locator(".pg-goal-period")).toHaveCount(presets.length + 1);          // 기본값 + 서버 프리셋
  await page.keyboard.press("Escape");

  const body = await startGoal(page, "build", "005930, 000660", pick);
  const doc = await wip(page);
  expect(doc.nodes.find((n) => n.type === "universe")!.params.tickers).toEqual(["005930", "000660"]);
  expect(doc.nodes.find((n) => n.type === "returns")!.params.lookback_days).toBe(pick);
  expect(Object.values(body.nodes).some((r) => r.status === "ok")).toBe(true);
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  expect((await wip(page)).nodes.map((n) => n.id).sort()).toEqual(before);
});

test("목표로 시작: 기간을 '기본값' 으로 두면 키를 넣지 않는다(서버 기본값) · 기업 하나는 두 단계 · 결과는 완료 아니면 사유(BM C4)", async ({ page }) => {
  await openCanvas(page);
  await startGoal(page, "check", "005930, 000660, 035420", "default");
  const doc = await wip(page);
  expect("lookback_days" in doc.nodes.find((n) => n.type === "returns")!.params).toBe(false);

  await page.locator(".pg-goal-open").click();
  await page.locator('.pg-goal-card[data-goal="company"]').click();
  await expect(page.locator(".pg-goal-step")).toHaveText("2 / 2");                 // 기간을 묻지 않는다
  await page.keyboard.press("Escape");
  const body = await startGoal(page, "company", "000660");
  const d2 = await wip(page);
  expect(d2.nodes.map((n) => n.type).sort()).toEqual(["company_valuation", "valuation_distribution"]);
  for (const n of d2.nodes) expect(n.params.code).toBe("000660");
  for (const r of Object.values(body.nodes)) expect(r.status === "ok" || !!r.reason, JSON.stringify(r).slice(0, 200)).toBe(true);
});

test("자라나는 흐름(BM C4): 시작한 뒤 한 번 · 흐름 번호 순서로 늦게 · 감속 모션이면 없음(짝)", async ({ page }) => {
  await openCanvas(page);
  await page.locator(".pg-goal-open").click();
  await page.locator('.pg-goal-card[data-goal="build"]').click();
  await page.locator(".pg-goal-next").click();
  await page.locator(".pg-goal-go").click();
  await expect(page.locator(".pg-canvas")).toHaveClass(/pg-growing/);
  const anim = await node(page, "optimizer").evaluate((el) => ({ name: getComputedStyle(el).animationName, delay: getComputedStyle(el).animationDelay }));
  expect(anim.name).toBe("pg-grow");
  const d1 = await node(page, "universe").evaluate((el) => parseFloat(getComputedStyle(el).animationDelay));
  expect(parseFloat(anim.delay)).toBeGreaterThan(d1);
  await expect(page.locator(".pg-canvas")).not.toHaveClass(/pg-growing/, { timeout: 5_000 });

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.locator(".pg-goal-open").click();
  await page.locator('.pg-goal-card[data-goal="build"]').click();
  await page.locator(".pg-goal-next").click();
  await page.locator(".pg-goal-go").click();
  await expect(page.locator(".pg-canvas")).toHaveClass(/pg-growing/);
  expect(await node(page, "optimizer").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
});

test("빈 캔버스는 시작하라고 말한다 — 누르면 목표로 시작(BM C4)", async ({ page }) => {
  await openCanvas(page);
  await page.locator(".pg-import-input").setInputFiles({ name: "empty.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ format: "project-alpha.portfolio-graph", version: 1, nodes: [], edges: [] })) });
  await expect(page.locator(".pg-empty-start")).toContainText("비어 있어요");
  await page.locator(".pg-empty-start button").click();
  await expect(page.locator(".pg-goal-card")).toHaveCount(4);
});

test("간단히 보기(BM C4): 노드 대신 정할 것 → 결과 · 결과 = 서버 값 · 바꾸면 노드 설정이 바뀌고 낡음 · 막힘은 캔버스 원인 경로로", async ({ page }) => {
  await openCanvas(page);
  await page.locator(".pg-simple-toggle").click();
  await expect(page.locator(".pg-simple")).toBeVisible();
  await expect(page.locator(".pg-body")).toBeHidden();
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-simple-run").click();
  const body = (await (await resp).json()) as RunBody;
  type Ex = { explain?: { headline?: { value: number | null } | null } };
  const shown = Object.entries(body.nodes).filter(([, r]) => r.status !== "ok" || (r as Ex).explain?.headline || r.glance).map(([id]) => id);
  await expect(page.locator(".pg-simple-result")).toHaveCount(shown.length);
  const h = (body.nodes.optimizer as Ex).explain!.headline!.value!;
  await expect(page.locator('.pg-simple-result[data-node-id="optimizer"] .pg-simple-headline b')).toHaveText(Number.isInteger(h) ? String(h) : h.toFixed(1));
  // 질문을 바꾸면 노드 설정이 바뀐다(같은 위젯 · 같은 스토어).
  const ask = page.locator('.pg-simple-ask[data-node-id="universe"] input').first();
  await ask.fill("005930");
  await ask.press("Enter");
  await expect(page.locator(".pg-simple-stale")).toBeVisible();
  expect((await wip(page)).nodes.find((n) => n.id === "universe")!.params.tickers).toEqual(["005930"]);
  const resp2 = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-simple-run").click();
  await resp2;
  const blocked = page.locator(".pg-simple-result--blocked, .pg-simple-result--failed").first();
  await expect(blocked).toBeVisible();
  await blocked.locator(".pg-cause-btn").click();
  await expect(page.locator(".pg-simple")).toHaveCount(0);
  await expect(page.locator(".pg-cause-banner")).toContainText("첫 원인");
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BM C4): ${scheme} — 목표로 시작 · 간단히 보기 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.locator(".pg-goal-open").click();
    let audit = await page.evaluate<AuditResult>(contrastAudit(".pg-goal"));
    expect(audit.checked).toBeGreaterThan(8);
    expect(audit.low, `${scheme} 목표 AA`).toEqual([]);
    await page.keyboard.press("Escape");
    await page.locator(".pg-simple-toggle").click();
    await page.locator(".pg-simple-run").click();
    await expect(page.locator(".pg-simple-result").first()).toBeVisible({ timeout: 120_000 });
    audit = await page.evaluate<AuditResult>(contrastAudit(".pg-simple"));
    expect(audit.checked).toBeGreaterThan(30);
    expect(audit.low, `${scheme} 간단히 보기 AA`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// BN N1 · 전략 지도도 노드와 선(사용자 결정: "원래 캔버스의 노드 링크 UI") — 거는 것:
//  · 접은 전략 = 노드 카드 한 장: 노드 수 · 이름 · 몫 = ★그 전략 포트의 서버 share_pct★(응답을 바꾸면 따라온다) · 계산 전 "—"
//    · 서버가 몫을 주지 않으면 "—" 와 이유, 도넛 조각도 없다(짝) · 포트폴리오에 잇지 않은 전략은 그 이유(짝)
//  · 선은 그대로 — 합치기로 들어가는 선도 몫과 상관없이 같은 굵기·포트 타입 색
//  · 포트폴리오 노드의 입력 자리: 이은 자리 + 빈 자리 하나만 · 이은 자리 이름 = 전략 이름
//  · 이 전략만 계산(상자 머리·접은 카드) = 전략 안에서 하류가 없는 노드만 대상 · 다른 전략은 이전 결과
//  · 전략째 갈래 — 전략 노드 전부 복제 · 포트폴리오로 나가는 선은 잇지 않음 · 되돌리기
// ═══════════════════════════════════════════════════════════════════════════════

type Strat = NonNullable<Doc["groups"]>[number];
const strategiesOf = (doc: Doc) => (doc.groups ?? []).filter((g) => g.kind === "strategy");
const portfolioOf = (doc: Doc) => doc.nodes.find((n) => n.type === "portfolio_combine")!;
const portOf = (doc: Doc, g: Strat) => doc.edges.find((e) => e.source === g.output && e.target === portfolioOf(doc).id)!.target_port;
type ShareRow = { port: string; share_pct?: number };
const shareRows = (body: RunBody, pfId: string) => ((body.nodes[pfId] as NodeRes & { view: { strategies: ShareRow[] } }).view.strategies);

test("접은 전략 = 노드 카드(BN N1): 몫 = 그 포트의 서버 값(바꿔 보내면 따라옴) · 계산 전 '—' · 서버가 안 주면 '—'+이유, 도넛 조각 없음(짝)", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const doc = await wip(page);
  const pf = portfolioOf(doc);
  const [a, b] = strategiesOf(doc);
  const frameB = page.locator(`.pg-group--strategy[data-group-id="${b.id}"]`);
  await page.locator(`.pg-group--strategy[data-group-id="${a.id}"] .pg-group-toggle`).click();
  const card = page.locator(`.pg-snode[data-group-id="${a.id}"]`);
  await expect(card.locator(".pg-node-k")).toHaveText(`전략 · 노드 ${a.members.length}개`);
  await expect(card.locator(".pg-snode-name")).toHaveValue(a.label);
  await expect(card.locator(".pg-snode-share")).toHaveAttribute("data-share", "");
  await expect(card.locator(".pg-snode-share")).toContainText("계산하면 보여요");
  await expect(frameB.locator(".pg-group-share")).toHaveText("몫 —");

  const fake: Record<string, number> = { [portOf(doc, a)]: 61.2, [portOf(doc, b)]: 38.8 };
  await patchRun(page, (body) => { for (const r of shareRows(body, pf.id)) r.share_pct = fake[r.port]; });
  await run(page);
  await expect(card.locator(".pg-snode-share")).toHaveAttribute("data-share", "61.2");
  await expect(card.locator(".pg-snode-share b")).toHaveText("61.2%");
  await expect(frameB.locator(".pg-group-share")).toHaveText("몫 38.8%");
  const donut = node(page, pf.id).locator(".pg-donut");
  await expect(donut.locator(`circle[data-port="${portOf(doc, a)}"]`)).toHaveAttribute("data-share", "61.2");
  await expect(donut.locator(`circle[data-port="${portOf(doc, b)}"]`)).toHaveAttribute("data-share", "38.8");
  await expect(donut.locator(`li[data-port="${portOf(doc, a)}"] b`)).toHaveText("61.2%");

  // 선은 그대로 — 몫이 61 대 39 여도 합치기로 들어가는 두 선은 같은 굵기, 비중(Weights) 색.
  const into = page.locator(`.react-flow__edge[aria-label$=" to ${pf.id}"] .react-flow__edge-path`);
  await expect(into).toHaveCount(2);
  const styles = await into.evaluateAll((ps) => ps.map((p) => [getComputedStyle(p).strokeWidth, getComputedStyle(p).stroke]));
  expect(new Set(styles.map((x) => x[0]))).toEqual(new Set(["2.5px"]));
  expect(new Set(styles.map((x) => x[1]))).toEqual(new Set(["rgb(22, 163, 74)"]));

  // 짝 — 서버가 A 의 몫을 주지 않으면: "—" 와 이유 · 도넛 조각 없음 · 목록 "—" (0·균등으로 채우지 않는다).
  await patchRun(page, (body) => { for (const r of shareRows(body, pf.id)) if (r.port === portOf(doc, a)) delete r.share_pct; });
  await run(page);
  await expect(card.locator(".pg-snode-share")).toHaveAttribute("data-share", "");
  await expect(card.locator(".pg-snode-share")).toContainText("몫을 모름");
  await expect(donut.locator(`circle[data-port="${portOf(doc, a)}"]`)).toHaveCount(0);
  await expect(donut.locator(`li[data-port="${portOf(doc, a)}"] b`)).toHaveText("—");
  await expect(frameB.locator(".pg-group-share")).not.toHaveText("몫 —");
});

test("포트폴리오 노드의 입력 자리(BN N1): 이은 자리 + 빈 자리 하나만 · 이은 자리 이름 = 전략 이름 · 잇지 않은 전략 카드는 그 이유(짝)", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  let doc = await wip(page);
  const pf = portfolioOf(doc);
  const handles = () => page.locator(`.react-flow__node[data-id="${pf.id}"] .react-flow__handle.target`);
  const portName = (port: string) => node(page, pf.id).locator(`.pg-port:has(.react-flow__handle[data-handleid="${port}"]) .pg-port-name`);
  await expect(handles()).toHaveCount(3);                                   // s1·s2 + 빈 자리 하나 — 여덟 자리를 늘어놓지 않는다
  const labels = pf.params.labels as Record<string, string>;
  for (const [port, label] of Object.entries(labels)) await expect(portName(port)).toHaveText(label);
  await expect(portName("s3")).toHaveText("전략 더 잇기");
  await addStrategy(page, "tpl:rebalance");
  await expect(handles()).toHaveCount(4);

  // 짝 — 세 번째 전략의 선을 빼고 불러오면 자리는 다시 셋이고, 그 전략 카드는 몫 대신 "포트폴리오에 잇지 않았어요".
  doc = await wip(page);
  const third = strategiesOf(doc)[2];
  const port3 = portOf(doc, third);
  const cut = JSON.parse(JSON.stringify(doc)) as Doc;
  cut.edges = cut.edges.filter((e) => !(e.source === third.output && e.target === pf.id));
  const pfCut = cut.nodes.find((n) => n.id === pf.id)!;
  delete (pfCut.params.labels as Record<string, string>)[port3];
  await page.locator(".pg-import-input").setInputFiles({ name: "cut.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(cut)) });
  await expect(handles()).toHaveCount(3);
  await run(page);
  await page.locator(`.pg-group--strategy[data-group-id="${third.id}"] .pg-group-toggle`).click();
  await expect(page.locator(`.pg-snode[data-group-id="${third.id}"] .pg-snode-share`)).toContainText("포트폴리오에 잇지 않았어요");
  await expect(page.locator(`.pg-snode[data-group-id="${third.id}"] .pg-snode-share`)).toHaveAttribute("data-share", "");
});

test("이 전략만 계산(BN N1): 상자 머리·접은 카드 — 대상 = 전략 안에서 하류가 없는 노드 · 다른 전략은 이전 결과로 남음", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  await run(page);
  const doc = await wip(page);
  const [a, b] = strategiesOf(doc);
  const leaves = (g: Strat) => g.members.filter((m) => !doc.edges.some((e) => e.source === m && g.members.includes(e.target))).sort();
  const targetsOf = async (click: () => Promise<void>) => {
    const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
    await click();
    return (new URL((await resp).url()).searchParams.get("targets") ?? "").split(",").sort();
  };
  expect(await targetsOf(() => page.locator(`.pg-group--strategy[data-group-id="${b.id}"] .pg-group-run`).click())).toEqual(leaves(b));
  await expect(node(page, a.members[0])).toHaveClass(/pg-node--previous/);
  await expect(node(page, b.output!)).not.toHaveClass(/pg-node--previous/);

  await page.locator(`.pg-group--strategy[data-group-id="${a.id}"] .pg-group-toggle`).click();
  // 두 전략을 다 담으면 멀리 확대라 카드는 이름·몫만 보인다(노드 카드와 같은 규칙) — 여기서는 단추가 부르는 동작만 확인한다.
  expect(await targetsOf(() => page.locator(`.pg-snode[data-group-id="${a.id}"] .pg-group-run`).dispatchEvent("click"))).toEqual(leaves(a));
  await expect(node(page, b.output!)).toHaveClass(/pg-node--previous/);
});

test("전략째 갈래(BN N1): 상자 머리에서 — 전략 노드 전부 복제 · 안쪽 선은 복제끼리 · 포트폴리오로 나가는 선은 잇지 않음 · 되돌리기", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  let doc = (await wip(page)) as BDoc;
  const [, b] = strategiesOf(doc);
  const pf = portfolioOf(doc);
  await page.locator(`.pg-group--strategy[data-group-id="${b.id}"] .pg-group-branch`).click();
  await expect(page.locator(".pg-note")).toContainText("갈래");
  doc = (await wip(page)) as BDoc;
  expect(doc.branches).toHaveLength(1);
  const br = doc.branches![0];
  expect(Object.values(br.map).sort()).toEqual([...b.members].sort());
  const copies = Object.keys(br.map);
  expect(doc.edges.filter((e) => copies.includes(e.source) && e.target === pf.id)).toEqual([]);
  const inner = (ids: string[]) => doc.edges.filter((e) => ids.includes(e.source) && ids.includes(e.target)).length;
  expect(inner(copies)).toBe(inner(b.members));
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  await expect(page.locator(".pg-branch")).toHaveCount(0);
  expect(((await wip(page)) as BDoc).branches ?? []).toEqual([]);
});

test("맞춰 보기(BN N1 에서 찾은 결함): 떠 있는 판(선 범례·안내 줄)이 맨 위 상자 머리와 노드를 가리지 않는다 — 자동 정리 뒤·맞춤 버튼 뒤", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });                 // 다 담기는 크기 — 넘치는 경우는 아래에서 따로
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  await addStrategy(page, "tpl:rebalance");
  await run(page);                                                          // 선 범례는 계산한 뒤에 뜬다
  const check = async (when: string) => {
    await page.waitForTimeout(300);
    const legend = (await page.locator(".pg-wire-legend").boundingBox())!;
    const filters = (await page.locator(".pg-filters-toggle").boundingBox())!;
    const hint = (await page.locator(".pg-hint").boundingBox())!;
    const tops = await page.locator(".react-flow__node:not([style*='visibility: hidden'])").evaluateAll((els) =>
      els.filter((e) => (e as HTMLElement).offsetParent !== null).map((e) => { const r = e.getBoundingClientRect(); return [r.top, r.bottom]; }));
    expect(Math.min(...tops.map((t) => t[0])), `${when}: 가장 위 노드·상자가 선 범례·걸러 보기 아래`)
      .toBeGreaterThanOrEqual(Math.max(legend.y + legend.height, filters.y + filters.height));
    expect(Math.max(...tops.map((t) => t[1])), `${when}: 가장 아래 노드가 안내 줄 위`).toBeLessThanOrEqual(hint.y);
    // 맨 위 전략 상자의 접기 단추를 실제로 누를 수 있다(가로막히면 trial 이 실패한다).
    await page.locator(".pg-group--strategy .pg-group-toggle").first().click({ trial: true, timeout: 3_000 });
  };
  await page.locator('button[aria-label="자동 정리"]').click();
  await check("자동 정리 뒤");
  await page.mouse.move(700, 600);
  await page.mouse.wheel(0, 400);
  await page.locator(".react-flow__controls-fitview").click();
  await check("맞춤 버튼 뒤");

  // 짝 — 가장 작게 줄여도 넘치는 작은 창: 가운데 두지 않고 흐름의 시작에 붙인다(맨 위 머리는 여전히 판 아래·누를 수 있다).
  await page.setViewportSize({ width: 1024, height: 560 });
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
  const legend = (await page.locator(".pg-wire-legend").boundingBox())!;
  const top = await page.locator(".react-flow__node").evaluateAll((els) =>
    Math.min(...els.filter((e) => (e as HTMLElement).offsetParent !== null).map((e) => e.getBoundingClientRect().top)));
  expect(top).toBeGreaterThanOrEqual(legend.y + legend.height);
  await page.locator(".pg-group--strategy .pg-group-toggle").first().click({ trial: true, timeout: 3_000 });
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BN N1): ${scheme} — 접은 전략 카드 · 상자 머리 몫 · 포트폴리오 도넛·자리 이름 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    await addStrategy(page, "tpl:stress");
    await page.locator('button[aria-label="자동 정리"]').click();
    await run(page);
    const doc = await wip(page);
    const [a] = strategiesOf(doc);
    await page.locator(`.pg-group--strategy[data-group-id="${a.id}"] .pg-group-toggle`).click();
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await zoomTo(page, "mid");
    await expect(page.locator(".pg-snode .pg-snode-share b")).toBeVisible();
    await node(page, portfolioOf(doc).id).hover();
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-canvas"));
    expect(audit.checked).toBeGreaterThan(30);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// BN N2 · BM 이 하지 않고 남긴 것 — 거는 것:
//  · 그림 고정이 파일에 남는다(pinned 왕복) · 없는 노드를 가리키는 고정은 불러올 때 뺀다(짝)
//  · 갈래 승격 — 복제의 설정이 원본으로 가고 갈래·복제는 사라짐 · 결과는 낡음 · 되돌리기 한 번으로 돌아옴
//  · 첫 방문 환영 줄 — 한 번 · 닫으면 다시 안 뜸 · [목표로 시작] · 저장소가 막히면 늘 뜨되 닫힘(짝)
//  · 종목 이름 — 칩 "이름 · 코드"(서버 이름) · 모르는 코드는 "이름 모름"(짝) · 이름으로 찾으면 후보 = 서버 검색 · 골라 넣기 ·
//    검색이 실패하면 빈 목록이 아니라 실패라고 말함
//  · 위험 회피 δ — 초심자 질문에서 빠짐(전문가에서만) · 도움말이 어디서만 쓰이는지 말함
// ═══════════════════════════════════════════════════════════════════════════════

test("그림 고정이 파일에 남는다(BN N2): 내보내기 → 불러오기 왕복 · 없는 노드를 가리키는 고정은 뺀다(짝)", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await page.locator(".pg-pin").click();
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--pinned/);
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const doc = JSON.parse(readFileSync((await (await dl).path())!, "utf-8"));
  expect(doc.pinned).toEqual(["optimizer"]);
  await page.locator('.pg-template[data-template="core"]').click();
  await expect(node(page, "optimizer")).not.toHaveClass(/pg-node--pinned/);
  const withGhost = { ...doc, pinned: ["optimizer", "no_such_node"] };
  await page.locator(".pg-import-input").setInputFiles({ name: "p.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(withGhost)) });
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--pinned/);
  expect((await wip(page) as Doc & { pinned?: string[] }).pinned).toEqual(["optimizer"]);
});

test("갈래 승격(BN N2): '이 갈래를 원본으로' — 바꾼 설정이 원본으로 · 갈래·복제는 사라짐 · 결과 낡음 · 되돌리기 한 번", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  await makeBranch(page, "optimizer");
  let doc = (await wip(page)) as BDoc;
  const br = doc.branches![0];
  const copy = Object.entries(br.map).find(([, o]) => o === "optimizer")![0];
  await node(page, copy).click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="constraints"] .pg-chip', { hasText: "20%" }).click();
  const n0 = doc.nodes.length;
  const before = JSON.stringify(doc.nodes.find((n) => n.id === "optimizer")!.params.constraints ?? null);
  await page.locator(`.pg-branch[data-branch-id="${br.id}"] .pg-branch-promote`).click();
  await expect(page.locator(".pg-note")).toContainText("원본으로 옮겼어요");
  doc = (await wip(page)) as BDoc;
  expect(doc.branches ?? []).toEqual([]);
  expect(doc.nodes.find((n) => n.id === "optimizer")!.params.constraints).toEqual({ max_weight_pct: 20 });
  expect(doc.nodes.some((n) => n.id === copy)).toBe(false);
  expect(doc.nodes.length).toBe(n0 - Object.keys(br.map).length);
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  doc = (await wip(page)) as BDoc;
  expect(doc.branches).toHaveLength(1);
  expect(JSON.stringify(doc.nodes.find((n) => n.id === "optimizer")!.params.constraints ?? null)).toBe(before);
});

test.describe("첫 방문(BN N2)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });                 // 이 묶음만 처음 온 사람

  test("환영 줄: 처음이면 한 줄 · 캔버스를 가리지 않음 · 닫으면 새로고침해도 다시 안 뜸 · [목표로 시작]", async ({ page }) => {
    await openCanvas(page);
    const w = page.locator(".pg-welcome");
    await expect(w).toBeVisible();
    await expect(w).toContainText("처음이세요");
    // 가리지 않는다 — 맞춰 본 노드들은 환영 줄 위에 있다.
    const wb = (await w.boundingBox())!;
    const bottoms = await page.locator(".react-flow__node").evaluateAll((els) => els.map((e) => e.getBoundingClientRect().bottom));
    expect(Math.max(...bottoms)).toBeLessThanOrEqual(wb.y);
    await w.locator(".pg-welcome-go").click();
    await expect(page.locator(".pg-goal")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(w).toHaveCount(0);                                          // 목표로 시작을 눌렀으니 본 것
    await page.reload();
    await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".pg-welcome")).toHaveCount(0);
  });

  test("환영 줄 짝: 이 브라우저에 적을 수 없으면 올 때마다 뜨되 닫을 수 있다(조용히 사라지지 않는다)", async ({ page }) => {
    await page.addInitScript(() => {
      Storage.prototype.setItem = () => { throw new Error("blocked"); };
      Storage.prototype.getItem = () => { throw new Error("blocked"); };
    });
    await openCanvas(page);
    await expect(page.locator(".pg-welcome")).toBeVisible();
    await page.locator(".pg-welcome-x").click();
    await expect(page.locator(".pg-welcome")).toHaveCount(0);
    await page.reload();
    await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".pg-welcome")).toBeVisible();
  });
});

test("환영 줄은 본 적 있으면 뜨지 않는다(BN N2 · 기본 E2E 상태)", async ({ page }) => {
  await openCanvas(page);
  await expect(page.locator(".pg-hint")).toBeVisible();
  await expect(page.locator(".pg-welcome")).toHaveCount(0);
});

test("종목 이름(BN N2): 칩 = 서버 이름 · 코드 · 모르는 코드는 '이름 모름'(짝) · 이름으로 찾으면 후보 = 서버 검색 · ↓ Enter 로 넣기", async ({ page }) => {
  await openCanvas(page);
  await node(page, "universe").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  const field = page.locator('.pg-basic-field[data-field="tickers"]');
  const doc = await wip(page);
  const codes = doc.nodes.find((n) => n.id === "universe")!.params.tickers as string[];
  for (const c of codes) {
    const hit = ((await (await page.request.get(`http://localhost:8000/api/v1/screener/stock-search?q=${c}&limit=5`)).json()).items as { code: string; name: string }[])
      .find((x) => x.code === c);
    const chip = field.locator(`.pg-stock-chip[data-code="${c}"]`);
    await expect(chip.locator(".pg-stock-name")).toHaveText(hit ? hit.name : "이름 모름");
  }
  const input = field.locator("input");
  await input.fill(`${codes.join(", ")}, 999999`);
  await input.press("Enter");
  await expect(field.locator('.pg-stock-chip[data-code="999999"] .pg-stock-name')).toHaveText("이름 모름");
  await expect(field.locator('.pg-stock-chip[data-code="999999"]')).toHaveAttribute("data-name", "unknown");
  // 짝 — 이름 글자를 그대로 두고 벗어나면 종목으로 넣지 않고, 뺐다고 말한다(코드만 넣는다).
  await input.fill(`${codes.join(", ")}, 삼성없는회사`);
  await input.press("Escape");
  await input.press("Enter");
  await expect(field.locator(".pg-ticker-note")).toContainText("‘삼성없는회사’");
  expect((await wip(page)).nodes.find((n) => n.id === "universe")!.params.tickers).toEqual(codes);

  const server = (await (await page.request.get(`http://localhost:8000/api/v1/screener/stock-search?q=${encodeURIComponent("삼성")}&limit=8`)).json()).items as { code: string; name: string }[];
  expect(server.length, "mock 마스터에도 '삼성' 이 있어야 이 검사가 뜻이 있다").toBeGreaterThan(1);
  await input.fill("005930, 삼성");
  const list = page.locator(".pg-suggest-item");
  await expect(list).toHaveCount(server.length);
  await expect(list.first()).toHaveAttribute("data-code", server[0].code);
  await expect(list.first()).toHaveAttribute("aria-selected", "true");
  // 이미 넣은 005930 이 아닌 첫 후보를 ↓ 로 골라 Enter — 그 토막이 코드로 바뀌고 곧바로 목록에 들어간다.
  const k = server.findIndex((x) => x.code !== "005930");
  for (let i = 0; i < k; i++) await input.press("ArrowDown");
  await input.press("Enter");
  await expect(page.locator(".pg-suggest")).toHaveCount(0);
  await expect(input).toHaveValue(`005930, ${server[k].code}`);
  expect((await wip(page)).nodes.find((n) => n.id === "universe")!.params.tickers).toEqual(["005930", server[k].code]);
  await expect(field.locator(`.pg-stock-chip[data-code="${server[k].code}"] .pg-stock-name`)).toHaveText(server[k].name);
});

test("종목 검색이 실패하면 빈 목록이 아니라 실패라고 말한다 · 코드는 그대로 넣을 수 있다(BN N2)", async ({ page }) => {
  await page.route("**/api/v1/screener/stock-search**", (r) => r.fulfill({ status: 503, body: "{}" }));
  await openCanvas(page);
  await page.locator(".pg-goal-open").click();
  await page.locator('.pg-goal-card[data-goal="build"]').click();
  await page.locator(".pg-goal-input").fill("005930, 삼성");
  await expect(page.locator(".pg-suggest-note--err")).toContainText("HTTP 503");
  await expect(page.locator(".pg-suggest-item")).toHaveCount(0);
  await expect(page.locator('.pg-goal-chip[data-code="005930"]')).toHaveAttribute("data-name", "failed");
  await expect(page.locator('.pg-goal-chip[data-code="005930"] .pg-stock-name')).toHaveText("이름 확인 못 함");
});

test("위험 회피 δ(BN N2): 초심자 질문에 없음 · 전문가에서만, 도움말은 어디서만 비중을 움직이는지 말함", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(page.locator('.pg-basic-field[data-field="delta"]')).toHaveCount(0);
  await expect(page.locator(".pg-settings")).not.toContainText("위험을 얼마나 피할까요");
  const cat = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  const help = cat.nodes.find((c: { type: string }) => c.type === "optimizer").params_schema.properties.delta["x-ui"].help as string;
  await page.locator(".pg-mode .pg-switch").check();
  await expect(page.locator(".pg-field-help", { hasText: help })).toBeVisible();
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`대비(BN N2): ${scheme}`, () => {
    test.use({ storageState: { cookies: [], origins: [] } });
    test("환영 줄 · 종목 후보 목록·칩 · 갈래 승격 단추 AA 미달 0", async ({ page }) => {
      await openCanvas(page);
      if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
      let audit = await page.evaluate<AuditResult>(contrastAudit(".pg-welcome"));
      expect(audit.checked).toBeGreaterThan(1);
      expect(audit.low, `${scheme} 환영 줄`).toEqual([]);
      await makeBranch(page, "optimizer");
      audit = await page.evaluate<AuditResult>(contrastAudit(".pg-branch"));
      expect(audit.low, `${scheme} 갈래 틀`).toEqual([]);
      await page.locator('.pg-tab[data-tab="story"]').click();
      await page.locator('.pg-step[data-node-id="universe"] .pg-step-num').click();
      await page.locator('.pg-tab[data-tab="settings"]').click();
      await page.locator('.pg-basic-field[data-field="tickers"] input').fill("005930, 삼성");
      await expect(page.locator(".pg-suggest-item").first()).toBeVisible();
      audit = await page.evaluate<AuditResult>(contrastAudit(".pg-basic-field[data-field='tickers']"));
      expect(audit.checked).toBeGreaterThan(4);
      expect(audit.low, `${scheme} 종목 후보·칩`).toEqual([]);
      if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// BN N3 · 캔버스 손길 — 거는 것:
//  · 선을 빈 곳에 놓으면 후보 = ★그 포트 타입을 받는(내는) 카탈로그 노드와 정확히 같다★ · 고르면 놓고 이음 · 되돌리기 한 번에 둘 다(짝: 입력에서 끌면 내는 노드)
//  · 우클릭 — 노드(여기까지 계산·갈래·복제·그림 고정·지우기) · 빈 곳(여기에 추가·붙여넣기·정리·찾기)
//  · 안내 줄 [되돌리기] · 되돌릴 수 있는 안내만 8초 뒤 닫힘 · 올려 두면 기다림 · 되돌릴 수 없는 안내는 남음(짝)
//  · 빈 필수 입력 — 포트 고리 + "‘비중’을 이어 주세요"(이으면 사라짐 짝) · Ctrl+F 찾기 · ? 단축키(입력 중엔 안 뜸 짝)
//  · 계산 중 "· n개" = 계산하는 노드 수 · 좁은 폭 "더 보기"(넓으면 없음 짝) · 끌면 11px 격자 · 라이트/다크 AA
// ═══════════════════════════════════════════════════════════════════════════════

type Cat = { nodes: { type: string; inputs: { name: string; type: string }[]; outputs: { name: string; type: string }[] }[] };
const catalogOf = async (page: Page) => (await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json()) as Cat;

/** 포트에서 끌어 캔버스 아래쪽 빈 띠(맞춤이 비워 둔 자리)에 놓는다. */
async function dragToEmpty(page: Page, handle: string) {
  const h = (await page.locator(handle).boundingBox())!;
  const cv = (await page.locator(".react-flow").boundingBox())!;
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2);
  await page.mouse.down();
  await page.mouse.move(cv.x + cv.width * 0.45, cv.y + cv.height - 90, { steps: 12 });
  await page.mouse.up();
}

test("선 끌어 놓기(BN N3): 후보 = 비중을 받는 카탈로그 노드 전부 · 고르면 놓고 이음 · 되돌리기 한 번에 둘 다 · 짝: 입력에서 끌면 내는 노드", async ({ page }) => {
  await openCanvas(page);
  const cat = await catalogOf(page);
  const n0 = (await wip(page)).nodes.length;
  await dragToEmpty(page, '.react-flow__node[data-id="optimizer"] .react-flow__handle.source[data-handleid="weights"]');
  const quick = page.locator(".pg-quick");
  await expect(quick).toHaveAttribute("data-type", "Weights");
  const want = cat.nodes.filter((c) => c.inputs.some((p) => p.type === "Weights")).map((c) => c.type).slice(0, 30).sort();
  expect((await quick.locator(".pg-quick-item").evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")))).sort()).toEqual(want);
  await quick.locator('.pg-quick-item[data-kind="risk"]').click();
  let doc = await wip(page);
  expect(doc.nodes.length).toBe(n0 + 1);
  const added = doc.nodes.find((n) => n.type === "risk" && !["risk"].includes(n.id))!;
  expect(doc.edges.some((e) => e.source === "optimizer" && e.source_port === "weights" && e.target === added.id && e.target_port === "weights")).toBe(true);
  await expect(page.locator(".pg-note")).toContainText("이었어요");
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  doc = await wip(page);
  expect(doc.nodes.length).toBe(n0);
  expect(doc.edges.some((e) => e.target === added.id)).toBe(false);

  // 짝 — 입력(수익률)에서 끌면 수익률을 **내는** 노드만.
  await dragToEmpty(page, '.react-flow__node[data-id="risk"] .react-flow__handle.target[data-handleid="weights"]');
  await expect(quick).toHaveAttribute("data-type", "Weights");
  const makers = cat.nodes.filter((c) => c.outputs.some((p) => p.type === "Weights")).map((c) => c.type).slice(0, 30).sort();
  expect((await quick.locator(".pg-quick-item").evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")))).sort()).toEqual(makers);
  await page.keyboard.press("Escape");
  await expect(quick).toHaveCount(0);
  expect((await wip(page)).nodes.length).toBe(n0);
});

test("우클릭(BN N3): 노드 메뉴 — 그림 고정·풀기·지우기(되돌리기) · 빈 곳 메뉴 — 여기에 추가 → 찾아 넣기", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click({ button: "right" });
  const menu = page.locator('.pg-ctx[aria-label="노드 메뉴"]');
  expect(await menu.locator(".pg-ctx-item").evaluateAll((els) => els.map((e) => e.getAttribute("data-action"))))
    .toEqual(["run-to", "branch", "duplicate", "pin", "remove"]);
  await expect(menu.locator('[data-action="run-to"]')).toBeFocused();
  await menu.locator('[data-action="pin"]').click();
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--pinned/);
  await node(page, "optimizer").click({ button: "right" });
  await expect(menu.locator('[data-action="pin"]')).toHaveText("그림 고정 풀기");
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);

  await node(page, "risk").click({ button: "right" });
  await menu.locator('[data-action="remove"]').click();
  await expect(node(page, "risk")).toHaveCount(0);
  await page.locator(".pg-note-undo").click();
  await expect(node(page, "risk")).toHaveCount(1);

  const cv = (await page.locator(".react-flow").boundingBox())!;
  await page.mouse.click(cv.x + cv.width * 0.5, cv.y + cv.height - 90, { button: "right" });
  const pane = page.locator('.pg-ctx[aria-label="캔버스 메뉴"]');
  expect(await pane.locator(".pg-ctx-item").evaluateAll((els) => els.map((e) => e.getAttribute("data-action"))))
    .toEqual(["add-here", "paste", "layout", "find"]);
  await expect(pane.locator('[data-action="paste"]')).toBeDisabled();                  // 복사한 것이 없다
  await pane.locator('[data-action="add-here"]').click();
  const quick = page.locator(".pg-quick");
  await expect(quick).toHaveAttribute("data-type", "");
  const n0 = (await wip(page)).nodes.length;
  await quick.locator("input").fill("스트레스");
  await expect(quick.locator(".pg-quick-item").first()).toBeVisible();
  const kind = await quick.locator(".pg-quick-item").first().getAttribute("data-kind");
  await quick.locator("input").press("Enter");
  const doc = await wip(page);
  expect(doc.nodes.length).toBe(n0 + 1);
  expect(doc.nodes.filter((n) => n.type === kind).length).toBeGreaterThan(0);
});

test("안내 줄(BN N3): [되돌리기] · 되돌릴 수 있는 안내는 8초 뒤 닫힘 · 올려 두면 기다림 · 짝: 되돌릴 수 없는 안내는 남음", async ({ page }) => {
  test.setTimeout(150_000);
  await openCanvas(page);
  await makeBranch(page, "optimizer");
  const note = page.locator(".pg-note");
  await expect(note.locator(".pg-note-undo")).toBeVisible();
  await note.hover();
  await page.waitForTimeout(9_000);
  await expect(note).toBeVisible();                                                        // 올려 두면 기다린다
  await page.mouse.move(5, 5);
  await expect(note).toHaveCount(0, { timeout: 10_000 });
  expect(((await wip(page)) as BDoc).branches).toHaveLength(1);                            // 닫혀도 동작은 그대로

  await makeBranch(page, "optimizer", "command");                                          // 키보드 길(명령 찾기)도 되돌릴 수 있는 안내
  await page.locator(".pg-note-undo").click();
  expect(((await wip(page)) as BDoc).branches).toHaveLength(1);
  await expect(page.locator(".pg-note")).toContainText("되돌렸어요");

  // 짝 — 되돌릴 수 없는 안내(묶지 못한 사유)는 사람이 닫을 때까지 남고 [되돌리기] 도 없다.
  await page.locator('.pg-tab[data-tab="story"]').click();
  await page.locator('.pg-step[data-node-id="universe"] .pg-step-num').click();
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("전략으로 묶기");
  await page.keyboard.press("Enter");
  await expect(note).toContainText("비중을 내는 노드가 없어요");
  await expect(note.locator(".pg-note-undo")).toHaveCount(0);
  await page.waitForTimeout(9_000);
  await expect(note).toContainText("비중을 내는 노드가 없어요");
});

test("빈 필수 입력(BN N3): 포트 고리 + '‘비중’을 이어 주세요' · 이으면 사라짐(짝) · 이어진 노드엔 없음", async ({ page }) => {
  await openCanvas(page);
  await expect(page.locator(".pg-port--missing")).toHaveCount(0);                            // 기본 사슬은 다 이어져 있다
  const cv = (await page.locator(".react-flow").boundingBox())!;
  await page.mouse.click(cv.x + cv.width * 0.5, cv.y + cv.height - 90, { button: "right" });
  await page.locator('[data-action="add-here"]').click();
  await page.locator(".pg-quick input").fill("흔들림");
  await page.locator('.pg-quick-item[data-kind="risk"]').click();
  await expect(page.locator(".pg-quick")).toHaveCount(0);
  const doc = await wip(page);
  const fresh = doc.nodes.find((n) => n.type === "risk" && n.id !== "risk")!;
  const card = node(page, fresh.id);
  await expect(card.locator(".pg-node-need")).toHaveText("‘비중’을 이어 주세요");
  await expect(card.locator('.pg-port--missing .react-flow__handle[data-handleid="weights"]')).toHaveCount(1);
  // 짝 — 선을 이으면 고리와 한 줄이 사라진다.
  await dragFromTo(page, '.react-flow__node[data-id="optimizer"] .react-flow__handle.source[data-handleid="weights"]',
                   `.react-flow__node[data-id="${fresh.id}"] .react-flow__handle.target[data-handleid="weights"]`);
  await expect(card.locator(".pg-node-need")).toHaveCount(0);
  await expect(card.locator(".pg-port--missing")).toHaveCount(0);
});

async function dragFromTo(page: Page, from: string, to: string) {
  const a = (await page.locator(from).boundingBox())!;
  const b = (await page.locator(to).boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 14 });
  await page.mouse.up();
}

test("찾기·단축키(BN N3): Ctrl+F 로 이름을 찾아 Enter → 그 노드를 고름 · 없으면 말함 · ? 는 단축키 한 장(입력 중엔 안 뜸 짝)", async ({ page }) => {
  await openCanvas(page);
  const cat = await catalogOf(page) as Cat & { nodes: { type: string; plain_label: string }[] };
  const label = (cat.nodes as { type: string; plain_label: string }[]).find((c) => c.type === "optimizer")!.plain_label;
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+f");
  const input = page.locator(".pg-find input");
  await expect(input).toBeFocused();
  await input.fill("없는노드이름");
  await expect(page.locator(".pg-find")).toContainText("맞는 노드가 없어요");
  await input.fill(label);
  await expect(page.locator('.pg-find-item[data-node-id="optimizer"]')).toBeVisible();
  await input.press("Enter");
  await expect(page.locator(".pg-find")).toHaveCount(0);
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--selected/);

  await page.locator(".pg-name").fill("무엇?");                                              // 입력 중의 ? 는 글자다
  await expect(page.locator(".pg-keys")).not.toBeVisible();
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("?");
  await expect(page.locator(".pg-keys")).toBeVisible();
  expect(await page.locator(".pg-keys-list > div").count()).toBeGreaterThanOrEqual(10);
  await expect(page.locator(".pg-keys")).toContainText("Ctrl+F");
  await page.keyboard.press("Escape");
  await expect(page.locator(".pg-keys")).not.toBeVisible();
});

test("계산 중(BN N3): 단추에 '계산하는 중 · n개'(= 계산하는 노드 수) · 그 노드들의 점이 숨 쉼 · 끝나면 돌아옴", async ({ page }) => {
  await openCanvas(page);
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  const n = (await wip(page)).nodes.length;
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-run")).toContainText(`계산하는 중 · ${n}개`);
  await expect(page.locator(".pg-node-dot--running")).toHaveCount(n);
  await expect(page.locator(".pg-run")).toHaveText("계산하기", { timeout: 120_000 });
  await expect(page.locator(".pg-node-dot--running")).toHaveCount(0);
});

test("상단 줄(BN N3): 1024px 이면 서랍·불러오기·내보내기가 '더 보기' 에 · 서랍이 열림 · 짝: 1280px 이면 '더 보기' 없음 · 390px 가로 스크롤 0", async ({ page }) => {
  await recordDownloadNames(page);
  await page.setViewportSize({ width: 1024, height: 800 });
  await openCanvas(page);
  await expect(page.locator(".pg-more")).toBeVisible();
  await expect(page.locator(".pg-toolbar .pg-drawers")).toBeHidden();
  await expect(page.locator(".pg-toolbar .pg-export")).toBeHidden();
  await page.locator(".pg-more").click();
  const drawers = page.locator(".pg-more-menu [data-drawer]");
  expect(await drawers.count()).toBe(3);
  await page.locator(".pg-more-export").click();
  expect(await lastDownloadName(page)).toMatch(/\.json$/);
  await page.locator(".pg-more").click();
  await drawers.first().click();
  await expect(page.locator("dialog[open]")).toHaveCount(1);
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(page.locator(".pg-more")).toBeHidden();
  await expect(page.locator(".pg-toolbar .pg-drawers")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});

test("격자 맞춤(BN N3): 노드를 끌면 11px 격자에 선다(자동 정리 자리는 그대로)", async ({ page }) => {
  await openCanvas(page);
  const card = (await node(page, "optimizer").boundingBox())!;
  await page.mouse.move(card.x + 60, card.y + 20);
  await page.mouse.down();
  await page.mouse.move(card.x + 97, card.y + 63, { steps: 10 });
  await page.mouse.up();
  const p = (await wip(page)).nodes.find((n) => n.id === "optimizer")!.position;
  expect([Math.round(p.x) % 11, Math.round(p.y) % 11]).toEqual([0, 0]);
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(BN N3): ${scheme} — 빠른 추가 · 우클릭 메뉴 · 찾기 · 단축키 · 안내 되돌리기 · 빈 입력 AA 미달 0`, async ({ page }) => {
    await openCanvas(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    const check = async (sel: string, min = 2) => {
      const a = await page.evaluate<AuditResult>(contrastAudit(sel));
      expect(a.checked, sel).toBeGreaterThanOrEqual(min);
      expect(a.low, `${scheme} ${sel}`).toEqual([]);
      if (scheme === "dark") expect(a.bright, `${sel} 다크인데 밝은 배경`).toEqual([]);
    };
    await dragToEmpty(page, '.react-flow__node[data-id="optimizer"] .react-flow__handle.source[data-handleid="weights"]');
    await check(".pg-quick", 6);
    await page.locator('.pg-quick-item[data-kind="risk"]').click();
    await check(".pg-note", 2);
    await node(page, "optimizer").click({ button: "right" });
    await check(".pg-ctx", 5);
    await page.keyboard.press("Escape");
    await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
    await page.keyboard.press("Control+f");
    await page.locator(".pg-find input").fill("비중");
    await check(".pg-find", 2);
    await page.keyboard.press("Escape");
    await page.keyboard.press("?");
    await check(".pg-keys", 10);
    await page.keyboard.press("Escape");
    // 빈 입력 한 줄 — 잇지 않은 노드를 빈 곳 메뉴로 하나 놓는다.
    const cv = (await page.locator(".react-flow").boundingBox())!;
    await page.mouse.click(cv.x + cv.width * 0.5, cv.y + cv.height - 90, { button: "right" });
    await page.locator('[data-action="add-here"]').click();
    await page.locator(".pg-quick input").fill("흔들림");
    await page.locator('.pg-quick-item[data-kind="risk"]').click();
    await expect(page.locator(".pg-node-need").first()).toBeVisible();
    await check(".pg-node-need", 1);
  });
}
