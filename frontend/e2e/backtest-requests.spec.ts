import { test, expect, type Page, type Request } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { recordApi, stableJson } from "./helpers";

/**
 * BU3a · 백테스트 요청 골든 — ★편집기 모습을 바꿔도 서버에 가는 요청은 한 바이트도 바뀌지 않는다★
 * BU3 는 단계 넷(돈·기간·비용을 매수 패널에서 꺼냄)·kit 토스화·죽은 결과 자리 삭제를 한다. 전략 모델·`strategyToRun`·기본값은
 * 바꾸지 않는다 — 그것을 이 골든이 건다.
 *
 * - 실행(`POST /api/v1/backtest/runs`)은 가로채 `run_id` 만 돌려준다 — 실제 실행을 만들지 않고 본문만 잰다.
 * - 대상 수(`POST /api/v1/screener/universe-count`)는 `recordApi` 로 단계마다 정렬 고유 집합.
 * - 날짜 기본값(오늘·3년 전)이 본문에 들어가므로 시계를 고정한다. 저장한 전략은 `id`·`savedAt` 을 빼고 잰다.
 * - 조작은 `data-act` 훅으로만(화면 구조와 무관). 다시 얼리기: UPDATE_REQUEST_GOLDEN=1 — ★화면 바꾸기 전에만★(BU3a).
 */

const GOLDEN = path.join(__dirname, "golden", "backtest-requests.json");
const NOW = new Date("2026-10-02T09:00:00+09:00");
const SEARCH = "조건을 단어로 입력하세요";
const act = (page: Page, a: string) => page.locator(`[data-act="${a}"]`);

type Runs = { bodies: string[] };

async function setup(page: Page, seed?: (p: Page) => Promise<void>): Promise<Runs> {
  await page.clock.setFixedTime(NOW);
  const runs: Runs = { bodies: [] };
  await page.route("**/api/v1/backtest/runs", async (route) => {
    const req: Request = route.request();
    if (req.method() !== "POST") return route.fallback();
    runs.bodies.push(stableJson(JSON.parse(req.postData() ?? "null")));
    await route.fulfill({ json: { run_id: "bu3-golden", status: "queued" } });
  });
  // 실행 뒤 옮겨 가는 진행 화면의 요청은 이 계약 밖 — 조용히 막는다.
  await page.route("**/api/v1/backtest/runs/bu3-golden**", (route) => route.fulfill({ status: 404, json: { detail: "golden" } }));
  await page.goto("/backtest", { waitUntil: "domcontentloaded" });
  if (seed) { await seed(page); await page.reload({ waitUntil: "domcontentloaded" }); }
  await expect(act(page, "run")).toBeVisible({ timeout: 20_000 });
  return runs;
}

async function runOnce(page: Page, runs: Runs): Promise<string> {
  const n = runs.bodies.length;
  await act(page, "run").click();
  await expect.poll(() => runs.bodies.length, { timeout: 15_000 }).toBe(n + 1);
  await page.waitForURL(/\/backtest\/runs\/bu3-golden\/loading/);
  return runs.bodies[n];
}

async function back(page: Page) {
  await page.goto("/backtest", { waitUntil: "domcontentloaded" });
  await expect(act(page, "run")).toBeVisible({ timeout: 20_000 });
}

async function addDirectCondition(page: Page, expr: string, rhs: string) {
  await act(page, "cond-mode").first().getByRole("button", { name: "직접 입력", exact: true }).click();
  await act(page, "cond-expr").first().fill(expr);
  await act(page, "cond-rhs").first().fill(rhs);
  await act(page, "cond-save").first().click();
}

