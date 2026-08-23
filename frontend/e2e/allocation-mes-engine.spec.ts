import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, freezeCharts, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// M2 — 기대수익 엔진 근거 · 분포 무가정 예측 구간
// ─────────────────────────────────────────────────────────────────────────────
// 백엔드는 pytest 가 지킨다(entropy_views 25 · mes_capability 16 · conformal 10 ·
// case_binding 13). 이 스펙이 지키는 것은 **화면 계약** 넷이다:
//
//   1. 미가용 엔진이 숫자를 내지 않는다 — 사유만 낸다
//   2. ★엔진 라벨은 서버의 `mu_engine` 이지 화면의 `model` 추측이 아니다★
//      뷰가 없으면 BL 도 시장균형이고, 그때 μ 엔진은 BL 이 아니다. 화면이 `model` 로
//      추측하면 서버가 실제로 탄 경로와 갈라지고, 그 갈라짐은 타입 에러를 내지 않는다.
//   3. EP 가 신뢰도를 쓰지 않는다는 사실이 화면에 있다 (매핑을 지어내지 않았음을 밝힌다)
//   4. conformal 적중률은 **실측**이지 이론 `1-α` 가 아니다
//
// ★서버 상태를 남기지 않는다★ `/analyze` 와 `/backtest` 를 전부 스텁한다 — A4 의 알파
// 스펙이 실제로 ResearchRun 을 기록해 `research-run-roundtrip` 을 타임아웃시킨 전례가 있다.
// ═══════════════════════════════════════════════════════════════════════════════

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

const EP_OK = {
  available: true, feasible: true, n_views: 1, kl: 0.12,
  ens: 640, ens_prior: 756, confidence_used: false,
  violations: [], skipped: [], note: null,
};

/**
 * ★손으로 쓴 응답 본문을 만들지 않는다★
 *
 * 처음에는 `/analyze` 응답 전체를 스텁으로 지어냈다가 12건이 통째로 실패했다 —
 * `.as-eng` 이 아예 렌더되지 않았다. 이 저장소는 그 함정을 이미 기록해 두었다
 * (`allocation-stages2.spec.ts:65` — "스텁은 화면이 읽는 필드를 다 못 채워서
 * 서브트리가 통째로 안 그려지는 실패를 이미 한 번 만들었다").
 *
 * 그래서 **실제 응답을 받아 M2 가 추가한 필드만 덮어쓴다.** 화면이 읽는 나머지
 * 필드는 서버가 채우므로 서브트리가 정상적으로 그려지고, 이 스펙이 재려는 것
 * (엔진 라벨·EP 진단·MES)만 결정적으로 고정된다. `/analyze` 는 순수 계산
 * 엔드포인트라 서버에 아무것도 남기지 않는다.
 */
async function patchAnalyze(page: Page, over: Record<string, unknown>) {
  await page.route("**/api/v1/allocation/analyze", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, ...over } });
  });
}

/** 게이트 → 05 OPTIMIZE → `.as-run` 으로 실제 최적화를 돌린다. */
async function enterOptimize(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  // ★`.as-run` 이 최적화 트리거다★ (optimize/page.tsx) — 모델 버튼은 닫힌
  // `<details class="aas-adv">` 안에 있고, 그것으로 몰다가 두 번 헛짚었다.
  await page.locator(".as-run").click();
  await expect(page.locator(".as-card", { hasText: "SUMMARY METRICS" }).first())
    .toBeVisible({ timeout: 45_000 });
  await expect(page.locator(".as-eng")).toBeVisible({ timeout: 20_000 });
}

// ── 1. ★미가용 엔진은 숫자를 내지 않는다★ ──────────────────────────────────

