import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page, type Request } from "./fixtures";
import { voiceAudit, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 분할 창(G5 · 작업 공간 1단계) — 백테스트 › 분봉 규칙의 '설정 | 결과와 분석' 두 칸 (계획 문서 §6 · ★실제 서버★)
// ────────────────────────────────────────────────────────────────────────────
// 거는 것:
//  · 가로 1280px 이상이고 세로 800px 이상일 때만 두 칸 — 왼쪽 설정 · 오른쪽 결과와 분석 · ★페이지는 구르지 않고 두 칸이 각자 구른다★
//  · 실행 줄은 왼쪽 칸 바닥에 붙어 칸을 굴려도 늘 보인다 · 합성 알림은 두 칸 밖 위에 선다(결과 칸을 굴려도 그 자리)
//  · 구분선: 이름 '설정 창 폭' · ←/→ 16px · Home 최소 440 · End 최대(작업 칸 − 16 − 640) · 끌기 · aria 값 = 그린 폭 · Enter 로 접기
//  · '설정 접기' ↔ '설정 펴기'(aria-expanded) · 폭과 접힘은 브라우저에 남고, 꼴이 틀린 저장은 기본값(480 · 펼침)
//  · 창을 줄이면 그 폭의 최대로 clamp 하고 다시 넓히면 선호 폭이 돌아온다
//  · 실행하면 결과 칸을 맨 위로 · 설정을 바꾸면 결과를 지우고 그렇게 말한다 · 판정도 결과 칸
//  · ★짝★ 한 열(1280 × 720 · 1440 × 780 · 1200 × 900 · 390 × 844): 구분선 · 단추 · 빈 칸 문장이 없고 지금처럼 위아래로 쌓인다(칸 사이 12px)
// 데이터는 다른 분봉 스펙과 같은 고정물(seed_bars.py) — 손 계산 열흘 035720 · 합성 사흘 005930 · 000660.
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";
const HERE = "/backtest/intraday";
const KEY = "itd.split";
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const SYNTH = { tickers: "005930, 000660", from: "2026-04-01", to: "2026-04-03" };
const WIDE = { width: 1440, height: 900 };
const HUGE = { width: 1920, height: 1080 };

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

async function open(page: Page, viewport = WIDE): Promise<void> {
  await page.setViewportSize(viewport);
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeAttached();
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);
const bar = (page: Page) => page.locator(".itd-split-bar");
const toggle = (page: Page) => page.locator(".itd-set-toggle");
const box = async (page: Page, sel: string) => {
  const b = await page.locator(sel).first().boundingBox();
  expect(b, sel).not.toBeNull();
  return b!;
};
const setWidth = (page: Page) => page.locator(".itd-set").evaluate((el) => Math.round(el.getBoundingClientRect().width));
const workWidth = (page: Page) => page.locator(".itd-work").evaluate((el) => el.clientWidth);
const maxOf = async (page: Page) => (await workWidth(page)) - 16 - 640;

async function setSynth(page: Page): Promise<void> {
  await page.locator(".itd-tickers").fill(SYNTH.tickers);
  await page.locator(".itd-from").fill(SYNTH.from);
  await page.locator(".itd-to").fill(SYNTH.to);
  await field(page, "minutes").fill("5");
  await field(page, "stop_pct").fill("0.4");
  await field(page, "target_pct").fill("0.8");
  await field(page, "commission_bp").fill("1.5");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
}

async function run(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/simulate") && r.method() === "POST");
  await page.locator(".itd-run").click();
  const req = await sent;
  await expect(page.locator(".itd-out .itd-result")).toBeVisible({ timeout: 60_000 });
  return req;
}

test("두 칸: 1440 × 900 에서 설정 | 결과와 분석이 나란히 선다 · 기본 폭 480 · 페이지는 구르지 않고 두 칸이 각자 구른다", async ({ page }) => {
  await open(page);
  await expect(page.locator(".itd")).toHaveAttribute("data-split", "");
  const s = await box(page, ".itd-set"), b = await box(page, ".itd-split-bar"), o = await box(page, ".itd-out");
  expect(Math.abs(s.y - o.y), "두 칸의 위가 같다").toBeLessThan(1);
  expect(s.x + s.width).toBeLessThanOrEqual(b.x + 0.5);
  expect(b.x + b.width).toBeLessThanOrEqual(o.x + 0.5);
  expect(Math.round(b.width)).toBe(16);
  expect(await setWidth(page)).toBe(480);
  // 구분선의 이름 · 값 · 범위 · 다스리는 칸
  const sep = page.getByRole("separator", { name: "설정 창 폭" });
  await expect(sep).toBeVisible();
  await expect(sep).toHaveAttribute("aria-orientation", "vertical");
  await expect(sep).toHaveAttribute("aria-valuenow", "480");
  await expect(sep).toHaveAttribute("aria-valuemin", "440");
  await expect(sep).toHaveAttribute("aria-valuemax", String(await maxOf(page)));
  await expect(sep).toHaveAttribute("aria-controls", "itd-set");
  await expect(page.locator("#itd-set")).toHaveClass(/itd-set/);
  await expect(page.getByRole("region", { name: "설정" })).toBeVisible();
  await expect(page.getByRole("region", { name: "결과와 분석" })).toBeVisible();
  // 두 칸 위의 머리 · 모드 전환 줄은 제 높이를 지킨다(세로 flex 가 스크롤 칸인 전환 줄을 눌러 없애지 않게 — 스크린샷 검수에서 찾음)
  const kids = await page.locator(".itd > :not(.itd-work)").evaluateAll((els) => els.map((el) => ({
    cls: String(el.className), h: el.getBoundingClientRect().height, sh: el.scrollHeight })));
  expect(kids.length, "머리 · 전환 줄").toBeGreaterThanOrEqual(2);
  for (const k of kids) {
    expect(k.h, k.cls).toBeGreaterThan(0);
    expect(k.h, `${k.cls} 가 눌리지 않는다`).toBeGreaterThanOrEqual(k.sh - 0.5);
  }
  await expect(page.locator(".tx-subnav-a[aria-current]")).toBeVisible();
  // 페이지는 구르지 않는다 · 두 칸은 각자 구른다(설정은 화면보다 길다 — 잰 값 약 2,760px)
  const main = await page.locator(".terminal-main").evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight }));
  expect(main.sh, JSON.stringify(main)).toBeLessThanOrEqual(main.ch + 1);
  for (const sel of [".itd-set", ".itd-out"]) {
    const st = await page.locator(sel).evaluate((el) => ({ oy: getComputedStyle(el).overflowY, sh: el.scrollHeight, ch: el.clientHeight, bottom: el.getBoundingClientRect().bottom }));
    expect(st.oy, sel).toBe("auto");
    expect(st.bottom, `${sel} 는 화면 안에서 끝난다`).toBeLessThanOrEqual(900);
    if (sel === ".itd-set") expect(st.sh).toBeGreaterThan(st.ch);
  }
  // 넓은 페이지(한 열의 1080 상한을 넘는다) · 실행 전 결과 칸의 문장
  expect(await page.locator(".itd").evaluate((el) => el.getBoundingClientRect().width)).toBeGreaterThan(1080);
  await expect(page.locator(".itd-out-empty")).toHaveText("실행 결과가 이 자리에 나옵니다. 설정을 정하고 실행하십시오.");
  await expect(page.locator(".itd-out-empty")).toHaveAttribute("data-state", "idle");
  await expect(toggle(page)).toHaveText("설정 접기");
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
  await expect(toggle(page)).toHaveAttribute("aria-controls", "itd-set");
});

