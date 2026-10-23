import { test, expect, type Page } from "@playwright/test";

/**
 * CF3b2 · 전달 점검 화면 — 선마다 무엇이 건너갔고 무엇이 빠지거나 바뀌었는지(서버 `edges`)를 선과 선 판이 말한다.
 * 거는 것(짝으로 항상-표시·항상-침묵을 배제):
 *  · 표시 칩은 문제가 있는 선에만, 받는 쪽 끝에 하나 — `[]`(점검했고 찾지 못함)·`null`(점검하지 않음)에는 없다
 *  · 단계 우선순위 lost > changed > structural > unused · 개수 = 서버 문제 수 · 이름은 "전달 점검 n건: 첫 글"
 *  · 실제 계산: 충격 점검에서 수익률 → 기대 수익 추정은 '쓰지 않음', 비중 계산 → 시나리오·민감도는 칩 없음
 *    (K3 부터 민감도는 받은 비중의 방식으로 다시 풀어 그 선이 깨끗하다 — 예전엔 '바뀜')
 *  · 민감도(K3): 기대 수익을 쓰지 않는 방식(위험 똑같이)이면 0 칸 히트맵 대신 서버 문장 · 짝: 수익 대비 위험 최적은 히트맵
 *  · 칩은 카드·선 요약과 겹치지 않는다(중간·가까이) · 멀리에서는 글자 없는 점
 *  · 칩을 누르면 선 판: 관계 문장·건너간 것(키)·문제 글 = 서버 · `[]` 이면 점검한 것을 말하고 · `null` 이면 사유
 *  · 계산 전 관계 문장은 요약 괄호가 없고, 계산 뒤엔 요약이 들어간다
 *  · 여기까지 계산 뒤에도 다시 계산하지 않은 받는 쪽의 기록은 남는다 · 받는 쪽이 예전 결과면 칩을 숨긴다(짝: 다른 칩은 남는다)
 *  · 고른 방식 대신 다른 비중을 냈으면 카드에 "고른 방식 대신함" 칩 — 가정 수에서는 뺀다
 */

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
// 충격 점검 템플릿과 같은 꼴(열 간격 320 = 카드 240 + 틈 80) — 기대 수익 추정은 위 줄로 비켜 둔다.
const STRESS = {
  ...F,
  nodes: [n("universe", "universe", 0, 140, { tickers: ["005930", "000660", "035420"] }), n("returns", "returns", 320, 140),
          n("estimate", "estimate", 640, -420), n("optimizer", "optimizer", 960, 140, { model: "risk_parity" }),
          n("scenario", "scenario_stress", 1280, -420), n("corr", "corr_stress", 1280, 140), n("sens", "sensitivity", 1280, 700)],
  edges: [e("universe", "universe", "returns", "universe"), e("returns", "returns", "estimate", "returns"),
          e("returns", "returns", "optimizer", "returns"), e("estimate", "belief", "optimizer", "belief"),
          e("optimizer", "weights", "scenario", "weights"), e("returns", "returns", "corr", "returns"),
          e("optimizer", "weights", "corr", "weights"), e("returns", "returns", "sens", "returns"), e("optimizer", "weights", "sens", "weights")],
};
const SENS = "optimizer.weights->sens.weights";
const SCEN = "optimizer.weights->scenario.weights";
const EST = "returns.returns->estimate.returns";
const OPT_RET = "returns.returns->optimizer.returns";

type Issue = { level: string; code: string; text: string; fix?: string };
type Rec = { facts: { key: string; text: string }[] | null; checks: string[]; issues: Issue[] | null; issues_reason: string | null };
type Body = { edges: Record<string, Rec>; relations: Record<string, { text: string; brief: string | null }>;
              nodes: Record<string, { explain?: { trust?: { state: string; text: string; kind?: string }[] }; view?: Record<string, unknown> }> };

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("cf3b2_seeded")) return;
      sessionStorage.setItem("cf3b2_seeded", "1");
      localStorage.removeItem("alpha_pg_panels");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}