test("★EP 가 실현 불가면 비중 숫자가 아니라 사유가 온다★", async ({ page }) => {
  await patchAnalyze(page, {
    mu_engine: "ep",
    ep: { ...EP_OK, feasible: false, note: null,
          violations: [{ view_index: 0, assets: "005930", direction: 1,
                         requested_pct: 20, achieved_pct: 3.41, gap_pct: 16.59 }] },
  });
  await enterOptimize(page);

  const panel = page.locator(".as-eng");
  await expect(panel.locator(".as-eng-badge.bad")).toHaveText(/실현 불가/);

  // 위반은 **사용자 용어**로 온다 — 변환 공간의 부호 뒤집힌 값이 아니다.
  const viol = panel.locator(".as-eng-viol li");
  await expect(viol).toHaveCount(1);
  await expect(viol.first()).toContainText("005930");
  await expect(viol.first()).toContainText("20.00%");
  await expect(viol.first()).toContainText("3.41%");
});

test("★미가용 사유는 접히지 않는다★ (A5 경계 — 설명은 접고 사유는 접지 않는다)",
  async ({ page }) => {
    await patchAnalyze(page, {
      mu_engine: "ep",
      ep: { ...EP_OK, feasible: false,
            violations: [{ view_index: 0, assets: "000660", direction: -1,
                           requested_pct: -15, achieved_pct: -2.0, gap_pct: 13 }] },
    });
    await enterOptimize(page);
    // 닫힌 <details> 안이면 innerText 가 빈 문자열이라 textContent 로 본다(A6 기록).
    const inClosed = await page.locator(".as-eng .as-eng-viol").evaluate(
      (el) => !!el.closest("details:not([open])"));
    expect(inClosed, "위반 내역이 닫힌 details 안에 있다").toBe(false);
  });

// ── 2. ★라벨은 서버가 준 것이다★ (짝 단언) ─────────────────────────────────

test("엔진 라벨이 서버의 mu_engine 을 그대로 쓴다 (ep)", async ({ page }) => {
  await patchAnalyze(page, { mu_engine: "ep", ep: EP_OK });
  await enterOptimize(page);
  await expect(page.locator(".as-eng .as-eng-v")).toHaveText("Entropy Pooling");
});

test("★model 이 bl 이어도 mu_engine 이 mvo 면 화면은 MVO 라고 말한다★", async ({ page }) => {
  // 이것이 짝 단언이다. 앞 테스트만 있으면 화면이 `model` 로 추측해도 통과할 수 있다.
  // 뷰 없는 BL 은 시장균형이고 그때 μ 엔진은 BL 이 아니다 — 서버가 그 사실을 안다.
  await patchAnalyze(page, { model: "bl", views_applied: false, mu_engine: "mvo", ep: null });
  await enterOptimize(page);
  await expect(page.locator(".as-eng .as-eng-v")).toHaveText(/MVO/);
  await expect(page.locator(".as-eng .as-eng-v")).not.toHaveText(/Black-Litterman/);
});

// ── 3. ★신뢰도를 쓰지 않는다는 사실이 화면에 있다★ ─────────────────────────

test("★EP 가 신뢰도를 쓰지 않는다고 화면이 말한다★", async ({ page }) => {
  await patchAnalyze(page, { mu_engine: "ep", ep: EP_OK });
  await enterOptimize(page);
  // 이 문구가 없으면 사용자는 BL 처럼 신뢰도가 반영됐다고 읽는다. 매핑을 지어내지
  // 않았다는 사실 자체가 화면에 있어야 그 오해가 막힌다.
  await expect(page.locator(".as-eng")).toContainText("신뢰도를 사용하지 않습니다");
});

test("유효 시나리오 수가 사전 → 사후로 함께 온다", async ({ page }) => {
  await patchAnalyze(page, { mu_engine: "ep", ep: { ...EP_OK, ens_prior: 756, ens: 640 } });
  await enterOptimize(page);
  const txt = await page.locator(".as-eng").textContent();
  expect(txt).toContain("756");
  expect(txt).toContain("640");
});

test("MES 가 없으면 증거 줄을 그리지 않는다 (지어내지 않는다)", async ({ page }) => {
  await patchAnalyze(page, { mu_engine: "mvo", ep: null, mes: null });
  await enterOptimize(page);
  await expect(page.locator(".as-eng")).not.toContainText("고정된 매크로 증거");
});

