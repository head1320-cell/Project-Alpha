import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, type Page, type Request } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 실행 전 가설 · 자유도 공시 (묶음 G · G3 — 구현 계획 `docs/superpowers/plans/2026-11-16-evidence-and-trader-ux.md` §4) · ★실제 서버★
// ────────────────────────────────────────────────────────────────────────────
// 분봉은 `e2e/fixtures/intraday/seed_bars.py` 의 손으로 만든 열흘(035720 · 2026-03-02 ~ 03-13)이다(시가 범위 돌파 1분 → 거래 열 건).
// ★시행 기록은 이 서버의 DB 에 남는다★ — 가설은 시행마다 처음 것만 남으므로 시험마다 기록에 없는 진입 금액(새 시행)으로 돈다.
// 거는 것:
//  · 설정의 '실행 전 가설' 칸 — 글자 수 상한은 서버의 것 · 가설은 설정이 아니다(바꿔도 결과를 지우지 않는다 ↔ 설정을 바꾸면 지운다)
//  · 첫 실행과 함께 적으면 '결과를 보기 전' · 두 번 돌린 뒤 처음 적으면 '앞선 실행의 결과를 본 뒤' · 고쳐 보내면 처음 것이 남고 그렇다고 말한다
//  · 빈 칸은 보내지 않는다 · 가설이 없으면 줄이 없다 · 개인정보 모양은 실행 전에 서버 사유로 거절(결과를 만들지 않는다)
//  · 자유도 공시 — 판정의 '시행 횟수와 다중 비교' 절에 물음 · 답 · 셈 · 한계가 서버 문장 그대로 · 다중 비교 관문의 마지막 사실 줄과 같은 답 ·
//    손 계산(시가 범위 돌파의 값 1 + 종목당 진입 수 1 = 2 · 거래 10 → 5.0건) ↔ 칸 하나를 더 정하면 하나 는다 · 관문의 상태는 그대로
//  · 매매일지 '백테스트와 견주기'의 시행 고르기 — 가설이 남은 시행은 줄에 '적은 때'가 붙고, 고르면 그 글이 보인다
//  · 라이트/다크 AA · 문체 · 390px 에서 넘치지 않는다
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HERE = "/backtest/intraday";
const JOURNAL = "/my-account/journal";
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const IDEA = "장 초반 1분 고가를 넘으면 그날 매수세가 이어진다고 봅니다.";
const FIRST = "이 설정의 첫 실행과 함께 적은 가설입니다. 결과를 보기 전에 적었습니다.";
const NOT_SAVED = "처음 적은 가설이 남아 있어 이번에 보낸 글은 저장하지 않았습니다.";
const DAYS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"];

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

let seq = 0;
/** 기록에 없는 진입 금액 — 새 시행이어야 '처음 적은 가설'을 볼 수 있다(로컬 DB 는 앞선 실행을 기억한다). */
const fresh = (): string => String(1_000_000 + ((Date.now() * 7 + ++seq * 7_919) % 8_000_000) + 1);

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);
const box = (page: Page) => page.locator(".itd-hypothesis");
const gate = (page: Page, key: string) => page.locator(`.itd-gate[data-gate="${key}"]`);

/** 손 계산의 그 설정 + 기록에 없는 진입 금액. */
async function openHand(page: Page): Promise<string> {
  const token = await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await page.locator(".itd-tickers").fill(HAND.tickers);
  await page.locator(".itd-from").fill(HAND.from);
  await page.locator(".itd-to").fill(HAND.to);
  await field(page, "minutes").fill("1");
  await field(page, "commission_bp").fill("1.5");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
  await field(page, "amount").fill(fresh());
  return token;
}

async function run(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/simulate") && r.method() === "POST");
  await page.locator(".itd-run").click();
  const req = await sent;
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
  return req;
}

async function judge(page: Page): Promise<{ req: Request; body: { freedom: Record<string, string | number | null> } }> {
  const answered = page.waitForResponse((r) => r.url().includes("/intraday/validate") && r.request().method() === "POST");
  await page.locator(".itd-judge-btn").click();
  const res = await answered;
  await expect(page.locator(".itd-verdict")).toBeVisible({ timeout: 60_000 });
  return { req: res.request(), body: await res.json() };
}

