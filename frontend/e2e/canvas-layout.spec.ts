import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * CF4 · 배경·배치 — ★자유 배치는 그대로, 맞추는 도구를 더한다★
 * CF4a 거는 것(짝으로 항상-붙음·항상-안 붙음을 배제):
 *  · 격자 두 겹 — 작은 칸 점(22) 위에 큰 칸 선(110 = 점 다섯 칸). 점이 먼저 그려진다(바탕 대비 테스트가 첫 무늬를 잰다)
 *  · 한 카드를 끌 때 다른 카드의 가장자리·가운데와 화면 몇 px 안이면 그 값에 정확히 붙고 안내선이 보인다 · 놓으면 선은 사라진다
 *    (짝: 40px 떨어지면 붙지 않고 선도 없다)
 *  · 여럿 고르면 '정렬' — 왼쪽·가운데·위 맞추기, 셋 이상이면 가로·세로 간격 똑같이(짝: 둘이면 간격 항목 없음) · 되돌리기 한 번
 *  · 자동 정리는 자란 카드(긴 막힘 사유)의 실제 높이로 쌓는다 — 아래 카드와 겹치지 않는다(짝: 그 카드는 정말 자랐다)
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[] };
const mod = process.platform === "darwin" ? "Meta" : "Control";

// 서로 맞지 않는 자리 셋(x 는 11 의 배수가 아니다 — 격자로는 우연히 같아질 수 없다). 셋 다 처음 화면(오른쪽 창 왼쪽)에 보인다.
const LOOSE = { ...F, nodes: [n("a", "universe", 320, 0, { tickers: ["005930"] }), n("b", "returns", 880, 440), n("c", "estimate", 1160, 160)], edges: [] };

async function openWith(page: Page, doc: object | null) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("cf4_seeded")) return;
      sessionStorage.setItem("cf4_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      if (d) sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d)); else sessionStorage.removeItem("alpha_pg_wip");
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
}
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const pos = async (page: Page, id: string) => (await wip(page)).nodes.find((x) => x.id === id)!.position;
const card = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);

// ── 격자 ───────────────────────────────────────────────────────────────────

test("격자 두 겹: 점(22) 먼저 · 선(110 = 점 다섯 칸) 다음 — 확대해도 비율 그대로", async ({ page }) => {
  await openWith(page, LOOSE);
  const bgs = page.locator(".react-flow__background");
  await expect(bgs).toHaveCount(2);
  await expect(bgs.nth(0).locator("circle")).toHaveCount(1);
  await expect(bgs.nth(1).locator("path")).toHaveCount(1);
  const widths = async () => bgs.evaluateAll((els) => els.map((el) => Number(el.querySelector("pattern")!.getAttribute("width"))));
  const [dot, line] = await widths();
  expect(line / dot).toBeCloseTo(5, 5);
  await page.locator(".react-flow__controls-zoomin").click();
  await page.waitForTimeout(200);
  const [dot2, line2] = await widths();
  expect(dot2).not.toBeCloseTo(dot, 3);                       // 짝 — 확대가 실제로 바뀌었다
  expect(line2 / dot2).toBeCloseTo(5, 5);
});

for (const scheme of ["light", "dark"] as const) {
  test(`격자 대비(${scheme}): 큰 칸 선은 바탕과 1.1~1.3 — 보이되 점(작은 칸)보다 조용하다`, async ({ page }) => {
    await openWith(page, LOOSE);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    const r = await page.evaluate(() => {
      const rgb = (s: string) => (s.match(/(\d+(?:\.\d+)?)/g) ?? []).slice(0, 3).map(Number);
      const lum = ([r, g, b]: number[]) => {
        const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
      };
      const ratio = (a: number[], b: number[]) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
      const canvas = rgb(getComputedStyle(document.querySelector(".pg-canvas")!).backgroundColor);
      const bgs = document.querySelectorAll(".react-flow__background");
      return { line: ratio(rgb(getComputedStyle(bgs[1].querySelector("path")!).stroke), canvas),
               dot: ratio(rgb(getComputedStyle(bgs[0].querySelector("circle")!).fill), canvas) };
    });
    expect(r.line).toBeGreaterThanOrEqual(1.1);
    expect(r.line).toBeLessThanOrEqual(1.3);
    expect(r.line).toBeLessThan(r.dot);
  });
}

