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
  // L2 밴드도 전부 포함한다 — 여기서 하나라도 빠지면 그 밴드는 모션을 끈 사용자에게
  // 빈 칸으로 보이고, 그 사실을 아무도 모른다.
  const sel = ".lp-module, .lp-ev, .lp-pillar, .lp-pipe-step, .lp-guard-item, .lp-src, .lp-quote";
  const els = await page.locator(sel).all();
  expect(els.length, "검사 대상이 비면 이 테스트는 아무것도 지키지 못한다").toBeGreaterThan(25);
  for (const el of els) {
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

  // 이전 페이지가 싣고 있던 낡은 수치가 되돌아오지 않는지. 실측은 1,539 / 181 이다.
  const body = await page.locator("body").innerText();
  expect(body, "낡은 TEST SUITE 470 이 되살아나면 안 된다").not.toContain("470");
});

// ═══════════════════════════════════════════════════════════════════════════════
// L2 — 확장된 밴드들
// ─────────────────────────────────────────────────────────────────────────────
// 레퍼런스(Aladdin Wealth · Solovis)의 밴드 구성을 가져오되, 두 곳이 기대는 것들
// (고객 후기 · 수상 · 파트너 로고 · 보도자료 · 영상)은 이 프로젝트에 없다. 없는 것을
// 지어내지 않았다는 사실 자체를 여기서 검사할 수는 없지만, **대신 넣은 것들이 진짜인지**는
// 검사할 수 있다 — 인용한 테스트 경로, 출처의 한계, 수치의 재현 방법.
// ═══════════════════════════════════════════════════════════════════════════════

test("L2: 세 기둥이 번호와 함께 놓인다", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  const pillars = page.locator(".lp-pillar");
  await expect(pillars).toHaveCount(3);
  const ns = await pillars.locator(".lp-pillar-n").allInnerTexts();
  expect(ns.map((s) => s.trim())).toEqual(["01", "02", "03"]);
  // 기둥마다 한 줄 요약과 본문이 모두 있어야 한다 — 제목만 있는 상자가 아니다.
  for (const p of await pillars.all()) {
    expect((await p.locator(".lp-pillar-lede").innerText()).trim().length).toBeGreaterThan(5);
    expect((await p.locator(".lp-pillar-body").innerText()).trim().length).toBeGreaterThan(30);
  }
});

test("L2: 파이프라인 일곱 단계가 순서대로, 각자 넘기는 신원과 함께 놓인다", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  const steps = page.locator(".lp-pipe-step");
  await expect(steps).toHaveCount(7);

  // DOM 순서가 곧 근거 경로의 순서다.
  const ns = await steps.locator(".lp-pipe-n").allInnerTexts();
  expect(ns.map((s) => s.trim())).toEqual(["1", "2", "3", "4", "5", "6", "7"]);

  // ★핵심★ 각 단계는 다음 단계로 **신원**을 넘긴다 — 빈 칸이면 그 주장이 무너진다.
  for (const s of await steps.all()) {
    expect((await s.locator(".lp-pipe-carries").innerText()).trim().length).toBeGreaterThan(0);
  }
  // 재현 좌표의 이름들이 실제로 화면에 있어야 한다.
  const band = await page.locator(".lp-pipe").innerText();
  for (const id of ["snapshot_id", "name@version", "pack_id@해시", "run_id"]) {
    expect(band, `${id} 가 파이프라인에 없다`).toContain(id);
  }
});

test("★L2: 보장 여섯 개가 각각 그것을 강제하는 테스트를 인용한다★", async ({ page }) => {
  // 마케팅 문구 대신 실행되는 근거를 적는다는 것이 이 밴드의 전부다.
  // 인용 경로가 실재하는지는 tests/test_landing_claims.py 가 CI 에서 따로 검사한다.
  await page.goto("/", { waitUntil: "networkidle" });
  const items = page.locator(".lp-guard-item");
  await expect(items).toHaveCount(6);

  for (const it of await items.all()) {
    expect((await it.locator(".lp-guard-claim").innerText()).trim().length).toBeGreaterThan(8);
    const t = (await it.locator(".lp-guard-test").innerText()).trim();
    expect(t, "보장에는 그것을 강제하는 테스트 경로가 붙어야 한다").toMatch(/^tests\/test_[a-z0-9_]+\.py$/);
  }
});

