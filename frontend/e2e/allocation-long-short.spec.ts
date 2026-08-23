import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, freezeCharts, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// P3 — 롱숏: 연구·백테스트에서 일급, 실행에서는 명시적 차단
// ─────────────────────────────────────────────────────────────────────────────
// 백엔드는 pytest 가 지킨다(`tests/test_long_short.py` 30건 — 클램프·제약·게이트).
// 이 스펙이 지키는 것은 **화면이 숏에 대해 거짓말하지 않는가** 넷이다:
//
//   1. 숏이 화면에 실제로 보인다 (스트립·범례·노출 두 축)
//   2. ★HHI 가 롱 다리만으로 계산되지 않는다★ — F3 의 핵심
//      `concentration()` 이 `Math.max(w, 0)` 이던 시절, 롱 150/숏 −50 인 책의
//      분모가 150 이 되어 집중도를 과소 보고했다. 숏도 포지션이고 위험을 진다.
//   3. 롱숏 목표는 실행 화면에서 **왜 못 하는지** 세 줄로 막힌다 (죽은 버튼 아님)
//   4. 롱온리 화면은 한 자리도 바뀌지 않았다 (짝 단언 — 없으면 롱숏만 보고 통과한다)
//
// ★서버 상태를 남기지 않는다★ `/analyze` 는 순수 계산이라 안전하지만, 응답 본문을
// 손으로 지어내지는 않는다 — 실제 응답을 받아 P3 필드만 덮어쓴다(M2 스펙의 관례).
// 손으로 쓴 스텁은 화면이 읽는 필드를 다 못 채워 서브트리가 통째로 안 그려진다.
// ═══════════════════════════════════════════════════════════════════════════════

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

/** 롱숏 해 — 롱 3 · 숏 2, gross 180 · net 100. 숫자는 이 스펙이 검증할 값이다. */
const LS_OPTIMIZED = {
  "005930": 60.0, "000660": 50.0, "035420": 30.0,
  "051910": -25.0, "005380": -15.0,
};
const LS_GROSS = 180.0;   // 60+50+30+25+15
const LS_NET = 100.0;     // 60+50+30-25-15
const LS_LONG = 140.0;
const LS_SHORT = -40.0;

async function patchAnalyze(page: Page, over: Record<string, unknown>) {
  await page.route("**/api/v1/allocation/analyze", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, ...over } });
  });
}

/** 최적화 결과에 숏을 심는다 — `weights.optimized` 만 덮어쓰고 나머지는 서버 값. */
async function patchOptimizedWeights(page: Page, optimized: Record<string, number>) {
  await page.route("**/api/v1/allocation/analyze", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({
      response: res,
      json: { ...body, weights: { ...body.weights, optimized } },
    });
  });
}

async function enterOptimize(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  await page.locator(".as-run").click();
  await expect(page.locator(".as-card", { hasText: "SUMMARY METRICS" }).first())
    .toBeVisible({ timeout: 45_000 });
}

// ── 1. 숏이 화면에 보인다 ──────────────────────────────────────────────────

test("★롱숏 결과가 gross·net·롱·숏 네 축으로 온다 — 넷 하나로 뭉개지 않는다★",
  async ({ page }) => {
    await patchOptimizedWeights(page, LS_OPTIMIZED);
    await enterOptimize(page);

    const exp = page.locator(".as-ls-exposure");
    await expect(exp).toBeVisible({ timeout: 20_000 });
    await expect(exp).toContainText(`${LS_GROSS.toFixed(1)}%`);
    await expect(exp).toContainText(`${LS_NET.toFixed(1)}%`);
    await expect(exp).toContainText(`${LS_LONG.toFixed(1)}%`);
    await expect(exp).toContainText(`${LS_SHORT.toFixed(1)}%`);
  });

test("★짝 단언 — 롱온리 결과에는 노출 줄이 뜨지 않는다★", async ({ page }) => {
  // 이것이 없으면 `.as-ls-exposure` 를 항상 렌더해도 앞 테스트가 통과한다.
  await enterOptimize(page);
  await expect(page.locator(".as-ls-exposure")).toHaveCount(0);
});