// ── 끌 때 안내선 ─────────────────────────────────────────────────────────────

/** 카드를 화면에서 (dx, dy) 만큼 끈다 — React Flow 는 누른 뒤 첫 움직임으로 끌기를 시작하고 그 움직임만큼은 카드를 옮기지 않는다
 *  (실측 25px 이 사라졌다). 그래서 4px 로 끌기를 시작한 뒤 카드의 실제 자리에서 남은 거리만 옮긴다. */
async function dragBy(page: Page, id: string, dx: number, dy: number, during?: () => Promise<void>) {
  const b = (await card(page, id).boundingBox())!;
  const p = { x: b.x + 30, y: b.y + 14 };
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + 4, p.y, { steps: 2 });
  const now = (await card(page, id).boundingBox())!;
  const to = { x: p.x + 4 + (b.x + dx - now.x), y: p.y + (b.y + dy - now.y) };
  await page.mouse.move((p.x + to.x) / 2, (p.y + to.y) / 2, { steps: 6 });
  await page.mouse.move(to.x, to.y, { steps: 6 });
  await page.waitForTimeout(100);
  if (during) await during();
  await page.mouse.up();
}

test("안내선: 다른 카드의 왼쪽 가장자리 3px 안으로 끌면 정확히 붙고 선이 보인다 · 놓으면 선이 사라진다", async ({ page }) => {
  await openWith(page, LOOSE);
  const a = (await card(page, "a").boundingBox())!;
  const b = (await card(page, "b").boundingBox())!;
  await dragBy(page, "b", a.x - b.x + 3, 0, async () => {
    // 세로 선은 상자 폭이 0 이라 '보임' 판정 대신 자리로 잰다 — 붙은 x(320)에 선이 있다.
    await expect(page.locator(".pg-guides")).toBeVisible();
    const xs = await page.locator('.pg-guide[data-axis="x"]').evaluateAll((els) => els.map((el) => Number(el.getAttribute("x1"))));
    expect(xs).toContain(320);
  });
  await expect(page.locator(".pg-guide")).toHaveCount(0);
  expect((await pos(page, "b")).x).toBe(320);
});

test("안내선 짝: 40px 떨어지면 붙지 않고 세로 선도 없다", async ({ page }) => {
  await openWith(page, LOOSE);
  const a = (await card(page, "a").boundingBox())!;
  const b = (await card(page, "b").boundingBox())!;
  await dragBy(page, "b", a.x - b.x + 40, 0, async () => {
    await expect(page.locator('.pg-guide[data-axis="x"]')).toHaveCount(0);
  });
  expect((await pos(page, "b")).x).not.toBe(320);
});

// ── 정렬·간격 ───────────────────────────────────────────────────────────────

// 카드 머리 왼쪽(끌기와 같은 자리)을 누른다 — 가운데는 '이어 주기' 같은 단추일 수 있다.
const HEAD = { x: 30, y: 14 };
async function pick(page: Page, ids: string[]) {
  // 먼저 빈 곳을 눌러 고른 것을 비운다(이미 고른 카드를 누르면 고른 묶음이 그대로라 셈이 틀어진다). 왼쪽 판과 관문 줄 사이 빈 자리.
  await page.locator(".react-flow__pane").click({ position: { x: 350, y: 20 } });
  await card(page, ids[0]).locator(".pg-node").click({ position: HEAD });
  for (const id of ids.slice(1)) await card(page, id).locator(".pg-node").click({ position: HEAD, modifiers: [mod] });
  await expect(page.locator(".pg-selbar-n")).toHaveText(`${ids.length}개 골랐어요`);
}
async function align(page: Page, label: string) {
  await page.locator(".pg-align-open").click();
  await page.locator(".pg-align-menu [role=menuitem]", { hasText: label }).click();
}

