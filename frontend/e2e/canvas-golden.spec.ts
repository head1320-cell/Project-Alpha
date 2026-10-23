import * as fs from "node:fs";
import * as path from "node:path";
import { test, expect, type Page } from "@playwright/test";

/**
 * CF 3부 E1 · 캔버스 골든 — ★`PortfolioCanvas`·`store` 를 나누기(E2·E3) 전후로 동작이 같다는 것을 못 박는다★ (스펙 §8.1)
 *  ① 문서(`canvas-doc.json`): 고정 문서 → 정해진 조작(복제 · 목록에서 추가 · 잇기 · 칸 값 · 정렬 · 묶기 · 갈래 · 복사/붙여넣기 · 경유점 ·
 *     말로 초안 받아들이기 · 자동 정리)마다 작업 중 문서 · ★되돌리기 사다리★(한 번씩 되돌린 문서 전부 — 어떤 조작이 몇 걸음인지) · 내보낸 파일
 *  ② 화면(`canvas-classes.json`): 상태마다 `.pg-root` 아래 요소 모양 집합(태그 + 클래스 + data-·aria-·role 속성 이름)
 *  ③ 명령(`canvas-commands.json`): 명령 찾기 항목(고른 것에 따라) · 우클릭 메뉴(노드·빈 곳) · 단축키 한 장 · 보기·정렬 메뉴
 * 노드·묶음·갈래 id 는 시각으로 만든다 → 시계를 고정한다(`clock.setFixedTime` — 타이머는 그대로 돈다).
 * 다시 얼리기: UPDATE_CANVAS_GOLDEN=1 — ★의도한 변경만★. 나누기(E2·E3)에서는 다시 얼리지 않는다.
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const CORE = { ...F, nodes: [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 320, 0),
                             n("estimate", "estimate", 640, 0), n("optimizer", "optimizer", 960, 0)],
               edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
                       e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")] };
const EMPTY = { ...F, nodes: [], edges: [] };
const DRAFT = {
  summary: "과거로 돌려 보기를 붙이고 5년 기준으로 바꿔요",
  add: [{ ref: "b", id: "backtest", kind: "backtest", label: "과거로 돌려 보기" }],
  connect: [{ id: "returns.returns->backtest.returns", source: "returns", source_port: "returns", target: "backtest", target_port: "returns" }],
  set: [{ node: "backtest", field: "cost_bps", label: "거래비용", value: 30, display: "0.3%", quote: "0.3%", read: "preset" }],
  empty: [],
};
const DRAFT_OK = { available: true, source: "claude", model: "m", understood: true, cannot: null, draft: DRAFT, rejected: [],
                   cached: false, usage: { input_tokens: 1, output_tokens: 1, cost_usd: 0, cost_note: null } };
const NOW = new Date("2026-10-23T00:00:00Z");
const HEAD = { x: 30, y: 14 };
const W_UR = "universe.universe->returns.universe";

type Pt = { x: number; y: number };
type Doc = { nodes: { id: string; type: string; position: Pt }[]; edges: { id: string; waypoints?: Pt[] }[]; [k: string]: unknown };

// ── 골든 ─────────────────────────────────────────────────────────────────────
const GOLD = (name: string) => path.join(__dirname, "golden", `canvas-${name}.json`);
function golden(name: string, got: Record<string, unknown>) {
  const file = GOLD(name);
  if (process.env.UPDATE_CANVAS_GOLDEN === "1") {
    fs.writeFileSync(file, JSON.stringify(got, null, 1) + "\n");
    return;
  }
  // 짝 — 골든이 없거나 비면 통과가 아니라 실패다(항상-통과 금지).
  expect(fs.existsSync(file), `${file} 이 없다 — UPDATE_CANVAS_GOLDEN=1 로 얼린다`).toBe(true);
  const want = JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
  expect(Object.keys(want).length, "골든이 비었다").toBeGreaterThan(0);
  for (const k of Object.keys(want)) expect(got[k], `${name} · ${k}`).toEqual(want[k]);
  expect(Object.keys(got).sort(), `${name} · 상태 목록`).toEqual(Object.keys(want).sort());
}

// ── 열기 ─────────────────────────────────────────────────────────────────────
async function signIn(page: Page) {
  await page.addInitScript(() => { try { localStorage.setItem("project-alpha.auth-token", "e2e.fake.token"); } catch { /* */ } });
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: {
    principal: { username: "alice", role: "analyst" }, must_change_password: false, password_changed_at: null } }));
}

