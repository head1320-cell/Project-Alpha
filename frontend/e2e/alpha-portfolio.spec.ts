import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, freezeCharts, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// P2 — 알파 포트폴리오: 승인된 알파가 목표 비중이 되는 자리
// ─────────────────────────────────────────────────────────────────────────────
// 백엔드 사슬(게이트·결합·상관·as_of)은 pytest 15건이 실측으로 지킨다. 이 스펙이
// 지키는 것은 **화면 계약**이다:
//   · 승인되지 않은 알파는 고를 수 없고, **왜 못 고르는지 보인다**(죽은 버튼 금지)
//   · 상관 경고·제외 사유가 접히지 않는다 (A5 경계)
//   · 낡은 점수의 시점이 화면에 적혀 있다 (P2 가 밝힌 결함)
//   · 결과가 01 CONSTRUCT 로 간다
//
// ★서버 상태를 남기지 않는다★ 레지스트리·포트폴리오를 전부 스텁한다. A4 의 알파 스펙이
// 실제로 ResearchRun 을 기록해 `research-run-roundtrip` 을 타임아웃시킨 전례가 있다.
// ═══════════════════════════════════════════════════════════════════════════════

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

const APPROVED = "al_approved_e2e";
const DRAFT = "al_draft_e2e";

function alphaRow(id: string, name: string, status: string) {
  return {
    alpha_id: id, name, expr: "rank(mom_12_1)", description: "", universe: "kospi50",
    tags: [], status, version: 1, is_template: false, last_run_id: null,
    parent_id: null, notes: "", created_at: 1, updated_at: 1,
  };
}

async function stubRegistry(page: Page) {
  await page.route("**/api/v1/alpha-registry**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ alphas: [
        alphaRow(APPROVED, "승인된 모멘텀", "approved"),
        alphaRow(DRAFT, "초안 모멘텀", "draft"),
      ] }),
    });
  });
}

async function enter(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/alphalab", { waitUntil: "networkidle" });
  await expect(page.locator(".as-ap")).toBeVisible({ timeout: 20_000 });
}

const DONE_BODY = {
  available: true, as_of_requested: null, as_of_effective: "2026-08-14",
  base_weights: { "005930": 50.0, "000660": 50.0 },
  holdings: [
    { code: "005930", name: "삼성전자", weight: 50.0, score: 0.98 },
    { code: "000660", name: "SK하이닉스", weight: 50.0, score: 0.91 },
  ],
  used: [{ alpha_id: APPROVED, weight: 1.0 }],
  excluded: [{ alpha_id: "al_broken", reason: "필드 커버리지가 부족합니다." }],
  pairwise: [{ a: APPROVED, b: "al_twin", rho: 0.97, duplicate: true }],
  effective_n: 1.03,
  warnings: [
    "al_approved_e2e 와 al_twin 의 순위상관이 +0.97 입니다 — 사실상 같은 베팅이라 분산 효과가 거의 없습니다.",
    "1개 알파가 산출 불가로 제외됐습니다 — 남은 가중치는 재정규화하지 않았으므로 배합 비율이 의도와 다를 수 있습니다.",
  ],
  weighting: "equal", top_k: 10, universe_resolved_n: 50,
  note: "거래비용·슬리피지 미반영 — 알파 검증과 같은 한계입니다.",
  run_id: null, run_recorded: false,
};

async function stubPortfolio(page: Page, body: unknown) {
  await page.route("**/api/v1/alpha-lab/portfolio", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(body) });
  });
}

// ── 1. ★사다리가 화면에서도 보인다★ ─────────────────────────────────────────

