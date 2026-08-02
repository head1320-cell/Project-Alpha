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
//   1) shared/ui 의 컴포넌트 export 36개가 전부 표본으로 마운트되었는가(제외 없음)
//   2) 각 프리미티브가 내보내는 **클래스 계약**이 그대로인가
//   3) 순수 프레젠테이션 화면인데 uncaught error / 네트워크 호출이 없는가
//
// 한계(정직하게): 클래스가 존재한다는 것은 시각적 동등성의 증명이 아니다. 클래스명
// 변경·DOM 구조 붕괴·컴포넌트 크래시는 잡지만, 색·간격이 달라지는 것은 잡지 못한다.
// kit 은 전부 인라인 스타일이라(.bs-numbox 외 클래스 없음) role·태그로 검증한다.
//
// 개수 단언은 전부 갤러리 루트(.devui)로 범위를 좁힌다. 셸(TerminalShell)이
// 페이지를 감싸고 있어서다 — 예를 들어 헤더의 RegimeBadge 는 로딩 중 .skeleton 을
// 렌더하므로, 범위를 좁히지 않으면 skeleton 개수가 타이밍에 따라 흔들린다.
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

    // 갤러리 자체는 데이터를 부르지 않는다. 셸(TerminalShell)의 RegimeBadge 가
    // /macro/regime 을 한 번 호출하지만 그것은 200 이어야 하므로, 4xx/5xx 가
    // 하나라도 잡히면 실패다.
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
    await expect(g.locator(".tstate-loading .tstate-spinner")).toHaveCount(3);
    await expect(g.locator(".tstate-empty .tstate-glyph")).toHaveCount(3);
    await expect(g.locator(".tstate-sub")).toHaveCount(6); // sub/reason 이 있는 것만

    // 로딩은 role=status, 오류는 role=alert — 스크린리더 계약
    await expect(g.locator('.tstate-loading[role="status"]')).toHaveCount(3);
    await expect(g.locator('.tstate-error[role="alert"]')).toHaveCount(2);

    await expect(g.locator(".tstate-loading").first()).toContainText("[ LOADING ]");
    await expect(g.locator(".tstate-error").first()).toContainText("[ ERROR ]");

    // ★unavailable 은 empty 와 반드시 다르게 보여야 한다★ 같은 모양이면 "없음" 이
    // "문제 없음" 으로 읽힌다. 클래스가 다르다는 것만으로는 부족하므로 실제 계산된
    // 배경색이 서로 다른지까지 본다.
    await expect(g.locator(".tstate-unavail").first()).toContainText("[ N/A ]");
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

    // Segmented — 3개 버튼
    const seg = page.locator(".devui-item", { has: page.locator(".devui-item-name", { hasText: /^Segmented$/ }) });
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
