import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  bandHeight, captionLines, EXPORT_MAX_PX, EXPORT_PAD, EXPORT_SKIP, EXPORT_VIEW_STATE, exportNote, exportSize, keepForExport, pickFontFaces, pngFileName,
} from "../src/entities/portfolio-graph/exportImage";

/**
 * CF 3부 R7 · 그림(PNG) 내보내기 (스펙 §8.3 결정 7 · 2026-10-31 결정 셋 + 같은 문서면 같은 그림)
 *  ① 그래프 전체(지금 보는 자리와 무관) · 확대 ≤ 2 선명 · 긴 변 ≤ 4096 · 유령·초안·안내선·단계 띠·도구줄·꺾는 점·손잡이·알약은 거름
 *  ② 글꼴은 그림에 쓴 글자 범위만 넣음 ③ 아래 띠 = 이름·때 + 결과의 성격(연습용 · 예전 결과 · 계산 전 — '실데이터'라고 쓰지 않음)
 *  ④ 같은 문서면 같은 그림 — 찍는 동안만 보통 확대 모양 · 화면 상태(고름·흐림·원인 길·빛)를 뗀 모양, 찍은 뒤 되돌림 · html-to-image 는 누를 때 불러옴
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const NODES = [n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] }), n("returns", "returns", 330, 0),
               n("estimate", "estimate", 660, 0), n("optimizer", "optimizer", 990, 0)];
const EDGES = [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
               e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief")];
const CORE = { ...F, meta: { name: "R7 test" }, nodes: NODES, edges: EDGES };
const EO = "estimate.belief->optimizer.belief";
const T = new Date(2026, 9, 31, 14, 5);
const HEAD = { x: 30, y: 14 };
type B = { x: number; y: number; width: number; height: number };

async function open(page: Page, doc: object, width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  await page.clock.setFixedTime(T);
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("r7_seeded")) return;
      sessionStorage.setItem("r7_seeded", "1");
      for (const k of ["alpha_pg_panels", "alpha_pg_view", "alpha_pg_left_tab"]) localStorage.removeItem(k);
      localStorage.setItem("alpha_pg_welcomed", "1");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(350);
}
const card = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const pngBtn = (page: Page) => page.locator(".pg-export-png");
/** 단추를 눌러 받은 파일 — 이름과 바이트. */
async function take(page: Page, click: () => Promise<void> = () => pngBtn(page).click()) {
  const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 30_000 }), click()]);
  const buf = readFileSync((await dl.path())!);
  return { name: dl.suggestedFilename(), buf, w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}
/** 카드·묶음·갈래 틀의 경계(캔버스 좌표) — 감싸개 자리(translate)와 레이아웃 크기. 확대·이동과 무관. */
const domBounds = (page: Page): Promise<B> => page.evaluate(() => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const el of document.querySelectorAll<HTMLElement>(".react-flow__viewport .react-flow__node")) {
    if (!el.offsetWidth || !el.offsetHeight) continue;
    const t = new DOMMatrixReadOnly(getComputedStyle(el).transform);
    x0 = Math.min(x0, t.e); y0 = Math.min(y0, t.f);
    x1 = Math.max(x1, t.e + el.offsetWidth); y1 = Math.max(y1, t.f + el.offsetHeight);
  }
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
});
async function compute(page: Page) {
  await page.locator(".pg-run").click();
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 90_000 });
  await expect(page.locator(".pg-node--stale")).toHaveCount(0);
}

// ── 규칙(브라우저 없이) ─────────────────────────────────────────────────────