test("정렬 메뉴는 캔버스 안에 다 보이고 가리지 않는 쪽으로 열린다 — 막대가 카드 위에 있어도 · 위쪽 카드 둘이어도", async ({ page }) => {
  await openWith(page, LOOSE);
  const inside = async () => {
    const m = (await page.locator(".pg-align-menu").boundingBox())!;
    const c = (await page.locator(".pg-canvas").boundingBox())!;
    expect(m.y).toBeGreaterThanOrEqual(c.y);
    expect(m.y + m.height).toBeLessThanOrEqual(c.y + c.height);
    // 메뉴 항목이 다른 판에 가리지 않는다(맨 위 항목의 가운데를 실제로 누를 수 있다).
    const first = (await page.locator(".pg-align-menu [role=menuitem]").first().boundingBox())!;
    expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest(".pg-align-menu"),
                               [first.x + first.width / 2, first.y + first.height / 2])).toBe(true);
  };
  await pick(page, ["a", "b", "c"]);                    // 막대가 카드 위(아래 자리가 모자람)
  await page.locator(".pg-align-open").click();
  await inside();
  await expect(page.locator(".pg-align-menu")).toHaveAttribute("data-dir", "down");
  await page.keyboard.press("Escape");
  await pick(page, ["a", "c"]);                         // 위쪽 카드 둘 — 막대 자리가 달라도 메뉴는 캔버스 안
  await page.locator(".pg-align-open").click();
  await inside();
});
// 화면 상자(x·y·폭·높이) + 문서 자리(fx·fy).
const boxes = async (page: Page, ids: string[]) => Promise.all(ids.map(async (id) => {
  const p = await pos(page, id);
  return { id, fx: p.x, fy: p.y, ...(await card(page, id).boundingBox())! };
}));

test("정렬: 왼쪽·가운데·위 맞추기 · 되돌리기 한 번에 원래 자리", async ({ page }) => {
  await openWith(page, LOOSE);
  const ids = ["a", "b", "c"];
  const before = await Promise.all(ids.map((id) => pos(page, id)));
  await pick(page, ids);
  await align(page, "왼쪽 맞추기");
  expect(new Set(await Promise.all(ids.map(async (id) => (await pos(page, id)).x)))).toEqual(new Set([320]));
  await page.keyboard.press("Control+z");
  expect(await Promise.all(ids.map((id) => pos(page, id)))).toEqual(before);

  await pick(page, ids);
  await align(page, "위 맞추기");
  expect(new Set(await Promise.all(ids.map(async (id) => (await pos(page, id)).y)))).toEqual(new Set([0]));
  await page.keyboard.press("Control+z");

  await pick(page, ids);
  await align(page, "가운데 맞추기");
  await page.waitForTimeout(200);
  const centers = (await boxes(page, ids)).map((r) => r.x + r.width / 2);
  expect(Math.max(...centers) - Math.min(...centers)).toBeLessThanOrEqual(2);
});

