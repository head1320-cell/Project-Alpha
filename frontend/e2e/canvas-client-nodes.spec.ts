import { test, expect, type Page } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// CF 3부 PB1 · 고객·계좌·목표·보유 진단 노드 — ★관측만(비중을 바꾸지 않는다)★
// ─────────────────────────────────────────────────────────────────────────────
//  · 목록에서 '고객' 으로 찾으면 넷이 나온다(분류가 아니라 워크플로 단계로 묶인다 — 데이터·확인하기)
//  · 계좌 점검: 선언하지 않은 한도는 '판정 못 함'(통과가 아니다) · 구간을 덮는 한도는 '넘지 않음' · 위험자산 비중은 구간으로
//  · 목표까지: 목표가 구간 안이면 격차의 부호를 모른다고 말한다 · 고객: 성향·출처·평가일 · 보유 진단: 위험 기여
//  · 이야기 탭이 "최적화기는 이 고객·계좌를 모른 채" 라고 말한다 · 별칭에 전화번호 모양이면 이유와 함께 멈춘다
// 연습 종목은 자산군이 배정되지 않아(KIS master 캐시 없음) 위험자산 비중이 0~100% — 그것이 이 테스트가 보는 정직한 상태다.
// ═══════════════════════════════════════════════════════════════════════════════

const F = { format: "project-alpha.portfolio-graph", version: 1 };
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) => ({ id, type, position: { x, y }, params });
const e = (s: string, sp: string, t: string, tp: string) => ({ id: `${s}.${sp}->${t}.${tp}`, source: s, source_port: sp, target: t, target_port: tp });
const T3 = ["005930", "000660", "035420"];

function pbDoc(alias = "고객 A-12") {
  return { ...F,
    nodes: [n("u", "universe", 0, 0, { tickers: T3, weights: { "005930": 50, "000660": 30, "035420": 20 } }),
            n("cw", "current_weights", 320, 0),
            n("c", "client_profile", 0, 360, { alias, risk_tolerance: "moderate", profile_source: "survey", assessed_at: "2026-01-02", horizon_years: 10 }),
            n("a", "account", 640, 0, { account_type: "irp", risky_asset_classes: ["EQUITY"],
                                        limits: [{ kind: "risky_asset_max_pct", value: 100, source: "PB 선언", as_of: "2026-10-01" }] }),
            n("t", "goal", 960, 0, { target_retirement_year: 2045,
                                     curve: [{ years_to_target: 20, risky_target_pct: 70 }, { years_to_target: 0, risky_target_pct: 30 }] }),
            n("h", "holdings_check", 640, 360)],
    edges: [e("u", "universe", "cw", "universe"), e("cw", "weights", "a", "weights"), e("c", "client", "a", "client"),
            e("a", "account", "t", "account"), e("cw", "weights", "h", "weights")] };
}

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const tab = (page: Page, k: "story" | "settings" | "detail") => page.locator(`.pg-tab[data-tab="${k}"]`).click();

async function openWith(page: Page, doc: object) {
  await page.addInitScript((d) => {
    try {
      if (sessionStorage.getItem("pb1_seeded")) return;
      sessionStorage.setItem("pb1_seeded", "1");
      sessionStorage.setItem("alpha_pg_wip", JSON.stringify(d));
    } catch { /* */ }
  }, doc);
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}

async function run(page: Page) {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  await resp;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
}

test("PB1 · 목록에서 '고객' 으로 찾으면 고객·계좌 점검·목표까지·보유 진단이 나온다", async ({ page }) => {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.locator('.pg-palette input[aria-label="노드 찾기"]').fill("고객");
  for (const kind of ["client_profile", "account", "goal", "holdings_check"])
    await expect(page.locator(`.pg-palette-item[data-kind="${kind}"]`), kind).toBeVisible();
});

