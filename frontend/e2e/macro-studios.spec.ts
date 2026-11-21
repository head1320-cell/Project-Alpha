import { test, expect, type Page } from "./fixtures";
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
  expect(body, "검사하지 않았다는 사실").toContain("검사하지 않았습니다");
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
test("BU5c 답 줄 = 서버 값(기간 구조) — inverted 를 뒤집으면 '역전됐습니다'(짝: 원래 '역전되지 않았습니다')", async ({ page }) => {
  await openStudio(page, "neural-sde");
  await expect(page.locator(".ms-studio .ms-answer")).toContainText("역전되지 않았습니다", { timeout: 20_000 });
  await patchRun(page, "neural-sde", (o) => { o.inverted = true; });
  await openStudio(page, "neural-sde");
  await expect(page.locator(".ms-studio .ms-answer")).toContainText("역전됐습니다", { timeout: 20_000 });
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
test("BU5c 그림 — 인과: 간선을 넣은 응답이면 그래프 선 수 = 간선 수(짝: 빈 간선은 그래프 없이 '찾지 못했습니다')", async ({ page }) => {
  await openStudio(page, "causal-deepm");
  await expect(page.locator(".ms-studio .ms-answer")).toContainText("찾지 못했습니다", { timeout: 20_000 });
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

test("BU5c 실패 — 스튜디오 목록 500: alert + 재시도 → 풀면 회복(짝: 정상 alert 0)", async ({ page }) => {
  await openStudio(page, "neural-sde");
  await expect(page.locator(".ms-studio h1")).toHaveText("기간 구조", { timeout: 20_000 });
  expect(await page.locator(".ms-studio [role=alert]").count(), "정상인데 alert").toBe(0);
  await page.route(/\/api\/backend\/api\/v1\/macro\/studios(\?.*)?$/, (r) => r.fulfill(fail500));
  await page.goto("/macro/neural-sde");
  const alert = page.locator(".ms-studio [role=alert]").first();
  await expect(alert).toBeVisible({ timeout: 20_000 });
  await page.unroute(/\/api\/backend\/api\/v1\/macro\/studios(\?.*)?$/);
  await alert.getByRole("button", { name: "재시도" }).click();
  await expect(page.locator(".ms-card-frontier")).toBeVisible({ timeout: 20_000 });
});
test("BU5c 실패 — 실행 500: 대체 카드 안 alert + 재시도 → 풀면 결과", async ({ page }) => {
  await page.route(`${API}/neural-sde**`, (r) => r.fulfill(fail500));
  await openStudio(page, "neural-sde");
  const alert = page.locator(".ms-card-sub [role=alert]");
  await expect(alert).toBeVisible({ timeout: 20_000 });
  await expect(alert.getByRole("button", { name: "재시도" })).toBeVisible();
  await page.unroute(`${API}/neural-sde**`);
  await alert.getByRole("button", { name: "재시도" }).click();
  await expect(page.locator(".ms-card-sub .ms-outcome")).toBeVisible({ timeout: 20_000 });
});
test("BU5c 실패 — 뷰 컴파일 500: alert + 재시도 → 풀면 결과", async ({ page }) => {
  await page.route(`${API}/agentic-mcp`, (r) => (r.request().method() === "POST" ? r.fulfill(fail500) : r.continue()));
  await openStudio(page, "agentic-mcp");
  await page.locator(".ms-vbtn-run").click();
  const alert = page.locator(".ms-card-sub [role=alert]");
  await expect(alert).toBeVisible({ timeout: 20_000 });
  await page.unroute(`${API}/agentic-mcp`);
  await alert.getByRole("button", { name: "재시도" }).click();
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

// ── 읽는 줄 — 스튜디오 선 그림 셋 (2026-11-10 · ADR 004 §6) ──
// 값은 호버 툴팁이 아니라 늘 보이는 줄(`.cr-read` · 처음 자리 = 마지막 관측 · ←→ Home End)과 표 쌍둥이(`.cr-table` — 전부)에 있다.
const sg3 = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3)}`;          // macroKo.signed(v, 3) 과 같은 서식
const fx = (v: number, d: number) => v.toFixed(d).replace(/^-/, "−");                 // 음수는 빼기표(−)
const crFrame = (page: Page, id: string) => page.locator(`.ms-studio .cr[data-chart="${id}"]`);

test("읽는 줄 — 잠재 요인: 툴팁 0 · 처음 자리 = 서버 마지막 관측 · ← 로 앞 관측 · 표 쌍둥이 = 전부", async ({ page }) => {
  const runP = page.waitForResponse((r) => r.url().includes("/macro/studios/tsfm-latent"));
  await page.goto("/macro/tsfm-latent", { waitUntil: "networkidle" });
  const o = (await (await runP).json()).outputs as { factors: (number | number[])[] };
  const n = o.factors.length;
  expect(n, "요인 관측이 없으면 이 검사는 공허하다").toBeGreaterThan(3);
  const f = crFrame(page, "studio-factor");
  await expect(f.locator(".recharts-line-curve").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".ms-studio .recharts-tooltip-wrapper")).toHaveCount(0);
  const at = (i: number) => [o.factors[i]].flat() as number[];
  await expect(f.locator(".cr-head")).toHaveText(`관측 ${n}번째`);
  await expect(f.locator(".cr-read")).toContainText(`요인 1 ${sg3(at(n - 1)[0])}`);
  await f.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(f.locator(".cr-head")).toHaveText(`관측 ${n - 1}번째`);
  await expect(f.locator(".cr-read")).toContainText(`요인 1 ${sg3(at(n - 2)[0])}`);
  await page.keyboard.press("Home");
  await expect(f.locator(".cr-head")).toHaveText("관측 1번째");
  await f.locator(".cr-table summary").click();
  await expect(f.locator(".cr-table tbody tr")).toHaveCount(n);
  await expect(page.locator(".ms-studio [title]")).toHaveCount(0);
});

test("읽는 줄 — 기간 구조(세 요인 · 기간프리미엄 대용): 툴팁 0 · 처음 자리 = 서버 마지막 관측 · 표 쌍둥이 = 전부", async ({ page }) => {
  const runP = page.waitForResponse((r) => r.url().includes("/macro/studios/neural-sde"));
  await page.goto("/macro/neural-sde", { waitUntil: "networkidle" });
  const o = (await (await runP).json()).outputs as { level: number[]; slope: number[]; curvature: number[]; term_premium_proxy: number[] };
  expect(o.level.length, "곡선 요인 관측이 없으면 이 검사는 공허하다").toBeGreaterThan(3);
  const c = crFrame(page, "studio-curve");
  await expect(c.locator(".recharts-line-curve")).toHaveCount(3, { timeout: 20_000 });
  await expect(page.locator(".ms-studio .recharts-tooltip-wrapper")).toHaveCount(0);
  const n = o.level.length;
  await expect(c.locator(".cr-head")).toHaveText(`관측 ${n}번째`);
  for (const [k, ko] of [["level", "수준"], ["slope", "기울기"], ["curvature", "곡률"]] as const) {
    await expect(c.locator(".cr-read")).toContainText(`${ko} ${fx(o[k][n - 1], 2)}`);
  }
  await c.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(c.locator(".cr-read")).toContainText(`수준 ${fx(o.level[n - 2], 2)}`);
  await c.locator(".cr-table summary").click();
  await expect(c.locator(".cr-table tbody tr")).toHaveCount(n);
  const tp = crFrame(page, "studio-tp");
  const m = o.term_premium_proxy.length;
  await expect(tp.locator(".cr-head")).toHaveText(`관측 ${m}번째`);
  await expect(tp.locator(".cr-read")).toContainText(`기간프리미엄 대용 ${fx(o.term_premium_proxy[m - 1], 1)}`);
  await tp.locator(".cr-table summary").click();
  await expect(tp.locator(".cr-table tbody tr")).toHaveCount(m);
});

// ═══════════════════════════════════════════════════════════════════════════════
// U2-b — 스튜디오의 합성 표시 (설계 문서 §2.2 C13 · 계획 docs/superpowers/plans/2026-11-21-uiux-u2-provenance.md)
// ─────────────────────────────────────────────────────────────────────────────
// mock 에서 수집기는 값이 없거나 받지 못한 지표를 합성 무작위 걸음으로 채우고, 스튜디오는 계열마다의 출처를 버린다 →
// 합성 계열에서 나온 수가 표시 없이 그려졌다. ★합성 표시는 서버 게이트(connection-status.mock_allowed)로만★
// (매크로의 정해진 규칙 · 받은 결정 ③ — 서버 0줄). ★먼저 써서 U2-a 빌드(`2e8c31b`)에서 빨간 것을 봤다★ 지키는 것(짝으로):
//   · 계열을 쓰는 스튜디오 넷: 게이트 참 → '합성 데이터'(경고색) / 거짓 → '출처 N/A(응답에 계열별 출처가 없습니다)'
//     (한국은행 키가 있어도 실데이터라 단정하지 않는다) / 게이트 실패 → '출처 N/A(합성 여부를 확인하지 못했습니다)'
//   · 뷰 만들기(입력 계열 없음): 표지 0 · 게이트를 묻지 않는다(짝: 서버가 입력 계열을 답하면 선다)
//   · 스튜디오 정보를 못 받으면 계산 응답의 기간(span)이 증거 — 있으면 게이트대로(짝: 계산이 미가용이면 표지 0)
//   · 요청: 계열 스튜디오에 connection-status 하나만 는다 · 뷰 만들기는 그대로
// ═══════════════════════════════════════════════════════════════════════════════

const DATA_STUDIOS = STUDIOS.filter(([s]) => s !== "agentic-mcp").map(([s]) => s);
const PROV = '.ms-studio .ms-head ul.tx-chips.tx-prov[aria-label="스튜디오 계산의 데이터 출처"]';
const GATE = "**/api/backend/api/v1/macro/connection-status";
const LIST = /\/api\/backend\/api\/v1\/macro\/studios(\?.*)?$/;
const GATE_OFF = { mock_allowed: false, real_mode: true, bok_configured: true, fred_configured: true };
const stubGate = (page: Page, body: Record<string, unknown> | null) =>
  page.route(GATE, (r) => (body ? r.fulfill({ json: body }) : r.fulfill(fail500)));

/** 중립 칩(모름)의 바탕이 그 뒤의 바탕과 갈리는지 — 같으면 칩의 테가 사라져 본문 한 줄처럼 읽힌다(스크린샷 검수에서 찾음). */
async function chipStandsOut(page: Page) {
  const r = await page.locator(`${PROV} .tx-chip`).first().evaluate((el) => {
    const bg = (e: Element) => getComputedStyle(e).backgroundColor;
    const clear = (c: string) => c === "transparent" || /rgba\(.*,\s*0\)$/.test(c);
    let n: Element | null = el.parentElement;
    while (n && clear(bg(n))) n = n.parentElement;
    return { chip: bg(el), behind: n ? bg(n) : "none", line: getComputedStyle(el).boxShadow };
  });
  expect(r.chip === r.behind && r.line === "none", `칩의 바탕 ${r.chip} · 뒤의 바탕 ${r.behind} · 테 ${r.line}`).toBe(false);
}

/** 합성 칩이 정말 보이는지 — 크기 · 투명도 · 보임 · 경고색(--tx-warn) · 가운데에 그려지는 것이 칩(잘리거나 덮이지 않음). */
async function syntheticShown(page: Page, what: string) {
  const chip = page.locator(`${PROV} .tx-chip[data-tone="practice"]`);
  await expect(chip, what).toHaveCount(1, { timeout: 20_000 });
  await expect(chip, what).toBeVisible();
  const m = await chip.evaluate((el) => {
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    let op = 1;
    for (let n: Element | null = el; n; n = n.parentElement) op *= Number(getComputedStyle(n).opacity);
    const probe = document.createElement("span");
    probe.style.color = "var(--tx-warn)";
    el.parentElement!.appendChild(probe);
    const warn = getComputedStyle(probe).color;
    probe.remove();
    return { w: r.width, h: r.height, op, color: getComputedStyle(el).color, warn, onTop: !!top && (top === el || el.contains(top)) };
  });
  expect(m.w, what).toBeGreaterThanOrEqual(40);
  expect(m.h, what).toBeGreaterThanOrEqual(14);
  expect(m.op, what).toBeGreaterThan(0.9);
  expect(m.color, `${what} — 경고색`).toBe(m.warn);
  expect(m.onTop, `${what} — 잘리거나 덮이지 않는다`).toBe(true);
}

test("U2-b 실제 mock 서버: 계열 스튜디오 넷 모두 머리에 '합성 데이터' 하나(경고색 · 근거의 종류 source)", async ({ page }) => {
  for (const slug of DATA_STUDIOS) {
    await openStudio(page, slug);
    const chips = page.locator(`${PROV} .tx-chip`);
    await expect(chips, slug).toHaveText(["합성 데이터"], { timeout: 20_000 });
    await expect(chips.first(), slug).toHaveAttribute("data-ev", "source");
    await syntheticShown(page, slug);
  }
});

test("U2-b 게이트 거짓: 합성 칩 0 · '출처 N/A(응답에 계열별 출처가 없습니다)' — 한국은행 키가 있어도 실데이터라 적지 않는다(짝: 참이면 합성)", async ({ page }) => {
  await stubGate(page, GATE_OFF);
  await openStudio(page, "tsfm-latent");
  const chips = page.locator(`${PROV} .tx-chip`);
  await expect(chips).toHaveText(["출처 N/A(응답에 계열별 출처가 없습니다)"], { timeout: 20_000 });
  await expect(chips.first()).toHaveAttribute("data-tone", "unknown");
  await expect(chips.first()).toBeVisible();
  await chipStandsOut(page);
  await expect(page.locator('.ms-studio .ms-head .tx-chip[data-tone="practice"]')).toHaveCount(0);
  expect(await page.locator(".ms-studio .ms-head").innerText()).not.toContain("실데이터");
  // 짝: 게이트만 참으로 바꾸면 같은 화면이 합성이라 적는다
  await page.unroute(GATE);
  await stubGate(page, { ...GATE_OFF, mock_allowed: true, real_mode: false });
  await openStudio(page, "tsfm-latent");
  await expect(chips).toHaveText(["합성 데이터"], { timeout: 20_000 });
});

test("U2-b 게이트 실패(500): '출처 N/A(합성 여부를 확인하지 못했습니다)' — 합성도 실데이터도 단정하지 않는다", async ({ page }) => {
  await stubGate(page, null);
  await openStudio(page, "neural-sde");
  const chips = page.locator(`${PROV} .tx-chip`);
  await expect(chips).toHaveText(["출처 N/A(합성 여부를 확인하지 못했습니다)"], { timeout: 20_000 });
  await expect(chips.first()).toHaveAttribute("data-tone", "unknown");
  await expect(chips.first()).toBeVisible();
  await chipStandsOut(page);
  await expect(page.locator('.ms-studio .ms-head .tx-chip[data-tone="practice"]')).toHaveCount(0);
  expect(await page.locator(".ms-studio .ms-head").innerText()).not.toContain("실데이터");
});

test("U2-b 뷰 만들기: 입력 계열이 없으면 표지 0 · 게이트를 묻지 않는다(짝: 서버가 입력 계열을 답하면 '합성 데이터')", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/macro/connection-status")) asked.push(r.url()); });
  await openStudio(page, "agentic-mcp");
  await expect(page.locator(".ms-studio h1")).toHaveText("뷰 만들기", { timeout: 20_000 });
  await page.waitForTimeout(500);
  await expect(page.locator(PROV)).toHaveCount(0);
  expect(asked, "입력 계열이 없으면 게이트를 묻지 않는다").toEqual([]);
  // 화면 안 이동: 계열 스튜디오에서 받은 게이트가 같은 열쇠의 캐시에 남아 있어도 뷰 만들기에는 표지가 없다
  await openStudio(page, "tsfm-latent");
  await expect(page.locator(`${PROV} .tx-chip`)).toHaveText(["합성 데이터"], { timeout: 20_000 });
  await page.locator('.ms-nav-item[href="/macro/agentic-mcp"]').click();
  await page.waitForURL(/\/macro\/agentic-mcp$/, { timeout: 20_000 });
  await expect(page.locator(".ms-studio h1")).toHaveText("뷰 만들기", { timeout: 20_000 });
  await page.waitForTimeout(500);
  await expect(page.locator(PROV), "캐시에 게이트가 있어도 입력 계열이 없으면 표지 0").toHaveCount(0);
  // 짝: 서버가 이 스튜디오의 입력 계열을 답하면 선다(규칙은 스튜디오 이름이 아니라 서버의 입력 계열을 본다)
  await page.route(LIST, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    for (const s of body.studios) if (s.id === "agentic-mcp") s.inputs = ["KR_LEADING_CYCLE"];
    await route.fulfill({ response: res, json: body });
  });
  await openStudio(page, "agentic-mcp");
  await expect(page.locator(`${PROV} .tx-chip`)).toHaveText(["합성 데이터"], { timeout: 20_000 });
});

test("U2-b 스튜디오 정보를 못 받으면 계산 응답의 기간이 증거 — 기간이 있으면 '합성 데이터'(짝: 계산이 미가용이면 표지 0)", async ({ page }) => {
  await page.route(LIST, (r) => r.fulfill(fail500));
  await openStudio(page, "tsfm-latent");
  await expect(page.locator('.ms-studio [role="alert"]').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(`${PROV} .tx-chip`)).toHaveText(["합성 데이터"], { timeout: 20_000 });
  // 짝: 계산도 미가용(기간 없음)이면 표지가 없다 — 화면에 수가 없고 실패 상자가 이미 그 사실을 말한다
  await page.route(`${API}/tsfm-latent**`, (r) => r.fulfill({ json: { available: false, engine: null, reason: "표본이 모자랍니다" } }));
  await openStudio(page, "tsfm-latent");
  await expect(page.locator(".ms-studio .ms-card-sub .tstate-unavail").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(500);
  await expect(page.locator(PROV)).toHaveCount(0);
});

test("U2-b 요청: 계열 스튜디오는 connection-status 하나만 는다 · 뷰 만들기는 그대로", async ({ page }) => {
  for (const slug of [...DATA_STUDIOS, "agentic-mcp"]) {
    const seen: string[] = [];
    const on = (r: { url(): string; method(): string }) => {
      const u = new URL(r.url());
      if (u.pathname.includes("/api/v1/")) seen.push(`${r.method()} ${u.pathname.replace(/^.*\/api\/v1/, "")}${u.search}`);
    };
    page.on("request", on);
    await openStudio(page, slug);
    await page.waitForTimeout(800);
    page.off("request", on);
    const want = slug === "agentic-mcp" ? ["GET /macro/studios"]
      : ["GET /macro/connection-status", "GET /macro/studios", `GET /macro/studios/${slug}?months=60&target=KOSPI`];
    expect([...seen].sort(), slug).toEqual([...want].sort());
  }
});

test("U2-b 대비: 표지가 있는 머리 — 라이트 · 다크 AA 미달 0 · 다크에 밝은 판 0 · 합성 칩은 두 테마에서 보인다", async ({ page }) => {
  await openStudio(page, "causal-deepm");
  await syntheticShown(page, "라이트");
  const light = await page.evaluate<AuditResult>(contrastAudit(".ms-studio .ms-head"));
  expect(light.checked, "라이트: 검사한 노드 수").toBeGreaterThan(3);
  expect(light.low, "라이트 AA 미달").toEqual([]);
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(200);
  await syntheticShown(page, "다크");
  const dark = await page.evaluate<AuditResult>(contrastAudit(".ms-studio .ms-head"));
  expect(dark.low, "다크 AA 미달").toEqual([]);
  expect(dark.bright, "다크인데 밝은 판").toEqual([]);
});