async function openWith(page: Page, doc: object, { login = true } = {}) {
  await page.clock.setFixedTime(NOW);
  if (login) await signIn(page);
  await page.route("**/api/v1/assist/canvas/draft", (r) => r.fulfill({ json: DRAFT_OK }));
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("golden_seeded")) return;
      sessionStorage.setItem("golden_seeded", "1");
      for (const k of ["alpha_pg_panels", "alpha_pg_view", "alpha_pg_left_tab", "alpha_pg_blocks"]) localStorage.removeItem(k);
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-root")).toBeVisible({ timeout: 30_000 });
  if ((doc as { nodes: unknown[] }).nodes.length) await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(500);
  await fitAll(page);
}

const fitAll = async (page: Page) => {
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(350);
};
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
/** 위치는 정수로 — 측정 크기의 소수점 흔들림까지 동작으로 보지 않는다(같은 코드 세 번 실행으로 확인). */
const norm = (d: Doc): Doc => JSON.parse(JSON.stringify(d, (k, v) => (typeof v === "number" && (k === "x" || k === "y") ? Math.round(v) : v)));
const blank = (page: Page) => page.locator(".react-flow__pane").click({ position: { x: 360, y: 24 } });

async function pick(page: Page, ids: string[]) {
  await blank(page);
  await node(page, ids[0]).click({ position: HEAD });
  for (const id of ids.slice(1)) await node(page, id).click({ position: HEAD, modifiers: ["Control"] });
  await expect(page.locator(".pg-selbar-n")).toHaveText(`${ids.length}개 골랐어요`);
}
/** 선 위 한 점(길이의 t)의 화면 좌표. */
const onWire = (page: Page, id: string, t = 0.5) => page.locator(`.react-flow__edge[data-id="${id}"] path.react-flow__edge-path`).evaluate((el, k) => {
  const g = el as SVGPathElement;
  const q = g.getPointAtLength(g.getTotalLength() * k);
  const m = g.getScreenCTM()!;
  return { x: q.x * m.a + m.e, y: q.y * m.d + m.f };
}, t);
const centre = async (page: Page, sel: string) => {
  const b = (await page.locator(sel).boundingBox())!;
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
};
/** 아래 안내 토스트를 닫는다 — 열린 메뉴·막대 단추를 가릴 수 있다(8초 뒤 닫히기를 기다리지 않는다). */
async function dismissNote(page: Page) {
  const x = page.locator(".pg-note-x");
  if (await x.isVisible()) await x.click();
}
async function command(page: Page, id: string) {
  await page.keyboard.press("Control+k");
  await page.locator(`.pg-cmd-item[data-cmd="${id}"]`).click();
  await expect(page.locator(".pg-cmd")).not.toBeVisible();
}

test.use({ viewport: { width: 1440, height: 900 } });

