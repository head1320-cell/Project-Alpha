import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page, type Request } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ══════════════════════════════════════════════════════════════════════════
// 괴리 보고 — 내 계좌 › 매매일지 '백테스트와 견주기' (★실제 서버★ — 계산을 가로채지 않는다)
// 설계 `docs/superpowers/specs/2026-11-14-paper-trading-monitor-design.md` §4
// ──────────────────────────────────────────────────────────────────────────
// 분봉은 `e2e/fixtures/intraday/seed_bars.py` 의 손으로 만든 열흘(035720 · 2026-03-02 ~ 03-13)이다.
// 규칙 '시가 범위 돌파 · 1분' · 진입 금액 100만원 · 슬리피지 1틱 → 시뮬레이션 체결은 날마다
//     09:02 매수 99주 @10,080 · 09:03 매도 99주 @10,100 (비용 전 하루 +1,980원 · 열흘 +19,800원).
// ★손 계산★ — 올린 체결이 양쪽 모두 한 틱(10원) 불리하면(09:02:40 매수 @10,090 · 09:03:20 매도 @10,090):
//     짝 스물 · 놓친 신호 0 · 규칙 밖 0 · 불리함 평균 +10원 = +1.0틱 · 실제 비용 전 0원 · 차이 −19,800원.
//     bp: 매수 10 ÷ 10,080 = 9.92bp · 매도 10 ÷ 10,100 = 9.90bp → 평균 9.9bp.
// 거는 것:
//  · 분봉 화면의 결과에서 매매일지로 가는 길 · 방금 돌린 설정이 목록 맨 위에 골라져 있다
//  · 서버로 가는 요청 = 그 설정 그대로 + 올린 줄 + 허용 시간(같은 설정이라 새 시행이 아니다)
//  · 판의 값 = 손 계산 · 창을 1분으로 줄이면 매수 스무 건이 아니라 … (시각이 같은 분이라 그대로 짝이다 — 창 표가 그 사실을 보인다)
//  · 늦은 체결은 '놓친 신호'와 '규칙 밖 매매'로 갈린다 ↔ 허용 시간을 넓히면 짝이 된다
//  · 다른 종목 · 기간 밖의 줄은 세어 적는다 · 시장 가정이 없으면 비용 후 차이는 0 이 아니라 N/A + 사유
//  · 돌린 백테스트가 없으면 어디서 돌리는지 안내 · 설정을 바꾸면 낡은 결과를 지운다 · 라이트/다크 AA · 문체
//  · 평균 ≠ 중앙값 ≠ 가장 불리한 체결(값이 갈리는 표본) · 짝이 없으면 N/A + 사유 · 시각 없는 파일은 하루 단위 + 사유
//  · 합성 분봉 위의 시뮬레이션이면 판 맨 위에 그렇게 적는다 ↔ 제공자 출처의 분봉이면 적지 않는다
//  · 시행을 기록하지 못하면 기록했다고 적지 않는다 · 색은 손익 칸에만(불리함 칸 · N/A 칸에는 없다)
//  · 목록에서 다른 백테스트를 고르면 그 설정으로 견준다
//  · ★순차 증거(부호 · G2)★ — 서버 문장 그대로: 불리 스물 = 평균_f (1 + f)^20 = 79,817.6(기준 20 이상) ↔ 불리 · 유리가 번갈면
//    최고 1.50 · 현재 0.26(못 미침 · "가정이 맞다는 뜻은 아닙니다") · 같은 체결뿐이면 e-값 1 · 짝이 없으면 줄이 없다
//    줄은 '물음 · 판정' 두 칸(질문 띠와 같은 꼴 · 어떤 물음에 답했는지 밝힌다) — 글자 왼쪽 끝이 위 사실 상자와 같은 세로줄이고, 390px 에서는 한 칸으로 쌓인다
// ══════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const MINUS = "−";
const JOURNAL = "/my-account/journal";
const INTRADAY = "/backtest/intraday";
const DAYS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"];
const HEAD = "체결일시,종목코드,매매구분,체결수량,체결단가";
/** 권고로 읽히는 낱말 — 괴리 판은 센 값만 말한다(설계 §8). */
const ADVICE = "추천|권장|권합니다|권고|바람직|올리십시오|낮추십시오|늘리십시오|줄이십시오|바꾸십시오|조정하십시오|고치십시오";

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

