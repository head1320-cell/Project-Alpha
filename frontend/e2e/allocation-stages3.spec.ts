import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// A7 — 하단 CTA 선형화 · 아카이브 드로어 · 0M 다중 도구 국면 · 07 실측화
// ─────────────────────────────────────────────────────────────────────────────
// A1~A6 은 11개 스테이지의 **표현**을 고쳤다. A7 은 네 곳의 **동작**을 고쳤고, 그 넷은
// 전부 "화면이 이미 가지고 있거나 서버가 이미 줄 수 있는 것을 사용자에게 닿게 하지
// 못하고 있다" 는 한 가지 결함의 변형이다. 그래서 이 스펙이 재는 것도 전부 **도달
// 가능성**이다 — 값이 맞느냐가 아니라, 그 값에 닿을 수 있느냐.
//
// ★루프 앞에서 개수를 먼저 단언한다★ A4~A6 에서 네 번, 대상이 0개라 조용히 통과하는
// "가드 모양의 무가드" 를 만들었다. 모든 루프 앞에 하한이 있다.
//
// ★이 스펙은 서버 상태를 남기지 않는다★ A4 의 Alpha Lab 스펙이 ResearchRun 을 기록해
// `research-run-roundtrip.spec.ts` 를 타임아웃시킨 전례가 있다. 07 은 읽기만 하고,
// 런 목록과 귀인 응답은 스텁한다 — 이 컨테이너의 DB 에는 런이 0개라 스텁 없이는
// 피커 자체가 렌더되지 않기도 한다.
// ═══════════════════════════════════════════════════════════════════════════════

/** STAGES 레지스트리(AllocationProvider.tsx:63-73)와 같은 순서. CTA 가 이 순서를 따라야 한다. */
const STAGES: [n: string, label: string, href: string][] = [
  ["00", "OVERVIEW", "/allocation/overview"],
  ["0M", "MACRO PHASE", "/allocation/macro"],
  ["01", "CONSTRUCT", "/allocation/construct"],
  ["02", "ALPHA LAB", "/allocation/alphalab"],
  ["03", "THESIS", "/allocation/thesis"],
  ["04", "TIMING", "/allocation/timing"],
  ["05", "OPTIMIZE", "/allocation/optimize"],
  ["06", "STRESS", "/allocation/stress"],
  ["07", "ATTRIBUTION", "/allocation/explain"],
  ["08", "EXECUTION", "/allocation/execution"],
  ["09", "JOURNAL", "/allocation/journal"],
];

async function seed(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
}

/**
 * 알파 레지스트리를 스텁한다.
 *
 * ★첫 실행에서 두 테스트가 여기서 걸렸다★ 레지스트리는 `/api/v1/alpha-registry`
 * (서버)에서 오는데 이 컨테이너에는 DB 가 없어 **항상 0건**이다. 스크린샷의 15개는
 * 사용자 세션의 데이터였다. 0건이면 클리핑 가드는 검사할 행이 없어 하한 단언에서
 * 걸리고(의도한 동작이다 — 조용히 통과하지 않았다), 드로어는 트리거 자체가 없다.
 *
 * 이름과 표현식을 **일부러 길게** 둔다. 짧은 이름은 300px 레일에서도 안 눌리므로
 * 클리핑을 재현하지 못한다 — 재현하지 못하는 가드는 가드가 아니다.
 * 본문 한도(MAIN_MAX = 4)를 넘겨서 서랍에도 행이 가도록 8개를 준다.
 */
