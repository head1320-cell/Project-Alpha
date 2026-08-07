import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 06 STRESS · 07 ATTRIBUTION · 08 EXECUTION · 09 JOURNAL (A6)
// ─────────────────────────────────────────────────────────────────────────────
// ★이 네 라우트는 지금까지 어떤 하한·정직성 스펙에도 들어간 적이 없다★
// `allocation-stages.spec.ts` 의 ROUTES 는 5개(0M·01·03·04·05)이고, A4 는 overview 와
// alphalab 을 덮었다. 그 사이 06~09 의 자체 패밀리(`.as-bt-* · .as-exec-* · .as-attr-* ·
// .as-health-* · .as-jr-* · .as-krs-* · .as-dj-* · .as-rr-*`)는 한 번도 측정되지 않았다.
// 다크 스윕(aas-dark.spec.ts)은 이 라우트들을 방문했지만 **대비**만 봤다.
//
// ★루프 앞에서 개수를 먼저 단언한다★ 이번 세션에서 세 번, 조건에 감싸이거나 대상이
// 0개라 조용히 통과하는 "가드 모양의 무가드" 를 만들었다. 모든 루프 앞에 하한이 있다.
// ═══════════════════════════════════════════════════════════════════════════════

const ROUTES: [path: string, label: string][] = [
  ["/allocation/stress", "06 STRESS"],
  ["/allocation/explain", "07 ATTRIBUTION"],
  ["/allocation/execution", "08 EXECUTION"],
  ["/allocation/journal", "09 JOURNAL"],
];

async function seed(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
}

/**
 * 시드에 더해 **최적화까지 돌린** 세션을 만든다.
 *
 * ★첫 실행에서 세 테스트가 여기서 걸렸다★ 07 의 사전 비중 분해도, 08 의 실행 준비실
 * 전체도, 09 의 저널 저장 버튼도 전부 `result` 가 있어야 렌더된다. 목표만 고른 세션은
 * 보유 종목은 있지만 분석 결과가 없어서, 세 테스트가 각자의 "검사 대상이 없다" 가드에
 * 걸렸다 — 가드는 의도대로 동작한 것이고(빈 화면을 통과시키지 않았다), 준비가 부족했던
 * 것은 테스트 쪽이다.
 */
/**
 * 스테이지 이동은 **클라이언트 라우팅**으로 한다.
 *
 * ★`page.goto()` 는 결과를 버린다 (두 번째 실행에서 잡힘)★ 보유 종목은 localStorage 에
 * 남지만 `result`(analyze 응답)는 Provider 의 메모리 상태다. `page.goto` 는 전체
 * 리로드라 07·08·09 가 전부 "결과 없음" 분기로 떨어졌다 — 최적화를 돌려 놓고도.
 * 위저드 스텝 버튼은 `router.push` 라 세션이 유지된다.
 */
async function gotoStage(page: Page, n: string, label: string, href: string) {
  await page.locator(".aas-wiz-step, .aas-wiz-book")
    .filter({ hasText: new RegExp(`${n}\\s*${label}`) }).first().click();
  // ★목적지를 지목해서 기다린다★ 첫 판은 `/allocation/` 로 기다렸는데, 그건 **지금
  // 있는 주소**에도 매칭돼서 즉시 통과했다. 클릭 직후 아직 05 인 DOM 을 조회하게 되고,
  // 07·08 이 "결과 없음" 으로 읽혔다. 09 는 우연히 통과해서 더 위험했다.
  await page.waitForURL(new RegExp(`${href.replace(/\//g, "\\/")}$`), { timeout: 15_000 });
  await page.waitForLoadState("networkidle");
}

