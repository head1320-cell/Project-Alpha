import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 랜딩(/) — 모듈 갤러리 (L1)
// ─────────────────────────────────────────────────────────────────────────────
// 이 라우트는 지금까지 전용 스펙이 없었다. 커버리지는 nav.spec.ts 안의 4줄이 전부였다.
//
// ★여기서 지키는 것 넷★
//   1) 호버로만 열리는 정보가 없다 — 키보드·터치에도 같은 내용이 도달한다.
//   2) 모션을 끄면 **빈 화면이 되지 않는다**. 등장 애니메이션의 기본값이 opacity:0 이라
//      reduced-motion 처리를 빠뜨리면 페이지가 통째로 사라진다. 조용한 실패다.
//   3) 스크롤이 브라우저 것 그대로다 — 연동은 하되 가로채지 않는다.
//   4) 증거 수치에 재현 방법이 붙어 있고 자리표시자가 없다.
// ═══════════════════════════════════════════════════════════════════════════════

const MODULE_HREFS = ["/screener", "/backtest", "/macro", "/insights", "/risk-tools", "/allocation"];

test("랜딩: 여섯 모듈 카드가 실제 라우트로 연결된다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto("/", { waitUntil: "networkidle" });

  const cards = page.locator(".lp-module");
  await expect(cards).toHaveCount(6);

  const hrefs = await cards.evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  expect(hrefs.sort()).toEqual([...MODULE_HREFS].sort());

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

test("★랜딩: 카드 상세가 호버 전용이 아니다 — 키보드 포커스로도 열린다★", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  const card = page.locator(".lp-module").first();
  const more = card.locator(".lp-module-more");

  // 쉴 때는 접혀 있다(레이아웃상 0 높이).
  const closed = await more.evaluate((e) => e.getBoundingClientRect().height);

  // 포커스만으로 열려야 한다. 마우스를 쓸 수 없는 사용자에게도 같은 정보가 있어야 한다.
  await card.focus();
  await expect(card).toBeFocused();
  await page.waitForTimeout(400);   // 전환 시간
  const focused = await more.evaluate((e) => e.getBoundingClientRect().height);

  expect(focused, "포커스 시 상세가 열려야 한다").toBeGreaterThan(closed);
  await expect(card.locator(".lp-module-desc")).toContainText(/\S/);
});

test("★랜딩: 모션을 꺼도 페이지가 비지 않는다★", async ({ page }) => {
  // 등장 애니메이션 기본값이 opacity:0 이라, reduced-motion 처리를 빠뜨리면 화면이
  // 통째로 사라진다 — 테스트는 초록인데 사용자는 빈 페이지를 보는 전형적인 조용한 실패다.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "networkidle" });

  await expect(page.locator(".lp-module")).toHaveCount(6);
  for (const el of await page.locator(".lp-module, .lp-ev").all()) {
    const op = await el.evaluate((e) => parseFloat(getComputedStyle(e).opacity));
    expect(op, "모션 OFF 에서 투명한 요소가 있으면 안 된다").toBeGreaterThan(0.9);
  }
  // 모션이 없으면 상세도 처음부터 열려 있어야 한다(전환이 없으니 열 방법이 없다).
  //
  // ★처음에는 여기서 높이만 쟀는데 그 단언은 아무것도 지키지 못했다★
  // reduced-motion 안전망을 통째로 지우고 돌려도 통과했다 — 그리드 컨테이너는 행이
  // 0fr 로 접혀도 자체 높이가 남기 때문이다. 실제로 사람이 못 읽게 만드는 것은 opacity 다.
  // 그래서 계산된 opacity 를 본다(프로브로 확인: 안전망을 지우면 이 줄이 빨개진다).
  const moreOpacity = await page.locator(".lp-module-more").first()
    .evaluate((e) => parseFloat(getComputedStyle(e).opacity));
  expect(moreOpacity, "모션 OFF 에서는 상세가 처음부터 읽혀야 한다").toBeGreaterThan(0.9);

  const body = await page.locator("body").innerText();
  expect(body.trim().length, "본문이 비면 안 된다").toBeGreaterThan(400);
});