test("R7 · 크기 — 작은 그래프는 2배 선명 · 큰 그래프는 긴 변 4096 상한 · 여백 포함", () => {
  const small = exportSize({ x: 0, y: 0, width: 600, height: 300 });
  expect(small.scale).toBe(2);
  expect(small.w).toBe((600 + 2 * EXPORT_PAD) * 2);
  expect(small.h).toBe((300 + 2 * EXPORT_PAD) * 2);
  expect(small.x).toBe(EXPORT_PAD * 2);                               // 경계 왼쪽 위가 여백만큼 안으로
  const moved = exportSize({ x: -500, y: 120, width: 600, height: 300 });
  expect(moved.x).toBe((EXPORT_PAD + 500) * 2);
  expect(moved.y).toBe((EXPORT_PAD - 120) * 2);
  const big = exportSize({ x: 0, y: 0, width: 9000, height: 1200 });
  expect(Math.max(big.w, big.h)).toBe(EXPORT_MAX_PX);                 // 짝: 큰 그래프는 상한에서 멈춘다
  expect(big.scale).toBeLessThan(1);
  expect(Math.abs(big.w / big.h - (9000 + 2 * EXPORT_PAD) / (1200 + 2 * EXPORT_PAD))).toBeLessThan(0.01);
  expect(bandHeight(2, 2)).toBeGreaterThan(bandHeight(1, 2));          // 줄이 늘면 띠도
  expect(bandHeight(1, 0.3)).toBe(bandHeight(1, 1));                  // 작게 줄인 그림도 띠 글자는 읽을 수 있게(1배 아래로 줄이지 않음)
});

test("R7 · 파일 이름 — JSON 과 같은 바탕 + .portfolio-graph.png (짝: 이름 없음)", () => {
  expect(pngFileName("R7 시험", T)).toBe("R7-시험.portfolio-graph.png");
  expect(pngFileName(undefined, new Date("2026-10-31T12:00:00Z"))).toBe("portfolio-2026-10-31.portfolio-graph.png");
});

test("R7 · 띠 문장 — 이름·때는 늘 · 연습용·예전 결과·계산 전은 있을 때만 · '실데이터' 말 없음", () => {
  const base = { name: "R7 시험", now: T };
  expect(captionLines({ ...base, computed: true, practice: false, stale: false })).toEqual(["‘R7 시험’ · 2026-10-31 14:05 내보냄"]);
  expect(captionLines({ ...base, name: "", computed: true, practice: false, stale: false })[0]).toBe("‘이름 없는 설계’ · 2026-10-31 14:05 내보냄");
  const all = captionLines({ ...base, computed: true, practice: true, stale: true });
  expect(all).toEqual(["‘R7 시험’ · 2026-10-31 14:05 내보냄", "연습용(합성) 데이터로 계산한 결과예요 — 실제 시세가 아니에요", "바꾼 뒤 다시 계산하지 않은 예전 결과가 섞여 있어요"]);
  expect(captionLines({ ...base, computed: false, practice: false, stale: false })[1]).toBe("계산 전이에요 — 카드에 결과가 없어요");
  for (const l of [...all, ...captionLines({ ...base, computed: false, practice: false, stale: false })]) expect(l).not.toContain("실데이터");
  expect(exportNote(all)).toContain("연습용(합성)");
  expect(exportNote(captionLines({ ...base, computed: true, practice: false, stale: false }))).toBe("그림(PNG)을 받았어요.");
});

test("R7 · 글꼴 고르기 — 쓴 글자가 든 범위만 (짝: 안 쓴 범위는 빠지고 범위 없는 글꼴은 늘)", () => {
  const faces = [{ unicodeRange: "U+0-FF", id: "latin" }, { unicodeRange: "U+AC00-AC47, U+B000", id: "ko1" },
                 { unicodeRange: "U+4E00-4E2F", id: "cjk" }, { unicodeRange: "U+B1??", id: "wild" }, { unicodeRange: "", id: "all" }];
  expect(pickFontFaces(faces, "가A").map((f) => f.id)).toEqual(["latin", "ko1", "all"]);
  expect(pickFontFaces(faces, "\u{B123}").map((f) => f.id)).toEqual(["wild", "all"]);     // U+B1?? = B100–B1FF
  expect(pickFontFaces(faces, "").map((f) => f.id)).toEqual(["all"]);
});