test("MES 레벨 불일치는 경고로 보인다", async ({ page }) => {
  await patchAnalyze(page, {
    mu_engine: "ep", ep: EP_OK,
    mes: { mes_id: "rgs_e2e_0001", as_of: "2026-08-14", capability_level: "L3",
           capability_reason: null, live_capability_level: "L1",
           capability_diverged: "이 증거가 고정될 때는 L3 였고 지금은 L1 입니다 — 같은 증거라도 지금 쓸 수 있는 도구가 달라졌습니다." },
  });
  await enterOptimize(page);
  await expect(page.locator(".as-eng .as-eng-warn")).toContainText("달라졌습니다");
  await expect(page.locator(".as-eng")).toContainText("rgs_e2e_0001");
});

// ── 4. ★적중률은 실측이지 이론값이 아니다★ ─────────────────────────────────

/** 백테스트도 같은 이유로 **실제 응답에 `conformal` 만 덮어쓴다.** */
async function enterJournalBacktest(page: Page, conformal: unknown) {
  await page.route("**/api/v1/allocation/backtest", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, conformal } });
  });
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });
  // ★버튼 텍스트는 "정책 백테스트 실행 →" 이다★ `exact: true` 로 잡으려다 3건이
  // 타임아웃했다. 클래스로 잡는 것이 계약이고(`.as-fb-apply`), 저널에 같은 클래스가
  // 여럿이므로 텍스트로 좁힌 뒤 `.first()` 를 쓴다.
  await page.locator(".as-fb-apply", { hasText: "정책 백테스트" }).first().click();
  await expect(page.locator(".as-bt-cf")).toBeVisible({ timeout: 60_000 });
}

test("★적중률이 홀드아웃 실측값으로 온다 (1-α 가 아니다)★", async ({ page }) => {
  await enterJournalBacktest(page, {
    available: true, alpha: 0.1, unit: "daily_mean_return", n_pairs: 56, n_required: 9,
    next_period: { point: 0.00058, lower: -0.0033, upper: 0.00445, half_width: 0.00387 },
    measured_coverage: { available: true, coverage: 0.9411764705882353, n: 17, hits: 16,
                         mean_width: 0.0077, n_calibration: 39 },
    note: "다음 리밸런스 구간의 **일평균** 포트폴리오 수익률 구간입니다.",
  });
  const cf = page.locator(".as-bt-cf");
  // ★분수까지 보여야 한다★ 94.1% 만 있으면 이론값인지 실측인지 구분할 수 없다.
  await expect(cf).toContainText("94.1%");
  await expect(cf).toContainText("16/17");
  await expect(cf).not.toContainText("90.0%");
});

test("★보정 표본이 모자라면 숫자 자리에 사유가 온다★", async ({ page }) => {
  await enterJournalBacktest(page, {
    available: false, alpha: 0.1, n_pairs: 8, n_required: 9,
    reason: "완료된 리밸런스 구간이 8개로 보정 최소치 9개에 미치지 못합니다 (α=0.1) — 구간을 만들 수 없습니다.",
  });
  const cf = page.locator(".as-bt-cf");
  await expect(cf.locator(".as-bt-cf-na")).toContainText("보정 최소치");
  // 구간을 못 만들었으면 구간 숫자가 없어야 한다.
  await expect(cf).not.toContainText("~");
});

test("적중률을 잴 수 없으면 그 사실만 적고 숫자를 만들지 않는다", async ({ page }) => {
  await enterJournalBacktest(page, {
    available: true, alpha: 0.1, unit: "daily_mean_return", n_pairs: 12, n_required: 9,
    next_period: { point: 0.0004, lower: -0.002, upper: 0.0028, half_width: 0.0024 },
    measured_coverage: { available: false, reason: "적중률을 잴 홀드아웃 표본이 없습니다." },
    note: null,
  });
  await expect(page.locator(".as-bt-cf")).toContainText("홀드아웃 표본이 없습니다");
});

