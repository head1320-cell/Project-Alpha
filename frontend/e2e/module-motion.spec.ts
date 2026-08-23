import { test, expect, type Page } from "@playwright/test";
import { freezeCharts, contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// A12 — 7개 코어 모듈 모션 (§63) + Recharts 런타임 토글  ·  A13 — 3·4번 계측 정상화
// ─────────────────────────────────────────────────────────────────────────────
// ★이 파일에서 가장 값진 것은 3·4번 쌍이다★ "차트 애니메이션을 프로덕션에서 켰다"는 주장은
// **켜졌는지 재지 않으면 검증되지 않는다**. 토글을 달아 놓고 실제로는 항상 꺼져 있어도
// 어설픈 결정성 가드는 초록으로 남는다 — 그게 A12 가 기각한 `NEXT_PUBLIC_E2E` 방식이
// 만들었을 상태와 정확히 같다(빌드 인라인이라 config 주입이 무시되고, 아무도 모른다).
// 그래서 3번과 4번을 **쌍으로** 둔다: 얼리면 멈추고(≤3 프레임), 안 얼리면 움직인다(37 프레임).
// 변이 프로브 3건 전부 각자의 이유로 빨개지는 것을 확인했다(A13):
//   훅 `return false` → 4번만 red · 훅 `return true` → 3·4번 red · freezeCharts 무력화 → 3·4번 red
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
// 04 Company 를 쓴다 — 실측에서 Recharts 시리즈가 확실히 렌더되는 라우트다.
const CHART_ROUTE = "/insights";

// ★A13: 여기서 재는 속성이 전부였다 — A12 는 틀린 속성을 쟀다★
// A12 는 `.recharts-area-area` 등의 **`d` 속성**을 샘플링해 "변하지 않는다 →
// 마운트 애니메이션이 죽었다"고 결론짓고 4번을 fixme 로 남겼다. 그런데 recharts 소스를
// 읽어 보면 **마운트 애니메이션은 `d` 를 설계상 건드리지 않는다**:
//
//   Line  `Line.js:303-315` — `prevPoints` 가 없는 첫 애니메이션은 `strokeDasharray` 를
//                             0→`totalLength` 로 보간한다. `d` 는 상수.
//   Area  `Area.js:290-297` — `animationClipPath-*` 사각형을 키운다. `d` 는 상수.
//   Bar   `Bar.js:170`      — rect 의 `y`/`height`(= `.recharts-rectangle` 의 `d`).
//   Pie                     — `.recharts-sector` 의 `d`. **여기만** `d` 가 변한다.
//
// `/insights` 는 Area + Bar 만 렌더한다(`widgets/company/parts.tsx:56,78`, Pie 없음).
// 즉 애니메이션이 정상 동작해도 A12 의 테스트는 **어떤 경우에도 초록이 될 수 없었다**.
// 제품 결함이 아니라 계측 결함이었다.
//
// 그래서 지문은 시리즈 종류에 의존하지 않도록 **애니메이션이 실제로 움직이는 속성 전부**를
// 모은다: 모든 path 의 `d` + `stroke-dasharray`, 그리고 clipPath 사각형의 기하.
async function chartFrame(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const surfaces = document.querySelectorAll(".recharts-surface");
    if (!surfaces.length) return null;
    const parts: string[] = [];
    surfaces.forEach((s) => {
      s.querySelectorAll("path").forEach((p) => {
        parts.push(p.getAttribute("d") ?? "", p.getAttribute("stroke-dasharray") ?? "");
      });
      s.querySelectorAll("clipPath rect").forEach((r) => {
        parts.push(r.getAttribute("x") ?? "", r.getAttribute("y") ?? "",
                   r.getAttribute("width") ?? "", r.getAttribute("height") ?? "");
      });
    });
    return parts.join("|");
  });
}

/** 내비게이션 직후부터 30ms 간격으로 훑어 **마운트 순간을 포함**한 서로 다른 프레임 수.
 *  ★첫 프레임을 기준으로 창을 잡는다★ 처음엔 고정 4.2초를 훑었는데 **0 프레임**이 나왔다 —
 *  `/insights` 의 차트는 데이터가 도착한 뒤에야 마운트되므로 그 창이 마운트보다 빨랐다.
 *  그래서 서피스가 나타날 때까지 기다리되, 나타난 뒤 2.1초를 더 훑는다(기본 애니메이션 1.5초). */
