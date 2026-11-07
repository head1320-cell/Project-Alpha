import { test, expect, type Page } from "./fixtures";
import { strategyEnds } from "../src/entities/portfolio-graph/strategy";
import type { NodeCatalogEntry } from "../src/entities/portfolio-graph/types";

/**
 * CF 3부 U6 · 갈래와 전략 상자 (스펙 §8.4 결정 5 — 사용자 결정 2026-11-01 "원본이 전략이면 자동 + 그 밖엔 단추")
 *  · 전략 상자째 갈래 → 복제도 새 전략 상자(이름 '<전략> · 갈래 X' · 출력 = 원본 출력의 복제) · 되돌리기 한 번에 복제·상자 모두 · 두 머리가 겹치지 않는다.
 *  · 고른 노드째 갈래 → 틀만(상자 없음) + 틀 머리 [전략으로 묶기] → 누르면 상자 · 비중 노드가 없으면 까닭 · 갈래를 지우면 그 상자도(원본 전략 그대로).
 */
type Group = { id: string; label: string; members: string[]; kind?: string; output?: string | null };
type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[]; edges: { source: string; target: string }[];
             groups?: Group[]; branches?: { id: string; label: string; root: string; of_root: string; map: Record<string, string> }[] };
const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
/** 종목 → 수익률 → 추정 → 비중(전략 아님). */
const CORE = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
                             n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0)],
               edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                       e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")] };
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const strategiesOf = (d: Doc) => (d.groups ?? []).filter((g) => g.kind === "strategy");
const mod = process.platform === "darwin" ? "Meta" : "Control";
const overlap = (a: { x: number; y: number; width: number; height: number }, b: { x: number; y: number; width: number; height: number }) =>
  Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));

async function openWith(page: Page, doc: object | null) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("u6_seeded")) return;
      sessionStorage.setItem("u6_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      if (d) sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
}
async function pickByCmd(page: Page, ids: string[], cmd: string, query: string) {
  // 갈래를 만들면 화면이 새 갈래로 옮겨진다 — 고르기 전에 맞춰 보기(카드가 떠 있는 판 밑에 들지 않게)
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await page.locator(".react-flow__pane").click({ position: { x: 360, y: 20 } });
  await page.locator(`.react-flow__node[data-id="${ids[0]}"] .pg-node`).click({ position: { x: 30, y: 14 } });
  for (const id of ids.slice(1)) await page.locator(`.react-flow__node[data-id="${id}"] .pg-node`).click({ position: { x: 30, y: 14 }, modifiers: [mod] });
  await page.keyboard.press("Control+k");
  await page.getByLabel("명령 찾기").last().fill(query);
  await expect(page.locator(`.pg-cmd-item[data-cmd="${cmd}"]`)).toBeVisible();
  await page.keyboard.press("Enter");
}

test.use({ viewport: { width: 1440, height: 900 } });

test("U6 · 전략째 갈래 → 복제도 새 전략 상자(이름 '<전략> · 갈래 X' · 출력 = 원본 출력의 복제) · 두 머리가 겹치지 않음 · 되돌리기 한 번에 복제·상자 모두 (짝: 원본 전략 그대로)", async ({ page }) => {
  await openWith(page, null);
  await page.locator(".pg-strat-add").click();
  await page.locator('.pg-strat-item[data-source="tpl:stress"]').click();
  await expect(page.locator(".pg-group--strategy")).toHaveCount(2);
  let doc = await wip(page);
  const [, b] = strategiesOf(doc);
  const bBefore = JSON.stringify(b);
  await page.locator(`.pg-group--strategy[data-group-id="${b.id}"] .pg-group-branch`).click();
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  doc = await wip(page);
  const br = doc.branches![0];
  const ss = strategiesOf(doc);
  expect(ss, "전략 상자가 하나 늘었다").toHaveLength(3);
  const made = ss.find((g) => g.id !== b.id && Object.keys(br.map).includes(g.members[0]))!;
  expect(made, "복제를 담은 새 전략 상자").toBeTruthy();
  expect(made.label).toBe(`${b.label} · ${br.label}`);
  expect([...made.members].sort()).toEqual(Object.keys(br.map).sort());
  expect(br.map[made.output!], "출력 = 원본 출력의 복제").toBe(b.output);
  expect(JSON.stringify(strategiesOf(doc).find((g) => g.id === b.id))).toBe(bBefore);
  await expect(page.locator(`.pg-group--strategy[data-group-id="${made.id}"]`)).toBeVisible();
  // 두 머리(갈래 틀 · 새 전략 상자)는 겹치지 않는다
  const bh = (await page.locator(".pg-branch-head").boundingBox())!;
  const gh = (await page.locator(`.pg-group--strategy[data-group-id="${made.id}"] .pg-group-head`).boundingBox())!;
  expect(overlap(bh, gh), "갈래 틀 머리 × 전략 상자 머리").toBe(0);
  // 되돌리기 한 번 — 복제·상자·갈래 모두
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  await expect(page.locator(".pg-branch")).toHaveCount(0);
  doc = await wip(page);
  expect(strategiesOf(doc)).toHaveLength(2);
  expect(doc.branches ?? []).toEqual([]);
});