test("실행 줄은 왼쪽 칸 바닥에 붙어 칸을 굴려도 늘 보인다", async ({ page }) => {
  await open(page);
  const seen = () => page.evaluate(() => {
    const s = document.querySelector(".itd-set")!.getBoundingClientRect();
    const r = document.querySelector(".itd-run")!.getBoundingClientRect();
    return { inside: r.top >= s.top - 0.5 && r.bottom <= s.bottom + 0.5, nearBottom: s.bottom - r.bottom < 120, onScreen: r.bottom <= window.innerHeight };
  });
  // 굴리기 전: 실행 줄의 제자리는 설정 끝(약 2,700px 아래)이지만 칸 바닥에 붙어 보인다
  expect(await seen()).toEqual({ inside: true, nearBottom: true, onScreen: true });
  for (const at of [0.35, 0.7]) {
    await page.locator(".itd-set").evaluate((el, f) => { el.scrollTop = el.scrollHeight * f; }, at);
    expect(await seen(), `scroll ${at}`).toEqual({ inside: true, nearBottom: true, onScreen: true });
  }
  // 쓰임: 칸 맨 위(데이터 절)를 보는 채로 실행한다 — 실행 줄까지 굴리지 않는다(누른 뒤에도 칸은 맨 위 그대로).
  await setSynth(page);
  await page.locator(".itd-set").evaluate((el) => { el.scrollTop = 0; });
  await expect(page.locator(".itd-run")).toBeEnabled();
  await page.locator(".itd-run").click();
  expect(await page.locator(".itd-set").evaluate((el) => el.scrollTop)).toBe(0);
  await expect(page.locator(".itd-out .itd-result")).toBeVisible({ timeout: 60_000 });
});

