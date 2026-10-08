import { test, expect, type Page, type Route } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// BU7b — 데이터 상태 `/admin/data` (계획 "BU7 상세", 사용자 결정: ★적재 확인 창 + 서버 권한은 별도 작업★)
// ─────────────────────────────────────────────────────────────────────────────
// ★먼저 써서 옛 화면(영어 대문자 소제목 · 확인 없는 적재 · 실패 삼킴)에서 빨강을 기록한다★ 지키는 것:
//   · 답 한 문장 = 서버 등급 세기(source-honesty `research_usage`) — 새 판단 없음
//   · 실행 모드를 모르면 "몰라요"(옛 화면은 불러오기 전·실패 때 "MODE: MOCK")
//   · 실패(닿지 못함) ≠ 비어 있음: 출처 등급 500 → alert · 폴링 실패 + 옛 값 → "마지막으로 받은 값"
//   · ★적재는 확인 창을 거친다★ 취소 → 요청 0 · 시작 → 옛 화면과 같은 요청 하나(경로 같음 · 본문 `{}`)
//   · 유니버스 막대 폭 = 적재/전체 · ★전체 0 이면 0% 가 아니라 몰라요★
// ═══════════════════════════════════════════════════════════════════════════════

const API = "**/api/backend/api/v1/data";
const fail500 = { status: 500, contentType: "application/json", body: '{"detail":"boom"}' };
type Src = { id: string; label: string; data_status: string; research_usage: string; reason: string };
const src = (id: string, usage: string, status = "real"): Src => ({ id, label: `원천 ${id}`, data_status: status, research_usage: usage, reason: `${id} 등급의 서버 사유 문장` });

async function open(page: Page) {
  await page.goto("/admin/data", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dsx")).toBeVisible({ timeout: 40_000 });
}
/** db-status 응답 고치기 — 실제 응답을 받아 fn 이 바꾼다. */
async function patchDb(page: Page, fn: (b: Record<string, unknown>) => void) {
  await page.route(`${API}/db-status`, async (route: Route) => {
    const res = await route.fetch(); const body = await res.json();
    fn(body);
    await route.fulfill({ response: res, json: body });
  });
}
/** 적재 POST 를 모두 기록하고 실제 적재는 시작하지 않는다. */
async function recordIngest(page: Page, reply: (target: string) => Record<string, unknown> | number = (t) => ({ started: [t], running: {}, message: `적재 시작: ${t}` })) {
  const posts: { path: string; body: string | null }[] = [];
  await page.route(`${API}/ingest/*`, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const path = new URL(route.request().url()).pathname;
    posts.push({ path, body: route.request().postData() });
    const r = reply(path.split("/").pop()!);
    if (typeof r === "number") return route.fulfill({ ...fail500, status: r });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(r) });
  });
  return posts;
}

test("답 = 서버 등급 세기 — 과거 검증에 쓸 수 있는 원천 수(응답을 고치면 따라간다)", async ({ page }) => {
  await page.route(`${API}/source-honesty`, (r) => r.fulfill({ json: { mock_mode: false, sources: [
    src("a", "backtest_eligible"), src("b", "backtest_eligible"), src("c", "forward_only"), src("d", "unavailable", "unavailable"), src("e", "forward_only")] } }));
  await open(page);
  await expect(page.locator(".tx-answer-s")).toHaveText("데이터 원천 5개 중 2개를 과거 검증에 쓸 수 있어요.", { timeout: 20_000 });
  const figs = page.locator(".tx-answer .tx-fig");
  await expect(figs.filter({ hasText: "과거 검증 가능" }).locator("dd")).toHaveText("2개");
  await expect(figs.filter({ hasText: "전방 전용" }).locator("dd")).toHaveText("2개");
  await expect(figs.filter({ hasText: "사용 불가" }).locator("dd")).toHaveText("1개");
});