/** 계산 응답을 고친다 — `fn` 이 없으면 그대로. 여기까지 계산(`?targets=`)도 잡도록 경로로 고른다. */
async function patchRun(page: Page, fn?: (b: Body) => void) {
  await page.unroute((u) => u.pathname.endsWith("/allocation/graph/run"));
  await page.route((u) => u.pathname.endsWith("/allocation/graph/run"), async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as Body;
    fn?.(body);
    await route.fulfill({ response: res, json: body });
  });
}
async function run(page: Page): Promise<Body> {
  const resp = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as Body;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}
const flag = (page: Page, id: string) => page.locator(`.pg-wire-flag[data-edge-id="${id}"]`);
const row = (page: Page, r: string) => page.locator(`.pg-wire-row[data-row="${r}"]`);
async function zoomTo(page: Page, level: "far" | "mid" | "near") {
  const canvas = page.locator(".pg-canvas");
  for (let i = 0; i < 16; i++) {
    const z = await canvas.getAttribute("data-zoom");
    if (z === level) return;
    const wantIn = level === "near" || (level === "mid" && z === "far");
    await page.locator(wantIn ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
  }
  await expect(canvas).toHaveAttribute("data-zoom", level);
}
const RANK: Record<string, number> = { lost: 0, changed: 1, structural: 2, unused: 3 };

test("실제 계산: 문제가 있는 선에만 칩 하나 · 단계·개수·이름 = 서버 — 짝: `[]` 인 선(비중 계산 → 시나리오)엔 없다", async ({ page }) => {
  await openWith(page, STRESS);
  await patchRun(page);
  const body = await run(page);
  expect(body.edges[SENS].issues).toEqual([]);                                   // K3 — 같은 방식으로 다시 푼다
  expect(body.edges[EST].issues?.map((i) => i.level)).toEqual(["unused"]);
  expect(body.edges[SCEN].issues).toEqual([]);

  const withIssues = Object.entries(body.edges).filter(([, r]) => r.issues && r.issues.length);
  await expect(page.locator(".pg-wire-flag")).toHaveCount(withIssues.length);
  for (const [id, r] of withIssues) {
    const top = [...r.issues!].sort((a, b) => RANK[a.level] - RANK[b.level])[0];
    await expect(flag(page, id)).toHaveCount(1);
    await expect(flag(page, id)).toHaveAttribute("data-level", top.level);
    await expect(flag(page, id)).toHaveAttribute("data-count", String(r.issues!.length));
    await expect(flag(page, id)).toHaveAttribute("aria-label", `전달 점검 ${r.issues!.length}건: ${r.issues![0].text}`);
  }
  await expect(flag(page, SCEN)).toHaveCount(0);
  await expect(flag(page, SENS)).toHaveCount(0);
  await expect(flag(page, OPT_RET)).toHaveCount(0);
});

test("주입: lost·unused 둘이면 lost 하나로 · `[]`·`null` 엔 칩 없음 (상수·전부 표시 배제)", async ({ page }) => {
  await openWith(page, STRESS);
  await patchRun(page, (b) => {
    b.edges[OPT_RET].issues = [{ level: "unused", code: "u", text: "쓰지 않아요" }, { level: "lost", code: "l", text: "빠졌어요" }];
    b.edges[SENS].issues = [];
    b.edges[EST].issues = null; b.edges[EST].issues_reason = "이 자리는 아직 점검 규칙이 없어요.";
  });
  await run(page);
  await expect(flag(page, OPT_RET)).toHaveAttribute("data-level", "lost");
  await expect(flag(page, OPT_RET)).toHaveAttribute("data-count", "2");
  await expect(flag(page, SENS)).toHaveCount(0);
  await expect(flag(page, EST)).toHaveCount(0);
});

test("자리: 칩은 받는 쪽 끝에 있고 카드·선 요약과 겹치지 않는다(중간·가까이) · 멀리에서는 글자 없는 점", async ({ page }) => {
  await openWith(page, STRESS);
  await patchRun(page, (b) => { for (const r of Object.values(b.edges)) r.issues = [{ level: "changed", code: "x", text: "바뀌었어요" }]; });
  await run(page);
  await expect(page.locator(".pg-wire-flag")).toHaveCount(STRESS.edges.length);
  type Box = { x: number; y: number; width: number; height: number };
  const overlap = (a: Box, b: Box) => a.x < b.x + b.width - 0.5 && b.x < a.x + a.width - 0.5 && a.y < b.y + b.height - 0.5 && b.y < a.y + a.height - 0.5;
  for (const lv of ["mid", "near"] as const) {
    await zoomTo(page, lv);
    await page.locator(".react-flow__controls-fitview").click();      // 맞춤은 멀리로 줄일 수 있다 — 잰 단계로 다시
    await zoomTo(page, lv);
    await page.waitForTimeout(300);
    const boxes = await page.evaluate(() => {
      const b = (el: Element) => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; };
      return {
        flags: [...document.querySelectorAll(".pg-wire-flag")].map((el) => ({ id: el.getAttribute("data-edge-id")!, box: b(el) })),
        cards: [...document.querySelectorAll(".react-flow__node .pg-node")].map(b),
        briefs: [...document.querySelectorAll(".pg-wire-brief")].map(b),
        handles: Object.fromEntries([...document.querySelectorAll(".react-flow__node")].map((nd) => [nd.getAttribute("data-id"), b(nd)])),
      };
    });
    expect(boxes.briefs.length, "선 요약이 있어야 겹침을 잴 수 있다").toBeGreaterThan(0);
    for (const f of boxes.flags) {
      for (const c of boxes.cards) expect(overlap(f.box, c), `${lv} ${f.id} 카드`).toBe(false);
      for (const br of boxes.briefs) expect(overlap(f.box, br), `${lv} ${f.id} 선 요약`).toBe(false);
      // 받는 쪽 끝 — 받는 카드의 왼쪽 가장자리에 붙어 있다(보내는 쪽보다 받는 쪽이 가깝다).
      const tgt = f.id.split("->")[1].split(".")[0];
      const t = boxes.handles[tgt];
      expect(t.x - (f.box.x + f.box.width), `${lv} ${f.id} 받는 쪽 끝`).toBeGreaterThanOrEqual(0);
      expect(t.x - (f.box.x + f.box.width), `${lv} ${f.id} 받는 쪽 끝`).toBeLessThan(40);
    }
    if (lv === "mid") await expect(flag(page, SENS)).toHaveText("1");
  }
  await zoomTo(page, "far");
  const far = await flag(page, SENS).evaluate((el) => el.getBoundingClientRect().width);
  expect(far).toBeLessThan(12);
  await expect(flag(page, SENS).locator(".pg-wire-flag-n")).toBeHidden();       // 점에는 글자가 없다 — 짝: 중간에서는 "1" 이 보였다
});