async function stubAlphaRegistry(page: Page) {
  const now = Math.floor(Date.now() / 1000);
  const alphas = Array.from({ length: 8 }, (_, i) => ({
    alpha_id: `al_e2e_${i}`,
    name: `장기 모멘텀 리버설 결합 알파 ${i + 1}`,
    expr: "rank(ts_mean(close / delay(close, 20), 5)) - rank(ts_std(returns, 60))",
    description: "20일 모멘텀과 60일 변동성의 랭크 스프레드",
    universe: "kospi200", tags: ["momentum", "reversal"],
    status: i === 0 ? "draft" : "validated",
    version: 1, is_template: false, last_run_id: null, parent_id: null,
    notes: "", created_at: now - i * 3600, updated_at: now - i * 3600,
  }));
  await page.route(/\/api\/v1\/alpha-registry(\?|$)/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ alphas }) }));
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. ★하단 CTA 는 선형 다음 단계다 — 자기 자신도, 뒤로도 아니다★
// ─────────────────────────────────────────────────────────────────────────────
// 결함의 정체는 `StageChrome.tsx` 의 **비대칭**이었다: `.aas-botnav-prev` 는
// `STAGES[idx-1]` 로 선형인데 `.aas-botnav-next` 만 `nextAction()` 정책을 썼다. 그래서
// 0M 에서는 "다음" 이 `0M MACRO PHASE →` — **자기 자신**을 가리켰고, 02 에서는 **뒤로**
// 갔다. 00 에서만 우연히 맞아서 더 늦게 발견됐다.
// ★스테이지마다 별도 test 다 — 한 판에 11번 이동하면 90초 예산을 넘긴다★
// 첫 실행에서 정확히 그렇게 타임아웃했다(`networkidle` → `domcontentloaded` 로 바꿔도
// 마찬가지였다). 나누면 각자 예산을 갖고, 실패했을 때 **어느 스테이지인지** 이름이 나온다.
// 한 판짜리 루프는 첫 실패에서 멈춰서 나머지 열 개의 상태를 영영 모른다.
for (let i = 0; i < STAGES.length; i++) {
  const [n, label, href] = STAGES[i];
  const isLast = i === STAGES.length - 1;
  const nextStage = isLast ? null : STAGES[i + 1];

  test(`★${n} ${label}: 다음 CTA 가 ${nextStage ? `${nextStage[0]} ${nextStage[1]}` : "비활성"}★`, async ({ page }) => {
    await seed(page);
    await page.goto(href, { waitUntil: "domcontentloaded" });

    const next = page.locator(".aas-botnav-next");
    await expect(next, `${n} ${label}: 다음 CTA 가 없다`).toBeVisible({ timeout: 20_000 });
    const text = ((await next.textContent()) || "").replace(/\s+/g, " ").trim();

    if (!nextStage) {
      // 09 는 마지막이다 — 갈 곳이 없으면 비활성이어야 한다. 어딘가로 보내면 거짓이다.
      await expect(next, "09 에서 다음 CTA 가 활성이다 — 마지막 단계인데 갈 곳을 만들었다")
        .toBeDisabled();
      return;
    }

    const [nn, nlabel] = nextStage;
    await expect(next).toBeEnabled();
    expect(text, `${n} ${label} 의 CTA 가 다음 단계(${nn} ${nlabel})를 가리키지 않는다`)
      .toContain(`${nn} ${nlabel}`);
    // ★자기 자신 금지★ 이것이 스크린샷에 찍혀 있던 결함 그 자체다 — 0M 에서 다음이
    // `0M MACRO PHASE →` 였다.
    expect(text, `${n} ${label} 의 CTA 가 자기 자신을 가리킨다`).not.toContain(`${n} ${label}`);
  });
}

