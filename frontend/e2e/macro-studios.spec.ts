import { test, expect, type Page } from "@playwright/test";
import { freezeCharts, contrastAudit, trackErrors, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// M1-U — /macro/* 5개 서브스튜디오
// ─────────────────────────────────────────────────────────────────────────────
// ★이 스펙이 지키는 것★
// 서버(M1-M)는 스튜디오마다 **두 엔진**을 답한다: 프론티어(이 환경에서 전부 미가용 —
// torch 미설치 · 표본 60 < 240)와 대체(실제로 도는 것). 그리고 `04 TAIL` 은 대체
// 엔진까지 미가용이다 — 임계 90% 초과 관측이 6개뿐이고 GPD 적합에 8개가 필요하다.
//
// 화면이 그 상태를 0 이나 빈 표로 그리면 "계산했더니 0" 과 구분되지 않는다. 그래서
// 아래 가드들은 **미가용 자리에 숫자가 없다**는 것을 직접 잰다. 스텁이 아니라 실제
// 서버 상태로 재는 것이 이 스펙의 값이다 — 이 환경이 진짜로 그 상태이기 때문이다.
// ═══════════════════════════════════════════════════════════════════════════════

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

const STUDIOS: [slug: string, n: string][] = [
  ["tsfm-latent", "01"],
  ["neural-sde", "02"],
  ["causal-deepm", "03"],
  ["pinn-tail", "04"],
  ["agentic-mcp", "05"],
];

/** 미가용의 표지 — UnavailableState 의 꼬리표(`.tstate-unavail-tag`). BU0 에서 글자 `[ N/A ]` 를 이 꼬리표로 바꿨다. */
const NA_MARK = ".tstate-unavail-tag";

async function openStudio(page: Page, slug: string) {
  await page.goto(`/macro/${slug}`, { waitUntil: "networkidle" });
  await expect(page.locator(".ms-studio")).toBeVisible({ timeout: 20_000 });
}

// ── 1. 내비 + 라우트 건강 ─────────────────────────────────────────────────────

test("스튜디오 내비: 6항목 · 활성 표시 · 5개 라우트 도달", async ({ page }) => {
  await page.goto("/macro", { waitUntil: "networkidle" });
  const items = page.locator(".ms-nav .ms-nav-item");
  await expect(items).toHaveCount(6);          // 00 COCKPIT + 5 스튜디오
  // 루트에서는 00 이 활성이고 그것만 활성이다.
  expect(await page.locator('.ms-nav-item[aria-current="page"]').count()).toBe(1);

  for (const [slug] of STUDIOS) {
    await page.locator(`.ms-nav-item[href="/macro/${slug}"]`).click();
    await page.waitForURL(new RegExp(`/macro/${slug}$`), { timeout: 20_000 });
    await expect(page.locator(".ms-studio")).toBeVisible({ timeout: 20_000 });
    expect(await page.locator('.ms-nav-item[aria-current="page"]').count(),
      `${slug}: 활성 항목은 하나`).toBe(1);
  }
});

test("5개 라우트: h1 하나 · 콘솔 에러 0 · 4xx/5xx 0", async ({ page }) => {
  for (const [slug] of STUDIOS) {
    const sink = trackErrors(page);
    await openStudio(page, slug);
    await page.waitForTimeout(400);
    expect(await page.locator("h1").count(), `${slug}: h1 은 하나`).toBe(1);
    expect(sink.pageErrors, `${slug}: 페이지 에러`).toEqual([]);
    expect(sink.api404, `${slug}: 4xx/5xx 응답`).toEqual([]);
  }
});

// ── 2. ★미가용이 숫자를 내지 않는다★ ─────────────────────────────────────────

test("★프론티어 엔진은 미가용이고 사유를 갖는다 — 숫자 자리가 비어 있지 않다★", async ({ page }) => {
  for (const [slug] of STUDIOS) {
    await openStudio(page, slug);
    const card = page.locator(".ms-card-frontier");
    await expect(card).toBeVisible();
    // 이 환경의 실제 상태 — 프론티어는 전부 미가용이다.
    await expect(card.locator(NA_MARK), `${slug}: 프론티어 미가용 표지`).toHaveCount(1);
    // 사유는 **비어 있지 않은 문장**이어야 한다. 사유 없는 미가용은 만들지 않는다.
    const reason = (await card.locator(".tstate-sub").first().textContent()) ?? "";
    expect(reason.trim().length, `${slug}: 미가용 사유 길이`).toBeGreaterThan(10);
  }
});

test("★04 TAIL: 대체 엔진도 미가용 — 그 카드 안에 숫자 노드가 하나도 없다★", async ({ page }) => {
  // 이 환경의 실측: 임계(90%) 초과 6개 < GPD 최소 8개. 서버가 거부한다.
  // 여기서 0 이나 빈 표가 그려지면 "꼬리가 얇다" 로 읽힌다 — 그것이 이 가드의 표적이다.
  await openStudio(page, "pinn-tail");
  const sub = page.locator(".ms-card-sub");
  await expect(sub).toBeVisible();
  await expect(sub.locator(NA_MARK), "대체 엔진 미가용 표지").toHaveCount(1);
  // 산출 표가 아예 없어야 한다(빈 표도 그리지 않는다).
  expect(await sub.locator(".ms-out").count(), "미가용인데 산출 표가 있다").toBe(0);
  // 그리고 사유 밖에는 숫자가 없다. 사유 문장 자체에는 "6개"·"8개" 가 들어가므로
  // **산출 자리**(.ms-out-v)를 직접 센다 — 사유의 숫자와 산출의 숫자를 섞지 않는다.
  expect(await sub.locator(".ms-out-v").count(), "미가용인데 산출값이 있다").toBe(0);
});

// ── 3. ★span 을 항상 적는다 (A8 규칙)★ ───────────────────────────────────────

test("★01 LATENT: 요청보다 짧은 구간이면 화면이 그 사실을 말한다★", async ({ page }) => {
  // 실측: 60개월 요청 → 차분으로 59개 사용 → truncated: true.
  await openStudio(page, "tsfm-latent");
  const span = page.locator(".ms-span");
  await expect(span).toBeVisible({ timeout: 20_000 });
  const txt = (await span.textContent()) ?? "";
  expect(txt, "구간 문장에 관측/요청 수").toMatch(/관측 \d+개 \/ 요청 \d+개/);
  await expect(page.locator(".ms-span-trunc"),
    "잘렸으면 잘렸다고 말한다").toBeVisible();
  expect(txt).toContain("요청보다 짧은 구간");
});

test("★한계(note)는 접히지 않는다 — 03 CAUSAL 의 그레인저 경고★", async ({ page }) => {
  await openStudio(page, "causal-deepm");
  const note = page.locator(".ms-note").last();
  await expect(note).toBeVisible();
  // 닫힌 <details> 안에 있으면 innerText 가 "" 가 된다 — 보이는 텍스트로 확인한다.
  expect((await note.innerText()).length, "note 가 접혀 있다").toBeGreaterThan(10);
  expect(await note.locator("xpath=ancestor::details").count(),
    "한계가 <details> 안에 들어갔다").toBe(0);
});

// ── 4. ★feasible: null 을 "실현가능" 으로 그리지 않는다★ ──────────────────────

test("★05 VIEWS: 시나리오 없이 컴파일하면 '검사하지 않았다' 고 적는다★", async ({ page }) => {
  await openStudio(page, "agentic-mcp");
  await page.locator(".ms-vbtn-run").click();
  await expect(page.locator(".ms-outcome")).toBeVisible({ timeout: 20_000 });
  // ★검사 결과 자리를 비워 두면 "검사했고 문제없음" 으로 읽힌다★
  // 서버 note 도 같은 말을 하지만, note 에만 기대면 UI 가 결과 자리를 비워도 초록이다
  // (첫 작성이 정확히 그랬다). 그래서 **그 자리의 미가용 블록**을 직접 잡는다.
  await expect(page.locator(".ms-card-sub .tstate-unavail-l", { hasText: "실현가능성" }))
    .toBeVisible();
  const body = (await page.locator(".ms-card-sub").textContent()) ?? "";
  expect(body, "검사하지 않았다는 사실").toContain("검사하지 않았어요");
  // 삭제 버튼은 아이콘 하나이므로 접근 가능한 이름이 있어야 한다.
  await expect(page.locator(".ms-vdel").first()).toHaveAttribute("aria-label", /삭제/);
});

// ── 5. 타입 하한(§56) + 대비 ──────────────────────────────────────────────────

test("§56 하한: 스튜디오 텍스트 노드 ≥11px", async ({ page }) => {
  for (const [slug] of STUDIOS) {
    await openStudio(page, slug);
    const sizes = await page.evaluate(() => {
      const root = document.querySelector(".ms-studio");
      if (!root) return [] as { cls: string; px: number }[];
      const out: { cls: string; px: number }[] = [];
      root.querySelectorAll("*").forEach((el) => {
        const t = (el.textContent ?? "").trim();
        if (!t) return;
        const px = parseFloat(getComputedStyle(el).fontSize);
        if (Number.isFinite(px)) out.push({ cls: el.className?.toString?.() ?? "", px });
      });
      return out;
    });
    // ★노드 수를 먼저 단언한다★ 빈 선택자는 조용히 통과한다(이 저장소가 세 번 물렸다).
    expect(sizes.length, `${slug}: 검사한 노드 수`).toBeGreaterThan(5);
    expect(sizes.filter((s) => s.px < 11), `${slug}: 11px 미만`).toEqual([]);
  }
});

test("대비: /macro 스튜디오 라이트/다크 — AA 미달 0 · 밝은 배경 누출 0", async ({ page }) => {
  await openStudio(page, "tsfm-latent");

  const light = await page.evaluate<AuditResult>(contrastAudit(".ms-root"));
  expect(light.checked, "라이트: 검사한 노드 수").toBeGreaterThan(10);
  expect(light.low, "라이트 AA 미달").toEqual([]);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(200);   // 전이 중간값이 잡히지 않게 (A9 에서 배운 것)
  const dark = await page.evaluate<AuditResult>(contrastAudit(".ms-root"));
  expect(dark.checked, "다크: 검사한 노드 수").toBeGreaterThan(10);
  expect(dark.low, "다크 AA 미달").toEqual([]);
  expect(dark.bright, "다크인데 밝은 배경이 남았다").toEqual([]);
});

// ═══════════════════════════════════════════════════════════════════════════════
// BU5c — 스튜디오 다섯을 토스식으로 (계획 "BU5c 상세")
// ─────────────────────────────────────────────────────────────────────────────
// ★먼저 써서 옛 화면(`d1c2184`)에서 빨간 것을 기록했다★ 지키는 것:
//   · h1 은 한국어 이름(스튜디오 줄·경로 머리와 같은 말) — 서버 label(LATENT…)이 아니다
//   · 고급 엔진의 원래 사유(예외 글)는 지우지 않고 "원래 사유 보기" 안에, 위에는 사람 말
//   · 답 줄은 서버 값을 틀에 끼운 것(응답을 바꾸면 따라 바뀐다)
//   · 그림은 더할 뿐 지우지 않는다(옛 스파크라인 수 이상)
//   · 실패(닿지 못함)는 alert + 다시 시도 — 서버가 답한 "미가용"과 가른다
// ═══════════════════════════════════════════════════════════════════════════════

const STUDIO_KO: Record<string, string> = {
  "tsfm-latent": "잠재 요인", "neural-sde": "기간 구조", "causal-deepm": "인과 관계",
  "pinn-tail": "꼬리 위험", "agentic-mcp": "뷰 만들기",
};
const API = "**/api/backend/api/v1/macro/studios";
/** 서버 응답을 받아 고쳐서 돌려준다(값은 서버 것 — 바꾼 칸만 다르다). */
async function patchRun(page: Page, slug: string, fn: (o: Record<string, unknown>) => void) {
  await page.route(`${API}/${slug}**`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    fn(body.outputs);
    await route.fulfill({ response: res, json: body });
  });
}
const fail500 = { status: 500, contentType: "application/json", body: '{"detail":"boom"}' };