test("구분선 키: → 두 번 512 · ← 496 · Home 440 · End = 작업 칸 − 656 · 오른쪽 칸은 640 아래로 줄지 않는다", async ({ page }) => {
  await open(page);
  const sep = bar(page);
  await sep.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(sep).toHaveAttribute("aria-valuenow", "512");
  expect(await setWidth(page)).toBe(512);
  await page.keyboard.press("ArrowLeft");
  await expect(sep).toHaveAttribute("aria-valuenow", "496");
  expect(await setWidth(page)).toBe(496);
  await page.keyboard.press("Home");
  await expect(sep).toHaveAttribute("aria-valuenow", "440");
  expect(await setWidth(page)).toBe(440);
  await page.keyboard.press("End");
  const max = await maxOf(page);
  await expect(sep).toHaveAttribute("aria-valuenow", String(max));
  expect(await setWidth(page)).toBe(max);
  expect(Math.round((await box(page, ".itd-out")).width)).toBe(640);
  await page.keyboard.press("ArrowRight");                                          // 끝을 넘지 않는다
  await expect(sep).toHaveAttribute("aria-valuenow", String(max));
});

test("구분선 끌기: 오른쪽으로 100px 끌면 100px 넓어진다 · 끄는 동안 표시가 선다", async ({ page }) => {
  await open(page);
  const b = await box(page, ".itd-split-bar");
  const x = b.x + b.width / 2, y = b.y + 240;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 40, y, { steps: 4 });
  await expect(bar(page)).toHaveAttribute("data-drag", "true");
  await page.mouse.move(x + 100, y, { steps: 4 });
  await page.mouse.up();
  await expect(bar(page)).not.toHaveAttribute("data-drag", /.*/);
  await expect(bar(page)).toHaveAttribute("aria-valuenow", "580");
  expect(await setWidth(page)).toBe(580);
});

test("접기: 구분선에서 Enter 로 접고 단추로 편다 · 접으면 결과 칸이 작업 칸 전체 · 펴면 앞의 폭", async ({ page }) => {
  await open(page);
  await bar(page).focus();
  await page.keyboard.press("ArrowRight");                                          // 496
  await page.keyboard.press("Enter");
  await expect(page.locator(".itd-set")).toBeHidden();
  await expect(bar(page)).toBeHidden();
  await expect(toggle(page)).toBeFocused();                                          // 초점이 사라지지 않게 펴는 단추로
  // Enter 로 접은 것도 남는다(단추로 접은 것만 남기는 구멍이 없게)
  expect(JSON.parse(await page.evaluate((k) => localStorage.getItem(k) ?? "null", KEY))).toEqual({ w: 496, open: false });
  await expect(toggle(page)).toHaveText("설정 펴기");
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "false");
  expect(Math.round((await box(page, ".itd-out")).width)).toBe(await workWidth(page));
  await toggle(page).click();
  await expect(toggle(page)).toHaveText("설정 접기");
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".itd-set")).toBeVisible();
  expect(await setWidth(page)).toBe(496);
  await toggle(page).click();                                                       // 단추로도 접는다
  await expect(page.locator(".itd-set")).toBeHidden();
});

test("저장: 폭과 접힘이 다시 열어도 남는다 ↔ 꼴이 틀린 저장은 기본값(480 · 펼침)으로 그린다", async ({ page }) => {
  await open(page);
  await bar(page).focus();
  await page.keyboard.press("End");
  const max = String(await maxOf(page));
  await toggle(page).click();                                                       // 접기
  expect(JSON.parse(await page.evaluate((k) => localStorage.getItem(k) ?? "null", KEY))).toEqual({ w: Number(max), open: false });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(toggle(page)).toHaveText("설정 펴기");
  await expect(page.locator(".itd-set")).toBeHidden();
  await toggle(page).click();
  await expect(bar(page)).toHaveAttribute("aria-valuenow", max);
  // 짝: 꼴이 틀린 저장
  await page.evaluate((k) => localStorage.setItem(k, "{oops"), KEY);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-set")).toBeVisible();
  await expect(bar(page)).toHaveAttribute("aria-valuenow", "480");
  expect(await setWidth(page)).toBe(480);
});

