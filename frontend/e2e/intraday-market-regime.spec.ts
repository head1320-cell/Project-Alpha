import { expect, test, type Page } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 백테스트 › 분봉 규칙의 '시장 국면' 절 (K1 · 2026-11-17 · 구현 계획 §7.1)
// 지수 일봉은 E2E 서버(mock 게이트)의 합성 걸음이다 — 변동성이 일정한 걸음이라 국면이 없는 자료다. 그래서 여기서 거는 것은 장치다:
//  · 국면 수는 비어서 시작하고 비어 있으면 보내지 않는다 · 요청 = 폼(지수 · 국면 수 · 기간)
//  · 띠의 날 수 = 서버 날 수 · 날마다 가장 큰 국면 = 서버 · 읽는 줄 키보드(Home · End · ←→) · 표 쌍둥이 = 서버 값 전부
//  · 국면별 통계 · BIC · 일치도 · 전환 · 적합 줄 = 서버 값 · 한계 문장 = 서버 글자 그대로 · 합성 알림(서버 사유)
//  · 값이 없는 날은 0 이 아니라 '미상' + 사유(응답을 고쳐 심는다 — 그리기 계약만) · 거절은 서버 사유 · 실패는 재시도
//  · 라이트/다크 AA · 문체 · 390px
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const HERE = "/backtest/intraday";
/** 계산 문만 잡는다 — 상한 문(`/market-regime/limits`)은 절이 열릴 때 따로 부르므로 세지도 가로채지도 않는다. */
const MR_PATH = (u: URL) => u.pathname.endsWith("/intraday/market-regime");
const IS_MR = (u: string) => MR_PATH(new URL(u));
const pct = (p: number) => `${(p * 100).toFixed(1)}%`;
/** 일 로그 수익 평균의 서식(`format.dailyText`)과 같은 규칙 — 소수 두 자리 퍼센트 · 늘 부호(빼기는 U+2212) · 보이는 자릿수로 0 이면 부호 없음. */
const signed2 = (v: number) => {
  const r = Number(Math.abs(v * 100).toFixed(2));
  return `${r === 0 ? "" : v < 0 ? "\u2212" : "+"}${r.toFixed(2)}%`;
};
/** 화면의 숫자 서식(`krFormat.num`)과 같은 규칙 — 천 단위 쉼표 · 빼기 기호 U+2212 · 보이는 자릿수로 0 이면 부호 없음. */
const num = (v: number, d: number) =>
  `${Number(Math.abs(v).toFixed(d)) === 0 ? "" : v < 0 ? "\u2212" : ""}${Math.abs(v).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d })}`;

type Day = { date: string; probs: number[] | null; top: number | null; top_prob: number | null; reason: string | null };

async function login(page: Page): Promise<void> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
}

async function open(page: Page) {
  await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-mr-k")).toBeVisible();
}

async function run(page: Page, f: { index?: string; k: string; from: string; to: string }) {
  if (f.index) await page.locator(".itd-mr-index").selectOption(f.index);
  await page.locator(".itd-mr-from").fill(f.from);
  await page.locator(".itd-mr-to").fill(f.to);
  await page.locator(".itd-mr-k").selectOption(f.k);
  const sent = page.waitForRequest((r) => IS_MR(r.url()));
  const got = page.waitForResponse((r) => IS_MR(r.url()));
  await page.locator(".itd-mr-run").click();
  const url = new URL((await sent).url());
  const js = await (await got).json();
  await expect(page.locator(".itd-mr-result")).toBeVisible();
  return { params: Object.fromEntries(url.searchParams), js };
}

/**
 * 국면별 통계 표의 머리글이 ★낱말 가운데서★ 꺾인 자리 — 없어야 한다(keep-all 을 빼면 "평 / 균" · "변 / 동" · "연 / 율" — 잰 값 2026-11-19).
 * 글자마다 상자(Range)를 재어 앞 글자 상자의 아래보다 아래에서 시작하면 새 줄이다. 그 사이에 빈칸이 없고 새 줄이 여는 괄호로 시작하지 않으면 낱말 가운데다.
 * 짝: 실제로 줄이 바뀐 머리글이 있어야 한다(`wrapped` — 한 줄짜리만 보면 공허하다).
 */
const headerBreaks = (page: Page) => page.locator(".itd-mr-facts .itd-mr-states th").evaluateAll((els) => {
  const breaks: string[] = [];
  let wrapped = 0;
  for (const el of els) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let prev: { ch: string; bottom: number } | null = null, space = false, lines = 1;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const s = n.textContent ?? "";
      for (let i = 0; i < s.length; i++) {
        if (/\s/.test(s[i])) { space = true; continue; }
        const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1);
        const box = r.getClientRects()[0];
        if (!box) continue;
        if (prev && box.top >= prev.bottom - 2) {
          lines += 1;
          if (!space && s[i] !== "(") breaks.push(`${prev.ch}|${s[i]} · ${el.textContent ?? ""}`);
        }
        prev = { ch: s[i], bottom: box.bottom }; space = false;
      }
    }
    if (lines > 1) wrapped += 1;
  }
  return { breaks, wrapped };
});