test("간격: 셋이면 가로·세로 간격이 똑같고 양 끝은 그대로 · 짝: 둘이면 간격 항목이 없다", async ({ page }) => {
  await openWith(page, LOOSE);
  const ids = ["a", "b", "c"];
  await pick(page, ids);
  await page.locator(".pg-align-open").click();
  await expect(page.locator(".pg-align-menu [role=menuitem]")).toHaveCount(5);
  await page.keyboard.press("Escape");
  await align(page, "가로 간격 똑같이");
  await page.waitForTimeout(200);
  let r = (await boxes(page, ids)).sort((p, q) => p.x - q.x);
  expect(r[0].id).toBe("a");
  expect(r[0].fx).toBe(320);                                                   // 양 끝 그대로
  expect(r[2].fx).toBe(1160);
  const gx = [r[1].x - (r[0].x + r[0].width), r[2].x - (r[1].x + r[1].width)];
  expect(Math.abs(gx[0] - gx[1])).toBeLessThanOrEqual(2);
  await page.keyboard.press("Control+z");

  await pick(page, ids);
  await align(page, "세로 간격 똑같이");
  await page.waitForTimeout(200);
  r = (await boxes(page, ids)).sort((p, q) => p.y - q.y);
  const gy = [r[1].y - (r[0].y + r[0].height), r[2].y - (r[1].y + r[1].height)];
  expect(Math.abs(gy[0] - gy[1])).toBeLessThanOrEqual(2);

  await pick(page, ["a", "b"]);
  await page.locator(".pg-align-open").click();
  await expect(page.locator(".pg-align-menu [role=menuitem]")).toHaveCount(3);
  await expect(page.locator(".pg-align-menu")).not.toContainText("간격");
});

// ── 자동 정리 = 실제 높이 ─────────────────────────────────────────────────────

const STACK = {
  ...F,
  nodes: [n("universe", "universe", 0, 140, { tickers: ["005930", "000660", "035420"] }), n("returns", "returns", 320, 140),
          n("optimizer", "optimizer", 640, 140, { model: "risk_parity" }),
          n("scenario", "scenario_stress", 960, -420), n("corr", "corr_stress", 960, 140)],
  edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns"),
          e("optimizer", "weights", "scenario", "weights"), e("returns", "returns", "corr", "returns"), e("optimizer", "weights", "corr", "weights")],
};

test("자동 정리는 자란 카드의 실제 높이로 쌓는다 — 아래 카드와 겹치지 않는다(짝: 그 카드는 정말 자랐다)", async ({ page }) => {
  await openWith(page, STACK);
  await page.route((u) => u.pathname.endsWith("/allocation/graph/run"), async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    // 카드는 막힘 사유로 설명의 첫 사실(`.pg-node-why`, 줄 제한 없음)을 그린다 — 그 글을 길게 해 카드를 정말 자라게 한다.
    const why = "시나리오를 계산하지 못했어요 — " + "충격을 넣을 종목의 과거 시세가 모자라 이 시나리오의 손실을 잴 수 없어요. ".repeat(12);
    body.nodes.scenario.status = "failed";
    body.nodes.scenario.reason = why;
    body.nodes.scenario.explain = { ...(body.nodes.scenario.explain ?? { title: "시나리오를 계산하지 못했어요" }), facts: [why] };
    await route.fulfill({ response: res, json: body });
  });
  await page.locator(".pg-run").click();
  await expect(card(page, "scenario").locator(".pg-node")).toHaveClass(/pg-node--failed/, { timeout: 60_000 });
  const minH = await card(page, "scenario").locator(".pg-node").evaluate((el) => parseFloat(getComputedStyle(el).minHeight));
  const grown = (await card(page, "scenario").boundingBox())!;
  const zoom = await page.locator(".react-flow__viewport").evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).a);
  expect(grown.height / zoom, "막힘 사유로 카드가 자랐다").toBeGreaterThan(minH + 40);
  await page.locator('button[aria-label="자동 정리"]').click();
  await page.waitForTimeout(500);
  // 자동 정리는 맞춰 보기로 멀리 물러난다(멀리선 사유 글을 숨겨 카드가 다시 줄어든다) — 카드가 자랐던 확대로 돌아가 잰다.
  const scale = () => page.locator(".react-flow__viewport").evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).a);
  for (let i = 0; i < 12 && (await scale()) < zoom - 1e-3; i++) {
    await page.locator(".react-flow__controls-zoomin").click();
    await page.waitForTimeout(150);
  }
  expect(await scale(), "자랐던 확대로 돌아왔다").toBeGreaterThanOrEqual(zoom - 1e-3);
  expect((await card(page, "scenario").boundingBox())!.height / (await scale()), "돌아온 확대에서도 자란 그대로").toBeGreaterThan(minH + 40);
  const top = (await card(page, "scenario").boundingBox())!;
  const below = (await card(page, "corr").boundingBox())!;
  expect(Math.abs(top.x - below.x)).toBeLessThan(2);                            // 같은 열
  expect(below.y, "아래 카드가 자란 카드 밑에서 시작한다").toBeGreaterThanOrEqual(top.y + top.height);
});