test("PB1 · 계좌 점검 — 선언 안 한 한도는 '판정 못 함' · 덮는 한도는 '넘지 않음' · 위험자산 비중은 구간 · 최적화기는 모른다", async ({ page }) => {
  await openWith(page, pbDoc());
  // 새 포트(고객·계좌)는 제 색을 쓴다 — 모르는 타입의 회색이 아니다(화면 포트 목록에 빠지면 회색이 된다).
  const colors = await page.evaluate(() => {
    const probe = (v: string) => { const i = document.createElement("i"); i.style.color = v; document.querySelector(".pg-root")!.appendChild(i);
                                   const c = getComputedStyle(i).color; i.remove(); return c; };
    const bg = (sel: string) => getComputedStyle(document.querySelector(sel) as HTMLElement).backgroundColor;
    return { client: bg('.react-flow__handle.source[data-nodeid="c"][data-handleid="client"]'),
             account: bg('.react-flow__handle.source[data-nodeid="a"][data-handleid="account"]'),
             wantClient: probe("var(--pg-port-Client)"), wantAccount: probe("var(--pg-port-Account)"), unknown: probe("var(--pg-port-unknown)") };
  });
  expect(colors.client).toBe(colors.wantClient);
  expect(colors.account).toBe(colors.wantAccount);
  expect(colors.client).not.toBe(colors.unknown);
  await run(page);
  await node(page, "a").click();
  await tab(page, "detail");
  const side = page.locator(".pg-side");
  await expect(side.locator('.pg-acct-verdict[data-verdict="pass"]')).toHaveCount(1);
  await expect(side.locator('.pg-acct-verdict[data-verdict="undetermined"]')).toHaveCount(1);
  await expect(side.locator('.pg-acct-verdict[data-verdict="undetermined"]')).toContainText("판정 못 함");
  await expect(side.locator(".pg-acct-risky")).toContainText("0~100%");
  await expect(side.locator(".pg-acct-risky")).toContainText("모르는 보유 100%");
  await tab(page, "story");
  await expect(page.locator('.pg-step[data-node-id="a"]')).toContainText("최적화기는 이 고객·계좌를 모른 채");
});

test("PB1 · 목표까지 — 목표는 곡선에서 읽고, 구간 안이면 격차의 부호를 모른다고 말한다", async ({ page }) => {
  await openWith(page, pbDoc());
  await run(page);
  await node(page, "t").click();
  await tab(page, "detail");
  const side = page.locator(".pg-side");
  await expect(side.locator(".pg-goal-target")).toContainText("%");
  await expect(side.locator('.pg-goal-gap[data-state="unknown"]')).toContainText("몰라요");
});

test("PB1 · 고객 · 보유 진단 — 성향·출처·평가일 · 위험 기여", async ({ page }) => {
  await openWith(page, pbDoc());
  await run(page);
  await node(page, "c").click();
  await tab(page, "detail");
  const side = page.locator(".pg-side");
  await expect(side.locator(".pg-client-kv")).toContainText("위험중립형");
  await expect(side.locator(".pg-client-kv")).toContainText("설문");
  await expect(side.locator(".pg-client-kv")).toContainText("일 지났어요");
  await node(page, "h").click();
  await tab(page, "detail");
  await expect(side.locator(".pg-hold-risk .pg-table tr")).toHaveCount(3);
});

test("PB1 · 별칭에 전화번호 모양이면 그 이유로 멈춘다 — 짝: 보통 별칭은 통과", async ({ page }) => {
  await openWith(page, pbDoc("010-1234-5678"));
  await run(page).catch(() => { /* 검증 실패가 있으면 요약이 '완료' 가 아닐 수 있다 */ });
  await expect(node(page, "c").locator(".pg-node-status-why")).toContainText("전화번호");
});

test("PB1 · 위험 성향은 고른 뒤에도 '정하지 않음' 으로 되돌릴 수 있다(문서에서 칸이 지워진다)", async ({ page }) => {
  await openWith(page, pbDoc());
  await node(page, "c").click();
  await tab(page, "settings");
  const f = page.locator('.pg-basic-field[data-field="risk_tolerance"]');
  await expect(f.locator(".pg-choice.on")).toContainText("위험중립형");
  await f.locator('.pg-choice[data-choice=""]').click();
  await expect(f.locator('.pg-choice[data-choice=""]')).toHaveClass(/on/);
  const dl = page.waitForEvent("download");
  await page.locator(".pg-export").click();
  const doc = JSON.parse(require("node:fs").readFileSync((await (await dl).path())!, "utf-8"));
  expect(doc.nodes.find((x: { id: string }) => x.id === "c").params).not.toHaveProperty("risk_tolerance");
  // 짝 — 비울 수 없는 칸(성향 출처: 기본 '모름')에는 그 카드가 없다
  await expect(page.locator('.pg-basic-field[data-field="profile_source"] .pg-choice[data-choice=""]')).toHaveCount(0);
});
