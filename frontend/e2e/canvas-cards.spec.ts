import { test, expect, type Page } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// BS2 — 카드 크기·배치 간격 (설계 docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md §BS2)
// ─────────────────────────────────────────────────────────────────────────────
// 실측에서 찾은 것(확대 1, 두 전략 + 합치기): 선 요약 라벨 17개 중 13개가 카드를 덮었다(가로 틈 66px < 라벨 44~94px) ·
// 줄 간격 170 은 가장 큰 보통 카드(124)보다 46 넓고, 포트가 많은 카드(합치기 220)는 오히려 넘쳤다.
// 거는 것: 카드 폭 = 배치가 쓰는 폭(한 자리) · 카드끼리 겹치지 않는다 · 선 라벨이 카드에 가리지 않는다 ·
//         카드 안 내용이 넘치지 않는다 · 세로 간격은 내용 높이 + 틈(짝: 170 줄보다 촘촘하다)
// ═══════════════════════════════════════════════════════════════════════════════

type Doc = { nodes: { id: string; type: string; position: { x: number; y: number } }[] };
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;

async function mapAtZoomOne(page: Page, arrange = true) {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.locator(".pg-strat-add").click();
  await page.locator('.pg-strat-item[data-source="tpl:stress"]').click();
  if (arrange) await page.locator('button[aria-label="자동 정리"]').click();
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary")).toContainText("완료", { timeout: 30_000 });
  for (let i = 0; i < 14; i++) {
    const z = await page.locator(".pg-canvas").evaluate((el) => Number(getComputedStyle(el).getPropertyValue("--pg-z")));
    if (Math.abs(z - 1) < 0.06) break;
    await page.locator(z < 1 ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(150);
  }
  await page.waitForTimeout(300);
}

type Box = { id: string; kind: string; l: number; t: number; r: number; b: number };

// 자동 정리 뒤와 ★정리 전(시작 그래프·템플릿이 적어 둔 자리)★ 둘 다 — 템플릿이 손으로 적은 x(열 틈 46px)는 정리 전에
// 선 요약이 옆 카드를 덮었다(실측 7개 중 3개). 템플릿도 같은 격자(`COL`)를 쓴다.
for (const arrange of [true, false]) test(`카드(BS2${arrange ? "" : " · 정리 전"}): 카드 폭 = 배치 폭 · 카드끼리 겹치지 않는다 · 선 라벨이 카드에 가리지 않는다 · 내용이 넘치지 않는다`, async ({ page }) => {
  await mapAtZoomOne(page, arrange);
  const m = await page.evaluate(() => {
    const z = Number(getComputedStyle(document.querySelector(".pg-canvas")!).getPropertyValue("--pg-z"));
    const cards = [...document.querySelectorAll<HTMLElement>(".react-flow__node .pg-node")].map((el) => {
      const r = el.getBoundingClientRect();
      return { id: el.closest(".react-flow__node")!.getAttribute("data-id")!, kind: el.getAttribute("data-kind") ?? "",
               l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width / z,
               over: el.scrollHeight - el.clientHeight };
    });
    const briefs = [...document.querySelectorAll<HTMLElement>(".pg-wire-brief")]
      .filter((el) => getComputedStyle(el).display !== "none")
      .map((el) => { const r = el.getBoundingClientRect(); return { text: el.textContent ?? "", l: r.left, t: r.top, r: r.right, b: r.bottom }; });
    return { z, cards, briefs, nodeW: Number(getComputedStyle(document.querySelector(".pg-canvas")!).getPropertyValue("--pg-node-w")) };
  });
  const inter = (a: Omit<Box, "id" | "kind">, b: Omit<Box, "id" | "kind">) =>
    Math.max(0, Math.min(a.r, b.r) - Math.max(a.l, b.l)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.t, b.t));
  expect(m.nodeW, "배치가 쓰는 카드 폭이 캔버스에 선언돼 있다").toBeGreaterThan(0);
  for (const c of m.cards.filter((c) => c.kind !== "portfolio_combine")) {
    expect(Math.round(c.w), `${c.id} 폭 = 배치 폭`).toBe(m.nodeW);
  }
  for (let i = 0; i < m.cards.length; i++) {
    for (let j = i + 1; j < m.cards.length; j++) {
      expect(inter(m.cards[i], m.cards[j]), `${m.cards[i].id} · ${m.cards[j].id} 겹침`).toBe(0);
    }
  }
  expect(m.briefs.length).toBeGreaterThan(5);
  for (const b of m.briefs) {
    const hit = m.cards.find((c) => inter(b, c) > 4);
    expect(hit?.id ?? null, `선 라벨 '${b.text}' 이 카드를 덮는다`).toBeNull();
  }
  // 선 라벨끼리도 겹치지 않는다 — 한 포트에서 여러 선이 나가면 요약은 첫 선에만(같은 글이 한 자리에 쌓였다).
  for (let i = 0; i < m.briefs.length; i++) {
    for (let j = i + 1; j < m.briefs.length; j++) {
      expect(inter(m.briefs[i], m.briefs[j]), `선 라벨 '${m.briefs[i].text}' · '${m.briefs[j].text}' 겹침`).toBeLessThanOrEqual(4);
    }
  }
  // 라벨 자리 — 원천 카드 바로 오른쪽 틈, 원천 포트 높이(선 가운데가 아니다). 왼쪽 가장 가까운 카드의 세로 범위 안에 있다.
  for (const b of m.briefs) {
    const cy = (b.t + b.b) / 2;
    const left = m.cards.filter((c) => c.r <= b.l + 1 && b.l - c.r < 80 * m.z).sort((x, y) => y.r - x.r);
    const src = left.find((c) => cy >= c.t && cy <= c.b);
    expect(src?.id ?? null, `선 라벨 '${b.text}' 이 원천 카드 옆 틈에 있다`).not.toBeNull();
  }
  for (const c of m.cards) expect(c.over, `${c.id} 내용 넘침`).toBeLessThanOrEqual(1);
});

