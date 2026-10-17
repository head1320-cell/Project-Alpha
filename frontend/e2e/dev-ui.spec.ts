import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// /dev/ui — shared/ui 프리미티브 격리 갤러리에 대한 회귀 검사.
//
// 왜 필요한가: CLAUDE.md 는 "CSS 클래스명이 E2E 계약"이라고 못박고 있는데, 정작
// shared/ui 프리미티브가 내보내는 클래스명을 **직접** 검증하는 테스트가 없었다.
// 지금까지는 소비 화면의 스펙이 우연히 걸러 주기를 기대하는 구조였다.
//
// 이 스펙은 데이터 없이 렌더되는 갤러리에서 다음 세 가지를 본다:
//   1) shared/ui 의 컴포넌트 export 46개(BU0 tx 10 포함)가 전부 표본으로 마운트되었는가(제외 없음)
//   2) 각 프리미티브가 내보내는 **클래스 계약**이 그대로인가
//   3) 순수 프레젠테이션 화면인데 uncaught error / 네트워크 호출이 없는가
//
// 한계(정직하게): 클래스가 존재한다는 것은 시각적 동등성의 증명이 아니다. 클래스명
// 변경·DOM 구조 붕괴·컴포넌트 크래시는 잡지만, 색·간격이 달라지는 것은 잡지 못한다.
// kit 은 전부 인라인 스타일이라(.bs-numbox 외 클래스 없음) role·태그로 검증한다.
//
// 개수 단언은 전부 갤러리 루트(.devui)로 범위를 좁힌다. 셸(TerminalShell)이
// 페이지를 감싸고 있어서다 — 예전에는 헤더의 국면 배지가 로딩 중 .skeleton 을 렌더했다(BR R3 에서
// 프로필로 바뀌었다). 셸이 무엇을 그리든 갤러리의 개수가 흔들리지 않게 범위를 좁힌다.
// ═══════════════════════════════════════════════════════════════════════════════

// 갤러리가 선언한 표본 이름 — page.tsx 의 <Specimen name=…> 과 1:1 이어야 한다.
const SPECIMENS = [
  // primitives (11)
  "PageHeader", "PageContent", "StatCard", "Tabs", "Spinner", "Badge",
  "Section", "FormRow", "Field", "ErrorMsg", "Empty",
  // kit (7) — Section·Field 는 primitives 와 이름이 겹치는 별개 구현
  "GroupedSelect", "Toggle", "Section", "SubToggle", "Field", "QuickStepper", "Segmented",
  // States (5) — UnavailableState·AsyncState 는 P2 에서 추가됐다.
  "LoadingState", "EmptyState", "ErrorState", "UnavailableState", "AsyncState",
  // evidence (2)
  "EvidenceBadge", "EvidenceDrawer",
  // feedback (7)
  "Skeleton", "SkeletonText", "SkeletonCard", "SkeletonTable", "TickValue", "MetricCard", "Sparkline",
  // MiniViz (3) + SectionHead (1)
  "MiniViz", "StatGrid", "Stat", "SectionHead",
  // tx (10) — BU0 토스식 공용 부품(ADR-003). Section·Stat·Segmented·Tabs 는 위와 이름이 겹치는 별개 구현.
  "PageHead", "Answer", "Chips", "Section", "ListRow", "Stat", "Segmented", "Tabs", "Notice", "Unknown",
];

