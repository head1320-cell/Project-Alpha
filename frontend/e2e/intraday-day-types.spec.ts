import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 백테스트 › 분봉 규칙의 '하루 유형' 절 (T1 · 2026-11-16 · 구현 계획 §5.4)
// 분봉은 `e2e/fixtures/intraday/seed_day_types.py`(유형 넷을 심은 열이틀) · `seed_bars.py`(손 계산 열흘 · 합성 12일)가 심는다.
//  · 심은 자료: 005380 · 035420 · 2026-05-04 ~ 05-19 · 봉 다섯 · 첫 봉 시가 10,000 · 10bp = 10원 → 유형마다 표본 6개.
//      유형 1 = 내림 −10 … −50 · 유형 2 = V −10 −20 −30 −20 −10 · 유형 3 = 역V +10 +20 +30 +20 +10 · 유형 4 = 오름 +10 … +50.
//      같은 유형의 표본은 바이트로 같아 흩어짐 0.0bp · 난수 시드 다섯이 같은 배정 · 두 손실이 표시 자리에서 같다.
//  · 손 계산 열흘(035720 · 봉 넷) — 5분 구간이 모자라 전부 빠진다 → 학습 거절(쓸 수 있는 표본 0 · 필요한 표본 20).
//  · 합성 12일(005930 · 000660) — 합성 분봉으로 학습한 모형이라고 맨 위에 적는다.
// 거는 것: 학습 본문 = 폼 · 그림의 끝값과 표본 수 = 손 계산 · 읽는 줄 키보드 · 표 쌍둥이 전부 · 같은 입력은 같은 모형 ·
//  내 모형에서 고르면 그 모형 · 거절은 서버 사유와 뺀 표본의 사유 · 어긋난 칸은 보내지 않는다 · 실패는 재시도 ·
//  로그인 전에는 절이 없다 · 라이트/다크 AA · 문체 · 390px
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HERE = "/backtest/intraday";
const PLANTED = { tickers: "005380, 035420", from: "2026-05-04", to: "2026-05-19", minutes: "5", k: "4" };
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13", minutes: "5", k: "4" };
const SYNTH = { tickers: "005930, 000660", from: "2026-04-01", to: "2026-04-16", minutes: "30", k: "4" };
const EXCL = { tickers: "000270, 068270", from: "2026-06-01", to: "2026-06-17", minutes: "5", k: "4" };
const IS_TRAIN = (u: string, m: string) => u.includes("/intraday/day-types") && !u.match(/day-types\/[0-9a-f]{64}/) && m === "POST";

test.beforeAll(() => {
  for (const script of ["seed_bars.py", "seed_day_types.py"]) {
    execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", script)],
      { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
  }
});

async function login(page: Page): Promise<void> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
}

async function open(page: Page) {
  await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-dt-tickers")).toBeVisible();
  await expect(page.locator(".itd-dt-limits")).toContainText("유형 하나에 표본 5개 이상");      // 상한을 받은 뒤에만 학습할 수 있다
}

async function fill(page: Page, f: typeof PLANTED) {
  await page.locator(".itd-dt-tickers").fill(f.tickers);
  await page.locator(".itd-dt-from").fill(f.from);
  await page.locator(".itd-dt-to").fill(f.to);
  await page.locator(".itd-dt-minutes").fill(f.minutes);
  await page.locator(".itd-dt-k").fill(f.k);
}

async function train(page: Page) {
  const sent = page.waitForRequest((r) => IS_TRAIN(r.url(), r.method()));
  const got = page.waitForResponse((r) => IS_TRAIN(r.url(), r.request().method()));
  await page.locator(".itd-dt-train").click();
  const req = await sent;
  const res = await got;
  return { body: req.postDataJSON(), status: res.status(), json: await res.json() };
}

/** 규칙 기간의 바로 앞 같은 길이 — 화면의 계산과 따로(UTC 날짜 셈) 짓는다. */
function preceding(from: string, to: string): { from: string; to: string } {
  const day = 86_400_000;
  const at = (s: string) => Date.UTC(Number(s.slice(0, 4)), Number(s.slice(5, 7)) - 1, Number(s.slice(8, 10)));
  const span = (at(to) - at(from)) / day + 1;
  const end = at(from) - day;
  const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  return { from: iso(end - (span - 1) * day), to: iso(end) };
}

