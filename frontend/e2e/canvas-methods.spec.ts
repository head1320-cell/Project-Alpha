import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, trackErrors, uniq, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BS4 — 합치기 방법 (설계 docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md §BS4)
// ─────────────────────────────────────────────────────────────────────────────
// 사용자 승인(2026-09-29): 기본값(위험 똑같이)은 그대로 두고, 고를 때만 쓰이는 방법을 더한다.
// 거는 것:
//  · 방법 카드 = 서버 x-ui 그대로(순서 · 이름 · 한 줄 설명) · 기본은 위험 똑같이
//  · 몫 직접 정하기: 전략마다 칸 · 합을 늘 보인다(빈 칸 수 → 남은 % → 맞아요) · 계산하면 몫 = 정한 값
//  · 짝: 칸을 비우면 노드가 비어 있는 전략 이름을 들어 실패한다(다른 방법으로 대신 계산하지 않는다)
//  · 방법 비교(자세히) = 서버 view.method_compare 그대로 — 줄 수 · 지금 방법 표시 · "낫다는 뜻이 아니에요"
//  · 위기 때 위험 똑같이: 믿음 칸이 시장 대용과 위기일 수를 말한다
//  · 라이트·다크 AA
// ═══════════════════════════════════════════════════════════════════════════════

type Dict = Record<string, unknown>;
type NodeRes = { status: string; reason: string | null; view?: Dict; explain?: { trust: { state: string; text: string }[] } };
type RunBody = { nodes: Record<string, NodeRes> };
type Doc = { nodes: { id: string; type: string; params: Dict }[];
             edges: { source: string; source_port: string; target: string; target_port: string }[];
             groups?: { id: string; label: string; kind?: string; output?: string | null }[] };
type Ui = { options: Record<string, string>; descriptions: Record<string, string>; order: string[]; question: string };

const wip = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha_pg_wip") ?? "{}")) as Promise<Doc>;
const portfolioOf = (doc: Doc) => doc.nodes.find((n) => n.type === "portfolio_combine")!;
const strategiesOf = (doc: Doc) => (doc.groups ?? []).filter((g) => g.kind === "strategy");
const portOf = (doc: Doc, output: string | null | undefined) =>
  doc.edges.find((e) => e.source === output && e.target === portfolioOf(doc).id)!.target_port;

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
}

async function addStrategy(page: Page, source: string) {
  await page.locator(".pg-strat-add").click();
  await page.locator(`.pg-strat-item[data-source="${source}"]`).click();
  await expect(page.locator(".pg-note")).toBeVisible();
}

async function runRaw(page: Page): Promise<RunBody> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  return (await (await resp).json()) as RunBody;
}

async function openTab(page: Page, id: string, tab: "settings" | "detail") {
  const step = page.locator(`.pg-step[data-node-id="${id}"] .pg-step-num`);
  if (await step.count()) await step.click();
  await page.locator(`.pg-tab[data-tab="${tab}"]`).click();
}

async function methodUi(page: Page): Promise<Ui> {
  const cat = await (await page.request.get("http://localhost:8000/api/v1/allocation/graph/node-types")).json();
  return cat.nodes.find((c: { type: string }) => c.type === "portfolio_combine").params_schema.properties.method["x-ui"] as Ui;
}