test("R7 · 거를 것 — 겹침 클래스는 빼고 카드·선은 남긴다 · 화면 상태 목록은 고름·흐림·원인 길·빛", () => {
  for (const c of EXPORT_SKIP) expect(keepForExport(`x ${c} y`), c).toBe(false);
  for (const c of ["react-flow__node", "react-flow__edge", "pg-node", "pg-group", "pg-wire-brief"]) expect(keepForExport(c), c).toBe(true);
  for (const c of ["pg-ghosts", "pg-drafts", "pg-guides", "pg-lanes", "pg-edge-tb", "pg-waypoint", "pg-wire-type"]) expect(EXPORT_SKIP).toContain(c);
  for (const c of ["selected", "pg-node--selected", "pg-wire--picked", "pg-dim", "pg-edge--faint", "pg-on-path", "pg-on-cause", "pg-group--drop"]) expect(EXPORT_VIEW_STATE).toContain(c);
});

// ── 화면(실제 서버) ─────────────────────────────────────────────────────────

test("R7 · 받은 파일 — 이름 · PNG 머리 · 크기 = 경계 + 띠 (짝: 노드를 멀리 두면 넓어진다)", async ({ page }) => {
  await open(page, CORE);
  const b = await domBounds(page);
  const got = await take(page);
  expect(got.name).toBe("R7-test.portfolio-graph.png");
  expect(got.buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe(true);
  const s = exportSize(b);
  expect(Math.abs(got.w - s.w)).toBeLessThanOrEqual(2);
  expect(Math.abs(got.h - (s.h + bandHeight(2, s.scale)))).toBeLessThanOrEqual(2);  // 계산 전 — 띠 두 줄(이름·때 + 계산 전)
  const far = await (async () => {
    const p2 = await page.context().newPage();
    await open(p2, { ...CORE, nodes: NODES.map((x) => (x.id === "optimizer" ? { ...x, position: { x: 2600, y: 0 } } : x)) });
    const r = await take(p2);
    await p2.close();
    return r;
  })();
  expect(far.w).toBeGreaterThan(got.w);
});

test("R7 · 같은 문서면 같은 그림 — 유령·고른 노드·고른 선(도구줄)·확대·이동을 바꿔도 같은 바이트 (짝: 노드를 옮기면 다르다)", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page, CORE);
  await expect(page.locator(".pg-ghost").first()).toBeVisible();          // 유령이 정말 떠 있어야 거름을 잰다
  const a = await take(page);
  const again = await take(page);
  expect(again.buf.equals(a.buf), "그대로 두 번").toBe(true);
  await card(page, "returns").click({ position: HEAD });
  await expect(card(page, "returns")).toHaveClass(/pg-node--selected/);
  expect((await take(page)).buf.equals(a.buf), "고른 노드").toBe(true);
  await page.locator('.react-flow__edge[data-id="returns.returns->estimate.returns"]').dispatchEvent("click");
  await expect(page.locator(".pg-edge-tb")).toBeVisible();
  expect((await take(page)).buf.equals(a.buf), "고른 선 · 도구줄").toBe(true);
  await page.keyboard.press("Control+k");
  await page.locator('.pg-cmd-item[data-cmd="ghosts"]').click();
  await expect(page.locator(".pg-ghost")).toHaveCount(0);
  for (let i = 0; i < 6; i++) await page.locator(".react-flow__controls-zoomin").click();
  await page.mouse.move(700, 500); await page.mouse.down(); await page.mouse.move(520, 380, { steps: 5 }); await page.mouse.up();
  expect((await take(page)).buf.equals(a.buf), "유령 끔 · 확대 · 이동").toBe(true);
  // 짝 — 문서가 바뀌면 그림도 바뀐다
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
  await page.keyboard.press("Escape");                                     // 고른 선의 도구줄이 카드 머리를 덮지 않게
  await expect(page.locator(".pg-edge-tb")).toHaveCount(0);
  const wipY = () => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}").nodes.find((x: { id: string }) => x.id === "estimate").position.y);
  const y0 = await wipY();
  const box = (await card(page, "estimate").boundingBox())!;
  await page.mouse.move(box.x + HEAD.x, box.y + HEAD.y); await page.mouse.down();
  await page.mouse.move(box.x + HEAD.x, box.y + HEAD.y + 120, { steps: 6 }); await page.mouse.up();
  await expect.poll(wipY).toBeGreaterThan(y0 + 50);                        // 정말 옮겨졌다
  expect((await take(page)).buf.equals(a.buf), "노드를 옮김").toBe(false);
});