test("정책은 버려지지 않았다 — 권장이 선형 다음과 다르면 보조 링크로 남는다", async ({ page }) => {
  await seed(page);
  await page.goto("/allocation/construct", { waitUntil: "networkidle" });

  // `.aas-botnav-why` 와 그 `data-next` 는 셀렉터 계약이다 — research-shell.spec.ts 가 읽는다.
  const why = page.locator(".aas-botnav-why");
  await expect(why).toBeVisible();
  await expect(why).toHaveAttribute("data-next", /.+/);
  await expect(why).toContainText("권장");

  // 권장 목적지가 선형 다음과 다를 때만 보조 링크가 뜬다. 있으면 눌러서 실제로
  // 이동하는지 본다 — 있는데 죽어 있으면 힌트가 아니라 장식이다.
  const rec = page.locator(".aas-botnav-rec");
  if (await rec.count()) {
    await expect(rec.first()).toBeEnabled();
    await rec.first().click();
    await page.waitForURL(/\/allocation\/[a-z]+/, { timeout: 15_000 });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. ★세로로 쏟아지던 글자 — 원인(flex 축소)이 고쳐졌는가★
// ─────────────────────────────────────────────────────────────────────────────
// 스크린샷의 `↑ 검 증 됨` 세로 쌓임은 폰트가 아니라 **flex 축소**였다. `.as-al-item` 의
// 자식에 `min-width: 0` 이 없고 승격 칩에 `flex-shrink: 0` 도 없어서, 300px 레일에서
// 이름+표현식이 자리를 먼저 먹으면 칩이 몇 px 로 눌리고 그 폭에서 글자 단위로 줄바꿈됐다.
// 드로어로 옮기는 것만으로는 안 된다 — 좁은 폭이면 드로어 안에서도 재발한다.
test("★02 레지스트리 행의 어떤 자식도 가로로 넘치지 않는다 (세로 글자 재발 가드)★", async ({ page }) => {
  await stubAlphaRegistry(page);
  await seed(page);
  await page.goto("/allocation/alphalab", { waitUntil: "networkidle" });

  const items = page.locator(".as-al-item");
  const n = await items.count();
  expect(n, "레지스트리 행 수 (0 이면 이 테스트는 아무것도 지키지 않는다)").toBeGreaterThan(0);

  // ★첫 판의 가드는 무가드였다 — 변이 프로브가 알려 줬다★
  // 처음에는 `scrollWidth > clientWidth` 로 "넘침" 을 쟀다. §57 의 세 규칙을 **전부**
  // 지웠는데도 초록이었다. 실측해 보니 이유가 분명했다: flex 로 눌린 텍스트는
  // **넘치지 않고 줄바꿈된다**. 칩의 scrollWidth(25) == clientWidth(25) 이고, 대신
  // 높이가 49px — line-height 14.4px 의 3.4배였다. 그게 `↑ 검 증 됨` 세로 쌓임의 정체다.
  // 넘침은 폭이 아니라 **부모 쪽**에서 났다: `.as-al-pick` 348px 가 278px 짜리 행 밖으로.
  // 그래서 재는 것을 둘 다 바꿨다.
  const bad = await page.locator(".as-al-item").evaluateAll((items) => {
    const out: string[] = [];
    for (const item of items) {
      const iw = item.getBoundingClientRect().width;
      for (const k of Array.from(item.children)) {
        const r = k.getBoundingClientRect();
        const s = getComputedStyle(k);
        const cls = String(k.className);
        const txt = (k.textContent || "").trim().slice(0, 20);

        // ① 자식이 행보다 넓다 = 행 밖으로 삐져나갔다 (min-width:0 이 없을 때의 모습).
        if (r.width > iw + 1) out.push(`넘침 ${cls} ${Math.round(r.width)}>${Math.round(iw)} | ${txt}`);

        // ② 한 줄짜리 칩이 여러 줄로 쌓였다 = 폭이 글자 단위까지 눌렸다.
        // ★컨테이너에는 적용하지 않는다★ `.as-al-pick` 은 이름 + 표현식 행을 **일부러**
        // 세로로 쌓는 블록이라 2줄이 정상이다. 처음엔 자식 전부에 걸었다가 그걸 결함으로
        // 신고했다 — 규칙이 틀린 것이지 화면이 틀린 게 아니었다. 그래서 자식 엘리먼트가
        // 없는 **잎 노드**(칩·×처럼 한 줄이어야 하는 것)만 잰다. 변이 프로브에서 걸린
        // 칩(h=49, lh=14.4)은 잎이므로 이 좁힘 뒤에도 그대로 잡힌다.
        if (k.children.length > 0) continue;
        const lh = parseFloat(s.lineHeight);
        if (!Number.isFinite(lh) || !txt) continue;
        const padY = parseFloat(s.paddingTop) + parseFloat(s.paddingBottom)
          + parseFloat(s.borderTopWidth) + parseFloat(s.borderBottomWidth);
        if (r.height > lh * 1.8 + padY)
          out.push(`줄바꿈 ${cls} h=${Math.round(r.height)} lh=${lh.toFixed(1)} | ${txt}`);
      }
    }
    return out;
  });
  expect(bad, "행 밖으로 넘치거나 글자 단위로 줄바꿈된 자식 — min-width:0 / flex-shrink:0 이 빠졌다")
    .toEqual([]);
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. ★아카이브 드로어 — 열리고, Escape 로 닫히고, 포커스가 돌아오는가★
// ─────────────────────────────────────────────────────────────────────────────
// Radix 는 Overlay/Content 를 `document.body` 로 포털한다 — 컨테이너로 스코프한 단언은
// 이 안을 못 본다(`shadcn/dialog.tsx` 헤더가 같은 함정을 기록해 뒀다). 페이지 루트에서 잡는다.
test("★드로어가 열리고 Escape 로 닫히며 포커스가 트리거로 복귀한다★", async ({ page }) => {
  await stubAlphaRegistry(page);           // 8개 = 본문 한도(4) 초과 → 서랍에 4개가 간다
  await seed(page);
  await page.goto("/allocation/alphalab", { waitUntil: "networkidle" });

  const trigger = page.locator(".as-arch-t").first();
  await expect(trigger, "레지스트리가 본문 한도를 넘는데 드로어 트리거가 없다")
    .toBeVisible({ timeout: 20_000 });

  await trigger.click();
  const panel = page.locator(".as-arch");
  await expect(panel, "드로어가 열리지 않았다").toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".as-arch-title")).toBeVisible();
  // 닫기 버튼은 아이콘 하나다 — 접근 가능한 이름이 없으면 스크린리더에게는 없는 버튼이다.
  await expect(page.locator(".as-arch-x")).toHaveAttribute("aria-label", /.+/);

  await page.keyboard.press("Escape");
  await expect(panel, "Escape 로 닫히지 않았다").toBeHidden({ timeout: 10_000 });

  // 포커스가 허공에 남으면 키보드 사용자는 목록의 처음부터 다시 Tab 해야 한다.
  const focusedIsTrigger = await page.evaluate(() =>
    !!document.activeElement?.classList.contains("as-arch-t"));
  expect(focusedIsTrigger, "닫은 뒤 포커스가 트리거로 돌아오지 않았다").toBe(true);
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. ★0M — 세 도구가 나란히, 미가용은 숫자 없이 사유만★
// ─────────────────────────────────────────────────────────────────────────────
test("★0M: 세 국면 도구가 나란히 렌더되고 합쳐지지 않는다★", async ({ page }) => {
  await seed(page);
  await page.goto("/allocation/macro", { waitUntil: "networkidle" });

  const panel = page.locator(".as-rge");
  await expect(panel).toBeVisible({ timeout: 20_000 });

  const tools = page.locator(".as-rge-tool");
  await expect(tools).toHaveCount(3, { timeout: 20_000 });

  // 세 도구의 이름이 각각 보인다 — 하나로 합쳐 놓고 셋이라고 우기지 않는지.
  for (const name of ["축-확률", "상태전환", "군집"]) {
    await expect(panel, `${name} 도구가 없다`).toContainText(name);
  }
  // 일치/불일치는 **사실**만 말한다. 합의된 단일 확률을 만들지 않는다.
  await expect(page.locator(".as-rge-agree")).toBeVisible();
});

test("★0M: 미가용 도구는 확률 막대도 숫자도 그리지 않고 사유를 말한다★", async ({ page }) => {
  await seed(page);
  // 상태전환만 미수렴시킨다 — 나머지 둘은 그대로 두어, "미가용" 이 화면 전체를
  // 무너뜨리는 게 아니라 그 칸에만 국소적으로 나타나는지 본다.
  await page.route(/\/api\/v1\/macro\/regime-ensemble/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.tools.markov = { available: false, reason: "상태전환 모형이 수렴하지 않았습니다 (테스트)" };
    body.agreement = { unanimous: null, picks: {}, note: "테스트" };
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await page.goto("/allocation/macro", { waitUntil: "networkidle" });
  await expect(page.locator(".as-rge")).toBeVisible({ timeout: 20_000 });

  const na = page.locator(".as-rge-tool.na");
  await expect(na, "미가용 도구가 미가용으로 표시되지 않았다").toHaveCount(1, { timeout: 20_000 });

  // ★균등분포를 그리지 않는다★ 0.25씩 넷을 그리면 화면에는 "네 국면이 똑같이 가능"
  // 으로 읽히는데, 실제로는 아무것도 추정하지 못한 것이다.
  expect(await na.locator(".as-rge-bar").count(), "미가용인데 확률 막대를 그렸다").toBe(0);
  await expect(na, "미가용인데 사유가 없다").toContainText("수렴하지 않았습니다");

  // Markov 가 없으면 전이 그래프도 없다 — 빈 그래프를 그리지 않는다.
  expect(await page.locator(".as-rgg-svg").count(), "상태전환이 미가용인데 전이 그래프를 그렸다").toBe(0);
});

test("★0M: 전이 그래프는 4개 노드를 그리고 무엇을 말하지 않는지 적는다★", async ({ page }) => {
  await seed(page);
  await page.goto("/allocation/macro", { waitUntil: "networkidle" });
  await expect(page.locator(".as-rge")).toBeVisible({ timeout: 20_000 });

  const svg = page.locator(".as-rgg-svg");
  const drawn = await svg.count();
  test.skip(!drawn, "이 환경에서 상태전환 모형이 미가용이라 그래프가 없다");

  await expect(page.locator(".as-rgg-node")).toHaveCount(4);
  // 노드는 키보드로도 닿아야 한다 — 호버 전용이면 키보드 사용자에게는 없는 것이다.
  const firstNode = page.locator(".as-rgg-node").first();
  await expect(firstNode).toHaveAttribute("tabindex", "0");
  await expect(firstNode).toHaveAttribute("aria-label", /.+/);

  // ★과대주장 금지 가드★ 모형이 추정한 것은 성장 2상태다. 4×4 전이행렬이 아니라는
  // 사실이 캡션에 적혀 있어야 한다 — 없으면 그림이 하지 않은 말을 하게 된다.
  await expect(page.locator(".as-rgg-cap")).toContainText("4×4 전이행렬이 아닙니다");
});

// ─────────────────────────────────────────────────────────────────────────────
// 5. ★07 — 경과일 있는 런을 고르면 실측이 되고, 막힌 것은 여전히 막혀 있다★
// ─────────────────────────────────────────────────────────────────────────────
const RUN_ID = "rr_e2e_asof_1";

/** 14일 전에 결정된 런 하나 + 그 런의 실측 귀인 리포트. 서버에 아무것도 남기지 않는다. */
async function stubRunAndAttribution(page: Page) {
  const createdAt = Math.floor(Date.now() / 1000) - 14 * 86400;
  const decided = new Date(createdAt * 1000).toISOString().slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);

  await page.route(/\/api\/v1\/research-runs(\?|$)/, (r) =>
    r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        runs: [{
          run_id: RUN_ID, created_at: createdAt, kind: "allocation_analyze",
          name: "14일 전 결정", code_version: "test", parent_run_id: null, note: null, snapshot: {},
        }],
      }),
    }));

  await page.route(new RegExp(`/api/v1/allocation/attribution/${RUN_ID}`), (r) =>
    r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        run_id: RUN_ID, decision_date: decided, as_of: today, elapsed_days: 14, period_years: 14 / 365,
        coverage: { tickers: 2, covered: 2, missing: [], source: "real", has_expost: true },
        returns: { portfolio_pct: 3.42, benchmark_pct: 1.1, excess_pct: 2.32, benchmark_label: "KOSPI", basis: "real" },
        expected_vs_actual: { expected_return_pct: 0.31, expected_return_annual_pct: 8.0, actual_return_pct: 3.42, gap_pct: 3.11, basis: "real" },
        decomposition: {
          model_alpha_pct: 0.31, execution_slippage_pct: null, cost_pct: null, residual_pct: 3.11,
          basis: { model_alpha: "real", slippage: "unavailable", cost: "unavailable", residual: "real" },
          note: "연결된 실체결이 없어 슬리피지·비용은 산출 불가",
        },
        risk_compare: {
          ex_ante: { vol_pct: 15.0, var_pct: -2.5, cvar_pct: -3.8 },
          ex_post: { vol_pct: 13.2, beta: 0.94 }, vol_gap_pct: -1.8, basis: "real",
        },
        contribution: { assets: [{ code: "005930", weight_pct: 60, return_pct: 4.2, contribution_pct: 2.52 }], basis: "real" },
        fill_quality: { basis: "unavailable", note: "연결된 실행계획의 체결이 없습니다" },
        dependency: { basis: "unavailable", note: "사후 데이터 필요" },
        brinson_effects: {
          selection: null, allocation: null, factor: null, timing: null, hedge: null,
          basis: "unavailable", note: "벤치마크 구성종목 가중·섹터수익이 없어 산출 불가",
        },
        note: "", journal_entry_id: null,
      }),
    }));
  return { decided, today };
}