/** 날마다 매수 한 줄 · 매도 한 줄. */
const fillsCsv = (o: { buy?: number; sell?: number; buyAt?: string; sellAt?: string; extra?: string[] } = {}) =>
  [HEAD, ...DAYS.flatMap((d) => [
    `${d} ${o.buyAt ?? "09:02:40"},035720,매수,99,${o.buy ?? 10090}`,
    `${d} ${o.sellAt ?? "09:03:20"},035720,매도,99,${o.sell ?? 10090}`,
  ]), ...(o.extra ?? [])].join("\n") + "\n";

const csv = (text: string) => ({ name: "fills.csv", mimeType: "text/csv", buffer: Buffer.from(text, "utf-8") });

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

/** 내 시행 목록의 맨 위 줄(마지막으로 돌린 것) — 다른 시험이 같은 설정을 먼저 돌렸을 수 있어 실행 횟수는 서버에 묻는다. */
async function latestTrial(page: Page, token: string): Promise<{ runs: number; request: { tickers: string[]; from: string; to: string; costs: Record<string, unknown> } }> {
  const r = await page.request.get(`${API}/intraday/trials`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()).trials[0];
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);

/** 분봉 화면에서 손 계산의 그 설정을 한 번 돌린다(시행 한 줄이 남는다). */
async function runHandBacktest(page: Page, opts: { market?: boolean; ticker?: string; from?: string; to?: string } = {}) {
  await page.goto(INTRADAY, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await page.locator(".itd-tickers").fill(opts.ticker ?? "035720");
  await page.locator(".itd-from").fill(opts.from ?? "2026-03-02");
  await page.locator(".itd-to").fill(opts.to ?? "2026-03-13");
  await field(page, "minutes").fill("1");
  await field(page, "commission_bp").fill("1.5");
  if (opts.market !== false) {
    await field(page, "unknown_market").selectOption("KOSPI");
    await field(page, "unknown_instrument").selectOption("stock");
  }
  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
}

/** 매매일지에서 파일을 올리고 분석까지. */
async function analyze(page: Page, text: string) {
  await page.locator(".tj-file-input").setInputFiles(csv(text));
  await expect(page.locator(".tj-run")).toBeEnabled();
  await page.locator(".tj-run").click();
  await expect(page.locator(".tj-result")).toBeVisible();
  await expect(page.locator(".dv-compare")).toBeVisible();
}

async function compare(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/divergence") && r.method() === "POST");
  await page.locator(".dv-run").click();
  const req = await sent;
  await expect(page.locator(".dv-result")).toBeVisible({ timeout: 30_000 });
  return req;
}

const figure = (page: Page, label: string) => page.locator(".dv-result .tx-answer").getByText(label, { exact: true }).locator("xpath=..");
const windowRow = (page: Page, minutes: number) => page.locator(`.dv-windows tr[data-minutes="${minutes}"] > *`).allTextContents();
/** 순차 증거 줄의 글자 왼쪽 끝(px) — 열쇠 둘(물음 · 판정) · 값 둘 · 각주, 그리고 위 형제 사실 상자(`.dv-split`)의 글자 왼쪽 끝.
 *  상자 안에 안쪽 여백이 있는 상자가 또 들어가면 그 줄만 들여 쓰인다(스크린샷 검수에서 찾은 결함 — 이 값이 그것을 잡는다). */
const seqEdges = (page: Page) => page.evaluate(() => {
  const left = (el: Element) => Math.round(el.getBoundingClientRect().left);
  const split = document.querySelector(".dv-split")!;
  return {
    keys: [...document.querySelectorAll(".dv-seq .dv-seq-k")].map(left),
    question: left(document.querySelector(".dv-seq-question")!),
    verdict: left(document.querySelector(".dv-seq-verdict")!),
    note: left(document.querySelector(".dv-seq-note [data-server]")!),
    sibling: Math.round(split.getBoundingClientRect().left + parseFloat(getComputedStyle(split).paddingLeft)),
    overflow: (() => { const b = document.querySelector(".dv-seq")!; return b.scrollWidth - b.clientWidth; })(),
  };
});

test("분봉 결과에서 매매일지로 가는 길이 있고, 견준 값이 손 계산과 같다", async ({ page }) => {
  const token = await login(page);
  await runHandBacktest(page);
  const before = await latestTrial(page, token);
  expect(before.request.tickers).toEqual(["035720"]);
  await expect(page.locator(".itd-compare")).toContainText("매매일지");
  await page.locator(".itd-compare-go").click();
  await expect(page).toHaveURL(new RegExp(`${JOURNAL}$`));

  await analyze(page, fillsCsv());
  // 방금 돌린 설정이 맨 위에 골라져 있다
  const pickedText = await page.locator(".dv-trial").evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.textContent ?? "");
  expect(pickedText).toContain("035720");
  expect(pickedText).toContain("2026-03-02 ~ 2026-03-13");
  expect(pickedText).toContain(`${before.runs.toLocaleString("ko-KR")}회 실행`);
  await expect(page.locator(".dv-window")).toHaveValue("5");
  await expect(page.locator(".dv-rule-text")).toHaveText("진입 조건: 종가 상향 돌파 시가 범위 고가(1분) 또는 ((시가 범위 종료(1분) > 0.5 그리고 아님(직전 1봉 동안(시가 범위 종료(1분) > 0.5))) 그리고 종가 > 시가 범위 고가(1분))");   // 고른 백테스트의 규칙(서버가 낸 글)

  const req = await compare(page);
  const body = req.postDataJSON();
  expect(body.tickers).toEqual(["035720"]);
  expect([body.from, body.to]).toEqual(["2026-03-02", "2026-03-13"]);
  expect(body.rule.params.minutes).toBe(1);
  expect(body.costs.commission_bp).toBe(1.5);
  expect(body.costs.unknown_market).toBe("KOSPI");
  expect(body.window_minutes).toBe(5);
  expect(body.fills).toHaveLength(20);
  expect(body.fills[0]).toMatchObject({ executed_at: "2026-03-02 09:02:40", symbol: "035720", side: "buy", quantity: 99, price: 10090 });

  // ★판의 값 = 손 계산★
  await expect(page.locator(".dv-result .tx-answer")).toContainText("짝지은 20건의 체결가는 가정(슬리피지 1틱)보다 평균 1.0틱 불리했습니다.");
  await expect(figure(page, "짝지은 체결")).toContainText("20건");
  await expect(figure(page, "놓친 신호")).toContainText("0건");
  await expect(figure(page, "규칙 밖 매매")).toContainText("0건");
  await expect(page.locator(".dv-mean-won")).toHaveText("+10원");
  await expect(page.locator(".dv-mean-ticks")).toHaveText("+1.0틱");
  await expect(page.locator(".dv-mean-bp")).toHaveText("+9.9bp");
  await expect(page.locator(".dv-n-adverse")).toHaveText("20건");
  await expect(page.locator(".dv-n-favorable")).toHaveText("0건");
  await expect(page.locator(".dv-sim-gross")).toHaveText("+19,800원");
  await expect(page.locator(".dv-act-gross")).toHaveText("0원");
  await expect(page.locator(".dv-gap-gross")).toHaveText(`${MINUS}19,800원`);
  await expect(page.locator(".dv-sim-net")).toHaveText(`${MINUS}3,195원`);
  await expect(page.locator(".dv-pairs tbody tr")).toHaveCount(20);
  // ★순차 증거(부호) = 손 계산★ — 짝 스물이 모두 불리: 평균_f (1 + f)^20 = 79,817.6 → 기준 20 이상(서버 문장 그대로)
  await expect(page.locator(".dv-seq")).toHaveAttribute("data-passed", "");
  await expect(page.locator(".dv-seq-question")).toHaveText("가정한 체결보다 불리한 체결이 유리한 체결보다 체계적으로 잦은가");
  await expect(page.locator(".dv-seq-verdict")).toHaveText("순차 증거(부호)의 최고값이 기준 이상입니다. 최고 79,818 · 현재 79,818 · 기준 20(유의수준 5%). 가정한 체결보다 불리한 체결이 유리한 체결보다 체계적으로 잦다는 증거입니다.");
  await expect(page.locator(".dv-seq .dv-seq-k")).toHaveText(["물음", "판정"]);
  await expect(page.getByRole("group", { name: "순차 증거(부호)" })).toBeVisible();   // 이름표를 따로 달지 않는 대신 묶음의 접근 이름
  await expect(page.locator(".dv-seq [data-server]")).toHaveCount(4);              // 물음 · 판정 · 잰 방식 · 한계 — 넷 다 서버 글
  await expect(page.locator(".dv-seq")).toContainText("크기가 아니라 방향만 봅니다.");
  await expect(page.locator(".dv-seq")).toContainText("허용 시간을 바꿔 다시 본 횟수와 다른 파일을 올려 본 횟수는 세지 않습니다.");
  await expect(page.locator(".dv-seq")).not.toContainText("순차 증거(부호) 순차 증거(부호)");    // 이름표와 서버 문장이 같은 말로 겹치지 않는다
  // 글자의 세로줄: 열쇠 둘 = 각주 = 위 사실 상자의 글자 · 값 둘은 한 세로줄이고 열쇠 오른쪽(넓은 창은 두 칸)
  const wide = await seqEdges(page);
  expect(wide.keys).toEqual([wide.sibling, wide.sibling]);
  expect(wide.note).toBe(wide.sibling);
  expect(wide.verdict).toBe(wide.question);
  expect(wide.question).toBeGreaterThan(wide.sibling);
  expect(wide.overflow).toBeLessThanOrEqual(0);
  // 손으로 만든 열흘은 출처가 제공자(kis)로 적힌 분봉이다 → 합성이라는 말이 붙지 않는다(짝: 아래의 합성 분봉 시험)
  await expect(page.locator(".dv-synthetic")).toHaveCount(0);
  await expect(page.locator(".dv-result .tx-answer")).not.toContainText("합성 분봉");
  await expect(page.locator(".dv-result .tx-answer")).toContainText("허용 시간 5분 · 가정");
  await expect(page.locator(".dv-result")).toHaveAttribute("data-mode", "timed");
  // 색은 손익에만 입힌다 — 불리함 칸은 '+' 가 불리라서 등락 색을 입히면 부호와 색이 서로 다른 말을 한다
  await expect(page.locator(".dv-mean-won")).not.toHaveAttribute("data-dir", /.+/);
  await expect(page.locator(".dv-pairs tbody tr").first().locator("td[data-dir]")).toHaveCount(0);
  await expect(page.locator(".dv-sim-gross")).toHaveAttribute("data-dir", "up");
  await expect(page.locator(".dv-act-gross")).toHaveAttribute("data-dir", "flat");
  await expect(page.locator(".dv-gap-gross")).toHaveAttribute("data-dir", "down");
  await expect(page.locator(".dv-sim-net")).toHaveAttribute("data-dir", "down");
  // 같은 설정을 다시 돌린 것이다 — 새 시행이 아니다
  await expect(page.locator(".dv-trial[data-recorded]")).toContainText(`${(before.runs + 1).toLocaleString("ko-KR")}회째 실행`);
  expect((await latestTrial(page, token)).runs).toBe(before.runs + 1);
  await expect(page.locator(".dv-result .dv-trial")).not.toContainText("새 시행");
  await expect(page.locator(".dv-result .dv-trial")).toContainText("올린 체결은 서버에 저장하지 않습니다.");
  // 창 표 — 같은 분 안의 체결이라 1분에서도 짝이다
  expect(await windowRow(page, 1)).toEqual(["1분", "20건", "0건", "0건"]);
  expect(await windowRow(page, 5)).toEqual(["5분 · 이번 계산", "20건", "0건", "0건"]);
});

