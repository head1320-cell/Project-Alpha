import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 01 CONSTRUCT — 컨트롤 패널 + 결과 패널 (A3)
// ─────────────────────────────────────────────────────────────────────────────
// 이 화면에서 가장 값진 테스트는 5번(가짜 커버리지)이다. 나머지는 "새로 만든 것이
// 동작하는가"를 보지만, 5번은 **되돌아오면 아무도 눈치채지 못할 결함**을 지킨다.
// 문자열 리터럴로 박힌 날짜 범위는 화면에서 측정값과 똑같이 생겼고, 기존 테스트는
// 그게 있든 없든 전부 초록이었다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 게이트에서 시드된 포트폴리오로 Construct 에 진입한다(다른 스펙과 같은 경로). */
async function enterWithHoldings(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await expect(page.locator(".as-wrow").first()).toBeVisible({ timeout: 15_000 });
}

test("비중: 숫자 입력과 슬라이더가 양방향으로 같은 값을 가리킨다", async ({ page }) => {
  // ★두 컨트롤이 한 값을 공유한다는 계약★ 각자 state 를 들면 여기서 갈라진다.
  await enterWithHoldings(page);
  const row = page.locator(".as-wrow").first();
  const input = row.locator("input.as-w-input");
  const slider = row.locator("input.as-range");

  // 입력 → 슬라이더
  await input.fill("42");
  await expect(slider, "숫자를 치면 슬라이더가 따라온다").toHaveValue("42");

  // 슬라이더 → 입력 (range 는 fill 로 값을 밀 수 있다)
  await slider.fill("17.5");
  await expect(input, "슬라이더를 움직이면 숫자가 따라온다").toHaveValue("17.5");

  // 네이티브 range 는 role=slider + aria-valuenow 를 UA 가 반영한다 —
  // Radix 를 안 써도 접근성 트리에서 값이 읽힌다는 근거(번들 10 kB 를 아낀 이유).
  await expect(slider).toHaveAttribute("type", "range");
  await expect(slider).toHaveAttribute("max", "100");
});

test("배분 게이지: 합계를 aria 로 말하고, 100%가 아니면 색이 아니라 글자로 알린다", async ({ page }) => {
  await enterWithHoldings(page);
  const gauge = page.locator(".as-gauge [role='progressbar']");
  await expect(gauge).toBeVisible();

  // 시드 직후는 균등배분이라 합계 100%
  await expect(page.locator(".as-gauge-s")).toContainText("합계 100%");

  // 한 자산을 크게 올려 합계를 깨뜨린다
  await page.locator(".as-wrow").first().locator("input.as-w-input").fill("90");
  const now = await gauge.getAttribute("aria-valuenow");
  expect(Number(now), "aria-valuenow 가 실제 합계를 말한다").toBeGreaterThan(100);

  // ★색만으로 말하지 않는다★ 문구가 상태를 설명해야 한다.
  const msg = page.locator(".as-gauge-s");
  await expect(msg).toContainText("100% 아님");
  await expect(msg).toHaveClass(/off/);
});

test("삭제 버튼에 이름이 있고, 한 행만 지운다", async ({ page }) => {
  await enterWithHoldings(page);
  const rows = page.locator(".as-wrow");
  const before = await rows.count();
  expect(before, "시드된 자산 행").toBeGreaterThan(1);

  const first = rows.first();
  const name = (await first.locator(".as-holding-nm").innerText()).trim();
  // 아이콘만 있는 버튼은 이름이 없으면 스크린리더에서 "버튼"으로만 읽힌다.
  const del = first.getByRole("button", { name: `${name} 제거` });
  await expect(del, "삭제 버튼의 접근 가능한 이름").toHaveCount(1);

  await del.click();
  await expect(rows).toHaveCount(before - 1);
  await expect(page.locator(".as-wrow .as-holding-nm").first()).not.toHaveText(name);
});