/** 보이는 글 검사 — 서버 글(`[data-server]`)과 닫힌 details 안은 뺀다. */
const studioCopy = (loc: ReturnType<Page["locator"]>) => loc.evaluate((root) => {
  const texts: string[] = []; const mono: string[] = [];
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n: Node | null;
  while ((n = walk.nextNode())) {
    const el = n.parentElement!; const s = (n.textContent ?? "").trim();
    if (!s) continue;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || !el.getClientRects().length) continue;
    if (!el.closest("[data-server]")) texts.push(s);
    if (/mono/i.test(cs.fontFamily) && !el.closest("[data-mono]")) mono.push(s.slice(0, 24));
  }
  return {
    texts, mono,
    titles: Array.from(root.querySelectorAll("[title]")).filter((e) => e.getAttribute("title")?.trim()).length
      + Array.from(root.querySelectorAll("svg title")).filter((e) => e.textContent?.trim()).length,
  };
});
const BANNED_STUDIO = /\b(LATENT|TERM|CAUSAL|TAIL|VIEWS|ModuleNotFoundError|torch|forward-only|series|factors|loadings|k_factors|explained_var|term_premium_proxy|n_series)\b/;

for (const [slug] of STUDIOS) {
  test(`BU5c h1 = 한국어 이름 '${STUDIO_KO[slug]}' — 서버 label 영어가 아니다 (${slug})`, async ({ page }) => {
    await openStudio(page, slug);
    await expect(page.locator(".ms-studio h1")).toHaveText(STUDIO_KO[slug], { timeout: 20_000 });
  });

  test(`BU5c 글 — ${slug}: em-dash 0 · 영어 꼬리표 0 · 툴팁 0 · 고정폭은 식별자만`, async ({ page }) => {
    await openStudio(page, slug);
    if (slug === "agentic-mcp") { await page.locator(".ms-vbtn-run").click(); await expect(page.locator(".ms-outcome")).toBeVisible({ timeout: 20_000 }); }
    else await expect(page.locator(".ms-card-sub .ms-outcome, .ms-card-sub .tstate-unavail").first()).toBeVisible({ timeout: 20_000 });
    const r = await studioCopy(page.locator(".ms-studio"));
    expect(r.texts.length).toBeGreaterThan(5);
    expect(r.texts.filter((s) => s.includes("—")), "보이는 em-dash").toEqual([]);
    expect(r.texts.filter((s) => BANNED_STUDIO.test(s)), "영어·원시 키").toEqual([]);
    expect(r.titles, "title 툴팁").toBe(0);
    expect(r.mono, "고정폭(식별자 밖)").toEqual([]);
  });

  test(`BU5c 390 — ${slug} 가로 넘침 없음`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openStudio(page, slug);
    await page.waitForTimeout(1500);
    const over = await page.evaluate(() => {
      const m = document.querySelector(".terminal-main") as HTMLElement;
      return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, m.scrollWidth - m.clientWidth);
    });
    expect(over).toBeLessThanOrEqual(0);
  });
}