async function seedWithResult(page: Page) {
  await seed(page);
  // 05 의 `.as-run` 이 최적화 트리거다 (optimize/page.tsx:110). `/allocation/analyze` 는
  // 순수 계산 엔드포인트라 서버에 아무것도 남기지 않는다 — allocation-stages.spec.ts 가
  // 같은 이유로 스텁 대신 실제 실행을 쓴다. 스텁은 화면이 읽는 필드를 다 못 채워서
  // 서브트리가 통째로 안 그려지는 실패를 이미 한 번 만들었다.
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  await page.locator(".as-run").click();
  await expect(page.locator(".as-card", { hasText: "SUMMARY METRICS" }).first())
    .toBeVisible({ timeout: 45_000 });
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. ★06 — available 인데 충격이 null 이면 초록 +0.0% 가 아니다★
// ─────────────────────────────────────────────────────────────────────────────
test("★06: 산출되지 않은 시나리오 충격이 초록 +0.0% 로 찍히지 않는다★", async ({ page }) => {
  // A4-V1 이 00 OVERVIEW 에서 고친 것과 **같은 결함**이 06 에 그대로 살아 있었다:
  //   fmtSign(portfolio_shock_pct ?? 0, 1)  +  color: (x ?? 0) >= 0 ? bull : bear
  // → null 이면 초록 `+0.0%`. 스트레스 화면에서 초록 0% 는 "이 시나리오는 내
  // 포트폴리오를 건드리지 않는다" 로 읽힌다. 눈으로는 절대 안 잡힌다 — 건강해 보인다.
  await seed(page);
  // ★스텁 범위를 두 번 좁혔다 — 두 번 다 실행이 알려 줬다★
  // 1판 `**/allocation/stress**` 는 **문서 내비게이션**까지 매칭해서, 페이지로 이동하는
  //     순간 브라우저가 이 JSON 을 본문으로 렌더했다.
  // 2판 `**/api/backend/**/stress**` 는 형제 엔드포인트 세 개(`stress-scenarios` ·
  //     `stress-catalog` · `stress-correlation`)까지 삼켰다. 시나리오 목록이 배열이
  //     아니게 되면서 `cats.map` 이 터져 화면이 client-side exception 으로 죽었다.
  // 정확히 하나의 경로만 가로챈다. 글롭의 `**` 는 `/` 를 넘으므로 정규식을 쓴다.
  await page.route(/\/api\/v1\/allocation\/stress(\?|$)/, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        label: "테스트 가정 시나리오", mode: "hypothetical", available: true,
        portfolio_shock_pct: null, rows: [], note: "",
        reason: "구성 종목의 팩터 노출이 없어 충격을 산출하지 못했습니다",
      }),
    });
  });
  await page.goto("/allocation/stress", { waitUntil: "networkidle" });

  const detail = page.locator(".as-card", { hasText: "SCENARIO DETAIL" }).first();
  await expect(detail).toBeVisible();
  const head = detail.locator(".as-shock-head");
  await expect(head).toBeVisible();

  // 숫자가 아예 없어야 한다 — `0.0%` 도 `+0.0%` 도.
  const text = (await head.innerText()).trim();
  expect(text, `충격 자리에 숫자가 찍혔다: ${text}`).not.toMatch(/[-+]?\d/);
  // 사유는 보여야 한다. 숫자를 지우고 아무 말도 안 하면 그것도 정직이 아니다.
  await expect(head).toContainText("산출 불가");
  await expect(head).toContainText("팩터 노출");

  // bull 색이 어디에도 입혀지지 않았는지 — 색만으로 "좋다" 를 말하던 자리다.
  const bull = await page.evaluate(() => {
    const el = document.querySelector(".as-shock-head");
    if (!el) return "NO-NODE";
    const want = getComputedStyle(document.documentElement).getPropertyValue("--color-bull").trim();
    const hit = [el, ...Array.from(el.querySelectorAll("*"))]
      .filter((n) => getComputedStyle(n).color === want);
    return `${hit.length}|${want}`;
  });
  expect(bull, "충격 미산출 상태에 상승색이 남아 있다").toMatch(/^0\|/);
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. ★07 — 실행 전 사전 비중 분해는 0.0% 가 아니라 미계산★
// ─────────────────────────────────────────────────────────────────────────────
test("★07: 사전 비중 분해의 시장·뷰 칼럼이 0.0% 를 지어내지 않는다★", async ({ page }) => {
  // `flow.market[c] ?? 0` / `flow.view_applied[c] ?? 0` — A5 가 03 THESIS 에서 고친 쌍이
  // 07 에 그대로 남아 있었다. "시장이 이 자산을 0% 로 본다" 와 "시장 사전분포가 없다" 는
  // 완전히 다른 문장이다.
  //
  // ★변이 프로브가 이 테스트의 첫 판을 기각했다★
  // 첫 판은 최적화를 돌린 뒤 "셀은 숫자이거나 미계산이다" 만 확인했다. 그런데 실행 후에는
  // `flow.market` 이 **전부 채워져** 있어서 결측 자체가 존재하지 않는다 — `?? 0` 을 되돌려도
  // 초록이었다. 검사할 상태를 만들지 않고 검사한 셈이고, 이 저장소에서 네 번째로 나온
  // "가드 모양의 무가드" 다.
  // 이번 판은 **결측을 실제로 만든다**: 실제 응답을 받아 `flow` 두 사전만 비우고 돌려준다.
  // 스텁을 손으로 짜지 않는 이유는 A5 에서 겪었다 — 화면이 읽는 필드를 다 못 채우면
  // 서브트리가 통째로 안 그려져서 또 조용히 통과한다.
  await seed(page);
  await page.route(/\/api\/v1\/allocation\/analyze(\?|$)/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    if (body?.flow) { body.flow.market = {}; body.flow.view_applied = {}; }
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  await page.locator(".as-run").click();
  await expect(page.locator(".as-card", { hasText: "SUMMARY METRICS" }).first())
    .toBeVisible({ timeout: 45_000 });
  await gotoStage(page, "07", "ATTRIBUTION", "/allocation/explain");

  const adv = page.locator("details", { hasText: "사전 비중 분해" }).first();
  await expect(adv, "사전 비중 분해 섹션이 없다 — 검사 대상이 없다")
    .toBeVisible({ timeout: 20_000 });
  await adv.locator("summary").click();
  const rows = adv.locator("tbody tr");
  expect(await rows.count(), "분해 표의 행 수 (0 이면 조용히 통과한다)").toBeGreaterThan(0);

  // ① Market · ② View(BL) 는 **전부** 미계산이어야 한다 — flow 를 비웠기 때문이다.
  // `0.0%` 가 하나라도 보이면 그것이 지어낸 값이다.
  const cells = await rows.evaluateAll((trs) => trs.flatMap((tr) => {
    const td = Array.from(tr.querySelectorAll("td"));
    return [td[1], td[2]].filter(Boolean).map((c) => ({
      text: (c!.textContent || "").trim(),
      na: !!c!.querySelector(".aas-cmp-na"),
    }));
  }));
  expect(cells.length, "검사한 셀 수").toBeGreaterThan(0);
  const fabricated = cells.filter((c) => !c.na);
  expect(fabricated.map((c) => c.text), "결측인데 숫자가 찍힌 셀").toEqual([]);
  for (const c of cells) expect(c.text).toContain("미계산");
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. ★09 — 정책 백테스트가 레일 안에 있으면 안 된다★
// ─────────────────────────────────────────────────────────────────────────────
test("★09: 정책 백테스트는 340px 레일이 아니라 전폭 밴드에 있다★", async ({ page }) => {
  // 컨트롤 5 + KPI 10 + Recharts 3 + `1+N+1` 열 비중표가 `.as-ws-jr` 의 340px 레일에
  // 들어 있었다. `.as-bt-wtbl` 은 nowrap 이라 자산 수와 무관하게 항상 가로 스크롤이
  // 생겼다. DOM 위치만이 아니라 **실제 렌더 폭**을 재는 이유가 이것이다.
  await page.setViewportSize({ width: 1440, height: 900 });
  await seed(page);
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });

  const bt = page.locator(".as-bt");
  await expect(bt).toBeVisible();

  const inAside = await bt.evaluate((e) => !!e.closest(".as-ws2 > aside"));
  expect(inAside, "정책 백테스트가 아직 레일(aside) 안에 있다").toBe(false);

  const railW = await page.locator(".as-ws2").evaluate(
    (e) => parseFloat(getComputedStyle(e).gridTemplateColumns.split(/\s+/)[0]));
  const btW = await bt.evaluate((e) => e.getBoundingClientRect().width);
  expect(railW, "레일 폭을 못 읽었다").toBeGreaterThan(100);
  expect(btW, `정책 백테스트 폭 ${btW}px 이 레일 폭 ${railW}px 을 넘지 못했다`)
    .toBeGreaterThan(railW * 1.5);
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. ★08 — 근거가 툴팁 밖으로 나왔는가★
// ─────────────────────────────────────────────────────────────────────────────
test("★08: 비용 구성·표 헤더·아이콘 버튼이 호버 없이 읽힌다★", async ({ page }) => {
  await seedWithResult(page);
  await gotoStage(page, "08", "EXECUTION", "/allocation/execution");

  // 실행 계획을 산출해야 주문표가 생긴다. 목표 배분이 없으면 빈 상태이므로,
  // 그 경우 검사 대상이 없다는 사실을 명시적으로 실패시킨다.
  // `count()` 는 기다리지 않는다 — 07 과 같은 이유로 자동 대기 단정으로 바꾼다.
  const run = page.locator(".as-exec-run");
  await expect(run, "실행 준비실이 빈 상태 — 목표 배분이 없다")
    .toBeVisible({ timeout: 20_000 });
  await run.click();
  await expect(page.locator(".as-exec-table")).toBeVisible({ timeout: 30_000 });

  // (a) 9열 주문표의 모든 열 헤더에 scope
  const ths = page.locator(".as-exec-table thead th");
  const thCount = await ths.count();
  expect(thCount, "주문표 헤더 수").toBeGreaterThan(5);
  const scopes = await ths.evaluateAll((els) => els.map((e) => e.getAttribute("scope")));
  expect(new Set(scopes), "모든 th 에 scope=col").toEqual(new Set(["col"]));

  // (b) 비용칩이 한 글자 + title 이 아니라 낱말이다
  const chips = page.locator(".as-exec-costchips span");
  const chipCount = await chips.count();
  expect(chipCount, "비용칩 수 (0 이면 조용히 통과한다)").toBeGreaterThan(0);
  const chipTexts = await chips.allInnerTexts();
  for (const t of chipTexts) {
    const label = t.trim().split(/\s+/)[0];
    expect(label.length, `비용칩 라벨이 한 글자다: "${t}"`).toBeGreaterThan(1);
  }
  // title= 로 되돌아가지 않았는지도 본다 — 낱말을 적고 title 도 남기면 회귀 신호다.
  const titled = await chips.evaluateAll((els) => els.filter((e) => e.hasAttribute("title")).length);
  expect(titled, "비용칩에 title 이 남아 있다").toBe(0);

  // (c) 단계·호가단위도 셀 안에서 읽힌다
  await expect(page.locator(".as-exec-stage").first()).toContainText("단계");
  await expect(page.locator(".as-exec-tick").first()).toContainText("호가단위");
});

// ─────────────────────────────────────────────────────────────────────────────
// 5. ★09 — 아이콘 전용 삭제 버튼에 접근 가능한 이름★
// ─────────────────────────────────────────────────────────────────────────────
test("09: 저널 삭제 버튼이 접근 가능한 이름을 가진다", async ({ page }) => {
  // 저널을 하나 만들어야 `.as-x` 가 생긴다. 시드 세션에는 없다 —
  // 없는 상태로 루프를 돌면 0개를 검사하고 통과한다(A4 에서 실제로 겪은 실패다).
  // 그리고 저장 버튼은 `result` 가 있어야 활성이므로 최적화까지 돌린 세션이 필요하다.
  await seedWithResult(page);
  await gotoStage(page, "09", "JOURNAL", "/allocation/journal");
  const nameInput = page.locator(".as-jr-field", { hasText: "이름" }).locator("input").first();
  await nameInput.fill("A6 접근성 확인용 저널");
  // ★hasText 는 부분 일치라 strict mode 위반이었다★ DecisionJournal 도 `.as-run` 에
  // "의사결정 저널 저장" 을 달고 있어서 `hasText: "저널 저장"` 이 둘 다 잡았다.
  // 이름이 정확히 일치하는 역할 로케이터로 지목한다.
  const save = page.getByRole("button", { name: "저널 저장", exact: true });
  await expect(save).toBeEnabled({ timeout: 15_000 });
  await save.click();

  const del = page.locator(".as-jr-entry .as-x");
  await expect(del.first()).toBeVisible();
  const names = await del.evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")));
  expect(names.length, "삭제 버튼 수").toBeGreaterThan(0);
  for (const n of names) expect(n, "aria-label 없는 아이콘 버튼").toMatch(/삭제/);
});

// ─────────────────────────────────────────────────────────────────────────────
// 6·7. 타입 하한 + 라이트/다크 대비 — 네 라우트 전부
// ─────────────────────────────────────────────────────────────────────────────
for (const [path, label] of ROUTES) {
  test(`${label}: 12px 산문 · 11px 크롬 하한`, async ({ page }) => {
    await seed(page);
    await page.goto(path, { waitUntil: "networkidle" });
    const res = await page.locator(".aas-root").evaluate((root) => {
      const out: string[] = [];
      let checked = 0;
      for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
        checked++;
        const px = parseFloat(cs.fontSize);
        if (px < 11) out.push(`${el.tagName}.${(el.getAttribute("class") || "").split(" ")[0]} ${px}px :: ${(el.textContent || "").trim().slice(0, 18)}`);
      }
      return { checked, out: [...new Set(out)] };
    });
    expect(res.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(20);
    expect(res.out, "11px 미만 텍스트").toEqual([]);
  });

  test(`${label}: 라이트·다크 양쪽 WCAG AA`, async ({ page }) => {
    const AUDIT = contrastAudit(".aas-root");
    await seed(page);
    await page.goto(path, { waitUntil: "networkidle" });

    const light = await page.evaluate<AuditResult>(AUDIT);
    expect(light.checked, "라이트에서 검사한 노드 수").toBeGreaterThan(20);
    expect(light.low, `${label}: 라이트 AA 미달`).toEqual([]);

    await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.waitForTimeout(200);
    const dark = await page.evaluate<AuditResult>(AUDIT);
    expect(dark.checked, "다크에서 검사한 노드 수").toBeGreaterThan(20);
    expect(dark.low, `${label}: 다크 AA 미달`).toEqual([]);
    expect(dark.bright, `${label}: 다크에서 밝은 배경이 남았다`).toEqual([]);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// 8. ★09 — 정책 백테스트 차트가 다크에서도 토큰을 따라간다★
// ─────────────────────────────────────────────────────────────────────────────
test("★09: 정책 백테스트를 실행한 상태에서 다크 대비★", async ({ page }) => {
  // A4-X3 는 parts.tsx 의 툴팁·마커만 토큰화했다. PolicyBacktest 는 Recharts 를 직접
  // 쓰기 때문에 그 스윕에 없었고, `#16a34a`(3.16:1) 가 KPI **글자색**으로 남아 있었다.
  // 차트가 그려진 상태에서 재지 않으면 이 결함은 영원히 안 잡힌다 — 실행 전에는
  // 문제의 노드가 DOM 에 없기 때문이다.
  await seed(page);
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });
  await page.locator(".as-fb-apply", { hasText: "정책 백테스트" }).first().click();
  await expect(page.locator(".as-bt-kpi").first()).toBeVisible({ timeout: 40_000 });

  const AUDIT = contrastAudit(".as-bt");
  const light = await page.evaluate<AuditResult>(AUDIT);
  expect(light.checked, "라이트에서 검사한 노드 수").toBeGreaterThan(10);
  expect(light.low, "정책 백테스트 라이트 AA 미달").toEqual([]);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(250);
  const dark = await page.evaluate<AuditResult>(AUDIT);
  expect(dark.checked, "다크에서 검사한 노드 수").toBeGreaterThan(10);
  expect(dark.low, "정책 백테스트 다크 AA 미달").toEqual([]);
  expect(dark.bright, "정책 백테스트 다크에서 밝은 배경이 남았다").toEqual([]);
});

// ─────────────────────────────────────────────────────────────────────────────
// 9. ★스윕이 볼 수 없는 상태를 스윕이 볼 수 있게 만든다★
// ─────────────────────────────────────────────────────────────────────────────
test("★조건부 상태(취소·반려·나쁜 결과·비중축소)도 다크에서 AA★", async ({ page }) => {
  // 이 세션에서 같은 결함을 네 번 만났다. 전부 모양이 같다: 배경은 테마 토큰이라
  // 다크에서 뒤집히는데 **글자만 하드코딩**이라 어두운 색 위 어두운 색이 된다.
  //   `.as-bt-badge.mock/.real`  ← 정책 백테스트를 **실행해야** 렌더된다
  //   `.as-exec-status.cancelled/.rejected` · `.as-dq.bad_outcome_bad_process`
  //   `.as-health-pill.de_risk`  ← 계획을 취소하거나 알파가 비중축소돼야 렌더된다
  //
  // 넷 다 A4 의 다크 스윕이 초록이었다 — 그 상태를 **한 번도 그린 적이 없기** 때문이다.
  // 통과가 아니라 부재였다. 그래서 여기서는 상태를 직접 만들어 놓고 잰다:
  // 실제 규칙이 걸리도록 `.aas-root` 안에 같은 클래스의 노드를 심고 감사한다.
  // (계산으로는 약 2.35:1 이 나왔지만, 계산은 실제 캐스케이드를 모른다.)
  await seed(page);
  await page.goto("/allocation/execution", { waitUntil: "networkidle" });

  const CASES = [
    ["as-exec-status cancelled", "취소됨"],
    ["as-exec-status rejected", "반려됨"],
    ["as-dq good_outcome_good_process", "좋은 결과"],
    ["as-dq bad_outcome_bad_process", "나쁜 결과"],
    ["as-dq good_outcome_bad_process", "운이 좋았다"],
    ["as-dq bad_outcome_good_process", "운이 나빴다"],
    ["as-health-pill de_risk", "비중축소 3"],
    ["as-bt-badge mock", "MOCK 데이터"],
    ["as-bt-badge real", "실데이터"],
  ] as const;

  const planted = await page.evaluate((cases) => {
    const root = document.querySelector(".aas-root");
    if (!root) return 0;
    const host = document.createElement("div");
    host.id = "a6-conditional-probe";
    for (const [cls, text] of cases) {
      const el = document.createElement("span");
      el.className = cls;
      el.textContent = text;
      host.appendChild(el);
    }
    root.appendChild(host);
    return host.childElementCount;
  }, CASES);
  expect(planted, "상태 노드를 심지 못했다 — .aas-root 가 없다").toBe(CASES.length);

  const AUDIT = contrastAudit("#a6-conditional-probe");
  const light = await page.evaluate<AuditResult>(AUDIT);
  expect(light.checked, "라이트에서 검사한 노드 수").toBeGreaterThanOrEqual(CASES.length);
  expect(light.low, "조건부 상태 라이트 AA 미달").toEqual([]);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(AUDIT);
  expect(dark.checked, "다크에서 검사한 노드 수").toBeGreaterThanOrEqual(CASES.length);
  expect(dark.low, "조건부 상태 다크 AA 미달").toEqual([]);
});