test("첫 실행과 함께 적은 가설은 '결과를 보기 전'으로 남고, 판정도 같은 글을 보인다 · 고쳐 보내면 처음 것이 남는다 · 가설은 설정이 아니다", async ({ page }) => {
  const token = await openHand(page);
  const limits = (await (await page.request.get(`${API}/intraday/templates`, { headers: { Authorization: `Bearer ${token}` } })).json()).limits;
  await expect(box(page)).toHaveAttribute("maxlength", String(limits.hypothesis_chars));            // 상한은 서버의 것(500)
  await box(page).fill(`  ${IDEA}  `);
  await expect(page.locator("#itd-hypothesis-note")).toContainText(`${IDEA.length + 4}/${limits.hypothesis_chars}자`);

  const req = await run(page);
  expect(req.postDataJSON().hypothesis).toBe(`  ${IDEA}  `);                                   // 받은 글 그대로 — 앞뒤 공백은 서버가 걷는다
  const line = page.locator(".itd-result .itd-hypo");
  await expect(line).toHaveAttribute("data-before", "true");
  await expect(line).toHaveAttribute("data-kept-now", "true");
  await expect(line.locator(".itd-hypo-text")).toHaveText(IDEA);
  await expect(line.locator(".itd-hypo-when")).toHaveText(FIRST);
  await expect(line.locator(".itd-hypo-k")).toHaveText(["가설", "적은 때"]);
  await expect(line).toHaveAccessibleName("실행 전 가설");

  // 가설은 설정이 아니다 — 바꿔도 결과가 남고 '재계산 필요'를 말하지 않는다(짝: 설정 칸을 바꾸면 결과를 지운다).
  await box(page).fill("결과를 보고 고친 다른 기제");
  await expect(page.locator(".itd-result")).toBeVisible();
  await expect(page.locator(".tj-stale")).toHaveCount(0);

  // 판정 — 같은 설정이라 같은 시행(2회째) · 처음 것이 남아 있고, 이번 글은 저장하지 않았다고 말한다.
  const { req: vreq } = await judge(page);
  expect(vreq.postDataJSON().hypothesis).toBe("결과를 보고 고친 다른 기제");
  const vline = page.locator(".itd-verdict .itd-hypo");
  await expect(vline.locator(".itd-hypo-text")).toHaveText(IDEA);
  await expect(vline.locator(".itd-hypo-when")).toHaveText(`${FIRST} ${NOT_SAVED}`);
  await expect(vline).toHaveAttribute("data-kept-now", "false");

  // 짝: 설정 칸을 바꾸면 결과와 판정을 지운다(가설 칸만 예외다).
  await field(page, "minutes").fill("2");
  await expect(page.locator(".itd-result")).toHaveCount(0);
  await expect(page.locator(".tj-stale")).toBeVisible();
});

test("가설 없이 두 번 돌린 뒤 처음 적으면 '앞선 실행의 결과를 본 뒤'로 남는다 · 빈 칸은 보내지 않는다 · 가설이 없으면 줄이 없다", async ({ page }) => {
  await openHand(page);
  const first = await run(page);
  expect(first.postDataJSON().hypothesis).toBeUndefined();
  await expect(page.locator(".itd-result .itd-hypo")).toHaveCount(0);
  await box(page).fill("   ");                                                           // 빈 글은 가설이 없는 것 — 보내지 않는다
  const blank = await run(page);
  expect(blank.postDataJSON().hypothesis).toBeUndefined();
  await expect(page.locator(".itd-result .itd-hypo")).toHaveCount(0);

  await box(page).fill(IDEA);
  await run(page);
  const line = page.locator(".itd-result .itd-hypo");
  await expect(line).toHaveAttribute("data-before", "false");
  await expect(line.locator(".itd-hypo-text")).toHaveText(IDEA);
  await expect(line.locator(".itd-hypo-when")).toHaveText("2회 실행한 뒤에 처음 적은 가설입니다. 앞선 실행의 결과를 본 뒤에 적었습니다.");
});

test("가설을 남기지 못했으면 글 칸 없이 서버 문장만 보인다 · 없음으로 꾸미지 않는다", async ({ page }) => {
  const NOT_KEPT = "가설을 저장하지 못했습니다. 시행 기록에 가설 칸이 없거나 읽고 쓰지 못했습니다.";
  await openHand(page);
  // 실제 서버의 답에서 가설 줄만 '남기지 못함'으로 바꿔 싣는다 — 저장소 장애는 이 서버에서 만들 수 없다(그 줄을 서버가 짓는 것은 pytest 가 건다).
  await page.route("**/api/v1/intraday/simulate", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.trial.hypothesis = { text: null, at_run: null, before_results: null, kept_now: false, message: NOT_KEPT };
    await route.fulfill({ response: res, json: body });
  });
  await box(page).fill(IDEA);
  await run(page);
  const line = page.locator(".itd-result .itd-hypo");
  await expect(line).toHaveAttribute("data-before", "unknown");
  await expect(line.locator(".itd-hypo-text")).toHaveCount(0);
  await expect(line.locator(".itd-hypo-k")).toHaveText(["가설"]);
  await expect(line.locator(".itd-hypo-when")).toHaveText(NOT_KEPT);
});