test("늦은 체결은 놓친 신호와 규칙 밖 매매로 갈리고, 허용 시간을 넓히면 짝이 된다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page);
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  // 매수가 7분 늦었다 · 규칙에 없던 매수 한 줄(13:00)을 더해 두 수가 서로 다르게 한다
  await analyze(page, fillsCsv({ buyAt: "09:09:00", buy: 10080, sell: 10100, sellAt: "09:03:00", extra: ["2026-03-03 13:00:00,035720,매수,5,10000"] }));

  await compare(page);
  await expect(figure(page, "짝지은 체결")).toContainText("10건");
  await expect(figure(page, "놓친 신호")).toContainText("10건");
  await expect(figure(page, "규칙 밖 매매")).toContainText("11건");
  expect(await windowRow(page, 5)).toEqual(["5분 · 이번 계산", "10건", "10건", "11건"]);
  expect(await windowRow(page, 15)).toEqual(["15분", "20건", "0건", "1건"]);
  await expect(page.locator(".dv-list-missed summary")).toHaveText("놓친 신호 10건");
  await expect(page.locator(".dv-list-offrule summary")).toHaveText("규칙 밖 매매 11건");
  // 목록의 줄은 제 쪽의 것이다: 놓친 신호 = 시뮬레이션의 시각(09:02) · 규칙 밖 매매 = 올린 체결의 시각(09:09 · 13:00)
  await expect(page.locator(".dv-list-missed tbody tr")).toHaveCount(10);
  await expect(page.locator(".dv-list-missed tbody tr").first()).toContainText("2026-03-02 09:02");
  await expect(page.locator(".dv-list-missed tbody tr").first()).toContainText("10,080원");
  await expect(page.locator(".dv-list-offrule tbody tr")).toHaveCount(11);
  await expect(page.locator(".dv-list-offrule tbody")).toContainText("2026-03-03 13:00");
  await expect(page.locator(".dv-list-offrule tbody tr").first()).toContainText("2026-03-02 09:09");

  // 설정을 바꾸면 낡은 결과를 지운다 → 다시 견주면 짝 스물
  await page.locator(".dv-window").selectOption("15");
  await expect(page.locator(".dv-result")).toHaveCount(0);
  const req = await compare(page);
  expect(req.postDataJSON().window_minutes).toBe(15);
  await expect(figure(page, "짝지은 체결")).toContainText("20건");
  await expect(figure(page, "규칙 밖 매매")).toContainText("1건");
  expect(await windowRow(page, 15)).toEqual(["15분 · 이번 계산", "20건", "0건", "1건"]);
  expect(await windowRow(page, 5)).toEqual(["5분", "10건", "10건", "11건"]);
  await expect(page.locator(".dv-time")).toContainText("최대 7분");
  await expect(page.locator(".dv-result .tx-answer")).toContainText("허용 시간 15분 · 가정");
});

