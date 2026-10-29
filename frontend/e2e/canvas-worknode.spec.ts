import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { contrastAudit, type AuditResult } from "./helpers";
import { cardHeight, NODE_W } from "../src/entities/portfolio-graph/size";
import { connectionProblem, type ConnEdge, type ConnNode } from "../src/entities/portfolio-graph/connect";
import type { NodeCatalogEntry } from "../src/entities/portfolio-graph/types";

// ═══════════════════════════════════════════════════════════════════════════════
// CF1 + CF2 — 작업 노드(자리 고정) + 소켓·핸들 (스펙 docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md)
// ─────────────────────────────────────────────────────────────────────────────
// 거는 것:
//  · ★같은 상자★(사용자 결정 2026-10-16 "자리 고정") — 멀리·중간·가까이에서 카드 크기 ÷ 확대율이 같다 · 폭 240 · 높이 = 카탈로그로
//    계산한 cardHeight · 계산 뒤(작은 그림이 생겨도) 그대로 · 짝: 포트·위젯 수가 다른 노드는 높이가 다르다(상수 배제)
//  · 단계별 보임 — 가까이: 위젯·결과 자리 / 중간: 소켓 이름·요약 / 멀리: 이름·값만(짝: 단계마다 안 보이는 것)
//  · 카드 위젯 — 값 쓰기는 문서·설정 판과 같은 길(같은 값 · Ctrl+Z 한 번 · 그 노드와 하류만 예전 결과) · show_if 칸이 나타나도 상자 그대로 ·
//    그릴 수 없는 칸만 있는 노드는 "설정 더 보기" → 설정 탭 · 위젯 위에서 끌어도 노드가 움직이지 않는다
//  · 소켓 — 선택은 빈 원 · 필수는 채운 원(짝) · 합치기 입력은 네모(짝) · 나가는 선이 둘 이상이면 "n곳"(짝: 하나면 없음)
//  · 끄는 중 — 선 색 = 보내는 타입 색 · 막힌 소켓 위에서 사유 글(= connectionProblem)이 놓기 전에 보인다(짝: 맞는 소켓 위엔 없음)
//  · 선 끝 다시 꽂기 — 맞는 소켓으로 옮기면 선 수 같고 id 바뀜 · Ctrl+Z 한 번 · 틀린 소켓은 사유 + 선 그대로 · 제자리에 놓아도 거부 없음
//  · 소켓 두 번 누르기 — 그 타입의 빠른 추가(내는 소켓 = 받는 노드 · 받는 소켓 = 내는 노드) · 캔버스 확대 그대로
//  · 접기 — 머리 줄만 · 핸들이 머리 가운데 · 선 유지 · 파일·작업 중 문서에 남는다(짝: 펴면 원래대로)
//  · 코드가 만든 흐름은 겹치지 않게 다시 쌓는다 · 예전 크기로 놓인 문서는 옮기지 않고 '자동 정리' 안내(짝: 안 겹치면 안내 없음)
//  · 대비 AA 라이트/다크(가까이 — 위젯 포함) · 390 가로 넘침 0
// ═══════════════════════════════════════════════════════════════════════════════

const API = "http://localhost:8000/api/v1/allocation/graph/node-types";
const OVERLAP_NOTE = "예전 크기로 놓인 문서라 노드가 겹쳐요. 위 도구줄의 ‘자동 정리’를 누르면 다시 놓아요.";
const F = { format: "project-alpha.portfolio-graph", version: 1 } as const;
type DocNode = { id: string; type: string; params: Record<string, unknown>; position: { x: number; y: number } };
type DocEdge = { id: string; source: string; source_port: string; target: string; target_port: string };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}): DocNode =>
  ({ id, type, params, position: { x, y } });
const e = (s: string, sp: string, t: string, tp: string): DocEdge =>
  ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const T = { tickers: ["005930", "000660", "035420"] };
/** 다시 꽂기·끄는 중 사유를 볼 작은 흐름 — 비중 계산의 수익률·생각 자리가 비어 있다(맞는 곳·틀린 곳이 둘 다 있다). */
const SMALL = { ...F, nodes: [n("universe", "universe", 0, 0, T), n("returns", "returns", 320, 0), n("estimate", "estimate", 640, 0),
                              n("optimizer", "optimizer", 640, 460)],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns")] };

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const rfNode = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);
const handle = (page: Page, id: string, port: string, side: "source" | "target") =>
  rfNode(page, id).locator(`.react-flow__handle.${side}[data-handleid="${port}"]`);