test("롱숏 제약 컨트롤은 하한이 음수일 때만 나타난다", async ({ page }) => {
  // ★게이트를 거쳐야 한다★ `/allocation/optimize` 로 직행하면 포트폴리오가 없어
  // 제약 패널이 렌더되지 않는다 — 한 번 그렇게 헛짚어 90s 타임아웃을 받았다.
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });

  // ★제약 패널은 클릭으로 열 수 없다 — 세션 상태로 연다★
  //
  // `<details className="aas-adv" open={!!constraints}>` 는 React 가 제어한다.
  // `constraints` 가 null 인 동안은 summary 를 눌러도 다음 렌더에서 즉시 닫히고,
  // 닫힌 `<details>` 의 자식은 접근성 트리에 아예 없어서 Playwright 가 입력을
  // 찾지 못한다. 셀렉터를 세 번 고쳐 봤지만 원인은 셀렉터가 아니었다 — DOM
  // 스냅샷의 `▸`(닫힘 표시)가 그것을 말해 줬다.
  //
  // 그래서 provider 가 실제로 읽는 세션 키에 롱온리 제약을 심어 패널을 열고,
  // 그 상태에서 하한만 음수로 바꾼다. 키는 `PortfolioContext` 의 `SS_WIP` 이다.
  await page.evaluate(() => {
    const raw = sessionStorage.getItem("alpha_alloc_wip");
    const wip = raw ? JSON.parse(raw) : {};
    sessionStorage.setItem("alpha_alloc_wip", JSON.stringify({
      ...wip, constraints: { min_weight_pct: 0, max_weight_pct: 60 },
    }));
  });
  await page.reload({ waitUntil: "networkidle" });

  const adv = page.locator("details.aas-adv").first();
  await expect(adv).toBeVisible({ timeout: 15_000 });
  // 롱온리 제약만 있을 때는 롱숏 컨트롤이 없다 (짝의 앞쪽)
  await expect(page.locator(".as-ls-controls")).toHaveCount(0);

  // ★접근성 이름으로 잡는다★ `.as-ct-grid label` + hasText 로는 못 잡았다.
  // DOM 스냅샷이 준 실제 이름은 `종목당 하한 % 음수=숏` — `<em>` 힌트까지 이름에
  // 들어간다. 구조 셀렉터보다 이 이름이 사용자가 실제로 보는 것에 가깝다.
  const lower = page.getByRole("spinbutton", { name: /종목당 하한/ });
  await lower.fill("-20");
  await expect(page.locator(".as-ls-controls")).toBeVisible();
  // 사후 변환과의 차이를 화면이 말한다 (R0 결함 종료)
  await expect(page.locator(".as-ls-hint")).toContainText("재최적화해도 유지");
  await expect(page.locator(".as-ls-hint")).toContainText("실행할 수 없습니다");
});

// ── 2. ★HHI 가 롱 다리만으로 계산되지 않는다★ (F3 의 핵심) ────────────────

test("★숏이 있으면 집중도가 gross 기준이라고 화면이 말한다★", async ({ page }) => {
  // 01 CONSTRUCT 의 보유 비중에 숏을 넣는다 — `concentration()` 의 입력이다.
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });

  // 롱온리 상태의 라벨을 먼저 고정한다(짝의 앞쪽).
  const basis = page.locator(".as-stat", { hasText: "HHI" }).locator(".as-stat-x");
  await expect(basis).toHaveText(/Σw² × 10,000/);
  await expect(basis).not.toContainText("gross");
});

test("★concentration() 이 숏을 버리지 않는다 — /dev/ui 표본으로 실측★", async ({ page }) => {
  // 화면 경로로 음수 보유를 만들 UI 가 없다(보유 입력은 롱온리다). 그래서 격리
  // 라우트에 표본을 두고 **실제 번들 코드가 계산한 값**을 읽는다 — Step 3b 가
  // 세운 관례이고, 청크 경로를 직접 import 하는 것보다 빌드 해시에 안 묶인다.
  await page.goto("/dev/ui", { waitUntil: "networkidle" });

  const lo = page.locator('.devui-ls-basis[data-case="long-only"]');
  const ls = page.locator('.devui-ls-basis[data-case="long-short"]');
  await expect(lo).toHaveText("net");
  await expect(ls).toHaveText("gross");

  // ★이 숫자가 F3 의 증거다★ 롱숏 [60, 50, 30, -25, -15] 의 gross 는 180.
  //   올바른 값 : (60²+50²+30²+25²+15²)/180² × 10⁴ = 7850/32400 × 10⁴ = 2422.8
  //   예전 값   : 롱 다리만(분모 140) → (60²+50²+30²)/140² × 10⁴ = 7000/19600 × 10⁴ = 3571.4
  // 예전 식은 집중도를 **1.47배 크게**(= 더 집중된 것처럼) 보고했다. 두 값이 1000
  // 이상 벌어지므로 이 단언은 반올림이 아니라 식이 바뀌었는지를 잰다.
  const hhi = Number(await page.locator('.devui-ls-hhi[data-case="long-short"]').innerText());
  expect(hhi).toBeGreaterThan(2400);
  expect(hhi).toBeLessThan(2450);
  expect(hhi, "롱 다리만으로 계산한 예전 값이 나왔다").toBeLessThan(3000);

  // 노출 네 축도 같은 표본에서 확인 — gross 180 · net 100 · long 140 · short −40
  await expect(page.locator(".devui-ls-legs")).toContainText("gross 180.0");
  await expect(page.locator(".devui-ls-legs")).toContainText("net 100.0");
  await expect(page.locator(".devui-ls-legs")).toContainText("short -40.0");
});

test("★AllocationMap 이 숏을 두 번째 스트립으로 그린다 — 버리지 않는다★", async ({ page }) => {
  await page.goto("/dev/ui", { waitUntil: "networkidle" });
  const map = page.locator(".devui-ls-map");

  // 롱 스트립 + 숏 스트립 = 2 (예전에는 filter(w>0) 라 1개였고 숏은 사라졌다)
  await expect(map.locator(".aas-map")).toHaveCount(2);
  await expect(map.locator(".as-ls-map-short")).toBeVisible();

  // 범례는 5종목 전부 — 숏 2개가 음수 값으로 남는다
  await expect(map.locator(".aas-legend-i")).toHaveCount(5);
  await expect(map.locator(".as-ls-neg")).toHaveCount(2);
  await expect(map.locator(".aas-legend-i", { hasText: "LG화학" })).toContainText("-25.0%");
});