test("★L2: 데이터 출처마다 한계가 함께 적힌다★", async ({ page }) => {
  // 출처만 나열하면 데이터가 완전하다는 인상을 준다. 실제로는 쿼터·지연·구간 제한이 있고,
  // 그것이 화면의 값이 비는 이유가 된다 — 그 이유를 첫 화면에서 감추지 않는다.
  await page.goto("/", { waitUntil: "networkidle" });
  const srcs = page.locator(".lp-src");
  await expect(srcs).toHaveCount(5);

  for (const s of await srcs.all()) {
    expect((await s.locator(".lp-src-k").innerText()).trim().length).toBeGreaterThan(1);
    const limit = (await s.locator(".lp-src-limit").innerText()).trim();
    expect(limit.length, "출처에 한계 문장이 없다").toBeGreaterThan(15);
  }
});

test("L2: 인용은 고객 후기가 아니라 저장소 규약이고, 출처를 밝힌다", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page.locator(".lp-quote-t")).toContainText("코드가 진실");
  // ★출처가 파일명으로 적혀 있어야 한다★ 익명 인용은 지어낸 것과 구별되지 않는다.
  await expect(page.locator(".lp-quote-src")).toContainText("CLAUDE.md");
});

test("L2: FAQ 다섯 항목이 클릭으로 열리고 답이 비어 있지 않다", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  const items = page.locator(".lp-faq-item");
  await expect(items).toHaveCount(5);

  for (const it of await items.all()) {
    // 네이티브 <details> — 쉴 때는 닫혀 있다.
    expect(await it.evaluate((e) => (e as HTMLDetailsElement).open)).toBe(false);
    await it.locator("summary").click();
    expect(await it.evaluate((e) => (e as HTMLDetailsElement).open)).toBe(true);
    expect((await it.locator(".lp-faq-a").innerText()).trim().length).toBeGreaterThan(40);
  }
});