const canvas = (page: Page) => page.locator(".pg-canvas");
const zoomOf = (page: Page) => canvas(page).evaluate((el) => Number(getComputedStyle(el).getPropertyValue("--pg-z")));
const edgeIds = (page: Page) => page.locator(".react-flow__edge").evaluateAll((els) => els.map((x) => x.getAttribute("data-id")).sort());

async function catalog(page: Page): Promise<{ nodes: NodeCatalogEntry[]; port_plain: Record<string, string> }> {
  return (await page.request.get(API)).json();
}

async function openWith(page: Page, doc: object | null) {
  if (doc) {
    await page.addInitScript((d) => {
      try {
        if (sessionStorage.getItem("cf1_seeded")) return;
        sessionStorage.setItem("cf1_seeded", "1");
        sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
      } catch { /* */ }
    }, doc);
  }
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}

async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
}

async function zoomTo(page: Page, level: "far" | "mid" | "near") {
  for (let i = 0; i < 16; i++) {
    const z = await canvas(page).getAttribute("data-zoom");
    if (z === level) return;
    const wantIn = level === "near" || (level === "mid" && z === "far");
    await page.locator(wantIn ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
  }
  await expect(canvas(page)).toHaveAttribute("data-zoom", level);
}

/** 판·토스트에 가리지 않은 빈 캔버스 한 점. */
async function emptyPoint(page: Page): Promise<{ x: number; y: number }> {
  return page.evaluate(() => {
    const r = document.querySelector(".react-flow")!.getBoundingClientRect();
    for (let y = r.bottom - 90; y > r.top + 80; y -= 17)
      for (let x = r.left + 20; x < r.right - 20; x += 23)
        if (document.elementFromPoint(x, y)?.classList.contains("react-flow__pane")) return { x, y };
    throw new Error("빈 캔버스 자리가 없다");
  });
}
async function clickEmpty(page: Page) { const p = await emptyPoint(page); await page.mouse.click(p.x, p.y); }
/** 노드를 판 사이 가운데로 끌어 온다(사람이 캔버스를 끄는 것과 같다). 가까이에서는 카드가 길어 머리 줄이 관문 알약 밑에 들 수 있어
 *  ★위쪽은 알약 아래(캔버스 위 + 130)에 맞춘다★. */
async function center(page: Page, id: string) {
  const r = await page.evaluate((nid) => {
    const nb = document.querySelector(`.react-flow__node[data-id="${nid}"]`)!.getBoundingClientRect();
    const hit = (sel: string) => { const x = document.querySelector<HTMLElement>(sel); return x && x.offsetParent ? x.getBoundingClientRect() : null; };
    const pl = hit(".pg-palette"), sd = hit(".pg-side"), cv = document.querySelector(".react-flow")!.getBoundingClientRect();
    const left = pl ? pl.right : cv.left, right = sd ? sd.left : cv.right;
    return { dx: (left + right) / 2 - (nb.left + nb.width / 2), dy: cv.top + 130 - nb.top };
  }, id);
  const p = await emptyPoint(page);
  await page.mouse.move(p.x, p.y); await page.mouse.down();
  await page.mouse.move(p.x + r.dx, p.y + r.dy, { steps: 8 }); await page.mouse.up();
}
const mid = async (l: ReturnType<Page["locator"]>) => { const b = (await l.boundingBox())!; return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };

/** 화면의 카드 크기 ÷ 확대율 = 캔버스 좌표의 상자. */
async function boxes(page: Page, ids: string[]) {
  return page.evaluate((list) => {
    const z = Number(getComputedStyle(document.querySelector(".pg-canvas")!).getPropertyValue("--pg-z"));
    return Object.fromEntries(list.map((id) => {
      const r = document.querySelector(`.pg-node[data-node-id="${id}"]`)!.getBoundingClientRect();
      return [id, { w: r.width / z, h: r.height / z }];
    }));
  }, ids);
}

test("같은 상자(CF1): 멀리·중간·가까이에서 카드 크기 ÷ 확대율이 같다 · 폭 240 · 높이 = 카탈로그로 계산한 cardHeight · 계산 뒤에도 그대로", async ({ page }) => {
  await openWith(page, null);
  const cat = (await catalog(page)).nodes;
  const ids = ["universe", "returns", "estimate", "views", "optimizer", "risk", "backtest"];
  // ★상수 배제 짝★ — 포트·위젯 수가 다른 노드는 높이가 다르다(모든 카드가 한 높이면 이 계약은 공허하다).
  expect(new Set(ids.map((k) => cardHeight(k, cat))).size).toBeGreaterThan(2);
  for (const phase of ["계산 전", "계산 뒤"]) {
    if (phase === "계산 뒤") await run(page);
    for (const lv of ["far", "mid", "near"] as const) {
      await zoomTo(page, lv);
      const b = await boxes(page, ids);
      for (const id of ids) {
        expect(Math.abs(b[id].w - NODE_W), `${phase} ${lv} ${id} 폭`).toBeLessThanOrEqual(1);
        expect(Math.abs(b[id].h - cardHeight(id, cat)), `${phase} ${lv} ${id} 높이 ${b[id].h}`).toBeLessThanOrEqual(1);
      }
    }
  }
});

// 결과 자리는 남는 높이를 채우되 줄어들 수도 있다(min-height 0) — 그림이 자리보다 크면 상자가 자라지 않고 ★상태 줄을 덮는다★. 그래서 '같은 상자'만으로는
// 결과 자리 높이(SLOT_H)가 모자란 것을 못 잡는다(변이로 확인함). 가장 큰 결과 그림이 나오는 흐름(종목 거르기 — 막대 다섯 + 그림 밖 n개)으로 잰다.
test("결과 자리(CF1): 가장 큰 결과 그림도 상자 안 — 상태 줄을 덮지 않고 상자도 자라지 않는다(가까이 · 계산 뒤)", async ({ page }) => {
  await openWith(page, null);
  const cat = (await catalog(page)).nodes;
  await page.locator("#pg-left-tab-add").click();
  await page.locator('.pg-template[data-template="screener"]').click();
  await run(page);
  await zoomTo(page, "near");
  const rows = await page.locator(".react-flow__node-pg .pg-node").evaluateAll((els) => els.map((n) => {
    const s = n.querySelector(".pg-node-slot")!, f = n.querySelector(".pg-node-foot");
    const z = Number(getComputedStyle(n.closest(".pg-canvas")!).getPropertyValue("--pg-z"));
    const top = s.getBoundingClientRect().top;
    const kids = [...s.children].filter((c) => (c as HTMLElement).offsetParent !== null);
    const bottom = Math.max(top, ...kids.map((c) => c.getBoundingClientRect().bottom));
    return { id: n.getAttribute("data-node-id")!, kind: n.getAttribute("data-kind")!, content: (bottom - top) / z,
             over: f ? (bottom - f.getBoundingClientRect().top) / z : 0, h: n.getBoundingClientRect().height / z };
  }));
  // ★공허 배제★ — 이 흐름에는 큰 결과 그림이 실제로 있다(작은 그림만 있으면 이 검사는 아무것도 재지 않는다).
  expect(Math.max(...rows.map((r) => r.content)), "가장 큰 결과 그림 높이").toBeGreaterThan(120);
  for (const r of rows) {
    expect(r.over, `${r.id} 결과 그림이 상태 줄을 덮는다(${r.content.toFixed(0)})`).toBeLessThanOrEqual(1);
    expect(Math.abs(r.h - cardHeight(r.kind, cat)), `${r.id} 상자 높이`).toBeLessThanOrEqual(1);
  }
});

// 사용자 결정(2026-10-17): 처음 열 때는 보통 확대 이상. 자리 고정 상자로 흐름 전체를 한 화면에 담으면 1280~1440 창에서 멀리(이름·값만)로 열렸다.
// 넘치는 오른쪽·아래는 끌거나 맞춤 단추로 본다 — 맞춤 단추는 그대로 전체를 담는다(짝).
test("처음 열림(CF1): 보통 확대 이상으로 열리고 흐름의 시작이 보인다 · 짝: 맞춤 단추는 전체를 담느라 멀리로 줄일 수 있다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openWith(page, null);
  // 1440×900 에서 전체를 담는 맞춤은 0.45 — 바닥 0.55 에 멈춘다(React Flow 첫 확대율 1 에서 바로 통과하지 않게 값을 못 박는다).
  await expect.poll(() => zoomOf(page), { timeout: 5_000 }).toBeCloseTo(0.55, 2);
  await expect(canvas(page)).not.toHaveAttribute("data-zoom", "far");
  const first = (await rfNode(page, "universe").boundingBox())!;
  const cv = (await page.locator(".react-flow").boundingBox())!;
  const pl = await page.locator(".pg-palette").boundingBox();
  expect(first.x, "흐름의 시작(종목 고르기)이 왼쪽 판 밖에 보인다").toBeGreaterThanOrEqual((pl ? pl.x + pl.width : cv.x) - 1);
  expect(first.y, "위로 잘리지 않는다").toBeGreaterThanOrEqual(cv.y);
  await page.locator(".react-flow__controls-fitview").click();
  await expect(canvas(page)).toHaveAttribute("data-zoom", "far");
});