test("★승인되지 않은 알파는 고를 수 없고, 왜 못 고르는지 보인다★", async ({ page }) => {
  await stubRegistry(page);
  await enter(page);

  const approved = page.locator(".as-ap-pick", { hasText: "승인된 모멘텀" });
  const draft = page.locator(".as-ap-pick", { hasText: "초안 모멘텀" });
  await expect(approved.locator("input[type=checkbox]")).toBeEnabled();
  await expect(draft.locator("input[type=checkbox]")).toBeDisabled();

  // ★막고 이유를 말하지 않으면 사용자는 버그로 읽는다★
  const why = draft.locator(".as-ap-why");
  await expect(why).toBeVisible();
  await expect(why).toContainText("승인 알파만");
  await expect(why, "다음 단계를 알려 준다").toContainText("실험");
});

test("서버가 막으면 비중을 그리지 않고 사유를 낸다", async ({ page }) => {
  await stubRegistry(page);
  await stubPortfolio(page, {
    available: false,
    reason: "실전 사용이 허용되지 않은 알파가 포함돼 있습니다 — 포트폴리오를 만들지 않았습니다.",
    blocked: [{ alpha_id: DRAFT, name: "초안 모멘텀", status: "draft",
                reason: "실전 사용은 approved 알파만 가능합니다 — 현재 draft." }],
  });
  await enter(page);
  await page.locator(".as-ap-pick", { hasText: "승인된 모멘텀" })
    .locator("input[type=checkbox]").check();
  await page.locator(".as-ap-run").click();

  await expect(page.locator(".as-ap-blocked")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-ap-blocked")).toContainText("만들지 않았습니다");
  expect(await page.locator(".as-ap-hold").count(), "막혔는데 비중표를 그렸다").toBe(0);
});

// ── 2. ★경고와 제외 사유는 접히지 않는다★ ──────────────────────────────────

test("★중복 베팅 경고와 제외 사유가 접히지 않고 보인다★", async ({ page }) => {
  await stubRegistry(page);
  await stubPortfolio(page, DONE_BODY);
  await enter(page);
  await page.locator(".as-ap-pick", { hasText: "승인된 모멘텀" })
    .locator("input[type=checkbox]").check();
  await page.locator(".as-ap-run").click();

  const warns = page.locator(".as-ap-warn");
  await expect(warns.first()).toBeVisible({ timeout: 20_000 });
  expect(await warns.count(), "경고 + 제외 사유").toBeGreaterThanOrEqual(3);

  // 닫힌 <details> 안이면 innerText 가 "" 다 — 보이는 텍스트로 확인한다.
  for (const w of await warns.all()) {
    expect((await w.innerText()).trim().length).toBeGreaterThan(5);
    expect(await w.locator("xpath=ancestor::details").count(),
      "한계가 <details> 안에 들어갔다").toBe(0);
  }
  await expect(page.locator(".as-ap-meta"), "유효 알파 수를 적는다").toContainText("유효 알파");
  await expect(page.locator(".as-ap-corr tr.dup")).toBeVisible();
});

test("상관을 낼 수 없으면 숫자 대신 사유가 온다", async ({ page }) => {
  await stubRegistry(page);
  await stubPortfolio(page, {
    ...DONE_BODY,
    pairwise: [{ a: "A", b: "B", rho: null,
                 reason: "분산이 0 이거나 표본이 3 미만이라 상관을 정의할 수 없습니다." }],
    warnings: [],
  });
  await enter(page);
  await page.locator(".as-ap-pick", { hasText: "승인된 모멘텀" })
    .locator("input[type=checkbox]").check();
  await page.locator(".as-ap-run").click();

  const cell = page.locator(".as-ap-corr tbody td.num").first();
  await expect(cell).toBeVisible({ timeout: 20_000 });
  await expect(cell, "산출 불가를 0 으로 그리지 않는다").toContainText("정의할 수 없습니다");
});

// ── 3. ★낡은 점수의 시점을 적는다★ ─────────────────────────────────────────

test("★검증 리포트 상위 종목이 어느 시점 값인지 화면이 말한다★", async ({ page }) => {
  // 이 화면의 진짜 결함이었다 — "최신 시점 상위 종목" 이라고 적고 한 달 낡은 값을 썼다.
  await stubRegistry(page);
  await page.route("**/alpha-lab/validate**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({
        expr: "rank(mom_12_1)", universe: "kospi50", n_periods: 24,
        universe_size: 50, avg_coverage: 40,
        period_start: "2024-09-09", period_end: "2026-07-16",
        ic: { mean: 0.02, icir: 0.1, t_stat: 0.5, hit_rate: 52 },
        latest_scores_top: [{ ticker: "005930", name: "삼성전자", score: 0.98 },
                            { ticker: "000660", name: "SK하이닉스", score: 0.91 }],
        notes: [],
      }) });
  });
  await enter(page);
  await page.locator(".as-fb-apply", { hasText: "검증 실행" }).click();

  const stale = page.locator(".as-ap-stale");
  await expect(stale).toBeVisible({ timeout: 20_000 });
  await expect(stale, "그 값의 시점을 적는다").toContainText("2026-07-16");
  await expect(stale, "현재 시점 도구로 안내한다").toContainText("알파 포트폴리오");
});

