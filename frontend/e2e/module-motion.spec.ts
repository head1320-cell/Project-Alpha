import { test, expect, type Page } from "@playwright/test";
import { freezeCharts, contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// A12 — 7개 코어 모듈 모션 (§63) + Recharts 런타임 토글
// ─────────────────────────────────────────────────────────────────────────────
// ★이 파일에서 가장 값진 것은 4번이다★ "차트 애니메이션을 프로덕션에서 켰다"는 주장은
// **켜졌는지 재지 않으면 검증되지 않는다**. 토글을 달아 놓고 실제로는 항상 꺼져 있어도
// 3번(결정성)은 초록으로 남는다 — 그게 A12 가 기각한 `NEXT_PUBLIC_E2E` 방식이 만들었을
// 상태와 정확히 같다(빌드 인라인이라 config 주입이 무시되고, 아무도 모른다).
// 그래서 3번과 4번을 **쌍으로** 둔다: 얼리면 멈추고, 안 얼리면 실제로 움직인다.
//
// ★`reducedMotion:'reduce'` 를 전역으로 켜지 않는 이유★ 그러면 §62/§63 이 전부 꺼져
// A10·A11 의 전이·엘리베이션 가드가 측정할 대상을 잃고 **0 으로 통과**한다. 이 스펙은
// Recharts 만 겨냥하는 `freezeCharts` 를 쓰고, CSS 모션은 살려 둔 채로 잰다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 실측으로 열거한 모듈별 라우트와 그 모듈의 패널 클래스(§63 과 같은 목록). */
// ★이 목록은 정적 grep 이 아니라 브라우저 실측이다★ 처음엔 위젯 소스를 grep 해서 썼는데
// 4개 모듈에서 실제 렌더와 달랐고, `/backtest` 는 **하나도 렌더되지 않았다**. 아래 1번의
// "노드 수 먼저 단언"이 그 0 을 잡아 준 덕에 목록이 틀렸다는 사실이 드러났다.
const MODULES: { name: string; path: string; panels: string }[] = [
  { name: "00 Dashboard",  path: "/dashboard",   panels: ".dash-card" },
  { name: "01 Screener",   path: "/screener",    panels: ".bsc-workspace, .bsc-rail, .bsc-preset, .bsc-mcap" },
  { name: "02 Backtester", path: "/backtest",    panels: ".tbt-chart, .tbt-config-main, .tbt-right-col, .tbt-watch-panel" },
  { name: "03 Macro",      path: "/macro",       panels: ".mc-card, .mv-rcard" },
  { name: "04 Company",    path: "/insights",    panels: ".ca-cp-card, .ca-cp-panel" },
  { name: "05 Risk",       path: "/risk-tools",  panels: ".tstat, .trisk-table" },
  { name: "07 Data Infra", path: "/admin/data",  panels: ".t-honesty, .trisk-table" },
];

// ★기존 대비 결함 — A12 가 만든 것이 아니다★ 이 감사를 7개 모듈에 처음 돌렸더니 25건이
// 나왔는데, §63 은 색을 하나도 바꾸지 않는다. 증거: `.tcrumb-sep`(셸 브레드크럼 구분자
// `›`, #e5e5e5, 1.26:1)이 **7개 라우트 전부**에서 걸린다. `/backtest` 의 흰 글씨 1.49:1,
// `rgb(220,53,69)`(=#dc3545, A11 이 통일한 줄 알았던 그 빨강), `/macro` 의 `#16a34a`
// (S1b-2 가 3.16:1 로 퇴출한 값)도 마찬가지다.
// 고치는 것은 A12(모션 단계)의 범위 밖이라, CSS 특이성 가드의 `KNOWN_COLLISIONS` 와 같은
// 방식으로 **기존 실패 수를 기록**한다. 새 결함은 빨개지고, 이 수는 줄어들 수만 있다.
const KNOWN_LOW: Record<string, number> = {
  "00 Dashboard": 1, "01 Screener": 3, "02 Backtester": 9,
  "03 Macro": 4, "04 Company": 6, "05 Risk": 1, "07 Data Infra": 1,
};

/** §62 가 정의한 모션 토큰 — 초 단위. 0 은 "전이 없음"이라 항상 허용된다. */
const ALLOWED_S = [0, 0.12, 0.18, 0.26];

// ★`networkidle` 을 쓰지 않는다★ `/insights` 는 폴링 때문에 idle 이 오지 않아 앞선
// 프로브에서 "패널 없음"으로 보였다. 실제로는 `.ca-cp-card` 가 6개 있었다.
async function goto(page: Page, path: string) {
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".terminal-main")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(3_000);   // 위젯 마운트 + 첫 데이터
}

