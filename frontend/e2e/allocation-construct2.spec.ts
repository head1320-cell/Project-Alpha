import { test, expect, type Page } from "@playwright/test";
import { freezeCharts, contrastAudit, type AuditResult } from "./helpers";

// A12: Recharts 애니메이션만 끈다 — CSS 모션(§62/§63)은 그대로 둔다.
// `reducedMotion:'reduce'` 를 쓰면 CSS 까지 꺼져 모션 가드가 공허해진다.
test.beforeEach(async ({ page }) => { await freezeCharts(page); });


// ═══════════════════════════════════════════════════════════════════════════════
// A9 — 01 CONSTRUCT 컴포넌트 품질 (스테퍼 폭 · 배지 수렴 · 밀도)
// ─────────────────────────────────────────────────────────────────────────────
// ★이 파일에서 가장 값진 것은 1번(클리핑 가드)이다★
// 스테퍼는 `text-overflow: ellipsis` 때문에 **잘려도 정상처럼 보였다**. 실측 전까지
// 어떤 테스트도 이것을 잡지 못했고, 눈으로도 "라벨이 원래 짧은가 보다"로 읽혔다.
// A7 에서 클리핑 가드가 §57 을 통째로 지워도 초록이었던 전례가 있으므로,
// 이 가드는 **가로·세로 둘 다** 보고 **노드 수를 먼저 단언**한다.
//
// ★변이 프로브 결과 — 무엇이 실제로 지켜지는지 (전부 실행함)★
//   · `flex: var(--wiz-steps)` → `flex: 1`      ⇒ 3번 red (1·2번은 초록: 폭 배분과
//     클리핑은 **다른 것**을 지킨다. 이 사실 자체가 프로브로 드러났다)
//   · `min-width: 97px` → `0`                    ⇒ 1·2번 **초록** — 줄바꿈이 막고 있어서다
//   · `white-space: normal` → `nowrap+ellipsis`  ⇒ 1·2번 red (원래 결함 재현.
//     1280 에서 MACRO PHASE +27 · ATTRIBUTION +20 등 5개를 이름과 함께 지목했다)
//   · 배지 기하 갈라놓기                          ⇒ 5번 red
//   · Δ 에 `?? 0` 복원                            ⇒ 6번 red
//
// ★알려진 구멍 — 정직하게 적는다★
//   superseded 앰버 리터럴을 되돌리는 프로브에서 8번(대비)이 **초록으로 남았다**.
//   씨드된 상태에서는 superseded 스텝이 렌더되지 않아 감사가 그 노드를 보지 못한다.
//   즉 이 스펙은 superseded 표면의 다크 대비를 **지키지 못한다**. 고치려면 stale 상태를
//   강제로 만들어 감사해야 한다 — 다음 단계로 넘긴다. 가드가 있는 척하지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════

async function enterWithHoldings(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await expect(page.locator(".as-wrow").first()).toBeVisible({ timeout: 15_000 });
}

for (const w of [1280, 1440]) {
  test(`★스테퍼 라벨이 잘리지 않는다 @${w}★`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: 900 });
    await enterWithHoldings(page);

    const labs = page.locator(".aas-wiz-lab");
    // 셀렉터가 0개면 조용히 통과한다 — 이 저장소가 반복해 겪은 실패 모양이다.
    expect(await labs.count(), "라벨이 렌더돼야 검사가 성립한다").toBeGreaterThanOrEqual(9);

    const over = await labs.evaluateAll((els) =>
      els.map((e) => ({
        t: (e as HTMLElement).innerText,
        x: e.scrollWidth - e.clientWidth,
        y: e.scrollHeight - e.clientHeight,
      })).filter((r) => r.x > 1 || r.y > 1));
    expect(over, `잘린 라벨: ${JSON.stringify(over)}`).toEqual([]);

    // 부제도 같은 계약 (활성·superseded 스텝에만 렌더된다)
    const subs = page.locator(".aas-wiz-sub");
    expect(await subs.count(), "활성 스텝의 부제는 항상 있다").toBeGreaterThan(0);
    const subOver = await subs.evaluateAll((els) =>
      els.map((e) => ({ t: (e as HTMLElement).innerText, x: e.scrollWidth - e.clientWidth }))
        .filter((r) => r.x > 1));
    expect(subOver, `잘린 부제: ${JSON.stringify(subOver)}`).toEqual([]);
  });
}

