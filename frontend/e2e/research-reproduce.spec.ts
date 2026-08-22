import { expect, test, type Page } from "@playwright/test";
import { contrastAudit } from "./helpers";

type AuditResult = { checked: number; low: unknown[]; bright: unknown[] };

// ═══════════════════════════════════════════════════════════════════════════════
// P1 — 재현: 다섯 상태를 서로 다른 문장으로 말한다
// ─────────────────────────────────────────────────────────────────────────────
// 지금까지 ResearchRun 은 **영수증**이었다. 무엇을 넣었고 무엇이 나왔는지는 적혀
// 있지만, 다시 돌려 같은 답이 나오는지 확인할 방법이 없었다. `reopenRun` 은 입력을
// 화면에 되돌릴 뿐 재실행·대조를 하지 않는다.
//
// ★이 스펙은 백엔드 산수를 재지 않는다★ 그건 pytest(test_research_reproduce.py) 가
// 10건으로 잠갔다. 여기서 재는 것은 **화면이 다섯 상태를 구분하는가** 이고, 그래서
// 응답을 전부 스텁한다 — 결정적이고, 서버에 상태를 남기지 않는다(A4 의 Alpha Lab
// 스펙이 ResearchRun 을 기록해 research-run-roundtrip 을 타임아웃시킨 전례가 있다).
// ═══════════════════════════════════════════════════════════════════════════════

const API = "**/api/backend/api/v1/research-runs**";
const RUN_ID = "rr_spec_fixture";

const LIST = {
  available: true,
  runs: [{
    run_id: RUN_ID, created_at: 1_770_000_000, kind: "allocation_analyze",
    name: "재현 스펙 픽스처", code_version: "dev", parent_run_id: null, note: null,
    snapshot: { coverage: { start: "2025-01-02", end: "2026-08-03", source: "db" } },
  }],
};

/** 목록은 항상 같은 한 건, 재현 응답만 케이스별로 바꾼다. */
async function mount(page: Page, reproduce: unknown | "abort") {
  await page.route(API, async (route) => {
    const url = route.request().url();
    if (url.includes("/reproduce")) {
      if (reproduce === "abort") return route.abort("failed");
      return route.fulfill({ status: 200, contentType: "application/json",
                             body: JSON.stringify(reproduce) });
    }
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({ status: 200, contentType: "application/json",
                           body: JSON.stringify(LIST) });
  });
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-rr-item")).toHaveCount(1, { timeout: 20_000 });
}

async function clickReproduce(page: Page) {
  await page.locator(".as-rr-repro").click();
  await expect(page.locator(".as-rr-repro-out")).toBeVisible({ timeout: 20_000 });
}

const DONE = {
  reproducible: true, run_id: RUN_ID, kind: "allocation_analyze",
  basis: "recorded_as_of", as_of: "2026-08-03", estimated: false,
  weights: { recorded: { "005930": 60 }, fresh: { "005930": 60 } },
  verdict: "identical", max_delta_pp: 0, deltas: [],
  universe_changed: { dropped: [], added: [] },
};

// ── 1. ★재현됨★ ─────────────────────────────────────────────────────────────
test("재현되면 기준일과 함께 '재현됨' 이라고 말한다", async ({ page }) => {
  test.setTimeout(120_000);
  await mount(page, DONE);
  await clickReproduce(page);
  const ok = page.locator(".as-rr-repro-ok");
  await expect(ok).toBeVisible();
  await expect(ok).toContainText("재현됨");
  await expect(ok).toContainText("2026-08-03");
  // 확정 재현에는 추정 배지가 붙으면 안 된다.
  await expect(page.locator(".as-rr-repro-est")).toHaveCount(0);
});

// ── 2. ★달라지면 무엇이 얼마나 움직였는지 말한다★ (1번의 짝) ────────────────
test("★비중이 달라지면 '재현됨' 이라고 하지 않는다★", async ({ page }) => {
  test.setTimeout(120_000);
  await mount(page, {
    ...DONE, verdict: "drifted", max_delta_pp: 7.5,
    weights: { recorded: { "005930": 60 }, fresh: { "005930": 67.5 } },
    deltas: [{ code: "005930", recorded: 60, fresh: 67.5, delta_pp: 7.5 }],
  });
  await clickReproduce(page);
  await expect(page.locator(".as-rr-repro-ok")).toHaveCount(0);
  const dr = page.locator(".as-rr-repro-drift");
  await expect(dr).toContainText("달라졌");
  await expect(dr).toContainText("7.50%p");
  await expect(dr, "무엇이 움직였는지 말하지 않는다").toContainText("005930");
});

// ── 3. ★추정 재현은 추정이라고 적는다★ ─────────────────────────────────────
test("★관측 마지막 날로 맞춘 재현은 '추정' 이라고 밝힌다★", async ({ page }) => {
  test.setTimeout(120_000);
  await mount(page, { ...DONE, basis: "coverage_end", estimated: true });
  await clickReproduce(page);
  await expect(page.locator(".as-rr-repro-est"),
    "추정인데 확정 재현과 같은 무게로 그렸다").toBeVisible();
  await expect(page.locator(".as-rr-repro-out")).toContainText("추정");
});

// ── 4. ★비교 불가는 일치가 아니다★ ─────────────────────────────────────────
test("★대조할 것이 없으면 '재현됨' 이 아니라 '대조할 수 없습니다' 다★", async ({ page }) => {
  test.setTimeout(120_000);
  await mount(page, {
    reproducible: true, run_id: RUN_ID, kind: "allocation_analyze",
    basis: "server_stamped", as_of: "2026-08-03", estimated: false,
    weights: { recorded: null, fresh: { "005930": 60 } },
    verdict: "incomparable",
    reason: "이 런에는 최적 비중이 기록돼 있지 않아 대조할 수 없습니다.",
  });
  await clickReproduce(page);
  await expect(page.locator(".as-rr-repro-ok")).toHaveCount(0);
  await expect(page.locator(".as-rr-repro-incomp")).toContainText("대조할 수 없");
});