test("짝 — 과거 검증 원천이 0 이면 '아직 없어요'(0개라고 숫자를 지어 넣지 않는 문장) · 등급 500 이면 '몰라요' 문장", async ({ page }) => {
  await page.route(`${API}/source-honesty`, (r) => r.fulfill({ json: { mock_mode: true, sources: [src("a", "forward_only"), src("b", "unavailable")] } }));
  await open(page);
  await expect(page.locator(".tx-answer-s")).toHaveText("데이터 원천 2개 중 과거 검증에 쓸 수 있는 원천은 아직 없어요.", { timeout: 20_000 });
  await page.unroute(`${API}/source-honesty`);
  await page.route(`${API}/source-honesty`, (r) => r.fulfill(fail500));
  await open(page);
  await expect(page.locator(".tx-answer-s")).toContainText("아직 몰라요", { timeout: 20_000 });
});

test("★출처 등급 500 → 그 절 alert + 다시 시도 → 풀면 회복★(옛 화면은 절이 조용히 사라졌다) · 짝: 정상은 alert 0", async ({ page }) => {
  let fail = true;
  await page.route(`${API}/source-honesty`, (r) => (fail ? r.fulfill(fail500) : r.fallback()));
  await open(page);
  const sec = page.locator(".t-honesty");
  await expect(sec.getByRole("alert")).toContainText("원천별 연구 등급을 불러오지 못했어요", { timeout: 20_000 });
  await expect(sec.locator(".t-honesty-row")).toHaveCount(0);
  fail = false;
  await sec.getByRole("button", { name: "다시 시도" }).click();
  await expect(sec.locator(".t-honesty-row").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".terminal-main [role=alert]")).toHaveCount(0);
});

test("★실행 모드를 모르면 '몰라요' — 연습용으로 그리지 않는다★ · 짝: kis_real true → 실제 · mock_mode → 연습용", async ({ page }) => {
  await page.route(`${API}/db-status`, (r) => r.fulfill(fail500));
  await open(page);
  const badge = page.locator(".t-mode-badge");
  await expect(badge).toHaveText("실행 모드를 몰라요", { timeout: 20_000 });
  await expect(badge).not.toHaveAttribute("data-real", /.+/);
  await expect(page.locator(".dsx").getByRole("alert").filter({ hasText: "데이터 상태를 불러오지 못했어요" })).toBeVisible();
  await expect(badge, "모름을 연습용으로 그리지 않는다").not.toContainText(/MOCK|연습용/);

  await page.unroute(`${API}/db-status`);
  await patchDb(page, (b) => { (b.config as Record<string, boolean>).kis_real = true; });
  await open(page);
  await expect(badge).toHaveText("실제 시세로 돌아요", { timeout: 20_000 });
  await expect(badge).toHaveAttribute("data-real", "1");

  await page.unroute(`${API}/db-status`);
  await page.route(`${API}/source-honesty`, (r) => r.fulfill({ json: { mock_mode: true, sources: [src("a", "forward_only", "mock")] } }));
  await open(page);
  await expect(badge).toHaveText("연습용 시세로 돌아요", { timeout: 20_000 });
  await expect(badge).toHaveAttribute("data-real", "0");
});