// ── CF4b · 단계 레인('보기' 메뉴) ────────────────────────────────────────────────
// 레인 = 서버 단계 순서대로 왼→오 세로 띠 여섯. 노드가 아니다(끌 수도 고를 수도 없다) · 빈 곳 누르기·끌기는 그대로 캔버스로 간다.
// STACK 은 비중 계산(build)이 x 640 — '신호' 띠 자리라 맞추기 전에는 제 띠 밖이다(짝).

async function stagesOf(page: Page): Promise<{ key: string; label: string }[]> {
  return (await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json()).stages;
}
async function viewMenu(page: Page) {
  await page.locator(".pg-view-open").click();
  await expect(page.locator(".pg-view-menu")).toBeVisible();
}
async function lanesOn(page: Page, on: boolean) {
  await viewMenu(page);
  const item = page.locator('.pg-view-menu [role=menuitemcheckbox][data-view="lanes"]');
  if ((await item.getAttribute("aria-checked")) !== String(on)) await item.click();
  else await page.keyboard.press("Escape");
}
const center = (b: { x: number; width: number }) => b.x + b.width / 2;

test("레인: 켜면 띠 여섯이 서버 단계 순서·이름 그대로 · 노드 수 · 짝: 끄면 0 · 노드는 그대로", async ({ page }) => {
  await openWith(page, STACK);
  const stages = await stagesOf(page);
  expect(stages.length).toBe(6);
  await expect(page.locator(".pg-lane")).toHaveCount(0);                       // 기본은 꺼짐
  await viewMenu(page);
  await expect(page.locator('.pg-view-menu [data-view="lanes"]')).toHaveAttribute("aria-checked", "false");
  await expect(page.locator('.pg-view-menu [data-view="fit-lanes"]')).toHaveCount(0);   // 짝 — 끈 동안 맞추기 없음
  await page.keyboard.press("Escape");
  await lanesOn(page, true);
  const lanes = page.locator(".pg-lane");
  await expect(lanes).toHaveCount(6);
  expect(await lanes.evaluateAll((els) => els.map((el) => el.getAttribute("data-stage")))).toEqual(stages.map((s) => s.key));
  for (const [i, s] of stages.entries()) await expect(lanes.nth(i).locator(".pg-lane-name")).toHaveText(s.label);
  const counts = await lanes.evaluateAll((els) => els.map((el) => Number(el.getAttribute("data-count"))));
  expect(counts).toEqual([2, 0, 0, 1, 2, 0]);                                   // universe·returns / optimizer / scenario·corr
  // 띠는 왼→오로 겹치지 않고 이어진다.
  const xs = await Promise.all([...Array(6).keys()].map(async (i) => (await lanes.nth(i).boundingBox())!));
  for (let i = 1; i < 6; i++) expect(Math.abs(xs[i].x - (xs[i - 1].x + xs[i - 1].width))).toBeLessThan(1.5);
  await expect(page.locator(".react-flow__node")).toHaveCount(STACK.nodes.length);   // 노드로 만들지 않았다
  await lanesOn(page, false);
  await expect(page.locator(".pg-lane")).toHaveCount(0);
});