test("★07: 경과일이 있는 런을 고르면 수익이 — 가 아니라 숫자다★", async ({ page }) => {
  await stubRunAndAttribution(page);
  await seed(page);
  await page.goto("/allocation/explain", { waitUntil: "networkidle" });

  // 피커는 `result` 유무와 무관하게 런이 있으면 나온다 — 예전에는 이 세션에서 방금
  // 만든 런만 볼 수 있어서, 서버의 2주 전 런에 닿을 방법이 없었다.
  const pick = page.locator(".as-attr-pick");
  await expect(pick, "런이 있는데 피커가 없다").toBeVisible({ timeout: 20_000 });

  const select = page.locator("#as-attr-run");
  await expect(select).toBeVisible();
  await expect(select, "런 선택에 접근 가능한 이름이 없다").toHaveAccessibleName(/결정/);
  await expect(pick, "옵션에 경과일이 보이지 않는다 — 무엇을 고르는지 알 수 없다")
    .toContainText("경과 14일");

  await expect(page.locator("#as-attr-asof"), "기준일 입력에 접근 가능한 이름이 없다")
    .toHaveAccessibleName(/기준일/);

  await select.selectOption(RUN_ID);

  const view = page.locator(".as-attr");
  await expect(view, "귀인 리포트가 렌더되지 않았다").toBeVisible({ timeout: 20_000 });

  // ★이것이 A7-4 의 전부다★ 예전에는 여기가 전부 `—` 였다. 데이터가 없어서가 아니라
  // 경과 0일 런만 볼 수 있어서였다.
  const cards = page.locator(".as-attr-card");
  expect(await cards.count(), "수익 카드 수").toBeGreaterThan(0);
  const first = ((await cards.first().textContent()) || "").trim();
  expect(first, "포트폴리오 수익이 여전히 미측정이다").toMatch(/\d/);
  expect(first, "포트폴리오 수익이 — 로 남아 있다").not.toMatch(/—\s*$/);

  // 0일이 아니므로 0일 사유는 뜨지 않아야 한다 — 항상 뜨면 그건 상태가 아니라 장식이다.
  expect(await page.locator(".as-attr-zero").count(), "경과 14일인데 0일 사유가 떴다").toBe(0);
});

