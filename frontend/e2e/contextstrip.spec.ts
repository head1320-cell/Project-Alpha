import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 리서치 컨텍스트 스트립 — 근거가 호버 뒤에 숨지 않는다 (UI/UX 현대화 P3)
// ─────────────────────────────────────────────────────────────────────────────
// ★이 스펙이 지키는 것★
// 스트립은 title= 을 16개 들고 있었다. 스펙 §8.1 은 카탈로그 창에 대해 "사유는 행에,
// 툴팁이 아니라" 를 못박아 두었는데 정작 무결성에 가장 민감한 컴포넌트가 반대였다.
// 호버는 **키보드 사용자와 터치 사용자에게 존재하지 않는다**.
//
// 그래서 여기서 단언하는 것은 "클래스가 있다" 가 아니라 **"사유가 읽힌다"** 이다:
//   · 비정상 상태는 호버 없이 사유 텍스트가 보인다(.as-ctx-warn-r)
//   · 정상 부연은 서랍 안에 있고, 서랍은 키보드로 열린다
//   · 스트립 칩에는 사유를 숨긴 title= 이 남아 있지 않다
//
// ★경고 상태는 만들어서 검사한다 — 조건부 단언은 아무것도 지키지 못한다★
// 콜드 스타트에는 경고할 것이 없다(룰셋 미저장·팩 미선택·런 없음). 처음에는 "경고가 있으면
// 확인한다" 라고 썼는데, 그 테스트는 루프가 0회 돌아 **언제나 통과**했다 — 경고 UI 를
// 통째로 지워도 초록이었다. 그래서 sessionStorage 에 버전 없는 룰셋을 심어 실제 경고
// 경로를 태운다. 백엔드에 의존하지 않고, 프로덕션 코드가 읽는 그 키를 그대로 쓴다.
// ═══════════════════════════════════════════════════════════════════════════════

const AAS = "/allocation/optimize";

/** TimingContext 의 SS_RULESET 키 — 버전이 null 이면 "룰셋 버전 미기록" 경고가 뜬다. */
const SS_RULESET = "alpha_alloc_ruleset";
const seedVersionlessRuleSet = (id = "tr_e2e_ctxstrip") =>
  `sessionStorage.setItem(${JSON.stringify(SS_RULESET)}, JSON.stringify({ id: ${JSON.stringify(id)}, version: null }));`;

test("컨텍스트 스트립: 사유를 숨긴 title= 이 칩에 남아 있지 않다", async ({ page }) => {
  const sink = trackErrors(page);
  await page.goto(AAS, { waitUntil: "networkidle" });

  const strip = page.locator(".as-ctx");
  await expect(strip).toBeVisible();

  // 카나리(.as-ctx-canary)만 title 을 갖는다 — 지표명·z 점수는 **보조** 수치이고
  // 값 자체는 이미 화면에 있다. 그 밖의 칩이 title 을 되찾으면 여기서 걸린다.
  const titled = strip.locator("[title]");
  for (const el of await titled.all()) {
    const cls = (await el.getAttribute("class")) ?? "";
    expect(cls, `title= 을 가진 칩: ${cls}`).toContain("as-ctx-canary");
  }

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

test("컨텍스트 스트립: 비정상 상태는 사유까지 호버 없이 보인다", async ({ page }) => {
  // 버전 없는 룰셋을 심는다 — 프로덕션이 읽는 그 키다. 이게 없으면 경고가 0건이라
  // 아래 단언이 전부 공회전한다(그 상태로는 경고 UI 를 지워도 초록이었다).
  await page.addInitScript(seedVersionlessRuleSet());
  await page.goto(AAS, { waitUntil: "networkidle" });

  const warns = page.locator(".as-ctx-warn");
  await expect(warns, "심은 상태에서 경고가 반드시 렌더돼야 한다").not.toHaveCount(0);

  const n = await warns.count();
  for (let i = 0; i < n; i++) {
    const w = warns.nth(i);
    await expect(w.locator(".as-ctx-warn-l"), "경고 라벨").toBeVisible();
    const reason = w.locator(".as-ctx-warn-r");
    await expect(reason, "★사유는 호버 없이 보여야 한다★").toBeVisible();
    expect((await reason.innerText()).trim().length,
      "사유 없는 경고는 존재할 수 없다").toBeGreaterThan(0);
  }

  // 심은 조건에 해당하는 경고가 정확히 그것인지 — 아무 경고나 뜬 것으로 만족하지 않는다.
  const nover = page.locator(".as-ctx-warn-rules-nover");
  await expect(nover).toBeVisible();
  await expect(nover.locator(".as-ctx-warn-r"))
    .toContainText("어떤 룰로 계산됐는지 단정할 수 없습니다");

  // 경고는 스크린리더에도 전달된다 — 시각에만 두지 않는다.
  await expect(page.locator('.as-ctx-warns[role="status"]')).toBeVisible();
});

test("컨텍스트 스트립: 재현 좌표 서랍이 키보드로 열리고 Escape 로 닫힌다", async ({ page }) => {
  await page.goto(AAS, { waitUntil: "networkidle" });

  const trigger = page.locator(".as-ctx .tev-drawer-t");
  await expect(trigger).toBeVisible();

  // 키보드만으로 도달·조작 가능해야 한다 — 이 서랍이 호버 툴팁을 대체하는 물건이므로,
  // 마우스로만 열린다면 아무것도 고치지 못한 것이다.
  await trigger.focus();
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");

  // Radix 는 document.body 로 포털한다 — .as-ctx 로 범위를 좁히면 못 찾는다.
  const drawer = page.locator(".tev-drawer");
  await expect(drawer).toBeVisible();
  await expect(page.locator(".tev-drawer-h")).toContainText("재현 좌표");
  expect(await page.locator(".tev-drawer-r").count(), "부연 행").toBeGreaterThan(0);

  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(trigger, "닫으면 포커스가 트리거로 돌아온다").toBeFocused();
});

test("컨텍스트 스트립: 스펙 §4 의 신원 요소가 사라지지 않았다", async ({ page }) => {
  await page.goto(AAS, { waitUntil: "networkidle" });
  const strip = page.locator(".as-ctx");

  // 근거를 서랍으로 옮기면서 **칩 자체를 지우지 않았는지** 확인한다.
  // PINNED/LIVE 와 유니버스는 어떤 상태에서도 렌더된다.
  await expect(strip.locator(".as-ctx-regime")).toBeVisible();
  await expect(strip.locator(".as-ctx-src")).toHaveText(/PINNED|LIVE/);
  await expect(strip.locator(".as-ctx-univ")).toBeVisible();
  await expect(strip.locator(".as-ctx-rules")).toBeVisible();
  await expect(strip.locator(".as-ctx-canary").first()).toBeVisible();
});