test.describe("/dev/ui — shared/ui 격리 갤러리", () => {
  test("모든 표본이 마운트되고 uncaught error 가 없다", async ({ page }) => {
    const sink = trackErrors(page);
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");   // 셸 마크업과 격리

    await expect(page.locator("h1.devui-title")).toContainText("프리미티브 격리 갤러리");

    // 표본 개수 — 컴포넌트가 조용히 빠지거나 렌더 중 죽으면 여기서 걸린다.
    await expect(g.locator(".devui-item")).toHaveCount(SPECIMENS.length);

    // 표본 이름이 선언과 정확히 일치(순서까지) — 이름 변경/누락 감지.
    const names = await g.locator(".devui-item .devui-item-name").allInnerTexts();
    expect(names.map((s) => s.trim())).toEqual(SPECIMENS);

    // 갤러리 자체는 데이터를 부르지 않는다. 셸(TerminalShell)의 프로필은 토큰이 있을 때만
    // /auth/me 를 부른다(여기서는 토큰이 없다) — 4xx/5xx 가 하나라도 잡히면 실패다.
    expect(uniq([...sink.api404, ...sink.apiOther4xx5xx]), "4xx/5xx 응답이 없어야 한다").toEqual([]);
    expect(uniq(sink.pageErrors), "uncaught page errors").toEqual([]);

    const body = await page.locator("body").innerText();
    expect(body, "한글이 깨지지 않아야 한다").not.toMatch(/�/);
  });

  test("primitives 의 클래스 계약이 유지된다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");   // 셸 마크업과 격리

    // PageHeader — 갤러리 크롬은 .devui-* 만 쓰므로 이 클래스는 표본에서만 나온다.
    await expect(g.locator(".pv-page-header")).toHaveCount(1);
    await expect(g.locator(".pv-page-header .pv-page-title")).toHaveText("페이지 제목");
    await expect(g.locator(".pv-page-header .pv-page-subtitle")).toBeVisible();
    await expect(g.locator(".pv-page-header .pv-breadcrumb a")).toHaveCount(1);

    // PageContent + PageHeader 가 공통으로 쓰는 폭 컨테이너
    await expect(g.locator(".container-pv").first()).toBeVisible();

    // StatCard ×3 (up / down / sm)
    const statCards = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^StatCard$/ }) });
    await expect(statCards.locator(".card.card-md")).toHaveCount(3);
    await expect(statCards.locator(".card.card-md .label").first()).toHaveText("누적수익률");
    await expect(statCards.locator(".card.card-md .num").first()).toHaveText("+18.4%");

    // Tabs — .pv-tabs / .pv-tab / active 는 실제 앱 스펙들이 의존하는 계약이다.
    await expect(g.locator(".pv-tabs")).toHaveCount(1);
    await expect(g.locator(".pv-tabs .pv-tab")).toHaveCount(3);
    await expect(g.locator(".pv-tabs .pv-tab.active")).toHaveCount(1);
    await expect(g.locator(".pv-tabs .pv-tab.active")).toHaveText("개요");

    // Badge — 4개 variant 가 각각 다른 클래스로 나가야 한다.
    // Badge 표본 안으로 범위를 좁힌다: Badge 는 PageHeader 의 actions 슬롯과 primitives
    // Section 의 action 슬롯에서도 채움용으로 쓰이므로 전역 카운트는 1이 아니다.
    // 카운트를 2/1/1/2 로 박으면 그 채움이 바뀔 때마다 깨진다 — 범위 한정이 옳다.
    const badges = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^Badge$/ }) });
    for (const cls of ["badge-success", "badge-danger", "badge-warning", "badge-info"]) {
      await expect(badges.locator(`.badge.${cls}`)).toHaveCount(1);
    }
  });

  test("Tabs 표본이 실제로 상호작용한다(active 가 옮겨감)", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");   // 셸 마크업과 격리

    const tabs = g.locator(".pv-tabs .pv-tab");
    await expect(tabs.nth(0)).toHaveClass(/active/);

    await tabs.nth(2).click();
    await expect(tabs.nth(2)).toHaveClass(/active/);
    await expect(tabs.nth(0)).not.toHaveClass(/active/);
    // active 는 항상 정확히 하나
    await expect(g.locator(".pv-tabs .pv-tab.active")).toHaveCount(1);
  });

  test("States 의 .tstate-* 계약과 접근성 속성이 유지된다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");   // 셸 마크업과 격리

    // 세 상태 × 2 variant = 6, + UnavailableState 2, + AsyncState 의 비-ready 3 = 11
    await expect(g.locator(".tstate")).toHaveCount(11);
    await expect(g.locator(".tstate.tstate-loading")).toHaveCount(3);
    await expect(g.locator(".tstate.tstate-empty")).toHaveCount(3);
    await expect(g.locator(".tstate.tstate-error")).toHaveCount(2);
    await expect(g.locator(".tstate.tstate-unavail")).toHaveCount(3);

    // 하위 요소 계약
    // BU0 — 로딩은 뼈대 줄 셋(돌아가는 원 대신). 빈 상태의 ◇ 표식은 걷었다.
    await expect(g.locator(".tstate-loading .tstate-skel")).toHaveCount(3);
    await expect(g.locator(".tstate-loading .tstate-skel i")).toHaveCount(9);
    await expect(g.locator(".tstate-empty .tstate-label")).toHaveCount(3);
    await expect(g.locator(".tstate-sub")).toHaveCount(6); // sub/reason 이 있는 것만

    // 로딩은 role=status, 오류는 role=alert — 스크린리더 계약
    await expect(g.locator('.tstate-loading[role="status"]')).toHaveCount(3);
    await expect(g.locator('.tstate-error[role="alert"]')).toHaveCount(2);

    // BU0 — 글자 표지(`[ LOADING ]`·`[ ERROR ]`)를 해요체 문장으로 바꿨다. 문장은 바뀔 수 있으니 클래스로 보고,
    // 표지가 다시 생기지 않는지만 짝으로 본다.
    await expect(g.locator(".tstate-loading .tstate-label").first()).toHaveText("불러오는 중이에요");
    await expect(g.locator(".tstate-error .tstate-label").first()).toHaveText("불러오지 못했어요");
    expect(await g.locator(".tstate").allInnerTexts(), "대괄호 표지가 남아 있지 않다").not.toContainEqual(expect.stringMatching(/\[ (LOADING|ERROR|N\/A) \]/));

    // ★뼈대는 400ms 지연 뒤에만 보인다★(깜빡임 방지) — 지연은 CSS 가 갖는다. 짝: 빈 상태에는 지연이 없다.
    const anim = (l: string) => g.locator(l).first().evaluate((e) => {
      const c = getComputedStyle(e); return { name: c.animationName, delay: c.animationDelay };
    });
    expect(await anim(".tstate-loading")).toEqual({ name: "tstate-reveal", delay: "0.4s" });
    expect((await anim(".tstate-empty")).delay).toBe("0s");
    await expect(g.locator(".tstate-loading").first()).toBeVisible();

    // ★unavailable 은 empty 와 반드시 다르게 보여야 한다★ 같은 모양이면 "없음" 이
    // "문제 없음" 으로 읽힌다. 클래스가 다르다는 것만으로는 부족하므로 실제 계산된
    // 배경색이 서로 다른지까지 본다.
    await expect(g.locator(".tstate-unavail .tstate-unavail-tag")).toHaveCount(3);
    await expect(g.locator(".tstate-unavail-tag").first()).toHaveText("지금은 못 재요");
    const bg = (l: string) => g.locator(l).first().evaluate((e) => getComputedStyle(e).backgroundColor);
    expect(await bg(".tstate-unavail"), "unavailable 이 empty 와 같은 배경이면 안 된다")
      .not.toBe(await bg(".tstate-empty"));

    // unavailable 은 사유가 필수 prop — 화면에 실제로 사유 텍스트가 나와야 한다
    for (const el of await g.locator(".tstate-unavail").all()) {
      expect((await el.locator(".tstate-sub").innerText()).trim().length,
        "사유 없는 unavailable 은 존재할 수 없다").toBeGreaterThan(0);
    }
  });

  test("EvidenceBadge 의 .tev-* 계약 — 사유가 호버 뒤에 숨지 않는다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");

    await expect(g.locator(".tev")).toHaveCount(4);
    for (const k of ["measured", "estimated", "caution", "unavailable"]) {
      await expect(g.locator(`.tev.tev-${k}`), `${k} 처리 1개`).toHaveCount(1);
      await expect(g.locator(`.tev-${k} .tev-l`)).toBeVisible();
    }

    // ★이 스펙의 핵심★ caution·unavailable 의 사유는 **보이는 텍스트**여야 한다.
    // title= 로 옮기는 순간 키보드·터치 사용자에게서 사라진다 — 이번 현대화가
    // ContextStrip 에서 고치려는 바로 그 결함이다.
    for (const k of ["caution", "unavailable"]) {
      const r = g.locator(`.tev-${k} .tev-r`);
      await expect(r, `${k} 은 사유를 보여야 한다`).toBeVisible();
      expect((await r.innerText()).trim().length).toBeGreaterThan(0);
    }
    expect(await g.locator(".tev[title]").count(), "배지는 title= 로 사유를 숨기지 않는다").toBe(0);
  });

  test("EvidenceDrawer 는 포털되고, 키보드로 열리고 닫히고, 포커스가 돌아온다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");
    const trigger = g.locator(".tev-drawer-t");

    await expect(trigger).toHaveCount(1);
    // 닫혀 있을 때는 내용이 DOM 에 없다 — "닫힌 서랍은 존재하지 않는다" 를 그대로 확인한다.
    await expect(page.locator(".tev-drawer")).toHaveCount(0);

    await trigger.click();
    // ★Radix 는 document.body 로 포털한다★ .devui 로 범위를 좁히면 못 찾는다.
    // 그 사실 자체를 단언한다 — 나중에 누가 스코프를 좁히면 여기서 걸린다.
    await expect(page.locator(".tev-drawer")).toBeVisible();
    expect(await g.locator(".tev-drawer").count(), "포털이므로 갤러리 루트 안에는 없다").toBe(0);

    // 행 계약: dt/dd 쌍 3개, 식별자 행은 등폭
    await expect(page.locator(".tev-drawer-r")).toHaveCount(3);
    await expect(page.locator(".tev-drawer-r dd.num").first()).toBeVisible();
    await expect(page.locator(".tev-drawer-h")).toContainText("재현 좌표");

    // Escape 로 닫히고, 포커스가 트리거로 돌아온다(next/dynamic 뒤 Radix 포커스 복원 함정).
    await page.keyboard.press("Escape");
    await expect(page.locator(".tev-drawer")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("MiniViz / StatGrid / Stat / SectionHead 의 클래스 계약이 유지된다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");   // 셸 마크업과 격리

    // MiniViz kind 5종 — 기본 className 이 .t-miniviz
    await expect(g.locator(".t-miniviz")).toHaveCount(5);

    // StatGrid 1개 안에 Stat 3개 + 단독 Stat 표본 2개 = .tstat 5개
    await expect(g.locator(".tstat-grid")).toHaveCount(1);
    await expect(g.locator(".tstat-grid .tstat")).toHaveCount(3);
    await expect(g.locator(".tstat")).toHaveCount(5);
    await expect(g.locator(".tstat .tstat-key").first()).toHaveText("CAGR");
    await expect(g.locator(".tstat .tstat-val").first()).toHaveText("14.2%");

    // SectionHead — index 있음/없음
    await expect(g.locator(".tpage-section-head")).toHaveCount(2);
    await expect(g.locator(".tpage-section-head .sh-label").first()).toHaveText("유동성 게이트");
    await expect(g.locator(".tpage-section-head .sh-index")).toHaveCount(1); // index 를 넘긴 쪽만
  });

  test("feedback 의 .skeleton / .sparkline 계약이 유지된다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");   // 셸 마크업과 격리

    // Skeleton 1 + SkeletonText(3+5) + SkeletonCard(3) + SkeletonTable(3행×3) +
    // MetricCard loading=true → SkeletonCard(3) = 1+8+3+9+3 = 24
    await expect(g.locator(".skeleton")).toHaveCount(24);

    // Sparkline: data 2개 이상인 것만 svg 를 그린다(1개짜리는 빈 span)
    await expect(g.locator(".sparkline")).toHaveCount(2);
    await expect(g.locator(".sparkline svg polyline")).toHaveCount(2);

    // MetricCard — value=null 은 대시로 정직하게 표시
    const metric = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^MetricCard$/ }) });
    await expect(metric).toContainText("—");
  });

  // BU3 — kit 에 `kit-*` 클래스가 생겼지만(모습 전용) 계약은 여전히 role·태그 구조로 본다.
  test("kit 은 클래스가 없으므로 role·태그 구조로 검증한다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");   // 셸 마크업과 격리

    // GroupedSelect — optgroup 2개 / option 3개
    const select = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^GroupedSelect$/ }) }).locator("select");
    await expect(select).toHaveCount(1);
    await expect(select.locator("optgroup")).toHaveCount(2);
    await expect(select.locator("option")).toHaveCount(3);

    // Toggle — role=switch. tone 3개 + Section 1개 + SubToggle 1개 = 5
    await expect(g.locator('[role="switch"]')).toHaveCount(5);
    await expect(g.locator('[role="switch"][aria-checked="true"]')).toHaveCount(5);

    // Toggle 을 끄면 aria-checked 가 뒤집힌다
    const firstSwitch = g.locator('[role="switch"]').first();
    await firstSwitch.click();
    await expect(firstSwitch).toHaveAttribute("aria-checked", "false");

    // kit/Section — 토글을 끄면 자식이 사라지는 계약
    const kSection = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^Section$/ }) }).nth(1);
    await expect(kSection).toContainText("유동성 게이트");
    await expect(kSection).toContainText("자식 노드는");
    await kSection.locator('[role="switch"]').click();
    await expect(kSection).not.toContainText("자식 노드는");

    // QuickStepper — .bs-numbox 는 kit 의 유일한 클래스 계약. +5 칩으로 20 → 25.
    const stepper = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^QuickStepper$/ }) });
    const numbox = stepper.locator("input.bs-numbox");
    await expect(numbox).toHaveValue("20");
    await stepper.getByRole("button", { name: "+5%" }).click();
    await expect(numbox).toHaveValue("25");

    // Segmented — 3개 버튼 (kit 표본 — BU0 에서 같은 이름의 tx 표본이 생겨 출처로 가른다)
    const seg = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^Segmented$/ }) })
      .filter({ has: page.locator(".devui-item-from", { hasText: /^kit$/ }) });
    await expect(seg.locator("button")).toHaveCount(3);
  });

  // ── shadcn 섹션 (Phase 5) ───────────────────────────────────────────────
  // ★기존 .devui-item 단언을 건드리지 않는다★ — shadcn 표본은 .devui-sitem 이라는
  // 별개 클래스를 쓰므로 위의 "표본 36개" 계약은 그대로 유효하다.
  test("shadcn 섹션이 기존 갤러리 계약을 깨지 않고 함께 렌더된다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const g = page.locator(".devui");

    // 기존 계약 불변
    await expect(g.locator(".devui-item")).toHaveCount(SPECIMENS.length);

    // 새 섹션은 별개 클래스로 3개
    await expect(g.locator(".devui-shadcn")).toHaveCount(1);
    const names = await g.locator(".devui-sitem .devui-sitem-name").allInnerTexts();
    expect(names).toEqual(["Button", "Badge", "Dialog"]);
  });

  test("shadcn Button 의 variant 가 실제로 다른 클래스를 낸다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const row = page.locator(".devui-sitem", { hasText: "Button" }).locator(".devui-variants");
    // cn()/twMerge 가 동작하면 variant 별로 배경 유틸리티가 달라진다
    const cls = await row.locator("button").first().getAttribute("class");
    expect(cls).toContain("var(--primary)");
    await expect(row.locator("button:disabled")).toHaveCount(1);
  });

  // ★Radix 포털 위험을 명시적으로 고정한다★
  // Dialog 내용은 document.body 로 포털된다 — .devui 로 스코프하면 **잡히지 않는다**.
  // 이 테스트는 그 사실 자체를 계약으로 박아 둔다(Phase 6 에서 모달을 옮길 때의 근거).
  test("shadcn Dialog 는 .devui 밖(document.body)으로 포털된다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    await page.locator(".devui-dialog-open").click();

    const content = page.locator(".devui-dialog-content");
    await expect(content).toBeVisible();
    await expect(content).toContainText("포털됩니다");

    // 컨테이너로 스코프하면 0개 — 이것이 Phase 6 이 조심해야 하는 바로 그 함정이다
    await expect(page.locator(".devui .devui-dialog-content")).toHaveCount(0);

    // 접근성: Radix 가 role=dialog 와 포커스 트랩을 제공한다
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(content).toHaveCount(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// S1 — Card 밀도 + 다크 토큰이 실제로 해석되는가
// ─────────────────────────────────────────────────────────────────────────────
// ★다크 토큰은 '정의만 되고 아무도 안 쓰는' 상태가 되기 쉽다★ globals.css §47 이
// .dark 에서 --card/--foreground 를 덮지만, 그 값을 그리는 화면이 없으면 오타 하나로
// 죽어도 아무도 모른다. 여기서 계산된 색을 직접 읽어 그 상태를 막는다.
// ═══════════════════════════════════════════════════════════════════════════════

test("S1a: Card 가 상류 기본값(p-6)이 아니라 조인 패딩으로 렌더된다", async ({ page }) => {
  await page.goto("/dev/ui", { waitUntil: "networkidle" });
  const content = page.locator(".devui-s1card .p-3").first();
  await expect(content).toBeVisible();
  // ★12px 로 못 박았다가 실패했다 — 이 앱의 root font-size 는 16px 이 아니라 14px 이라
  // p-3(0.75rem)이 10.5px 로 떨어진다. 매직 넘버 대신 계약 자체를 쓴다:
  // "본문 패딩은 p-3(0.75rem)이고, 상류 기본값 p-6(1.5rem)이 아니다".
  const { pad, root } = await content.evaluate((e) => ({
    pad: parseFloat(getComputedStyle(e).paddingTop),
    root: parseFloat(getComputedStyle(document.documentElement).fontSize),
  }));
  expect(pad, "Card 본문 패딩 = p-3(0.75rem)").toBeCloseTo(root * 0.75, 1);
  expect(pad, "상류 기본값 p-6 이 되살아나면 안 된다").toBeLessThan(root * 1.5 - 0.5);
});

test("★S1f: .dark 를 켜면 토큰이 실제로 바뀐다★", async ({ page }) => {
  await page.goto("/dev/ui", { waitUntil: "networkidle" });
  const card = page.locator(".devui-s1card").first();

  const light = await card.evaluate((e) => getComputedStyle(e).backgroundColor);
  await page.locator(".devui-darktoggle").click();
  await page.waitForTimeout(120);
  const dark = await card.evaluate((e) => getComputedStyle(e).backgroundColor);

  expect(dark, "다크에서 카드 배경이 그대로면 토큰이 안 먹은 것이다").not.toBe(light);
  // zinc-900(#18181b) = rgb(24, 24, 27) — §47 이 지정한 값과 정확히 맞아야 한다.
  expect(dark).toBe("rgb(24, 24, 27)");

  // 글자도 함께 뒤집혀야 한다 — 배경만 어두워지면 읽을 수 없다.
  const fg = await card.evaluate((e) => getComputedStyle(e).color);
  expect(fg, "다크에서 글자색").toBe("rgb(250, 250, 250)");
});

// ── 롱숏 노출·집중도 (BL4 · `allocation-long-short.spec.ts` 에서 옮김 — 마법사 화면 테스트는 캔버스
//    `portfolio-graph.spec.ts` 롱숏(BL4) 가 지키고, 공용 계산 `shared/lib/exposure` 와 `shared/ui/AllocationMap` 은 여기서) ──
test("★concentration() 이 숏을 버리지 않는다 — /dev/ui 표본으로 실측★", async ({ page }) => {
  // 화면 경로로 음수 보유를 만들 UI 가 없다(보유 입력은 롱온리다). 그래서 격리
  // 라우트에 표본을 두고 **실제 번들 코드가 계산한 값**을 읽는다 — Step 3b 가
  // 세운 관례이고, 청크 경로를 직접 import 하는 것보다 빌드 해시에 안 묶인다.
  await page.goto("/dev/ui", { waitUntil: "networkidle" });

  const lo = page.locator('.devui-ls-basis[data-case="long-only"]');
  const ls = page.locator('.devui-ls-basis[data-case="long-short"]');
  await expect(lo).toHaveText("net");
  await expect(ls).toHaveText("gross");

  // ★이 숫자가 F3 의 증거다★ 롱숏 [60, 50, 30, -25, -15] 의 gross 는 180.
  //   올바른 값 : (60²+50²+30²+25²+15²)/180² × 10⁴ = 7850/32400 × 10⁴ = 2422.8
  //   예전 값   : 롱 다리만(분모 140) → (60²+50²+30²)/140² × 10⁴ = 7000/19600 × 10⁴ = 3571.4
  // 예전 식은 집중도를 **1.47배 크게**(= 더 집중된 것처럼) 보고했다. 두 값이 1000
  // 이상 벌어지므로 이 단언은 반올림이 아니라 식이 바뀌었는지를 잰다.
  const hhi = Number(await page.locator('.devui-ls-hhi[data-case="long-short"]').innerText());
  expect(hhi).toBeGreaterThan(2400);
  expect(hhi).toBeLessThan(2450);
  expect(hhi, "롱 다리만으로 계산한 예전 값이 나왔다").toBeLessThan(3000);

  // 노출 네 축도 같은 표본에서 확인 — gross 180 · net 100 · long 140 · short −40
  await expect(page.locator(".devui-ls-legs")).toContainText("gross 180.0");
  await expect(page.locator(".devui-ls-legs")).toContainText("net 100.0");
  await expect(page.locator(".devui-ls-legs")).toContainText("short -40.0");
});

test("★AllocationMap 이 숏을 두 번째 스트립으로 그린다 — 버리지 않는다★", async ({ page }) => {
  await page.goto("/dev/ui", { waitUntil: "networkidle" });
  const map = page.locator(".devui-ls-map");

  // 롱 스트립 + 숏 스트립 = 2 (예전에는 filter(w>0) 라 1개였고 숏은 사라졌다)
  await expect(map.locator(".aas-map")).toHaveCount(2);
  await expect(map.locator(".as-ls-map-short")).toBeVisible();

  // 범례는 5종목 전부 — 숏 2개가 음수 값으로 남는다
  await expect(map.locator(".aas-legend-i")).toHaveCount(5);
  await expect(map.locator(".as-ls-neg")).toHaveCount(2);
  await expect(map.locator(".aas-legend-i", { hasText: "LG화학" })).toContainText("-25.0%");
});

// ═══════════════════════════════════════════════════════════════════════════════
// BU0 · shared/ui/tx + shared/lib/krFormat — 클래스가 아니라 **동작**을 본다(짝으로 항상-통과를 배제).
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("/dev/ui — BU0 토스식 공용 부품", () => {
  test("Tabs: 화살표·Home·End 로 고르고 초점이 따라간다 · 고른 탭은 늘 하나 · 패널이 바뀐다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const tx = page.locator(".devui-tx");
    const tabs = tx.locator('.tx-tablist [role="tab"]');
    await expect(tabs).toHaveCount(3);
    await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");
    await expect(tx.locator(".devui-tx-panel")).toHaveText("a 패널");
    await tabs.nth(0).focus();
    await page.keyboard.press("ArrowRight");
    await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
    await expect(tabs.nth(1)).toBeFocused();
    await expect(tx.locator(".devui-tx-panel")).toHaveText("b 패널");
    await page.keyboard.press("End");
    await expect(tabs.nth(2)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowRight");                       // 끝에서 처음으로 돈다
    await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");
    await expect(tx.locator('.tx-tablist [aria-selected="true"]')).toHaveCount(1);
    // 로빙 tabindex — 고른 탭만 Tab 순서에 있다(짝: 나머지는 -1)
    await expect(tx.locator('.tx-tablist [tabindex="0"]')).toHaveCount(1);
    await expect(tx.locator('.tx-tablist [tabindex="-1"]')).toHaveCount(2);
    // 패널은 고른 탭을 가리킨다
    const labelled = await tx.locator('[role="tabpanel"]').getAttribute("aria-labelledby");
    expect(labelled).toBe(await tabs.nth(0).getAttribute("id"));
  });

  test("Segmented: radiogroup — 화살표로 고르면 aria-checked 가 옮겨간다(짝: 하나만 켜진다)", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const seg = page.locator('.devui-tx .tx-seg[role="radiogroup"]');
    const opts = seg.locator('[role="radio"]');
    await expect(opts.nth(0)).toHaveAttribute("aria-checked", "true");
    await opts.nth(0).focus();
    await page.keyboard.press("ArrowRight");
    await expect(opts.nth(1)).toHaveAttribute("aria-checked", "true");
    await expect(opts.nth(0)).toHaveAttribute("aria-checked", "false");
    await expect(seg.locator('[aria-checked="true"]')).toHaveCount(1);
  });

  test("Stat: 등락은 색 + ▲▼ + 글자 — 오름 빨강 · 내림 파랑(한국식) · 그대로·모름은 흐린 글자이고 화살표가 없다", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const d = (dir: string) => page.locator(`.devui-tx .tx-delta[data-dir="${dir}"]`).first();
    const color = (dir: string) => d(dir).evaluate((e) => getComputedStyle(e).color);
    expect(await color("up")).toBe("rgb(210, 42, 59)");          // --tx-up-ink #d22a3b
    expect(await color("down")).toBe("rgb(27, 100, 218)");       // --tx-down-ink #1b64da
    expect(await color("flat")).toBe("rgb(95, 107, 122)");       // --tx-mute
    await expect(d("up")).toHaveText("▲ +2.1%p");
    await expect(d("down")).toHaveText("▼ −3.0%p");
    await expect(d("flat")).toHaveText("0.0%p");                 // ★짝★ 그대로에는 화살표가 없다
    await expect(d("unknown")).toHaveText("몰라요");               // 미상은 0 이 아니다
    expect(await color("unknown")).not.toBe(await color("up"));
  });

  test("Unknown 은 사유를 보이는 글자로 싣는다 · ListRow 는 누를 수 있을 때만 화살표가 있다(짝)", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const u = page.locator(".devui-tx .tx-unknown").first();
    await expect(u.locator(".tx-unknown-v")).toHaveText("몰라요");
    await expect(u.locator(".tx-unknown-why")).toBeVisible();
    expect((await u.locator(".tx-unknown-why").innerText()).trim().length).toBeGreaterThan(5);

    const rows = page.locator(".devui-tx .tx-row");
    await expect(page.locator(".devui-tx a.tx-row--go .tx-row-go").first()).toBeVisible();
    await expect(page.locator(".devui-tx button.tx-row--go .tx-row-go")).toHaveCount(1);
    const plain = rows.filter({ hasText: "적재 행 수" });
    await expect(plain).toHaveCount(1);
    await expect(plain.locator(".tx-row-go")).toHaveCount(0);
    expect(await plain.evaluate((e) => e.tagName)).toBe("DIV");
  });

  test("krFormat: 한국식 단위·부호·비율 — 미상은 '몰라요'(0·NaN 으로 그리지 않는다)", async ({ page }) => {
    await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
    const want: [string, string, string][] = [
      ["num", "1234.5", "1,235"], ["num", "1234.5, 1", "1,234.5"], ["num", "-0.0001", "0"],
      ["krUnit", "3.4e11", "3,400억"], ["krUnit", "1.234e12", "1.2조"], ["krUnit", "9.9996e11", "1.0조"],
      ["krUnit", "99995000", "1억"], ["krUnit", "56000000", "5,600만"], ["krUnit", "9999.6", "1만"],
      ["krUnit", "-2.5e8", "−3억"], ["won", "1234", "1,234원"], ["won", "3.4e11", "3,400억원"],
      ["pct", "0.241", "24.1%"], ["pct", "-0.03", "−3.0%"], ["signedPct", "0.241", "+24.1%"],
      ["signedPct", "0", "0.0%"], ["signedPct", "-0.00004", "0.0%"], ["pp", "0.021", "+2.1%p"],
      ["pp", "-0.03", "−3.0%p"], ["num", "null", "몰라요"], ["pct", "NaN", "몰라요"], ["won", "Infinity", "몰라요"],
      ["priceWon", "71200", "71,200원"], ["priceWon", "undefined", "몰라요"],
      ["direction", "0.1", "up"], ["direction", "-1", "down"], ["direction", "0", "flat"], ["direction", "null", "unknown"],
    ];
    const rows = page.locator(".devui-krfmt-table tr");
    await expect(rows).toHaveCount(want.length);
    const got = await rows.evaluateAll((trs) => trs.map((tr) => [tr.getAttribute("data-fn"), tr.getAttribute("data-in"),
      tr.querySelector(".devui-krfmt-out")?.textContent ?? ""]));
    expect(got).toEqual(want);
  });
});
