import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page, type Request } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 분봉 백테스트 — `/intraday` (★실제 서버★ — 계산을 가로채지 않는다. 설계 `docs/superpowers/specs/2026-11-14-intraday-minute-simulator-design.md`)
// ────────────────────────────────────────────────────────────────────────────
// 분봉은 `e2e/fixtures/intraday/seed_bars.py` 가 서버의 `MINUTE_BARS_DIR`(저장소 밖)에 심는다. 두 묶음:
//  · 손으로 만든 열흘(035720 · 2026-03-02 ~ 03-13 · 출처 열 `kis`) — ★화면의 값 = 손 계산★
//      봉 넷: 09:00 고 10,020 / 09:01 종 10,060 / 09:02 시 10,070 / 09:03 종 10,110. 규칙 '시가 범위 돌파 · 1분' + 진입 금액 100만원 + 슬리피지 1틱(10원):
//      09:01 종가가 첫 1분 고가를 넘는다 → 09:02 시가 10,070 + 10 = 10,080 에 99주(= 1,000,000 ÷ 10,080 내림) → 마지막 봉 종가 10,110 − 10 = 10,100 에 청산.
//      하루 +1,980원 × 10일 = 비용 전 +19,800원. 거래 대금 99 × (10,080 + 10,100) × 10 = 19,978,200원.
//      수수료 1.5bp = 2,996.73원 · 매도세 20bp × 999,900 × 10 = 19,998원 → 비용 후 −3,194.73원. 손익분기 9.9bp · 실제 11.5bp.
//      슬리피지 0틱 +39,600원 · 2틱 0원 · 비용 두 배(3bp · 2틱) 비용 후 −25,971.66원 · 표본외 3일 +5,940원 / −958.42원.
//  · 합성 12일(005930 · 000660 · 2026-04-01 ~ 04-16) — 모의 게이트의 수집기가 만든 것. ★합성 알림과 데이터 무결성 미달★을 본다.
// 거는 것:
//  · 로그인 전에는 아무것도 묻지 않는다 · 서버로 가는 본문 = 화면의 설정(비운 칸은 `null`)
//  · ★미상 ≠ 0★ — 시장 구분을 모르면 비용 후는 N/A + 서버 사유(짝: 가정을 고르면 값과 '가정' 표지)
//  · 관문 일곱의 상태·사유는 서버 값 그대로 · 미상은 통과가 아니다 · 종합 점수 없음
//  · 워크포워드는 ★미리 선언한 격자★만 · 격자가 어긋나면 보내지 않는다
//  · 합성이면 화면 맨 위에 적는다 · 분봉이 없으면 결과 대신 사유 · 설정을 바꾸면 낡은 결과를 지운다
//  · 시행 기록: 설정을 바꾸면 한 번 늘고, 같은 설정을 다시 돌리면 늘지 않는다
//  · 거절(400)은 서버 사유 그대로 · 실패(500)는 재시도 · 로그인 만료 · 라이트/다크 AA · 문체 · 390px
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const MINUS = "−";
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const SYNTH = { tickers: "005930, 000660", from: "2026-04-01", to: "2026-04-16" };

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

async function login(page: Page): Promise<void> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
}