test("★적재 확인 창 — 취소하면 요청 0, 시작하면 같은 요청 하나(경로 · 본문 `{}`)★ · 전체와 데이터별 둘 다", async ({ page }) => {
  const posts = await recordIngest(page);
  await open(page);
  const all = page.locator('[data-act="ingest-all"]');
  await expect(all).toBeEnabled({ timeout: 20_000 });

  await all.click();
  const dlg = page.getByRole("dialog");
  await expect(dlg).toContainText("전체 적재를 시작할까요?");
  await expect(dlg).toContainText("전자공시(DART) 하루 요청 한도");
  await dlg.getByRole("button", { name: "취소" }).click();
  await expect(dlg).toHaveCount(0);
  await page.waitForTimeout(800);
  expect(posts, "취소 → 요청 0").toEqual([]);

  await all.click();
  await page.getByRole("dialog").getByRole("button", { name: "적재 시작" }).click();
  await expect(page.locator('.dsx-ing-row[data-ds="all"] .dsx-ing-res')).toContainText("적재를 시작했어요", { timeout: 10_000 });
  expect(posts).toEqual([{ path: "/api/backend/api/v1/data/ingest/all", body: "{}" }]);

  const one = page.locator('[data-act="ingest-stocks"]');
  await one.click();
  await expect(page.getByRole("dialog")).toContainText("‘주식 일봉’ 적재를 시작할까요?");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);
  expect(posts.length, "Esc → 요청 0").toBe(1);
  await one.click();
  await page.getByRole("dialog").getByRole("button", { name: "적재 시작" }).click();
  await expect(page.locator('.dsx-ing-row[data-ds="stocks"] .dsx-ing-res')).toContainText("적재를 시작했어요", { timeout: 10_000 });
  expect(posts[1]).toEqual({ path: "/api/backend/api/v1/data/ingest/stocks", body: "{}" });
  expect(posts.length).toBe(2);
});

test("적재 결과는 그 단추 옆 — 이미 실행 중(started 비어 있음) · 실패 500 → 그 줄 alert(다른 줄은 조용)", async ({ page }) => {
  await recordIngest(page, (t) => (t === "etf" ? 500 : { started: [], running: { [t]: true }, message: "모두 이미 실행 중" }));
  await open(page);
  await page.locator('[data-act="ingest-index"]').click();
  await page.getByRole("dialog").getByRole("button", { name: "적재 시작" }).click();
  await expect(page.locator('.dsx-ing-row[data-ds="index"] .dsx-ing-res')).toContainText("이미 실행 중이에요", { timeout: 10_000 });
  await page.locator('[data-act="ingest-etf"]').click();
  await page.getByRole("dialog").getByRole("button", { name: "적재 시작" }).click();
  await expect(page.locator('.dsx-ing-row[data-ds="etf"]').getByRole("alert")).toContainText("적재를 시작하지 못했어요", { timeout: 10_000 });
  await expect(page.locator('.dsx-ing-row[data-ds="index"]').getByRole("alert")).toHaveCount(0);
});

test("★폴링 실패 + 옛 값 → '마지막으로 받은 값' 알림 + 다시 시도★(옛 화면은 낡은 값을 새 값처럼) · 짝: 받기 전엔 알림 0", async ({ page }) => {
  let n = 0;
  await page.route(`${API}/db-status`, async (route) => {
    n += 1;
    if (n > 1) return route.fulfill(fail500);
    const res = await route.fetch(); const body = await res.json();
    body.ingest_running = { ...(body.ingest_running ?? {}), stocks: true };
    await route.fulfill({ response: res, json: body });
  });
  await open(page);
  await expect(page.locator('[data-act="ingest-stocks"]')).toHaveText("적재하는 중이에요", { timeout: 20_000 });
  await expect(page.getByText("마지막으로 받은 값이에요")).toHaveCount(0);
  await expect(page.getByText(/마지막으로 받은 값이에요/)).toBeVisible({ timeout: 15_000 });
  // 옛 값은 남아 있다(지우지 않는다) — 다만 낡았다고 말한다.
  await expect(page.locator(".dsx-tables .trisk-table")).toBeVisible();
});

test("유니버스 적재 막대 — 폭 = 적재/전체 · ★전체 0 이면 막대 없이 몰라요(0% 아님)★", async ({ page }) => {
  await patchDb(page, (b) => {
    b.universe_progress = { progress: { kospi: { master: 200, ingested: 50 }, kosdaq: { master: 0, ingested: 3 } }, composition: {} };
  });
  await open(page);
  const kospi = page.locator('.dsx-uni-row[data-uni="kospi"]');
  await expect(kospi).toContainText("50 / 200종목 · 25%", { timeout: 20_000 });
  const ratio = await kospi.locator(".dsx-uni-bar").evaluate((t) => (t.querySelector("i") as HTMLElement).getBoundingClientRect().width / t.getBoundingClientRect().width);
  expect(ratio).toBeGreaterThan(0.23); expect(ratio).toBeLessThan(0.27);
  const kosdaq = page.locator('.dsx-uni-row[data-uni="kosdaq"]');
  await expect(kosdaq).toContainText("몰라요");
  await expect(kosdaq).not.toContainText("0%");
  await expect(kosdaq.locator(".dsx-uni-bar i")).toHaveCount(0);
});