test("창 크기: 1920 에서 끝까지 넓힌 폭은 1440 에서 그 최대로 줄고, 1920 으로 돌아오면 선호 폭이 돌아온다", async ({ page }) => {
  await open(page, HUGE);
  await bar(page).focus();
  await page.keyboard.press("End");
  const big = await maxOf(page);
  await expect(bar(page)).toHaveAttribute("aria-valuenow", String(big));
  await page.setViewportSize(WIDE);
  await expect.poll(async () => (await setWidth(page)) === (await maxOf(page))).toBe(true);
  await expect(bar(page)).toHaveAttribute("aria-valuenow", String(await maxOf(page)));
  expect(await maxOf(page)).toBeLessThan(big);
  await page.setViewportSize(HUGE);
  await expect.poll(() => setWidth(page)).toBe(big);
  await expect(bar(page)).toHaveAttribute("aria-valuenow", String(big));
});

test("문턱 넘기: 창을 줄이면 다시 열지 않고 한 열로 · 넓히면 두 칸으로 돌아온다 · 절은 다시 생기지 않는다(절 안의 입력 · 폭 그대로)", async ({ page }) => {
  await open(page);
  await page.locator(".itd-tickers").fill(SYNTH.tickers);
  await page.locator(".itd-dt-k").fill("4");                                         // 하루 유형 절의 자체 상태(처음 값 6)
  await bar(page).focus();
  await page.keyboard.press("ArrowRight");                                          // 496
  await page.setViewportSize({ width: 1200, height: 900 });
  await expect(page.locator(".itd")).not.toHaveAttribute("data-split", /.*/);
  await expect(bar(page)).toHaveCount(0);
  await expect(toggle(page)).toHaveCount(0);
  await expect(page.locator(".itd-out-empty")).toHaveCount(0);
  await expect(page.locator(".itd-dt-k")).toHaveValue("4");
  await page.setViewportSize(WIDE);
  await expect(page.locator(".itd")).toHaveAttribute("data-split", "");
  await expect(bar(page)).toHaveAttribute("aria-valuenow", "496");
  expect(await setWidth(page)).toBe(496);
  await expect(page.locator(".itd-dt-k")).toHaveValue("4");
  await expect(page.locator(".itd-tickers")).toHaveValue(SYNTH.tickers);
});

test("흐름: 실행 결과 · 판정은 결과 칸에 · 다시 실행하면 결과 칸을 맨 위로 · 설정을 바꾸면 결과를 지우고 그렇게 말한다 · 합성 알림은 두 칸 밖 위", async ({ page }) => {
  await open(page);
  await setSynth(page);
  await run(page);
  await expect(page.locator(".itd-out-empty")).toHaveCount(0);
  // 합성 알림: 두 칸 밖 · 두 칸 위 · 결과 칸을 굴려도 그 자리
  const banner = page.locator(".itd-banner");
  await expect(banner).toBeVisible();
  expect(await banner.evaluate((el) => el.closest(".itd-set, .itd-out") === null)).toBe(true);
  const b0 = await box(page, ".itd-banner"), s0 = await box(page, ".itd-set");
  expect(b0.y + b0.height).toBeLessThanOrEqual(s0.y + 0.5);
  await page.locator(".itd-out").evaluate((el) => { el.scrollTop = 1600; });
  expect(await page.locator(".itd-out").evaluate((el) => el.scrollTop)).toBeGreaterThan(500);
  expect(Math.abs((await box(page, ".itd-banner")).y - b0.y)).toBeLessThan(0.5);
  // 결과 칸을 굴려도 접기 단추 막대는 칸 맨 위에 남는다
  const tg = await box(page, ".itd-set-toggle"), oc = await box(page, ".itd-out");
  expect(tg.y - oc.y, "접기 단추는 결과 칸 맨 위").toBeGreaterThanOrEqual(-0.5);
  expect(tg.y - oc.y, "접기 단추는 결과 칸 맨 위").toBeLessThan(8);
  // 같은 설정을 다시 실행해도 결과 칸을 맨 위로 올린다
  await run(page);
  expect(await page.locator(".itd-out").evaluate((el) => el.scrollTop)).toBeLessThan(1);
  const top = await page.locator(".itd-out .itd-result").evaluate((el) => el.getBoundingClientRect().top - el.closest(".itd-out")!.getBoundingClientRect().top);
  expect(top, "결과는 칸 위쪽에 선다").toBeLessThan(120);
  // 판정도 결과 칸
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/validate") && r.method() === "POST");
  await page.locator(".itd-out .itd-judge-btn").click();
  await sent;
  await expect(page.locator(".itd-out .itd-verdict")).toBeVisible({ timeout: 60_000 });
  // 설정을 바꾸면 결과를 지우고 두 칸 모두 그렇게 말한다
  await field(page, "minutes").fill("6");
  await expect(page.locator(".itd-result")).toHaveCount(0);
  await expect(page.locator(".itd-out-empty")).toHaveText("설정이 변경돼 앞의 결과를 지웠습니다. 다시 실행하십시오.");
  await expect(page.locator(".itd-out-empty")).toHaveAttribute("data-state", "stale");
  await expect(page.locator(".itd-set .tj-stale")).toHaveText("설정이 변경됐습니다. 재계산이 필요합니다.");
});

