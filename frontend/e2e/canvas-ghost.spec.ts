import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, minimapOn, type AuditResult } from "./helpers";

/**
 * CF6 · 유령 노드 — 서버 규칙 추천(`/validate` procedure.next · by_gate)을 캔버스 위에(스펙 §CF6, 사용자 결정 2026-10-22)
 *  · 유령 = 반투명 카드(붙이면 놓일 자리·크기) + 점선 추천 선 + "규칙 추천" 칩 + [붙이기]·[닫기] · 서로 다른 추천만, 최대 3
 *  · ★문서가 아니다★ — 저장·계산·`.react-flow__node`·미니맵에 없다 · 진짜 카드와 겹치지 않고, 카드를 누르는 것을 가로채지 않는다
 *  · 아래 '다음 한 걸음' 바와 하나 — next 유령을 닫으면 바도, 바 [다음에]면 next 유령도 · 바에 올리면 그 유령이 또렷 · 붙이는 자리는 어느 쪽이든 유령 자리
 *  · '보기' 메뉴 "추천 보기"(기본 켬)로 끄고 켠다 — 이 브라우저에 남는다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const U = n("universe", "universe", 0, 0, { tickers: ["005930", "000660"] });
const R = n("returns", "returns", 320, 0);
const O = n("optimizer", "optimizer", 640, 0, { model: "risk_parity" });
/** 종목 → 수익률 → 비중: next = 기대 수익 추정(비중 계산 앞) · 비용·표본외 관문 = 과거로 돌려 보기(같은 추천 둘). */
const CHAIN = { ...F, nodes: [U, R, O], edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "optimizer", "returns")] };
/** 종목·수익률이 끊김: next = 잇기만. */
const CUT = { ...F, nodes: [U, R], edges: [] as ReturnType<typeof e>[] };
/** 종목 · 비중만: next = 수익률(비중 계산으로) · 데이터 관문 = 수익률(종목에서) — 같은 자리를 노리는 서로 다른 추천 둘. */
const GAP = { ...F, nodes: [U, O], edges: [] as ReturnType<typeof e>[] };

type Sug = { action: string; kind: string | null; text: string; attach: { source: string; source_port: string; target: string; target_port: string }[] };
type Proc = { next: Sug | null; by_gate: Record<string, Sug | null> };
type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[]; edges: { source: string; source_port: string; target: string; target_port: string }[] };
const sig = (s: Sug) => JSON.stringify([s.action, s.kind, s.attach.map((a) => `${a.source}.${a.source_port}>${a.target}.${a.target_port}`).sort()]);
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const ghost = (page: Page, kind: string) => page.locator(`.pg-ghost[data-kind="${kind}"]`);