async function open(page: Page) {
  await login(page);
  await page.goto("/intraday", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);
const kind = (page: Page, name: string) => page.locator(".itd-kinds").getByRole("radio", { name });

async function setData(page: Page, d: { tickers: string; from: string; to: string }) {
  await page.locator(".itd-tickers").fill(d.tickers);
  await page.locator(".itd-from").fill(d.from);
  await page.locator(".itd-to").fill(d.to);
}

/** 손 계산의 그 설정 — 시가 범위 돌파 1분 · 수수료 1.5bp · (고르면) 코스피 주식으로 가정. */
async function setHand(page: Page, opts: { market?: boolean; commission?: string | null } = {}) {
  await setData(page, HAND);
  await field(page, "minutes").fill("1");
  if (opts.commission !== null) await field(page, "commission_bp").fill(opts.commission ?? "1.5");
  if (opts.market !== false) {
    await field(page, "unknown_market").selectOption("KOSPI");
    await field(page, "unknown_instrument").selectOption("stock");
  }
}

async function run(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/simulate") && r.method() === "POST");
  await page.locator(".itd-run").click();
  const req = await sent;
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
  return req;
}

async function judge(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/validate") && r.method() === "POST");
  await page.locator(".itd-judge-btn").click();
  const req = await sent;
  await expect(page.locator(".itd-verdict")).toBeVisible({ timeout: 60_000 });
  return req;
}

const sum = (page: Page, k: string, side: "gross" | "net") => page.locator(`.tj-sum tr[data-k="${k}"] .tj-sum-${side}`);
const gate = (page: Page, key: string) => page.locator(`.itd-gate[data-gate="${key}"]`);
const chips = (page: Page, root: string) => page.locator(`${root} .tx-chip`);
/** 표의 한 줄(여럿이 맞으면 첫 줄) → 칸의 글자들(머리 칸 포함). */
const cells = (page: Page, row: string) => page.locator(row).first().locator(":scope > *").allTextContents();
const trialN = async (page: Page): Promise<number> => {
  const m = /기록된 시행 ([\d,]+)회/.exec(await page.locator(".itd-result .itd-trial").innerText());
  expect(m, "시행 횟수 문장").not.toBeNull();
  return Number(m![1].replace(/,/g, ""));
};

test("로그인 전에는 로그인하라고만 말한다 · 서버에 아무것도 묻지 않는다 · 메뉴에 '분봉 백테스트'", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/intraday/")) asked.push(r.url()); });
  await page.goto("/intraday", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-signed-out")).toContainText("로그인");
  await expect(page.locator(".itd-signed-out a")).toHaveAttribute("href", /\/login\?next=%2Fintraday/);
  await expect(page.locator('.nav-item[href="/intraday"]')).toContainText("분봉 백테스트");
  await expect(page.locator(".itd-tickers")).toHaveCount(0);
  expect(asked).toEqual([]);
});

test("설정 칸은 서버의 틀 목록 그대로 · 종목은 비어서 시작한다 · 틀을 바꾸면 매개변수가 새 틀의 출발값으로", async ({ page }) => {
  await open(page);
  await expect(page.locator(".itd-kinds").getByRole("radio")).toHaveText(
    ["시가 범위 돌파", "VWAP 상향 돌파", "변동성 돌파", "갭", "거래량 급증", "RSI", "볼린저 밴드"]);
  await expect(page.locator(".itd-tickers")).toHaveValue("");                       // 도구가 종목을 고르지 않는다
  await expect(field(page, "minutes")).toHaveValue("30");
  await expect(field(page, "amount")).toHaveValue("1000000");
  await expect(field(page, "commission_bp")).toHaveValue("");                       // 수수료율은 지어 넣지 않는다
  await expect(field(page, "slippage_ticks")).toHaveValue("1");
  await expect(field(page, "stop_pct")).toHaveValue("");
  await expect(page.locator(".itd-run")).toBeDisabled();
  await expect(page.locator(".itd-problems")).toContainText("종목코드를 하나 이상 입력하십시오.");

  await field(page, "minutes").fill("7");
  await kind(page, "RSI").click();
  await expect(field(page, "n")).toHaveValue("14");
  await expect(field(page, "oversold")).toHaveValue("30");
  await expect(page.locator('.itd-field[data-key="minutes"]')).toHaveCount(0);
  await kind(page, "시가 범위 돌파").click();
  await expect(field(page, "minutes")).toHaveValue("30");                           // 앞에서 넣은 7 을 끌고 오지 않는다
  await kind(page, "변동성 돌파").click();
  await expect(page.locator(".itd-needs-prev")).toContainText("전일 값");
});

test("적재 범위는 있는 그대로 — 어느 날 · 어떤 출처로 · 고른 종목 가운데 없는 것", async ({ page }) => {
  await open(page);
  await setData(page, { ...HAND, tickers: "035720, 005930" });
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/coverage?") && r.url().includes("tickers="));
  await page.locator(".itd-coverage-btn").click();
  const url = new URL((await sent).url());
  expect([url.searchParams.get("from"), url.searchParams.get("to"), url.searchParams.get("tickers")]).toEqual(["2026-03-02", "2026-03-13", "035720,005930"]);
  const read = page.locator(".itd-coverage-read");
  await expect(read).toContainText("2026-03-02 ~ 2026-03-13");
  await expect(read).toContainText("달력 12일 가운데 적재된 날 10일");
  await expect(read).toContainText("봉 40개");
  await expect(page.locator('.itd-sources [data-k="kis"] dd')).toHaveText("40행");
  await expect(page.locator('.itd-sources [data-k="synthetic"] dd')).toHaveText("0행");
  await expect(page.locator('.itd-sources [data-k="unknown"] dd')).toHaveText("0행");
  const loaded = page.locator('.itd-days tr[data-status="loaded"]');
  await expect(loaded).toHaveCount(10);
  expect(await cells(page, '.itd-days tr[data-status="loaded"]')).toEqual(["2026-03-02", "적재됨", "1", "4", "0", "005930"]);
  await expect(page.locator(".itd-banner")).toHaveCount(0);

  // 합성 기간을 물으면 화면 맨 위에 합성이라고 적는다(돌리기 전에도).
  await setData(page, SYNTH);
  await page.locator(".itd-coverage-btn").click();
  await expect(page.locator(".itd-coverage-read")).toContainText("2026-04-01 ~ 2026-04-16");
  await expect(page.locator('.itd-sources [data-k="kis"] dd')).toHaveText("0행");
  await expect(page.locator('.itd-sources [data-k="synthetic"] dd')).toHaveText(/^[1-9][\d,]*행$/);
  await expect(page.locator(".itd-banner .tx-notice-t")).toHaveText("합성 분봉: 장치 확인용이며 예측력·수익의 증거가 아닙니다.");
  await expect(page.locator('.itd-days tr[data-status="loaded"]')).toHaveCount(12);
  await expect(page.locator('.itd-days tr[data-status="loaded"]').first().locator("td").last()).toHaveText("없음");
});

test("손으로 만든 열흘: 화면의 값이 손 계산과 같다 · 서버로 가는 본문이 화면의 설정과 같다", async ({ page }) => {
  await open(page);
  await setHand(page);
  const req = await run(page);
  expect(req.postDataJSON()).toEqual({
    tickers: ["035720"], from: "2026-03-02", to: "2026-03-13",
    rule: { kind: "opening_range_breakout", params: { minutes: 1 } },
    position: { amount: 1_000_000, stop_pct: null, target_pct: null, trail_pct: null, time_exit: null, entry_from: null, entry_until: null,
                max_entries_per_ticker: 1, max_open_positions: null, daily_loss_limit: null, cooldown_after_loss_min: null },
    costs: { commission_bp: 1.5, slippage_ticks: 1, participation_cap: 0.1, unknown_market: "KOSPI", unknown_instrument: "stock" },
  });

  const answer = page.locator(".itd-result .tx-answer");
  await expect(answer.locator(".tx-answer-s")).toHaveText(`모의 거래 10건의 비용 후 실현손익 ${MINUS}3,195원`);
  expect(await answer.locator(".tx-fig").allInnerTexts().then((a) => a.map((s) => s.replace(/\s+/g, " ")))).toEqual(
    ["승률 0.0%", "손익비 N/A", `거래당 기대값 ${MINUS}319원`, "손익분기 비용(편도) 9.9bp"]);
  await expect(chips(page, ".itd-result .tx-answer")).toHaveText(["실제 분봉", "비용 후 기준", "수수료 가정 0.015%", "매도세 가정", "슬리피지 가정 1틱"]);
  await expect(page.locator(".itd-banner")).toHaveCount(0);

  await expect(page.locator(".itd-used-read")).toHaveText("거래일 10일 · 종목×일 10건 · 봉 40개 · 건너뛴 종목×일 0건");
  await expect(page.locator(".itd-origin")).toHaveAttribute("data-grade", "E3");
  await expect(page.locator(".itd-skipped")).toHaveCount(0);

  await expect(sum(page, "n", "gross")).toHaveText("10건");
  await expect(sum(page, "total", "gross")).toHaveText("+19,800원");
  await expect(sum(page, "total", "net")).toHaveText(`${MINUS}3,195원`);
  await expect(sum(page, "win_rate", "gross")).toHaveText("100.0%");
  await expect(sum(page, "win_rate", "net")).toHaveText("0.0%");                    // 비용이 이긴 거래를 전부 진 거래로 바꿨다
  await expect(sum(page, "expectancy", "gross")).toHaveText("+1,980원");
  await expect(page.locator('.tj-costs [data-k="fees"] dd')).toHaveText("2,997원");
  await expect(page.locator('.tj-costs [data-k="taxes"] dd')).toHaveText("19,998원");
  await expect(page.locator('.tj-costs [data-k="turnover"] dd')).toHaveText("19,978,200원");
  await expect(page.locator('.itd-breakeven [data-k="breakeven"] dd')).toHaveText("9.9bp");
  await expect(page.locator('.itd-breakeven [data-k="spent"] dd')).toHaveText("11.5bp");
  await expect(page.locator(".tj-trades tbody tr")).toHaveCount(10);

  // 이 화면의 '다루지 않는 것'은 시뮬레이터의 목록이다 — 매매일지의 '올린 파일' 이야기가 섞이지 않는다.
  const notCovered = page.locator(".tj-not-covered li");
  await expect(notCovered.first()).toContainText("호가");
  expect((await notCovered.allTextContents()).filter((s) => s.includes("파일"))).toEqual([]);
  await expect(page.locator(".itd-unknowns li")).toHaveCount(3);
  await expect(page.locator(".itd-result .itd-trial")).toHaveAttribute("data-recorded", "true");
  await expect(page.locator(".tj-basis")).toContainText("가정(지정한 시장) 10건");
});

test("★미상 ≠ 0★ 시장 구분을 모르면 비용 후는 N/A + 서버 사유 · 수수료율을 비우면 든 비용도 N/A (짝: 넣으면 값)", async ({ page }) => {
  await open(page);
  await setHand(page, { market: false });
  const req = await run(page);
  expect(req.postDataJSON().costs).toEqual({ commission_bp: 1.5, slippage_ticks: 1, participation_cap: 0.1, unknown_market: null, unknown_instrument: null });
  await expect(page.locator(".itd-result .tx-answer-s")).toHaveText("모의 거래 10건의 비용 전 실현손익 +19,800원");
  await expect(chips(page, ".itd-result .tx-answer")).toHaveText(["실제 분봉", "비용 전 기준", "수수료 가정 0.015%", "매도세 미상", "슬리피지 가정 1틱"]);
  await expect(sum(page, "total", "gross")).toHaveText("+19,800원");
  await expect(sum(page, "total", "net")).toHaveText("N/A");
  await expect(page.locator(".itd-result")).toContainText("종목의 시장·상품 구분을 알 수 없어 매도세를 계산하지 않았습니다.");
  await expect(page.locator('.itd-breakeven [data-k="breakeven"] dd')).toHaveText("9.9bp");      // 비용 전 값이라 알 수 있다
  await expect(page.locator('.itd-breakeven [data-k="spent"] dd')).toHaveText("N/A");
  await expect(page.locator(".itd-breakeven").locator("..")).toContainText("수수료율이나 매도세를 알 수 없어 실제로 든 비용은 산출하지 않았습니다.");

  // 판정도 비용을 모르는 채로는 통과시키지 않는다.
  await judge(page);
  await expect(gate(page, "costs")).toHaveAttribute("data-state", "unknown");
  await expect(gate(page, "cost_robustness")).toHaveAttribute("data-state", "unknown");
  expect((await cells(page, '.itd-slippage tr[data-ticks="1"]')).slice(0, 4)).toEqual(["1틱 · 지금 가정", "10건", "+19,800원", "N/A"]);

  // 짝: 가정을 고르면 값이 나오고 '가정'이라고 적힌다. 설정을 바꿨으니 앞의 결과는 지워진다.
  await field(page, "unknown_market").selectOption("KOSPI");
  await expect(page.locator(".itd-result")).toHaveCount(0);
  await expect(page.locator(".itd-verdict")).toHaveCount(0);
  await expect(page.locator(".tj-stale")).toHaveText("설정이 변경됐습니다. 재계산이 필요합니다.");
  await field(page, "unknown_instrument").selectOption("stock");
  await run(page);
  await expect(page.locator(".tj-stale")).toHaveCount(0);
  await expect(sum(page, "total", "net")).toHaveText(`${MINUS}3,195원`);
  await expect(chips(page, ".itd-result .tx-answer")).toContainText(["매도세 가정"]);

  // 수수료율을 비우면 0 으로 보지 않는다.
  await field(page, "commission_bp").fill("");
  await run(page);
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("비용 전 실현손익 +19,800원");
  await expect(chips(page, ".itd-result .tx-answer")).toContainText(["수수료 미상"]);
  await expect(sum(page, "total", "net")).toHaveText("N/A");
});

test("판정: 관문 일곱의 상태와 사유는 서버 값 그대로 · 표본외 · 슬리피지 민감도 · 두 배 비용", async ({ page }) => {
  await open(page);
  await setHand(page);
  await run(page);
  await expect(page.locator(".itd-verdict")).toHaveCount(0);                        // 실행만으로는 판정하지 않는다
  const req = await judge(page);
  expect(req.postDataJSON().walk_forward).toBeUndefined();                          // 격자를 선언하지 않았으면 워크포워드가 없다
  expect(req.postDataJSON().rule).toEqual({ kind: "opening_range_breakout", params: { minutes: 1 } });

  const verdict = page.locator(".itd-verdict");
  await expect(verdict.locator(".tx-answer-s")).toHaveText("관문 일곱 가운데 통과 2 · 미달 1 · 미상 4 입니다.");
  expect(await verdict.locator(".tx-answer .tx-fig").allInnerTexts().then((a) => a.map((s) => s.replace(/\s+/g, " ")))).toEqual(["통과 2", "미달 1", "미상 4"]);
  await expect(chips(page, ".itd-verdict .tx-answer")).toHaveText(["실제 분봉", "종합 점수 없음"]);
  const states = await page.locator(".itd-gate").evaluateAll((els) => els.map((el) => `${el.getAttribute("data-gate")}=${el.getAttribute("data-state")}`));
  expect(states).toEqual(["data_integrity=ok", "point_in_time=unknown", "costs=ok", "out_of_sample=unknown", "cost_robustness=degraded",
                          "multiplicity=unknown", "economic_value=unknown"]);
  // 상태는 색만으로 말하지 않는다 — 글자가 함께 간다.
  await expect(page.locator(".itd-gate .itd-gate-state")).toHaveText(["통과", "미상", "통과", "미상", "미달", "미상", "미상"]);
  await expect(gate(page, "out_of_sample").locator(".itd-gate-reason")).toHaveText("표본외 거래가 3건으로 30건에 못 미쳐 판단하지 않았습니다.");
  await expect(gate(page, "cost_robustness").locator(".itd-gate-reason")).toHaveText("비용을 두 배로 놓으면 거래당 기대값이 0 이하입니다.");
  await expect(gate(page, "multiplicity").locator(".itd-gate-reason")).toHaveText("거래일이 10일뿐입니다. 60일 이상이어야 확률을 산출합니다.");
  await expect(gate(page, "economic_value").locator(".itd-gate-reason")).toContainText("재지 않습니다");

  expect(await cells(page, '.itd-oos tr[data-k="in_sample"]')).toEqual(
    ["표본내 7일", "2026-03-02 ~ 2026-03-10", "7건", "+13,860원", `${MINUS}2,236원`, `${MINUS}319원`, "0.0%"]);
  expect(await cells(page, '.itd-oos tr[data-k="out_of_sample"]')).toEqual(
    ["표본외 3일", "2026-03-11 ~ 2026-03-13", "3건", "+5,940원", `${MINUS}958원`, `${MINUS}319원`, "0.0%"]);
  await expect(page.locator(".itd-oos-views")).toHaveText(/^이 표본외 구간을 [\d,]+번째 봅니다\./);

  expect(await cells(page, '.itd-slippage tr[data-ticks="0"]')).toEqual(["0틱", "10건", "+39,600원", "+16,585원", "+1,659원", "100.0%"]);
  expect(await cells(page, '.itd-slippage tr[data-ticks="1"]')).toEqual(["1틱 · 지금 가정", "10건", "+19,800원", `${MINUS}3,195원`, `${MINUS}319원`, "0.0%"]);
  expect(await cells(page, '.itd-slippage tr[data-ticks="2"]')).toEqual(["2틱", "10건", "0원", `${MINUS}22,975원`, `${MINUS}2,297원`, "0.0%"]);
  expect(await cells(page, '.itd-slippage tr[data-k="double"]')).toEqual(
    ["비용 두 배 · 수수료 3.0bp · 슬리피지 2틱", "10건", "0원", `${MINUS}25,972원`, `${MINUS}2,597원`, "0.0%"]);
  await expect(page.locator(".itd-walk")).toHaveCount(0);

  await expect(page.locator('.itd-mult [data-k="days"] dd')).toHaveText("10일");
  await expect(page.locator('.itd-mult [data-k="psr"] dd')).toHaveText("N/A");
  await expect(page.locator(".itd-mult-why")).toHaveText("거래일이 10일뿐입니다. 60일 이상이어야 확률을 산출합니다.");

  // 같은 판정을 다시 보면 표본외 구간을 본 횟수가 늘고, 두 번째부터는 표본외가 아니라고 말한다.
  const views = Number(/([\d,]+)번째/.exec(await page.locator(".itd-oos-views").innerText())![1].replace(/,/g, ""));
  await page.locator(".itd-judge-btn").click();
  await expect(page.locator(".itd-oos-views")).toHaveAttribute("data-views", String(views + 1));
  await expect(page.locator(".itd-oos-views")).toContainText("두 번째부터는 표본외가 아닙니다.");
  await expect(gate(page, "out_of_sample").locator(".itd-gate-facts")).toContainText("번째");
});

test("워크포워드: 미리 선언한 격자만 돌린다 · 고른 칸과 이어 붙인 결과 · 어긋난 격자는 보내지 않는다", async ({ page }) => {
  await open(page);
  await setHand(page);
  await run(page);
  await page.locator(".itd-grid-on input").check();
  // 값이 하나뿐인 격자 · 범위 밖의 값 · 구간 수 — 보내기 전에 말하고 단추가 꺼진다.
  await page.locator('[data-grid="rule.minutes"] input').fill("1");
  await expect(page.locator(".itd-grid-problems")).toContainText("격자에는 칸이 둘 이상 있어야 합니다.");
  await expect(page.locator(".itd-judge-btn")).toBeDisabled();
  await page.locator('[data-grid="rule.minutes"] input').fill("1, 500");
  await expect(page.locator(".itd-grid-problems")).toContainText("격자 범위를 재는 시간: 1~120분 범위로 입력하십시오.");
  await page.locator('[data-grid="rule.minutes"] input').fill("1, 2");
  await page.locator(".itd-folds").fill("1");
  await expect(page.locator(".itd-grid-problems")).toContainText("구간 수는 2~12의 정수로 입력하십시오.");
  await page.locator(".itd-folds").fill("2");
  await expect(page.locator(".itd-grid-problems")).toHaveCount(0);
  await expect(page.locator(".itd-grid-count")).toHaveText("격자 2칸 · 한 번에 12칸까지");

  const req = await judge(page);
  expect(req.postDataJSON().walk_forward).toEqual({ folds: 2, rule: { minutes: [1, 2] }, position: {} });
  expect(await cells(page, '.itd-cells tr[data-cell="0"]')).toEqual(
    ["1번 칸 · 지금 설정", "범위를 재는 시간 1", "10건", "+19,800원", `${MINUS}3,195원`, `${MINUS}319원`, "0.0%"]);
  // 2분 범위: 09:02 종가가 넘는다 → 마지막 봉 시가에 사서 그 봉 종가에 판다(슬리피지 뒤 같은 값) — 비용만 남는다.
  expect((await cells(page, '.itd-cells tr[data-cell="1"]')).slice(0, 4)).toEqual(["2번 칸", "범위를 재는 시간 2", "10건", "0원"]);
  const step = page.locator(".itd-steps tbody tr").first();
  await expect(step).toHaveAttribute("data-chosen", "0");
  expect(await step.locator("td").allTextContents()).toEqual(
    ["2026-03-02 ~ 2026-03-06", "1번 칸", "2026-03-09 ~ 2026-03-13", "5건", "+9,900원", `${MINUS}1,597원`, `${MINUS}319원`, "0.0%"]);
  expect(await cells(page, '.itd-steps tr[data-k="stitched"]')).toEqual(
    ["이어 붙인 결과(둘째 구간부터)", "5건", "+9,900원", `${MINUS}1,597원`, `${MINUS}319원`, "0.0%"]);
  await expect(page.locator(".itd-walk")).toContainText("시행");                     // 격자의 칸이 시행 횟수에 든다는 서버 주석

  // 격자를 고치면 앞의 판정만 지워지고 실행 결과는 남는다.
  await page.locator('[data-grid="rule.minutes"] input').fill("1, 3");
  await expect(page.locator(".itd-verdict")).toHaveCount(0);
  await expect(page.locator(".itd-result")).toBeVisible();
});

test("합성 분봉: 알림이 맨 위에 고정되고 결과와 판정이 합성이라고 말한다(데이터 무결성 미달)", async ({ page }) => {
  await open(page);
  await setData(page, SYNTH);
  await field(page, "commission_bp").fill("1.5");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
  await run(page);
  await expect(page.locator(".itd-banner .tx-notice-t")).toHaveText("합성 분봉: 장치 확인용이며 예측력·수익의 증거가 아닙니다.");
  await expect(chips(page, ".itd-result .tx-answer").first()).toHaveText("합성 분봉");
  await expect(page.locator(".itd-origin")).toHaveAttribute("data-grade", "E0");
  await expect(page.locator(".itd-origin")).toContainText("합성");
  await expect(page.locator(".itd-used-read")).toContainText("거래일 12일 · 종목×일 24건");

  await judge(page);
  await expect(page.locator(".itd-verdict .tx-answer-s")).toContainText("합성 분봉 위의 숫자이며 예측력이나 수익의 증거가 아닙니다.");
  await expect(chips(page, ".itd-verdict .tx-answer").first()).toHaveText("합성 분봉");
  await expect(gate(page, "data_integrity")).toHaveAttribute("data-state", "degraded");
  await expect(gate(page, "data_integrity").locator(".itd-gate-state")).toHaveText("미달");
  await expect(gate(page, "economic_value")).toHaveAttribute("data-state", "unknown");
  // 합성 위의 숫자로는 어느 관문도 '통과'라고만 읽히지 않게 — 알림은 판정 뒤에도 남는다.
  await expect(page.locator(".itd-banner")).toBeVisible();
});

test("분봉이 없는 기간: 결과 대신 서버 사유 · 판정 칸이 없다 · 일부만 없으면 사유와 함께 건너뛴다", async ({ page }) => {
  await open(page);
  await setData(page, { tickers: "035720", from: "2026-01-05", to: "2026-01-09" });
  await run(page);
  await expect(page.locator(".itd-result")).toHaveAttribute("data-empty", "not_loaded");
  await expect(page.locator(".itd-result")).toContainText("이 기간에 적재된 분봉이 없습니다.");
  await expect(page.locator(".itd-result .tx-answer")).toHaveCount(0);              // 빈 통계를 결과처럼 내지 않는다
  await expect(page.locator(".itd-judge-btn")).toHaveCount(0);

  // 고른 종목 가운데 하나만 분봉이 있다 — 없는 종목·일자를 세어 사유와 함께 적는다.
  await setData(page, { ...HAND, tickers: "035720, 005930" });
  await field(page, "minutes").fill("1");
  await run(page);
  await expect(page.locator(".itd-used-read")).toHaveText("거래일 10일 · 종목×일 10건 · 봉 40개 · 건너뛴 종목×일 10건");
  expect(await page.locator('.itd-skipped li[data-reason="no_bars"]').innerText()).toMatch(/^10건\s+이 날짜에 이 종목의 분봉이 없습니다\.$/);
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("모의 거래 10건");
});

test("보낼 수 없는 설정은 어느 칸인지 말하고 실행 단추가 꺼진다", async ({ page }) => {
  await open(page);
  const problems = page.locator(".itd-problems");
  await setData(page, HAND);
  await expect(page.locator(".itd-run")).toBeEnabled();
  await page.locator(".itd-tickers").fill(Array.from({ length: 31 }, (_, i) => String(100_000 + i)).join(" "));
  await expect(problems).toContainText("종목은 한 번에 30개까지입니다(지금 31개).");
  await page.locator(".itd-tickers").fill("035720, 035720\n035720");                 // 겹친 것은 한 번만
  await expect(page.locator("#itd-tickers-note")).toContainText("지금 1개");
  await expect(problems).toHaveCount(0);

  await field(page, "minutes").fill("121");
  await expect(problems).toContainText("범위를 재는 시간: 1~120분 범위로 입력하십시오.");
  await expect(field(page, "minutes")).toHaveAttribute("aria-invalid", "true");
  await field(page, "minutes").fill("");
  await expect(problems).toContainText("범위를 재는 시간: 값을 입력하십시오.");
  await field(page, "minutes").fill("1.5");
  await expect(problems).toContainText("범위를 재는 시간: 정수로 입력하십시오.");
  await field(page, "minutes").fill("5");
  await field(page, "time_exit").fill("2500");
  await expect(problems).toContainText("시간 청산: 시각은 네 자리 숫자(HHMM)로 입력하십시오.");
  await field(page, "time_exit").fill("1500");
  await field(page, "amount").fill("");
  await expect(problems).toContainText("진입 금액: 값을 입력하십시오.");
  await expect(page.locator(".itd-run")).toBeDisabled();
  await field(page, "amount").fill("1000000");
  await field(page, "stop_pct").fill("0");
  await expect(problems).toContainText("손절: 0.01~99% 범위로 입력하십시오.");
  await field(page, "stop_pct").fill("1.5");
  await expect(problems).toHaveCount(0);
  await expect(page.locator(".itd-run")).toBeEnabled();

  await page.locator(".itd-to").fill("2027-06-30");
  await expect(problems).toContainText("기간은 한 번에 366일까지입니다.");
  await expect(page.locator(".itd-run")).toBeDisabled();
});

test("시행 기록: 설정을 바꾸면 한 번 늘고 같은 설정을 다시 돌리면 늘지 않는다", async ({ page }) => {
  await open(page);
  await setHand(page);
  // 이 실행에서만 쓰는 진입 금액 — 기록에 없는 설정이어야 '새 시행'이다(로컬 DB 는 앞선 실행을 기억한다).
  const fresh = String(1_000_000 + (Date.now() % 900_000) + 1);
  await run(page);
  const before = await trialN(page);
  await field(page, "amount").fill(fresh);
  await run(page);
  expect(await trialN(page)).toBe(before + 1);
  await expect(page.locator(".itd-result .itd-trial")).not.toContainText("새 시행이 아님");
  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-result .itd-trial")).toContainText("같은 설정을 2번째 실행(새 시행이 아님)");
  expect(await trialN(page)).toBe(before + 1);
  await expect(page.locator(".itd-result .itd-trial")).toContainText("설정을 바꿔 다시 볼수록 좋아 보이는 결과가 우연히 나올 여지가 커집니다.");
});

test("거절은 서버 사유 그대로 · 실패는 재시도 · 로그인이 끝났으면 다시 로그인하라고 말한다", async ({ page }) => {
  await open(page);
  await setHand(page);
  let mode: "400" | "401" | "500" | "pass" = "400";
  const answer = (r: import("@playwright/test").Route) => mode === "pass" ? r.continue() : r.fulfill({
    status: Number(mode),
    json: { detail: mode === "400" ? { code: "too_much_data", reason: "읽을 분봉이 한 번에 볼 수 있는 양을 넘었습니다(시험)." }
      : mode === "401" ? "인증 토큰이 만료됐습니다." : "계산 실패(시험)" },
  });
  await page.route("**/api/v1/intraday/simulate", answer);
  await page.route("**/api/v1/intraday/validate", answer);

  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-run-fail .tx-notice-t")).toHaveText("실행 요청 거절");
  await expect(page.locator(".itd-run-fail")).toContainText("읽을 분봉이 한 번에 볼 수 있는 양을 넘었습니다(시험).");
  await expect(page.locator(".itd-run-fail").getByRole("button", { name: "재시도" })).toHaveCount(0);   // 같은 설정으로는 다시 거절된다
  await expect(page.locator(".itd-result")).toHaveCount(0);
  mode = "401";
  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-run-fail")).toContainText("로그인 세션이 만료됐습니다.");
  await expect(page.locator(".itd-run-fail a")).toHaveAttribute("href", /\/login\?next=%2Fintraday/);
  mode = "500";
  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-run-fail")).toContainText("계산 실패(시험)");
  mode = "pass";
  await page.locator(".itd-run-fail").getByRole("button", { name: "재시도" }).click();
  await expect(page.locator(".itd-result .tx-answer-s")).toContainText("모의 거래 10건");

  mode = "500";
  await page.locator(".itd-judge-btn").click();
  await expect(page.locator(".itd-judge-fail")).toContainText("계산 실패(시험)");
  await expect(page.locator(".itd-verdict")).toHaveCount(0);
  await expect(page.locator(".itd-result")).toBeVisible();                          // 판정이 실패해도 실행 결과는 남는다
  mode = "400";
  await page.locator(".itd-judge-fail").getByRole("button", { name: "재시도" }).click();
  await expect(page.locator(".itd-judge-fail .tx-notice-t")).toHaveText("판정 요청 거절");
  mode = "pass";
  await page.locator(".itd-judge-btn").click();
  await expect(page.locator(".itd-verdict .tx-answer-s")).toContainText("관문 일곱 가운데");
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 좁은 화면에서 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    // 합성 기간 — 알림 · 미달 · 미상 · 통과가 한 화면에 다 나온다.
    await setData(page, SYNTH);
    await page.locator(".itd-coverage-btn").click();
    await expect(page.locator(".itd-coverage-read")).toContainText("2026-04-01");
    await field(page, "commission_bp").fill("1.5");
    await field(page, "unknown_market").selectOption("KOSPI");
    await field(page, "unknown_instrument").selectOption("stock");
    await run(page);
    await page.locator(".itd-grid-on input").check();
    await page.locator(".itd-folds").fill("2");
    await page.locator('[data-grid="rule.minutes"] input').fill("15, 30");
    await judge(page);
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);

    const a = (await page.evaluate(contrastAudit(".itd"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(200);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd"))) as VoiceResult;
    expect(v.checked).toBeGreaterThan(150);
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    expect(v.titles).toBe(0);

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-verdict")).toBeVisible();
    const over = await page.evaluate(() => {
      const root = document.querySelector(".itd") as HTMLElement;
      const w = document.documentElement.clientWidth;
      return [...root.querySelectorAll<HTMLElement>(".tx-sec, .tx-answer, .tx-notice, .tj-curve")].filter((el) => el.getBoundingClientRect().right > w + 1)
        .map((el) => el.className);
    });
    expect(over).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    // ★잘림★ — 제 상자 안에서 스크롤하는 것(`.tj-scroll` · `.tj-scroll-x` · 탭 줄)을 빼면 전부 절의 안쪽 폭에 들어와야 한다.
    const clipped = await page.evaluate(() => {
      const out: string[] = [];
      for (const sec of document.querySelectorAll<HTMLElement>(".itd .tx-sec, .itd .tx-answer")) {
        const cs = getComputedStyle(sec);
        const right = sec.getBoundingClientRect().right - parseFloat(cs.paddingRight) + 1;
        for (const el of sec.querySelectorAll<HTMLElement>("table, ul, ol, dl, p, svg, li, td, th, span, b, label, input, select, textarea, button")) {
          if (!el.getClientRects().length || el.closest(".tj-scroll, .tj-scroll-x, .tj-bucket-list, .tx-tablist, .tx-sr, .tx-seg")) continue;
          if (el.getBoundingClientRect().right > right) out.push(`${el.tagName}.${el.className} :: ${(el.textContent ?? "").trim().slice(0, 24)}`);
        }
      }
      return [...new Set(out)].slice(0, 12);
    });
    expect(clipped, `${theme} · 390px 에서 절 밖으로 나간 것`).toEqual([]);
  });
}
