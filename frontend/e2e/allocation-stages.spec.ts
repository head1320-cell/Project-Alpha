import { test, expect, type Page } from "@playwright/test";
import { freezeCharts, contrastAudit, type AuditResult } from "./helpers";

// A12: Recharts 애니메이션만 끈다 — CSS 모션(§62/§63)은 그대로 둔다.
// `reducedMotion:'reduce'` 를 쓰면 CSS 까지 꺼져 모션 가드가 공허해진다.
test.beforeEach(async ({ page }) => { await freezeCharts(page); });


// ═══════════════════════════════════════════════════════════════════════════════
// 0M · 01 · 03 · 04 · 05 — 공통 구조 + 스테이지별 핵심 (A5)
// ─────────────────────────────────────────────────────────────────────────────
// 다섯 스테이지는 **서로 반대 방향으로** 실패하고 있었다: 0M·03 은 거의 비어 있고
// 04·05 는 레일이 넘쳤다. 원인은 하나 — 레일이 무엇을 담는 곳인지 아무도 말한 적이
// 없다. 그래서 이 스펙의 1번은 개별 화면이 아니라 **폭 스케일 자체**를 지킨다.
// ═══════════════════════════════════════════════════════════════════════════════

const ROUTES: [path: string, label: string][] = [
  ["/allocation/macro", "0M MACRO"],
  ["/allocation/construct", "01 CONSTRUCT"],
  ["/allocation/thesis", "03 THESIS"],
  ["/allocation/timing", "04 TIMING"],
  ["/allocation/optimize", "05 OPTIMIZE"],
];

async function seed(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
}

/** 그리드 칼럼 문자열에서 레일 폭(px)을 읽는다. `.as-ws-exp` 는 레일이 오른쪽이다. */
function railPx(cols: string, railIsSecond: boolean): number {
  const parts = cols.split(/\s+/).map((p) => parseFloat(p));
  return railIsSecond ? parts[1] : parts[0];
}

test("★레일 폭 스케일 — 가장 빽빽한 레일이 가장 좁으면 안 된다★", async ({ page }) => {
  // ★두 단계 동안 "무해"로 기록돼 있던 결함★
  // `.as-ws-opt`(320) · `.as-ws-jr`(340) 는 전부 레일을 넓히는데 `.as-ws-tm` 과
  // `.as-ws-rob` 은 **아무것도 정의하지 않아** `.as-ws2` 의 300px 로 떨어졌다.
  // 04 TIMING 레일에는 게이트 카드 4장 · 팩터 행(⇄ + 입력 + ×) · 브레드스 · 자산군
  // 스위치 · 오버레이 · 리스크 제어가 들어간다 — 스튜디오에서 가장 빽빽한 레일이
  // 가장 좁은 칼럼을 받고 있었다. 클래스는 넓히라고 붙어 있었고, 넓힌 적이 없다.
  await seed(page);

  const read = async (path: string, railIsSecond = false) => {
    await page.goto(path, { waitUntil: "networkidle" });
    const cols = await page.locator(".as-ws2").evaluate((e) => getComputedStyle(e).gridTemplateColumns);
    expect(cols.split(/\s+/).length, `${path}: 2칼럼 그리드가 아니다 (${cols})`).toBe(2);
    return railPx(cols, railIsSecond);
  };

  const timing = await read("/allocation/timing");
  const optimize = await read("/allocation/optimize");
  const construct = await read("/allocation/construct");

  expect(timing, "타이밍 레일이 300px 기본값으로 떨어졌다 — .as-ws-tm 이 다시 비었다")
    .toBeGreaterThan(construct);
  expect(timing, "가장 빽빽한 레일(04)이 05 보다 좁다").toBeGreaterThanOrEqual(optimize);
});