test("합치기 방법(BS4): 카드 = 서버 순서·이름·설명 · 기본 위험 똑같이 · 몫 직접 정하기는 합을 늘 보이고 계산하면 그 몫", async ({ page }) => {
  const sink = trackErrors(page);
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const doc = await wip(page);
  const pf = portfolioOf(doc);
  const [a, b] = strategiesOf(doc);
  const pa = portOf(doc, a.output), pb = portOf(doc, b.output);
  const ui = await methodUi(page);

  await openTab(page, pf.id, "settings");
  const field = page.locator('.pg-side .pg-basic-field[data-field="method"]');
  await expect(field.locator(".pg-q")).toHaveText(ui.question);
  await expect(field.locator(".pg-choice b")).toHaveText(ui.order.map((k) => ui.options[k]));
  await expect(field.locator(".pg-choice .pg-choice-help")).toHaveText(ui.order.map((k) => ui.descriptions[k]));
  await expect(field.locator('.pg-choice[aria-pressed="true"]')).toHaveAttribute("data-choice", "risk_parity");
  // 몫 칸은 그 방법일 때만(show_if) — 기본에서는 없다(짝).
  await expect(page.locator('.pg-side .pg-basic-field[data-field="shares"]')).toHaveCount(0);

  await field.locator('.pg-choice[data-choice="manual"]').click();
  const shares = page.locator('.pg-side .pg-basic-field[data-field="shares"]');
  await expect(shares.locator(".pg-perport-row")).toHaveCount(2);
  await expect(shares.locator(`.pg-perport-row[data-port="${pa}"] .pg-perport-name`)).toHaveText(a.label);
  const sum = shares.locator(".pg-perport-sum");
  await expect(sum).toHaveText("2개 전략이 비어 있어요");
  await expect(sum).toHaveAttribute("data-ok", "0");
  await shares.locator(`.pg-perport-row[data-port="${pa}"] input`).fill("60");
  await shares.locator(`.pg-perport-row[data-port="${pb}"] input`).fill("30");
  await expect(sum).toHaveText("합 90% — 10% 더 정해 주세요");
  await shares.locator(`.pg-perport-row[data-port="${pb}"] input`).fill("40");
  await expect(sum).toHaveText("합 100% — 맞아요");
  await expect(sum).toHaveAttribute("data-ok", "1");
  expect((await wip(page)).nodes.find((n) => n.id === pf.id)!.params).toMatchObject({ method: "manual", shares: { [pa]: 60, [pb]: 40 } });

  const body = await runRaw(page);
  const r = body.nodes[pf.id];
  expect(r.status, String(r.reason)).toBe("ok");
  const rows = (r.view!.strategies as { port: string; share_pct: number }[]);
  expect(rows.find((x) => x.port === pa)!.share_pct).toBe(60);
  expect(rows.find((x) => x.port === pb)!.share_pct).toBe(40);
  expect(r.explain!.trust.some((t) => t.text.includes("내가 정한 몫"))).toBe(true);
  await openTab(page, pf.id, "detail");
  await expect(page.locator(`.pg-side .pg-strat-table tr[data-port="${pa}"] td`).nth(1)).toHaveText("60.0%");
  expect(uniq(sink.pageErrors)).toEqual([]);
});

test("합치기 방법(BS4) 짝: 몫 칸을 비우면 노드가 비어 있는 전략 이름을 들어 실패한다 — 다른 방법으로 대신 계산하지 않는다", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const doc = await wip(page);
  const pf = portfolioOf(doc);
  const [a, b] = strategiesOf(doc);
  await openTab(page, pf.id, "settings");
  await page.locator('.pg-side .pg-choice[data-choice="manual"]').click();
  await page.locator(`.pg-side .pg-perport-row[data-port="${portOf(doc, a.output)}"] input`).fill("100");
  const body = await runRaw(page);
  const r = body.nodes[pf.id];
  expect(r.status).toBe("failed");
  expect(r.reason).toContain(b.label);
  expect(r.reason).toContain("대신 계산하지 않았어요");
  await expect(page.locator(`.pg-node[data-node-id="${pf.id}"]`)).toContainText(b.label);
});