test("계산 중: 결과 칸 문장이 '계산 중입니다.'로 바뀌고 끝나면 결과로 바뀐다", async ({ page }) => {
  await open(page);
  await page.locator(".itd-tickers").fill(HAND.tickers);
  await page.locator(".itd-from").fill(HAND.from);
  await page.locator(".itd-to").fill(HAND.to);
  await field(page, "minutes").fill("1");
  let release: () => void = () => undefined;
  const held = new Promise<void>((r) => { release = r; });
  await page.route("**/intraday/simulate", async (route) => { await held; await route.continue(); });
  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-out-empty")).toHaveText("계산 중입니다.");
  await expect(page.locator(".itd-out-empty")).toHaveAttribute("data-state", "pending");
  await expect(page.locator(".itd-out-empty")).toHaveAttribute("role", "status");
  release();
  await expect(page.locator(".itd-out .itd-result")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".itd-out-empty")).toHaveCount(0);
});

for (const vp of [{ width: 1280, height: 720 }, { width: 1440, height: 780 }, { width: 1200, height: 900 }, { width: 390, height: 844 }]) {
  test(`한 열(짝): ${vp.width} × ${vp.height} 에서는 지금처럼 위아래로 쌓인다 · 구분선 · 단추 · 빈 칸 문장이 없다 · 칸 사이 12px`, async ({ page }) => {
    await open(page, vp);
    await expect(page.locator(".itd")).not.toHaveAttribute("data-split", /.*/);
    await expect(bar(page)).toHaveCount(0);
    await expect(toggle(page)).toHaveCount(0);
    await expect(page.locator(".itd-out-empty")).toHaveCount(0);
    const s = await box(page, ".itd-set"), o = await box(page, ".itd-out");
    expect(o.y, "결과는 설정 아래").toBeGreaterThanOrEqual(s.y + s.height - 0.5);
    const gaps = await page.evaluate(() => {
      const kids = (sel: string) => [...document.querySelector(sel)!.children].filter((c) => c.getClientRects().length > 0);
      const set = kids(".itd-set"), out = kids(".itd-out");
      const g: number[] = [];
      for (let i = 1; i < set.length; i++) g.push(Math.round(set[i].getBoundingClientRect().top - set[i - 1].getBoundingClientRect().bottom));
      g.push(Math.round(out[0].getBoundingClientRect().top - set[set.length - 1].getBoundingClientRect().bottom));
      return g;
    });
    expect(gaps.every((g) => g === 12), JSON.stringify(gaps)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    expect(await page.locator(".itd").evaluate((el) => el.getBoundingClientRect().width)).toBeLessThanOrEqual(1080.5);
    // 접어 둔 저장이 있어도 한 열에서는 설정을 숨기지 않는다
    await page.evaluate((k) => localStorage.setItem(k, JSON.stringify({ w: 600, open: false })), KEY);
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator(".itd-tickers")).toBeVisible();
    await expect(page.locator(".itd-set")).toBeVisible();
  });
}

test("다크 · 문체: 두 칸의 새 글이 개조식 + 합니다체이고 구분선 · 단추가 다크에서도 보인다", async ({ page }) => {
  await page.addInitScript(() => { try { localStorage.setItem("alpha_theme", "dark"); } catch { /* */ } });
  await open(page);
  await expect(page.locator("html")).toHaveClass(/dark/);
  const v = (await page.evaluate(voiceAudit(".itd-work"))) as VoiceResult;
  expect(v.checked).toBeGreaterThan(20);
  expect(v.haeyo).toEqual([]);
  expect(v.dash).toEqual([]);
  expect(v.banned).toEqual([]);
  // 구분선 손잡이와 선이 바탕과 다른 색 · 단추 글자 대비
  const c = await page.evaluate(() => {
    const bar = document.querySelector(".itd-split-bar")!;
    const line = getComputedStyle(bar, "::before").backgroundColor;
    const grip = getComputedStyle(bar, "::after").backgroundColor;
    const bg = getComputedStyle(document.querySelector(".terminal-main")!).backgroundColor;
    return { line, grip, bg };
  });
  expect(c.line).not.toBe(c.bg);
  expect(c.grip).not.toBe(c.bg);
});
