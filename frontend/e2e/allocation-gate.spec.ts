import { test, expect } from "@playwright/test";
import { freezeCharts, contrastAudit, type AuditResult } from "./helpers";

// A12: Recharts 애니메이션만 끈다 — CSS 모션(§62/§63)은 그대로 둔다.
// `reducedMotion:'reduce'` 를 쓰면 CSS 까지 꺼져 모션 가드가 공허해진다.
test.beforeEach(async ({ page }) => { await freezeCharts(page); });


// ═══════════════════════════════════════════════════════════════════════════════
// 목표 게이트 (/allocation) — 온보딩 위저드 레이아웃 (A2)
// ─────────────────────────────────────────────────────────────────────────────
// ★이 파일에서 가장 중요한 테스트는 1번(카드 순서)이다★
// 이 화면은 네 개의 다른 스펙이 앱으로 들어오는 문이다:
//   aas.spec.ts:21               getByText("성장 추구")
//   allocation-backtest.spec.ts  .aas-goal.first() → 시드된 포트폴리오를 기대
//   research-run-roundtrip.ts    .aas-goal.first()
//   timing-factors.spec.ts       .aas-goal.first()
// 자산을 0개로 시드하는 카드(직접 구성)를 앞으로 옮기면 저 셋은 **빨개지지 않는다** —
// 빈 Construct 로 들어가서 조용히 다른 것을 검증한다. 그래서 순서를 여기서 못 박는다.
// ═══════════════════════════════════════════════════════════════════════════════

const GATE = "/allocation";

test("게이트: 프리셋 6 + 빈 프리셋 1, 그리고 첫 카드는 반드시 시드가 있는 프리셋", async ({ page }) => {
  await page.goto(GATE, { waitUntil: "networkidle" });
  await expect(page.locator(".aas-gate")).toBeVisible();

  const goals = page.locator(".aas-goal");
  expect(await goals.count(), "프리셋 6 + 직접 구성 1").toBe(7);
  // 그리드 안에는 6개만 — 빈 프리셋은 밖에 있다(브리프의 분리 요구이자, 위 계약의 보호막).
  expect(await page.locator(".aas-gate-grid .aas-goal").count(), "그리드 안 프리셋").toBe(6);

  await expect(goals.first(), "첫 카드 = 성장 추구 (시드 있음)").toContainText("성장 추구");
  await expect(goals.last(), "마지막 카드 = 빈 프리셋").toContainText("직접 구성");
  await expect(goals.first()).not.toHaveClass(/aas-goal-custom/);

  // 카드가 진짜 <button> 이어야 한다 — Card asChild(Slot)가 하는 일이 이것뿐이다.
  const tags = await goals.evaluateAll((els) => els.map((e) => e.tagName));
  expect(new Set(tags), "모든 프리셋 카드는 BUTTON").toEqual(new Set(["BUTTON"]));
});

test("게이트: 빈 프리셋만 파선 테두리로 구분된다", async ({ page }) => {
  await page.goto(GATE, { waitUntil: "networkidle" });
  const styles = await page.locator(".aas-goal").evaluateAll((els) => els.map((e) => {
    const cs = getComputedStyle(e);
    return {
      custom: e.classList.contains("aas-goal-custom"),
      style: cs.borderTopStyle,
      width: parseFloat(cs.borderTopWidth),
    };
  }));
  expect(styles.length, "카드 수").toBe(7);
  for (const s of styles) {
    if (s.custom) {
      expect(s.style, "빈 프리셋은 파선").toBe("dashed");
      expect(s.width, "빈 프리셋은 2px").toBeGreaterThanOrEqual(2);
    } else {
      expect(s.style, "사전 구성 프리셋은 실선").toBe("solid");
    }
  }
});