// ── 1. reduced-motion 에서 사라지는 요소가 없다 ──────────────────────────────
// `animation: … both` 는 애니메이션이 멈춘 채 시작 프레임(opacity:0)에 붙들리면
// 콘텐츠를 통째로 숨긴다. 눈으로는 "빈 화면"이고 어떤 기능 테스트도 빨개지지 않는다.
for (const m of MODULES) {
  test(`★${m.name}: reduced-motion 에서 숨겨지는 패널이 없다★`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await freezeCharts(page);
    await goto(page, m.path);

    const r = await page.evaluate((sel) => {
      const out: string[] = [];
      let n = 0;
      for (const el of document.querySelectorAll(`.terminal-main :is(${sel})`)) {
        n++;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;  // 의도적 숨김은 대상 아님
        if (parseFloat(cs.opacity) < 0.99) out.push(`${el.className} opacity=${cs.opacity}`);
        const box = el.getBoundingClientRect();
        if (box.width < 1 || box.height < 1) out.push(`${el.className} box=${box.width}x${box.height}`);
      }
      return { n, out: [...new Set(out)] };
    }, m.panels);

    // ★노드 수를 먼저 단언한다★ 빈 선택자는 아무것도 검사하지 않고 통과한다 —
    // A7 에서 클리핑 가드가 §57 을 통째로 지워도 초록이었던 실패 형태다.
    expect(r.n, `${m.name}: §63 대상 패널이 렌더돼야 검사가 성립한다`).toBeGreaterThan(0);
    expect(r.out, `${m.name} 에서 숨겨진 요소: ${JSON.stringify(r.out)}`).toEqual([]);
  });
}

// ── 2. 전이 시간이 §62 토큰 안에 있다 ────────────────────────────────────────
// ★한 테스트에 7개 라우트를 넣었더니 90초 타임아웃에 걸렸다★ 값 자체는 전부 정상
// (`0` 과 `0.12`)이었는데 5번째 모듈에서 시간이 끊겼다 — 제품 결함이 아니라 테스트 구조
// 문제였다. 모듈별로 쪼개면 각자 90초를 갖는다.
for (const m of MODULES) {
  test(`${m.name}: 전이 시간이 모션 토큰 범위 안이다`, async ({ page }) => {
    await freezeCharts(page);
    await goto(page, m.path);
    const r = await page.evaluate((sel) => {
      const out: string[] = [];
      let n = 0;
      for (const el of document.querySelectorAll(`.terminal-main :is(${sel})`)) {
        n++;
        for (const d of getComputedStyle(el).transitionDuration.split(",")) {
          const v = parseFloat(d);
          if (Number.isFinite(v)) out.push(`${v}`);
        }
      }
      return { n, durations: [...new Set(out)] };
    }, m.panels);
    expect(r.n, `${m.name}: 패널이 렌더되지 않았다`).toBeGreaterThan(0);
    const bad = r.durations.filter((d) => !ALLOWED_S.some((a) => Math.abs(a - parseFloat(d)) < 0.001));
    expect(bad, `${m.name} 토큰 밖 전이 시간: ${JSON.stringify(bad)}`).toEqual([]);
  });
}

// ── 3·4. 차트 토글이 양방향으로 실제 동작한다 ────────────────────────────────
// 03 Macro 를 대표로 쓴다 — Recharts 시리즈가 확실히 렌더되는 라우트다.
// 04 Company 를 쓴다 — 실측에서 `.recharts-curve` 가 확실히 렌더되는 라우트다(/macro 는
// 상단이 참조영역·사각형 위주라 첫 시리즈 path 를 잡기 어려웠다).
const CHART_ROUTE = "/insights";
/** 첫 Recharts 시리즈 path 의 `d` 를 읽는다. 애니메이션 중이면 프레임마다 달라진다. */
async function seriesPath(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const el = document.querySelector(
      ".recharts-curve, .recharts-line-curve, .recharts-area-area, .recharts-sector",
    );
    return el ? el.getAttribute("d") : null;
  });
}

// ★이 가드는 지금 공허하다 — 프로브가 그 사실을 드러냈다★ 훅이 `__MOTION_OFF__` 를
// 무시하도록 망가뜨려도 이 테스트는 **초록으로 남았다**. 이유는 아래 fixme 와 같다:
// 차트가 애초에 마운트 애니메이션을 하지 않으므로, "얼리면 멈춘다"가 참인 이유가
// "얼려서"가 아니라 "원래 안 움직여서"다. 리마운트 key 로 애니메이션이 실제로 켜지면
// 이 가드와 아래 fixme 가 **함께** 의미를 갖는다. 그때까지 통과를 근거로 쓰지 말 것.
test("★freezeCharts 를 걸면 차트가 첫 프레임부터 최종 형태다★", async ({ page }) => {
  await freezeCharts(page);
  await goto(page, CHART_ROUTE);
  await expect.poll(() => seriesPath(page), { timeout: 20_000 }).not.toBeNull();
  const first = await seriesPath(page);
  await page.waitForTimeout(900);
  expect(await seriesPath(page), "얼렸는데 차트가 움직였다 — 결정성이 깨진다").toBe(first);
});