test("★페이즈 폭이 스텝 수에 비례한다★ (반비례 회귀 가드)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await enterWithHoldings(page);

  const phases = await page.locator(".aas-wiz-phase").evaluateAll((els) =>
    els.map((p) => ({
      steps: p.querySelectorAll(".aas-wiz-step").length,
      width: p.getBoundingClientRect().width,
      stepW: (p.querySelector(".aas-wiz-step") as HTMLElement)?.getBoundingClientRect().width ?? 0,
    })));
  expect(phases.length, "3개 페이즈").toBe(3);

  // 예전 결함: 세 페이즈가 전부 flex:1 이라 스텝이 많을수록 스텝당 폭이 **좁아졌다**.
  // 이제 스텝 수가 많은 페이즈가 더 넓어야 한다.
  const sorted = [...phases].sort((a, b) => a.steps - b.steps);
  for (let i = 1; i < sorted.length; i++) {
    expect(sorted[i].width, `스텝 ${sorted[i].steps}개 페이즈가 ${sorted[i - 1].steps}개보다 넓어야 한다`)
      .toBeGreaterThan(sorted[i - 1].width);
  }
  // 그리고 스텝당 폭은 페이즈와 무관하게 고르다(±2px).
  const stepWs = phases.map((p) => p.stepW);
  expect(Math.max(...stepWs) - Math.min(...stepWs), "스텝 폭 편차").toBeLessThanOrEqual(2);
});

test("완료 스텝은 색만이 아니라 글리프·이름으로도 말한다", async ({ page }) => {
  await enterWithHoldings(page);
  const marks = page.locator(".aas-wiz-mark");
  expect(await marks.count(), "번호 마커가 스텝마다 있다").toBeGreaterThanOrEqual(9);

  const done = page.locator(".aas-wiz-step.done").first();
  if (await done.count()) {
    // 색각 이상 사용자에게도 완료가 전달되어야 한다 (WCAG: 색만으로 의미 전달 금지)
    await expect(done.locator("svg, .sr-only")).toHaveCount(2);
  }
});

test("★상태 배지 기하가 하나로 수렴한다★", async ({ page }) => {
  await enterWithHoldings(page);
  // 실측 전: regime(3px 8px/r2/h26.4) · mode(2px 6px/r2/h20.4) · stale(2px 7px/r4/h20.4)
  const geo = await page.evaluate(() =>
    [".as-ctx-regime", ".as-ctx-mode"]
      .map((s) => {
        const el = document.querySelector(s);
        if (!el) return null;
        const cs = getComputedStyle(el);
        return { s, pad: `${cs.paddingTop}/${cs.paddingLeft}`, r: cs.borderRadius };
      })
      .filter(Boolean) as { s: string; pad: string; r: string }[]);

  expect(geo.length, "비교할 칩이 2개 이상 렌더돼야 한다").toBeGreaterThanOrEqual(2);
  const pads = new Set(geo.map((g) => g.pad));
  const radii = new Set(geo.map((g) => g.r));
  expect([...pads], `패딩이 갈린다: ${JSON.stringify(geo)}`).toHaveLength(1);
  expect([...radii], `모서리가 갈린다: ${JSON.stringify(geo)}`).toHaveLength(1);
});