test("R7 · 띠에 글자가 그려진다 (짝: 위쪽 여백 줄은 한 색)", async ({ page }) => {
  await open(page, CORE);
  const got = await take(page);
  const s = exportSize(await domBounds(page));
  const band = bandHeight(2, s.scale);
  const r = await page.evaluate(async ({ b64, band, pad }) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d")!;
    g.drawImage(img, 0, 0);
    const differs = (y0: number, y1: number) => {
      const d = g.getImageData(0, y0, c.width, y1 - y0).data;
      const [r0, g0, b0] = [d[0], d[1], d[2]];
      let k = 0;
      for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - r0) + Math.abs(d[i + 1] - g0) + Math.abs(d[i + 2] - b0) > 60) k++;
      return k;
    };
    return { band: differs(img.height - band + 4, img.height - 2), top: differs(0, Math.max(2, pad - 6)) };
  }, { b64: got.buf.toString("base64"), band, pad: Math.floor(EXPORT_PAD * s.scale) });
  expect(r.band).toBeGreaterThan(200);
  expect(r.top).toBe(0);
});

/** 그림 안 카드 사이 틈(캔버스 x 250–320 — 종목 고르기 오른쪽 끝 240 과 수익률 불러오기 왼쪽 330 사이)에서 배경과 다른 픽셀 수 — 거기엔 선만 지난다. */
async function gapInk(page: Page, buf: Buffer, b: B) {
  const s = exportSize(b);
  return page.evaluate(async ({ b64, x0, x1, h }) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d")!;
    g.drawImage(img, 0, 0);
    const bg = g.getImageData(2, 2, 1, 1).data;
    const d = g.getImageData(x0, 0, x1 - x0, h).data;
    let k = 0;
    for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - bg[0]) + Math.abs(d[i + 1] - bg[1]) + Math.abs(d[i + 2] - bg[2]) > 60) k++;
    return k;
  }, { b64: buf.toString("base64"), x0: Math.round((250 - b.x + EXPORT_PAD) * s.scale), x1: Math.round((320 - b.x + EXPORT_PAD) * s.scale), h: s.h });
}

test("R7 · 선도 그림에 들어간다 — 카드 사이 틈에 선 픽셀 (짝: 선이 없는 문서는 그 틈이 비어 있다)", async ({ page }) => {
  await open(page, CORE);
  const withWires = await gapInk(page, (await take(page)).buf, await domBounds(page));
  expect(withWires, "선이 빠졌다(html-to-image 1.11.13 에서 본 결함)").toBeGreaterThan(50);
  const p2 = await page.context().newPage();
  await open(p2, { ...CORE, edges: [] });
  const bare = await gapInk(p2, (await take(p2)).buf, await domBounds(p2));
  await p2.close();
  expect(bare).toBe(0);
});

test("R7 · 받은 뒤 알림이 띠의 성격을 말한다 — 계산 전 → 연습용 → 예전 결과", async ({ page }) => {
  test.setTimeout(150_000);
  await open(page, CORE);
  await take(page);
  await expect(page.locator(".pg-note")).toContainText("계산 전이에요");
  await compute(page);
  await take(page);
  await expect(page.locator(".pg-note")).toContainText("연습용(합성) 데이터로 계산한 결과예요");
  await expect(page.locator(".pg-note")).not.toContainText("예전 결과");
  await page.locator(`.react-flow__edge[data-id="${EO}"]`).dispatchEvent("click");
  await page.keyboard.press("Delete");
  await expect(card(page, "optimizer")).toHaveClass(/pg-node--stale/);
  await take(page);
  await expect(page.locator(".pg-note")).toContainText("예전 결과가 섞여 있어요");
});

test("R7 · html-to-image 는 누를 때 받는다 — 누르기 전엔 새 JS 없음 · 두 번째엔 다시 받지 않음", async ({ page }) => {
  const js: string[] = [];
  page.on("request", (r) => { if (r.resourceType() === "script") js.push(r.url()); });
  await open(page, CORE);
  await page.waitForTimeout(1_500);
  const idle = js.length;
  await page.waitForTimeout(1_000);
  expect(js.length).toBe(idle);
  await take(page);
  expect(js.length).toBeGreaterThan(idle);
  const after = js.length;
  await take(page);
  expect(js.length).toBe(after);
});

