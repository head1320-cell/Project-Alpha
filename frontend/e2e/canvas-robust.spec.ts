import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, trackErrors, uniq, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BR R1 — 견고성: 같이 무너지나 (설계 docs/superpowers/specs/2026-09-28-br-robustness-profile-design.md §R1)
// ─────────────────────────────────────────────────────────────────────────────
// 거는 것:
//  · 전략 합치기의 '견고성' 절 = ★서버 view.robustness 그대로★(이야기 줄 · 같이 떨어진 날 대 기대 · 충격 · 낙폭 구간 · 실질 개수)
//  · 모르면 "—" 와 서버 사유 — 0 으로 그리지 않는다 · 절 전체를 못 재면 그렇다고(짝)
//  · 고른 노드 위 막대의 '견고성 비교' — 비중을 내는 노드 둘을 고르면 새 노드에 위→아래 순으로 a·b · 계산하면 결과 · 되돌리기 한 번에 사라짐
//  · 짝: 비중을 내지 않는 노드가 섞이면 단추가 흐리고, 누르면 사유만(노드를 만들지 않는다)
//  · 라이트·다크 AA
// ═══════════════════════════════════════════════════════════════════════════════

type Dict = Record<string, unknown>;
type NodeRes = { status: string; reason: string | null; view?: Dict };
type RunBody = { nodes: Record<string, NodeRes> };
type Doc = { nodes: { id: string; type: string; position: { x: number; y: number }; params: Dict }[];
             edges: { source: string; source_port: string; target: string; target_port: string }[] };

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const mod = process.platform === "darwin" ? "Meta" : "Control";

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
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as RunBody;
    fn(body);
    await route.fulfill({ response: res, json: body });
  });
}

async function addStrategy(page: Page, source: string) {
  await page.locator(".pg-strat-add").click();
  await page.locator(`.pg-strat-item[data-source="${source}"]`).click();
  await expect(page.locator(".pg-note")).toBeVisible();
}

async function openCombine(page: Page, id: string) {
  // 이미 그 노드를 고른 상태면 오른쪽 창이 노드를 보이고 있어 단계 목록이 없다.
  const step = page.locator(`.pg-step[data-node-id="${id}"] .pg-step-num`);
  if (await step.count()) await step.click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
}

const section = (page: Page, name: string) => page.locator(".pg-side .pg-rob-sec", { has: page.locator("summary", { hasText: name }) });
async function openSection(page: Page, name: string) {
  const sec = section(page, name);
  if (!(await sec.evaluate((el) => (el as HTMLDetailsElement).open))) await sec.locator("summary").click();
  return sec;
}

test("견고성 절(BR R1a): 전략 합치기 자세히 = 서버 view.robustness 그대로 — 이야기 · 같이 떨어진 날 대 기대 · 충격 · 낙폭 구간 · 실질 개수", async ({ page }) => {
  const sink = trackErrors(page);
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const body = await run(page);
  const doc = await wip(page);
  const pf = doc.nodes.find((n) => n.type === "portfolio_combine")!;
  const rob = body.nodes[pf.id].view!.robustness as Dict;
  expect(rob.available, String(rob.reason)).toBe(true);
  await openCombine(page, pf.id);
  const root = page.locator(".pg-side .pg-rob");
  await expect(root).toBeVisible();
  await expect(root.locator(".pg-rob-story li")).toHaveText(rob.story as string[]);
  // 성과 종류 = 응답이 선언한 것(과거 데이터 위 시뮬레이션 · mock 이면 합성) — 화면이 지어내지 않는다.
  const lab = rob.perf_label as { kind: string; data_real: boolean };
  expect(lab.kind).toBe("backtest");
  await expect(root.locator(`.perf-label.perf-label--${lab.kind}`)).toBeVisible();
  await expect(root).toContainText(`지난 ${rob.n_days}거래일`);

  // 상관 추이 — 기본으로 펼쳐져 있고, 한 쌍이면 칩 없이 그 쌍.
  const roll = rob.rolling as { pairs: { values: (number | null)[] }[]; window: number };
  const trend = await openSection(page, "상관 추이");
  const last = [...roll.pairs[0].values].reverse().find((v) => v !== null) as number;
  await expect(trend.locator(".pg-rob-trend")).toHaveAttribute("aria-label", new RegExp(`지금 ${last.toFixed(2)}`));
  await expect(trend.locator(".pg-rob-band")).toHaveCount(1);

  const crisis = rob.crisis as { pairs: { co_drops: number; expected_co_drops: number }[]; crisis_days: number };
  const cs = await openSection(page, "위기 때 상관");
  await expect(cs.locator(".pg-rob-pair")).toHaveCount(crisis.pairs.length);
  const p0 = crisis.pairs[0];
  await expect(cs.locator(".pg-rob-codrop").first()).toHaveText(`같이 떨어진 날 ${p0.co_drops}일 · 평소 관계라면 약 ${p0.expected_co_drops.toFixed(0)}일`);
  await expect(cs).toContainText(`${crisis.crisis_days}일`);

  const shock = rob.shock as { scenarios: { kind: string; available: boolean; stressed_vol_pct?: number }[] };
  const sh = await openSection(page, "상관 급등 충격");
  const assumed = shock.scenarios.find((x) => x.kind === "assumed")!;
  const box = sh.locator('.pg-rob-shock[data-kind="assumed"]');
  await expect(box.locator(".pg-tag")).toHaveText("가정");
  if (assumed.available) await expect(box).toContainText(`${assumed.stressed_vol_pct!.toFixed(1)}%`);

  const dd = rob.drawdown as { strategies: { max_drawdown_pct: number | null }[] };
  const dsec = await openSection(page, "최악 구간 겹침");
  await expect(dsec.locator(".pg-rob-dd-bar")).toHaveCount(dd.strategies.filter((x) => x.max_drawdown_pct !== null).length);
  // 자릿수를 맞춘다("-7.5%" 옆 "-15.14%" 가 아니게) — 서버 값 그대로, 소수 둘째 자리.
  for (const x of dd.strategies) {
    if (x.max_drawdown_pct !== null) await expect(dsec).toContainText(`${x.max_drawdown_pct.toFixed(2)}% · `);
  }

  const eff = rob.effective_n as { value: number; n: number };
  const more = await openSection(page, "더 보기");
  await expect(more).toContainText(`약 ${eff.value.toFixed(1)}개 / ${eff.n}개`);

  // 상관표 — 발산 색은 글자 값과 함께(색만으로 읽지 않는다).
  await expect(page.locator(".pg-side .pg-corr-table td.pos, .pg-side .pg-corr-table td.neg").first()).toHaveText(/-?\d\.\d\d/);
  expect(uniq(sink.pageErrors)).toEqual([]);
});

