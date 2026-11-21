import { readFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "./fixtures";
import { trackErrors, contrastAudit, type AuditResult } from "./helpers";

/**
 * P4 매크로 지능 패널 — 정직성 계약 (P4-V)
 * ==========================================================================
 * D1~D5·M1~M3 가 만든 것을 `/macro` 가 그린다. 이 스펙이 지키는 것은 "숫자가
 * 맞다" 가 아니라 **"거짓말을 하지 않는다"** 이다:
 *
 *   · 미가용이면 숫자를 하나도 내지 않고 사유를 낸다
 *   · 적중률 옆에 예측집합 크기가 **항상** 있다 (집합을 키우면 적중률은 오른다)
 *   · 개정 편향 사유는 접히지 않는다
 *   · 키 값은 어떤 형태로도 화면에 없다
 *
 * ★서버를 스텁한다★ 라이브 매크로 수집은 느리고(사다리 프로브가 실제로 수집한다)
 * 환경마다 값이 달라 단언이 불안정해진다. 프록시 경로(`/api/backend/**`)만 가로채고
 * 문서 내비게이션은 건드리지 않는다 — A6 에서 글롭이 문서까지 삼켜 페이지가 날 JSON
 * 으로 렌더된 전례가 있다.
 */

const CONSENSUS_SPLIT = {
  verdict: "Goldilocks", consensus: false, tie: false, n_available: 2,
  per_tool: { axis: "Goldilocks", markov: "Stagflation" },
  unavailable: ["cluster"],
  reasons: { cluster: "표본이 부족해 GMM 이 수렴하지 않았습니다" },
  disagreement: { score: 1.0, unique: 2, counts: { Goldilocks: 1, Stagflation: 1 }, n: 2 },
  note: "판정이 1:1 로 갈렸습니다",
};

const FORECAST_OK = {
  available: true, target: 0.9, coverage: 0.966, hits: 28, misses: 1, n_eval: 29,
  mean_set_size: 2.72, k: 1, walk_forward: true,
  note: "walk-forward 실측 적중률입니다 — 평균 집합 크기와 함께 읽어야 합니다.",
};

const LONGRUN_VECM = {
  available: true, model: "vecm", coint_rank: 1,
  variables: ["KR_BASE_RATE", "KR_CPI", "USD_KRW"],
  reason: "요한센 trace 검정에서 공적분 랭크 1 이 유의합니다(95%) — 오차수정항을 갖는 VECM 을 씁니다.",
  evidence: { test: "johansen_trace", trace_stat: [40.1, 12.0], crit_95: [29.8, 15.5] },
  span: { n: 240, k: 3, requested: 240 },
  requested: ["KR_BASE_RATE", "KR_CPI", "USD_KRW"],
  used: ["KR_BASE_RATE", "KR_CPI", "USD_KRW"],
};

const COVERAGE = {
  providers: [
    { provider: "ECOS", declared: 40, verified: 8, derived: 3, backtest_eligible: false,
      revision_bias_note: "한국은행 ECOS 는 빈티지(개정 이력) 엔드포인트를 제공하지 않습니다 — 개정 편향이 남습니다." },
    { provider: "FRED", declared: 21, verified: 21, derived: 0, backtest_eligible: true,
      revision_bias_note: null },
  ],
  keys: [
    { label: "한국은행 ECOS", env_vars: ["BOK_API_KEY"], configured: false, provider: "ECOS",
      series_count: 40, capability_requirements: [], unlocks_levels: [],
      unlocks: "한국 매크로 계열 — 계열 40종" },
    { label: "LLM (Anthropic)", env_vars: ["ANTHROPIC_API_KEY"], configured: false, provider: null,
      series_count: 0, capability_requirements: ["llm"], unlocks_levels: ["L0"],
      unlocks: "공시문 → 뷰 변환 — 사다리 요건 llm, 레벨 L0" },
  ],
  ladder: { level: "L1", note: "DeePM + 수익률곡선", blocked_level: "L0",
            blocked_reason: "torch 미설치 · 실측 표본 부족" },
};

/**
 * 국면 예측 비교(M2) — 표가 있는 응답. ★손으로 지은 것이 아니다★ 서버의 캔버스 노드를 긴 합성 계열로 돌린 출력이고
 * (`frontend/e2e/fixtures/regime-skill-node.json`), pytest `test_the_screen_fixture_is_what_the_node_produces` 가 그 고정물 = 지금 서버의 출력을 건다.
 * 노드의 `view.result` = 문(`/macro/regime-skill`)의 답이다(pytest `test_the_node_equals_the_view_when_there_is_a_table`).
 */
type SkillC = { key: string; name: string; available: boolean; hit_rate: number | null; brier: number | null; gain: number | null;
  evidence: { peak: number; passed: boolean; saturated: boolean; e_value: number } | null; reason: string | null };
type Skill = { candidates: SkillC[]; baseline: string; n_eval: number; k: number; note: string; not_measured: string[];
  evidence: { computed: boolean; threshold: number; note: string; reason: string | null } };
const SKILL_OK = (JSON.parse(readFileSync(path.join(__dirname, "fixtures/regime-skill-node.json"), "utf8")) as { view: { result: Skill } }).view.result;
const skillCopy = (): Skill => structuredClone(SKILL_OK);

/** 화면 규칙(`entities/macro/skill.ts`)을 시험 쪽에서 다시 적는다 — 칸 글자 = 서버 값의 이 서식. */
const fmt = {
  hit: (c: SkillC) => `${((c.hit_rate as number) * 100).toFixed(0)}%`,
  brier: (c: SkillC) => (c.brier as number).toFixed(3),
  gain: (c: SkillC) => `${(c.gain as number) >= 0 ? "+" : "\u2212"}${Math.abs(c.gain as number).toFixed(3)}`,
  ev: (c: SkillC) => {
    const e = c.evidence;
    if (!e) return "—";
    const v = e.saturated ? "10¹² 이상" : e.peak >= 1000 ? Math.round(e.peak).toLocaleString("ko-KR") : e.peak.toFixed(2);
    return e.passed ? `${v}*` : v;
  },
};

/** 프록시 API 경로만 가로챈다 — 문서 내비게이션은 절대 건드리지 않는다. */
async function stubIntel(page: import("@playwright/test").Page, over: {
  consensus?: unknown; forecast?: unknown; longRun?: unknown; coverage?: unknown;
} = {}) {
  const json = (body: unknown) => ({ status: 200, contentType: "application/json",
                                     body: JSON.stringify(body) });
  await page.route("**/api/backend/api/v1/macro/regime-consensus**",
    (r) => r.fulfill(json(over.consensus ?? CONSENSUS_SPLIT)));
  await page.route("**/api/backend/api/v1/macro/regime-forecast-coverage**",
    (r) => r.fulfill(json(over.forecast ?? FORECAST_OK)));
  await page.route("**/api/backend/api/v1/macro/long-run**",
    (r) => r.fulfill(json(over.longRun ?? LONGRUN_VECM)));
  await page.route("**/api/backend/api/v1/macro/source-coverage**",
    (r) => r.fulfill(json(over.coverage ?? COVERAGE)));
}

test.describe("P4 매크로 지능 패널", () => {
  test("★미가용 블록은 숫자를 하나도 내지 않고 사유를 낸다★", async ({ page }) => {
    await stubIntel(page, {
      forecast: { available: false, reason: "평가 시점이 4개로 최소 20개에 못 미칩니다." },
      longRun: { available: false, reason: "관측이 30개로 최소 60개에 못 미칩니다." },
    });
    await page.goto("/macro");
    const panel = page.locator(".mx-panel");
    await expect(panel).toBeVisible();

    // 사유가 보인다
    await expect(panel.getByText("평가 시점이 4개로")).toBeVisible();
    await expect(panel.getByText("관측이 30개로")).toBeVisible();

    // ★그리고 그 자리에 통계 숫자가 없다★ 노드 수를 먼저 단언해 빈 선택자가
    // 통과하는 것을 막는다(A7 에서 그 실패를 겪었다).
    const reasons = panel.locator(".mx-reason");
    expect(await reasons.count()).toBeGreaterThanOrEqual(2);
    expect(await panel.locator(".mx-stat-v").count()).toBe(0);
  });

  test("★적중률 옆에 예측집합 크기가 항상 있다★", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const stats = page.locator(".mx-panel .mx-stats");
    await expect(stats).toBeVisible();
    // 집합을 키우면 적중률은 언제든 올라간다 — 둘이 떨어지면 화면이 거짓말을 한다.
    await expect(stats).toContainText("96.6%");
    await expect(stats).toContainText("2.72");
    await expect(stats).toContainText("90%");
  });

  test("갈린 판정을 만장일치로 그리지 않고, 개별 도구 판정이 남는다", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const panel = page.locator(".mx-panel");
    await expect(panel.locator(".mx-split")).toBeVisible();      // "갈림"
    await expect(panel.locator(".mx-tools")).toContainText("axis");
    await expect(panel.locator(".mx-tools")).toContainText("markov");
    // 미가용 도구는 사유와 함께 이름이 남는다
    await expect(panel.locator(".mx-tools")).toContainText("cluster");
    await expect(panel).toContainText("GMM 이 수렴하지 않았습니다");
  });

  test("짝 — 전부 일치하면 갈림 표시가 없다", async ({ page }) => {
    await stubIntel(page, {
      consensus: {
        verdict: "Goldilocks", consensus: true, tie: false, n_available: 4,
        per_tool: { axis: "Goldilocks", markov: "Goldilocks", cluster: "Goldilocks", kmeans: "Goldilocks" },
        unavailable: [], reasons: {},
        disagreement: { score: 0, unique: 1, counts: { Goldilocks: 4 }, n: 4 },
        note: "가용한 도구 4개가 모두 일치합니다. 군집 두 방법(GMM · k-평균)은 같은 좌표를 묶는 방법이라 서로 독립이 아닙니다.",
        seed_unstable: [],
      },
    });
    await page.goto("/macro");
    await expect(page.locator(".mx-panel .mx-split")).toHaveCount(0);
    // 넷째 팔(M1)의 이름표 — 서버 키를 그대로 보이지 않고 이름을 붙인다(키는 곁에 남는다)
    await expect(page.locator(".mx-panel .mx-tools")).toContainText("군집(k-평균)");
    await expect(page.locator(".mx-panel .mx-tools")).toContainText("kmeans");
    // 합의 블록의 서버 문장(패널에는 .mx-why 가 블록마다 있다 — 합의 블록으로 좁힌다)
    const consensusCard = page.locator(".mx-panel .mx-card", { has: page.locator(".mx-card-t", { hasText: "국면 판정 도구끼리 맞는지" }) });
    await expect(consensusCard.locator(".mx-why")).toContainText("서로 독립이 아닙니다");
    await expect(page.locator(".mx-panel .mx-seed")).toHaveCount(0);   // 짝 — 시드에 따라 갈리는 도구가 없으면 그 줄도 없다
    // BU5c: 국면 이름은 한국어(번역표 `regimeName`) — 서버 열거값을 옮길 뿐 판단은 서버 것 그대로
    await expect(page.locator(".mx-panel .mx-tools")).toContainText("골디락스");
  });

  test("M1 — 판정이 모두 같아도 시드에 따라 갈리는 도구가 있으면 그 사실이 곁에 선다", async ({ page }) => {
    await stubIntel(page, {
      consensus: {
        verdict: "Stagflation", consensus: true, tie: false, n_available: 4,
        per_tool: { axis: "Stagflation", markov: "Stagflation", cluster: "Stagflation", kmeans: "Stagflation" },
        unavailable: [], reasons: {},
        disagreement: { score: 0, unique: 1, counts: { Stagflation: 4 }, n: 4 },
        note: "가용한 도구 4개가 모두 'Stagflation' 로 일치합니다. 군집 모형(GMM)의 답은 난수 시드에 따라 갈립니다(시드별 최다 답이 과반이 아닙니다).",
        seed_unstable: ["cluster"],
      },
    });
    await page.goto("/macro");
    // 패널에는 `.mx-ok` 가 블록마다 있다(데이터 출처 · 키) — 합의 블록으로 좁힌다.
    const consensusCard = page.locator(".mx-panel .mx-card", { has: page.locator(".mx-card-t", { hasText: "국면 판정 도구끼리 맞는지" }) });
    const line = consensusCard.locator(".mx-verdict-s");
    await expect(line.locator(".mx-ok")).toHaveText("사용 가능한 도구가 모두 동일합니다");   // 판정이 같다는 사실은 그대로 선다
    await expect(line).not.toContainText("엇갈렸습니다");                                   // 갈림으로 바꿔 그리지 않는다
    await expect(line.locator(".mx-seed")).toHaveText("난수 시드에 따라 답이 갈리는 도구가 있습니다");
    await expect(consensusCard.locator(".mx-tools li")).toHaveCount(4);
    await expect(consensusCard.locator(".mx-why")).toContainText("난수 시드에 따라 갈립니다");
  });

  test("모형 선택 사유와 검정 근거가 함께 보인다", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const panel = page.locator(".mx-panel");
    await expect(panel).toContainText("VECM");
    await expect(panel).toContainText("요한센 trace 검정에서 공적분 랭크 1");
    // 결론만 내지 않는다 — 통계량과 임계값이 표에 있다
    // ★표가 둘이다(장기관계·커버리지) — strict mode 위반을 피해 첫 표만 본다★
    const lrTbl = panel.locator(".mx-tbl").first();
    await expect(lrTbl).toContainText("40.10");
    await expect(lrTbl).toContainText("29.80");
  });

  test("★개정 편향 사유가 접히지 않는다★", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const bias = page.locator(".mx-panel .mx-bias");
    // ★`.count()` 는 auto-wait 하지 않는다★ 커버리지 블록은 네 번째 쿼리라 늦게
    // 오는데, 세지기 전에 기다리지 않으면 0 을 읽고 "사유가 없다" 로 오판한다.
    await expect(bias.first()).toBeVisible();
    expect(await bias.count()).toBeGreaterThanOrEqual(1);
    await expect(bias.first()).toContainText("빈티지");
    // 접힌 <details> 안에 있으면 안 된다 — 경고는 접지 않는다(A5 경계)
    expect(await page.locator(".mx-panel details:not([open]) .mx-bias").count()).toBe(0);
  });

  test("키 슬롯은 존재 여부만 그리고 값을 그리지 않는다", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const keys = page.locator(".mx-panel .mx-keys li");
    await expect(keys.first()).toBeVisible();   // `.count()` 는 기다리지 않는다
    expect(await keys.count()).toBeGreaterThanOrEqual(2);
    await expect(page.locator(".mx-panel")).toContainText("BOK_API_KEY");
    await expect(page.locator(".mx-panel")).toContainText("미설정");
    // 이 키를 넣으면 무엇이 열리는지가 적혀 있다
    await expect(page.locator(".mx-panel")).toContainText("계열 40종");
    await expect(page.locator(".mx-panel")).toContainText("레벨 L0");
  });

  test("패널이 콘솔 오류나 4xx/5xx 없이 렌더된다", async ({ page }) => {
    const sink = trackErrors(page);
    await stubIntel(page);
    await page.goto("/macro");
    await expect(page.locator(".mx-panel")).toBeVisible();
    expect(sink.pageErrors, sink.pageErrors.join("\n")).toEqual([]);
    expect(sink.api404, sink.api404.join("\n")).toEqual([]);
  });

  test("타입 하한(§56)과 라이트/다크 대비", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    await expect(page.locator(".mx-panel")).toBeVisible();
    // 네 블록이 모두 온 뒤에 잰다 — 마지막 블록의 노드가 빠지면 감사가 헐거워진다.
    await expect(page.locator(".mx-panel .mx-keys li").first()).toBeVisible();

    // 하한 — 노드 수를 먼저 단언한다
    const sizes = await page.locator(".mx-panel *").evaluateAll((els) =>
      els.filter((e) => (e.textContent || "").trim().length > 0 && e.children.length === 0)
         .map((e) => parseFloat(getComputedStyle(e).fontSize)));
    expect(sizes.length).toBeGreaterThan(10);
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11);

    for (const dark of [false, true]) {
      await page.evaluate((d) => {
        document.documentElement.setAttribute("data-theme", d ? "dark" : "light");
        if (d) document.documentElement.classList.add("dark");
        else document.documentElement.classList.remove("dark");
      }, dark);
      // 전이 중간값이 잡히지 않게 — A9 에서 값을 치른 절차
      await page.waitForTimeout(200);
      // ★`contrastAudit` 는 평가식 문자열을 돌려주고, `page.evaluate` 가 객체를
      // 그대로 준다★ JSON.parse 를 끼우면 "[object Object]" 를 파싱하려다 죽는다.
      const res = await page.evaluate<AuditResult>(contrastAudit(".mx-panel"));
      expect(res.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(10);
      expect(res.low, `${dark ? "dark" : "light"} AA 미달`).toEqual([]);
      // ★`bright` 는 **다크 전용** 검사다★ "글자만 뒤집히고 배경이 흰 채로 남는" 반만
      // 다크인 상태를 잡는 것이고(aas-dark.spec.ts 가 세운 용법), 라이트에서 밝은
      // 배경은 정상이다. 라이트에도 걸면 올바른 화면이 빨개진다 — 처음에 그렇게 썼다.
      if (dark) {
        expect(res.bright, `다크인데 밝은 배경이 남아 있다`).toEqual([]);
      }
    }
  });

  // ── BU5c — 실패와 미가용을 가른다 · 그림 더함 · 글 ─────────────────────────
  for (const [key, path] of [
    ["consensus", "regime-consensus"], ["forecast", "regime-forecast-coverage"],
    ["longRun", "long-run"], ["coverage", "source-coverage"],
  ] as const) {
    test(`BU5c 실패 — ${key} 500: 그 블록에 alert + 재시도 → 풀면 회복(미가용 배지가 아니다)`, async ({ page }) => {
      await stubIntel(page);
      await page.route(`**/api/backend/api/v1/macro/${path}**`,
        (r) => r.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
      await page.goto("/macro");
      const alert = page.locator(".mx-panel [role=alert]");
      await expect(alert).toHaveCount(1, { timeout: 20_000 });
      await page.unroute(`**/api/backend/api/v1/macro/${path}**`);
      await stubIntel(page);
      await alert.getByRole("button", { name: "재시도" }).click();
      await expect(page.locator(".mx-panel [role=alert]")).toHaveCount(0, { timeout: 20_000 });
    });
  }

  test("BU5c 짝 — 서버가 미가용이라고 답하면 사유 배지이고 alert 가 아니다", async ({ page }) => {
    await stubIntel(page, { forecast: { available: false, reason: "평가 시점이 4개로 최소 20개에 못 미칩니다." } });
    await page.goto("/macro");
    await expect(page.locator(".mx-panel").getByText("평가 시점이 4개로")).toBeVisible();
    await expect(page.locator(".mx-panel .mx-keys li").first()).toBeVisible();
    expect(await page.locator(".mx-panel [role=alert]").count()).toBe(0);
  });

  test("BU5c 그림 — 공적분 통계량 막대 수 = 가설 수, 적중률 막대에 목표 눈금(표·숫자는 그대로)", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    await expect(page.locator(".mx-panel .mx-trace-row")).toHaveCount(LONGRUN_VECM.evidence.trace_stat.length, { timeout: 20_000 });
    await expect(page.locator(".mx-panel .mx-cov-bar .mx-cov-target")).toHaveCount(1);
    await expect(page.locator(".mx-panel .mx-tbl").first()).toContainText("40.10");
  });

  test("BU5c 능력 단계: 사람 말 한 줄 + 원래 사유는 닫힌 details 안에 그대로", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    const ladder = page.locator(".mx-panel .mx-ladder");
    await expect(ladder).toContainText("레벨 L1", { timeout: 20_000 });
    const raw = page.locator(".mx-panel details.mx-raw");
    await expect(raw).toHaveCount(1);
    expect(await raw.textContent()).toContain("torch 미설치");
  });

  test("BU5c 글 — em-dash 0 · 영어 꼬리표 0(국면 이름·forward-only) · 툴팁 0", async ({ page }) => {
    await stubIntel(page);
    await page.goto("/macro");
    await expect(page.locator(".mx-panel .mx-keys li").first()).toBeVisible({ timeout: 20_000 });
    const r = await page.locator(".mx-panel").evaluate((root) => {
      const texts: string[] = [];
      const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let n: Node | null;
      while ((n = walk.nextNode())) {
        const el = n.parentElement!; const s = (n.textContent ?? "").trim();
        if (!s || !el.getClientRects().length || el.closest("[data-server]")) continue;
        texts.push(s);
      }
      return { texts, titles: root.querySelectorAll("[title]").length };
    });
    expect(r.texts.length).toBeGreaterThan(10);
    expect(r.texts.filter((s) => s.includes("—")), "보이는 em-dash").toEqual([]);
    expect(r.texts.filter((s) => /\b(Goldilocks|Stagflation|forward-only|trace 통계량)\b|r ≤/.test(s)), "영어 꼬리표").toEqual([]);
    expect(r.titles).toBe(0);
  });

  // ── M2 — 국면 예측 비교: 단추로만 계산 · 서버 순서 그대로 · 이긴 행을 칠하지 않는다 ─────────────────────
  const skillCard = (page: import("@playwright/test").Page) =>
    page.locator(".mx-panel .mx-card", { has: page.locator(".mx-card-t", { hasText: "국면 예측 비교" }) });
  async function stubSkill(page: import("@playwright/test").Page, body: unknown, asked: string[] = []) {
    await page.route("**/api/backend/api/v1/macro/regime-skill**", (r) => {
      asked.push(r.request().url());
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    return asked;
  }
  /** 칸 글자 = 서버 값의 서식 · 행 순서 = 서버 순서 · 기준선 · 세우지 못한 후보 — 표 하나를 통째로 견준다. */
  async function checkSkillTable(page: import("@playwright/test").Page, d: Skill) {
    const rows = skillCard(page).locator(".mx-skill tbody tr");
    await expect(rows).toHaveCount(d.candidates.length);
    expect(await rows.evaluateAll((trs) => trs.map((tr) => tr.getAttribute("data-key"))), "행 순서 = 서버의 고정 순서").toEqual(d.candidates.map((c) => c.key));
    for (const c of d.candidates) {
      const row = skillCard(page).locator(`.mx-skill tbody tr[data-key="${c.key}"]`);
      await expect(row.locator("th")).toHaveText(c.name);                          // 이름표 = 서버 이름(화면이 짓지 않는다)
      const cells = row.locator("td");
      if (!c.available) {
        await expect(cells, c.key).toHaveCount(1);                                   // 숫자 칸 없음
        await expect(cells.first()).toHaveText(`값 없음 · ${c.reason}`);
      } else if (c.key === d.baseline) {
        await expect(cells, c.key).toHaveText([fmt.hit(c), fmt.brier(c), "기준선"]);
      } else {
        await expect(cells, c.key).toHaveText([fmt.hit(c), fmt.brier(c), fmt.gain(c), fmt.ev(c)]);
      }
    }
    // ★이긴 행을 칠하지 않는다★ 기준선이 아닌 채점된 행의 숫자 칸은 굵기 · 글자색 · 바탕이 모두 같다(기준을 넘은 행도 '*' 글자만 다르다).
    // 행은 서버 값으로 고른다(클래스로 고르면 이긴 행에 클래스를 붙이는 결함이 걸러져 빠진다) — 행 자신과 숫자 칸의 모양.
    const scored = d.candidates.filter((c) => c.available && c.key !== d.baseline).map((c) => c.key);
    const looks = await rows.evaluateAll((trs, keys) => trs.filter((tr) => keys.includes(tr.getAttribute("data-key") ?? "")).map((tr) => {
      const own = getComputedStyle(tr);
      return [`${own.fontWeight}|${own.color}|${own.backgroundColor}`, ...Array.from(tr.querySelectorAll("th, td")).map((td) => {
        const st = getComputedStyle(td); return `${st.fontWeight}|${st.color}|${st.backgroundColor}`; })].join(",");
    }), scored);
    expect(looks.length, "견줄 행이 둘 이상이어야 공허하지 않다").toBeGreaterThanOrEqual(2);
    expect(new Set(looks).size, "행마다 숫자 칸의 모양이 같다").toBe(1);
  }

  test("M2 — 국면 예측 비교는 단추로만 계산한다 · 표는 서버 순서와 서버 값 그대로 · 이긴 행을 칠하지 않는다", async ({ page }) => {
    const sink = trackErrors(page);
    await stubIntel(page);
    const asked = await stubSkill(page, SKILL_OK);
    await page.goto("/macro");
    const card = skillCard(page);
    await expect(card.locator(".mx-skill-run")).toHaveText("계산 시작");
    await expect(page.locator(".mx-panel .mx-keys li").first()).toBeVisible({ timeout: 20_000 });   // 다른 블록이 다 온 뒤에도
    expect(asked, "단추를 누르기 전에는 부르지 않는다(첫 계산이 수십 초)").toEqual([]);
    await card.locator(".mx-skill-run").click();
    await checkSkillTable(page, SKILL_OK);
    expect(asked.length).toBe(1);
    const q = new URL(asked[0]).searchParams;
    expect([q.get("market"), q.get("months"), q.get("k")]).toEqual(["kr", "120", "1"]);
    await expect(card.locator("dl")).toContainText(`${SKILL_OK.n_eval}개`);
    await expect(card.locator(".mx-why[data-server]").first()).toHaveText(SKILL_OK.evidence.note);    // 순차 증거의 뜻 = 서버 문장
    await expect(card.locator(".mx-why[data-server]").last()).toHaveText(SKILL_OK.note);
    await expect(card.locator(".mx-bias")).toContainText(SKILL_OK.not_measured[0]);                  // 재지 않은 것을 접지 않는다
    // 짝: 기준을 넘은 후보가 없는 응답이면 '*' 도 범례도 없다
    expect(SKILL_OK.candidates.some((c) => c.evidence?.passed), "고정물 전제 — 기준을 넘은 후보 없음").toBe(false);
    await expect(card.locator(".mx-skill-pass")).toHaveCount(0);
    expect(await card.locator(".mx-skill td").evaluateAll((tds) => tds.filter((td) => (td.textContent ?? "").includes("*")).length)).toBe(0);
    expect(sink.pageErrors, sink.pageErrors.join("\n")).toEqual([]);
    expect(sink.api404, sink.api404.join("\n")).toEqual([]);
  });

  test("M2 — 기준을 넘은 후보는 '*' 와 범례로 말한다(색이 아니다) · 세우지 못한 후보는 숫자 없이 서버 사유", async ({ page }) => {
    const d = skillCopy();
    const tr = d.candidates.find((c) => c.key === "transition")!;
    tr.evidence = { ...(tr.evidence as NonNullable<SkillC["evidence"]>), peak: 151.37, passed: true };
    for (const c of d.candidates.filter((x) => x.key === "gmm_start" || x.key === "gmm_now")) {
      Object.assign(c, { available: false, hits: null, hit_rate: null, brier: null, gain: null, evidence: null,
        reason: "2019-11 시점에 세우지 못했습니다 — 표본이 부족해 GMM 이 수렴하지 않았습니다" });
    }
    await stubIntel(page);
    await stubSkill(page, d);
    await page.goto("/macro");
    await skillCard(page).locator(".mx-skill-run").click();
    await checkSkillTable(page, d);
    await expect(skillCard(page).locator(`.mx-skill tbody tr[data-key="transition"] td`).last()).toHaveText("151.37*");
    await expect(skillCard(page).locator(".mx-skill-pass")).toHaveText(`* 순차 증거가 기준(${d.evidence.threshold.toFixed(0)})을 넘은 후보입니다.`);
  });

  test("M2 — 순차 증거를 계산하지 않은 응답(k > 1)은 그 사유 · 증거 칸은 0 이 아니라 —", async ({ page }) => {
    const d = skillCopy();
    d.k = 3;
    d.evidence = { ...d.evidence, computed: false,
      reason: "k개월 앞(k > 1) 예측은 앞 예측이 실현되기 전에 다음 예측이 나와 평가 결과가 겹칩니다 — 순차 검정의 전제가 서지 않아 1개월 앞(k = 1)에서만 계산합니다." };
    for (const c of d.candidates) c.evidence = null;
    await stubIntel(page);
    await stubSkill(page, d);
    await page.goto("/macro");
    await skillCard(page).locator(".mx-skill-run").click();
    await checkSkillTable(page, d);
    await expect(skillCard(page).locator(".mx-why", { hasText: "순차 증거를 계산하지 않았습니다." })).toContainText("겹칩니다");
    await expect(skillCard(page).locator(".mx-why[data-server]", { hasText: "상한 가정 없이" })).toHaveCount(0);   // 짝
  });

  test("M2 — 개발 자료(실제 서버)는 평가 시점이 모자라 표 대신 서버 사유를 낸다(지어내지 않는다)", async ({ page }) => {
    await stubIntel(page);                                                      // 다른 블록만 스텁 — 이 블록은 실제 서버
    await page.goto("/macro");
    const card = skillCard(page);
    const resp = page.waitForResponse((r) => r.url().includes("/macro/regime-skill"), { timeout: 60_000 });
    await card.locator(".mx-skill-run").click();
    const body = await (await resp).json();
    expect(body.available).toBe(false);
    await expect(card.locator(".mx-reason")).toContainText("평가 시점이 17개로 최소 20개에 못 미칩니다");
    await expect(card.locator(".mx-skill")).toHaveCount(0);
    await expect(card.locator(".num")).toHaveCount(0);
  });

  for (const width of [390, 360]) test(`M2 — 좁은 화면(${width}px): 표가 카드 안에 든다 · 숫자는 한 줄이고 붙지 않는다 · 이름은 띄어쓰기에서만 접힌다 · '×' 는 뒤 낱말과 한 줄`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    // 가장 긴 숫자 글(상한에 닿은 e-값 '10¹² 이상*')까지 심는다 — 고정물의 그 칸만 덮어쓴다.
    const d = skillCopy();
    const km = d.candidates.find((c) => c.key === "kmeans_share")!;
    km.evidence = { ...(km.evidence as NonNullable<SkillC["evidence"]>), peak: 1e12, saturated: true, passed: true };
    await stubIntel(page);
    await stubSkill(page, d);
    await page.goto("/macro");
    await skillCard(page).locator(".mx-skill-run").click();
    await checkSkillTable(page, d);
    const g = await skillCard(page).locator(".mx-skill").evaluate((tb) => {
      const wrap = tb.parentElement as HTMLElement;
      let minGap = Infinity;
      const wrapped: string[] = [];
      for (const tr of Array.from(tb.querySelectorAll("tbody tr"))) {
        const nums = Array.from(tr.querySelectorAll("td.num"));
        for (let i = 0; i + 1 < nums.length; i++) {
          const a = document.createRange(); a.selectNodeContents(nums[i]);
          const b = document.createRange(); b.selectNodeContents(nums[i + 1]);
          minGap = Math.min(minGap, b.getBoundingClientRect().left - a.getBoundingClientRect().right);
        }
        for (const td of nums) {
          const r = document.createRange(); r.selectNodeContents(td);
          if (new Set(Array.from(r.getClientRects()).map((x) => Math.round(x.top))).size > 1) wrapped.push(td.textContent ?? "");
        }
      }
      const split: string[] = [];
      for (const th of Array.from(tb.querySelectorAll('tbody th[scope="row"]'))) {
        const node = th.firstChild;
        if (!node || node.nodeType !== Node.TEXT_NODE) { split.push(`글 노드 아님: ${th.textContent}`); continue; }
        const text = node.textContent ?? "";
        const spans: [number, number][] = [];
        for (const m of text.matchAll(/[^ ]+/g)) spans.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
        const xi = text.indexOf("×");
        if (xi >= 0) { const next = spans.find(([a]) => a > xi); spans.push([xi, next ? next[1] : xi + 1]); }
        for (const [a, b] of spans) {
          const r = document.createRange(); r.setStart(node, a); r.setEnd(node, b);
          if (new Set(Array.from(r.getClientRects()).map((x) => Math.round(x.top))).size > 1) split.push(text.slice(a, b));
        }
      }
      return { overflow: wrap.scrollWidth - wrap.clientWidth, minGap, wrapped, split };
    });
    expect(g.overflow, "표가 감싼 칸보다 넓은 길이(px) — 옆으로 밀어야 보이는 열이 없다").toBeLessThanOrEqual(0.5);
    expect(g.minGap, "이웃 숫자 사이(px)").toBeGreaterThanOrEqual(4);
    expect(g.wrapped, "두 줄로 감긴 숫자 칸").toEqual([]);
    expect(g.split, "두 줄에 걸친 낱말(또는 '×' 와 뒤 낱말)").toEqual([]);
  });

  test("M2 — 실패(500)는 사유 배지가 아니라 alert + 재시도 · 표가 열린 뒤에도 글 규칙(em-dash 0)과 라이트/다크 대비", async ({ page }) => {
    await stubIntel(page);
    await page.route("**/api/backend/api/v1/macro/regime-skill**",
      (r) => r.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
    await page.goto("/macro");
    await skillCard(page).locator(".mx-skill-run").click();
    await expect(skillCard(page).locator("[role=alert]")).toHaveCount(1, { timeout: 20_000 });
    await page.unroute("**/api/backend/api/v1/macro/regime-skill**");
    await stubSkill(page, SKILL_OK);
    await skillCard(page).getByRole("button", { name: "재시도" }).click();
    await expect(skillCard(page).locator(".mx-skill tbody tr")).toHaveCount(SKILL_OK.candidates.length, { timeout: 20_000 });
    const texts = await skillCard(page).evaluate((root) => {
      const out: string[] = [];
      const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let n: Node | null;
      while ((n = walk.nextNode())) {
        const el = n.parentElement!; const s = (n.textContent ?? "").trim();
        if (s && el.getClientRects().length && !el.closest("[data-server]")) out.push(s);
      }
      return out;
    });
    expect(texts.length).toBeGreaterThan(10);
    expect(texts.filter((s) => s.includes("—")), "보이는 em-dash(서버 문장 밖)").toEqual([]);
    for (const dark of [false, true]) {
      await page.evaluate((dk) => {
        document.documentElement.setAttribute("data-theme", dk ? "dark" : "light");
        document.documentElement.classList.toggle("dark", dk);
      }, dark);
      await page.waitForTimeout(200);
      const res = await page.evaluate<AuditResult>(contrastAudit(".mx-panel .mx-card:has(.mx-skill)"));
      expect(res.checked, "검사한 텍스트 노드 수").toBeGreaterThan(10);
      expect(res.low, `${dark ? "dark" : "light"} AA 미달`).toEqual([]);
      if (dark) expect(res.bright, "다크인데 밝은 배경").toEqual([]);
    }
  });
});