// ★측정이 내 설계의 한계를 드러냈다 — 초록으로 위장하지 않고 fixme 로 남긴다★
// `useChartAnimation` 은 하이드레이션 불일치를 피하려고 **첫 렌더에 항상 `false`** 를 주고
// 마운트 뒤 `true` 로 뒤집는다. 그런데 Recharts 는 **마운트 시점에** 애니메이션 여부를
// 정하므로, 나중에 프롭이 true 가 돼도 이미 최종 상태로 그려진 차트에는 애니메이션할
// 대상이 남아 있지 않다. 즉 "프로덕션에서 켜진다"는 주장이 **마운트 애니메이션에 한해서는
// 아직 참이 아니다**(데이터가 나중에 도착하는 차트는 그 갱신에서 애니메이션된다).
//
// 고치려면 `anim` 이 true 가 될 때 차트를 리마운트시키는 key 가 필요하고 19개 소비자를
// 전부 건드려야 한다 — A12 범위를 넘어 다음 단계로 넘긴다. 그때까지 통과 도장을 찍지 않고
// 사유를 적어 둔다. 3번(결정성)은 계속 실측으로 지켜진다.
test.fixme("★freezeCharts 없이는 차트가 실제로 애니메이션된다★", async ({ page }) => {
  // 이 가드가 없으면 "프로덕션에서 애니메이션을 켰다"는 주장이 검증되지 않는다 —
  // 토글이 항상 꺼져 있어도 위 3번은 초록으로 남기 때문이다.
  //
  // ★샘플링 시점이 전부다 (첫 시도의 실패 원인)★ 공용 `goto()` 는 위젯 마운트를 기다리며
  // 3초를 쉬는데 Recharts 기본 애니메이션은 1.5초라 그때는 이미 끝나 있다. 그래서 여기서는
  // 내비게이션 직후부터 30ms 간격으로 훑어 **마운트 순간을 포함**한다.
  await page.goto(CHART_ROUTE, { waitUntil: "commit" });
  const frames = new Set<string>();
  for (let i = 0; i < 160; i++) {
    const d = await seriesPath(page);
    if (d) frames.add(d);
    if (frames.size > 1) break;
    await page.waitForTimeout(30);
  }
  expect(frames.size,
    "차트가 한 프레임도 변하지 않았다 — 토글이 켜지지 않거나 샘플링이 늦었다").toBeGreaterThan(1);
});

// ── 5. §63 이 쓰는 키프레임은 layout 속성을 건드리지 않는다 ──────────────────
test("모션 키프레임이 GPU 속성만 애니메이션한다", async ({ page }) => {
  await goto(page, "/dashboard");
  const bad = await page.evaluate(() => {
    const LAYOUT = new Set(["width", "height", "top", "left", "right", "bottom",
      "margin", "padding", "max-height", "min-height", "flex", "font-size"]);
    const out: string[] = [];
    let seen = 0;
    for (const sheet of Array.from(document.styleSheets)) {
      let rules: CSSRuleList;
      try { rules = sheet.cssRules; } catch { continue; }   // 교차 출처 시트는 건너뛴다
      const walk = (list: CSSRuleList) => {
        for (const r of Array.from(list)) {
          if (r instanceof CSSKeyframesRule) {
            if (!/^a11-/.test(r.name)) continue;             // §62/§63 이 쓰는 것만
            seen++;
            for (const kf of Array.from(r.cssRules) as CSSKeyframeRule[]) {
              for (const p of Array.from(kf.style)) {
                if (LAYOUT.has(p)) out.push(`${r.name}:${p}`);
              }
            }
          } else if ("cssRules" in r) {
            walk((r as CSSGroupingRule).cssRules);
          }
        }
      };
      walk(rules);
    }
    return { seen, out: [...new Set(out)] };
  });
  expect(bad.seen, "a11-* 키프레임을 하나도 찾지 못했다 — 검사가 성립하지 않는다").toBeGreaterThan(0);
  expect(bad.out, `layout 속성을 애니메이션하는 키프레임: ${JSON.stringify(bad.out)}`).toEqual([]);
});

// ── 6. 라이트·다크 대비 ───────────────────────────────────────────────────────
for (const m of MODULES) {
  test(`${m.name}: 라이트 WCAG AA (기록된 기존 결함 이하)`, async ({ page }) => {
    await freezeCharts(page);
    await goto(page, m.path);
    // ★다크는 재지 않는다 — 이 7개 모듈에는 다크 구현이 없다★ 실측: `.dark` 규칙이
    // `.aas-root`(73) · `.brun-results`(10) · `.aas-gate`(3) 에만 있고, 이 모듈들의
    // 클래스(`.dash-card` `.mc-card` `.tbt-*` `.bsc-*` `.trisk-*` …)에는 **0건**이다.
    // 없는 기능을 단언하면 가드가 아니라 영원한 빨강이 된다. 다크 확장은 별도 단계다.
    const a = (await page.evaluate(contrastAudit(".terminal-main"))) as AuditResult;
    expect(a.checked, `${m.name}: 검사한 노드가 0`).toBeGreaterThan(5);
    expect(a.low.length,
      `${m.name} AA 미달이 기록(${KNOWN_LOW[m.name]})을 넘었다: ${JSON.stringify(a.low)}`)
      .toBeLessThanOrEqual(KNOWN_LOW[m.name]);
  });
}