test("학습 기간의 처음 값은 규칙 설정 기간의 바로 앞 같은 길이다(학습한 날로 규칙을 판정하지 않게)", async ({ page }) => {
  await open(page);
  const from = await page.locator(".itd-from").inputValue();
  const to = await page.locator(".itd-to").inputValue();
  expect(from, "규칙 설정 기간이 비어 있으면 이 시험은 아무것도 보지 않는다").toMatch(/^\d{4}-\d{2}-\d{2}$/);
  const want = preceding(from, to);
  await expect(page.locator(".itd-dt-from")).toHaveValue(want.from);
  await expect(page.locator(".itd-dt-to")).toHaveValue(want.to);
  expect(want.to < from).toBe(true);
});

test("로그인 전에는 하루 유형 절이 없다(아무것도 묻지 않는다)", async ({ page }) => {
  let asked = 0;
  page.on("request", (r) => { if (r.url().includes("/intraday/day-types")) asked += 1; });
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-signed-out")).toBeVisible();
  await expect(page.locator(".itd-dt")).toHaveCount(0);
  expect(asked).toBe(0);
});

test("심은 네 유형 — 본문 = 폼 · 그림 = 손 계산 · 읽는 줄 · 표 쌍둥이 · 같은 입력은 같은 모형 · 목록에서 고르기", async ({ page }) => {
  await open(page);
  await fill(page, PLANTED);
  let listed = 0;                                                    // 학습 뒤 내 모형 목록을 다시 읽는다(DB 에 그 모형이 이미 있었든 없었든)
  page.on("request", (r) => { if (r.method() === "GET" && /\/intraday\/day-types(\?|$)/.test(r.url())) listed += 1; });
  const first = await train(page);
  expect(first.body).toEqual({ tickers: ["005380", "035420"], from: "2026-05-04", to: "2026-05-19", minutes: 5, k: 4 });
  expect(first.status).toBe(200);
  await expect.poll(() => listed).toBeGreaterThan(0);
  const key = first.json.model.key as string;
  const model = page.locator(".itd-dt-model");
  await expect(model).toHaveAttribute("data-key", key);
  await expect(model).toHaveAttribute("data-synthetic", "false");
  // 처음 학습인지는 E2E DB 에 남은 것에 달렸다 — 화면은 서버의 답과 같아야 한다
  await expect(page.locator(".itd-dt-reused")).toHaveCount(first.json.created ? 0 : 1);

  // 판 넷 · 표본 6개씩 · 끝값(손 계산)
  await expect(page.locator(".itd-dt-panel")).toHaveCount(4);
  for (const [type, end] of [["1", "−50.0bp"], ["2", "−10.0bp"], ["3", "+10.0bp"], ["4", "+50.0bp"]] as const) {
    const panel = page.locator(`.itd-dt-panel[data-type="${type}"]`);
    await expect(panel).toHaveAttribute("data-samples", "6");
    await expect(panel.locator(".itd-dt-end")).toHaveText(`끝 ${end}`);
    await expect(panel.locator(".itd-dt-samples")).toHaveText("표본 6개");
  }
  // ★모든 판이 같은 세로축★ — 기준선(0)의 높이가 판마다 같고 눈금 글자도 같다(판마다 축을 따로 잡으면 높낮이를 견줄 수 없다)
  const baseY = await page.locator(".itd-dt-panel .pf-baseline").evaluateAll((ls) => ls.map((l) => l.getAttribute("y1")));
  expect(baseY).toHaveLength(4);
  expect(new Set(baseY).size).toBe(1);
  for (const type of ["1", "2", "3", "4"]) {
    await expect(page.locator(`.itd-dt-panel[data-type="${type}"] .pf-ytick`)).toHaveText(["50.0", "−50.0", "0"]);
  }
  // 사실 줄 · 서버 글자 그대로
  const facts = page.locator(".itd-dt-facts");
  await expect(facts).toContainText("2026-05-04 ~ 2026-05-19 · 날 12일");
  await expect(facts).toContainText("첫 봉부터 5분");
  await expect(facts).toContainText("24개(종목 하나의 하루가 표본 하나)");
  await expect(facts).toContainText("09:00 24개");
  await expect(facts.locator(".itd-dt-excluded dd")).toHaveText("없음");
  await expect(page.locator(".itd-dt-loss")).toHaveText(first.json.model.loss.note);
  await expect(page.locator(".itd-dt-loss")).toContainText("표시 자리에서 같습니다.");
  await expect(page.locator(".itd-dt-agree [data-server]")).toHaveText("난수 시드 다섯이 같은 배정을 냈습니다.");
  await expect(page.locator(".itd-dt-agree")).toHaveAttribute("data-same", "true");
  await expect(page.locator(".itd-dt-ari")).toContainText("1235 1.00 · 1236 1.00 · 1237 1.00 · 1238 1.00");

  // 읽는 줄 — 처음은 마지막 분 · 키보드로 옮긴다
  const read = page.locator(".itd-dt-fig .cr-read");
  await expect(read.locator(".cr-head")).toHaveText("5분째");
  for (const t of ["유형 1 −50.0bp", "유형 2 −10.0bp", "유형 3 +10.0bp", "유형 4 +50.0bp"]) await expect(read).toContainText(t);
  await page.locator(".itd-dt-grid").focus();
  await page.keyboard.press("Home");
  await expect(read.locator(".cr-head")).toHaveText("1분째");
  for (const t of ["유형 1 −10.0bp", "유형 2 −10.0bp", "유형 3 +10.0bp", "유형 4 +10.0bp"]) await expect(read).toContainText(t);
  await page.keyboard.press("ArrowRight");
  await expect(read.locator(".cr-head")).toHaveText("2분째");
  for (const t of ["유형 1 −20.0bp", "유형 2 −20.0bp", "유형 3 +20.0bp", "유형 4 +20.0bp"]) await expect(read).toContainText(t);

  // 표 쌍둥이 — 분 다섯 × 유형 넷 전부
  const twin = page.locator(".itd-dt-fig details.cr-table");
  await twin.locator("summary").click();
  await expect(twin.locator("tbody tr")).toHaveCount(5);
  await expect(twin.locator("thead th")).toHaveText(["첫 봉부터", "유형 1", "유형 2", "유형 3", "유형 4"]);
  await expect(twin.locator("tbody tr").nth(2).locator("td")).toHaveText(["3분째", "−30.0bp", "−30.0bp", "+30.0bp", "+30.0bp"]);
  await expect(twin.locator("tbody tr").nth(3).locator("td")).toHaveText(["4분째", "−40.0bp", "−20.0bp", "+20.0bp", "+40.0bp"]);

  // 유형 표 — 표본 · 비중 · 끝값 · 최저 · 최고 · 흩어짐
  const rows = page.locator(".itd-dt-table tbody tr");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(1).locator("td").nth(0)).toHaveText("유형 2");
  await expect(rows.nth(1).locator("td")).toContainText(["유형 2", "6", "25.0%", "−10.0bp", "−30.0bp", "−10.0bp", "0.0bp"]);
  await rows.nth(0).locator("details summary").click();
  await expect(rows.nth(0).locator(".itd-dt-members li")).toHaveCount(6);

  // 주의 문장은 서버 문장 그대로 · ★새 절은 같은 화면의 E2E 고리 클래스를 쓰지 않는다★ — 분봉 규칙 스펙들이
  // `.itd-tickers` · `.itd-notes` 로 ★하나★를 찾는다(겹치면 그 스펙들이 엄격 모드에서 깨진다 — 실제로 깨졌던 것)
  await expect(page.locator(".itd-dt-notes li")).toHaveText(first.json.notes);
  await expect(page.locator(".itd-dt").locator(".itd-tickers, .itd-notes")).toHaveCount(0);
  await expect(page.locator(".itd-tickers")).toHaveCount(1);                       // 짝: 규칙 폼의 칸은 그대로 하나

  // 같은 입력을 다시 — 같은 열쇠 · 다시 학습하지 않았다고 말한다
  const again = await train(page);
  expect(again.json.created).toBe(false);
  expect(again.json.model.key).toBe(key);
  await expect(page.locator(".itd-dt-reused")).toHaveText("같은 표본 · 같은 설정의 모형이 이미 있어 그 모형을 보입니다. 다시 학습하지 않았습니다.");
  await expect(page.locator(`.itd-dt-pick[data-key="${key}"]`)).toHaveCount(1);

  // 새로 열고 내 모형에서 고르면 그 모형을 읽는다(하나 읽기 · 학습하지 않는다)
  await page.reload({ waitUntil: "domcontentloaded" });
  const pick = page.locator(`.itd-dt-pick[data-key="${key}"]`);
  await expect(pick).toContainText("2026-05-04 ~ 2026-05-19");
  await expect(pick).toContainText("5분 · 유형 4개 · 표본 24개");
  let trained = 0;
  page.on("request", (r) => { if (IS_TRAIN(r.url(), r.method())) trained += 1; });
  await pick.click();
  await expect(page.locator(".itd-dt-model")).toHaveAttribute("data-key", key);
  await expect(pick).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".itd-dt-panel")).toHaveCount(4);
  await expect(page.locator(".itd-dt-reused")).toHaveCount(0);
  expect(trained).toBe(0);
});