test("단계별 보임(CF1): 가까이 = 위젯·결과 자리 · 중간 = 소켓 이름·요약(위젯 없음) · 멀리 = 이름·값(소켓 이름 없음)", async ({ page }) => {
  await openWith(page, null);
  const opt = node(page, "optimizer");
  const portName = opt.locator(".pg-port--in .pg-port-name").first();
  await zoomTo(page, "near");
  await expect(opt.locator(".pg-cw")).toBeVisible();
  await expect(opt.locator('.pg-cw-f[data-field="model"]')).toBeVisible();
  await expect(opt.locator(".pg-node-slot-empty")).toHaveText("계산하면 결과가 여기에 보여요");
  await expect(portName).toBeVisible();
  await expect(opt.locator(".pg-node-far")).toBeHidden();

  await zoomTo(page, "mid");
  await page.mouse.move(5, 5);                       // 올림(hover)이 아니어도 보인다
  await expect(portName).toBeVisible();
  await expect(opt.locator(".pg-node-t")).toBeVisible();
  await expect(opt.locator(".pg-cw")).toBeHidden();
  await expect(opt.locator(".pg-node-slot-empty")).toBeHidden();

  await zoomTo(page, "far");
  await expect(opt.locator(".pg-node-far")).toBeVisible();
  await expect(portName).toBeHidden();
  await expect(opt.locator(".pg-cw")).toBeHidden();
  // 멀리 = 큰 이름·값이 ★상자를 채운다★ — 빈 결과 자리가 남는 높이를 나눠 가지면 글이 위쪽 반에 몰리고 아래 반이 비어 보인다.
  for (const id of ["returns", "optimizer", "backtest"]) {
    const g = await node(page, id).evaluate((el) => {
      const c = el.getBoundingClientRect(), f = el.querySelector(".pg-node-far")!.getBoundingClientRect();
      return { fill: f.height / c.height, off: Math.abs(f.top + f.height / 2 - (c.top + c.height / 2)) / c.height };
    });
    expect(g.fill, `${id} 멀리 글 자리 / 상자 높이`).toBeGreaterThan(0.8);
    expect(g.off, `${id} 멀리 글 자리가 상자 가운데`).toBeLessThan(0.05);
  }
});