test("평균 · 중앙값 · 가장 불리한 체결은 서로 다른 값이다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page);
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  // 하루(03-04)의 매수만 50원 비싸게: 불리함 = 10원 × 19건 + 50원 × 1건 → 평균 12원 · 중앙값 10원 · 가장 큰 것 50원
  const text = fillsCsv().replace("2026-03-04 09:02:40,035720,매수,99,10090", "2026-03-04 09:02:40,035720,매수,99,10130");
  expect(text).toContain("10130");
  await analyze(page, text);
  await compare(page);
  await expect(page.locator(".dv-result .tx-answer")).toContainText("평균 1.2틱 불리했습니다.");
  const row = (k: string) => page.locator(`.dv-gap tr[data-k="${k}"] > *`).allTextContents();
  expect(await row("mean")).toEqual(["평균", "+12원", "+1.2틱", "+11.9bp"]);          // bp = (9.9206×9 + 49.6032 + 9.9010×10) ÷ 20
  expect(await row("median")).toEqual(["중앙값", "+10원", "+1.0틱", "+9.9bp"]);
  expect(await row("worst")).toEqual(["가장 불리한 체결", "+50원", "+5.0틱", "+49.6bp"]);
  await expect(page.locator(".dv-split")).toContainText("가장 불리한 체결: 035720 2026-03-04 09:02 매수");
  // 실제 쪽 손익 = −40원 × 99주 = −3,960원 → 차이 = −3,960 − 19,800
  await expect(page.locator(".dv-act-gross")).toHaveText(`${MINUS}3,960원`);
  await expect(page.locator(".dv-gap-gross")).toHaveText(`${MINUS}23,760원`);
  await expect(figure(page, "비용 전 손익 차이")).toContainText(`${MINUS}23,760원`);
});