test("★Δ 칩은 미계산을 0.0 으로 위장하지 않는다★", async ({ page }) => {
  await enterWithHoldings(page);
  // 최적화 실행 전 상태 — 이 화면이 A3 에서 세운 규칙(0 ≠ 미계산)의 연장이다.
  const rows = page.locator(".as-wrow");
  expect(await rows.count(), "보유 행이 있어야 한다").toBeGreaterThan(0);

  const hasResult = await page.locator(".as-cov").count();
  if (!hasResult) {
    expect(await page.locator(".as-w-delta").count(),
      "결과가 없으면 Δ 칩 자체가 없어야 한다 (0.0%p 를 그리지 않는다)").toBe(0);
    expect(await page.locator(".as-wrow-head-d").count(),
      "Δ 열 머리글도 결과가 있을 때만").toBe(0);
  }
  // 열 머리글은 보유가 있으면 항상
  await expect(page.locator(".as-wrow-head")).toBeVisible();
});

test("타입 하한 — 산문 12px · 크롬 11px", async ({ page }) => {
  await enterWithHoldings(page);
  for (const sel of [".aas-wiz-lab", ".aas-wiz-mark", ".as-stat-x", ".as-w-unit", ".as-stat-k"]) {
    const nodes = page.locator(sel);
    expect(await nodes.count(), `${sel} 가 렌더돼야 검사가 성립한다`).toBeGreaterThan(0);
    const sizes = await nodes.evaluateAll((els) =>
      els.map((e) => parseFloat(getComputedStyle(e).fontSize)));
    for (const px of sizes) expect(px, `${sel} 하한 11px`).toBeGreaterThanOrEqual(11);
  }
});

test("대비 — 라이트/다크 AA (스테퍼·배지·밀도 표면 전부)", async ({ page }) => {
  const AUDIT = contrastAudit(".aas-root");
  await enterWithHoldings(page);

  const light = await page.evaluate<AuditResult>(AUDIT);
  expect(light.checked, "라이트에서 검사한 텍스트 노드 수").toBeGreaterThan(20);
  expect(light.low, `라이트 AA 미달: ${JSON.stringify(light.low.slice(0, 6))}`).toHaveLength(0);

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  // ★전이가 끝나기를 기다린다★ Badge·Button 은 `transition-colors` 를 갖고 있어서
  // 클래스를 붙인 직후에 읽으면 **전이 중간값**이 잡힌다. 첫 실행에서 실제로 그랬다:
  // CAUTIOUS 칩이 rgb(154,100,25)(라이트 #854d0e ↔ 다크 #fcd34d 의 중간), 버튼이
  // rgb(58,58,58)(#111 ↔ #fafafa 의 중간)로 읽혀 AA 미달 5건이 났다. 제품 결함이
  // 아니라 **측정 시점 결함**이었다 — allocation-construct.spec.ts:140 이 같은 이유로
  // 이미 200ms 를 기다리고 있었다.
  await page.waitForTimeout(200);
  const dark = await page.evaluate<AuditResult>(AUDIT);
  expect(dark.checked, "다크에서 검사한 텍스트 노드 수").toBeGreaterThan(20);
  expect(dark.low, `다크 AA 미달: ${JSON.stringify(dark.low.slice(0, 6))}`).toHaveLength(0);
  // 라이트 전용 리터럴이 남아 있으면 여기서 밝은 배경으로 새어 나온다.
  expect(dark.bright, `다크 밝은 배경 누출: ${JSON.stringify(dark.bright.slice(0, 6))}`).toHaveLength(0);
});

// ═══════════════════════════════════════════════════════════════════════════════
// A10 — 그래픽 패스 가드 (모듈러 스케일 · 4px 리듬 · 엘리베이션)
// ─────────────────────────────────────────────────────────────────────────────
// ★가드를 대상 표면으로 한정한다★ 앱 전체는 padding 36종 · gap 24종이라 전역으로
// 걸면 이 단계가 손대지 않은 곳에서 빨개진다. A10 이 재정렬한 클래스만 본다 —
// 지키지도 않을 범위를 단언하는 것은 가드가 아니라 소음이다.
const A10_SURFACE = [".as-card", ".as-stat", ".aas-wiz", ".aas-wiz-step", ".aas-wiz-phase", ".as-ctx"];