test("카드 위젯(CF1): 방식을 바꾸면 설정 판도 같은 값 · 그 노드와 하류만 예전 결과(짝: 상류 그대로) · Ctrl+Z 한 번에 돌아간다", async ({ page }) => {
  await openWith(page, null);
  await run(page);
  await zoomTo(page, "near");
  await center(page, "optimizer");
  const sel = node(page, "optimizer").locator('.pg-cw-f[data-field="model"] select');
  const before = await sel.locator("option:checked").textContent();
  const labels = await sel.locator("option:not([disabled])").allTextContents();
  const next = labels.find((l) => l !== before)!;
  await sel.selectOption({ label: next });
  await expect(sel.locator("option:checked")).toHaveText(next);
  // 하류(비중 → 위험·과거로 돌려 보기)만 낡는다 — 상류는 결과 그대로.
  for (const id of ["optimizer", "risk", "backtest"]) await expect(node(page, id), id).toHaveClass(/pg-node--stale/);
  for (const id of ["universe", "returns", "estimate", "views"]) await expect(node(page, id), id).not.toHaveClass(/pg-node--stale/);
  // 설정 판의 같은 칸이 같은 값을 보인다(값을 쓰는 길이 하나).
  await node(page, "optimizer").locator(".pg-node-k").click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(page.locator('.pg-basic-field[data-field="model"] .pg-choice[aria-pressed="true"]')).toContainText(next);
  // 되돌리기 한 번 — 입력 칸 밖에서.
  await clickEmpty(page);
  await page.keyboard.press("Control+z");
  await expect(sel.locator("option:checked")).toHaveText(before!);
  await expect(page.locator(".pg-node--stale")).toHaveCount(0);
});