test("개인정보 모양의 가설은 실행 전에 서버 사유로 거절한다 · 결과를 만들지 않는다", async ({ page }) => {
  await openHand(page);
  await box(page).fill("문의는 010-1234-5678 로 받습니다.");
  await page.locator(".itd-run").click();
  await expect(page.locator(".itd-run-fail .tx-notice-t")).toHaveText("실행 요청 거절");
  await expect(page.locator(".itd-run-fail")).toContainText("가설에 전화번호 형식이 포함돼 있습니다");
  await expect(page.locator(".itd-result")).toHaveCount(0);
  // 짝: 고치면 그대로 돈다(거절이 칸을 막아 두지 않는다).
  await box(page).fill(IDEA);
  await run(page);
  await expect(page.locator(".itd-result .itd-hypo .itd-hypo-text")).toHaveText(IDEA);
});

test("자유도 공시: 판정의 '시행 횟수와 다중 비교' 절에 서버 문장 그대로 · 다중 비교 관문의 마지막 사실 줄 · 칸 하나를 더 정하면 하나 는다", async ({ page }) => {
  await openHand(page);
  await run(page);
  const { body } = await judge(page);
  const f = body.freedom;
  // 손 계산: 시가 범위 돌파의 값 1(분) + 포지션의 정한 칸 1(종목당 하루 진입 수의 기본값 1 — 진입 금액은 세지 않는다) = 2 · 거래 10 → 5.0건.
  expect(f.message).toBe("조정 가능한 값 2개(규칙 1 · 포지션 1) · 거래 10건 · 값 하나당 거래 5.0건입니다.");
  const free = page.locator(".itd-verdict .itd-free");
  await expect(free).toHaveAccessibleName("자유도 공시");
  await expect(free.locator(".itd-free-k")).toHaveText(["물음", "답"]);
  await expect(free.locator(".itd-free-question")).toHaveText(String(f.question));
  await expect(free.locator(".itd-free-answer")).toHaveText(String(f.message));
  await expect(free.locator(".itd-free-note")).toHaveText(`${f.basis} ${f.limit}`);
  await expect(free.locator("[data-server]")).toHaveCount(4);
  await expect(gate(page, "multiplicity").locator(".itd-gate-facts li").last()).toHaveText(String(f.message));
  await expect(gate(page, "multiplicity")).toHaveAttribute("data-state", "unknown");          // 상태는 확률(10일 — 미상)이 정한다
  await expect(gate(page, "multiplicity").locator(".itd-gate-reason")).toHaveText("거래일이 10일뿐입니다. 60일 이상이어야 확률을 산출합니다.");

  // 짝: 하루 최대 손실을 정하면 손잡이가 하나 는다(3개 · 3.3건) — 같은 자리 · 같은 문장 꼴.
  await field(page, "daily_loss_limit").fill("10000");
  await run(page);
  const again = await judge(page);
  expect(again.body.freedom.message).toBe("조정 가능한 값 3개(규칙 1 · 포지션 2) · 거래 10건 · 값 하나당 거래 3.3건입니다.");
  await expect(page.locator(".itd-verdict .itd-free-answer")).toHaveText(String(again.body.freedom.message));
});