test("순차 증거는 방향만 센다 — 불리와 유리가 번갈면 기준에 못 미치고 그렇다고 적는다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page);
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  // 날마다 매수는 한 틱 불리(10,090 ↔ 10,080) · 매도는 한 틱 유리(10,110 ↔ 10,100) → 부호 +1, −1 이 열 번 번갈아 온다
  //   최고 = 첫 짝 뒤의 1 + 평균 f = 1.50 · 현재 = 평균_f (1 − f²)^10 = 0.26 → 기준 20 에 못 미친다
  await analyze(page, fillsCsv({ buy: 10090, sell: 10110 }));
  await compare(page);
  await expect(page.locator(".dv-n-adverse")).toHaveText("10건");
  await expect(page.locator(".dv-n-favorable")).toHaveText("10건");
  await expect(page.locator(".dv-seq")).toBeVisible();
  await expect(page.locator(".dv-seq")).not.toHaveAttribute("data-passed", /.*/);
  await expect(page.locator(".dv-seq-verdict")).toHaveText("순차 증거(부호)의 최고값이 기준에 못 미칩니다. 최고 1.50 · 현재 0.26 · 기준 20(유의수준 5%). 가정이 맞다는 뜻은 아닙니다. 증거가 아직 모자랄 수 있습니다.");
  await expect(page.locator(".dv-seq-question")).toHaveText("가정한 체결보다 불리한 체결이 유리한 체결보다 체계적으로 잦은가");
  // 평균 불리함은 0 원이다 — 크기의 평균과 방향의 증거는 다른 물음에 답한다
  await expect(page.locator(".dv-mean-won")).toHaveText("0원");
  // 390px: 두 칸이 한 칸으로 쌓인다 — 열쇠 · 값 · 각주가 모두 위 사실 상자의 글자와 같은 세로줄 · 옆으로 넘치지 않는다
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(async () => (await seqEdges(page)).question).toBe((await seqEdges(page)).sibling);
  const narrow = await seqEdges(page);
  expect(narrow.keys).toEqual([narrow.sibling, narrow.sibling]);
  expect([narrow.question, narrow.verdict, narrow.note]).toEqual([narrow.sibling, narrow.sibling, narrow.sibling]);
  expect(narrow.overflow).toBeLessThanOrEqual(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test("짝이 하나도 없으면 체결가 차이는 0 이 아니라 N/A 와 사유다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page);
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  await analyze(page, fillsCsv({ buyAt: "13:00:00", sellAt: "14:00:00" }));   // 시뮬레이션(09:02 · 09:03)과 몇 시간 떨어진 체결
  await compare(page);
  await expect(page.locator(".dv-result .tx-answer")).toContainText("짝지은 체결 없음");
  await expect(figure(page, "짝지은 체결")).toContainText("0건");
  await expect(figure(page, "놓친 신호")).toContainText("20건");
  await expect(figure(page, "규칙 밖 매매")).toContainText("20건");
  await expect(page.locator(".dv-none")).toContainText("N/A");
  await expect(page.locator(".dv-none")).toContainText("짝지은 체결이 없어 체결가 차이를 계산하지 못했습니다.");
  await expect(page.locator(".dv-gap")).toHaveCount(0);
  await expect(page.locator(".dv-time")).toHaveCount(0);
  await expect(page.locator(".dv-seq")).toHaveCount(0);                // 짝이 없으면 순차 증거 줄도 없다(1 이나 0 으로 적지 않는다)
  expect(await windowRow(page, 15)).toEqual(["15분", "0건", "20건", "20건"]);
  // 손익은 짝과 무관하게 양쪽을 따로 집계한다
  await expect(page.locator(".dv-gap-gross")).toHaveText(`${MINUS}19,800원`);
  await expect(page.locator(".dv-list-matched")).not.toHaveAttribute("open", "");
});

test("체결 시각이 없는 파일은 하루 단위로 견주고 그렇다고 적는다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page);
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  const text = [HEAD, ...DAYS.flatMap((d) => [`${d},035720,매수,99,10090`, `${d},035720,매도,99,10090`])].join("\n") + "\n";
  await analyze(page, text);
  const req = await compare(page);
  expect(req.postDataJSON().fills[0].executed_at).toBe("2026-03-02");
  await expect(page.locator(".dv-result")).toHaveAttribute("data-mode", "daily");
  await expect(page.locator(".dv-degraded")).toContainText("체결 시각이 없는 파일입니다.");
  await expect(page.locator(".dv-degraded")).toContainText("하루 단위로 견줬습니다");
  await expect(page.locator(".dv-result .tx-answer")).toContainText("하루 단위");
  await expect(page.locator(".dv-result .tx-answer")).not.toContainText("허용 시간");
  await expect(page.locator(".dv-windows")).toHaveCount(0);      // 허용 시간이 뜻을 갖지 않는다
  await expect(page.locator(".dv-time")).toHaveCount(0);
  await expect(page.locator(".dv-aside-untimed")).toHaveCount(0);
  await expect(figure(page, "짝지은 체결")).toContainText("20건");
  await expect(page.locator(".dv-mean-won")).toHaveText("+10원");
  // 하루 단위로 견줘도 순차 증거는 날짜 순의 짝으로 쌓는다(스물 모두 불리 — 기준 이상)
  await expect(page.locator(".dv-seq")).toHaveAttribute("data-passed", "");
  await expect(page.locator(".dv-seq-verdict")).toContainText("최고 79,818 · 현재 79,818 · 기준 20(유의수준 5%)");
});