test("BU5c 고급 엔진: 위에는 사람 말, 원래 사유(예외 글)는 닫힌 '원래 사유 보기' 안에 그대로 남는다", async ({ page }) => {
  await openStudio(page, "tsfm-latent");
  const card = page.locator(".ms-card-frontier");
  await expect(card.locator(".ms-why")).toContainText("딥러닝 도구", { timeout: 20_000 });
  await expect(card.locator(".ms-why")).toContainText("더 긴 기간");
  // 원래 사유는 지우지 않는다(정직성) — 닫힌 details 의 글자로 남는다
  const raw = card.locator("details.ms-raw");
  await expect(raw).toHaveCount(1);
  expect(await raw.evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
  expect(await raw.textContent()).toContain("ModuleNotFoundError");
  // 짝: 보이는 글에는 예외 이름이 없다
  expect(await card.innerText()).not.toContain("ModuleNotFoundError");
});

test("BU5c 입력 계열: 칩 수 = 서버 inputs 수, 아는 키는 한국어 이름", async ({ page }) => {
  const listP = page.waitForResponse((r) => /\/macro\/studios(\?|$)/.test(r.url()));
  await page.goto("/macro/tsfm-latent", { waitUntil: "networkidle" });
  const list = await (await listP).json();
  const d = list.studios.find((s: { id: string }) => s.id === "tsfm-latent");
  const chips = page.locator(".ms-studio .ms-in-chip");
  await expect(chips).toHaveCount(d.inputs.length);
  await expect(chips.filter({ hasText: "경기선행" })).toHaveCount(1);
  await expect(chips.filter({ hasText: "KR_LEADING_CYCLE" })).toHaveCount(0);
});

test("BU5c 답 줄 = 서버 값(잠재 요인) — 응답을 바꾸면 문장이 따라간다(짝)", async ({ page }) => {
  await patchRun(page, "tsfm-latent", (o) => { o.k_factors = 2; o.explained_var = 0.2346; });
  await openStudio(page, "tsfm-latent");
  const ans = page.locator(".ms-studio .ms-answer");
  await expect(ans).toContainText("요인 2개", { timeout: 20_000 });
  await expect(ans).toContainText("23.5%");
});
test("BU5c 답 줄 짝 — 원래 값(잠재 요인)", async ({ page }) => {
  const runP = page.waitForResponse((r) => r.url().includes("/macro/studios/tsfm-latent"));
  await page.goto("/macro/tsfm-latent", { waitUntil: "networkidle" });
  const o = (await (await runP).json()).outputs;
  const ans = page.locator(".ms-studio .ms-answer");
  await expect(ans).toContainText(`요인 ${o.k_factors}개`, { timeout: 20_000 });
  await expect(ans).toContainText(`${(o.explained_var * 100).toFixed(1)}%`);
});
test("BU5c 답 줄 = 서버 값(기간 구조) — inverted 를 뒤집으면 '역전됐어요'(짝: 원래 '역전되지 않았어요')", async ({ page }) => {
  await openStudio(page, "neural-sde");
  await expect(page.locator(".ms-studio .ms-answer")).toContainText("역전되지 않았어요", { timeout: 20_000 });
  await patchRun(page, "neural-sde", (o) => { o.inverted = true; });
  await openStudio(page, "neural-sde");
  await expect(page.locator(".ms-studio .ms-answer")).toContainText("역전됐어요", { timeout: 20_000 });
});

test("BU5c 그림 — 잠재 요인: 요인 추이 선 + 적재 막대 수 = loadings 키 수", async ({ page }) => {
  const runP = page.waitForResponse((r) => r.url().includes("/macro/studios/tsfm-latent"));
  await page.goto("/macro/tsfm-latent", { waitUntil: "networkidle" });
  const o = (await (await runP).json()).outputs;
  await expect(page.locator(".ms-viz-factor .recharts-line-curve").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".ms-load-row")).toHaveCount(Object.keys(o.loadings).length);
});
test("BU5c 그림 — 기간 구조: 수준·기울기·곡률 세 선 + 기간프리미엄 대용 선, 옛 스파크라인도 남는다", async ({ page }) => {
  await openStudio(page, "neural-sde");
  await expect(page.locator(".ms-viz-curve .recharts-line-curve")).toHaveCount(3, { timeout: 20_000 });
  await expect(page.locator(".ms-viz-tp .recharts-line-curve")).toHaveCount(1);
  // 옛 화면의 스파크라인 4(level·slope·curvature·term_premium_proxy)는 표에 그대로
  expect(await page.locator(".ms-out .ms-spark").count()).toBeGreaterThanOrEqual(4);
});
test("BU5c 그림 — 인과: 간선을 넣은 응답이면 그래프 선 수 = 간선 수(짝: 빈 간선은 그래프 없이 '찾지 못했어요')", async ({ page }) => {
  await openStudio(page, "causal-deepm");
  await expect(page.locator(".ms-studio .ms-answer")).toContainText("찾지 못했어요", { timeout: 20_000 });
  expect(await page.locator(".ms-studio .mc-causal").count()).toBe(0);
  await patchRun(page, "causal-deepm", (o) => {
    o.nodes = [{ id: "KR_CPI", label: "KR_CPI" }, { id: "KR_10Y", label: "KR_10Y" }, { id: "KOSPI", label: "KOSPI" }];
    o.edges = [
      { from: "KR_CPI", to: "KR_10Y", from_label: "KR_CPI", to_label: "KR_10Y", lag: 3, p: 0.01 },
      { from: "KR_10Y", to: "KOSPI", from_label: "KR_10Y", to_label: "KOSPI", lag: 1, p: 0.03 },
    ];
  });
  await openStudio(page, "causal-deepm");
  await expect(page.locator(".ms-studio .mc-causal line")).toHaveCount(2, { timeout: 20_000 });
  await expect(page.locator(".ms-studio .ms-answer")).toContainText("관계 2개");
});