// ── 5. §56 하한 + 라이트/다크 AA ────────────────────────────────────────────

test("§56 하한 + 대비: 엔진 근거 패널", async ({ page }) => {
  await patchAnalyze(page, { mu_engine: "ep", ep: EP_OK });
  await enterOptimize(page);

  const sizes = await page.locator(".as-eng *").evaluateAll((els: Element[]) =>
    els.filter((e) => (e.textContent || "").trim().length > 0)
       .map((e) => parseFloat(getComputedStyle(e).fontSize)));
  // 실측 이 패널의 텍스트 노드는 10개다. 임계값의 목적은 "빈 선택자가 조용히 통과하지
  // 않게" 하는 것이지 내용을 고정하는 것이 아니므로, 실측값보다 넉넉히 아래로 둔다.
  expect(sizes.length, "잴 노드가 없으면 이 단언은 공허하다").toBeGreaterThanOrEqual(4);
  expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11);

  // `contrastAudit` 은 evaluate 문자열을 돌려준다 (A2 에서 helpers 로 추출한 형태).
  //
  // ★범위를 `.as-eng` 에서 `.aas-root` 로 넓혔다 — 좁힌 것이 실수였다★
  // 처음에는 `.aas-root` 를 쟀다가 결함이 걸리자 패널로 좁히고 "남의 결함" 이라고
  // 적었다. 그 결함은 남의 것이 아니라 **이 스펙만이 도달할 수 있는 상태의 것**이다:
  //   `B.num 3.16:1 (need 4.5) 11px rgb(22,163,74) :: +22.0%`
  // `McHistogram`·`StressChart`(parts.tsx)는 **최적화 결과가 있어야 렌더**되는데,
  // `allocation-stages.spec.ts` 와 `aas-dark.spec.ts` 는 결과를 만들지 않고 들어간다.
  // 그래서 결과가 렌더된 `.aas-root` 는 한 번도 측정된 적이 없었다. 이 스펙은
  // `.as-run` 을 눌러 그 상태를 만드는 유일한 스펙이므로, 그 상태를 재는 것도
  // 이 스펙의 일이다. (원인 귀속도 틀렸었다 — `--color-bull` 은 §55 에서 이미
  // `#15803d` 로 내려가 있었고, 범인은 parts.tsx 의 인라인 리터럴이었다.)
  const AUDIT = contrastAudit(".aas-root");

  const light = await page.evaluate<AuditResult>(AUDIT);
  // ★추측한 임계값이 실측을 넘어섰던 자리★ 처음 `> 10` 으로 썼는데 이 패널의 실제
  // 검사 노드가 정확히 10개라 초록일 수 없었다. 측정 전에 숫자를 쓰지 않는다.
  // 실측 214 노드(라이트·다크 동일). 하한의 목적은 "빈 선택자가 조용히 통과하지 않게"
  // 하는 것이지 내용을 고정하는 것이 아니므로 실측값보다 넉넉히 아래로 둔다.
  // 결과가 실제로 렌더됐는지는 위의 `.as-eng` 단언이 이미 보장한다(결과 없이는 안 그려진다).
  expect(light.checked, "라이트에서 검사한 텍스트 노드 수").toBeGreaterThanOrEqual(120);
  expect(light.low, `라이트 AA 미달: ${JSON.stringify(light.low.slice(0, 6))}`).toHaveLength(0);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  // ★전이 중간값이 잡히는 것을 피한다★ Badge·Button 의 `transition-colors` 때문에
  // 클래스를 붙인 직후 읽으면 라이트·다크의 중간색이 나와 없는 결함이 보고된다(A9 실측).
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(AUDIT);
  expect(dark.checked, "다크에서 검사한 텍스트 노드 수").toBeGreaterThanOrEqual(120);
  expect(dark.low, `다크 AA 미달: ${JSON.stringify(dark.low.slice(0, 6))}`).toHaveLength(0);
  expect(dark.bright, `밝은 배경 누출: ${JSON.stringify(dark.bright.slice(0, 6))}`).toHaveLength(0);
});
