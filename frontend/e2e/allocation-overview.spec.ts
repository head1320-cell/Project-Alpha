import { test, expect, type Page } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// 00 OVERVIEW — 연구 색인 + KPI + 분석 격자 (A4-V)
// ─────────────────────────────────────────────────────────────────────────────
// ★1번이 이 파일의 존재 이유다★ 나머지는 "새로 만든 것이 동작하는가"를 보지만,
// 1번은 **되돌아와도 아무도 눈치채지 못할 결함**을 지킨다. 초록색 `+0.0%` 는
// 화면에서 "포트폴리오가 무사하다"로 읽히고, 실제로는 "재지 못했다"였다.
// 눈으로도, 기존 테스트로도 잡히지 않았다.
// ═══════════════════════════════════════════════════════════════════════════════

async function enter(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/overview", { waitUntil: "networkidle" });
  await expect(page.locator(".aas-kpi")).toBeVisible({ timeout: 15_000 });
}

test("★미측정 충격을 초록 +0.0% 로 지어내지 않는다★", async ({ page }) => {
  // ★이 테스트가 지키는 것★
  // 예전 코드: `portfolio_shock_pct ?? 0` 을 **값에도 색에도** 썼다.
  //   값  → fmtSign(0) = "+0.0"      (fmtSign 은 null 을 "—" 로 처리할 줄 아는데,
  //                                   `?? 0` 이 그 정직함을 정확히 무력화했다)
  //   색  → 0 >= 0 이므로 var(--color-bull) = **초록**
  // 즉 "산출 실패"가 "무사함"으로 렌더됐다. 대시보드 첫 화면에서, 가장 안심시키는
  // 방향으로 틀린 값이다.
  await page.route("**/api/backend/**/stress**", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        scenario: "e2e", label: "E2E 시나리오", mode: "hypothetical",
        available: true, portfolio_shock_pct: null,
        reason: "커버리지 부족으로 충격을 산출하지 못했습니다",
        excluded: [],
      }),
    });
  });
  await enter(page);

  const rob = page.locator(".as-card", { hasText: "ROBUSTNESS" });
  await expect(rob).toBeVisible();
  const text = (await rob.innerText()).trim();

  // 숫자를 지어내지 않았다 — 0.0% 도, undefined% 도 없다.
  expect(text, "미산출을 0 으로 지어냈다").not.toContain("+0.0%");
  expect(text, "undefined 를 문자열로 렌더했다").not.toContain("undefined");
  // 대신 사유가 **보이는 글자**로 있어야 한다 (호버 아님).
  await expect(rob, "미산출 사유가 보이지 않는다").toContainText("산출 불가");
  await expect(rob).toContainText("커버리지 부족");
  // 그리고 강세색이 붙어서는 안 된다 — 그것이 이 결함의 핵심이었다.
  await expect(rob.locator(".aas-ov-rob-v.bull"), "미산출에 강세색이 붙었다").toHaveCount(0);
});

test("크로스링크에 접근 가능한 이름이 있다", async ({ page }) => {
  await enter(page);
  const links = page.locator(".aas-xlink");
  const n = await links.count();
  expect(n, "크로스링크 개수 (0 이면 조용히 통과한다)").toBeGreaterThan(3);
  for (const b of await links.all()) {
    // 보이는 글자는 `05 ↗` 뿐 — 이름이 없으면 스크린리더에서 "05 버튼"으로만 읽힌다.
    await expect(b).toHaveAttribute("aria-label", /스테이지로 이동/);
  }
});

test("Overview: 12px 산문 하한 · 11px 크롬 하한", async ({ page }) => {
  // 이 화면의 최악은 CSS 가 아니라 **인라인 style** 이었다(9px · 9.5px · 10.5px).
  // 인라인은 어떤 규칙으로도 못 덮으므로, 클래스로 내렸는지를 여기서 잰다.
  await enter(page);
  const res = await page.locator(".aas-root").evaluate((root) => {
    const out: string[] = [];
    let checked = 0;
    for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
      checked++;
      const px = parseFloat(cs.fontSize);
      if (px < 11) out.push(`${el.tagName}.${(el.getAttribute("class") || "").split(" ")[0]} ${px}px :: ${(el.textContent || "").trim().slice(0, 16)}`);
    }
    return { checked, out };
  });
  expect(res.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(20);
  expect(res.out, "11px 미만 텍스트").toEqual([]);
});

test("★as-wrow 회귀 가드 — 평범한 행에 Construct 그리드가 새지 않는다★", async ({ page }) => {
  // ★A3 가 남긴 회귀★ §51 이 `.as-wrow` 를 **스코프 없이** 4열 2행 named-area 로
  // 재정의했는데, 그 이름을 overview(:104)와 timing(:278)이 3열 구조로 쓰고 있었다.
  // 뒤에 온 규칙이 이겨서, 두 화면의 자식들은 grid-area 없이 암시적 행으로 밀려났다 —
  // 한 줄이어야 할 것이 세로로 쌓였다. 어떤 스펙도 그 두 화면의 행을 보지 않았다.
  //
  // ★처음 쓴 버전은 최적화 결과가 없으면 skip 됐다 — 즉 아무것도 지키지 않았다★
  // 그래서 데이터에 기대지 않고 **CSS 계약 자체**를 잰다: 평범한 `.as-wrow` 는
  // 기본 3열이어야 하고, Construct 전용 `.as-wrow-edit` 만 4열이어야 한다.
  await enter(page);
  const cols = await page.evaluate(() => {
    const probe = (cls: string) => {
      const el = document.createElement("div");
      el.className = cls;
      document.querySelector(".aas-root")!.appendChild(el);
      const v = getComputedStyle(el).gridTemplateColumns;
      el.remove();
      return v;
    };
    return { plain: probe("as-wrow"), edit: probe("as-wrow as-wrow-edit") };
  });

  // 기본 행은 3열(`minmax(0,1fr) 80px 48px`) — 열 개수로만 판정한다(px 는 폭에 따라 계산됨).
  expect(cols.plain.split(/\s+/).length,
    `평범한 .as-wrow 가 3열이 아니다: ${cols.plain}`).toBe(3);
  // Construct 행은 4열 — 두 값이 같아지면 이름 충돌이 되돌아온 것이다.
  expect(cols.edit.split(/\s+/).length,
    `.as-wrow-edit 가 4열이 아니다: ${cols.edit}`).toBe(4);
  expect(cols.plain, "두 행이 같은 그리드를 쓴다 — 이름 충돌 재발").not.toBe(cols.edit);
});