test("백테스트 요청 골든: 단계마다 같은 실행 본문 · 같은 대상 수 요청 · 같은 저장 내용", async ({ page }) => {
  test.setTimeout(300_000);
  const out: Record<string, unknown> = {};
  const count = recordApi(page, "/api/v1/screener/universe-count");
  const runs = await setup(page);
  await count.step("00 첫 화면");

  out["01 기본값"] = await runOnce(page, runs);
  await back(page);

  // ① 매수 — 펀더멘털 평가 켜기 · 최대 보유 종목 +5 · 직접 입력 조건 하나
  await act(page, "step-buy").click();
  await act(page, "buy-fundamentals").click();
  await act(page, "max-stocks").fill("15");
  await addDirectCondition(page, "{종가}", "1000");
  out["02 매수 바꿈"] = await runOnce(page, runs);
  await back(page);

  // ② 매도 — 목표가/손절가 절 켜기(익절·손절이 함께 켜진다) · 손절 7%
  await act(page, "step-sell").click();
  await act(page, "sell-exits").click();
  await expect(act(page, "stop-loss")).toHaveAttribute("aria-checked", "true");
  await act(page, "stop-loss-pct").fill("7");
  out["03 매도 바꿈"] = await runOnce(page, runs);
  await back(page);

  // ③ 매매 대상 — 시총군 하나 빼기(대상 수 요청) · 유동성 완화 · 생존편향 보정 전체
  await act(page, "step-universe").click();
  await count.step("04a 매매 대상 열기");
  await act(page, "cap").first().click();
  await count.step("04b 시총군 하나 빼기");
  await act(page, "liq-gate").getByRole("button", { name: "완화", exact: true }).click();
  await act(page, "survivorship").getByRole("button", { name: "전체(생존편향 보정)", exact: true }).click();
  out["04 대상 바꿈"] = await runOnce(page, runs);
  await back(page);

  // ④ 돈·기간·비용 — 투자 금액 · 수수료 · 증권거래세 · 리밸런싱 매월
  await act(page, "step-buy").click();
  await act(page, "capital").fill("12000");
  await act(page, "fee").fill("0.2");
  await act(page, "sell-tax").click();
  await act(page, "rebalance").getByRole("button", { name: "매월", exact: true }).click();
  out["05 돈·비용 바꿈"] = await runOnce(page, runs);
  await back(page);

  // 팩터 창으로 조건 하나(수식 빌더) — PER ≥ 10
  await act(page, "step-buy").click();
  await act(page, "factor").first().click();
  await page.getByPlaceholder(SEARCH).fill("PER");
  await page.locator(".tfm-row").filter({ has: page.locator('.tfm-row-d:text-is("{PER}")') }).first().click();
  await page.getByRole("button", { name: "입력", exact: true }).click();
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);
  await act(page, "cond-rhs").first().fill("10");
  await act(page, "cond-save").first().click();
  out["06 팩터 조건"] = await runOnce(page, runs);
  await back(page);

  // 저장 → 새로고침 → 불러오기 → 실행 (저장 내용도 잰다)
  await act(page, "strategy-name").fill("골든 전략");
  await act(page, "capital").fill("7000");
  await act(page, "save").click();
  const lib = await page.evaluate(() => JSON.parse(localStorage.getItem("alpha_bt_strategies_v2") ?? "[]"));
  out["07 저장 내용"] = stableJson((lib as Array<Record<string, unknown>>).map(({ id: _i, savedAt: _s, ...rest }) => rest));
  await page.reload({ waitUntil: "domcontentloaded" });
  await act(page, "load").first().click();
  out["07 불러와 실행"] = await runOnce(page, runs);

  out.count = count.steps;
  expect(Object.keys(out)).toHaveLength(9);
  // 골든 파일의 `handoff` 칸은 아래 테스트 몫이다 — 여기서는 빼고 견준다(다시 얼릴 때도 지우지 않는다).
  const prev = fs.existsSync(GOLDEN) ? JSON.parse(fs.readFileSync(GOLDEN, "utf8")) : {};
  const { handoff, ...want } = prev as Record<string, unknown>;
  if (process.env.UPDATE_REQUEST_GOLDEN === "1") {
    fs.writeFileSync(GOLDEN, JSON.stringify({ ...out, ...(handoff ? { handoff } : {}) }, null, 1) + "\n");
    return;
  }
  expect(out).toEqual(want);
});

test("백테스트 요청 골든: 스크리너·매크로에서 넘어온 설정으로 실행해도 같은 본문", async ({ page }) => {
  test.setTimeout(120_000);
  const out: Record<string, string> = {};
  const runs = await setup(page, async (p) => {
    await p.evaluate(() => sessionStorage.setItem("alpha:screener-handoff", JSON.stringify({
      filterAst: { logic: "AND", conditions: [{ kind: "field", field: "per", op: "lte", value: 10 }], groups: [] },
      universe: "kospi200", conditionSummary: ["PER ≤ 10"], resultCount: 42, createdAt: 0,
    })));
  });
  out["08 스크리너 넘김"] = await runOnce(page, runs);

  await page.goto("/backtest", { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    sessionStorage.removeItem("alpha:screener-handoff");
    sessionStorage.setItem("alpha:macro-handoff", JSON.stringify({ createdAt: 0, config: {
      id: "golden", name: "골든 매크로", family: "f", market: "KR", mode: "asset_alloc", note: "n",
      basket: [{ ticker: "069500", name: "KODEX 200", weight_pct: 60 }, { ticker: "114260", name: "KODEX 국고채3년", weight_pct: 40 }],
      rebalance_months: 3,
    } }));
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(act(page, "run")).toBeVisible({ timeout: 20_000 });
  out["09 매크로 넘김"] = await runOnce(page, runs);

  const key = "handoff";
  if (process.env.UPDATE_REQUEST_GOLDEN === "1") {
    const g = JSON.parse(fs.readFileSync(GOLDEN, "utf8"));
    g[key] = out;
    fs.writeFileSync(GOLDEN, JSON.stringify(g, null, 1) + "\n");
    return;
  }
  expect(out).toEqual(JSON.parse(fs.readFileSync(GOLDEN, "utf8"))[key]);
});

test("짝: 비교기는 공허하지 않다 — 기본 투자 금액 하나만 바꿔도 다르다고 본다", async () => {
  const want = JSON.parse(fs.readFileSync(GOLDEN, "utf8")) as Record<string, string>;
  const base = want["01 기본값"];
  expect(base, "기본 실행 본문이 골든에 있다").toContain('"config"');
  expect(want["05 돈·비용 바꿈"], "바꾼 단계는 기본값과 다르다").not.toEqual(base);
  const bent = { ...want, "01 기본값": base.replace(/"initial_capital":(\d+)/, (_m, n) => `"initial_capital":${Number(n) + 1}`) };
  expect(bent["01 기본값"], "골든 본문에 initial_capital 이 있어야 이 짝이 성립한다").not.toEqual(base);
  expect(bent).not.toEqual(want);
});