test("카드 위젯(CF1): 조건부 칸(show_if)은 조건이 맞을 때만 나타나고 상자는 그대로 · 위젯 위에서 끌어도 노드가 움직이지 않는다", async ({ page }) => {
  await openWith(page, null);
  await zoomTo(page, "near");
  await center(page, "optimizer");
  const opt = node(page, "optimizer");
  const cat = (await catalog(page)).nodes;
  const ui = cat.find((c) => c.type === "optimizer")!.params_schema as { properties: Record<string, { "x-ui"?: { options?: Record<string, string> } }> };
  const h0 = (await boxes(page, ["optimizer"])).optimizer.h;
  await expect(opt.locator('.pg-cw-f[data-field="risk_aversion"]')).toHaveCount(0);
  await opt.locator('.pg-cw-f[data-field="model"] select').selectOption({ label: ui.properties.model["x-ui"]!.options!.mv_utility });
  await expect(opt.locator('.pg-cw-f[data-field="risk_aversion"] input[type="range"]')).toBeVisible();
  expect(Math.abs((await boxes(page, ["optimizer"])).optimizer.h - h0), "조건부 칸이 나타나도 상자 그대로").toBeLessThanOrEqual(1);
  // nodrag — 질문 글자를 잡고 끌어도 노드 자리는 그대로(캔버스가 끌기를 가로채지 않는다).
  const t0 = await rfNode(page, "optimizer").evaluate((el) => (el as HTMLElement).style.transform);
  const q = await mid(opt.locator('.pg-cw-f[data-field="model"] .pg-cw-q'));
  await page.mouse.move(q.x, q.y); await page.mouse.down();
  await page.mouse.move(q.x + 90, q.y + 60, { steps: 6 }); await page.mouse.up();
  expect(await rfNode(page, "optimizer").evaluate((el) => (el as HTMLElement).style.transform)).toBe(t0);
});

test("카드 위젯(CF1): 그릴 수 없는 칸만 있는 노드는 '설정 더 보기' → 그 노드의 설정 탭(짝: 다 그릴 수 있는 노드엔 단추 없음)", async ({ page }) => {
  await openWith(page, null);
  await zoomTo(page, "near");
  await center(page, "views");
  await expect(node(page, "optimizer").locator(".pg-cw-more")).toHaveCount(0);
  await node(page, "views").locator(".pg-cw-more").click();
  await expect(page.locator('.pg-tab[data-tab="settings"]')).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('.pg-basic-field[data-field="views"]')).toBeVisible();
  await expect(node(page, "views")).toHaveClass(/pg-node--selected/);
});

test("소켓(CF2): 선택 입력은 빈 원·필수는 채운 원(짝) · 합치기 입력은 네모(짝) · 나가는 선이 둘 이상이면 'n곳'(짝: 하나면 없음)", async ({ page }) => {
  await openWith(page, null);
  await zoomTo(page, "near");
  const paper = await node(page, "optimizer").evaluate((el) => getComputedStyle(el).backgroundColor);
  const bg = (id: string, port: string) => handle(page, id, port, "target").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(await bg("optimizer", "views"), "선택 입력 = 빈 원(카드 바탕색)").toBe(paper);
  expect(await bg("optimizer", "returns"), "필수 입력 = 타입색으로 채움").not.toBe(paper);
  await expect(node(page, "optimizer").locator(".pg-port--opt")).toHaveCount(1);
  await expect(node(page, "optimizer").locator(".pg-port--opt .pg-port-opt")).toHaveText(/선택/);
  // 수익률은 세 곳(기대 수익 추정·비중 계산·과거로 돌려 보기)으로 나간다 — 하나면 표시가 없다.
  await expect(node(page, "returns").locator(".pg-port--out .pg-port-n")).toHaveText(/3곳/);
  await expect(node(page, "universe").locator(".pg-port--out .pg-port-n")).toHaveCount(0);

  await page.evaluate(() => sessionStorage.clear());
  await openWith(page, { ...F, nodes: [n("combine", "portfolio_combine", 0, 0), n("optimizer", "optimizer", 320, 0)], edges: [] });
  const radius = (id: string, port: string) => handle(page, id, port, "target").evaluate((el) => getComputedStyle(el).borderTopLeftRadius);
  expect(await radius("combine", "s1"), "합치기 = 여러 전략을 받는 네모 칸").toBe("3px");
  expect(await radius("optimizer", "returns")).not.toBe("3px");
});