test("합성 분봉 위의 시뮬레이션이면 판 맨 위에 그렇게 적는다", async ({ page }) => {
  const token = await login(page);
  await runHandBacktest(page, { ticker: "005930", from: "2026-04-01", to: "2026-04-16" });   // 모의 모드가 만든 합성 분봉의 날들
  expect((await latestTrial(page, token)).request.tickers).toEqual(["005930"]);
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  await analyze(page, [HEAD, "2026-04-01 09:10:00,005930,매수,1,70000", "2026-04-01 13:10:00,005930,매도,1,70100"].join("\n") + "\n");
  expect(await page.locator(".dv-trial").evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.textContent ?? "")).toContain("005930");
  await compare(page);
  await expect(page.locator(".dv-synthetic")).toContainText("합성 분봉 위의 시뮬레이션입니다.");
  await expect(page.locator(".dv-synthetic")).toContainText("실제 시세와 견준 결과가 아닙니다.");
  // 판에서 가장 먼저 보이는 것이 그 말이다(답 문장보다 먼저)
  expect(await page.locator(".dv-result").evaluate((el) => [...el.children].filter((c) => !c.classList.contains("tx-sr"))[0]?.className ?? "")).toContain("dv-synthetic");
  await expect(page.locator(".dv-result .tx-answer")).toContainText("합성 분봉");
});