/** BIC 값 셋(국면 2 · 3 · 4)이 BIC 칸의 오른쪽 끝을 넘지 않는다 — 넘으면 옆 칸을 덮거나(넓은 폭) 잘린다(좁은 폭). */
async function bicInside(page: Page) {
  const cell = await page.locator(".itd-mr-bic").boundingBox();
  expect(cell).not.toBeNull();
  for (const k of ["2", "3", "4"]) {
    const b = await page.locator(`.itd-mr-bic-k:has([data-k="${k}"])`).boundingBox();
    expect(b, `BIC ${k}`).not.toBeNull();
    expect(b!.x + b!.width, `BIC ${k} 가 칸을 넘었다`).toBeLessThanOrEqual(cell!.x + cell!.width + 0.5);
  }
}

test("국면 수는 비어서 시작하고 비어 있으면 보내지 않는다 — 고르면 폼 그대로 보낸다", async ({ page }) => {
  let sent = 0;
  page.on("request", (r) => { if (IS_MR(r.url())) sent += 1; });
  await open(page);
  await expect(page.locator(".itd-mr-k")).toHaveValue("");
  // 기간의 처음 값은 규칙 설정의 기간 그대로다(같은 날들의 국면을 본다) — 화면이 따로 날짜를 짓지 않는다
  await expect(page.locator(".itd-mr-from")).toHaveValue(await page.locator(".itd-from").inputValue());
  await expect(page.locator(".itd-mr-to")).toHaveValue(await page.locator(".itd-to").inputValue());
  await expect(page.locator(".itd-mr-run")).toBeDisabled();
  await expect(page.locator(".itd-mr-problems")).toContainText("국면 수를 고르십시오.");
  await page.locator(".itd-mr-from").fill("2026-03-31");
  await page.locator(".itd-mr-to").fill("2026-01-02");
  await page.locator(".itd-mr-k").selectOption("2");
  await expect(page.locator(".itd-mr-problems")).toContainText("시작일이 종료일보다 늦습니다.");
  await expect(page.locator(".itd-mr-run")).toBeDisabled();
  expect(sent).toBe(0);
  const { params } = await run(page, { k: "3", from: "2026-01-02", to: "2026-03-31" });
  expect(params).toEqual({ index: "KOSPI", k: "3", from: "2026-01-02", to: "2026-03-31" });
});