/** 문서를 심고 열어 첫 검증 응답(절차)을 돌려준다. */
async function openWith(page: Page, doc: object, keepView = false): Promise<Proc> {
  await page.addInitScript(([d, keep]) => {
    try {
      if (sessionStorage.getItem("cf6_seeded")) return;
      sessionStorage.setItem("cf6_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      if (!keep) localStorage.removeItem("alpha_pg_view");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, [doc, keepView] as const);
  const validated = page.waitForResponse((r) => r.url().includes("/allocation/graph/validate") && r.request().method() === "POST");
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  const body = await (await validated).json();
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
  await page.waitForTimeout(300);
  return body.procedure as Proc;
}
const overlaps = (a: { x: number; y: number; width: number; height: number }, b: { x: number; y: number; width: number; height: number }) =>
  a.x < b.x + b.width - 1 && a.x + a.width > b.x + 1 && a.y < b.y + b.height - 1 && a.y + a.height > b.y + 1;

test.use({ viewport: { width: 1440, height: 900 } });

test("유령 = 서버의 서로 다른 추천(next 먼저) · '규칙 추천' 칩 · next 유령의 글 = 바의 글 · 관문 유령은 여는 관문을 말한다", async ({ page }) => {
  const proc = await openWith(page, CHAIN);
  const distinct = new Set([proc.next, ...Object.values(proc.by_gate)].filter((s): s is Sug => !!s).map(sig));
  expect(distinct.size, "서버 응답에서 센 서로 다른 추천").toBe(2);
  await expect(page.locator(".pg-ghost")).toHaveCount(distinct.size);
  const nx = page.locator('.pg-ghost[data-next="true"]');
  await expect(nx).toHaveCount(1);
  await expect(nx).toHaveAttribute("data-kind", proc.next!.kind!);
  await expect(nx.locator(".pg-ghost-text")).toHaveText(proc.next!.text);
  await expect(page.locator(".pg-next-text")).toHaveText(proc.next!.text);
  for (const g of await page.locator(".pg-ghost").all()) {
    await expect(g).toHaveAttribute("data-source", "rule");
    await expect(g.locator(".pg-ghost-chip")).toHaveText("규칙 추천");
  }
  await expect(ghost(page, "backtest")).toHaveAttribute("data-gates", "cost oos");
  await expect(ghost(page, "backtest").locator(".pg-ghost-gates")).toContainText("관문");
  await expect(nx.locator(".pg-ghost-gates")).toHaveCount(0);                      // 짝 — 여는 관문이 없으면 말하지 않는다
});

test("유령은 문서가 아니다 — 저장된 문서·.react-flow__node·미니맵에 없다 · 진짜 카드와 겹치지 않는다", async ({ page }) => {
  await openWith(page, CHAIN);
  await expect(page.locator(".pg-ghost")).toHaveCount(2);
  expect((await wip(page)).nodes.map((x) => x.id).sort()).toEqual(["optimizer", "returns", "universe"]);
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await minimapOn(page, true);
  await expect(page.locator(".react-flow__minimap-node")).toHaveCount(3);
  const cards = await Promise.all((await page.locator(".react-flow__node").all()).map((x) => x.boundingBox()));
  for (const g of await page.locator(".pg-ghost").all()) {
    const b = (await g.boundingBox())!;
    for (const c of cards) expect(overlaps(b, c!), `유령 ${await g.getAttribute("data-kind")} 이 카드와 겹친다`).toBe(false);
  }
});

test("유령 [붙이기] → 진짜 노드가 유령이 보인 자리에 · 추천 선 모두 · 되돌리기 한 번에 원래", async ({ page }) => {
  await openWith(page, CHAIN);
  const g = ghost(page, "estimate");
  const at = { x: Number(await g.getAttribute("data-x")), y: Number(await g.getAttribute("data-y")) };
  await g.locator(".pg-ghost-add").click();
  await expect(page.locator(".pg-note")).toContainText("기대 수익 추정");
  const doc = await wip(page);
  const made = doc.nodes.find((x) => x.type === "estimate")!;
  expect(made.position).toEqual(at);
  expect(doc.edges.some((x) => x.source === made.id && x.source_port === "belief" && x.target === "optimizer" && x.target_port === "belief")).toBe(true);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await wip(page)).nodes.length).toBe(3);
});

test("앞선 유령에 밀린 유령도 [붙이기]하면 보인 자리 그대로 — 두 유령은 겹치지 않는다", async ({ page }) => {
  await openWith(page, GAP);
  const rs = page.locator('.pg-ghost[data-kind="returns"]');
  await expect(rs).toHaveCount(2);
  const [a, b] = [(await rs.nth(0).boundingBox())!, (await rs.nth(1).boundingBox())!];
  expect(overlaps(a, b), "두 유령이 겹친다").toBe(false);
  const pushed = page.locator('.pg-ghost[data-kind="returns"][data-next="false"]');
  const at = { x: Number(await pushed.getAttribute("data-x")), y: Number(await pushed.getAttribute("data-y")) };
  expect(at.y, "밀린 유령").toBeGreaterThan(0);
  await pushed.locator(".pg-ghost-add").click();
  const made = (await wip(page)).nodes.find((x) => x.type === "returns")!;
  expect(made.position).toEqual(at);
});

test("바 [붙이기]도 유령 자리에 — 붙을 노드 앞 열에 카드가 있어도 그 위에 겹쳐 놓지 않는다", async ({ page }) => {
  await openWith(page, CHAIN);
  const g = ghost(page, "estimate");
  const at = { x: Number(await g.getAttribute("data-x")), y: Number(await g.getAttribute("data-y")) };
  expect(at.x).toBe(R.position.x);                                                  // 붙을 노드(비중 계산) 앞 열 = 수익률 열
  await page.locator(".pg-next-go").click();
  const made = (await wip(page)).nodes.find((x) => x.type === "estimate")!;
  expect(made.position).toEqual(at);
  expect(made.position, "수익률 카드 위에 겹쳐 놓았다").not.toEqual(R.position);  // 짝 — 예전 자리(같은 높이)는 수익률 위였다
  const rb = (await page.locator('.react-flow__node[data-id="returns"]').boundingBox())!;
  const nb = (await page.locator(`.react-flow__node[data-id="${made.id}"]`).boundingBox())!;
  expect(overlaps(rb, nb)).toBe(false);
});

test("next 유령 [닫기] → 바도 사라짐 · 관문 유령은 남음(짝) · 바 [다음에] → next 유령도 사라짐", async ({ page, context }) => {
  await openWith(page, CHAIN);
  await ghost(page, "estimate").locator(".pg-ghost-x").click();
  await expect(ghost(page, "estimate")).toHaveCount(0);
  await expect(page.locator(".pg-next")).toHaveCount(0);
  await expect(ghost(page, "backtest")).toHaveCount(1);
  const other = await context.newPage();
  await openWith(other, CHAIN);
  await expect(ghost(other, "estimate")).toHaveCount(1);
  await other.locator(".pg-next-later").click();
  await expect(ghost(other, "estimate")).toHaveCount(0);
  await expect(ghost(other, "backtest")).toHaveCount(1);
});

test("잇기 추천 = 카드 없는 점선 + [잇기] → 선이 생긴다", async ({ page }) => {
  const proc = await openWith(page, CUT);
  expect(proc.next!.action).toBe("connect");
  const g = page.locator('.pg-ghost[data-action="connect"]');
  await expect(g).toHaveCount(1);
  await expect(page.locator('.pg-ghost-wire[data-action="connect"]')).toHaveCount(1);
  await expect(g.locator(".pg-ghost-add")).toHaveText(/잇기/);
  await g.locator(".pg-ghost-add").click();
  await expect.poll(async () => (await wip(page)).edges.some((x) => x.source === "universe" && x.target === "returns")).toBe(true);
});

test("바에 올리면 next 유령이 또렷해진다 — 짝: 올리지 않으면 아니다", async ({ page }) => {
  await openWith(page, CHAIN);
  const nx = page.locator('.pg-ghost[data-next="true"]');
  await expect(nx).not.toHaveClass(/pg-ghost--hot/);
  await page.locator(".pg-next").hover();
  await expect(nx).toHaveClass(/pg-ghost--hot/);
  await expect(ghost(page, "backtest")).not.toHaveClass(/pg-ghost--hot/);
});

test("유령 선은 누름을 가로채지 않는다 — 선이 지나는 자리의 진짜 카드가 눌린다", async ({ page }) => {
  await openWith(page, CHAIN);
  // 수익률 → 과거로 돌려 보기 추천 선은 비중 계산 카드를 가로지른다.
  const hit = await page.locator('.pg-ghost-wire[data-to="backtest"][data-from="returns"] path').first().evaluate((path: SVGPathElement) => {
    const card = document.querySelector('.react-flow__node[data-id="optimizer"]')!.getBoundingClientRect();
    const m = path.getScreenCTM()!;
    for (let l = 0; l < path.getTotalLength(); l += 2) {
      const p = path.getPointAtLength(l);
      const x = p.x * m.a + m.e, y = p.y * m.d + m.f;
      if (x > card.left + 8 && x < card.right - 8 && y > card.top + 8 && y < card.bottom - 8) return { x, y };
    }
    return null;
  });
  expect(hit, "추천 선이 비중 계산 카드를 지나지 않는다(검사가 공허하다)").not.toBeNull();
  expect(await page.evaluate(({ x, y }) => !!document.elementFromPoint(x, y)?.closest('.react-flow__node[data-id="optimizer"]'), hit!)).toBe(true);
});

test("'보기' 메뉴 추천 보기 — 끄면 유령 0 · 새로고침해도 꺼짐 · 다시 켜면 보인다(짝)", async ({ page }) => {
  await openWith(page, CHAIN);
  await expect(page.locator(".pg-ghost")).toHaveCount(2);
  const toggle = async () => { await page.locator(".pg-view-open").click(); await page.locator('.pg-view-menu [data-view="ghosts"]').click(); };
  await page.locator(".pg-view-open").click();
  await expect(page.locator('.pg-view-menu [data-view="ghosts"]')).toHaveAttribute("aria-checked", "true");   // 기본 켬
  await page.keyboard.press("Escape");
  await toggle();
  await expect(page.locator(".pg-ghost")).toHaveCount(0);
  await expect(page.locator(".pg-next")).toBeVisible();                                                       // 바는 글 길로 남는다
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(800);
  await expect(page.locator(".pg-ghost")).toHaveCount(0);
  await toggle();
  await expect(page.locator(".pg-ghost")).toHaveCount(2);
});

test("멀리(확대 단계 far)에선 유령도 이름·칩·단추만 — 글은 숨기고 이름은 화면 11px 이상 · 짝: 보통에선 글이 보인다", async ({ page }) => {
  await openWith(page, CHAIN);
  const g = ghost(page, "estimate");
  await expect(g.locator(".pg-ghost-text")).toBeVisible();                                   // 짝 — 보통 확대
  for (let i = 0; i < 10 && (await page.locator(".pg-canvas").getAttribute("data-zoom")) !== "far"; i++) {
    await page.locator(".react-flow__controls-zoomout").click();
    await page.waitForTimeout(150);
  }
  await expect(page.locator(".pg-canvas")).toHaveAttribute("data-zoom", "far");
  await expect(g.locator(".pg-ghost-text")).toBeHidden();
  await expect(g.locator(".pg-ghost-name")).toBeVisible();
  await expect(g.locator(".pg-ghost-add")).toBeVisible();
  const screenPx = await g.locator(".pg-ghost-name").evaluate((el) =>
    parseFloat(getComputedStyle(el).fontSize) * Number(getComputedStyle(el.closest(".pg-canvas")!).getPropertyValue("--pg-z")));
  expect(screenPx).toBeGreaterThanOrEqual(10.9);
});

for (const scheme of ["light", "dark"] as const) {
  test(`유령 대비(${scheme}) AA`, async ({ page }) => {
    await openWith(page, CHAIN);
    if (scheme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    await expect(page.locator(".pg-ghost")).toHaveCount(2);
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-ghosts"));     // 유령 층 전체(둘 다)
    expect(a.checked).toBeGreaterThanOrEqual(8);
    expect(a.low, scheme).toEqual([]);
  });
}

test.describe("좁은 화면(390)", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("유령이 있어도 확대 단추는 진짜로 눌린다", async ({ page }) => {
    await openWith(page, CHAIN);
    await expect(page.locator(".pg-ghost").first()).toBeAttached();
    const before = await page.locator(".react-flow__viewport").evaluate((el) => getComputedStyle(el).transform);
    await page.locator(".react-flow__controls-zoomin").click();
    await expect.poll(() => page.locator(".react-flow__viewport").evaluate((el) => getComputedStyle(el).transform)).not.toBe(before);
  });
});