test("★간격이 4px 그리드에 놓인다★", async ({ page }) => {
  await enterWithHoldings(page);
  const bad = await page.evaluate((sels) => {
    const out: string[] = [];
    let n = 0;
    for (const s of sels) {
      for (const el of document.querySelectorAll(s)) {
        n++;
        const cs = getComputedStyle(el);
        for (const p of ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "rowGap", "columnGap"]) {
          const v = parseFloat(cs[p as keyof CSSStyleDeclaration] as string);
          if (Number.isFinite(v) && v > 0 && v % 4 !== 0) out.push(`${s} ${p}=${v}px`);
        }
      }
    }
    return { n, out: [...new Set(out)] };
  }, A10_SURFACE);

  expect(bad.n, "대상 노드가 렌더돼야 검사가 성립한다").toBeGreaterThan(5);
  expect(bad.out, `4의 배수를 벗어난 간격: ${JSON.stringify(bad.out)}`).toEqual([]);
});

test("★글자 크기가 모듈러 스케일 안에 있다★", async ({ page }) => {
  await enterWithHoldings(page);
  const SCALE = [11, 12, 13, 14, 16, 18, 22, 28];
  const bad = await page.evaluate((scale) => {
    const sels = [".as-card-title", ".as-note-inline", ".as-note", ".as-stat-k", ".as-stat-v",
                  ".as-empty", ".aas-wiz-lab", ".aas-wiz-sub", ".aas-wiz-mark"];
    const out: string[] = [];
    let n = 0;
    for (const s of sels) {
      for (const el of document.querySelectorAll(s)) {
        n++;
        const px = parseFloat(getComputedStyle(el).fontSize);
        if (!scale.includes(px)) out.push(`${s} ${px}px`);
      }
    }
    return { n, out: [...new Set(out)] };
  }, SCALE);

  expect(bad.n, "대상 노드가 렌더돼야 한다").toBeGreaterThan(5);
  expect(bad.out, `스케일 밖 크기: ${JSON.stringify(bad.out)}`).toEqual([]);
});

test("엘리베이션은 2단뿐 — 일회성 그림자 없음", async ({ page }) => {
  await enterWithHoldings(page);
  const shadows = await page.evaluate(() =>
    [...document.querySelectorAll(".as-card, .as-stat")]
      .map((e) => getComputedStyle(e).boxShadow)
      .filter((v, i, a) => a.indexOf(v) === i));
  expect(shadows.length, "그림자를 읽을 노드가 있어야 한다").toBeGreaterThan(0);
  // --elev-1 만 쓰거나 none. 세 종류 이상이면 스케일이 다시 흩어진 것이다.
  expect(shadows.length, `그림자 종류: ${JSON.stringify(shadows)}`).toBeLessThanOrEqual(2);
});

// ═══════════════════════════════════════════════════════════════════════════════
// A11 — Phase 1 잔여 색 토큰 + Construct 모션 파일럿
// ─────────────────────────────────────────────────────────────────────────────
// ★1번이 이 블록에서 가장 값진 가드다★ `animation: … both` 는 reduced-motion 에서
// 애니메이션만 끄면 **시작 프레임(opacity:0)에 붙들려 콘텐츠가 사라진다**. 눈으로는
// "빈 화면" 이고 어떤 기능 테스트도 빨개지지 않는다 — 랜딩 §46 이 같은 함정을 기록해
// 두었고, 여기서도 같은 방식으로 막았는지 기계로 확인한다.
// ═══════════════════════════════════════════════════════════════════════════════