test("표본이 모자라면 서버 사유와 뺀 표본의 사유를 보이고 학습하지 않는다", async ({ page }) => {
  await open(page);
  await fill(page, HAND);
  const r = await train(page);
  expect(r.status).toBe(400);
  await expect(page.locator(".itd-dt-refused .tx-notice-t")).toHaveText("학습 거절");
  await expect(page.locator(".itd-dt-refused [data-server]").first()).toHaveText(r.json.detail.reason);
  await expect(page.locator(".itd-dt-count")).toHaveText("쓸 수 있는 표본 0개 · 필요한 표본 20개");
  const why = page.locator('.itd-dt-why li[data-reason="short_window"]');
  await expect(why).toContainText(r.json.detail.excluded.messages.short_window);
  await expect(why).toContainText("10개");
  await expect(page.locator(".itd-dt-model")).toHaveCount(0);
});

test("합성 분봉으로 학습한 모형은 맨 위에 그렇게 적고 목록에 표지를 단다", async ({ page }) => {
  await open(page);
  await fill(page, SYNTH);
  const r = await train(page);
  expect(r.status).toBe(200);
  const model = page.locator(".itd-dt-model");
  await expect(model).toHaveAttribute("data-synthetic", "true");
  await expect(model.locator(".tx-notice-t")).toHaveText("합성 분봉으로 학습한 모형입니다.");
  await expect(model.locator(".tx-notice [data-server]")).toHaveText(r.json.model.grade_reason);
  await expect(page.locator(`.itd-dt-pick[data-key="${r.json.model.key}"] .itd-dt-synth`)).toHaveText("합성");
  // 무작위 걸음 자료 — 손실 · 일치도 문장은 서버 글자 그대로(값은 고정하지 않는다)
  await expect(page.locator(".itd-dt-loss")).toHaveText(r.json.model.loss.note);
  await expect(page.locator(".itd-dt-agree [data-server]")).toHaveText(r.json.model.agreement.note);
  // 무작위 걸음에는 묶을 모양이 없다 — 난수 시드마다 배정이 달랐다(관측). 화면의 표지는 서버 값 그대로다(짝: 심은 자료는 'true')
  expect(r.json.model.agreement.same).toBe(false);
  await expect(page.locator(".itd-dt-agree")).toHaveAttribute("data-same", "false");
});