test("띠 · 읽는 줄 · 표 쌍둥이 · 통계 · BIC · 일치도 · 한계 문장 = 서버 값", async ({ page }) => {
  await open(page);
  const { js } = await run(page, { k: "3", from: "2026-01-02", to: "2026-03-31" });
  const days = js.days as Day[];
  // 전제 — 최소 · 평균 일치도가 갈리는 자료라야 아래 단언이 둘을 가린다(국면 2개는 이 자료에서 둘 다 1 이라 가리지 못했다)
  expect(js.agreement.min).not.toBe(js.agreement.mean);
  const res = page.locator(".itd-mr-result");
  await expect(res).toHaveAttribute("data-index", "KOSPI");
  await expect(res).toHaveAttribute("data-k", "3");
  await expect(res).toHaveAttribute("data-grade", "E0");
  await expect(page.locator(".itd-mr-synth [data-server]")).toHaveText(js.coverage.reason);
  // 띠 — 날마다 막대 하나 · 가장 큰 국면 = 서버
  const cells = page.locator(".itd-mr-day");
  await expect(cells).toHaveCount(days.length);
  expect(await cells.evaluateAll((els) => els.map((e) => [e.getAttribute("data-day"), e.getAttribute("data-top")])))
    .toEqual(days.map((d) => [d.date, d.top === null ? "unknown" : String(d.top)]));
  // 범례 = 그린 것만 — 값이 다 있는 날들이라 '미상' 줄이 없다(짝: 아래 코스닥 시험의 심은 미상 날)
  await expect(page.locator(".itd-mr-legend li")).toHaveText(["국면 1", "국면 2", "국면 3"]);
  // 번호의 근거는 어느 변동성인지까지 — '변동성이 낮은 것부터'만으로는 아래 표의 실현 변동성(그 기간의 일 수익) 순서로 읽힌다(K1b)
  await expect(page.locator(".itd-mr-axis")).toHaveText(
    "막대 하나가 하루입니다. 아래부터 국면 1 이며 번호는 적합 창에서 20거래일 실현 변동성의 평균이 낮은 국면부터 매겼습니다. "
    + "막대의 칸 높이가 그 국면의 소속 확률입니다.");
  // 읽는 줄 — 처음은 마지막 날 · Home · End · ←
  const fig = page.locator(".itd-mr-fig");
  const read = page.locator(".itd-mr-result .cr-read");
  await expect(read.locator(".cr-head")).toHaveText(days[days.length - 1].date);
  await fig.focus();
  await page.keyboard.press("Home");
  await expect(read.locator(".cr-head")).toHaveText(days[0].date);
  for (const [i, p] of (days[0].probs ?? []).entries()) await expect(read).toContainText(`국면 ${i + 1} ${pct(p)}`);
  await page.keyboard.press("ArrowRight");
  await expect(read.locator(".cr-head")).toHaveText(days[1].date);
  await page.keyboard.press("End");
  await expect(read.locator(".cr-head")).toHaveText(days[days.length - 1].date);
  // 표 쌍둥이 — 모든 날 × 모든 국면
  await page.locator(".itd-mr-result .cr-table summary").click();
  const rows = page.locator(".itd-mr-result .cr-table tbody tr");
  await expect(rows).toHaveCount(days.length);
  expect(await rows.first().locator("td").allTextContents())                      // 첫 칸은 날짜(표 쌍둥이의 머리)
    .toEqual([days[0].date, ...(days[0].probs ?? []).map(pct), `국면 ${days[0].top}`]);
  // 국면별 통계 · BIC · 일치도 · 전환 · 적합
  const st = page.locator(".itd-mr-states tbody tr");
  await expect(st).toHaveCount(3);
  type State = { state: number; days: number; share: number; mean_return: number; realized_vol: number };
  for (const [i, s] of (js.states as State[]).entries()) {
    expect([s.share, s.mean_return, s.realized_vol].every((v) => typeof v === "number"), "전제 — 국면마다 값이 있다").toBe(true);
    const td = st.nth(i).locator("td");
    await expect(td.nth(0)).toHaveText(`국면 ${s.state}`);
    await expect(td.nth(1)).toHaveText(`${s.days.toLocaleString("ko-KR")}일`);
    await expect(td.nth(2)).toHaveText(pct(s.share));                              // 비중
    await expect(td.nth(3)).toHaveText(signed2(s.mean_return));                    // 일 수익 평균(로그)
    await expect(td.nth(4)).toHaveText(pct(s.realized_vol));                       // 실현 변동성(연율)
  }
  for (const k of ["2", "3", "4"]) await expect(page.locator(`.itd-mr-bic [data-k="${k}"]`)).toHaveText(num(js.bic[k], 1));
  await expect(page.locator(".itd-mr-agree")).toContainText(`최소 ${num(js.agreement.min, 3)}`);
  await expect(page.locator(".itd-mr-agree")).toContainText(`평균 ${num(js.agreement.mean, 3)}`);
  await expect(page.locator(".itd-mr-trans")).toContainText(`${js.transitions}번`);
  // 적합 횟수는 '3번(달마다 한 번)' — '달마다 3번'은 한 달에 세 번으로 읽힌다(K1b)
  await expect(page.locator(".itd-mr-fit dd")).toHaveText(
    `${js.fit.refits}번(달마다 한 번) · 창 ${js.fit.window_days.toLocaleString("ko-KR")}거래일 · 시드 ${js.fit.seeds}개`
    + (js.fit.failed ? ` · 수렴하지 않은 시드 ${js.fit.failed}개` : ""));
  await expect(page.locator(".itd-mr-notes li")).toHaveText(js.notes as string[]);
});

