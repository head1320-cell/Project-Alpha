import { test, expect, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { recordApi, stableJson } from "./helpers";

/**
 * BU2a · 스크리너 요청 골든 — ★모습을 바꿔도 서버에 가는 요청은 한 바이트도 바뀌지 않는다★
 * CLAUDE.md §6: 스크리너 3-레이어(유동성 게이트 → 필터 kind → 후처리)와 엔진은 리팩터링 대상이 아니다. BU2 가 화면을 토스식으로
 * 다시 짜도 유니버스·조건·연산자·값·시총·유동성 게이트(기본 꺼짐)·조건식·백테스트 넘기기가 같은 요청을 만들어야 한다.
 *
 * 조작은 `data-act` 훅으로만 한다(화면 구조와 무관). BU2 에서 생기는 `expert`(전문가 설정)는 있으면 펼치고 없으면 지나간다.
 * 대상은 `/api/v1/screener/*` 만 — 연습용 칩이 부르는 `/macro/connection-status` 같은 읽기는 이 계약 밖이다.
 * 다시 얼리기: UPDATE_REQUEST_GOLDEN=1 — ★화면 바꾸기 전에만★(BU2a). 그 뒤로는 바이트 동일이어야 한다.
 */

const GOLDEN = path.join(__dirname, "golden", "screener-requests.json");
const act = (page: Page, a: string) => page.locator(`[data-act="${a}"]`);
const SEARCH = "조건을 단어로 입력하세요";

async function openExpert(page: Page) {
  const ex = act(page, "expert");
  if (await ex.count() && !(await ex.evaluate((d) => (d as HTMLDetailsElement).open))) await ex.locator("summary").click();
}

async function addFactor(page: Page, name: string) {
  await act(page, "add-factor").first().click();
  await page.getByPlaceholder(SEARCH).fill(name);
  const row = page.locator(".tfm-row").filter({ has: page.locator(`.tfm-row-d:text-is("{${name}}")`) }).first();
  await row.click();
  await page.getByRole("button", { name: "입력", exact: true }).click();
  await expect(page.getByPlaceholder(SEARCH)).toHaveCount(0);
}

async function scenario(page: Page): Promise<Record<string, unknown>> {
  const rec = recordApi(page, "/api/v1/screener/");
  await page.goto("/screener", { waitUntil: "domcontentloaded" });
  await expect(act(page, "add-factor").first()).toBeVisible({ timeout: 20_000 });
  await rec.step("01 첫 화면");

  await act(page, "universe").selectOption("kosdaq150");
  await rec.step("02 유니버스 코스닥 150");

  await addFactor(page, "시가총액");
  await rec.step("03 팩터 시가총액");

  await act(page, "cond-op").first().selectOption("lte");
  await rec.step("04 연산자 ≤");
  await act(page, "cond-val").first().fill("500000");
  await rec.step("05 값 500000");

  await openExpert(page);
  await act(page, "gate").check();
  await rec.step("06 유동성 게이트 켜기");

  await act(page, "mcap-preset").first().click();
  await rec.step("07 시총 첫 프리셋");

  await addFactor(page, "PER");
  await rec.step("08 팩터 PER");

  await openExpert(page);
  await act(page, "expr").fill("팩터1 or 팩터2");
  await act(page, "expr-run").click();
  await rec.step("09 조건식 팩터1 or 팩터2");

  await act(page, "cond-remove").first().click();
  await rec.step("10 팩터1 지우기");

  await act(page, "send-backtest").click();
  await page.waitForURL(/\/backtest/);
  const handoff = await page.evaluate(() => JSON.parse(sessionStorage.getItem("alpha:screener-handoff") ?? "null"));
  if (handoff) delete handoff.createdAt;
  return { steps: rec.steps, handoff: JSON.parse(stableJson(handoff)) };
}

test("스크리너 요청 골든: 조작마다 같은 요청 · 백테스트로 넘기는 값도 같다", async ({ page }) => {
  test.setTimeout(180_000);
  const got = await scenario(page);
  expect(Object.keys(got.steps as object)).toHaveLength(10);
  expect(((got.steps as Record<string, string[]>)["01 첫 화면"]).some((r) => r.includes("run-advanced-stream")), "첫 화면이 스트림 실행을 부른다").toBe(true);
  if (process.env.UPDATE_REQUEST_GOLDEN === "1") {
    fs.writeFileSync(GOLDEN, JSON.stringify(got, null, 1) + "\n");
    return;
  }
  const want = JSON.parse(fs.readFileSync(GOLDEN, "utf8"));
  expect(got).toEqual(want);
});

test("짝: 비교기는 공허하지 않다 — 골든의 요청 하나만 바꿔도 다르다고 본다", async () => {
  const want = JSON.parse(fs.readFileSync(GOLDEN, "utf8")) as { steps: Record<string, string[]> };
  const k = "06 유동성 게이트 켜기";
  expect(want.steps[k].some((r) => r.includes('"liquidity_floor":"relaxed"')), "게이트를 켠 단계는 relaxed 를 보낸다").toBe(true);
  expect(want.steps["01 첫 화면"].every((r) => !r.includes('"liquidity_floor":"relaxed"')), "★게이트 기본값은 꺼짐★").toBe(true);
  const bent = JSON.parse(JSON.stringify(want));
  bent.steps[k] = bent.steps[k].map((r: string) => r.replace('"relaxed"', '"off"'));
  expect(bent).not.toEqual(want);
});