// ── 4. 결과가 01 CONSTRUCT 로 간다 ─────────────────────────────────────────

test("포트폴리오를 01 CONSTRUCT 로 보낸다", async ({ page }) => {
  await stubRegistry(page);
  await stubPortfolio(page, DONE_BODY);
  await enter(page);
  await page.locator(".as-ap-pick", { hasText: "승인된 모멘텀" })
    .locator("input[type=checkbox]").check();
  await page.locator(".as-ap-run").click();
  await expect(page.locator(".as-ap-hold")).toBeVisible({ timeout: 20_000 });

  await page.locator(".as-ap-send").click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 20_000 });
  await expect(page.locator(".as-holding, .as-wrow").first()).toBeVisible({ timeout: 20_000 });
});

test("네트워크 오류는 '막혔다' 와 다른 화면이다", async ({ page }) => {
  await stubRegistry(page);
  await page.route("**/api/v1/alpha-lab/portfolio", (route) => route.abort());
  await enter(page);
  await page.locator(".as-ap-pick", { hasText: "승인된 모멘텀" })
    .locator("input[type=checkbox]").check();
  await page.locator(".as-ap-run").click();

  await expect(page.locator(".as-ap-net")).toBeVisible({ timeout: 20_000 });
  expect(await page.locator(".as-ap-blocked").count(),
    "네트워크 오류를 서버 차단으로 그렸다").toBe(0);
});

// ── 5. 하한 + 대비 ──────────────────────────────────────────────────────────

test("§56 하한 + 라이트/다크 AA — 알파 포트폴리오 패널", async ({ page }) => {
  await stubRegistry(page);
  await stubPortfolio(page, DONE_BODY);
  await enter(page);
  await page.locator(".as-ap-pick", { hasText: "승인된 모멘텀" })
    .locator("input[type=checkbox]").check();
  await page.locator(".as-ap-run").click();
  await expect(page.locator(".as-ap-hold")).toBeVisible({ timeout: 20_000 });

  const sizes = await page.evaluate(() => {
    const root = document.querySelector(".as-ap");
    if (!root) return [] as number[];
    const out: number[] = [];
    root.querySelectorAll("*").forEach((el) => {
      if (!(el.textContent ?? "").trim()) return;
      const px = parseFloat(getComputedStyle(el).fontSize);
      if (Number.isFinite(px)) out.push(px);
    });
    return out;
  });
  expect(sizes.length, "검사한 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(10);
  expect(sizes.filter((p) => p < 11), "11px 미만").toEqual([]);

  const light = await page.evaluate<AuditResult>(contrastAudit(".as-ap"));
  expect(light.checked).toBeGreaterThan(10);
  expect(light.low, "라이트 AA 미달").toEqual([]);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(contrastAudit(".as-ap"));
  expect(dark.checked).toBeGreaterThan(10);
  expect(dark.low, "다크 AA 미달").toEqual([]);
  expect(dark.bright, "다크인데 밝은 배경이 남았다").toEqual([]);
});