test("방법 비교(BS4): 자세히 = 서버 view.method_compare 그대로 — 줄 · 지금 방법 · 막대 = 몫 · 숫자 · '낫다는 뜻이 아니에요' · 라이트·다크 AA", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const doc = await wip(page);
  const pf = portfolioOf(doc);
  const body = await runRaw(page);
  const mc = body.nodes[pf.id].view!.method_compare as { current: string; note: string;
    rows: { method: string; label: string; available: boolean; shares?: Record<string, number>; vol_pct?: number; reason?: string }[] };
  expect(mc.current).toBe("risk_parity");
  await openTab(page, pf.id, "detail");
  const root = page.locator(".pg-side .pg-mc");
  await expect(root.locator(".pg-mc-note")).toHaveText(mc.note);
  expect(mc.note).toContain("낫다는 뜻이 아니에요");
  await expect(root.locator(".pg-mc-row")).toHaveCount(mc.rows.length);
  await expect(root.locator(".pg-mc-row .pg-mc-head b")).toHaveText(mc.rows.map((x) => x.label));
  await expect(root.locator('.pg-mc-row[data-current="1"]')).toHaveCount(1);
  await expect(root.locator('.pg-mc-row[data-current="1"]')).toHaveAttribute("data-method", "risk_parity");
  await expect(root.locator('.pg-mc-row[data-current="1"] .pg-mc-chip--on')).toHaveText("지금");
  for (const row of mc.rows) {
    const el = root.locator(`.pg-mc-row[data-method="${row.method}"]`);
    if (!row.available) { await expect(el.locator(".pg-mc-reason")).toHaveText(String(row.reason)); continue; }
    const label = Object.entries(row.shares!).map(([n, v]) => `${n} ${v.toFixed(1)}%`).join(", ");
    await expect(el.locator(".pg-mc-bar")).toHaveAttribute("aria-label", label);
    await expect(el.locator(".pg-mc-nums dd").first()).toHaveText(`${row.vol_pct!.toFixed(1)}%`);
  }
  // 합치기 결과의 몫 = 비교표의 '지금' 줄 몫(같은 흐름)
  const cur = mc.rows.find((x) => x.method === "risk_parity")!;
  const res = body.nodes[pf.id].view!.result as { sleeve_allocation: Record<string, number> };
  expect(cur.shares).toEqual(res.sleeve_allocation);

  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => { document.documentElement.classList.toggle("dark", t === "dark"); }, theme);
    await page.waitForTimeout(150);
    const audit = await page.evaluate<AuditResult>(contrastAudit(".pg-side .pg-mc"));
    expect(audit.checked).toBeGreaterThan(20);
    expect(audit.low, `${theme} 대비`).toEqual([]);
  }
});

test("위기 때 위험 똑같이(BS4): 고르면 계산되고 믿음 칸이 시장 대용·위기일 수를 말한다 · 비교표에서 그 줄이 '지금'", async ({ page }) => {
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const doc = await wip(page);
  const pf = portfolioOf(doc);
  await openTab(page, pf.id, "settings");
  await page.locator('.pg-side .pg-choice[data-choice="crisis_risk_parity"]').click();
  const body = await runRaw(page);
  const r = body.nodes[pf.id];
  expect(r.status, String(r.reason)).toBe("ok");
  const days = (r.view!.result as { crisis: { days: number } }).crisis.days;
  const market = (r.view!.market as { label: string }).label;
  expect(r.explain!.trust.some((t) => t.text.includes(market) && t.text.includes(`${days}일`))).toBe(true);
  await openTab(page, pf.id, "detail");
  await expect(page.locator('.pg-side .pg-mc-row[data-current="1"]')).toHaveAttribute("data-method", "crisis_risk_parity");
});

test("방법 비교(BS4) 짝: 서버가 못 잰 줄은 막대·숫자 없이 서버 사유 그대로 · 대체한 줄은 '대신 계산' 칩", async ({ page }) => {
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as RunBody;
    for (const n of Object.values(body.nodes)) {
      const mc = n.view?.method_compare as { rows: Dict[] } | undefined;
      if (!mc) continue;
      const crisis = mc.rows.find((x) => x.method === "crisis_risk_parity")!;
      for (const k of ["shares", "vol_pct", "div_ratio", "effective_n", "fallback"]) delete crisis[k];
      Object.assign(crisis, { available: false, reason: "시장 대용 시세가 모자라요(12일)" });
      Object.assign(mc.rows.find((x) => x.method === "min_var")!, { fallback: { used: true, from: "min_var", reason: "풀리지 않아 역변동성" } });
    }
    await route.fulfill({ response: res, json: body });
  });
  await openCanvas(page);
  await addStrategy(page, "tpl:stress");
  const doc = await wip(page);
  const pf = portfolioOf(doc);
  await runRaw(page);
  await openTab(page, pf.id, "detail");
  const crisis = page.locator('.pg-side .pg-mc-row[data-method="crisis_risk_parity"]');
  await expect(crisis).toHaveAttribute("data-available", "0");
  await expect(crisis.locator(".pg-mc-reason")).toHaveText("시장 대용 시세가 모자라요(12일)");
  await expect(crisis.locator(".pg-mc-bar, .pg-mc-nums")).toHaveCount(0);
  await expect(page.locator('.pg-side .pg-mc-row[data-method="min_var"] .pg-mc-chip--fb')).toHaveText("대신 계산");
  await expect(page.locator('.pg-side .pg-mc-row[data-method="equal"] .pg-mc-chip--fb')).toHaveCount(0);   // 짝
});