test("끄는 중(CF2): 선 색 = 보내는 타입 색 · 막힌 소켓 위에서 사유 글이 놓기 전에 보인다(= connectionProblem) · 짝: 맞는 소켓 위엔 없다", async ({ page }) => {
  await openWith(page, SMALL);
  const cat = await catalog(page);
  const from = handle(page, "returns", "returns", "source");
  const typeColor = await from.evaluate((el) => getComputedStyle(el).backgroundColor);
  const a = await mid(from);
  await page.mouse.move(a.x, a.y); await page.mouse.down();
  const ok = await mid(handle(page, "optimizer", "returns", "target"));
  await page.mouse.move(ok.x, ok.y, { steps: 10 });
  await expect(page.locator(".pg-drag-wire path")).toHaveCount(1);
  expect(await page.locator(".pg-drag-wire path").evaluate((el) => getComputedStyle(el).stroke)).toBe(typeColor);
  await expect(page.locator(".pg-drag-why")).toHaveCount(0);
  const bad = await mid(handle(page, "optimizer", "belief", "target"));
  await page.mouse.move(bad.x, bad.y, { steps: 10 });
  const nodes: ConnNode[] = SMALL.nodes.map((x) => ({ id: x.id, data: { kind: x.type } }));
  const edges: ConnEdge[] = SMALL.edges.map((x) => ({ source: x.source, target: x.target, sourceHandle: x.source_port, targetHandle: x.target_port }));
  const why = connectionProblem({ source: "returns", sourceHandle: "returns", target: "optimizer", targetHandle: "belief" }, nodes, edges, cat.nodes, cat.port_plain);
  expect(why).toBeTruthy();
  await expect(page.locator(".pg-drag-why")).toHaveText(why!);
  // ★보이는 줄★ — 사유 글이 오른쪽 판 밑이나 캔버스 밖으로 잘리지 않는다(오른쪽으로 끌 때는 커서 왼쪽, 끌어 온 쪽에 쓴다).
  const wb = (await page.locator(".pg-drag-why").boundingBox())!;
  const cv = (await page.locator(".react-flow").boundingBox())!;
  const sd = await page.locator(".pg-side").boundingBox();
  expect(wb.x, "사유 글 왼쪽 끝").toBeGreaterThanOrEqual(cv.x);
  expect(wb.x + wb.width, "사유 글 오른쪽 끝 — 오른쪽 판 앞").toBeLessThanOrEqual(sd ? sd.x : cv.x + cv.width);
  expect(wb.x + wb.width, "오른쪽으로 끌면 글은 커서 왼쪽(끌어 온 쪽)").toBeLessThanOrEqual(bad.x);
  await expect(page.locator(".pg-drag-wire--bad")).toHaveCount(1);
  await page.mouse.up();
  await expect(page.locator(".pg-note")).toContainText(why!);       // 놓은 뒤에도 같은 말
  await expect(page.locator(".react-flow__edge")).toHaveCount(2);

  // 짝 — 왼쪽으로 끌면(받는 소켓에서 앞 노드로) 글은 커서 오른쪽.
  const b = await mid(handle(page, "optimizer", "belief", "target"));
  await page.mouse.move(b.x, b.y); await page.mouse.down();
  const r = await mid(handle(page, "returns", "returns", "source"));
  await page.mouse.move(r.x, r.y, { steps: 10 });
  await expect(page.locator(".pg-drag-why")).toHaveCount(1);
  const wl = (await page.locator(".pg-drag-why").boundingBox())!;
  expect(wl.x, "왼쪽으로 끌면 글은 커서 오른쪽").toBeGreaterThanOrEqual(r.x);
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(2);
});