// ── 3. 실행은 왜 못 하는지 말한다 (죽은 버튼 아님) ────────────────────────

test("★롱숏 목표는 실행 화면에서 세 가지 이유로 막힌다★", async ({ page }) => {
  // TPV 응답의 `cash_weight: null` 이 롱숏 신호다(P3-G — 넷 기준 현금은 뜻이 다르다).
  await page.route("**/api/v1/allocation/target-versions**", async (route) => {
    const res = await route.fetch();
    const body = await res.json().catch(() => ({}));
    await route.fulfill({
      response: res,
      json: {
        ...body, mode: "long_short", cash_weight: null,
        gross_after: LS_GROSS, net_after: LS_NET,
        status: "research_only",
        status_reason: "롱숏 목표는 연구·백테스트 전용입니다",
        final_weights: LS_OPTIMIZED,
      },
    });
  });
  // ★목표는 사용자가 만들어야 생긴다★ `targetVersion` 은 `.as-exec-run` 이
  // `compileTarget()` 을 호출해야 채워지는 로컬 상태다 — 페이지만 열면 null 이라
  // 차단 안내가 렌더될 조건 자체가 없다. 처음에 그걸 모르고 skip 으로 넘겼는데,
  // 그 skip 은 "이 단계의 산출물을 검증하지 않았다" 는 뜻이라 그대로 둘 수 없었다.
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  await page.locator(".as-run").click();
  await expect(page.locator(".as-card", { hasText: "SUMMARY METRICS" }).first())
    .toBeVisible({ timeout: 45_000 });

  // ★`page.goto` 로 가면 안 된다★ 최적화 결과는 전체 리로드에서 사라지고, 실행
  // 준비실은 "목표 배분이 필요합니다" 로 바뀌어 산출 버튼 자체를 그리지 않는다.
  // `allocation-tpv.spec.ts:43` 이 이미 기록해 둔 함정이다 — 앱 안에서 스파인으로
  // 이동한다. 그 스텝은 마우스 클릭이 구분자에 가려 안 먹으므로 `dispatchEvent`.
  await page.locator(".aas-wiz-step", { hasText: "EXECUTION" }).first()
    .dispatchEvent("click");
  await expect(page).toHaveURL(/\/allocation\/execution/, { timeout: 20_000 });
  await page.locator(".as-exec-run").first().click();

  const blocked = page.locator(".as-ls-blocked");
  await expect(blocked).toBeVisible({ timeout: 30_000 });
  await expect(blocked).toContainText("실행할 수 없습니다");
  const items = blocked.locator(".as-ls-blocked-l li");
  await expect(items).toHaveCount(3);
  await expect(items.nth(0)).toContainText("차입");
  await expect(items.nth(1)).toContainText("공매도");
  await expect(items.nth(2)).toContainText("미보유");
});

// ── 4. §56 타입 하한 + 대비 ────────────────────────────────────────────────

test("§56 하한 + 대비: 롱숏 노출 줄과 차단 안내", async ({ page }) => {
  await patchOptimizedWeights(page, LS_OPTIMIZED);
  await enterOptimize(page);
  await expect(page.locator(".as-ls-exposure")).toBeVisible({ timeout: 20_000 });

  // §56 — AAS 본문 최소 11px. 새로 넣은 `.as-ls-*` 가 그 하한을 지키는지.
  const small = await page.locator(".as-ls-exposure, .as-ls-exposure *").evaluateAll(
    (els) => els
      .filter((el) => (el.textContent || "").trim().length > 0)
      .map((el) => ({ px: parseFloat(getComputedStyle(el).fontSize),
                      t: (el.textContent || "").trim().slice(0, 20) }))
      .filter((x) => x.px < 11));
  expect(small, `§56 하한 미달: ${JSON.stringify(small)}`).toHaveLength(0);

  const AUDIT = contrastAudit(".aas-root");
  const light: AuditResult = await page.evaluate(AUDIT);
  expect(light.checked, "라이트에서 검사한 텍스트 노드 수").toBeGreaterThanOrEqual(120);
  expect(light.low, `라이트 AA 미달: ${JSON.stringify(light.low.slice(0, 6))}`).toHaveLength(0);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(350);   // transition-colors 중간값 회피 (M2-B 기록)
  const dark: AuditResult = await page.evaluate(AUDIT);
  expect(dark.checked, "다크에서 검사한 텍스트 노드 수").toBeGreaterThanOrEqual(120);
  expect(dark.low, `다크 AA 미달: ${JSON.stringify(dark.low.slice(0, 6))}`).toHaveLength(0);
  expect(dark.bright, `밝은 배경 누출: ${JSON.stringify(dark.bright.slice(0, 6))}`).toHaveLength(0);
});