test("목록에서 다른 백테스트를 고르면 그 설정으로 견준다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page);                                                                // 035720 · 손으로 만든 열흘
  await runHandBacktest(page, { ticker: "005930", from: "2026-04-01", to: "2026-04-16" });   // 뒤에 돌린 것이 맨 위다
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  await analyze(page, fillsCsv());
  const pickedText = () => page.locator(".dv-trial").evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.textContent ?? "");
  expect(await pickedText()).toContain("005930");
  const value = await page.locator(".dv-trial option").filter({ hasText: "035720 · 2026-03-02 ~ 2026-03-13" }).first().getAttribute("value");
  expect(value).toBeTruthy();
  await page.locator(".dv-trial").selectOption(value!);
  expect(await pickedText()).toContain("035720");
  const req = await compare(page);
  expect(req.postDataJSON().tickers).toEqual(["035720"]);
  expect([req.postDataJSON().from, req.postDataJSON().to]).toEqual(["2026-03-02", "2026-03-13"]);
  await expect(figure(page, "짝지은 체결")).toContainText("20건");
});

test("시행을 기록하지 못하면 기록했다고 적지 않는다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page);
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  await analyze(page, fillsCsv());
  // 저장소가 죽은 서버의 답 모양 그대로(서버 쪽은 pytest 가 건다) — 계산은 진짜 서버의 것을 쓴다
  await page.route("**/intraday/divergence", async (route) => {
    const res = await route.fetch();
    const json = await res.json();
    json.trial = { recorded: false, new: null, runs: null, family_n: null, user_total: null, reason: "store_unavailable",
                   message: "시행 기록을 읽거나 쓰지 못했습니다. 시행 횟수를 알 수 없어 보정하지 않았습니다." };
    await route.fulfill({ response: res, json });
  });
  await compare(page);
  await expect(figure(page, "짝지은 체결")).toContainText("20건");
  await expect(page.locator(".dv-result .dv-trial")).not.toHaveAttribute("data-recorded", "");
  await expect(page.locator(".dv-result .dv-trial")).toContainText("시행을 기록하지 못했습니다.");
  await expect(page.locator(".dv-result .dv-trial")).toContainText("시행 기록을 읽거나 쓰지 못했습니다.");
  await expect(page.locator(".dv-result .dv-trial")).not.toContainText("회째 실행");
  await expect(page.locator(".dv-result .dv-trial")).toContainText("올린 체결은 서버에 저장하지 않습니다.");
});

