import { test, expect, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";
import { applyBypassDoc, BYPASS_PORTS, canBypassDoc } from "../src/entities/portfolio-graph/bypass";
import type { GraphDoc, NodeCatalogEntry } from "../src/entities/portfolio-graph/types";

/**
 * 단계 건너뛰기 (2026-11-13 · 설계 `docs/superpowers/specs/2026-11-13-canvas-bypass-compare-design.md` §1 — 화면 재배선 · 서버 0줄)
 *  "이 단계 없이 계산하면?" — 받은 것을 그대로 넘길 수 있는 종류(입력·출력 종류가 같은 넷)만.
 *  · 순수 규칙(브라우저 없이): 넷 각각 · 조건이 안 맞으면 사유 · 연달아 둘 · 하류 여럿 · 버리는 입력 · ★짝★ 건너뛴 것이 없으면 문서 그대로(같은 객체)
 *  · 화면: 계산 요청에 그 노드가 없고 선이 돌려 이어진다(짝: 끄면 다시 있다) · 카드 "건너뜀" · 하류 낡음 · 문서에 표시 · 건너뛸 수 없는 종류엔 단추 없음
 *  · 대안: 복제에서 건너뛰면 칩·비교 표에 행 · 정직성 문장 · 승격이 표시를 옮긴다 · 대비 AA
 *  ★이 기능이 보여 주는 것은 같은 과거에서의 전달 차이다 — 예측력·경제적 가치의 증거가 아니다.★
 */

const P = (name: string, type: string) => ({ name, type });
const CAT = [
  { type: "universe", inputs: [], outputs: [P("universe", "Universe")] },
  { type: "optimizer", inputs: [P("returns", "Returns")], outputs: [P("weights", "Weights")] },
  { type: "neutralize", inputs: [P("weights", "Weights")], outputs: [P("weights", "Weights")] },
  { type: "exposure_overlay", inputs: [P("weights", "Weights"), P("signal", "TimingSignal"), P("regime", "RegimeState")], outputs: [P("weights", "Weights")] },
  { type: "screener", inputs: [P("universe", "Universe")], outputs: [P("universe", "Universe")] },
  { type: "company_views", inputs: [P("returns", "Returns"), P("views", "Views")], outputs: [P("views", "Views")] },
  { type: "timing", inputs: [], outputs: [P("signal", "TimingSignal")] },
  { type: "risk", inputs: [P("weights", "Weights")], outputs: [] },
  { type: "backtest", inputs: [P("weights", "Weights")], outputs: [] },
] as unknown as NodeCatalogEntry[];
const n = (id: string, type: string, bypass = false) => ({ id, type, params: {}, position: { x: 0, y: 0 }, ...(bypass ? { bypass: true } : {}) });
const e = (source: string, sp: string, target: string, tp: string) => ({ id: `${source}.${sp}>${target}.${tp}`, source, source_port: sp, target, target_port: tp });
const docOf = (nodes: ReturnType<typeof n>[], edges: ReturnType<typeof e>[]): GraphDoc =>
  ({ format: "project-alpha.portfolio-graph", version: 1, nodes, edges } as unknown as GraphDoc);
const links = (d: GraphDoc) => d.edges.map((x) => `${x.source}.${x.source_port}>${x.target}.${x.target_port}`).sort();

test("순수 — 건너뛸 수 있는 종류는 넷이고, 통과 포트의 종류가 서버 카탈로그에서 같다", () => {
  expect(Object.keys(BYPASS_PORTS).sort()).toEqual(["company_views", "exposure_overlay", "neutralize", "screener"]);
  for (const [kind, p] of Object.entries(BYPASS_PORTS)) {
    const entry = CAT.find((c) => c.type === kind)!;
    expect(entry.inputs.find((x) => x.name === p.input)!.type, kind).toBe(entry.outputs.find((x) => x.name === p.output)!.type);
  }
});

test("순수 — canBypass: 통과 입력이 이어져 있으면 됨 · 다른 종류는 사유 · 입력이 없으면 사유(넘길 것이 없다)", () => {
  const edges = [e("opt", "weights", "neut", "weights")];
  expect(canBypassDoc(n("neut", "neutralize"), edges, CAT)).toEqual({ ok: true, input: "weights", output: "weights" });
  const no = canBypassDoc(n("opt", "optimizer"), edges, CAT);
  expect(no.ok).toBe(false);
  expect(no.ok ? "" : no.reason).toContain("건너뛸 수 없습니다");
  const lone = canBypassDoc(n("scr", "screener"), [], CAT);
  expect(lone.ok ? "" : lone.reason).toContain("유니버스");
  // 카탈로그의 포트 종류가 달라지면(서버가 바뀌면) 조용히 통과시키지 않는다
  const broken = CAT.map((c) => (c.type === "neutralize" ? { ...c, outputs: [P("weights", "Returns")] } : c)) as unknown as NodeCatalogEntry[];
  expect(canBypassDoc(n("neut", "neutralize"), edges, broken).ok).toBe(false);
});

test("순수 — applyBypass: 노드를 빼고 원천을 하류 모두에 잇는다 · 표시는 서버로 가지 않는다", () => {
  const doc = docOf([n("opt", "optimizer"), n("neut", "neutralize", true), n("risk", "risk"), n("bt", "backtest")],
                    [e("opt", "weights", "neut", "weights"), e("neut", "weights", "risk", "weights"), e("neut", "weights", "bt", "weights")]);
  const r = applyBypassDoc(doc, CAT);
  expect(r.skipped).toEqual(["neut"]);
  expect(r.doc.nodes.map((x) => x.id)).toEqual(["opt", "risk", "bt"]);
  expect(links(r.doc)).toEqual(["opt.weights>bt.weights", "opt.weights>risk.weights"]);
  expect(JSON.stringify(r.doc)).not.toContain("bypass");
  expect(doc.nodes.length, "입력 문서는 바꾸지 않는다").toBe(4);
});

test("순수 — 노출 오버레이: 비중만 통과하고 신호·국면 선은 버린다(그 원천 노드는 남는다) · 연달아 둘도 풀린다", () => {
  const doc = docOf([n("opt", "optimizer"), n("neut", "neutralize", true), n("tim", "timing"), n("ov", "exposure_overlay", true), n("risk", "risk")],
                    [e("opt", "weights", "neut", "weights"), e("neut", "weights", "ov", "weights"), e("tim", "signal", "ov", "signal"), e("ov", "weights", "risk", "weights")]);
  const r = applyBypassDoc(doc, CAT);
  expect(r.skipped.sort()).toEqual(["neut", "ov"]);
  expect(r.doc.nodes.map((x) => x.id)).toEqual(["opt", "tim", "risk"]);
  expect(links(r.doc)).toEqual(["opt.weights>risk.weights"]);
});

test("순수 — ★짝★ 건너뛴 것이 없으면 문서 그대로(같은 객체) · 조건이 안 맞는 표시는 건너뛰지 않고 표시만 뗀다", () => {
  const plain = docOf([n("opt", "optimizer"), n("neut", "neutralize"), n("risk", "risk")],
                      [e("opt", "weights", "neut", "weights"), e("neut", "weights", "risk", "weights")]);
  expect(applyBypassDoc(plain, CAT).doc, "요청 본문이 바이트 그대로여야 한다").toBe(plain);
  expect(applyBypassDoc(plain, CAT).skipped).toEqual([]);
  const inert = docOf([n("scr", "screener", true), n("risk", "risk")], []);       // 앞에 유니버스가 없다 — 이 노드가 종목의 원천
  const r = applyBypassDoc(inert, CAT);
  expect(r.skipped).toEqual([]);
  expect(r.doc.nodes.map((x) => x.id)).toEqual(["scr", "risk"]);
  expect(JSON.stringify(r.doc)).not.toContain("bypass");
});

// ── 화면 ────────────────────────────────────────────────────────────────────

type Doc = { nodes: { id: string; type: string; params: Record<string, unknown>; position: { x: number; y: number }; bypass?: boolean }[];
             edges: { id: string; source: string; source_port: string; target: string; target_port: string }[];
             branches?: { id: string; label: string; root: string; of_root: string; map: Record<string, string> }[] };
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);