test("R7 · 찍은 뒤 화면이 그대로 돌아온다 — 확대 단계 · 고른 노드 (짝: 찍다 실패해도 돌아오고 까닭을 말한다)", async ({ page }) => {
  await open(page, CORE);
  for (let i = 0; i < 12 && (await page.locator(".pg-canvas").getAttribute("data-zoom")) !== "near"; i++) {
    await page.locator(".react-flow__controls-zoomin").click();
    await page.waitForTimeout(100);
  }
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
  const zoomBefore = await page.locator(".pg-canvas").getAttribute("data-zoom");
  await card(page, "returns").click({ position: HEAD });
  await take(page);
  await expect(page.locator(".pg-canvas")).toHaveAttribute("data-zoom", zoomBefore!);
  await expect(page.locator(".pg-canvas.pg-exporting")).toHaveCount(0);
  await expect(card(page, "returns")).toHaveClass(/pg-node--selected/);
  await expect(page.locator('.react-flow__node[data-id="returns"]')).toHaveClass(/selected/);
  // 짝 — 그림 도구(JS 조각)를 받지 못하게 막으면: 파일 없이 까닭 · 화면은 그대로
  await page.reload();
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(600);
  await card(page, "returns").click({ position: HEAD });
  const zoom2 = await page.locator(".pg-canvas").getAttribute("data-zoom");
  await page.route("**/_next/static/chunks/**", (r) => r.abort());
  await pngBtn(page).click();
  await expect(page.locator(".pg-note")).toContainText("그림을 만들지 못했어요");
  await expect(page.locator(".pg-canvas")).toHaveAttribute("data-zoom", zoom2!);
  await expect(page.locator(".pg-canvas.pg-exporting")).toHaveCount(0);
  await expect(card(page, "returns")).toHaveClass(/pg-node--selected/);
});

test("R7 · 글꼴은 쓴 범위만 받는다 — 내보내는 동안 받은 글꼴 파일 수 < 전체 조각의 절반", async ({ page }) => {
  await open(page, CORE);
  const total = await page.evaluate(() => {
    let k = 0;
    for (const sh of Array.from(document.styleSheets)) {
      try { for (const r of Array.from(sh.cssRules)) if (r instanceof CSSFontFaceRule && /Pretendard/.test(r.style.getPropertyValue("font-family"))) k++; } catch { /* */ }
    }
    return k;
  });
  expect(total).toBeGreaterThan(20);                                        // 동적 서브셋이 정말 여럿이어야 이 시험이 무언가를 잰다
  const fonts: string[] = [];
  page.on("request", (r) => { if (/\.woff2(\?|$)/.test(r.url())) fonts.push(r.url()); });
  await take(page);
  expect(fonts.length).toBeGreaterThan(0);
  expect(fonts.length).toBeLessThan(total / 2);
});

test("R7 · 좁은 화면 '더 보기' · 명령 찾기에서도 같은 그림 (짝: 노드가 없으면 단추가 꺼짐)", async ({ page }) => {
  await open(page, CORE, 1200);
  await page.locator(".pg-more").click();
  const fromMore = await take(page, () => page.locator(".pg-more-export-png").click());
  expect(fromMore.name).toBe("R7-test.portfolio-graph.png");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.keyboard.press("Control+k");
  const fromCmd = await take(page, () => page.locator('.pg-cmd-item[data-cmd="export-png"]').click());
  expect(fromCmd.name).toBe("R7-test.portfolio-graph.png");
  const p2 = await page.context().newPage();
  await p2.setViewportSize({ width: 1440, height: 900 });
  await p2.addInitScript(() => { try { localStorage.setItem("alpha_pg_welcomed", "1"); sessionStorage.setItem("alpha_pg_wip", JSON.stringify({ format: "project-alpha.portfolio-graph", version: 1, nodes: [], edges: [] })); } catch { /* */ } });
  await p2.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(p2.locator(".pg-export-png")).toBeDisabled({ timeout: 30_000 });
  await p2.close();
});