test("뺀 표본이 있는 모형 — 사실 줄에 사유마다 서버 문장과 수를 적는다(짝: 심은 네 유형은 '없음')", async ({ page }) => {
  await open(page);
  await fill(page, EXCL);
  const r = await train(page);
  expect(r.status).toBe(200);
  const ex = r.json.model.excluded;
  expect(ex.total).toBe(2);
  expect(ex.by_reason).toEqual({ short_window: 1, no_bars: 1 });
  const items = page.locator(".itd-dt-excluded li");
  await expect(items).toHaveCount(2);
  for (const code of ["short_window", "no_bars"]) {
    const li = page.locator(`.itd-dt-excluded li[data-reason="${code}"]`);
    await expect(li.locator("[data-server]")).toHaveText(ex.messages[code]);
    await expect(li).toContainText("1개");
  }
  const facts = page.locator(".itd-dt-facts");
  await expect(facts).toContainText("2026-06-01 ~ 2026-06-16 · 날 12일");       // 학습 기간은 쓰인 표본의 처음과 끝이다(요청의 끝 06-17 이 아니다)
  await expect(facts).toContainText("24개(종목 하나의 하루가 표본 하나)");
});

test("어긋난 칸은 보내지 않고 이유를 적는다 · 고치면 보낸다", async ({ page }) => {
  await open(page);
  await fill(page, { ...PLANTED, minutes: "4", k: "17" });
  let sent = 0;
  page.on("request", (r) => { if (IS_TRAIN(r.url(), r.method())) sent += 1; });
  await expect(page.locator(".itd-dt-train")).toBeDisabled();
  await expect(page.locator(".itd-dt-problems")).toContainText("분 수는 5 이상 120 이하의 정수여야 합니다.");
  await expect(page.locator(".itd-dt-problems")).toContainText("유형 수는 4 이상 16 이하의 정수여야 합니다.");
  await page.locator(".itd-dt-from").fill("2026-05-20");
  await expect(page.locator(".itd-dt-problems")).toContainText("시작일이 종료일보다 늦습니다.");
  expect(sent).toBe(0);
  await fill(page, PLANTED);
  await expect(page.locator(".itd-dt-problems")).toHaveCount(0);
  await expect(page.locator(".itd-dt-train")).toBeEnabled();
});

