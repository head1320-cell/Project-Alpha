import { test, expect, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { recordApi } from "./helpers";
import {
  LIVE_REFUSED, liveState, realismState, routeConnection, routeGate, routeLive, routeRealism, signIn,
  MB_STRATEGIES,
} from "./fixtures/admin";

/**
 * BU9a · 관리 화면 셋 요청 골든 — ★모습을 바꿔도 서버에 가는 요청(메서드·경로·본문)과 폴링 주기는 그대로★ (ADR-003 §2.7)
 *
 * - 화면 조작은 `data-act` 훅으로만(구조와 무관). 서버 응답은 `fixtures/admin.ts` 가 정한다(실키·등록 전략이 없어서).
 * - 단계마다 `writes`(GET 이 아닌 것)와 `reads`(GET)를 나눠 정렬 고유 집합으로 잰다. 실거래 화면은 10초마다 읽으므로
 *   ★취소 단계는 writes 만★ 남긴다(그 사이 폴링이 끼어도 흔들리지 않게). 쓰기 단계는 늘 다시 읽으므로 reads 가 정해진다.
 * - `confirmIfAsked(act)`: 확인 단추가 보이면 누른다. 옛 화면엔 확인이 없으니 그냥 지나간다 — ★골든은 확인 유무를 보지 않는다★
 *   (BU9b~d 가 확인을 더한다: 사용자 결정 2026-10-10). 확인이 있는지(취소면 요청 0)는 각 화면 스펙이 따로 건다.
 * - 같은 모드 단추 다시 누르기는 시나리오에 넣지 않는다 — BU9b 가 눌린 단추를 잠가 그 요청(감사에 SHADOW→SHADOW)을 없앤다(사용자 결정).
 * - 접두 밖에서 더하는 읽기(관문 `/api/v1/admin/live-gate` · 연습용 `/macro/connection-status` · `/auth/me`)는 골든이 보지 않는다.
 *   ★`/api/v1/live/*` 에 새 읽기를 더하면 이 골든이 빨개진다★ — 그건 별도 결정이다.
 * - 다시 얼리기: UPDATE_REQUEST_GOLDEN=1 — ★화면 바꾸기 전에만★(BU9a).
 */

const G = (name: string) => path.join(__dirname, "golden", `${name}-requests.json`);
const act = (page: Page, a: string) => page.locator(`[data-act="${a}"]`);
type Step = { writes: string[]; reads?: string[] };

function split(entries: string[], keepReads: boolean): Step {
  const writes = entries.filter((e) => !e.startsWith("GET "));
  const reads = entries.filter((e) => e.startsWith("GET "));
  return keepReads ? { writes, reads } : { writes };
}

async function confirmIfAsked(page: Page, a: string, ms = 1_500) {
  const el = act(page, a).first();
  try { await el.waitFor({ state: "visible", timeout: ms }); } catch { return; }
  await el.click();
}

/** select 든 분할 단추든 — 값으로 고른다. */
async function pick(page: Page, a: string, value: string) {
  const el = act(page, a).first();
  const tag = await el.evaluate((n) => n.tagName);
  if (tag === "SELECT") await el.selectOption(value);
  else await el.locator(`[data-value="${value}"]`).click();
}

function compare(name: string, out: Record<string, Step>) {
  if (process.env.UPDATE_REQUEST_GOLDEN === "1") {
    fs.writeFileSync(G(name), JSON.stringify(out, null, 1) + "\n");
    return;
  }
  expect(out).toEqual(JSON.parse(fs.readFileSync(G(name), "utf8")));
}

// ── 실거래 ─────────────────────────────────────────────────────────────────

test("실거래 요청 골든: 모드·실계좌·비상 정지·풀기·새로 고침의 요청이 바이트 그대로", async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page, "admin");
  await routeConnection(page);
  await routeGate(page, { current: null, history: [] });
  const st = liveState();
  await routeLive(page, st);
  const rec = recordApi(page, "/api/v1/live/");
  const out: Record<string, Step> = {};
  const close = async (name: string, keepReads = true) => { await rec.step(name); out[name] = split(rec.steps[name], keepReads); };

  await page.goto("/admin/live-trading", { waitUntil: "domcontentloaded" });
  await expect(act(page, "mode-shadow")).toBeVisible({ timeout: 20_000 });
  await close("01 첫 화면");
  await act(page, "refresh").click();
  await close("02 새로 고침");
  await act(page, "mode-paper").click();
  await confirmIfAsked(page, "paper-yes");
  await close("03 모의 체결로");
  await expect.poll(() => st.mode).toBe("PAPER");
  await act(page, "mode-shadow").click();
  await close("04 기록만으로");
  await act(page, "mode-live").click();
  await act(page, "live-no").click();
  await close("05 실계좌 취소", false);
  await act(page, "mode-live").click();
  await act(page, "live-yes").click();
  await close("06 실계좌 확인");
  await act(page, "kill-open").click();
  await act(page, "kill-no").click();
  await close("07 비상 정지 취소", false);
  await act(page, "kill-open").click();
  await act(page, "kill-yes").click();
  await close("08 비상 정지 걸기");
  await expect(act(page, "resolve")).toBeVisible();
  await act(page, "resolve").click();
  await confirmIfAsked(page, "resolve-yes");
  await close("09 비상 정지 풀기");
  await page.waitForTimeout(11_000);
  await close("10 10초 뒤");

  expect(out["06 실계좌 확인"].writes.join(""), "실계좌는 확인 코드와 함께 나간다").toContain("EXPLICIT_LIVE_CONFIRMED");
  expect(out["05 실계좌 취소"].writes, "취소면 아무것도 보내지 않는다").toEqual([]);
  expect(out["08 비상 정지 걸기"].writes.join(""), "비상 정지는 보유를 그대로 둔다").toContain('"liquidation_mode":"hold"');
  expect(LIVE_REFUSED.length).toBeGreaterThan(0);
  compare("live-trading", out);
});