test("코스닥을 고르면 코스닥으로 보낸다 · 값이 없는 날은 0 이 아니라 미상과 사유", async ({ page }) => {
  await open(page);
  const reason = "적합에 쓸 날이 모자랍니다. 필요 750일 · 있는 날 241일.";
  const planted = "심은 출처 사유입니다.";                                         // 화면이 서버의 출처 사유를 그대로 싣는지 — 심은 글자로 잰다
  await page.route(MR_PATH, async (route) => {
    const r = await route.fetch();
    const js = await r.json();
    js.days[0] = { ...js.days[0], probs: null, top: null, top_prob: null, reason };
    js.coverage = { ...js.coverage, reason: planted };
    await route.fulfill({ response: r, json: js });
  });
  const { params, js } = await run(page, { index: "KOSDAQ", k: "2", from: "2026-01-02", to: "2026-03-31" });
  expect(params.index).toBe("KOSDAQ");
  await expect(page.locator(".itd-mr-result")).toHaveAttribute("data-index", "KOSDAQ");
  await expect(page.locator(".itd-mr-result")).toContainText("코스닥");
  await expect(page.locator(".itd-mr-day").first()).toHaveAttribute("data-top", "unknown");
  await expect(page.locator(".itd-mr-legend li")).toHaveText(["국면 1", "국면 2", "미상"]);
  await expect(page.locator(".itd-mr-synth [data-server]")).toHaveText(planted);
  await page.locator(".itd-mr-fig").focus();
  await page.keyboard.press("Home");
  const read = page.locator(".itd-mr-result .cr-read");
  await expect(read.locator(".cr-head")).toHaveText((js.days as Day[])[0].date);
  await expect(read).toContainText("국면 1 N/A");                                   // 값 자리는 N/A — 0 이 아니다(용어집 §2)
  await expect(read).toContainText(`국면 미상 · ${reason}`);
});

test("합성 알림 — 서버의 출처 사유가 없으면 화면이 문장을 지어내지 않는다", async ({ page }) => {
  await open(page);
  await page.route(MR_PATH, async (route) => {
    const r = await route.fetch();
    const js = await r.json();
    js.coverage = { ...js.coverage, reason: null };
    await route.fulfill({ response: r, json: js });
  });
  await run(page, { k: "2", from: "2026-01-02", to: "2026-03-31" });
  const synth = page.locator(".itd-mr-synth");
  await expect(synth).toContainText("합성 지수 일봉입니다.");
  await expect(synth.locator("[data-server]")).toHaveCount(0);
});

test("거절은 서버 사유 · 실패는 재시도", async ({ page }) => {
  await open(page);
  await page.locator(".itd-mr-from").fill("2025-01-01");
  await page.locator(".itd-mr-to").fill("2026-01-02");
  await page.locator(".itd-mr-k").selectOption("2");
  const res = page.waitForResponse((r) => IS_MR(r.url()));
  await page.locator(".itd-mr-run").click();
  const body = await (await res).json();
  await expect(page.locator(".itd-mr .tx-notice [data-server]").first()).toHaveText(body.detail.reason);
  let fail = true;
  await page.route(MR_PATH, async (route) => {
    if (fail) { fail = false; await route.fulfill({ status: 500, json: { detail: "서버 오류" } }); } else await route.continue();
  });
  await page.locator(".itd-mr-from").fill("2026-01-02");
  await page.locator(".itd-mr-to").fill("2026-03-31");
  await page.locator(".itd-mr-run").click();
  const retry = page.locator(".itd-mr").getByRole("button", { name: "재시도" });   // 공용 RetryFail 의 단추
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(page.locator(".itd-mr-result")).toBeVisible();
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 390px 에서 시장 국면 절이 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    await run(page, { k: "3", from: "2026-01-02", to: "2026-03-31" });
    const a = (await page.evaluate(contrastAudit(".itd-mr"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(40);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd-mr"))) as VoiceResult;
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    const rowH = () => page.locator(".itd-mr-states tbody tr").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
    const wide = await rowH();
    await bicInside(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-mr-fig")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await bicInside(page);
    expect(await rowH(), "좁은 폭에서 통계 표의 칸 글자가 줄을 바꿨다").toEqual(wide);
    // 390px 에서는 머리글만 줄을 바꿔 다섯 칸이 가로 스크롤 없이 다 보인다(2026-11-19 받은 결정 — 그 전에는 351px 표가 270px 칸에서 옆으로 넘어 오른쪽 칸이 가려졌다 · 잰 값).
    const scroll = page.locator(".itd-mr-facts .itd-mr-scroll");
    expect(await scroll.evaluate((e) => e.scrollWidth <= e.clientWidth + 1), "390px 에서 국면별 통계 표가 옆으로 넘는다").toBe(true);
    const heads = await headerBreaks(page);
    expect(heads.breaks, "통계 표 머리글이 낱말 가운데서 꺾인 자리").toEqual([]);
    expect(heads.wrapped, "390px 에서 줄이 바뀐 머리글이 없다(공허한 검사)").toBeGreaterThan(0);
    // 더 좁은 폭(320px)에서는 여전히 옆으로 넘고(값 칸은 줄을 바꾸지 않는다), 넘는 상자는 키보드(Tab → ←→)로도 닿는다.
    await page.setViewportSize({ width: 320, height: 844 });
    expect(await rowH(), "320px 에서 통계 표의 칸 글자가 줄을 바꿨다").toEqual(wide);
    expect(await scroll.evaluate((e) => e.scrollWidth > e.clientWidth)).toBe(true);
    await scroll.focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => scroll.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0);
  });
}