test("U6 · 고른 노드째 갈래는 틀만 + [전략으로 묶기] → 누르면 전략 상자(출력 = 비중 계산 복제) · 되돌리기 한 번 (짝: 비중 노드 없는 갈래는 까닭 · 갈래를 지우면 그 상자도)", async ({ page }) => {
  await openWith(page, CORE);
  await pickByCmd(page, ["estimate", "optimizer"], "branch-picked", "고른 노드째 갈래");
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  let doc = await wip(page);
  expect(strategiesOf(doc), "고른 노드째 갈래는 상자를 만들지 않는다").toHaveLength(0);
  const br = doc.branches![0];
  const btn = page.locator(`.pg-branch[data-branch-id="${br.id}"] .pg-branch-strategy`);
  await expect(btn).toBeVisible();
  await btn.click();
  await expect(page.locator(".pg-note")).toContainText("전략");
  doc = await wip(page);
  const [s] = strategiesOf(doc);
  expect([...s.members].sort()).toEqual(Object.keys(br.map).sort());
  expect(br.map[s.output!]).toBe("optimizer");
  await expect(btn, "묶은 뒤에는 단추가 없다").toHaveCount(0);
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  await expect.poll(async () => strategiesOf(await wip(page)).length, "되돌리기 한 번에 상자만 사라짐").toBe(0);
  expect((await wip(page)).branches ?? []).toHaveLength(1);
  await expect(btn).toBeVisible();

  // 짝 — 비중 노드가 없는 갈래(종목·수익률)는 까닭 · 상자 없음
  await pickByCmd(page, ["universe", "returns"], "branch-picked", "고른 노드째 갈래");
  await expect(page.locator(".pg-branch")).toHaveCount(2);
  doc = await wip(page);
  const br2 = doc.branches!.find((x) => x.id !== br.id)!;
  await page.locator(`.pg-branch[data-branch-id="${br2.id}"] .pg-branch-strategy`).click();
  await expect(page.locator(".pg-note")).toContainText("비중을 내는 노드가 없어요");
  expect(strategiesOf(await wip(page))).toHaveLength(0);

  // 짝 — 첫 갈래를 묶은 뒤 그 갈래를 지우면 상자도 사라진다(둘째 갈래로 화면이 옮겨졌으니 맞춰 보기부터 — 머리가 오른쪽 창 밑에 들지 않게)
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await btn.click();
  await expect.poll(async () => strategiesOf(await wip(page)).length).toBe(1);
  await page.locator(`.pg-branch[data-branch-id="${br.id}"] .pg-branch-x`).click();
  await expect.poll(async () => (await wip(page)).branches?.length ?? 0).toBe(1);
  expect(strategiesOf(await wip(page)), "지운 갈래의 상자는 남지 않는다").toHaveLength(0);
});

test("U6 · 짝 — 전략째 갈래를 원본으로 올리면 갈래의 상자도 사라진다(빈 상자가 남지 않음 · 원본 전략 그대로)", async ({ page }) => {
  await openWith(page, null);
  await page.locator(".pg-strat-add").click();
  await page.locator('.pg-strat-item[data-source="tpl:stress"]').click();
  await expect(page.locator(".pg-group--strategy")).toHaveCount(2);
  const before = strategiesOf(await wip(page));
  await page.locator(`.pg-group--strategy[data-group-id="${before[1].id}"] .pg-group-branch`).click();
  await expect.poll(async () => strategiesOf(await wip(page)).length).toBe(3);
  // 올리기는 바꾼 설정이 있어야 눌린다 — 전략 출력(비중 계산)의 복제를 골라 켜지지 않은 보기 하나를 누른다(뿌리 복제는 종목 칸뿐이다)
  const br = (await wip(page)).branches![0];
  const outCopy = Object.entries(br.map).find(([, o]) => o === before[1].output)![0];
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await page.locator(`.react-flow__node[data-id="${outCopy}"] .pg-node`).click({ position: { x: 30, y: 14 } });
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator(".pg-basic-field .pg-chip:not(.on):not(.pg-chip--custom)").first().click();
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await expect(page.locator(".pg-branch .pg-branch-promote")).toBeEnabled();
  await page.locator(".pg-branch .pg-branch-promote").click();
  await expect(page.locator(".pg-note")).toContainText("원본으로 옮겼어요");
  await expect(page.locator(".pg-branch")).toHaveCount(0);
  const doc = await wip(page);
  expect((doc.groups ?? []).filter((g) => g.members.length === 0), "빈 상자가 남지 않는다").toEqual([]);
  expect(strategiesOf(doc).map((g) => g.id)).toEqual(before.map((g) => g.id));
  await expect(page.locator(".pg-group--strategy")).toHaveCount(2);
});