test("★07: 실측이 되어도 구조적으로 막힌 것은 여전히 미가용 + 사유다★", async ({ page }) => {
  await stubRunAndAttribution(page);
  await seed(page);
  await page.goto("/allocation/explain", { waitUntil: "networkidle" });
  await page.locator("#as-attr-run").selectOption(RUN_ID);
  await expect(page.locator(".as-attr")).toBeVisible({ timeout: 20_000 });

  // Brinson — 벤치마크 구성종목 가중이 저장소에 없다. 시간이 지난다고 생기지 않는다.
  const brinson = page.locator(".as-card", { hasText: "Brinson" }).first();
  await expect(brinson).toBeVisible();
  const na = brinson.locator(".tev-unavailable");
  await expect(na, "Brinson 이 미가용 처리를 쓰지 않는다").toHaveCount(1);
  await expect(brinson, "미가용인데 사유가 없다").toContainText("산출 불가");
  await expect(brinson).toContainText("벤치마크");

  // 숫자를 지어내지 않았는지 — 프록시로 채우는 순간 나머지 숫자도 믿을 수 없게 된다.
  const cells = await brinson.locator("td.num").allTextContents();
  expect(cells.filter((t) => /\d/.test(t)), "Brinson 에 숫자가 찍혔다").toEqual([]);
});