test("학습 요청이 실패하면 재시도 · 로그인이 끝났으면 다시 로그인하라고 한다", async ({ page }) => {
  await open(page);
  let mode: "500" | "401" | "pass" = "500";
  await page.route((u) => IS_TRAIN(u.toString(), "POST"), async (route) => {
    if (route.request().method() !== "POST" || mode === "pass") return route.continue();
    return route.fulfill({ status: Number(mode), contentType: "application/json", body: JSON.stringify({ detail: "실패를 흉내 낸 응답" }) });
  });
  await fill(page, PLANTED);
  await page.locator(".itd-dt-train").click();
  await expect(page.locator(".itd-dt .tx-notice-t").first()).toHaveText("요청 실패");
  await expect(page.locator(".itd-dt .tx-notice-b [data-server]").first()).toHaveText("실패를 흉내 낸 응답");
  mode = "pass";
  await page.locator(".itd-dt").getByRole("button", { name: "재시도" }).click();
  await expect(page.locator(".itd-dt-model")).toBeVisible();
  mode = "401";
  await page.locator(".itd-dt-train").click();
  await expect(page.locator(".itd-dt .tx-notice-t").first()).toHaveText("로그인 세션이 만료됐습니다.");
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 390px 에서 하루 유형 절이 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    await fill(page, PLANTED);
    await train(page);
    await expect(page.locator(".itd-dt-model")).toBeVisible();
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    const a = (await page.evaluate(contrastAudit(".itd-dt"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(60);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd-dt"))) as VoiceResult;
    expect(v.checked).toBeGreaterThan(40);
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    expect(v.titles).toBe(0);

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-dt-panel").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    const clipped = await page.evaluate(() => {
      const sec = document.querySelector<HTMLElement>(".itd-dt")!.closest<HTMLElement>(".tx-sec")!;
      const cs = getComputedStyle(sec);
      const right = sec.getBoundingClientRect().right - parseFloat(cs.paddingRight) + 1;
      const out: string[] = [];
      for (const el of sec.querySelectorAll<HTMLElement>("table, ul, dl, p, svg, li, td, th, span, b, label, input, textarea, button, figure")) {
        // 제 상자 안에서 스크롤하는 것(표 · 표 쌍둥이)은 뺀다 — 닫힌 표 쌍둥이도 크롬은 배치하므로 좌표가 잡힌다.
        if (!el.getClientRects().length || el.closest(".tj-scroll, .tj-scroll-x, .cr-scroll")) continue;
        if (el.getBoundingClientRect().right > right) out.push(`${el.tagName}.${el.className} :: ${(el.textContent ?? "").trim().slice(0, 24)}`);
      }
      return [...new Set(out)].slice(0, 12);
    });
    expect(clipped, `${theme} · 390px 에서 절 밖으로 나간 것`).toEqual([]);
  });
}