test("카드(BS2) 짝: 세로 간격은 내용 높이 + 틈 — 예전 170 줄보다 촘촘하고, 포트가 많은 카드는 그만큼 띄운다", async ({ page }) => {
  await mapAtZoomOne(page);
  const doc = await wip(page);
  // 같은 열(x 같음)에서 위아래로 이웃한 카드 사이의 흐름 좌표 간격.
  const cols = new Map<number, { id: string; y: number; type: string }[]>();
  for (const n of doc.nodes) cols.set(n.position.x, [...(cols.get(n.position.x) ?? []), { id: n.id, y: n.position.y, type: n.type }]);
  const gaps: number[] = [];
  for (const col of cols.values()) {
    col.sort((a, b) => a.y - b.y);
    for (let i = 1; i < col.length; i++) gaps.push(col[i].y - col[i - 1].y);
  }
  expect(gaps.length).toBeGreaterThan(2);
  expect(Math.min(...gaps), "가장 촘촘한 세로 간격").toBeLessThan(170);
});

test("한 노드 도구줄(BS2): 다른 카드를 덮지 않는다 — 시작 그래프와 두 전략 지도의 모든 노드에서 · 덮지 않으면 예전 자리(위 가운데)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  let atDefault = 0, moved = 0, free = 0;
  const sweep = async (tag: string) => {
    const ids = await page.locator(".react-flow__node:has(.pg-node)").evaluateAll((els) => els.map((e) => e.getAttribute("data-id")!));
    for (const id of ids) {
      const card = page.locator(`.react-flow__node[data-id="${id}"] .pg-node`);
      if (!(await card.isVisible())) continue;
      await card.click({ position: { x: 20, y: 10 } });
      await expect(page.locator(".react-flow__node-toolbar", { has: page.locator(".pg-run-to") })).toBeVisible();
      const m = await page.evaluate((sel) => {
        type R = { l: number; t: number; r: number; b: number };
        const b = document.querySelector(".react-flow__node-toolbar:has(.pg-run-to)")!.getBoundingClientRect();
        const me = document.querySelector(`.react-flow__node[data-id="${sel}"]`)!.getBoundingClientRect();
        const cards: R[] = [...document.querySelectorAll<HTMLElement>(".react-flow__node")]
          .filter((n) => n.getAttribute("data-id") !== sel && n.querySelector(".pg-node") && n.offsetParent !== null)
          .map((n) => { const r = n.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; });
        const cover = (x: R) => cards.reduce((s, c) => s + Math.max(0, Math.min(x.r, c.r) - Math.max(x.l, c.l)) * Math.max(0, Math.min(x.b, c.b) - Math.max(x.t, c.t)), 0);
        // 후보 여섯(위/아래 × 가운데/시작/끝, offset 8) — 도구줄 크기는 실제 DOM 크기.
        const w = b.width, h = b.height, cands: R[] = [];
        for (const top of [me.top - 8 - h, me.bottom + 8])
          for (const left of [(me.left + me.right) / 2 - w / 2, me.left, me.right - w]) cands.push({ l: left, t: top, r: left + w, b: top + h });
        const cv = document.querySelector(".react-flow")!.getBoundingClientRect();
        const inView = (x: R) => x.t >= cv.top && x.b <= cv.bottom;
        const freeExists = cands.some((x) => cover(x) <= 4 && inView(x));
        const mine = cover({ l: b.left, t: b.top, r: b.right, b: b.bottom });
        return { mine, freeExists, least: Math.min(...cands.map(cover)),
                 def: b.bottom <= me.top + 1 && Math.abs((b.left + b.right) / 2 - (me.left + me.right) / 2) < 2 };
      }, id);
      // 덮지 않는 자리가 있으면 그 자리 · 없으면(아주 멀리 본 촘촘한 지도) 가장 덜 덮는 자리.
      if (m.freeExists) expect(m.mine, `${tag} · ${id} 도구줄이 카드를 덮는다(빈 자리가 있는데)`).toBeLessThanOrEqual(4);
      else expect(m.mine, `${tag} · ${id} 가장 덜 덮는 자리가 아니다`).toBeLessThanOrEqual(m.least + 4);
      if (m.freeExists) free++;
      if (m.def) atDefault++; else moved++;
    }
  };
  await sweep("시작 그래프");
  await page.locator(".pg-strat-add").click();
  await page.locator('.pg-strat-item[data-source="tpl:stress"]').click();
  await page.keyboard.press("Escape");
  await sweep("두 전략");
  // 짝 — 덮을 것이 없으면 예전 자리 그대로(늘 옮기는 구현이 아니다) · 덮을 것이 있으면 옮긴다(늘 그 자리인 구현이 아니다).
  expect(free, "빈 자리가 있는 노드").toBeGreaterThan(5);
  expect(atDefault).toBeGreaterThan(0);
  expect(moved).toBeGreaterThan(0);
});