test("칩을 누르면 선 판: 관계 문장 · 건너간 것 · 문제 글 = 서버 · `[]` 이면 점검한 것 · `null` 이면 사유", async ({ page }) => {
  await openWith(page, STRESS);
  // 실제 문제가 있는 선은 수익률 → 기대 수익 추정(쓰지 않음) · 실제로 깨끗한 선은 비중 계산 → 민감도(K3) · 점검하지 않은 선은 주입.
  await patchRun(page, (b) => { b.edges[SCEN].issues = null; b.edges[SCEN].issues_reason = "이 자리는 아직 점검 규칙이 없어요."; });
  const body = await run(page);
  await flag(page, EST).click();
  await expect(page.locator(".pg-wire-sheet")).toBeVisible();
  await expect(page.locator("p.pg-wire-relation")).toHaveText(body.relations[EST].text);
  expect(body.relations[EST].text).toContain(`(${body.relations[EST].brief})`);
  const keys = await row(page, "facts").locator("tr[data-key]").evaluateAll((trs) => trs.map((t) => t.getAttribute("data-key")));
  expect(keys).toEqual(body.edges[EST].facts!.map((f) => f.key));
  const issues = row(page, "issues").locator("li.pg-wire-issue");
  await expect(issues).toHaveCount(body.edges[EST].issues!.length);
  for (const [i, is] of body.edges[EST].issues!.entries()) {
    await expect(issues.nth(i)).toHaveAttribute("data-level", is.level);
    await expect(issues.nth(i)).toHaveAttribute("data-code", is.code);
    await expect(issues.nth(i)).toContainText(is.text);
  }

  // 짝 — 점검했고 찾지 못한 선: 점검한 것을 말한다(빈 줄 아님) · 문제 줄 0.
  const sens = body.edges[SENS];
  expect(sens.issues).toEqual([]);
  await page.locator(`.react-flow__edge[data-testid="rf__edge-${SENS}"]`).evaluate((el) => (el as HTMLElement).dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await expect(row(page, "issues")).toContainText("잃거나 바뀐 것을 찾지 못했어요");
  for (const c of sens.checks) await expect(row(page, "issues")).toContainText(c);
  await expect(row(page, "issues").locator("li.pg-wire-issue")).toHaveCount(0);

  // 짝 — 점검하지 않은 선: 사유(지어내지 않는다).
  await page.locator(`.react-flow__edge[data-testid="rf__edge-${SCEN}"]`).evaluate((el) => (el as HTMLElement).dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await expect(row(page, "issues")).toContainText("이 자리는 아직 점검 규칙이 없어요.");
  await expect(row(page, "issues")).not.toContainText("찾지 못했어요");
});

test("계산 전 관계 문장에는 요약 괄호가 없고, 계산 뒤엔 서버 요약이 들어간다", async ({ page }) => {
  await openWith(page, STRESS);
  await page.locator(`.react-flow__edge[data-testid="rf__edge-${SENS}"]`).evaluate((el) => (el as HTMLElement).dispatchEvent(new MouseEvent("click", { bubbles: true })));
  const rel = page.locator("p.pg-wire-relation");
  await expect(rel).toContainText("‘비중 계산’의");
  expect((await rel.textContent())!.split("→")[0]).not.toContain("(");
  await patchRun(page);
  const body = await run(page);
  await expect(rel).toHaveText(body.relations[SENS].text);
  expect(body.relations[SENS].brief).toBeTruthy();
});

test("여기까지 계산 뒤에도 다시 계산하지 않은 받는 쪽의 기록은 남는다 · 받는 쪽이 예전 결과면 칩을 숨긴다(짝)", async ({ page }) => {
  await openWith(page, STRESS);
  // 화면이 기록을 합치고 숨기는 규칙을 본다 — 비중 계산 → 민감도 선에 문제 하나를 주입한다(K3 부터 실제로는 깨끗하다).
  await patchRun(page, (b) => { if (b.edges[SENS]) b.edges[SENS].issues = [{ level: "changed", code: "x", text: "바뀌었어요" }]; });
  await run(page);
  await expect(flag(page, SENS)).toHaveCount(1);
  await expect(flag(page, EST)).toHaveCount(1);

  // 수익률까지만 다시 계산 — 민감도로 가는 선의 기록은 이번 응답에 없지만 남아야 한다.
  await page.locator('.pg-node[data-node-id="returns"]').click();
  await page.locator(".react-flow__pane").focus().catch(() => {});
  const resp = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/allocation/graph/run"));
  await page.keyboard.press("Shift+Enter");
  const partial = await (await resp).json() as Body & { partial?: unknown };
  expect(partial.partial).toBeTruthy();
  expect(partial.edges[SENS]).toBeUndefined();
  await expect(page.locator(".pg-run")).not.toContainText("계산하는 중");
  await expect(flag(page, SENS)).toHaveCount(1);

  // 비중 계산 방식을 바꾸면 비중 계산과 하류가 예전 결과 — 그쪽으로 가는 칩은 숨고, 기대 수익 추정으로 가는 칩은 남는다.
  await page.locator('.pg-node[data-node-id="optimizer"]').click();
  await page.locator('.pg-tab[data-tab="settings"]').click();
  await page.locator('.pg-basic-field[data-field="model"] .pg-choice', { hasText: "흔들림 최소" }).click();
  await expect(page.locator(".pg-summary--stale")).toBeVisible();
  await expect(flag(page, SENS)).toHaveCount(0);
  await expect(flag(page, EST)).toHaveCount(1);
});

test("고른 방식 대신 다른 비중이면 카드에 '고른 방식 대신함' 칩 — 가정 수에서는 뺀다(짝: 대체가 없으면 칩 없음)", async ({ page }) => {
  await openWith(page, STRESS);
  await patchRun(page);
  await run(page);
  const card = page.locator('.pg-node[data-node-id="optimizer"]');
  await expect(card.locator(".pg-tag--fallback")).toHaveCount(0);
  const before = await card.locator(".pg-node-ev").textContent();

  await patchRun(page, (b) => {
    const trust = b.nodes.optimizer.explain!.trust!;
    trust.push({ state: "assumed", kind: "fallback", text: "‘위험 똑같이’ 방식이 답을 내지 못해 역변동성 비중으로 대신했어요." });
  });
  await run(page);
  await expect(card.locator(".pg-tag--fallback")).toHaveText("고른 방식 대신함");
  // 가정 칩의 수는 대체를 세지 않는다 — 대체 앞과 같은 글.
  const assumeBefore = (before ?? "").match(/가정 (있음|\d+개)/)?.[0] ?? null;
  const assumeAfter = ((await card.locator(".pg-node-ev").textContent()) ?? "").match(/가정 (있음|\d+개)/)?.[0] ?? null;
  expect(assumeAfter).toBe(assumeBefore);
});

// ── K3 · 민감도는 받은 비중의 방식으로 다시 푼다 ──────────────────────────────────────────────
async function sensDetail(page: Page) {
  await page.locator('.pg-node[data-node-id="sens"]').click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
}

test("민감도(K3): 위험 똑같이는 기대 수익을 쓰지 않아 0 칸 히트맵 대신 서버 문장 · 짝: 수익 대비 위험 최적은 히트맵", async ({ page }) => {
  await openWith(page, STRESS);
  await patchRun(page);
  const body = await run(page);
  const r = body.nodes.sens.view!.result as { still?: string; mu_reach?: string; matrix: (number[] | null)[] };
  expect(r.mu_reach).toBe("none");
  expect(r.matrix.flat().every((x) => x === 0)).toBe(true);
  await sensDetail(page);
  await expect(page.locator(".pg-sens-still")).toHaveText(r.still!);
  await expect(page.locator(".pg-heat")).toHaveCount(0);
});

test("민감도(K3) 짝: 수익 대비 위험 최적이면 히트맵이 서버 행렬을 그린다 · 문장 없음", async ({ page }) => {
  const doc = { ...STRESS, nodes: STRESS.nodes.map((x) => (x.id === "optimizer" ? { ...x, params: { model: "mvo" } } : x)) };
  await openWith(page, doc);
  await patchRun(page);
  const body = await run(page);
  const r = body.nodes.sens.view!.result as { still?: string | null; matrix: number[][] };
  expect(r.still ?? null).toBeNull();
  await sensDetail(page);
  await expect(page.locator(".pg-sens-still")).toHaveCount(0);
  await expect(page.locator(".pg-heat tbody tr")).toHaveCount(r.matrix.length);
});