test("★reduced-motion 에서 사라지는 요소가 없다★", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await enterWithHoldings(page);

  const faded = await page.evaluate(() => {
    const out: string[] = [];
    let n = 0;
    for (const el of document.querySelectorAll(".as-ws2 .as-card, .as-ws2 .aas-map, .as-ws2 .as-conc-bar > i")) {
      n++;
      const cs = getComputedStyle(el);
      const op = parseFloat(cs.opacity);
      if (op < 0.99) out.push(`${el.className} opacity=${op}`);
      // scaleX(0) 에 붙들리면 폭이 0 이 된다 — opacity 만 보면 놓친다.
      if (el.getBoundingClientRect().width < 1) out.push(`${el.className} width=0`);
    }
    return { n, out };
  });
  expect(faded.n, "모션 대상 노드가 렌더돼야 검사가 성립한다").toBeGreaterThan(2);
  expect(faded.out, `reduced-motion 에서 숨겨진 요소: ${JSON.stringify(faded.out)}`).toEqual([]);
});

test("★숫자는 첫 페인트부터 최종값이다 (카운트업 금지)★", async ({ page }) => {
  await enterWithHoldings(page);
  // L2 전례: CountUp 이 1.1초 동안 틀린 숫자를 보여 줬고 스크린샷에 그게 남았다.
  const read = () => page.locator(".as-stat-v").allTextContents();
  const first = await read();
  expect(first.length, "지표 값이 렌더돼야 한다").toBeGreaterThan(2);
  await page.waitForTimeout(900);
  expect(await read(), "숫자가 시간에 따라 변한다 — 카운트업이 들어왔다").toEqual(first);
});

test("전이 시간이 모션 토큰 범위 안이다", async ({ page }) => {
  await enterWithHoldings(page);
  const bad = await page.evaluate(() => {
    const ALLOWED = [0, 0.12, 0.18, 0.26];
    const out: string[] = [];
    let n = 0;
    for (const el of document.querySelectorAll(".as-ws2 .as-card, .as-ws2 .as-wrow, .as-ws2 .as-stat")) {
      n++;
      for (const d of getComputedStyle(el).transitionDuration.split(",")) {
        const v = parseFloat(d);
        if (Number.isFinite(v) && !ALLOWED.some((a) => Math.abs(a - v) < 0.001)) {
          out.push(`${el.className} ${v}s`);
        }
      }
    }
    return { n, out: [...new Set(out)] };
  });
  expect(bad.n).toBeGreaterThan(2);
  expect(bad.out, `토큰 밖 전이 시간: ${JSON.stringify(bad.out)}`).toEqual([]);
});

test("Phase 1 색 토큰이 적용됐다", async ({ page }) => {
  await enterWithHoldings(page);
  const t = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const g = (k: string) => cs.getPropertyValue(k).trim();
    return {
      destructive: g("--destructive"),
      secondary: g("--secondary"),
      card: g("--card"),
      warnFg: g("--warn-fg"),
      warnMark: g("--warn-mark"),
      tint: g("--brand-tint"),
    };
  });
  // ③ 빨강은 하나 — 예전엔 폴백이 안 먹어 #dc3545 가 나갔다.
  expect(t.destructive.toLowerCase(), "destructive 통일").toBe("#dc2626");
  // ② Secondary 가 Surface 와 달라야 분리된 것이다.
  expect(t.secondary, "Secondary 가 카드 표면과 갈렸다").not.toBe(t.card);
  // ④ 칠하는 앰버와 읽는 앰버가 서로 다른 값이어야 분리가 성립한다.
  expect(t.warnFg, "warn-fg 정의됨").not.toBe("");
  expect(t.warnMark, "warn-mark 정의됨").not.toBe("");
  expect(t.warnFg, "읽는 앰버와 칠하는 앰버는 달라야 한다").not.toBe(t.warnMark);
  // ① 램프
  expect(t.tint, "액센트 램프 정의됨").toContain("rgb");
});