test("견고성 절(BR R1a): 모르면 '—' 와 서버 사유 — 0 으로 그리지 않는다 · 절 전체를 못 재면 그렇다고(짝)", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  let pfId = "";
  await patchRun(page, (b) => {
    for (const [id, r] of Object.entries(b.nodes)) {
      const rob = r.view?.robustness as Dict | undefined;
      if (!rob) continue;
      pfId = id;
      const pairs = (rob.crisis as { pairs: Dict[] }).pairs;
      pairs[0].co_drops = null; pairs[0].expected_co_drops = null; pairs[0].reason = "흔들림이 없어요(테스트)";
      rob.effective_n = { available: false, value: null, n: 2, reason: "상관을 못 잰 쌍이 있어요(테스트)" };
      rob.shock = { available: false, reason: "충격을 넣지 못했어요(테스트)" };
    }
  });
  await run(page);
  await openCombine(page, pfId);
  const cs = await openSection(page, "위기 때 상관");
  await expect(cs.locator(".pg-rob-codrop").first()).toHaveText("같이 떨어진 날 —");
  await expect(cs.locator(".pg-rob-codrop").first()).toHaveAttribute("title", "흔들림이 없어요(테스트)");
  const more = await openSection(page, "더 보기");
  await expect(more.locator(".pg-kv div").first()).toContainText("—");
  await expect(more).toContainText("상관을 못 잰 쌍이 있어요(테스트)");
  const sh = await openSection(page, "상관 급등 충격");
  await expect(sh).toContainText("충격을 넣지 못했어요(테스트)");

  // 짝 — 절 전체를 못 재면 그 사유 한 줄만(빈 표를 그리지 않는다).
  await page.unroute("**/api/v1/allocation/graph/run**");
  await patchRun(page, (b) => {
    for (const r of Object.values(b.nodes)) {
      if (r.view?.robustness) r.view.robustness = { available: false, reason: "견고성 계산이 깨졌어요(테스트)" };
    }
  });
  await run(page);
  await openCombine(page, pfId);
  await expect(page.locator(".pg-side .pg-rob")).toContainText("견고성을 재지 못했어요 — 견고성 계산이 깨졌어요(테스트)");
  await expect(page.locator(".pg-side .pg-rob-sec")).toHaveCount(0);
});