test("BU5c 실패 — 스튜디오 목록 500: alert + 다시 시도 → 풀면 회복(짝: 정상 alert 0)", async ({ page }) => {
  await openStudio(page, "neural-sde");
  await expect(page.locator(".ms-studio h1")).toHaveText("기간 구조", { timeout: 20_000 });
  expect(await page.locator(".ms-studio [role=alert]").count(), "정상인데 alert").toBe(0);
  await page.route(/\/api\/backend\/api\/v1\/macro\/studios(\?.*)?$/, (r) => r.fulfill(fail500));
  await page.goto("/macro/neural-sde");
  const alert = page.locator(".ms-studio [role=alert]").first();
  await expect(alert).toBeVisible({ timeout: 20_000 });
  await page.unroute(/\/api\/backend\/api\/v1\/macro\/studios(\?.*)?$/);
  await alert.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.locator(".ms-card-frontier")).toBeVisible({ timeout: 20_000 });
});
test("BU5c 실패 — 실행 500: 대체 카드 안 alert + 다시 시도 → 풀면 결과", async ({ page }) => {
  await page.route(`${API}/neural-sde**`, (r) => r.fulfill(fail500));
  await openStudio(page, "neural-sde");
  const alert = page.locator(".ms-card-sub [role=alert]");
  await expect(alert).toBeVisible({ timeout: 20_000 });
  await expect(alert.getByRole("button", { name: "다시 시도" })).toBeVisible();
  await page.unroute(`${API}/neural-sde**`);
  await alert.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.locator(".ms-card-sub .ms-outcome")).toBeVisible({ timeout: 20_000 });
});
test("BU5c 실패 — 뷰 컴파일 500: alert + 다시 시도 → 풀면 결과", async ({ page }) => {
  await page.route(`${API}/agentic-mcp`, (r) => (r.request().method() === "POST" ? r.fulfill(fail500) : r.continue()));
  await openStudio(page, "agentic-mcp");
  await page.locator(".ms-vbtn-run").click();
  const alert = page.locator(".ms-card-sub [role=alert]");
  await expect(alert).toBeVisible({ timeout: 20_000 });
  await page.unroute(`${API}/agentic-mcp`);
  await alert.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.locator(".ms-outcome")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".ms-card-sub [role=alert]")).toHaveCount(0);
});
test("BU5c 뷰 만들기: 컴파일된 제약을 사람 말 목록으로(서버 human 수와 같다)", async ({ page }) => {
  await openStudio(page, "agentic-mcp");
  const resP = page.waitForResponse((r) => r.url().endsWith("/macro/studios/agentic-mcp") && r.request().method() === "POST");
  await page.locator(".ms-vbtn-run").click();
  const o = (await (await resP).json()).outputs;
  await expect(page.locator(".ms-view-rule")).toHaveCount(o.human.length);
  await expect(page.locator(".ms-studio .ms-answer")).toContainText(`뷰 ${o.n_views}개`);
});
test("BU5c 적재 막대는 수준이라 중립 한 색 — +·− 막대가 같은 색이고 등락색(빨강/파랑 토큰)이 아니다", async ({ page }) => {
  await openStudio(page, "tsfm-latent");
  await expect(page.locator(".ms-load-row").first()).toBeVisible({ timeout: 20_000 });
  const c = await page.evaluate(() => {
    const probe = (v: string) => { const s = document.createElement("span"); s.style.color = `var(${v})`; document.body.appendChild(s);
      const r = getComputedStyle(s).color; s.remove(); return r; };
    const bg = (sel: string) => { const e = document.querySelector(sel); return e ? getComputedStyle(e).backgroundColor : null; };
    return { pos: bg(".ms-load-track i.pos"), neg: bg(".ms-load-track i.neg"), up: probe("--tx-up"), upInk: probe("--tx-up-ink") };
  });
  expect(c.pos, "양(+) 막대가 있다").not.toBeNull();
  expect(c.neg, "음(−) 막대가 있다").not.toBeNull();
  expect(c.pos).toBe(c.neg);
  expect([c.up, c.upInk]).not.toContain(c.pos);
});
test("BU5c 대비: 뷰 만들기 — 제약으로 바꾼 뒤 라이트/다크 AA 미달 0 · 다크 밝은 판 0", async ({ page }) => {
  await openStudio(page, "agentic-mcp");
  await page.locator(".ms-vbtn-run").click();
  await expect(page.locator(".ms-outcome")).toBeVisible({ timeout: 20_000 });
  const light = await page.evaluate<AuditResult>(contrastAudit(".ms-root"));
  expect(light.checked).toBeGreaterThan(10);
  expect(light.low, "라이트 AA 미달").toEqual([]);
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(contrastAudit(".ms-root"));
  expect(dark.low, "다크 AA 미달").toEqual([]);
  expect(dark.bright, "다크인데 밝은 배경").toEqual([]);
});