test("★산키 라벨이 플롯 밖으로 잘려 나가지 않는다★", async ({ page }) => {
  // ★화면에서는 결함으로 보이지 않았다★ 마지막 단 라벨을 노드 오른쪽에 그리면서
  // `KODEX 미국S&P500 89.5%` 가 `KODEX 미국S&P500 89` 로 잘렸는데, 이름이 원래
  // 그런 줄 알기 딱 좋은 모양이다. 어떤 테스트도 SVG 텍스트의 좌표를 본 적이 없다.
  // ★스텁을 쓰지 않는다★ 첫 판은 analyze 응답을 흉내 냈는데, 이 화면이 결과에서 읽는
  // 필드가 스텁보다 많아 서브트리가 아예 렌더되지 않았다(= 라벨 0개 → 테스트가 통과할
  // 뻔했다면 더 나빴다). `/allocation/analyze` 는 **순수 계산 엔드포인트**라 서버에
  // 아무것도 남기지 않으므로(런 기록은 저널 패널의 별도 행위다) 실제로 실행하는 편이
  // 더 단순하고 더 진짜에 가깝다. 백엔드는 이미 KIS_USE_MOCK 로 결정적이다.
  await seed(page);
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  await page.locator(".as-run").click();

  const svgText = page.locator(".as-card", { hasText: "ALLOCATION FLOW" }).locator("svg text");
  await expect(svgText.first()).toBeVisible({ timeout: 30_000 });

  const overflow = await page.locator(".as-card", { hasText: "ALLOCATION FLOW" })
    .evaluate((card) => {
      const svg = card.querySelector("svg");
      if (!svg) return ["NO SVG"];
      const right = svg.getBoundingClientRect().right;
      const bad: string[] = [];
      svg.querySelectorAll("text").forEach((t) => {
        const b = (t as SVGTextElement).getBoundingClientRect();
        // 1px 여유 — 반올림.
        if (b.right > right + 1) bad.push(`${t.textContent?.trim()} (${Math.round(b.right - right)}px 초과)`);
      });
      return bad;
    });
  expect(overflow, "산키 라벨이 플롯 오른쪽으로 넘쳤다").toEqual([]);
});

test("컴포짓 하위 점수가 글자로만 있지 않다", async ({ page }) => {
  // 다섯 값 전부 0–100 같은 척도인데 `label 100` 짝만 나열돼 순위를 눈으로 못 읽었다.
  await seed(page);
  await page.goto("/allocation/timing", { waitUntil: "networkidle" });

  const comps = page.locator(".as-tm-comp");
  const n = await comps.count();
  if (n === 0) test.skip(true, "컴포짓 데이터 없음 (백엔드 timing_panel 미제공)");
  expect(n, "하위 점수 개수").toBeGreaterThan(2);

  // 개수를 먼저 단언한 뒤 루프 — 빈 셀렉터가 조용히 통과하지 않게.
  const tracks = page.locator(".as-tm-comp .as-tm-comp-track");
  await expect(tracks).toHaveCount(n);
  for (const t of await tracks.all()) {
    await expect(t, "막대에 접근 가능한 이름이 없다").toHaveAttribute("aria-label", /\d+점/);
  }
  // 숫자도 그대로 남아 있어야 한다 — 막대로 **대체**하면 정확한 값을 잃는다.
  await expect(page.locator(".as-tm-comp .as-tm-comp-v").first()).toHaveText(/^\d+$/);
});

test("★03: 뷰 효과를 0 으로 지어내지 않는다★", async ({ page }) => {
  // 최적화 전에는 시장 사전분포도 뷰 사후분포도 **존재하지 않는다**. 0.0 으로 채우면
  // "뷰가 아무것도 안 바꿨다"로 읽힌다 — A3 의 캡가중, A4 의 충격과 같은 부류다.
  await seed(page);
  await page.goto("/allocation/thesis", { waitUntil: "networkidle" });

  const card = page.locator(".as-card", { hasText: "VIEW EFFECT" });
  await expect(card).toBeVisible({ timeout: 15_000 });

  const na = card.locator(".aas-cmp-na");
  expect(await na.count(), "미계산 셀이 하나도 없다").toBeGreaterThan(0);
  await expect(na.first()).toHaveText("미계산");
  expect((await card.innerText()), "실행 전인데 0.0 을 그렸다").not.toMatch(/\b0\.0\b/);
});

test("0M: 빈 상태가 막다른 골목이 아니다", async ({ page }) => {
  await seed(page);
  await page.goto("/allocation/macro", { waitUntil: "networkidle" });

  const none = page.locator(".as-macro-none");
  if (await none.count() === 0) test.skip(true, "이미 스냅샷이 붙어 있음");

  const link = none.locator("a.as-macro-open");
  await expect(link, "Macro 탭으로 가는 링크가 없다").toHaveCount(1);
  await expect(link).toHaveAttribute("href", "/macro");
  // 이 단계는 선택이다 — 그 사실을 적지 않으면 사용자는 뭘 빠뜨린 줄 안다.
  await expect(none).toContainText("선택");
});