test("고른 노드 견고성 비교(BR R1b): 비중 노드 둘을 고르면 막대의 단추로 새 노드에 위→아래 a·b · 계산하면 결과 · 되돌리기 한 번에 사라짐", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await page.keyboard.press("Control+d");
  let doc = await wip(page);
  const opts = doc.nodes.filter((n) => n.type === "optimizer");
  expect(opts).toHaveLength(2);
  const [top, bottom] = [...opts].sort((a, b) => a.position.y - b.position.y || a.position.x - b.position.x);
  await node(page, top.id).click();
  await node(page, bottom.id).click({ modifiers: [mod] });
  const bar = page.locator(".pg-selbar");
  await expect(bar).toBeVisible();
  await expect(bar.locator(".pg-selbar-n")).toHaveText("2개 골랐어요");
  await expect(bar.locator(".pg-selbar-compare")).not.toHaveAttribute("aria-disabled", "true");
  const before = doc.nodes.length;
  await bar.locator(".pg-selbar-compare").click();
  await expect(page.locator(".pg-note")).toContainText("견고성 비교");
  doc = await wip(page);
  const cmp = doc.nodes.filter((n) => n.type === "sleeve_analytics");
  expect(cmp).toHaveLength(1);
  expect(doc.nodes).toHaveLength(before + 1);
  const into = doc.edges.filter((e) => e.target === cmp[0].id).map((e) => [e.target_port, e.source, e.source_port]).sort();
  expect(into).toEqual([["a", top.id, "weights"], ["b", bottom.id, "weights"]]);

  const body = await run(page);
  expect(body.nodes[cmp[0].id].status, String(body.nodes[cmp[0].id].reason)).toBe("ok");
  await node(page, cmp[0].id).click();
  await page.locator('.pg-tab[data-tab="detail"]').click();
  await expect(page.locator(".pg-side .pg-rob")).toBeVisible();
  await expect(page.locator(".pg-side .pg-rob-legend li")).toHaveCount(2);
  await expect(page.locator(".pg-side .pg-corr")).toBeVisible();          // 예전 표(상관·위험 몫)도 그대로

  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 10 } });
  await page.keyboard.press("Control+z");
  doc = await wip(page);
  expect(doc.nodes.filter((n) => n.type === "sleeve_analytics"), "되돌리기 한 번에 노드가").toHaveLength(0);
  expect(doc.edges.filter((e) => e.target === cmp[0].id), "선도").toHaveLength(0);
});

test("고른 노드 견고성 비교(BR R1b) 짝: 비중을 내지 않는 노드가 섞이면 단추가 흐리고, 누르면 사유만 — 노드를 만들지 않는다", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await node(page, "returns").click({ modifiers: [mod] });
  const bar = page.locator(".pg-selbar");
  await expect(bar).toBeVisible();
  const btn = bar.locator(".pg-selbar-compare");
  await expect(btn).toHaveAttribute("aria-disabled", "true");
  await expect(btn).toHaveAttribute("title", /비중을 내는 노드끼리만/);
  const before = (await wip(page)).nodes.length;
  // aria-disabled 는 누를 수 있다(누르면 사유를 말한다) — Playwright 는 aria-disabled 를 '누를 수 없음'으로 보므로 force.
  await btn.click({ force: true });
  await expect(page.locator(".pg-note")).toContainText("비중을 내는 노드끼리만");
  expect((await wip(page)).nodes).toHaveLength(before);
  // 하나만 고르면 막대가 없다.
  await node(page, "optimizer").click();
  await expect(bar).toHaveCount(0);
});

test("견고성 절 대비(BR R1): 라이트·다크 AA — 펼친 네 절 모두", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  await run(page);
  const doc = await wip(page);
  const pf = doc.nodes.find((n) => n.type === "portfolio_combine")!;
  await openCombine(page, pf.id);
  for (const name of ["위기 때 상관", "상관 급등 충격", "최악 구간 겹침", "더 보기"]) await openSection(page, name);
  for (const dark of [false, true]) {
    await page.evaluate((d) => document.documentElement.classList.toggle("dark", d), dark);
    await page.waitForTimeout(150);
    const a = await page.evaluate<AuditResult>(contrastAudit(".pg-side .pg-rob"));
    expect(a.checked).toBeGreaterThan(30);
    expect(a.low, dark ? "dark" : "light").toEqual([]);
  }
});

test("고른 노드 막대(BR R1b): 고른 노드 아래에 뜨고 · 묶으면 사라져 상자 머리 단추를 누를 수 있다(짝)", async ({ page }) => {
  await openCanvas(page);
  await node(page, "optimizer").click();
  await node(page, "risk").click({ modifiers: [mod] });
  const bar = page.locator(".pg-selbar");
  await expect(bar).toBeVisible();
  const barBox = (await bar.boundingBox())!;
  const lowest = Math.max(...await Promise.all(["optimizer", "risk"].map(async (id) => {
    const b = (await node(page, id).boundingBox())!;
    return b.y + b.height;
  })));
  expect(barBox.y, "막대는 고른 노드 아래 — 위에 두면 상자 머리를 가린다").toBeGreaterThanOrEqual(lowest - 1);
  await page.keyboard.press("Control+g");
  await expect(page.locator(".pg-group")).toHaveCount(1);
  await expect(bar, "묶은 뒤에는 상자 머리가 그 역할 — 막대가 없다").toHaveCount(0);
  await page.locator(".pg-group").getByRole("button", { name: "묶음 접기" }).click();
  await expect(page.locator(".pg-group").getByRole("button", { name: "묶음 펼치기" })).toBeVisible();
});