// ★A2b 의 3단계 스테퍼 테스트를 이 테스트가 대체한다 (A6-G)★
// 예전 테스트는 `.aas-gstep-item` 3개 · DOM 순서 · `aria-current` · sticky 를 단언했다.
// 스테퍼가 제거됐으므로 그 단언들은 의미가 없다. 다만 **삭제만 하면** 다음 사람이
// "게이트에 스테퍼가 있었나?" 를 알 방법이 없고, 되살아나도 아무도 모른다. 그래서
// 부재를 단언한다 — 그리고 같은 테스트에서 진입 계약(카드 7장·성장 추구 우선)이
// 제거로 인해 깨지지 않았음을 함께 확인한다. 제거의 유일한 리스크가 그것이기 때문이다.
test("게이트: 3단계 스테퍼는 제거됐고, 진입 계약은 그대로다", async ({ page }) => {
  await page.goto(GATE, { waitUntil: "networkidle" });
  await expect(page.locator(".aas-gate")).toBeVisible();

  expect(await page.locator(".aas-gstep, .aas-gstep-item, .aas-gstep-lab").count(),
    "게이트 스테퍼 잔재").toBe(0);
  // 페이즈 라벨 자체가 게이트에 남아 있지 않은지 — 클래스만 지우고 마크업을 남기는
  // 어중간한 제거를 잡는다. (PHASES 레지스트리는 살아 있고 StageChrome 이 계속 쓴다.)
  const gateText = await page.locator(".aas-gate").innerText();
  for (const w of ["SETUP", "LOGIC", "VALIDATION"]) {
    expect(gateText, `게이트 본문에 페이즈 라벨 ${w}`).not.toContain(w);
  }

  // 제거가 깨뜨릴 수 있는 유일한 것: 게이트가 여전히 앱의 문인가.
  const goals = page.locator(".aas-goal");
  expect(await goals.count(), "프리셋 6 + 직접 구성 1").toBe(7);
  await expect(goals.first(), "첫 카드 = 성장 추구").toContainText("성장 추구");
});

test("게이트: 12px 산문 하한 · 11px 크롬 하한", async ({ page }) => {
  await page.goto(GATE, { waitUntil: "networkidle" });

  // 산문(카드 설명)은 12px. 예전에는 11px 이었다.
  const desc = page.locator(".aas-goal-d");
  expect(await desc.count(), ".aas-goal-d 가 있어야 검사가 성립한다").toBe(7);
  for (const px of await desc.evaluateAll((els) => els.map((e) => parseFloat(getComputedStyle(e).fontSize)))) {
    expect(px, "카드 설명은 12px 이상").toBeGreaterThanOrEqual(12);
  }

  // 나머지 텍스트 노드 전부 11px 하한. 예전엔 시드 태그 9px, 푸터 라벨 10px, 칩 10.5px 였다.
  const small = await page.locator(".aas-gate").evaluate((root) => {
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
  expect(small.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(20);
  expect(small.out, "11px 미만 텍스트").toEqual([]);
});

test("★게이트: 라이트·다크 양쪽에서 WCAG AA★", async ({ page }) => {
  // 이 저장소에서 다크 결함은 항상 이 검사로만 잡혔다 — 육안으로는 "좀 흐리네"로 지나가고
  // 기존 테스트는 전부 초록이었다(§49 의 .aas-wiz-lab 1.04:1 이 그 예).
  const AUDIT = contrastAudit(".aas-gate");
  await page.goto(GATE, { waitUntil: "networkidle" });
  await expect(page.locator(".aas-goal").first()).toBeVisible();

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

test("게이트: 프리셋 카드를 키보드로 실행할 수 있다", async ({ page }) => {
  // ★호버 전용 어포던스를 막는 테스트★ 카드가 <div onClick> 이면 이 테스트가 빨개진다.
  await page.goto(GATE, { waitUntil: "networkidle" });
  const first = page.locator(".aas-goal").first();
  await first.focus();
  await expect(first, "탭 포커스가 카드 자체에 앉는다").toBeFocused();
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
});