test("매매일지 '백테스트와 견주기': 가설이 남은 시행은 고르기 줄에 '적은 때'가 붙고, 고르면 그 글이 보인다", async ({ page }) => {
  const token = await login(page);
  const amount = Number(fresh());
  const request = { tickers: [HAND.tickers], from: HAND.from, to: HAND.to, rule: { kind: "opening_range_breakout", params: { minutes: 1 } },
                    position: { amount }, costs: { commission_bp: 1.5, unknown_market: "KOSPI", unknown_instrument: "stock" } };
  const auth = { Authorization: `Bearer ${token}` };
  const made = await page.request.post(`${API}/intraday/simulate`, { headers: auth, data: { ...request, hypothesis: IDEA } });
  expect(made.ok(), await made.text()).toBe(true);
  const withIdea = (await made.json()).trial.trial_key as string;
  const bare = await page.request.post(`${API}/intraday/simulate`, { headers: auth, data: { ...request, position: { amount: amount + 1 } } });
  expect(bare.ok(), await bare.text()).toBe(true);
  const without = (await bare.json()).trial.trial_key as string;

  await page.goto(JOURNAL, { waitUntil: "domcontentloaded" });
  const fills = ["체결일시,종목코드,매매구분,체결수량,체결단가",
                 ...DAYS.flatMap((d) => [`${d} 09:02:40,035720,매수,99,10090`, `${d} 09:03:20,035720,매도,99,10090`])].join("\n") + "\n";
  await page.locator(".tj-file-input").setInputFiles({ name: "fills.csv", mimeType: "text/csv", buffer: Buffer.from(fills, "utf-8") });
  await expect(page.locator(".tj-run")).toBeEnabled();
  await page.locator(".tj-run").click();
  await expect(page.locator(".dv-compare")).toBeVisible();

  // 가설이 남은 시행 — 줄 끝에 '적은 때' · 고르면 아래에 글과 서버 문장.
  await expect(page.locator(`.dv-trial option[value="${withIdea}"]`)).toHaveText(/ · 1회 실행 · 가설: 결과를 보기 전$/);
  await page.locator(".dv-trial").selectOption(withIdea);
  const line = page.locator(".dv-compare .itd-hypo");
  await expect(line.locator(".itd-hypo-text")).toHaveText(IDEA);
  await expect(line.locator(".itd-hypo-when")).toHaveText(FIRST);
  // 짝: 가설이 없는 시행은 줄에 아무것도 붙지 않고, 고르면 가설 줄이 없다.
  await expect(page.locator(`.dv-trial option[value="${without}"]`)).not.toContainText("가설");
  await page.locator(".dv-trial").selectOption(without);
  await expect(page.locator(".dv-compare .itd-hypo")).toHaveCount(0);
  // 다시 보낼 요청에는 가설이 들지 않는다 — 괴리 보고는 가설 칸을 받지 않는다(서버가 422 로 거절한다).
  await page.locator(".dv-trial").selectOption(withIdea);
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/divergence") && r.method() === "POST");
  await page.locator(".dv-run").click();
  expect((await sent).postDataJSON().hypothesis).toBeUndefined();
  await expect(page.locator(".dv-result")).toBeVisible({ timeout: 30_000 });
});

for (const theme of ["light", "dark"] as const) {
  test(`가설 줄 · 자유도 공시: 대비(${theme}) AA · 문체 · 390px 에서 한 칸으로 쌓이고 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await openHand(page);
    await box(page).fill(`${IDEA}\n둘째 줄은 줄바꿈을 지킵니다.`);
    await run(page);
    await judge(page);
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    for (const root of [".itd-hypo", ".itd-free", ".itd-hypo-field"]) {
      const a = (await page.evaluate(contrastAudit(root))) as AuditResult;
      expect(a.checked, root).toBeGreaterThan(1);
      expect(a.low, `${theme} ${root}`).toEqual([]);
    }
    const v = (await page.evaluate(voiceAudit(".itd"))) as VoiceResult;
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    // 사용자가 적은 줄바꿈을 지킨다(두 줄).
    const lines = await page.locator(".itd-verdict .itd-hypo-text").evaluate((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
    expect(lines).toBeGreaterThanOrEqual(2);

    // 넓은 창: 열쇠와 값이 한 줄(값의 왼쪽 끝이 열쇠의 오른쪽) · 390px: 한 칸으로 쌓인다(값이 열쇠 아래) · 넘침 0.
    const layout = () => page.evaluate(() => [...document.querySelectorAll(".itd-verdict .itd-hypo-row, .itd-verdict .itd-free-row")].map((row) => {
      const k = row.children[0].getBoundingClientRect();
      const v = row.children[1].getBoundingClientRect();
      return { beside: v.left >= k.right - 1 && Math.abs(v.top - k.top) < 8, below: v.top >= k.bottom - 1,
               over: (row as HTMLElement).scrollWidth - (row as HTMLElement).clientWidth };
    }));
    expect((await layout()).every((r) => r.beside && r.over <= 0)).toBe(true);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-verdict .itd-free")).toBeVisible();
    expect((await layout()).every((r) => r.below && r.over <= 0)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  });
}