// ── U6 이어서 · 결정 5 '출력을 정할 수 없으면(범위 안 흐름 끝이 둘 이상) 까닭' (사용자 결정 2026-11-01 그대로 — U6 이 남긴 것) ──────────
const W = (type: string, ins: string[], outs: string[]) => ({ type, inputs: ins.map((t) => ({ type: t })), outputs: outs.map((t) => ({ type: t })) });
const CAT = [W("returns", [], ["Returns"]), W("optimizer", ["Returns"], ["Weights"]), W("neutralize", ["Weights"], ["Weights"]), W("backtest", ["Weights"], ["Metrics"]), W("mid", ["Weights"], ["Returns"])] as unknown as NodeCatalogEntry[];
const nd = (id: string, kind: string) => ({ id, position: { x: 0, y: 0 }, data: { kind } });
const ed = (source: string, target: string) => ({ source, target });

test("U6 규칙 · strategyEnds — 범위 안에서 비중을 내고 그 뒤에 비중을 내는 구성원이 없는 끝들 (짝: 줄로 이어지면 끝은 하나 · 고르지 않은 노드를 거쳐도 이어진 것 · 비중이 없으면 0 · 범위 밖 하류는 세지 않음)", () => {
  const nodes = [nd("r", "returns"), nd("a", "optimizer"), nd("b", "optimizer"), nd("n", "neutralize"), nd("t", "backtest")];
  const par = [ed("r", "a"), ed("r", "b")];
  expect(strategyEnds(["a", "b"], nodes, par, CAT), "나란한 비중 계산 둘 = 끝 둘").toEqual(["a", "b"]);
  const ser = [ed("r", "a"), ed("a", "n"), ed("n", "t")];
  expect(strategyEnds(["a", "n", "t"], nodes, ser, CAT), "비중 → 치우침 없애기 → 돌려 보기 = 끝 하나(뒤쪽)").toEqual(["n"]);
  expect(strategyEnds(["a", "t"], nodes, [ed("a", "t")], CAT), "비중을 받기만 하는 노드는 끝이 아니다").toEqual(["a"]);
  expect(strategyEnds(["r"], nodes, par, CAT)).toEqual([]);
  expect(strategyEnds(["a"], nodes, ser, CAT), "범위 밖 하류(n)는 세지 않는다").toEqual(["a"]);
  // 고르지 않은 노드를 거쳐 이어져도 흐름은 흐름 — 비중 계산 → (고르지 않은 m) → 비중 계산 = 끝 하나(뒤쪽)
  const via = [...nodes, nd("m", "mid")];
  expect(strategyEnds(["a", "b"], via, [ed("r", "a"), ed("a", "m"), ed("m", "b")], CAT), "범위 밖을 거쳐 이어진 둘 = 끝 하나").toEqual(["b"]);
});

