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

/** `[ N/A ]` 는 UnavailableState 의 접두사(shared/ui/States.tsx:66) — 미가용의 표지다. */
const NA_MARK = "[ N/A ]";

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
    const txt = (await card.textContent()) ?? "";
    // 이 환경의 실제 상태 — 프론티어는 전부 미가용이다.
    expect(txt, `${slug}: 프론티어 미가용 표지`).toContain(NA_MARK);
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
  const txt = (await sub.textContent()) ?? "";
  expect(txt, "대체 엔진 미가용 표지").toContain(NA_MARK);
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
