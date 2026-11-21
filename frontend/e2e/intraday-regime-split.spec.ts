import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════════════════════════
// 분봉 결과의 '시장 국면별로 나눠 보기' (K2a · 2026-11-17 · 구현 계획 §7.3)
// 실행은 ★실제 서버★다 — 손으로 만든 열흘(035720 · 2026-03-02 ~ 03-13 · `seed_bars.py`)을 손 계산의 그 설정으로 돌린다
// (하루 +1,980원 비용 전 · 수수료 1.5bp · 코스피 주식 가정 → 비용 뒤 열흘 −3,194.73원 · `intraday.spec.ts` 의 손 계산).
// 국면은 E2E 서버(mock 게이트)의 합성 지수 걸음이다 — 그래서 여기서 거는 것은 장치다:
//  · 국면 수는 비어서 시작하고 비어 있으면 묻지 않는다 · 물을 때는 ★방금 실행의 시행 열쇠★로 · 요청 = 폼(지수 · 국면 수)
//  · 국면별 표 · 미상 줄 · 합계 · 전환 · 한계 문장 = 서버 값(합계 = 손 계산의 열흘 그대로 — 국면별로 갈라질 뿐 바뀌지 않는다)
//  · 거래 수를 남기지 않은 옛 시행은 거래 · 승률이 N/A + 서버 사유(응답을 고쳐 심는다 — 그리기 계약만 · 서버의 셈은 pytest)
//  · 나누지 않은 까닭 · 거절은 서버 사유 그대로 · 실패는 재시도 · 시행을 기록하지 못한 실행이면 묻지 않는다
//  · 라이트/다크 AA · 문체 · 390px(표는 칸 글자를 쪼개지 않고 옆으로 넘긴다)
// ════════════════════════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HERE = "/backtest/intraday";
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const IS_SPLIT = (u: string) => /\/intraday\/trials\/[^/]+\/regime-split$/.test(new URL(u).pathname);
const IS_SIM = (u: string) => new URL(u).pathname.endsWith("/intraday/simulate");
const MINUS = "−";
const n = (v: number) => v.toLocaleString("ko-KR");
/** 화면의 손익 서식(`krFormat.signedWon`)과 같은 규칙 — 원 단위 반올림 · 늘 부호(빼기는 U+2212) · 0 이면 부호 없음. */
const won = (v: number) => { const r = Math.round(Math.abs(v)); return `${r === 0 ? "" : v < 0 ? MINUS : "+"}${n(r)}원`; };
/** 화면의 퍼센트 서식(`krFormat.pct`)과 같은 규칙 — 소수 한 자리 · 빼기는 U+2212. */
const pct = (p: number) => {
  const v = p * 100;
  return `${Number(Math.abs(v).toFixed(1)) === 0 ? "" : v < 0 ? MINUS : ""}${Math.abs(v).toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
};

type Part = { days: number; trades: number | null; wins: number | null; pnl: number; win_rate?: number | null };

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

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);

/** 손 계산의 그 설정으로 실행한다 — 시가 범위 돌파 1분 · 수수료 1.5bp · 코스피 주식으로 가정. 서버의 답(JSON)을 돌려준다. */
async function simulateHand(page: Page): Promise<{ trial: { trial_key: string | null } }> {
  await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await page.locator(".itd-tickers").fill(HAND.tickers);
  await page.locator(".itd-from").fill(HAND.from);
  await page.locator(".itd-to").fill(HAND.to);
  await field(page, "minutes").fill("1");
  await field(page, "commission_bp").fill("1.5");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
  const got = page.waitForResponse((r) => IS_SIM(r.url()) && r.request().method() === "POST");
  await page.locator(".itd-run").click();
  const js = await (await got).json();
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
  return js;
}

async function split(page: Page, k: string, index?: string) {
  if (index) await page.locator(".itd-rs-index").selectOption(index);
  await page.locator(".itd-rs-k").selectOption(k);
  const sent = page.waitForRequest((r) => IS_SPLIT(r.url()));
  const got = page.waitForResponse((r) => IS_SPLIT(r.url()));
  await page.locator(".itd-rs-run").click();
  const url = new URL((await sent).url());
  const res = await got;
  return { url, status: res.status(), js: await res.json() };
}

/** 응답을 고쳐 심는다 — 서버의 답을 받아 `change` 를 거친 몸으로 바꾼다(그리기 계약만 본다). */
async function plant(page: Page, change: (js: Record<string, unknown>) => void) {
  await page.route((u) => IS_SPLIT(u.toString()), async (route) => {
    const r = await route.fetch();
    const js = await r.json();
    change(js);
    await route.fulfill({ response: r, json: js });
  });
}

test("국면 수는 비어서 시작하고 비어 있으면 묻지 않는다 — 고르면 방금 실행의 시행 열쇠로 묻는다", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (IS_SPLIT(r.url())) asked.push(r.url()); });
  const sim = await simulateHand(page);
  const key = sim.trial.trial_key;
  expect(key, "전제 — 실행이 시행으로 남았다").toBeTruthy();
  await expect(page.locator(".itd-rs-k")).toHaveValue("");
  await expect(page.locator(".itd-rs-run")).toBeDisabled();
  await expect(page.locator(".itd-rs-problems")).toHaveText("국면 수를 고르십시오.");
  expect(asked).toEqual([]);
  const { url } = await split(page, "2", "KOSDAQ");
  expect(url.pathname).toBe(`${API}/intraday/trials/${key}/regime-split`);
  expect(Object.fromEntries(url.searchParams)).toEqual({ index: "KOSDAQ", k: "2" });
  await expect(page.locator(".itd-rs-result")).toHaveAttribute("data-index", "KOSDAQ");
});

test("국면별 표 · 미상 줄 · 합계 · 전환 · 한계 문장 = 서버 값 — 합계는 손 계산의 열흘 그대로", async ({ page }) => {
  await simulateHand(page);
  // 잰 값(E2E 서버의 합성 지수): 코스닥 · 국면 3개면 이 열흘이 국면 2(3일) · 국면 3(7일)로 갈리고 국면 1 은 0일이다.
  // 처음 고른 코스피 · 국면 3개는 열흘 모두 국면 2 라 나눔이 공허했다(아래 전제가 잡았다).
  const { js } = await split(page, "3", "KOSDAQ");
  const s = js.split as { states: (Part & { state: number; low_conf_days: number })[]; unknown: Part;
    total: Part & { low_conf_days: number }; transitions: number; trades_known: boolean; basis: string };
  expect(s, "전제 — 나눴다").not.toBeNull();
  expect(s.trades_known, "전제 — 새 실행은 날마다의 거래 수를 남긴다").toBe(true);
  // 합계 = 손 계산(열흘 · 하루 한 거래 · 비용 뒤 −3,194.73원 · 비용 뒤로는 이긴 거래 없음)
  expect([s.total.days, s.total.trades, s.total.wins, s.total.win_rate, s.basis]).toEqual([10, 10, 0, 0, "net"]);
  expect(s.total.pnl).toBeCloseTo(-3194.73, 2);
  expect(s.total.low_conf_days, "합계의 0.5 미만 = 국면들의 합").toBe(s.states.reduce((a, x) => a + x.low_conf_days, 0));
  const res = page.locator(".itd-rs-result");
  await expect(res).toHaveAttribute("data-k", "3");
  await expect(res).toHaveAttribute("data-trial-grade", js.trial_grade ?? "unknown");
  await expect(res).toHaveAttribute("data-regime-grade", js.regime_grade ?? "unknown");
  for (const st of s.states) {
    const td = page.locator(`.itd-rs-table tbody tr[data-state="${st.state}"] td`);
    await expect(td.nth(0)).toHaveText(`국면 ${st.state}`);
    await expect(td.nth(1)).toHaveText(`${n(st.days)}일`);
    await expect(td.nth(2)).toHaveText(`${n(st.low_conf_days)}일`);
    await expect(td.nth(3)).toHaveText(`${n(st.trades ?? -1)}건`);
    await expect(td.nth(4)).toHaveText(won(st.pnl));
    await expect(td.nth(5)).toHaveText(st.win_rate === null || st.win_rate === undefined ? "N/A" : pct(st.win_rate));
  }
  expect(s.states.filter((x) => x.days > 0).length, "전제 — 둘 이상의 국면에 날이 있다(나눔이 공허하지 않다)").toBeGreaterThan(1);
  // 국면 색은 번호의 표지 — 국면마다 다른 색(시장 국면 절과 같은 밝기 단계 · 순위가 아니다)
  const chips = page.locator(".itd-rs-table tbody tr[data-state] .itd-rs-chip:not(.itd-rs-chip--unknown)");
  const colors = await chips.evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
  expect(new Set(colors).size, "국면마다 다른 색").toBe(s.states.length);
  await expect(page.locator('.itd-rs-table tbody tr[data-state="unknown"]')).toHaveCount(s.unknown.days > 0 ? 1 : 0);
  const tot = page.locator('.itd-rs-table tfoot tr[data-state="total"] > *');
  await expect(tot.nth(0)).toHaveText("합계");
  await expect(tot.nth(1)).toHaveText(`${n(s.total.days)}일`);
  await expect(tot.nth(2)).toHaveText(`${n(s.total.low_conf_days)}일`);
  await expect(tot.nth(3)).toHaveText(`${n(s.total.trades ?? -1)}건`);
  await expect(tot.nth(4)).toHaveText(won(s.total.pnl));
  await expect(tot.nth(5)).toHaveText("0.0%");                                   // 손 계산: 비용 뒤로 이긴 거래 0 ÷ 10
  await expect(page.locator(".itd-rs-cap")).toContainText(`시행 거래일 ${n(s.total.days)}일 · 손익은 비용 뒤`);
  await expect(page.locator(".itd-rs-trans dd")).toHaveText(`${n(s.transitions)}번(국면이 있는 거래일끼리)`);
  await expect(page.locator(".itd-rs-notes li")).toHaveText(js.notes as string[]);
  await expect(page.locator(".itd-rs-trades-why")).toHaveCount(0);              // 짝 — 거래 수가 있으면 사유 줄이 없다
});

test("칸마다 서버 값 그대로 — 칸끼리 값이 다른 심은 답(거래일 ≠ 거래 · 0.5 미만 ≠ 거래일 · 비용 전 기준)", async ({ page }) => {
  // 손 계산 열흘은 하루 한 거래라 거래일 = 거래다 — 칸이 서로 바뀌어도 위 시험이 못 본다(변이 f01 이 살아남았다). 칸마다 다른 값을 심는다.
  await simulateHand(page);
  const why = "심은 사유: 적합 창이 덜 찼습니다.";
  await plant(page, (js) => {
    js.k = 2;
    js.empty = null;
    js.split = {
      basis: "gross",
      states: [
        { state: 1, days: 3, low_conf_days: 1, trades: 5, wins: 2, win_rate: 0.4, pnl: 1234 },
        { state: 2, days: 0, low_conf_days: 0, trades: 0, wins: 0, win_rate: null, pnl: 0 },
      ],
      unknown: { days: 2, trades: 1, wins: 0, win_rate: 0, pnl: -100, reasons: [{ reason: why, days: 2 }] },
      total: { days: 5, low_conf_days: 1, trades: 6, wins: 2, win_rate: 2 / 6, pnl: 1134 },
      transitions: 2, trades_known: true, trades_reason: null,
    };
  });
  await split(page, "2");
  const row = (st: string) => page.locator(`.itd-rs-table tr[data-state="${st}"] > *`);
  await expect(row("1")).toHaveText(["국면 1", "3일", "1일", "5건", "+1,234원", "40.0%"]);
  await expect(row("2")).toHaveText(["국면 2", "0일", "0일", "0건", "0원", "N/A"]);          // 거래 0 이면 승률은 N/A(0.0% 가 아니다)
  await expect(row("unknown")).toHaveText(["국면 미상", "2일", "N/A", "1건", `${MINUS}100원`, "0.0%"]);
  await expect(row("total")).toHaveText(["합계", "5일", "1일", "6건", "+1,134원", "33.3%"]);
  await expect(page.locator(".itd-rs-table thead th")).toHaveText(["국면", "거래일", "확률 0.5 미만", "거래", "손익(비용 전)", "승률"]);
  await expect(page.locator(".itd-rs-cap")).toContainText("시행 거래일 5일 · 손익은 비용 전");
  await expect(page.locator(".itd-rs-trans dd")).toHaveText("2번(국면이 있는 거래일끼리)");
  await expect(page.locator(".itd-rs-unknown li")).toHaveText([`국면 미상 2일 ${why}`]);
});

test("국면을 모르는 날은 '국면 미상' 줄과 사유별 날 수 — 0 이나 국면 1 로 세지 않는다", async ({ page }) => {
  await simulateHand(page);
  const why = "심은 사유: 그날의 지수 일봉이 없어 국면을 알 수 없습니다.";
  await plant(page, (js) => {
    const sp = js.split as { states: Part[]; unknown: Part & { reasons: { reason: string; days: number }[] } };
    const first = sp.states.find((x) => x.days > 0)!;              // 날이 있는 첫 국면에서 하루를 미상으로 옮긴다
    const perDay = first.pnl / first.days;
    first.days -= 1; first.pnl -= perDay; first.trades = (first.trades ?? 0) - 1;
    sp.unknown = { days: 1, trades: 1, wins: 0, win_rate: 0, pnl: perDay, reasons: [{ reason: why, days: 1 }] };
  });
  const { js } = await split(page, "2");
  const unknown = (js.split as { unknown: Part }).unknown;
  const row = page.locator('.itd-rs-table tbody tr[data-state="unknown"] td');
  await expect(row.nth(0)).toHaveText("국면 미상");
  await expect(row.nth(1)).toHaveText("1일");
  await expect(row.nth(2)).toHaveText("N/A");                                    // 그날 확률이 없다 — 0일이 아니다
  await expect(row.nth(3)).toHaveText("1건");
  await expect(row.nth(4)).toHaveText(won(unknown.pnl));
  await expect(row.nth(5)).toHaveText("0.0%");                                   // 서버 승률(거래 1 · 이긴 거래 0) — N/A 가 아니다
  await expect(page.locator(".itd-rs-unknown li")).toHaveText([`국면 미상 1일 ${why}`]);
});

test("거래 수를 남기지 않은 옛 시행은 거래 · 승률이 N/A 와 서버 사유 — 0 이 아니다", async ({ page }) => {
  await simulateHand(page);
  const reason = "심은 사유: 이 시행의 기록에는 날마다의 거래 수가 없습니다.";
  await plant(page, (js) => {
    const sp = js.split as Record<string, unknown> & { states: Part[]; unknown: Part & { reasons?: { reason: string; days: number }[] }; total: Part };
    const strip = (x: Part) => ({ ...x, trades: null, wins: null, win_rate: null });
    const first = sp.states.find((x) => x.days > 0)!;              // 미상 줄도 보이게 하루를 옮긴다(옛 시행의 미상 날)
    const perDay = first.pnl / first.days;
    first.days -= 1; first.pnl -= perDay;
    sp.unknown = { days: 1, trades: 0, wins: 0, win_rate: 0, pnl: perDay, reasons: [{ reason: "심은 사유: 국면 미상", days: 1 }] };
    Object.assign(sp, { trades_known: false, trades_reason: reason, states: sp.states.map(strip), unknown: strip(sp.unknown), total: strip(sp.total) });
  });
  const { js } = await split(page, "2");
  for (const st of (js.split as { states: (Part & { state: number })[] }).states) {
    const td = page.locator(`.itd-rs-table tbody tr[data-state="${st.state}"] td`);
    await expect(td.nth(3)).toHaveText("N/A");
    await expect(td.nth(4)).toHaveText(won(st.pnl));                              // 손익은 그대로 나뉜다
    await expect(td.nth(5)).toHaveText("N/A");
  }
  const unknownRow = page.locator('.itd-rs-table tbody tr[data-state="unknown"] td');
  await expect(unknownRow.nth(3)).toHaveText("N/A");
  await expect(unknownRow.nth(5)).toHaveText("N/A");                             // 짝 — 승률이 없으면 0% 가 아니라 N/A
  const totalRow = page.locator('.itd-rs-table tfoot tr[data-state="total"] > *');
  await expect(totalRow.nth(3)).toHaveText("N/A");
  await expect(totalRow.nth(5)).toHaveText("N/A");
  await expect(page.locator(".itd-rs-trades-why [data-server]")).toHaveText(reason);
});

test("등급 — 시행 · 국면 가운데 하나라도 합성이면 맨 위 알림 · 둘 다 실데이터면 없다 · 국면 등급 미상은 서버 사유", async ({ page }) => {
  await simulateHand(page);
  const { js } = await split(page, "2");
  // 잰 값(E2E 서버): 손으로 만든 열흘의 분봉은 실데이터 표시라 시행 등급 E3 · 국면은 합성 지수라 E0 — 국면 쪽만 합성이어도 알린다
  expect([js.trial_grade, js.regime_grade], "전제 — 두 등급이 다르다").toEqual(["E3", "E0"]);
  await expect(page.locator(".itd-rs-synth")).toHaveCount(1);
  await expect(page.locator(".itd-rs-head")).toContainText("시행 등급 E3 · 국면 등급 E0");
  await plant(page, (x) => { x.regime_grade = "E3"; x.coverage = { ok: true, reason: null }; });
  await split(page, "3");
  await expect(page.locator(".itd-rs-head")).toContainText("시행 등급 E3 · 국면 등급 E3");
  await expect(page.locator(".itd-rs-synth")).toHaveCount(0);                    // 짝 — 둘 다 실데이터면 알림이 없다
  await page.unroute((u) => IS_SPLIT(u.toString()));
  const why = "심은 사유: 일봉의 출처 표시가 없어 등급을 매기지 않았습니다.";
  await plant(page, (x) => { x.regime_grade = null; x.regime_grade_reason = why; x.coverage = { ok: true, reason: null }; });
  await split(page, "2");
  await expect(page.locator(".itd-rs-head")).toContainText("국면 등급 미상");
  await expect(page.locator(".itd-rs-grade [data-server]")).toHaveText(why);
  await expect(page.locator(".itd-rs-synth")).toHaveCount(0);                    // 미상은 합성이 아니다(알림으로 바꾸지 않는다)
});

test("나누지 않은 까닭은 서버 사유 그대로 · 거절도 서버 사유 · 실패는 재시도", async ({ page }) => {
  await simulateHand(page);
  const message = "심은 사유: 이 시행의 일별 손익이 거래일 수와 맞지 않아 나누지 않았습니다.";
  await plant(page, (js) => { js.split = null; js.empty = { reason: "flow_mismatch", message }; });
  await split(page, "2");
  await expect(page.locator('.itd-rs-empty[data-empty="flow_mismatch"] [data-server]')).toHaveText(message);
  await expect(page.locator(".itd-rs-table")).toHaveCount(0);
  await page.unroute((u) => IS_SPLIT(u.toString()));

  const refusal = "심은 거절: 그 시행을 찾지 못했습니다.";
  await page.route((u) => IS_SPLIT(u.toString()), (route) => route.fulfill({ status: 404, json: { detail: { code: "not_found", reason: refusal } } }));
  await page.locator(".itd-rs-k").selectOption("3");
  await page.locator(".itd-rs-run").click();
  await expect(page.locator(".itd-rs .tx-notice [data-server]")).toHaveText(refusal);
  await expect(page.locator(".itd-rs .tx-notice")).toContainText("요청 거절");
  // 거절(없는 시행)은 다시 물어도 같다 — 재시도 단추가 없다(짝: 아래 500 은 재시도가 있다 · 변이 f20 이 이 단언 없이 살아남았다)
  await expect(page.locator(".itd-rs").getByRole("button", { name: "재시도" })).toHaveCount(0);
  await page.unroute((u) => IS_SPLIT(u.toString()));

  let fail = true;
  await page.route((u) => IS_SPLIT(u.toString()), async (route) => {
    if (fail) { fail = false; await route.fulfill({ status: 500, json: { detail: "서버 오류" } }); } else await route.continue();
  });
  await page.locator(".itd-rs-k").selectOption("2");
  await page.locator(".itd-rs-run").click();
  const retry = page.locator(".itd-rs").getByRole("button", { name: "재시도" });
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(page.locator(".itd-rs-result")).toBeVisible();
});

test("로그인 만료(401)는 로그인 링크 — 돌아올 곳은 이 화면이고 재시도는 없다", async ({ page }) => {
  await simulateHand(page);
  await page.route((u) => IS_SPLIT(u.toString()), (route) => route.fulfill({ status: 401, json: { detail: "로그인이 필요합니다." } }));
  await page.locator(".itd-rs-k").selectOption("2");
  await page.locator(".itd-rs-run").click();
  const note = page.locator(".itd-rs .tx-notice").filter({ hasText: "로그인 세션이 만료됐습니다." });
  // 짝: 캔버스의 같은 판은 `/allocation` 으로 돌아온다(`canvas-intraday-regime.spec.ts`) — 돌아올 곳을 한 화면에 박으면 둘 중 하나가 깨진다
  await expect(note.locator("a")).toHaveAttribute("href", "/login?next=%2Fbacktest%2Fintraday");
  await expect(page.locator(".itd-rs").getByRole("button", { name: "재시도" })).toHaveCount(0);
  await expect(page.locator(".itd-rs-result")).toHaveCount(0);
});

test("시행을 기록하지 못한 실행이면 물을 열쇠가 없어 묻지 않는다", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (IS_SPLIT(r.url())) asked.push(r.url()); });
  await page.route((u) => IS_SIM(u.toString()), async (route) => {
    const r = await route.fetch();
    const js = await r.json();
    js.trial = { ...js.trial, recorded: false, trial_key: null, reason: "store_unavailable" };
    await route.fulfill({ response: r, json: js });
  });
  await simulateHand(page);
  await expect(page.locator(".itd-rs-no-trial")).toHaveText("이 실행은 시행으로 기록되지 않아 국면별로 나눌 수 없습니다.");
  await expect(page.locator(".itd-rs-k")).toHaveCount(0);
  expect(asked).toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 390px 에서 국면별 나눔 절이 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await simulateHand(page);
    await split(page, "3");
    const a = (await page.evaluate(contrastAudit(".itd-rs"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(20);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd-rs"))) as VoiceResult;
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    const rowH = () => page.locator(".itd-rs-table tbody tr").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
    const wide = await rowH();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-rs-result")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    expect(await rowH(), "좁은 폭에서 표의 칸 글자가 줄을 바꿨다").toEqual(wide);
    const scroll = page.locator(".itd-rs-scroll");
    expect(await scroll.evaluate((e) => e.scrollWidth > e.clientWidth)).toBe(true);    // 좁은 폭에서는 표가 옆으로 넘는다
    await scroll.focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => scroll.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0);
  });
}