test("표별 적재 — 미상은 '몰라요'(옛 '—') · 못 읽은 표의 원래 사유는 닫힌 칸 안에 그대로", async ({ page }) => {
  await open(page);
  const t = page.locator(".dsx-tables .trisk-table");
  await expect(t).toBeVisible({ timeout: 20_000 });
  await expect(t).not.toContainText("—");
  const vint = t.locator('tr[data-table="financials_vintages"]');
  await expect(vint).toContainText("이 표를 읽지 못했어요");
  await expect(vint.locator("details.dsx-raw")).not.toHaveAttribute("open", "");
  await expect(vint.locator("details.dsx-raw [data-server]")).toBeHidden();
  await expect(t.locator('tr[data-table="daily_prices"]')).toContainText("몰라요");
});

test("글 · 대비 · 390 — 영어 대문자 소제목·이모지·툴팁·em-dash 0 · 라이트/다크 AA · 확인 창 AA · 가로 넘침 0", async ({ page }) => {
  await open(page);
  await expect(page.locator(".t-honesty-row").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(800);
  const r = await page.locator(".dsx").evaluate((root) => {
    const texts: string[] = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n: Node | null;
    while ((n = walk.nextNode())) {
      const el = n.parentElement!; const s = (n.textContent ?? "").trim();
      if (!s || !el.getClientRects().length || el.closest("[data-server],[data-mono]")) continue;
      texts.push(s);
    }
    return { texts, titles: root.querySelectorAll("[title]").length };
  });
  expect(r.texts.filter((s) => s.includes("—")), "em-dash").toEqual([]);
  expect(r.texts.filter((s) => /\b(DATA SOURCES|TOOL READINESS|TABLE COVERAGE|UNIVERSE COVERAGE|INGEST|REGISTRY|MACRO TOKENS|TICKER COVERAGE|MODE|MOCK|REAL|KEYS|ON DEMAND)\b/.test(s)), "영어 대문자").toEqual([]);
  expect(r.texts.filter((s) => /[★✓✗●○↻]|\p{Extended_Pictographic}/u.test(s)), "이모지·기호").toEqual([]);
  expect(r.titles, "title 툴팁").toBe(0);
  const light = await page.evaluate<AuditResult>(contrastAudit(".dsx"));
  expect(light.low, "라이트").toEqual([]);
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(300);
  const dark = await page.evaluate<AuditResult>(contrastAudit(".dsx"));
  expect(dark.low, "다크").toEqual([]);
  expect(dark.bright, "다크 밝은 판").toEqual([]);
  await page.locator('[data-act="ingest-all"]').click();
  await expect(page.locator(".dsx-dlg")).toBeVisible();
  const dlgDark = await page.evaluate<AuditResult>(contrastAudit(".dsx-dlg"));
  expect(dlgDark.low, "확인 창 다크").toEqual([]);
  expect(dlgDark.bright, "확인 창 다크 밝은 판").toEqual([]);
  await page.keyboard.press("Escape");
  await page.evaluate(() => document.documentElement.classList.remove("dark"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(600);
  const over = await page.evaluate(() => {
    const m = document.querySelector(".terminal-main") as HTMLElement;
    return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
  });
  expect(over).toBeLessThanOrEqual(0);
  await page.locator('[data-act="ingest-all"]').click();
  const dlgLight = await page.evaluate<AuditResult>(contrastAudit(".dsx-dlg"));
  expect(dlgLight.low, "확인 창 라이트").toEqual([]);
  const box = await page.locator(".dsx-dlg").boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy();
});