async function countFrames(page: Page): Promise<number> {
  await page.goto(CHART_ROUTE, { waitUntil: "commit" });
  const frames = new Set<string>();
  let sampled = 0;
  for (let i = 0; i < 500 && sampled < 70; i++) {
    const f = await chartFrame(page);
    if (f) { frames.add(f); sampled++; }
    await page.waitForTimeout(30);
  }
  return frames.size;
}

// 3. 얼리면 정지한다 — 스크린샷 결정성의 근거.
// ★A12 시점에 이 가드는 공허했고, A13 의 첫 시도도 여전히 약했다★
// A12 는 틀린 속성을 재서 "얼려서 안 움직인다"와 "원래 안 움직인다"를 구분하지 못했다.
// A13 에서 지문을 고친 뒤에도 **안정 상태만** 보면(로드 3초 뒤 900ms) 마운트 애니메이션은
// 이미 끝나 있어서, 훅을 `return true` 로 고정하는 변이에 여전히 초록이었다 —
// 프로브가 그 사실을 드러냈다. 그래서 **마운트 창 전체**를 세는 형태로 바꾼다.
// 실측: 얼리면 1 프레임, 안 얼리면 37 프레임.
test("★freezeCharts 를 걸면 차트가 첫 프레임부터 최종 형태다★", async ({ page }) => {
  test.setTimeout(120_000);
  await freezeCharts(page);
  const frozen = await countFrames(page);
  test.info().annotations.push({ type: "frozen-frames", description: String(frozen) });
  expect(frozen, "차트를 한 프레임도 못 잡았다 — 라우트/선택자를 확인할 것").toBeGreaterThan(0);
  // 데이터 도착으로 한두 프레임은 정당하게 늘 수 있다. 애니메이션이 켜지면 수십이 된다.
  expect(frozen, `얼렸는데 ${frozen} 프레임이 잡혔다 — 결정성이 깨진다`).toBeLessThanOrEqual(3);

  // 안정 상태에서도 움직이지 않는다(스크린샷은 이 시점에 찍힌다).
  await goto(page, CHART_ROUTE);
  const first = await chartFrame(page);
  await page.waitForTimeout(900);
  expect(await chartFrame(page), "정착 후에도 차트가 움직였다").toBe(first);
});

// 4. 얼리지 않으면 실제로 움직인다 — "프로덕션에서 애니메이션이 켜진다"의 유일한 증거.
// ★차분으로 잰다★ 페이지 로드 중에는 데이터가 도착하며 차트가 정당하게 바뀌므로,
// "프레임이 2개 이상"만으로는 애니메이션을 증명하지 못한다(데이터 도착만으로도 참이 된다).
// 그래서 **같은 라우트를 얼린 채로도 한 번 재고 그 차이**를 본다 — 데이터 도착은 양쪽에
// 똑같이 기여하므로, 차이는 오직 차트 애니메이션에서만 나온다.
test("★freezeCharts 없이는 차트가 실제로 애니메이션된다 (얼린 것과의 차분)★",
  async ({ browser }) => {
    test.setTimeout(150_000);   // 두 번의 전체 로드 + 각 최대 15초 샘플링
    const run = async (freeze: boolean) => {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      if (freeze) await freezeCharts(page);
      const n = await countFrames(page);
      await ctx.close();
      return n;
    };
    const frozen = await run(true);
    const live = await run(false);
    test.info().annotations.push({ type: "frames", description: `frozen=${frozen} live=${live}` });

    expect(frozen, "얼린 쪽에서 차트를 한 프레임도 못 잡았다 — 라우트/선택자를 확인할 것")
      .toBeGreaterThan(0);
    // 30ms 샘플링 × 1.5초 애니메이션이면 수십 프레임이 나온다. 데이터 도착이 만드는
    // 몇 프레임과 확실히 구분되도록 여유 있게 +10 을 요구한다.
    expect(live, `애니메이션이 켜지지 않았다 (live=${live}, frozen=${frozen})`)
      .toBeGreaterThanOrEqual(frozen + 10);
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