test("문서 골든 — 조작마다 작업 중 문서 · 되돌리기 사다리 · 내보낸 파일이 얼린 것과 같다", async ({ page }) => {
  test.setTimeout(180_000);
  await openWith(page, CORE);
  const steps: Record<string, Doc> = {};
  const snap = async (k: string) => { await page.waitForTimeout(250); steps[k] = norm(await wip(page)); await dismissNote(page); };
  await snap("01-load");

  // 경유점 — 선을 두 번 누르기(캔버스가 단순할 때 — 뒤의 붙여넣기가 이 선을 덮는다)
  await blank(page);
  const at = await onWire(page, W_UR, 0.5);
  await page.mouse.dblclick(at.x, at.y);
  await expect.poll(async () => ((await wip(page)).edges.find((x) => x.id === W_UR)?.waypoints ?? []).length).toBe(1);
  await snap("01b-waypoint");

  // 복제(Ctrl+D)
  await node(page, "optimizer").click({ position: HEAD });
  await page.keyboard.press("Control+d");
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(5);
  const dup = (await wip(page)).nodes.find((x) => !CORE.nodes.some((c) => c.id === x.id))!.id;
  await snap("02-duplicate");

  // 왼쪽 목록에서 추가 → 보이는 가운데(아무것도 고르지 않은 채 — 고른 노드가 있으면 거기에 바로 잇는다)
  await blank(page);
  await page.locator('.pg-left-tab[data-tab="add"]').click();
  const before = new Set((await wip(page)).nodes.map((x) => x.id));
  await page.locator('.pg-palette-item[data-kind="risk"]').click();
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(before.size + 1);
  const risk = (await wip(page)).nodes.find((x) => !before.has(x.id))!.id;
  await snap("03-add");

  // 자동 정리 — 가운데에 놓인 새 노드가 다른 카드 밑에 깔려 있다(명령 찾기)
  await blank(page);
  await command(page, "layout");
  await snap("03b-layout");

  // 잇기 — 비중 계산 '비중' → 새 노드 '비중'
  await fitAll(page);
  const from = await centre(page, '.react-flow__node[data-id="optimizer"] .react-flow__handle.source[data-handleid="weights"]');
  const to = await centre(page, `.react-flow__node[data-id="${risk}"] .react-flow__handle.target[data-handleid="weights"]`);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, { steps: 6 });
  await page.mouse.move(to.x, to.y, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => (await wip(page)).edges.some((x) => x.id === `optimizer.weights->${risk}.weights`)).toBe(true);
  await snap("04-connect");

  // 칸 값 — 설정 탭 프리셋
  await blank(page);
  await node(page, "returns").click({ position: HEAD });
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="lookback_days"] .pg-chip', { hasText: "5년" }).click();
  await snap("05-param");

  // 정렬 — 둘째 줄의 둘(새 노드 · 복제한 비중 계산)을 골라 위 맞추기(뒤에서 누를 첫 줄 카드 머리를 가리지 않는다)
  await fitAll(page);
  await pick(page, [risk, dup]);
  await page.locator(".pg-align-open").click();
  await page.locator('.pg-align-menu [data-align="top"]').click();
  await snap("06-align");

  // 묶기(Ctrl+G)
  await page.keyboard.press("Control+g");
  await snap("07-group");

  // 갈래 — 명령 찾기
  await fitAll(page);
  await blank(page);
  await node(page, "estimate").click({ position: HEAD });
  await command(page, "branch");
  await snap("08-branch");

  // 복사 · 붙여넣기
  await fitAll(page);
  await blank(page);
  await node(page, "universe").click({ position: HEAD });
  await page.keyboard.press("Control+c");
  await page.keyboard.press("Control+v");
  await snap("09-paste");

  // 말로 초안 받아들이기(가로챈 답)
  await page.locator('.pg-left-tab[data-tab="say"]').click();
  await page.locator(".pg-say-text").fill("과거로 돌려 보기를 붙이고 거래비용은 0.3%로 해 줘");
  await page.locator(".pg-say-text").press("Enter");
  await page.locator(".pg-say-accept").click();
  await expect.poll(async () => (await wip(page)).nodes.some((x) => x.id === "backtest")).toBe(true);
  await snap("11-draft");

  // 자동 정리 — 명령 찾기
  await blank(page);
  await command(page, "layout");
  await snap("12-layout");

  // ★되돌리기 사다리★ — 한 번씩 되돌려 문서가 더 바뀌지 않을 때까지. 다시하기로 끝까지 가면 마지막 문서와 같다(짝).
  await blank(page);
  const ladder: Doc[] = [];
  let last = JSON.stringify(steps["12-layout"]);
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Control+z");
    await page.waitForTimeout(200);
    const d = norm(await wip(page));
    if (JSON.stringify(d) === last) break;
    ladder.push(d);
    last = JSON.stringify(d);
  }
  expect(ladder.length, "되돌리기가 하나도 먹지 않았다").toBeGreaterThan(5);
  for (let i = 0; i < ladder.length; i++) {
    await page.keyboard.press("Control+Shift+z");
    await page.waitForTimeout(150);
  }
  expect(norm(await wip(page)), "다시하기로 끝까지 가면 마지막 문서").toEqual(steps["12-layout"]);

  // 내보낸 파일
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const file = norm(JSON.parse(fs.readFileSync((await (await dl).path())!, "utf-8")));

  golden("doc", { steps, ladder, export: file, ids: { dup, risk } });
});