/** 기본 캔버스의 최적화 뒤에 '노출 중립화'를 끼운 문서를 불러온다 — 최적화 → 중립화 → (위험 · 과거 성과). */
async function openWithNeutralize(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  const doc = await wip(page);
  const opt = doc.nodes.find((x) => x.id === "optimizer")!;
  const outs = doc.edges.filter((x) => x.source === "optimizer");
  expect(outs.length, "최적화의 하류가 있다").toBeGreaterThan(0);
  const port = outs[0].source_port;
  doc.nodes.push({ id: "neut", type: "neutralize", params: {}, position: { x: opt.position.x + 160, y: opt.position.y + 260 } });
  for (const x of outs) { x.source = "neut"; x.source_port = "weights"; }
  doc.edges.push({ id: "e_opt_neut", source: "optimizer", source_port: port, target: "neut", target_port: "weights" });
  await page.locator(".pg-import-input").setInputFiles({ name: "n.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ format: "project-alpha.portfolio-graph", version: 1, ...doc })) });
  await expect(node(page, "neut")).toBeVisible();
  // 파일 안내 토스트는 사람이 닫을 때까지 떠 있다 — 그 아래에 놓인 노드 도구줄을 가리지 않게 닫는다.
  const fileNote = page.locator(".pg-file-note .pg-toast-x");
  if (await fileNote.count()) await fileNote.click();
  await page.locator(".react-flow__controls-fitview").click();
  return { port, downstream: outs.map((x) => x.target) };
}
type RunReq = { nodes: { id: string; bypass?: boolean }[]; edges: { source: string; source_port: string; target: string; target_port: string }[] };
async function runAndCapture(page: Page) {
  const reqP = page.waitForRequest((r) => r.url().includes("/allocation/graph/run") && r.method() === "POST", { timeout: 120_000 });
  const respP = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const req = (await reqP).postDataJSON() as RunReq;
  const body = (await (await respP).json()) as { nodes: Record<string, { status: string }> };
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return { req, body };
}
const toggle = async (page: Page, id: string) => { await node(page, id).click(); await page.locator(".pg-bypass-toggle").click(); };

test("건너뛰면 계산 요청에 그 노드가 없고 선이 돌려 이어진다 · 카드 '건너뜀' · ★짝★ 끄면 다시 요청에 있다", async ({ page }) => {
  const { port, downstream } = await openWithNeutralize(page);
  await toggle(page, "neut");
  await expect(node(page, "neut")).toHaveClass(/pg-node--bypassed/);
  await expect(node(page, "neut").locator(".pg-node-skip")).toHaveText("건너뜀");
  await expect(page.locator(".pg-bypass-toggle")).toHaveAttribute("aria-pressed", "true");
  expect((await wip(page)).nodes.find((x) => x.id === "neut")!.bypass, "문서에 표시가 남는다").toBe(true);
  const on = await runAndCapture(page);
  expect(on.req.nodes.map((x) => x.id)).not.toContain("neut");
  expect(JSON.stringify(on.req), "표시는 서버로 가지 않는다").not.toContain("bypass");
  for (const t of downstream) expect(on.req.edges.some((x) => x.source === "optimizer" && x.source_port === port && x.target === t), `${t} 가 최적화에 바로 이어진다`).toBe(true);
  expect(on.body.nodes.neut, "서버는 그 노드를 계산하지 않았다").toBeUndefined();
  expect(on.body.nodes[downstream[0]].status, "하류는 그 노드 없이 계산된다").toBe("ok");
  await expect(node(page, "neut").locator(".pg-node-skip")).toHaveText("건너뜀");            // 계산 뒤에도 결과를 지어내지 않는다
  // ★짝★ — 다시 적용하면 요청에 돌아온다
  await toggle(page, "neut");
  await expect(node(page, "neut")).not.toHaveClass(/pg-node--bypassed/);
  expect((await wip(page)).nodes.find((x) => x.id === "neut")!.bypass).toBeUndefined();
  const off = await runAndCapture(page);
  expect(off.req.nodes.map((x) => x.id)).toContain("neut");
  expect(off.req.edges.some((x) => x.source === "neut" && x.target === downstream[0])).toBe(true);
});

test("켜고 끄면 하류가 낡는다 · 예전 결과를 건너뛴 노드의 결과처럼 두지 않는다 · 건너뛸 수 없는 종류에는 단추가 없다 · 표시는 새로 고쳐도 남는다", async ({ page }) => {
  const { downstream } = await openWithNeutralize(page);
  await runAndCapture(page);
  await expect(node(page, "neut").locator(".pg-node-status")).toHaveCount(1);                 // 계산됐다 — 결과가 있다
  await toggle(page, "neut");
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  // 건너뛴 카드는 예전 결과를 제 결과처럼 두지 않는다(상태 줄도 '이전 결과' 안내도 없다) · ★짝★ 하류 카드는 예전 결과라고 말한다
  await expect(node(page, "neut").locator(".pg-node-status, .pg-node-stale")).toHaveCount(0);
  await expect(node(page, downstream[0]).locator(".pg-node-stale")).toHaveCount(1);
  // 오른쪽 창의 결과 탭도 같다 — 예전 결과를 보이지 않고 건너뛴 단계라고 말한다
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await expect(page.locator(".pg-skip-panel-note")).toContainText("건너뛴 단계입니다");
  await expect(page.locator(".pg-result")).toHaveCount(0);
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await expect(page.locator('.pg-passport [data-k="state"] dd')).toHaveText("건너뛴 단계입니다 — 계산하지 않습니다");
  await node(page, "optimizer").click();
  await expect(page.locator(".pg-run-to")).toBeVisible();
  await expect(page.locator(".pg-bypass-toggle"), "최적화는 받은 것을 그대로 넘기는 종류가 아니다").toHaveCount(0);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(node(page, "neut")).toHaveClass(/pg-node--bypassed/);
});

test("‘바뀐 곳만 계산’ — 건너뛴 노드는 대상에서 빠지고, 끝나면 그 노드의 예전 결과가 남지 않는다", async ({ page }) => {
  const { downstream } = await openWithNeutralize(page);
  await runAndCapture(page);
  await toggle(page, "neut");
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  const reqP = page.waitForRequest((r) => r.url().includes("/allocation/graph/run") && r.method() === "POST", { timeout: 120_000 });
  const respP = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-stale-run").click();
  const r = await reqP;
  const req = r.postDataJSON() as RunReq;
  const targets = (new URL(r.url()).searchParams.get("targets") ?? "").split(",").filter(Boolean);      // 대상은 주소의 쿼리로 간다
  expect(req.nodes.map((x) => x.id), "요청 문서에 건너뛴 노드가 없다").not.toContain("neut");
  expect(targets, "계산 대상에도 없다(서버가 모르는 노드를 대상으로 받지 않는다)").not.toContain("neut");
  expect(targets).toContain(downstream[0]);
  const body = (await (await respP).json()) as { nodes: Record<string, { status: string }> };
  expect(body.nodes[downstream[0]].status).toBe("ok");
  // 건너뛴 노드의 예전 결과가 '이전 계산'으로 남으면 영영 낡은 것으로 세어진다 — 남기지 않는다
  await expect(page.locator(".pg-summary--stale")).toHaveCount(0, { timeout: 30_000 });
  await expect(node(page, "neut").locator(".pg-node-skip")).toHaveText("건너뜀");
});

test("불러온 문서의 표시 — 건너뛸 수 없는 종류에 붙어 있으면 빼고 알린다", async ({ page }) => {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  const doc = await wip(page);
  doc.nodes.find((x) => x.id === "optimizer")!.bypass = true;
  await page.locator(".pg-import-input").setInputFiles({ name: "x.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ format: "project-alpha.portfolio-graph", version: 1, ...doc })) });
  await expect(page.locator(".pg-load-problems")).toContainText("건너뛰기 표시를 뺐습니다");
  expect((await wip(page)).nodes.find((x) => x.id === "optimizer")!.bypass).toBeUndefined();
  await expect(node(page, "optimizer")).not.toHaveClass(/pg-node--bypassed/);
});

test("대안에서 건너뛰기: 칩 '적용 → 건너뜀' · 비교 표의 행 · 전달 차이 문장 · 승격이 표시를 원본으로 옮긴다", async ({ page }) => {
  await openWithNeutralize(page);
  await node(page, "neut").click();
  await page.locator(".pg-branch-make").click();
  await expect(page.locator(".pg-branch").first()).toBeVisible();
  await page.waitForTimeout(600);
  const b = (await wip(page)).branches![0];
  const copy = Object.entries(b.map).find(([, o]) => o === "neut")![0];
  await page.locator(".react-flow__controls-fitview").click();          // 복제본은 원본 아래에 놓인다 — 화면 안으로
  await page.waitForTimeout(400);
  await toggle(page, copy);
  await expect(page.locator(".pg-branch-chip").filter({ hasText: "적용 → 건너뜀" })).toHaveCount(1);
  await page.locator('.pg-tab[data-tab="branches"]').click();
  await expect(page.locator('.pg-branch-row--set[data-row="skip:neut"] td')).toHaveText(["적용", "건너뜀"]);
  await expect(page.locator(".pg-branch-skip-note")).toContainText("전달 차이");
  await expect(page.locator(".pg-branch-skip-note")).toContainText("증거가 아닙니다");
  await page.locator(".pg-branch-promote").click();
  const after = await wip(page);
  expect(after.branches ?? []).toEqual([]);
  expect(after.nodes.find((x) => x.id === "neut")!.bypass, "승격이 건너뜀을 원본으로 옮긴다").toBe(true);
  await expect(node(page, "neut")).toHaveClass(/pg-node--bypassed/);
});

for (const theme of ["light", "dark"] as const) {
  test(`대비 AA (${theme}) — 건너뛴 카드`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await openWithNeutralize(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    await toggle(page, "neut");
    await page.locator(".react-flow__pane").click({ position: { x: 8, y: 8 } });
    await page.locator(".react-flow__controls-zoomin").click();
    await page.locator(".react-flow__controls-zoomin").click();
    await expect(node(page, "neut").locator(".pg-node-skip")).toBeVisible();
    const r = await page.evaluate<AuditResult>(contrastAudit('.pg-node[data-node-id="neut"]'));
    expect(r.low, JSON.stringify(r.low)).toEqual([]);
  });
}