test("실거래 폴링 주기: 10초마다 한 번 다시 읽는다 (9초엔 아직, 10.5초엔 한 번 더)", async ({ page }) => {
  test.setTimeout(60_000);
  await signIn(page, "admin");
  await routeConnection(page);
  await routeGate(page, { current: null, history: [] });
  await routeLive(page, liveState());
  let modeReads = 0;
  page.on("request", (req) => { if (req.method() === "GET" && /\/api\/v1\/live\/mode$/.test(new URL(req.url()).pathname)) modeReads += 1; });
  await page.clock.install();
  await page.goto("/admin/live-trading", { waitUntil: "domcontentloaded" });
  await expect(act(page, "mode-shadow")).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => modeReads).toBe(1);
  await page.clock.runFor(9_000);
  await page.waitForTimeout(500);
  expect(modeReads, "10초가 되기 전엔 다시 읽지 않는다").toBe(1);
  await page.clock.runFor(1_500);
  await expect.poll(() => modeReads, { timeout: 5_000 }).toBe(2);
});

// ── 현실성 점검 ────────────────────────────────────────────────────────────

test("현실성 요청 골든: 처음엔 요청 0 · 계산하기는 전략을 읽고 두 계산을 같은 조건으로", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, "admin");
  await routeConnection(page);
  const st = realismState({ strategies: [] });
  await routeRealism(page, st);
  const rec = recordApi(page, ["/api/v1/multibacktest/", "/api/v1/realism/"]);
  const out: Record<string, Step> = {};
  const close = async (name: string) => { await rec.step(name); out[name] = split(rec.steps[name], true); };

  await page.goto("/admin/realism", { waitUntil: "domcontentloaded" });
  await expect(act(page, "calc")).toBeVisible({ timeout: 20_000 });
  await close("01 첫 화면");
  await act(page, "calc").click();
  await close("02 전략 없이 계산하기");
  st.strategies = MB_STRATEGIES;
  await expect(act(page, "calc")).toBeEnabled();
  await act(page, "calc").click();
  await close("03 계산하기");
  await expect(act(page, "calc")).toBeEnabled({ timeout: 20_000 });
  await act(page, "calc").click();
  await close("04 다시 계산하기");

  expect(out["01 첫 화면"], "처음엔 아무것도 묻지 않는다").toEqual({ writes: [], reads: [] });
  expect(out["02 전략 없이 계산하기"].writes, "전략이 없으면 계산을 보내지 않는다").toEqual([]);
  expect(out["03 계산하기"].writes).toHaveLength(2);
  compare("realism", out);
});

// ── 짝: 비교기는 공허하지 않다 ─────────────────────────────────────────────

test("짝: 골든 본문 하나만 바꿔도 다르다고 본다 (두 화면)", async () => {
  const bend = (name: string, step: string, from: RegExp, to: string) => {
    const want = JSON.parse(fs.readFileSync(G(name), "utf8")) as Record<string, Step>;
    const before = want[step].writes.join("\n");
    const bent: Record<string, Step> = { ...want, [step]: { ...want[step], writes: want[step].writes.map((w) => w.replace(from, to)) } };
    expect(bent[step].writes.join("\n"), `${name} ${step} 에 바꿀 글자가 있어야 짝이 성립한다`).not.toEqual(before);
    expect(bent).not.toEqual(want);
  };
  bend("live-trading", "08 비상 정지 걸기", /"hold"/, '"immediate"');
  bend("realism", "03 계산하기", /"initial_capital":\d+/, '"initial_capital":1000000000');
});