test("★접힌 것은 설명뿐 — 경고는 접지 않는다★", async ({ page }) => {
  // 이번 단계에서 답으로 받은 규칙의 기계적 검사. 산문을 접는 것은 좋지만
  // 경고·미가용·한계를 같이 접으면 "정직하게 보이는 화면"만 남는다.
  const WARN = /산출 불가|미가용|미계산|경고|주의|불가능|forward_only|MOCK|재계산 필요/;
  let seenClosed = 0;
  await seed(page);

  for (const [path, label] of ROUTES) {
    await page.goto(path, { waitUntil: "networkidle" });
    const probe = await page.evaluate((src) => {
      const re = new RegExp(src);
      const bad: string[] = [];
      const closed = document.querySelectorAll("details:not([open])");
      closed.forEach((d) => {
        // ★`innerText` 를 쓰면 안 된다 — 이 가드가 처음에 가짜였던 이유★
        // 닫힌 <details> 의 본문은 **렌더되지 않으므로** innerText 가 빈 문자열이다.
        // 경고를 일부러 집어넣는 변이를 넣어도 초록이었다. `textContent` 는 숨은
        // 노드도 읽는다. (이번 세션에서 세 번째로 잡힌 "가드 모양의 무가드".)
        d.querySelectorAll("summary").forEach((s) => s.setAttribute("data-skip", "1"));
        let text = "";
        d.childNodes.forEach((n) => {
          if (n.nodeType === 1 && (n as Element).tagName === "SUMMARY") return;
          text += n.textContent ?? "";
        });
        if (re.test(text)) bad.push(text.trim().replace(/\s+/g, " ").slice(0, 70));
      });
      return { closed: closed.length, bad };
    }, WARN.source);
    expect(probe.bad, `${label}: 닫힌 details 안에 경고가 들어갔다`).toEqual([]);
    seenClosed += probe.closed;
  }
  // 닫힌 <details> 가 하나도 없으면 위 루프는 아무것도 검사하지 않은 것이다 —
  // 산문 접기 자체가 사라져도 초록일 수 있으므로 존재를 먼저 단언한다.
  expect(seenClosed, "닫힌 details 가 하나도 없다 — 검사 대상이 없었다").toBeGreaterThan(0);
});

for (const [path, label] of ROUTES) {
  test(`${label}: 12px 산문 · 11px 크롬 하한`, async ({ page }) => {
    await seed(page);
    await page.goto(path, { waitUntil: "networkidle" });
    const res = await page.locator(".aas-root").evaluate((root) => {
      const out: string[] = [];
      let checked = 0;
      for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
        checked++;
        const px = parseFloat(cs.fontSize);
        if (px < 11) out.push(`${el.tagName}.${(el.getAttribute("class") || "").split(" ")[0]} ${px}px :: ${(el.textContent || "").trim().slice(0, 18)}`);
      }
      return { checked, out: [...new Set(out)] };
    });
    expect(res.checked, "검사한 텍스트 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(20);
    expect(res.out, "11px 미만 텍스트").toEqual([]);
  });

  test(`${label}: 라이트·다크 양쪽 WCAG AA`, async ({ page }) => {
    // ★A4 는 `.aas-root` 를 다크에서만 쟀다★ 라이트를 재니 컨텍스트 스트립에서만
    // 모든 라우트 공통으로 4건이 나왔다 — 전부 채우기용 색을 글자로 쓴 경우였다.
    const AUDIT = contrastAudit(".aas-root");
    await seed(page);
    await page.goto(path, { waitUntil: "networkidle" });

    const light = await page.evaluate<AuditResult>(AUDIT);
    expect(light.checked, "라이트에서 검사한 노드 수").toBeGreaterThan(20);
    expect(light.low, `${label}: 라이트 AA 미달`).toEqual([]);

    await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.waitForTimeout(200);
    const dark = await page.evaluate<AuditResult>(AUDIT);
    expect(dark.checked, "다크에서 검사한 노드 수").toBeGreaterThan(20);
    expect(dark.low, `${label}: 다크 AA 미달`).toEqual([]);
    expect(dark.bright, `${label}: 다크인데 밝은 배경이 남아 있다`).toEqual([]);
  });
}