test("레인은 누르기·끌기를 잡지 않는다 — 빈 띠 위 점은 캔버스(pane)", async ({ page }) => {
  await openWith(page, STACK);
  await lanesOn(page, true);
  const empty = (await page.locator('.pg-lane[data-stage="belief"]').boundingBox())!;    // 빈 띠
  const canvasBox = (await page.locator(".pg-canvas").boundingBox())!;
  const p = { x: center(empty), y: Math.min(empty.y + empty.height / 2, canvasBox.y + canvasBox.height - 120) };
  const hit = await page.evaluate(([x, y]) => {
    const el = document.elementFromPoint(x, y);
    return { pane: !!el?.closest(".react-flow__pane"), lane: !!el?.closest(".pg-lane") };
  }, [p.x, p.y]);
  expect(hit).toEqual({ pane: true, lane: false });
});

test("레인에 맞추기: 노드마다 자기 단계 띠 안으로 · 되돌리기 한 번에 원래 자리 (짝: 맞추기 전엔 띠 밖 노드가 있다)", async ({ page }) => {
  await openWith(page, STACK);
  const stages = await stagesOf(page);
  const catalog = (await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json()).nodes as { type: string; stage: string }[];
  const stageOf = (kind: string) => catalog.find((c) => c.type === kind)!.stage;
  await lanesOn(page, true);
  const outside = async () => {
    const out: string[] = [];
    for (const nd of STACK.nodes) {
      const lane = (await page.locator(`.pg-lane[data-stage="${stageOf(nd.type)}"]`).boundingBox())!;
      const c = center((await card(page, nd.id).boundingBox())!);
      if (c < lane.x || c > lane.x + lane.width) out.push(nd.id);
    }
    return out;
  };
  expect(await outside(), "맞추기 전엔 띠 밖 노드가 있다").not.toEqual([]);
  const before = await Promise.all(STACK.nodes.map((nd) => pos(page, nd.id)));
  await viewMenu(page);
  await page.locator('.pg-view-menu [role=menuitem][data-view="fit-lanes"]').click();
  await page.waitForTimeout(500);
  expect(await outside()).toEqual([]);
  expect(stages.length).toBe(6);
  await page.keyboard.press("Control+z");
  expect(await Promise.all(STACK.nodes.map((nd) => pos(page, nd.id)))).toEqual(before);
});

test("레인 켬은 이 브라우저에 남는다 — 새로고침 뒤에도 켜짐 · 짝: 끄고 새로고침하면 꺼짐", async ({ page }) => {
  await openWith(page, STACK);
  await lanesOn(page, true);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".pg-lane")).toHaveCount(6);
  await lanesOn(page, false);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await expect(page.locator(".pg-lane")).toHaveCount(0);
});

test("명령 찾기(Ctrl+K)에도 같은 항목 — 레인 켜기 · 레인에 맞추기", async ({ page }) => {
  await openWith(page, STACK);
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("단계 레인");
  await expect(page.locator('.pg-cmd-item[data-cmd="lanes"]')).toContainText("단계 레인 보기");
  await page.keyboard.press("Enter");
  await expect(page.locator(".pg-lane")).toHaveCount(6);
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("레인에 맞추기");
  await expect(page.locator('.pg-cmd-item[data-cmd="fit-lanes"]')).toHaveCount(1);
  await page.keyboard.press("Escape");
  // 기본 대화상자의 close 사건은 Esc 다음 차례에 온다 — 닫히기 전에 Ctrl+K 를 누르면 '이미 열림' 으로 무시돼 다시 열리지 않는다.
  await expect(page.locator("dialog.pg-cmd")).toBeHidden();
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill("단계 레인");
  await expect(page.locator('.pg-cmd-item[data-cmd="lanes"]')).toContainText("단계 레인 끄기");
});

for (const scheme of ["light", "dark"] as const) {
  test(`레인 대비(${scheme}): 띠 머리 글은 AA · 띠 바탕은 카드보다 조용하다`, async ({ page }) => {
    await openWith(page, STACK);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await lanesOn(page, true);
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-lanes"));
    expect(a.checked).toBeGreaterThanOrEqual(6);
    expect(a.low, `${scheme} 띠 머리`).toEqual([]);
  });
}