test("다시 꽂기(CF2): 맞는 소켓으로 옮기면 선 수 같고 id 바뀜 · Ctrl+Z 한 번 · 틀린 소켓은 사유 + 선 그대로 · 제자리에 놓아도 거부하지 않는다", async ({ page }) => {
  await openWith(page, SMALL);
  const cat = await catalog(page);
  const OLD = "returns.returns->estimate.returns";
  const end = () => page.locator(`.react-flow__edge[data-id="${OLD}"] .react-flow__edgeupdater-target`);
  const drag = async (to: { x: number; y: number }) => {
    const s = await mid(end());
    await page.mouse.move(s.x, s.y); await page.mouse.down();
    await page.mouse.move(to.x, to.y, { steps: 12 }); await page.mouse.up();
  };
  const before = await edgeIds(page);
  // 제자리 — 옮기는 선 자신 때문에 "이미 이어져 있어요"가 되면 안 된다.
  await drag(await mid(handle(page, "estimate", "returns", "target")));
  expect(await edgeIds(page)).toEqual(before);
  await expect(page.locator(".pg-note")).toHaveCount(0);
  // 틀린 소켓(수익률 → 생각 자리) — 사유를 말하고 선은 그대로.
  await drag(await mid(handle(page, "optimizer", "belief", "target")));
  const nodes: ConnNode[] = SMALL.nodes.map((x) => ({ id: x.id, data: { kind: x.type } }));
  const rest: ConnEdge[] = SMALL.edges.filter((x) => x.id !== OLD)
    .map((x) => ({ source: x.source, target: x.target, sourceHandle: x.source_port, targetHandle: x.target_port }));
  const why = connectionProblem({ source: "returns", sourceHandle: "returns", target: "optimizer", targetHandle: "belief" }, nodes, rest, cat.nodes, cat.port_plain)!;
  await expect(page.locator(".pg-note")).toContainText(why);
  await expect(page.locator(".pg-note")).toContainText("선은 그대로 두었어요");
  expect(await edgeIds(page)).toEqual(before);
  // 맞는 소켓 — 선 수 같고 id 가 바뀐다.
  await drag(await mid(handle(page, "optimizer", "returns", "target")));
  const after = await edgeIds(page);
  expect(after).toHaveLength(before.length);
  expect(after).toContain("returns.returns->optimizer.returns");
  expect(after).not.toContain(OLD);
  await clickEmpty(page);
  await page.keyboard.press("Control+z");
  await expect.poll(() => edgeIds(page)).toEqual(before);
});

test("소켓 두 번 누르기(CF2): 내는 소켓 = 그 값을 받는 노드 · 받는 소켓 = 그 값을 내는 노드 · 캔버스 확대 그대로", async ({ page }) => {
  await openWith(page, null);
  await center(page, "optimizer");                  // 처음 열림은 보통 확대 — 오른쪽 열은 판 밑일 수 있어 끌어 온다
  const z0 = await zoomOf(page);
  // 노드를 고르면 판이 200ms 동안 옆으로 비킨다(오른쪽 창) — 그동안 d3 의 부드러운 이동이 확대를 1e-4 쯤 잠깐 낮췄다 되돌린다.
  // ★끝난 값★을 본다(두 번 누르기가 캔버스를 확대했다면 그 값에 머물러 실패한다).
  await handle(page, "optimizer", "weights", "source").dblclick();
  const q = page.locator(".pg-quick");
  await expect(q).toHaveAttribute("data-type", "Weights");
  await expect(q.locator('.pg-quick-item[data-kind="risk"]')).toHaveCount(1);
  await expect(q.locator('.pg-quick-item[data-kind="returns"]'), "비중을 받지 않는 노드는 없다").toHaveCount(0);
  await expect.poll(() => zoomOf(page)).toBe(z0);
  await page.keyboard.press("Escape");
  await handle(page, "optimizer", "returns", "target").dblclick();
  await expect(q).toHaveAttribute("data-type", "Returns");
  await expect(q.locator('.pg-quick-item[data-kind="returns"]')).toHaveCount(1);
  await expect(q.locator('.pg-quick-item[data-kind="risk"]'), "수익률을 내지 않는 노드는 없다").toHaveCount(0);
  await expect.poll(() => zoomOf(page)).toBe(z0);
});