/** 요소 모양 집합 — 태그 + 정렬한 클래스 + data-·aria-·role 속성 이름. 값(글·좌표)은 보지 않는다. */
const shape = (page: Page) => page.locator(".pg-root").evaluate((root) => {
  const sig = new Set<string>();
  for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
    const cls = Array.from(el.classList).sort().join(".");
    const attrs = Array.from(el.attributes).map((a) => a.name)
      .filter((k) => k.startsWith("data-") || k.startsWith("aria-") || k === "role").sort().join(",");
    sig.add(`${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""}${attrs ? `[${attrs}]` : ""}`);
  }
  return Array.from(sig).sort();
});

test("화면 골든 — 상태마다 요소 모양(태그·클래스·data/aria/role 이름) 집합이 얼린 것과 같다", async ({ page: first }) => {
  test.setTimeout(180_000);
  const got: Record<string, string[]> = {};
  let page = first;
  const take = async (k: string) => {
    await page.waitForTimeout(300);
    got[k] = await shape(page);
    // 짝 — 빈 집합·덜 그린 화면이 통과하지 않게 상태마다 하한.
    expect(got[k].length, `${k}: 잰 요소 모양이 너무 적다`).toBeGreaterThan(60);
  };

  await openWith(page, EMPTY, { login: false });
  await take("empty");

  // 새 탭(작업 중 문서는 탭마다) — 로그인한 사람이 네 노드 흐름을 연다.
  page = await first.context().newPage();
  await openWith(page, CORE);
  await take("loaded");

  for (const k of ["proc", "add", "say"]) {
    await page.locator(`.pg-left-tab[data-tab="${k}"]`).click();
    await take(`left:${k}`);
  }

  await node(page, "optimizer").click({ position: HEAD });
  await take("node");
  for (const k of ["story", "settings", "detail"]) {
    await page.locator(`.pg-tab[data-tab="${k}"]`).click();
    await take(`node:${k}`);
  }

  await blank(page);
  const w = await onWire(page, W_UR, 0.5);
  await page.mouse.click(w.x, w.y);
  await expect(page.locator(`.react-flow__edge[data-id="${W_UR}"]`)).toHaveClass(/selected/);
  await expect(page.locator('.pg-tab[data-tab="wire"]')).toHaveClass(/on/);
  await take("edge");

  await blank(page);
  await page.locator(".pg-view-open").click();
  await take("menu:view");
  await page.keyboard.press("Escape");

  await node(page, "optimizer").click({ position: HEAD, button: "right" });
  await expect(page.locator(".pg-ctx")).toBeVisible();
  await take("menu:node");
  await page.keyboard.press("Escape");

  await page.locator(".react-flow__pane").click({ position: { x: 700, y: 640 }, button: "right" });
  await expect(page.locator(".pg-ctx")).toBeVisible();
  await take("menu:pane");
  await page.keyboard.press("Escape");

  await pick(page, ["universe", "returns", "estimate"]);
  await take("multi");
  await page.locator(".pg-align-open").click();
  await take("multi:align");
  await page.keyboard.press("Escape");

  await blank(page);
  await page.keyboard.press("Control+k");
  await expect(page.locator(".pg-cmd")).toBeVisible();
  await take("dialog:cmd");
  await page.keyboard.press("Escape");

  await page.keyboard.press("?");
  await expect(page.locator(".pg-keys")).toBeVisible();
  await take("dialog:keys");
  await page.keyboard.press("Escape");

  golden("classes", got);
});