test("★L2: 증거 수치는 카운트업하지 않는다 — 처음부터 최종값이다★", async ({ page }) => {
  // ★이 페이지에서 가장 조용한 거짓말이었다★
  // CountUp 은 1.1초 동안 최종값이 아닌 수를 그린다. 스크린샷을 찍으면 BACKEND TESTS 가
  // 1,467 로 나오는데 바로 밑 캡션은 1,534 라고 적혀 있었다. 모든 수치가 참이라는 것이
  // 유일한 주장인 밴드에서, 참값을 향해 올라가는 그 1.1초는 그냥 거짓이다.
  //
  // ★처음에 쓴 단언은 이 회귀를 못 잡았다★
  // "로드 직후 값을 읽어 최종값과 같은지" 보게 했는데, Playwright 는 단언을 자동으로
  // 재시도한다 — 1.1초짜리 카운트업이 끝난 뒤에 읽히니 언제나 최종값이었다.
  // 프로브로 확인했다: CountUp 을 되살려도 초록이었다. 정착한 상태를 아무리 봐도
  // "도중에 무엇을 보여 줬는가" 는 알 수 없다. **변이 자체를 기록해야 한다.**
  // rAF 로 매 프레임 표본을 남긴다. (MutationObserver 로 먼저 해 봤는데 기록이 0건이었다 —
  // 왜인지 파고들기보다, 프레임마다 직접 읽는 쪽이 단순하고 확실하다. 1.8초 × 60fps ≈ 100 표본
  // 이라 1.1초짜리 애니메이션을 놓칠 수 없다.)
  await page.addInitScript(() => {
    const seen: Record<string, string[]> = {};
    (window as unknown as { __evSeen: Record<string, string[]> }).__evSeen = seen;
    const tick = () => {
      document.querySelectorAll(".lp-ev-v").forEach((el, i) => {
        (seen[String(i)] ||= []).push((el.textContent || "").trim());
      });
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

  await page.goto("/", { waitUntil: "networkidle" });
  // 카운트업은 뷰포트 진입(IntersectionObserver, threshold 0.45)에서 시작한다 —
  // 스크롤해 넣지 않으면 되살아나도 발화하지 않아 프로브가 무의미해진다.
  await page.locator(".lp-ev").first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(1800);   // 1,100ms 애니메이션 + 여유

  const seen = await page.evaluate(() => {
    const src = (window as unknown as { __evSeen: Record<string, string[]> }).__evSeen ?? {};
    return Object.fromEntries(Object.entries(src).map(([k, v]) => [k, [...new Set(v)]]));
  });
  // 표본이 없으면 이 테스트는 아무것도 지키지 못한다 — 먼저 그것부터 막는다.
  expect(Object.keys(seen).length, "증거 항목을 하나도 관찰하지 못했다").toBeGreaterThan(2);
  for (const [i, texts] of Object.entries(seen)) {
    expect(texts, `증거 #${i} 가 도중에 다른 수를 보여 줬다`).toHaveLength(1);
  }

  // 그리고 그 하나뿐인 값이 캡션과 맞아야 한다.
  await expect(page.locator(".lp-ev", { hasText: "BACKEND TESTS" }).locator(".lp-ev-v")).toHaveText("1,539");
  await expect(page.locator(".lp-ev", { hasText: "E2E TESTS" }).locator(".lp-ev-v")).toHaveText("181");
});

test("L2: 푸터 링크가 전부 실재하는 라우트를 가리킨다", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  const links = page.locator(".lp-footer-list a");
  const n = await links.count();
  expect(n, "푸터 링크").toBeGreaterThan(14);

  const hrefs = await links.evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  expect(hrefs.every((h) => !!h && h.startsWith("/")), "내부 라우트만 있어야 한다").toBe(true);
  // 저장소 경로 열은 링크가 아니다 — 앱 라우트가 없는데 링크처럼 보이면 거짓말이 된다.
  await expect(page.locator(".lp-footer-path").first()).toBeVisible();
  expect(await page.locator(".lp-footer-path a").count(), "경로는 링크가 아니다").toBe(0);
});

test("L2: 고지 바가 기본값의 한계를 첫 줄에서 말한다", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  const bar = page.locator(".lp-topbar");
  await expect(bar).toBeVisible();
  await expect(bar).toContainText("KIS_USE_MOCK=1");
  await expect(bar).toContainText("dry_run=True");
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

    // ★L2 밴드도 어느 폭에서나 온전히 있어야 한다★
    // 390px 에서 헤더 앵커가 2개 → 5개가 되면서 실제로 57px 넘쳤다(실측). 줄바꿈으로 고쳤고,
    // 이 단언이 그 회귀를 잡는다.
    await expect(page.locator(".lp-pillar")).toHaveCount(3);
    await expect(page.locator(".lp-pipe-step")).toHaveCount(7);
    await expect(page.locator(".lp-guard-item")).toHaveCount(6);
    await expect(page.locator(".lp-src")).toHaveCount(5);
    await expect(page.locator(".lp-faq-item")).toHaveCount(5);

    // 좁은 폭이라고 신원·한계를 토글 뒤로 숨기지 않는다(P10 §8 과 같은 계약).
    await expect(page.locator(".lp-topbar")).toBeVisible();
    await expect(page.locator(".lp-guard-test").first()).toBeVisible();
    await expect(page.locator(".lp-src-limit").first()).toBeVisible();
    await expect(page.locator(".lp-deck-sample")).toBeVisible();
  });
}