test("접기(CF1): 머리 줄만 · 핸들은 머리 가운데 · 선 그대로 · 작업 중 문서와 내보낸 파일에 남는다 · 짝: 펴면 원래대로", async ({ page }) => {
  await openWith(page, null);
  await zoomTo(page, "near");
  await center(page, "optimizer");
  const opt = node(page, "optimizer");
  const edges = await edgeIds(page);
  await opt.locator(".pg-node-fold").click();
  await expect(opt).toHaveClass(/pg-node--folded/);
  await expect(opt.locator(".pg-node-fold")).toHaveAttribute("aria-pressed", "true");
  await expect(opt.locator(".pg-cw")).toBeHidden();
  await expect(opt.locator(".pg-node-slot")).toBeHidden();
  expect(await edgeIds(page)).toEqual(edges);
  const z = await zoomOf(page);
  const top = (await opt.boundingBox())!.y;
  const hy = (await mid(handle(page, "optimizer", "returns", "target"))).y;
  expect(Math.abs((hy - top) / z - 25), "핸들 = 머리 가운데(테두리 1 + 12 + 24/2)").toBeLessThanOrEqual(1.5);
  // 작업 중 문서 — 다시 열어도 접혀 있다.
  await page.waitForTimeout(400);
  await page.reload();
  await expect(node(page, "optimizer")).toHaveClass(/pg-node--folded/, { timeout: 30_000 });
  // 내보낸 파일에도 남는다.
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const doc = JSON.parse(readFileSync((await (await dl).path())!, "utf-8")) as { folded?: string[] };
  expect(doc.folded).toEqual(["optimizer"]);
  // 펴면 원래대로 — 다시 가까이 본 뒤 그 노드를 화면 가운데로(사람처럼 끌어서). 그림판은 스크롤되지 않는다(overflow: clip) — 화면 밖 단추는 누를 수 없다.
  await zoomTo(page, "near");
  await center(page, "optimizer");
  await node(page, "optimizer").locator(".pg-node-fold").click();
  await expect(node(page, "optimizer")).not.toHaveClass(/pg-node--folded/);
  await expect(node(page, "optimizer").locator(".pg-cw")).toBeVisible();
});

/** 화면의 카드끼리 겹치는 쌍. */
async function overlaps(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const r = [...document.querySelectorAll<HTMLElement>(".pg-node")].map((x) => [x.dataset.nodeId!, x.getBoundingClientRect()] as const);
    const out: string[] = [];
    for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {
      const [a, A] = r[i], [b, B] = r[j];
      if (A.left < B.right - 1 && B.left < A.right - 1 && A.top < B.bottom - 1 && B.top < A.bottom - 1) out.push(`${a}×${b}`);
    }
    return out;
  });
}

test("배치(CF1): 기본 흐름·템플릿은 새 높이로 다시 쌓여 겹치지 않는다 · 안내도 없다", async ({ page }) => {
  await openWith(page, null);
  expect(await overlaps(page)).toEqual([]);
  await expect(page.locator(".pg-toasts")).not.toContainText(OVERLAP_NOTE);
  await page.locator("#pg-left-tab-add").click();
  for (const key of ["stress", "risk"]) {
    await page.locator(`.pg-template[data-template="${key}"]`).click();
    await expect.poll(() => overlaps(page), key).toEqual([]);
  }
});

test("배치(CF1): 예전 크기로 놓인 작업 중 문서는 옮기지 않고 '자동 정리' 안내 · 짝: 안 겹치는 문서는 안내 없음", async ({ page, browser }) => {
  const OLD = { ...F, nodes: [n("universe", "universe", 0, 140, T), n("returns", "returns", 230, 140), n("estimate", "estimate", 460, 20),
                              n("optimizer", "optimizer", 690, 140)],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                        e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")] };
  await openWith(page, OLD);
  await expect(page.locator(".pg-toasts")).toContainText(OVERLAP_NOTE);
  expect((await overlaps(page)).length, "옮기지 않았다").toBeGreaterThan(0);

  const other = await browser.newPage();
  const SPACED = { ...OLD, nodes: OLD.nodes.map((x, i) => ({ ...x, position: { x: i * 320, y: 0 } })) };
  await openWith(other, SPACED);
  await other.waitForTimeout(600);
  await expect(other.locator(".pg-toasts")).not.toContainText(OVERLAP_NOTE);
  await other.close();
});

for (const scheme of ["light", "dark"] as const) {
  test(`대비(CF1): ${scheme} — 가까이(위젯·소켓 이름·결과 자리) AA 미달 0`, async ({ page }) => {
    await openWith(page, null);
    await run(page);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await zoomTo(page, "near");
    await center(page, "optimizer");
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-canvas"));
    expect(audit.checked).toBeGreaterThan(20);
    expect(audit.low, `${scheme} AA 미달`).toEqual([]);
    if (scheme === "dark") expect(audit.bright, "다크인데 밝은 배경").toEqual([]);
  });
}

test("390(CF1): 좁은 화면에서도 가로로 넘치지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openWith(page, null);
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over).toBeLessThanOrEqual(0);
});