test("★07: 경과 0일이면 왜 미측정인지 그 자리에서 말한다★", async ({ page }) => {
  const today = new Date().toISOString().slice(0, 10);
  const createdAt = Math.floor(Date.now() / 1000);
  await page.route(/\/api\/v1\/research-runs(\?|$)/, (r) =>
    r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        runs: [{
          run_id: RUN_ID, created_at: createdAt, kind: "allocation_analyze",
          name: "오늘 결정", code_version: "test", parent_run_id: null, note: null, snapshot: {},
        }],
      }),
    }));
  await page.route(new RegExp(`/api/v1/allocation/attribution/${RUN_ID}`), (r) =>
    r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        run_id: RUN_ID, decision_date: today, as_of: today, elapsed_days: 0, period_years: 0,
        coverage: { tickers: 2, covered: 0, missing: [], source: "real", has_expost: false },
        returns: { portfolio_pct: null, benchmark_pct: null, excess_pct: null, benchmark_label: "KOSPI", basis: "unavailable" },
        expected_vs_actual: { expected_return_pct: null, expected_return_annual_pct: 8.0, actual_return_pct: null, gap_pct: null, basis: "unavailable" },
        decomposition: {
          model_alpha_pct: null, execution_slippage_pct: null, cost_pct: null, residual_pct: null,
          basis: { model_alpha: "unavailable", slippage: "unavailable", cost: "unavailable", residual: "unavailable" }, note: "",
        },
        risk_compare: { ex_ante: { vol_pct: 15.0, var_pct: null, cvar_pct: null }, ex_post: { vol_pct: null, beta: null }, vol_gap_pct: null, basis: "unavailable" },
        contribution: { assets: [], basis: "unavailable" },
        fill_quality: { basis: "unavailable", note: "" },
        dependency: { basis: "unavailable", note: "" },
        brinson_effects: { selection: null, allocation: null, factor: null, timing: null, hedge: null, basis: "unavailable", note: "벤치마크 구성종목 가중 없음" },
        note: "", journal_entry_id: null,
      }),
    }));

  await seed(page);
  await page.goto("/allocation/explain", { waitUntil: "networkidle" });
  await page.locator("#as-attr-run").selectOption(RUN_ID);
  await expect(page.locator(".as-attr")).toBeVisible({ timeout: 20_000 });

  // ★데이터가 없는 것과 잴 구간이 없는 것은 다르다★ 뒤쪽은 런만 바꾸면 풀린다.
  // 침묵하면 사용자는 앞쪽으로 읽고 포기한다.
  const zero = page.locator(".as-attr-zero");
  await expect(zero, "경과 0일인데 이유를 말하지 않는다").toBeVisible();
  await expect(zero).toContainText("경과 0일");
  await expect(zero).toContainText("데이터가 없어서가 아닙니다");

  // 그리고 여전히 숫자를 지어내지 않는다.
  const cards = await page.locator(".as-attr-card").allTextContents();
  expect(cards.length, "수익 카드 수").toBeGreaterThan(0);
  for (const c of cards) {
    expect(c, `0일 구간인데 수익 숫자가 찍혔다: ${c}`).not.toMatch(/[+-]\d+\.\d+%/);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 6. §56 타입 하한 + 라이트/다크 대비 — 이번에 새로 생긴 표면만
// ─────────────────────────────────────────────────────────────────────────────
// SVG 안의 `font-size` 는 CSS 가 닿지 못한다 — A5 의 SankeyNode, A6 의 축 눈금에서 두 번
// 겪었다. 그래서 DOM 텍스트와 SVG `<text>` 를 **둘 다** 잰다.
const NEW_SURFACES: [path: string, root: string][] = [
  ["/allocation/macro", ".as-rge"],
  ["/allocation/explain", ".as-attr-pick"],
];

for (const [path, root] of NEW_SURFACES) {
  test(`§56 하한: ${path} 의 ${root} — 산문 12px · 크롬 11px (SVG 포함)`, async ({ page }) => {
    if (path.includes("explain")) await stubRunAndAttribution(page);
    await seed(page);
    await page.goto(path, { waitUntil: "networkidle" });
    await expect(page.locator(root)).toBeVisible({ timeout: 20_000 });

    const small = await page.locator(`${root} *`).evaluateAll((els) => {
      const out: { cls: string; px: number; text: string }[] = [];
      for (const el of els) {
        const t = (el.textContent || "").trim();
        if (!t) continue;
        // 텍스트를 직접 들고 있는 노드만 — 컨테이너의 상속 크기까지 세면 중복이다.
        const own = Array.from(el.childNodes).some(
          (n) => n.nodeType === 3 && (n.textContent || "").trim());
        if (!own) continue;
        const px = parseFloat(getComputedStyle(el).fontSize);
        if (px < 11) out.push({ cls: String(el.className), px, text: t.slice(0, 24) });
      }
      return out;
    });

    const nodes = await page.locator(`${root} *`).count();
    expect(nodes, "검사한 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(5);
    expect(small, "11px 미만 텍스트").toEqual([]);
  });
}

test("§56 하한: 전이 그래프의 SVG 텍스트도 11px 이상이다", async ({ page }) => {
  await seed(page);
  await page.goto("/allocation/macro", { waitUntil: "networkidle" });
  await expect(page.locator(".as-rge")).toBeVisible({ timeout: 20_000 });

  const drawn = await page.locator(".as-rgg-svg").count();
  test.skip(!drawn, "이 환경에서 상태전환 모형이 미가용이라 그래프가 없다");

  const texts = page.locator(".as-rgg-svg text");
  const n = await texts.count();
  expect(n, "SVG 텍스트 노드 수").toBeGreaterThan(4);

  const small = await texts.evaluateAll((els) =>
    els.map((el) => ({ t: (el.textContent || "").slice(0, 20), px: parseFloat(getComputedStyle(el).fontSize) }))
      .filter((x) => x.px < 11));
  expect(small, "11px 미만 SVG 텍스트 — CSS 로는 못 고친다, 컴포넌트가 직접 써야 한다").toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`대비: 0M 국면 패널 (${theme}) — AA 실패 0 · 밝은 배경 누출 0`, async ({ page }) => {
    await seed(page);
    await page.goto("/allocation/macro", { waitUntil: "networkidle" });
    if (theme === "dark") {
      await page.evaluate(() => document.documentElement.classList.add("dark"));
    }
    await expect(page.locator(".as-rge")).toBeVisible({ timeout: 20_000 });
    // 도구 카드가 실제로 그려진 뒤에 재야 한다 — 로딩 중을 재면 아무것도 검사하지 않는다.
    await expect(page.locator(".as-rge-tool").first()).toBeVisible({ timeout: 20_000 });

    const r: AuditResult = await page.evaluate(contrastAudit(".as-rge"));
    expect(r.checked, "검사한 노드 수").toBeGreaterThan(5);
    expect(r.low, `${theme}: AA 미달`).toEqual([]);
    if (theme === "dark") expect(r.bright, "다크에서 밝은 배경 누출").toEqual([]);
  });
}

test("대비: 07 피커 (dark) — AA 실패 0 · 밝은 배경 누출 0", async ({ page }) => {
  await stubRunAndAttribution(page);
  await seed(page);
  await page.goto("/allocation/explain", { waitUntil: "networkidle" });
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await expect(page.locator(".as-attr-pick")).toBeVisible({ timeout: 20_000 });

  const r: AuditResult = await page.evaluate(contrastAudit(".as-attr-pick"));
  expect(r.checked, "검사한 노드 수").toBeGreaterThan(3);
  expect(r.low, "다크: AA 미달").toEqual([]);
  expect(r.bright, "다크에서 밝은 배경 누출").toEqual([]);
});