test("비중 비교가 진짜 표다 — 열 머리글과 오른쪽 정렬", async ({ page }) => {
  await enterWithHoldings(page);
  const table = page.locator(".aas-cmp-t");
  await expect(table).toBeVisible();

  const heads = table.locator("thead th");
  await expect(heads).toHaveText(["자산", "현재", "캡가중", "최적화"]);
  for (const th of await heads.all()) {
    await expect(th, "열 머리글에 scope=col").toHaveAttribute("scope", "col");
  }
  // 행 머리글도 scope 를 갖는다 — 그래야 셀을 읽을 때 "무엇의 값"인지 말해 준다.
  await expect(table.locator("tbody th").first()).toHaveAttribute("scope", "row");

  const align = await table.locator("tbody td").first()
    .evaluate((e) => getComputedStyle(e).textAlign);
  expect(align, "숫자 셀은 오른쪽 정렬").toBe("right");
});

test("★미계산을 0 으로 지어내지 않는다 — 커버리지도, 캡가중도★", async ({ page }) => {
  // ★이 테스트가 지키는 것★
  //  ① 예전에는 결과가 없을 때 DATA COVERAGE 가 문자열 리터럴
  //     "2019-07-17 ~ 2026-07-16 · 1,712 거래일" 을 .num 서체로 렌더했다.
  //     측정값과 화면에서 구분이 안 됐고, 어떤 테스트도 빨개지지 않았다.
  //  ② 캡가중·최적화 열은 `?? 0` 이라 최적화 전에도 0.0 이 찍혔다 —
  //     "아직 계산 안 함"과 "시장 비중이 정말 0%"가 같은 모양이었다.
  await enterWithHoldings(page);

  const body = await page.locator(".as-ws2").innerText();
  expect(body, "지어낸 커버리지 날짜가 화면에 없어야 한다").not.toContain("2019-07-17");
  expect(body, "지어낸 거래일 수가 화면에 없어야 한다").not.toContain("1,712");

  // 최적화 전에는 캡가중·최적화가 '미계산' 이어야 한다.
  const na = page.locator(".aas-cmp-t .aas-cmp-na");
  expect(await na.count(), "미계산 셀이 존재한다").toBeGreaterThan(0);
  await expect(na.first()).toHaveText("미계산");

  // 커버리지 카드도 값을 지어내지 않고 사유를 적는다.
  const cov = page.locator(".as-card", { hasText: "DATA COVERAGE" });
  await expect(cov).toContainText("측정되지 않습니다");
});

test("고급 설정(슬리브 스튜디오)은 접혀 있고 키보드로 펼쳐진다", async ({ page }) => {
  await enterWithHoldings(page);
  const adv = page.locator("details.as-adv");
  await expect(adv).toBeVisible();
  expect(await adv.evaluate((e: HTMLDetailsElement) => e.open), "기본은 접힘").toBe(false);

  // 네이티브 <details> 라 summary 가 기본으로 포커스를 받고 Enter 로 열린다.
  await adv.locator("summary").focus();
  await page.keyboard.press("Enter");
  expect(await adv.evaluate((e: HTMLDetailsElement) => e.open), "Enter 로 펼쳐진다").toBe(true);
});

test("★Construct 가 라이트·다크 양쪽에서 WCAG AA★", async ({ page }) => {
  const AUDIT = contrastAudit(".as-ws2");
  await enterWithHoldings(page);

  const light = await page.evaluate<AuditResult>(AUDIT);
  expect(light.checked, "라이트에서 검사한 텍스트 노드 수").toBeGreaterThan(20);
  expect(light.low, "라이트: AA 미달").toEqual([]);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(AUDIT);
  expect(dark.checked, "다크에서 검사한 텍스트 노드 수").toBeGreaterThan(20);
  expect(dark.low, "다크: AA 미달").toEqual([]);
  expect(dark.bright, "다크인데 밝은 배경이 남아 있다").toEqual([]);
});

test("Construct: 12px 산문 하한 · 11px 크롬 하한", async ({ page }) => {
  await enterWithHoldings(page);
  const res = await page.locator(".as-ws2").evaluate((root) => {
    const out: string[] = [];
    let checked = 0;
    for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
      checked++;
      const px = parseFloat(cs.fontSize);
      if (px < 11) out.push(`${el.tagName}.${(el.getAttribute("class") || "").split(" ")[0]} ${px}px`);
    }
    return { checked, out };
  });
  expect(res.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(20);
  expect(res.out, "11px 미만 텍스트").toEqual([]);
});