// ── 5. 재현 불가와 응답 없음은 서로 다른 화면이다 ───────────────────────────
test("재현 좌표가 없으면 그 사실을 말한다", async ({ page }) => {
  test.setTimeout(120_000);
  await mount(page, {
    reproducible: false, run_id: RUN_ID, kind: "allocation_analyze", basis: "none",
    reason: "이 런에는 재현 좌표가 없습니다 — as_of 도, 서버가 쓴 절단일도 없습니다.",
  });
  await clickReproduce(page);
  await expect(page.locator(".as-rr-repro-no")).toContainText("재현할 수 없");
  await expect(page.locator(".as-rr-repro-ok")).toHaveCount(0);
  await expect(page.locator(".as-rr-repro-net")).toHaveCount(0);
});

test("응답을 못 받으면 재현 실패가 아니라 네트워크라고 말한다", async ({ page }) => {
  test.setTimeout(120_000);
  await mount(page, "abort");
  await clickReproduce(page);
  await expect(page.locator(".as-rr-repro-net")).toContainText("응답이 없");
  await expect(page.locator(".as-rr-repro-no")).toHaveCount(0);
});

// ── 6. 다섯 문장이 서로 다르다 (같은 문구를 돌려쓰면 구분이 아니다) ─────────
test("다섯 상태의 문구가 서로 다르다", async ({ page }) => {
  test.setTimeout(180_000);
  const cases: [unknown | "abort", string][] = [
    [DONE, ".as-rr-repro-ok"],
    [{ ...DONE, verdict: "drifted", max_delta_pp: 7.5,
       deltas: [{ code: "005930", recorded: 60, fresh: 67.5, delta_pp: 7.5 }] },
     ".as-rr-repro-drift"],
    [{ ...DONE, verdict: "incomparable", weights: { recorded: null, fresh: {} },
       reason: "최적 비중이 기록돼 있지 않습니다." }, ".as-rr-repro-incomp"],
    [{ reproducible: false, run_id: RUN_ID, kind: "allocation_analyze", basis: "none",
       reason: "재현 좌표가 없습니다." }, ".as-rr-repro-no"],
    ["abort", ".as-rr-repro-net"],
  ];
  const texts: string[] = [];
  for (const [body, sel] of cases) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await mount(page, body);
    await clickReproduce(page);
    texts.push((await page.locator(sel).innerText()).trim());
  }
  expect(texts, "다섯 상태를 모두 잡지 못했다").toHaveLength(5);
  expect(new Set(texts).size, "같은 문장을 돌려쓰고 있다 — 구분이 아니다").toBe(5);
});

// ── 7. 재현은 되돌리기와 다른 동작이다 ──────────────────────────────────────
test("★재현은 작업 중인 상태를 바꾸지 않는다★", async ({ page }) => {
  test.setTimeout(120_000);
  await mount(page, DONE);
  // 되돌리기는 위저드를 덮어쓴다(확인 창까지 띄운다). 재현은 아무것도 바꾸면 안 된다.
  const url = page.url();
  const before = await page.locator(".as-rr-item.active").count();
  await clickReproduce(page);
  expect(page.url(), "재현이 화면을 이동시켰다").toBe(url);
  expect(await page.locator(".as-rr-item.active").count(),
    "재현이 활성 런을 바꿨다 — 되돌리기와 같은 동작이 됐다").toBe(before);
});

// ── 8. §56 하한 + 라이트/다크 AA ────────────────────────────────────────────
test("재현 결과가 타입 하한과 대비를 지킨다", async ({ page }) => {
  test.setTimeout(180_000);
  await mount(page, { ...DONE, basis: "coverage_end", estimated: true });
  await clickReproduce(page);

  const sizes = await page.locator(".as-rr-repro-out, .as-rr-repro, .as-rr-repro-est")
    .evaluateAll((els) => els.map((e) => parseFloat(getComputedStyle(e).fontSize)));
  expect(sizes.length, "잴 노드가 없다 — 빈 선택자는 통과가 아니다").toBeGreaterThanOrEqual(3);
  for (const s of sizes) expect(s).toBeGreaterThanOrEqual(11);

  for (const dark of [false, true]) {
    await page.emulateMedia({ colorScheme: dark ? "dark" : "light" });
    await page.evaluate((d) => document.documentElement.classList.toggle("dark", d), dark);
    await page.waitForTimeout(200);      // 전이 중간값이 잡히는 것을 피한다 (A9)
    const audit = await page.evaluate<AuditResult>(contrastAudit(".aas-root"));
    expect(audit.checked, "검사한 텍스트 노드가 0 이면 조용히 통과한다").toBeGreaterThan(10);
    expect(audit.low, `${dark ? "다크" : "라이트"} AA 미달`).toEqual([]);
    // ★`bright` 는 다크에서만 의미가 있다★ 이 감사기는 휘도 0.6 초과 배경을 **모드와
    // 무관하게** 담으므로 라이트에서는 당연히 비지 않는다(첫 작성에서 그걸 라이트에도
    // 걸어 스펙이 빨갰다 — 제품이 아니라 단언이 틀렸다). `aas-dark.spec.ts` 도 다크에만
    // 건다. 여기서 잡는 것은 "글자만 뒤집히고 배경이 흰 채로 남는" 반쪽 다크다.
    if (dark) expect(audit.bright, "다크인데 밝은 배경이 남아 있다").toEqual([]);
  }
});