test("명령 골든 — 명령 찾기 · 우클릭 메뉴 · 단축키 · 보기·정렬 메뉴의 항목과 순서가 얼린 것과 같다", async ({ page }) => {
  test.setTimeout(180_000);
  await openWith(page, CORE);
  const got: Record<string, string[]> = {};
  // 명령 찾기는 앞 40개만 보인다 — 빈 찾기 + 묶음 이름으로 찾은 목록을 함께 얼려 뒤쪽 명령(전략·서랍·템플릿·비교·AI)까지 본다.
  const cmds = async (k: string, queries = ["", "전략", "서랍", "템플릿", "비교", "AI", "보기"]) => {
    await page.keyboard.press("Control+k");
    await expect(page.locator(".pg-cmd")).toBeVisible();
    for (const q of queries) {
      await page.locator(".pg-cmd-search input").fill(q);
      await page.waitForTimeout(100);
      got[`cmd:${k}${q ? `?${q}` : ""}`] = await page.locator(".pg-cmd-item").evaluateAll((els) => els.map((el) =>
        [el.getAttribute("data-cmd"), ...Array.from(el.children).map((c) => (c.textContent ?? "").trim())].join(" | ")));
    }
    expect(got[`cmd:${k}`].length, `cmd:${k} 항목이 너무 적다`).toBeGreaterThan(15);
    await page.keyboard.press("Escape");
    await expect(page.locator(".pg-cmd")).not.toBeVisible();
  };
  const items = (sel: string) => page.locator(sel).evaluateAll((els) => els.map((el) =>
    [el.getAttribute("data-action") ?? el.getAttribute("data-view") ?? el.getAttribute("data-wire") ?? el.getAttribute("data-align")
       ?? el.getAttribute("data-drawer") ?? "", (el.textContent ?? "").trim(), (el as HTMLButtonElement).disabled ? "disabled" : ""].join(" | ")));

  await blank(page);
  await cmds("none");
  await node(page, "optimizer").click({ position: HEAD });
  await cmds("node");
  await blank(page);
  const w = await onWire(page, W_UR, 0.5);
  await page.mouse.click(w.x, w.y);
  await expect(page.locator(`.react-flow__edge[data-id="${W_UR}"]`)).toHaveClass(/selected/);
  await cmds("edge");
  await pick(page, ["universe", "returns", "estimate"]);
  await cmds("multi");
  await page.locator(".pg-align-open").click();
  got["menu:align"] = await items(".pg-align-menu [role=menuitem]");
  await page.keyboard.press("Escape");

  await blank(page);
  await node(page, "optimizer").click({ position: HEAD, button: "right" });
  got["ctx:node"] = await items(".pg-ctx .pg-ctx-item");
  await page.keyboard.press("Escape");
  await page.locator(".react-flow__pane").click({ position: { x: 700, y: 640 }, button: "right" });
  got["ctx:pane"] = await items(".pg-ctx .pg-ctx-item");
  await page.keyboard.press("Escape");

  await page.locator(".pg-view-open").click();
  got["menu:view"] = await items(".pg-view-menu button");
  await page.keyboard.press("Escape");

  await page.keyboard.press("?");
  got["keys"] = await page.locator(".pg-keys-list > div").evaluateAll((els) => els.map((el) =>
    `${el.querySelector("dt")?.textContent?.trim()} | ${el.querySelector("dd")?.textContent?.trim()}`));
  await page.keyboard.press("Escape");

  for (const k of ["ctx:node", "ctx:pane", "menu:view", "menu:align", "keys"]) {
    expect(got[k].length, `${k} 항목이 비었다`).toBeGreaterThan(1);
  }
  golden("commands", got);
});