test("U6 · 끝이 둘인 갈래는 [전략으로 묶기]가 까닭을 말하고 상자를 만들지 않는다 (짝: 줄로 이어진 갈래는 묶이고 출력 = 뒤쪽 끝의 복제)", async ({ page }) => {
  const PAR = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
                              n("optA", "optimizer", 660, 0), n("optB", "optimizer", 990, 0, { model: "risk_parity" })],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optA", "returns"), e("returns", "returns", "optB", "returns")] };
  await openWith(page, PAR);
  await pickByCmd(page, ["optA", "optB"], "branch-picked", "고른 노드째 갈래");
  await expect(page.locator(".pg-branch")).toHaveCount(1);
  const br = (await wip(page)).branches![0];
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(400);
  await page.locator(`.pg-branch[data-branch-id="${br.id}"] .pg-branch-strategy`).click();
  await expect(page.locator(".pg-note")).toContainText("비중을 내는 끝이 2개");
  expect(strategiesOf(await wip(page)), "끝이 둘이면 상자 없음").toHaveLength(0);

  // 짝 — 비중 계산 → 치우침 없애기(줄)는 끝 하나: 묶이고 출력 = 치우침 없애기의 복제
  const SER = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
                              n("opt", "optimizer", 660, 0), n("neu", "neutralize", 990, 0)],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "opt", "returns"), e("opt", "weights", "neu", "weights")] };
  const other = await page.context().newPage();
  await openWith(other, SER);
  await pickByCmd(other, ["opt", "neu"], "branch-picked", "고른 노드째 갈래");
  const br2 = (await wip(other)).branches![0];
  await other.locator(".react-flow__controls-fitview").click();
  await other.waitForTimeout(400);
  await other.locator(`.pg-branch[data-branch-id="${br2.id}"] .pg-branch-strategy`).click();
  await expect.poll(async () => strategiesOf(await wip(other)).length).toBe(1);
  const [box] = strategiesOf(await wip(other));
  expect(br2.map[box.output!], "출력 = 뒤쪽 끝(치우침 없애기)의 복제").toBe("neu");
});

test("U6 이어서 · Ctrl+K '전략으로 묶기' 도 끝이 둘이면 까닭을 말하고 묶지 않는다 — 하나를 말없이 고르지 않음 (짝: 줄로 이어진 둘은 묶이고 출력 = 뒤쪽 끝)", async ({ page }) => {
  const PAR = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
                              n("optA", "optimizer", 660, 0), n("optB", "optimizer", 990, 0, { model: "risk_parity" })],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optA", "returns"), e("returns", "returns", "optB", "returns")] };
  await openWith(page, PAR);
  await pickByCmd(page, ["optA", "optB"], "strategy-picked", "전략으로 묶기");
  await expect(page.locator(".pg-note")).toContainText("비중을 내는 끝이 2개");
  expect(strategiesOf(await wip(page)), "끝이 둘이면 상자 없음").toHaveLength(0);

  const SER = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
                              n("opt", "optimizer", 660, 0), n("neu", "neutralize", 990, 0)],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "opt", "returns"), e("opt", "weights", "neu", "weights")] };
  const other = await page.context().newPage();
  await openWith(other, SER);
  await pickByCmd(other, ["opt", "neu"], "strategy-picked", "전략으로 묶기");
  await expect.poll(async () => strategiesOf(await wip(other)).length).toBe(1);
  const [box] = strategiesOf(await wip(other));
  expect(box.output, "출력 = 뒤쪽 끝(치우침 없애기)").toBe("neu");
  expect([...box.members].sort()).toEqual(["neu", "opt"]);
});

test("U6 이어서 · '전략 추가' 가 지금 흐름을 '전략 1' 로 묶을 때도 끝이 둘이면 묶지 않고 까닭 — 새 전략은 그대로 들어간다 (짝: 끝이 하나인 흐름은 예전처럼 묶임)", async ({ page }) => {
  const PAR = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
                              n("optA", "optimizer", 660, 0), n("optB", "optimizer", 990, 0, { model: "risk_parity" })],
                edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optA", "returns"), e("returns", "returns", "optB", "returns")] };
  await openWith(page, PAR);
  await page.locator(".pg-strat-add").click();
  await page.locator('.pg-strat-item[data-source="tpl:stress"]').click();
  await expect(page.locator(".pg-note")).toContainText("비중을 내는 끝이 2개라");
  await expect(page.locator(".pg-note")).toContainText("묶지 않았어요");
  const doc = await wip(page);
  const ss = strategiesOf(doc);
  expect(ss, "새 전략 하나만 — 지금 흐름은 묶지 않음").toHaveLength(1);
  expect(ss[0].members.some((m) => ["optA", "optB", "universe", "returns"].includes(m)), "지금 흐름의 노드는 상자 밖").toBe(false);

  // 짝 — 끝이 하나인 흐름(CORE: 비중 계산 하나)은 예전처럼 '전략 1' 로 묶이고 새 전략과 둘
  const other = await page.context().newPage();
  await openWith(other, CORE);
  await other.locator(".pg-strat-add").click();
  await other.locator('.pg-strat-item[data-source="tpl:stress"]').click();
  await expect.poll(async () => strategiesOf(await wip(other)).length).toBe(2);
  const wrapped = strategiesOf(await wip(other)).find((g) => g.members.includes("optimizer"))!;
  expect(wrapped.output).toBe("optimizer");
});