test("★랜딩: 스크롤을 가로채지 않는다 (연동이지 jacking 이 아니다)★", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });

  // 프로그램 스크롤이 그대로 먹혀야 한다 — preventDefault 로 막거나 스냅으로 되돌리면 실패.
  await page.evaluate(() => window.scrollTo(0, 900));
  await page.waitForTimeout(350);
  const y = await page.evaluate(() => window.scrollY);
  expect(y, "스크롤이 취소되거나 되돌려지면 안 된다").toBeGreaterThan(400);

  // scroll-snap 으로 뷰포트를 가두지 않는다.
  const snap = await page.evaluate(() =>
    getComputedStyle(document.documentElement).scrollSnapType + "|" +
    getComputedStyle(document.body).scrollSnapType);
  expect(snap, "스크롤 스냅으로 가두지 않는다").toMatch(/none\|none/);
});

test("랜딩: 증거 수치마다 재현 방법이 붙고 자리표시자가 없다", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });

  const evs = page.locator(".lp-ev");
  expect(await evs.count(), "증거 항목").toBeGreaterThan(2);

  for (const ev of await evs.all()) {
    const v = (await ev.locator(".lp-ev-v").innerText()).trim();
    const how = (await ev.locator(".lp-ev-how").innerText()).trim();
    expect(v.length, "값이 비면 안 된다").toBeGreaterThan(0);
    // ★출처 없는 수치는 이 페이지에 있을 수 없다★
    expect(how.length, `${v} 의 재현 방법이 없다`).toBeGreaterThan(8);
    expect(v, "자리표시자를 렌더하지 않는다").not.toMatch(/^(TBD|--|—|N\/A)$/i);
  }

  // 이전 페이지가 싣고 있던 낡은 수치가 되돌아오지 않는지 — 실측은 1,534 / 163 이다.
  const body = await page.locator("body").innerText();
  expect(body, "낡은 TEST SUITE 470 이 되살아나면 안 된다").not.toContain("470");
});

test("★랜딩: 히어로 덱이 지어낸 수치를 실적으로 주장하지 않는다★", async ({ page }) => {
  // ★이 페이지에서 가장 위험했던 것★
  // 덱의 +24.6% / Sharpe 2.14 / 312 트레이드는 전부 HeroDeckLive.tsx 안의 리터럴인데,
  // 초록 점이 깜빡이는 `LIVE` 배지 아래 놓여 있었다. 퀀트 플랫폼의 첫 화면에서 그것은
  // 트랙 레코드로 읽힌다 — 바로 옆 문장이 "수치가 어디서 왔는지 말할 수 있는 것을
  // 우선합니다" 인데도. 배지 하나 되돌리면 다시 거짓말이 되므로 테스트로 못을 박는다.
  await page.goto("/", { waitUntil: "networkidle" });

  const deck = page.locator(".lp-deck");
  await expect(deck).toBeVisible();

  // 1) 덱 어디에도 LIVE / 실시간 주장이 없다.
  const deckText = await deck.innerText();
  expect(deckText, "지어낸 수치에 LIVE 를 붙이지 않는다").not.toMatch(/\bLIVE\b|실시간/i);
  await expect(page.locator(".lp-deck-live"), "맥동하는 LIVE 배지가 되살아나면 안 된다")
    .toHaveCount(0);

  // 2) 대신 예시라는 표시가 덱 안에 있다.
  await expect(deck.locator(".lp-deck-sample")).toContainText("예시");

  // 3) 배지는 짧아서 오해가 남는다 — 왜 실적이 아닌지 문장으로도 적혀 있어야 한다.
  const note = page.locator(".lp-deck-note");
  await expect(note).toBeVisible();
  await expect(note).toContainText("백테스트가 아닙니다");
});

for (const [w, h] of [[390, 844], [1280, 900], [1440, 900]] as [number, number][]) {
  test(`랜딩 ${w}px: 가로 넘침 없이 여섯 카드가 모두 있다`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto("/", { waitUntil: "networkidle" });

    await expect(page.locator(".lp-module")).toHaveCount(6);
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `가로 오버플로 @${w}`).toBeLessThanOrEqual(1);
  });
}