test("견주지 않은 줄은 세어 적고, 시장 가정이 없으면 비용 후 차이는 N/A 와 사유다", async ({ page }) => {
  await login(page);
  await runHandBacktest(page, { market: false });
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  await analyze(page, fillsCsv({ buy: 10080, sell: 10100, buyAt: "09:02:00", sellAt: "09:03:00", extra: [
    "2026-03-02 10:00:00,000660,매수,1,80000", "2026-03-02 10:30:00,000660,매도,1,81000",       // 규칙에 없는 종목
    "2026-02-20 09:02:00,035720,매수,99,10000",                                                  // 기간 밖
  ] }));
  await compare(page);
  await expect(figure(page, "짝지은 체결")).toContainText("20건");
  await expect(page.locator(".dv-mean-ticks")).toHaveText("0.0틱");
  await expect(page.locator(".dv-result .tx-answer")).toContainText("평균이 같았습니다");
  // 같은 체결뿐이면 순차 증거가 쌓이지 않는다(e-값 1 — 빈칸이나 0 이 아니다)
  await expect(page.locator(".dv-seq-verdict")).toHaveText("불리하거나 유리한 짝이 없어 순차 증거가 쌓이지 않았습니다(같은 체결 20건 · e-값 1). 가정이 맞다는 뜻은 아닙니다.");
  await expect(page.locator(".dv-aside-other")).toContainText("2줄");
  await expect(page.locator(".dv-aside-other")).toContainText("000660");
  await expect(page.locator(".dv-aside-outside")).toContainText("1줄");
  // 다른 종목의 손익(+1,000원)은 실제 쪽에 섞이지 않는다
  await expect(page.locator(".dv-act-gross")).toHaveText("+19,800원");
  await expect(page.locator(".dv-gap-gross")).toHaveText("0원");
  // ★미상 ≠ 0★ — 올린 줄에는 시장 구분이 없고 가정도 선언하지 않았다
  await expect(page.locator(".dv-act-net")).toHaveText("N/A");
  await expect(page.locator(".dv-gap-net")).toHaveText("N/A");
  await expect(page.locator(".dv-gap-net")).not.toHaveAttribute("data-dir", /.+/);
  await expect(page.locator(".dv-net-missing")).toContainText("비용 후 차이를 계산하지 못했습니다");
});

test("돌린 분봉 백테스트가 없으면 어디서 돌리는지 안내한다", async ({ page }) => {
  await login(page);
  // 관리자 계정에는 다른 시험이 남긴 시행이 있다 — 빈 목록은 서버의 답 모양 그대로 흉내 낸다(빈 목록의 서버 쪽은 pytest 가 건다).
  await page.route("**/intraday/trials", (route) => route.fulfill({ json: { available: true, reason: null, trials: [], unreadable: 0 } }));
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  await page.locator(".tj-file-input").setInputFiles(csv(fillsCsv()));
  await page.locator(".tj-run").click();
  await expect(page.locator(".tj-result")).toBeVisible();
  await expect(page.locator(".dv-no-trials")).toContainText("돌린 분봉 백테스트가 없습니다.");
  await expect(page.locator(".dv-no-trials a")).toHaveAttribute("href", INTRADAY);
  await expect(page.locator(".dv-run")).toHaveCount(0);
});

test("목록을 읽지 못하면 빈 목록이 아니라 사유다", async ({ page }) => {
  await login(page);
  await page.route("**/intraday/trials", (route) => route.fulfill({
    json: { available: false, reason: "시행 기록을 읽거나 쓰지 못했습니다. 시행 횟수를 알 수 없어 보정하지 않았습니다.", trials: [], unreadable: 0 },
  }));
  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  await page.locator(".tj-file-input").setInputFiles(csv(fillsCsv()));
  await page.locator(".tj-run").click();
  await expect(page.locator(".dv-compare")).toContainText("분봉 백테스트 목록을 읽지 못했습니다.");
  await expect(page.locator(".dv-compare")).toContainText("시행 기록을 읽거나 쓰지 못했습니다.");
  await expect(page.locator(".dv-no-trials")).toHaveCount(0);
  await expect(page.locator(".dv-run")).toHaveCount(0);
});

for (const theme of ["light", "dark"] as const) {
  test(`견주기 판 — ${theme === "dark" ? "다크" : "라이트"}에서 글자 대비와 문체`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await login(page);
    await runHandBacktest(page);
    await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
    await analyze(page, fillsCsv({ buyAt: "09:09:00" }));
    await compare(page);
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    for (const root of [".dv-compare", ".dv-result"]) {
      const a = (await page.evaluate(contrastAudit(root))) as AuditResult;
      expect(a.checked).toBeGreaterThan(root === ".dv-result" ? 60 : 8);
      expect(a.low, `${theme} ${root}`).toEqual([]);
      if (theme === "dark") expect(a.bright, "다크에 밝은 배경").toEqual([]);
      // 결과 판에는 권고 낱말이 없다(도구는 규칙을 추천하지 않는다 — 관측만). 견주기 절의 안내("규칙을 권하지 않습니다")는 부정문이라 결과 판에만 건다.
      const v = (await page.evaluate(voiceAudit(root, root === ".dv-result" ? ADVICE : ""))) as VoiceResult;
      expect(v.haeyo).toEqual([]);
      expect(v.dash).toEqual([]);
      expect(v.banned).toEqual([]);
    }
  });
}
