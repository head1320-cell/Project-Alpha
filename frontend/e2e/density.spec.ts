import { test, expect, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * 단 · 밀도 장치 — 실제 브라우저에서 (ADR 007 §3 · §7 · 계획 `docs/superpowers/plans/2026-11-20-uiux-u0-foundation.md` §2)
 * ──────────────────────────────────────────────────────────────────────────
 * 거는 것:
 *  · 토큰의 값: 견본 상자에 속성을 달면 줄 · 칸 · 글자 · 조작 높이 · 절 간격이 ADR 의 표대로 나온다(짝: 속성이 없으면 넉넉 기본값).
 *  · 단의 반경 · 단 안의 수는 본문 글꼴(짝: 단 밖의 `.num` 은 지금 그대로 고정폭 글꼴).
 *  · 강조는 잉크 — 라이트 · 안쪽 다크 상자 모두(짝: 강조 ≠ 하락색).
 *  · 개발 견본 경로 `/dev/density`: 첫 그림 전 조각이 속성을 달고(스크립트 청크를 막아도) 맞춤 훅이 같은 답을 유지한다.
 *  · ★끄면 그대로★ — 다른 화면으로 가면 속성이 떨어지고, 제품 경로는 저장값이 있어도 속성이 없다.
 * 한계: 손가락 화면은 Chromium 의 흉내(터치 맥락)로 본다 — 실제 기기가 아니다.
 */

const BOX = (tier: string, density: string, dark = false) =>
  `.devui-dn-box[data-tier="${tier}"][data-density="${density}"]${dark ? ".dark" : ":not(.dark)"}`;

type Metrics = { rowH: number; cellX: number; fsTable: number; fsTh: number; ctlH: number; inputH: number; padSec: number; gapSec: number; rSec: number; rRow: number };

async function metrics(page: Page, sel: string): Promise<Metrics> {
  return page.locator(sel).first().evaluate((box) => {
    const q = (s: string) => box.querySelector(s) as HTMLElement;
    const cs = (e: Element) => getComputedStyle(e);
    const secs = box.querySelectorAll(".devui-dn-sec");
    const sec = secs[0] as HTMLElement, td = q(".devui-dn-table tbody td"), th = q(".devui-dn-table thead th"), btn = q(".devui-dn-btn");
    return {
      rowH: q(".devui-dn-table tbody tr").getBoundingClientRect().height,
      cellX: parseFloat(cs(td).paddingLeft),
      fsTable: parseFloat(cs(td).fontSize),
      fsTh: parseFloat(cs(th).fontSize),
      ctlH: btn.getBoundingClientRect().height,
      inputH: q(".devui-dn-input").getBoundingClientRect().height,
      padSec: parseFloat(cs(sec).paddingTop),
      gapSec: secs[1].getBoundingClientRect().top - sec.getBoundingClientRect().bottom,
      rSec: parseFloat(cs(sec).borderTopLeftRadius),
      rRow: parseFloat(cs(btn).borderTopLeftRadius),
    };
  });
}

const WANT: Record<string, Omit<Metrics, "rSec" | "rRow">> = {
  compact: { rowH: 28, cellX: 8, fsTable: 12, fsTh: 11, ctlH: 26, inputH: 26, padSec: 12, gapSec: 8 },
  regular: { rowH: 34, cellX: 12, fsTable: 13, fsTh: 12, ctlH: 30, inputH: 30, padSec: 16, gapSec: 16 },
  comfortable: { rowH: 44, cellX: 16, fsTable: 14, fsTh: 13, ctlH: 40, inputH: 40, padSec: 24, gapSec: 24 },
};

const htmlAttrs = (page: Page) =>
  page.evaluate(() => [document.documentElement.getAttribute("data-tier"), document.documentElement.getAttribute("data-density")]);

async function openCatalogue(page: Page) {
  await page.goto("/dev/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".devui-dn")).toBeVisible({ timeout: 20_000 });
}

test.describe("견본 상자 — 토큰의 값", () => {
  test("밀도 셋: 줄 28 · 34 · 44px · 칸 여백 · 글자 · 조작 높이 · 절 안 · 절 사이가 ADR 의 표와 같다 (라이트 · 안쪽 다크 상자 모두)", async ({ page }) => {
    await openCatalogue(page);
    for (const dark of [false, true]) {
      for (const d of ["compact", "regular", "comfortable"]) {
        const m = await metrics(page, BOX("work", d, dark));
        const { rSec, rRow, ...rest } = m;
        expect(rest, `${d}${dark ? " 다크" : ""}`).toEqual(WANT[d]);
        expect([rSec, rRow], "작업 단의 반경").toEqual([4, 2]);
      }
    }
  });

  test("짝: 속성이 없는 상자는 넉넉 기본값이다(밀도 토큰의 뿌리 값) · 반경은 지금 값(절 20 · 행 12)", async ({ page }) => {
    await openCatalogue(page);
    const box = ".devui-dn-box.devui-dn-bare";
    await expect(page.locator(box)).toHaveCount(1);
    expect(await page.locator(box).evaluate((e) => [e.hasAttribute("data-tier"), e.hasAttribute("data-density")])).toEqual([false, false]);
    const { rSec, rRow, ...rest } = await metrics(page, box);
    expect(rest).toEqual(WANT.comfortable);
    expect([rSec, rRow]).toEqual([20, 12]);
  });

  test("견본의 꼴: 값 없음(N/A + 사유) 줄까지 모든 줄이 한 높이다 · 표가 제 절을 넘치지 않는다 (상자 아홉 — 스크린샷 검수가 잡은 것을 못 박는다)", async ({ page }) => {
    await openCatalogue(page);
    const boxes = page.locator(".devui-dn .devui-dn-box");
    await expect(boxes).toHaveCount(9);
    const got = await boxes.evaluateAll((els) => els.map((box) => {
      const sec = box.querySelectorAll(".devui-dn-sec")[1] as HTMLElement;
      return {
        label: `${box.querySelector(".devui-dn-cap-t")?.textContent}${box.classList.contains("dark") ? " 다크" : ""}`,
        rows: [...box.querySelectorAll(".devui-dn-table tbody tr")].map((r) => r.getBoundingClientRect().height),
        over: sec.scrollWidth - sec.clientWidth,
        unknown: box.querySelector(".devui-dn-table tbody tr:last-child .tx-unknown")?.textContent ?? "",
      };
    }));
    for (const g of got) {
      expect(g.unknown, `${g.label}: 마지막 줄이 값 없음 줄이어야 이 시험이 뜻이 있다`).toContain("N/A");
      expect(g.rows.length, g.label).toBe(4);
      expect(new Set(g.rows).size, `${g.label}: 줄 높이가 서로 다르다 ${g.rows.join(" · ")}`).toBe(1);
      expect(g.over, `${g.label}: 표가 절보다 ${g.over}px 넓다`).toBeLessThanOrEqual(0);
    }
  });

  test("단의 반경: 작업 4 · 2 / 해석 12 · 8 / 설명 20 · 12px — 밀도와 따로 움직인다", async ({ page }) => {
    await openCatalogue(page);
    const r = async (tier: string, density: string) => { const m = await metrics(page, BOX(tier, density)); return [m.rSec, m.rRow, m.rowH]; };
    expect(await r("work", "compact")).toEqual([4, 2, 28]);
    expect(await r("read", "regular")).toEqual([12, 8, 34]);
    expect(await r("present", "comfortable")).toEqual([20, 12, 44]);
    expect(await r("work", "comfortable")).toEqual([4, 2, 44]);         // 밀도를 바꿔도 단의 반경은 그대로
  });

  test("단 안의 수는 본문 글꼴 + 고정폭 숫자 ↔ 단 밖의 .num 은 지금 그대로 고정폭 글꼴", async ({ page }) => {
    await openCatalogue(page);
    const font = (sel: string) => page.locator(sel).first().evaluate((e) => { const c = getComputedStyle(e); return [c.fontFamily.split(",")[0].replace(/["']/g, "").trim(), c.fontVariantNumeric]; });
    for (const tier of ["work", "read", "present"]) {
      const d = tier === "work" ? "compact" : tier === "read" ? "regular" : "comfortable";
      const [family, variant] = await font(`${BOX(tier, d)} td.num`);
      expect(family, tier).toBe("Pretendard Variable");
      expect(variant, tier).toContain("tabular-nums");
    }
    const [outFamily, outVariant] = await font(".devui-dn-out.num");
    expect(outFamily).toMatch(/^JetBrains Mono/);
    expect(outVariant).toContain("tabular-nums");
    // 수 칸은 오른쪽 맞춤 · 식별자(종목 코드)는 고정폭 글꼴 + 왼쪽 맞춤(ADR 007 §5 의 예외)
    expect(await page.locator(`${BOX("work", "compact")} td.num`).first().evaluate((e) => getComputedStyle(e).textAlign)).toBe("right");
    const code = await page.locator(`${BOX("work", "compact")} .devui-dn-code`).first().evaluate((e) => getComputedStyle(e).fontFamily);
    expect(code).toMatch(/^"?JetBrains Mono/);
  });

  test("강조는 잉크다 — 주 단추 · 초점 고리가 그 범위의 잉크(라이트 · 다크) ↔ 하락색 · 링크는 파랑으로 남는다", async ({ page }) => {
    await openCatalogue(page);
    const read = (dark: boolean) => page.locator(BOX("work", "compact", dark)).evaluate((box) => {
      const c = (s: string, p: "color" | "backgroundColor") => getComputedStyle(box.querySelector(s) as Element)[p];
      return { btnBg: c(".devui-dn-btn--primary", "backgroundColor"), btnFg: c(".devui-dn-btn--primary", "color"),
        down: c(".devui-dn-down", "color"), up: c(".devui-dn-up", "color"), link: c(".devui-dn-link", "color") };
    });
    const light = await read(false), dark = await read(true);
    expect(light).toEqual({ btnBg: "rgb(25, 31, 40)", btnFg: "rgb(255, 255, 255)", down: "rgb(27, 100, 218)", up: "rgb(210, 42, 59)", link: "rgb(27, 100, 218)" });
    expect(dark).toEqual({ btnBg: "rgb(242, 244, 246)", btnFg: "rgb(26, 32, 41)", down: "rgb(77, 148, 255)", up: "rgb(255, 107, 118)", link: "rgb(138, 184, 255)" });
    for (const t of [light, dark]) { expect(t.btnBg).not.toBe(t.down); expect(t.btnBg).not.toBe(t.up); }   // 강조의 값이 등락색과 겹치지 않는다
    // 초점 고리 — 자판 초점에서 잉크 2px 가 곧바로 선다(전환 없음)
    for (const isDark of [false, true]) {
      const btn = page.locator(`${BOX("work", "compact", isDark)} .devui-dn-btn--primary`);
      await btn.focus();
      const ring = await btn.evaluate((e) => { const c = getComputedStyle(e); return { on: e.matches(":focus-visible"), style: c.outlineStyle, width: c.outlineWidth, color: c.outlineColor, dur: c.transitionDuration, prop: c.transitionProperty }; });
      expect(ring.on, "자판 초점으로 본다").toBe(true);
      expect([ring.style, ring.width, ring.color]).toEqual(["solid", "2px", isDark ? "rgb(242, 244, 246)" : "rgb(25, 31, 40)"]);
      expect(ring.prop === "none" || ring.dur.split(",").every((d) => parseFloat(d) === 0) || !/all|outline/.test(ring.prop), `전환이 고리를 늦추지 않는다(${ring.prop} ${ring.dur})`).toBe(true);
    }
  });

  test("대비: 밀도 셋 × 라이트 · 다크 견본의 글자가 모두 AA · 합성 표시는 어느 밀도에서도 보인다 · 촘촘한 견본의 누르는 것은 24px 이상", async ({ page }) => {
    await openCatalogue(page);
    for (const dark of [false, true]) {
      for (const d of ["compact", "regular", "comfortable"]) {
        const sel = BOX("work", d, dark);
        const a = (await page.evaluate(contrastAudit(sel))) as AuditResult;
        expect(a.checked, sel).toBeGreaterThan(15);
        expect(a.low, sel).toEqual([]);
        if (dark) expect(a.bright.filter((x) => !x.includes("devui-dn-btn--primary")), `${sel} — 다크에 밝은 바탕(잉크 주 단추만 뒤집힌다)`).toEqual([]);
        const chip = page.locator(`${sel} .devui-dn-chip`).first();
        await expect(chip).toBeVisible();
        await expect(chip).toHaveText("합성");
      }
    }
    const small = await page.locator(`${BOX("work", "compact")}`).evaluate((box) =>
      [...box.querySelectorAll("button, input, a")].map((e) => { const r = e.getBoundingClientRect(); return [e.className, Math.round(r.width), Math.round(r.height)] as const; })
        .filter(([, w, h]) => w < 24 || h < 24));
    expect(small).toEqual([]);
  });
});

test.describe("개발 견본 경로 /dev/density — 첫 그림 전 조각과 맞춤 훅", () => {
  const open = async (page: Page) => {
    await page.goto("/dev/density", { waitUntil: "domcontentloaded" });
    await expect(page.locator(".devui-dn-state")).toHaveAttribute("data-ready", "1", { timeout: 20_000 });   // 수화가 끝났다
  };

  test("저장값이 없으면 작업 단 · 촘촘 — 속성이 html 에 붙고 화면의 줄이 28px 이다", async ({ page }) => {
    await open(page);
    expect(await htmlAttrs(page)).toEqual(["work", "compact"]);
    await expect(page.locator(".devui-dn-state")).toHaveText("작업 단 · 촘촘");
    const box = ".devui-dn-page .devui-dn-box";
    expect(await page.locator(box).evaluate((e) => [e.hasAttribute("data-tier"), e.hasAttribute("data-density")]), "이 상자에는 속성이 없다 — 값은 html 에서 내려온다").toEqual([false, false]);
    const { rSec, rRow, ...rest } = await metrics(page, box);
    expect(rest).toEqual(WANT.compact);
    expect([rSec, rRow]).toEqual([4, 2]);
  });

  for (const [stored, want, label] of [["regular", "regular", "작업 단 · 보통"], ["comfortable", "comfortable", "작업 단 · 넉넉"], ["compact", "compact", "작업 단 · 촘촘"], ["junk", "compact", "작업 단 · 촘촘"]] as const) {
    test(`저장값 ${stored} → ${want}(모르는 값은 자동)`, async ({ page }) => {
      await page.addInitScript((v) => localStorage.setItem("alpha_density", v), stored);
      await open(page);
      expect(await htmlAttrs(page)).toEqual(["work", want]);
      await expect(page.locator(".devui-dn-state")).toHaveText(label);
      const m = await metrics(page, ".devui-dn-page .devui-dn-box");
      expect(m.rowH).toBe(WANT[want].rowH);
    });
  }

  test("★스크립트 청크를 막아도 속성이 붙는다★ — 첫 그림 전 조각이 한 일이다(React 는 돌지 않았다)", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("alpha_density", "regular"));
    await page.route("**/_next/static/**/*.js", (r) => r.abort());
    await page.goto("/dev/density", { waitUntil: "domcontentloaded" });
    expect(await htmlAttrs(page)).toEqual(["work", "regular"]);
    await page.waitForTimeout(800);
    await expect(page.locator(".devui-dn-state")).toHaveAttribute("data-ready", "0");    // 수화되지 않았다
    expect(await htmlAttrs(page)).toEqual(["work", "regular"]);
    expect((await metrics(page, ".devui-dn-page .devui-dn-box")).rowH).toBe(34);         // 서버가 그린 표가 조각의 값으로 그려진다
  });

  test("손가락 화면은 저장값이 촘촘이어도 넉넉이다 ↔ 같은 저장값의 마우스 화면은 촘촘", async ({ page, browser }) => {
    const ctx = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width: 820, height: 1180 },
      storageState: { cookies: [], origins: [{ origin: "http://localhost:3000", localStorage: [{ name: "alpha_density", value: "compact" }] }] } });
    const touch = await ctx.newPage();
    await touch.goto("/dev/density", { waitUntil: "domcontentloaded" });
    expect(await touch.evaluate(() => matchMedia("(pointer: coarse)").matches), "이 맥락이 손가락 화면으로 보여야 시험이 뜻이 있다").toBe(true);
    expect(await htmlAttrs(touch)).toEqual(["work", "comfortable"]);
    await expect(touch.locator(".devui-dn-state")).toHaveAttribute("data-ready", "1", { timeout: 20_000 });
    expect(await htmlAttrs(touch), "수화 뒤에도 같다(훅이 조각과 같은 답)").toEqual(["work", "comfortable"]);
    expect((await metrics(touch, ".devui-dn-page .devui-dn-box")).rowH).toBe(44);
    await ctx.close();
    await page.addInitScript(() => localStorage.setItem("alpha_density", "compact"));
    await open(page);
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(false);
    expect(await htmlAttrs(page)).toEqual(["work", "compact"]);
  });

  test("좁은 손가락 화면(390px): 쪽은 가로로 밀리지 않는다 · 절보다 넓은 표는 절 안에서 밀어 끝 칸까지 본다", async ({ browser }) => {
    const ctx = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });
    const p = await ctx.newPage();
    await p.goto("/dev/density", { waitUntil: "domcontentloaded" });
    await expect(p.locator(".devui-dn-state")).toHaveAttribute("data-ready", "1", { timeout: 20_000 });
    expect(await htmlAttrs(p)).toEqual(["work", "comfortable"]);
    expect(await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), "쪽의 가로 넘침").toBeLessThanOrEqual(0);
    const edge = await p.locator(".devui-dn-page .devui-dn-box").evaluate((box) => {
      const sec = box.querySelectorAll(".devui-dn-sec")[1] as HTMLElement;
      const before = sec.scrollWidth - sec.clientWidth;
      sec.scrollLeft = sec.scrollWidth;
      const last = box.querySelector(".devui-dn-table thead th:last-child") as HTMLElement;
      // 값 없음 칸: 값(N/A)과 사유가 한 줄에 나란한가 — 접히면 사유가 값 아래로 내려가 왼쪽 끝이 값의 오른쪽 끝보다 앞선다.
      // (넉넉의 44px 줄은 두 줄 글자를 담고도 높이가 그대로라, 줄 높이로는 접힘을 보지 못한다 — 변이가 살아남아 알았다.)
      const v = box.querySelector(".devui-dn-table .tx-unknown-v") as HTMLElement, why = box.querySelector(".devui-dn-table .tx-unknown-why") as HTMLElement;
      return { before, moved: sec.scrollLeft, gap: sec.getBoundingClientRect().right - last.getBoundingClientRect().right,
        side: why.getBoundingClientRect().left - v.getBoundingClientRect().right };
    });
    expect(edge.before, "이 너비에서 표가 절보다 넓어야 이 시험이 뜻이 있다").toBeGreaterThan(0);
    expect(edge.side, "표가 눌려도 값 없음(N/A + 사유)이 두 줄로 접히지 않는다").toBeGreaterThanOrEqual(0);
    expect(edge.moved, "절이 가로로 밀린다").toBeGreaterThan(0);
    expect(edge.gap, "끝까지 밀면 마지막 칸이 절 안에 있다").toBeGreaterThanOrEqual(0);
    await ctx.close();
  });

  test("★단 · 밀도 속성은 셸 크롬(머리 줄 · 메뉴)의 계산 스타일을 바꾸지 않는다★ — 속성을 떼어도 셸은 한 값도 달라지지 않는다 ↔ 본문의 견본은 달라진다", async ({ page }) => {
    await open(page);
    // 속성은 html 에 있어 셸 크롬도 범위 안이다 — 셸의 규칙이 단이 바꾸는 토큰(밀도 · 반경 · 단 안의 .num)을 읽기 시작하면 여기서 걸린다.
    const snap = () => page.evaluate(() => {
      const PROPS = ["fontFamily", "fontSize", "fontWeight", "lineHeight", "color", "backgroundColor", "borderTopLeftRadius", "borderBottomRightRadius",
        "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "marginTop", "marginBottom", "height", "width", "gap", "fontVariantNumeric", "zIndex"] as const;
      const out: string[] = [];
      for (const root of document.querySelectorAll(".terminal-header, .terminal-sidebar")) {
        for (const el of [root, ...root.querySelectorAll("*")]) {
          const cs = getComputedStyle(el);
          out.push(`${el.tagName}.${el.getAttribute("class") ?? ""}|` + PROPS.map((p) => cs[p]).join("|"));
        }
      }
      return out;
    });
    const withTier = await snap();
    expect(withTier.length, "셸 크롬의 요소를 실제로 쟀다").toBeGreaterThan(40);
    const rowWith = (await metrics(page, ".devui-dn-page .devui-dn-box")).rowH;
    await page.evaluate(() => { document.documentElement.removeAttribute("data-tier"); document.documentElement.removeAttribute("data-density"); });
    const without = await snap();
    const rowWithout = (await metrics(page, ".devui-dn-page .devui-dn-box")).rowH;
    expect(without).toEqual(withTier);
    expect([rowWith, rowWithout], "짝: 같은 조작이 본문의 견본은 바꾼다(촘촘 28 → 기본값 44)").toEqual([28, 44]);
  });

  test("★화면 사이 이동: 제품 화면으로 가면 속성이 떨어지고 돌아오면 다시 붙는다★(새로 고침 없이)", async ({ page }) => {
    await open(page);
    expect(await htmlAttrs(page)).toEqual(["work", "compact"]);
    await page.evaluate(() => { (window as unknown as { __noReload: number }).__noReload = 1; });
    await page.locator('.terminal-nav a[href="/screener"]').click();
    await expect(page).toHaveURL(/\/screener$/);
    await expect(page.locator(".terminal-main")).toBeVisible();
    await expect.poll(() => htmlAttrs(page)).toEqual([null, null]);
    expect(await page.evaluate(() => (window as unknown as { __noReload?: number }).__noReload), "문서를 다시 받지 않았다(화면 안 이동)").toBe(1);
    await page.goBack();
    await expect(page).toHaveURL(/\/dev\/density$/);
    await expect.poll(() => htmlAttrs(page)).toEqual(["work", "compact"]);
    expect(await page.evaluate(() => (window as unknown as { __noReload?: number }).__noReload)).toBe(1);
  });
});

test("★끄면 그대로 — 제품 경로는 저장값이 있어도 속성이 없다★ (첫 그림 전 · 수화 뒤 모두)", async ({ page }) => {
  test.setTimeout(240_000);
  await page.addInitScript(() => localStorage.setItem("alpha_density", "compact"));
  const paths = ["/", "/login", "/c", "/dashboard", "/screener", "/backtest", "/backtest/intraday", "/macro", "/insights", "/risk-tools", "/derivatives",
    "/allocation", "/my-account", "/my-account/journal", "/clients", "/settings", "/admin/data", "/admin/live-trading", "/dev/ui"];
  const seen: Record<string, unknown> = {};
  for (const p of paths) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const early = await htmlAttrs(page);
    await page.waitForLoadState("load");
    await page.waitForTimeout(400);                                    // 수화 · 훅의 첫 효과
    seen[p] = [early, await htmlAttrs(page), await page.evaluate(() => localStorage.getItem("alpha_density"))];
  }
  expect(seen).toEqual(Object.fromEntries(paths.map((p) => [p, [[null, null], [null, null], "compact"]])));
});
