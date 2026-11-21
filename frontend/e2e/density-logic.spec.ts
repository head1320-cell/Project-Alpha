import { test, expect } from "./fixtures";
import {
  DENSITY_BOOT, DENSITY_KEY, TIER_DEFAULT, TIER_ROUTES, applyDensity, densityBoot, parsePref, resolveDensity, tierRoute,
  type DensityState, type TierRoute,
} from "../src/shared/ui/density/density";

/**
 * 단 · 밀도 장치의 순수 규칙(브라우저 없이) — ADR 007 §7 · 계획 `docs/superpowers/plans/2026-11-20-uiux-u0-foundation.md` §2.1
 *  · 밀도를 정하는 차례: 표에 없는 경로 → 속성 없음 · 고객에게 보이는 화면(lock) → 넉넉 · 손가락 화면 → 넉넉 · 저장값 · 단의 기본값.
 *  · 첫 그림 전에 도는 조각은 ★같은 입력에 순수 함수와 같은 답★을 낸다(둘이 갈리면 화면이 그려진 뒤 밀도가 바뀐다).
 *  · ★제품 경로는 경로 표에 없다★ — 화면 조각이 경로를 더할 때 아래 허용 목록을 같은 커밋에서 고친다.
 */

const T: TierRoute[] = [
  { pattern: /^\/w\/?$/, tier: "work", label: "작업" },
  { pattern: /^\/r\/?$/, tier: "read", label: "해석" },
  { pattern: /^\/p\/?$/, tier: "present", label: "설명" },
  { pattern: /^\/c\/?$/, tier: "present", label: "고객 화면", lock: true },
  { pattern: /^\/wl\/?$/, tier: "work", label: "고정한 작업 화면", lock: true },
];

test("저장값 읽기: 아는 값 셋만 그대로 · 없는 값 · 모르는 값 · 대소문자가 다른 값은 자동", () => {
  expect(parsePref("compact")).toBe("compact");
  expect(parsePref("regular")).toBe("regular");
  expect(parsePref("comfortable")).toBe("comfortable");
  for (const v of [null, undefined, "", "auto", "COMPACT", "dense", " compact", 42, {}, []]) expect(parsePref(v), String(v)).toBe("auto");
});

test("표에 없는 경로는 속성이 없다(저장값 · 손가락 화면과 무관) ↔ 표에 있으면 단과 밀도가 함께 나온다", () => {
  for (const pref of ["auto", "compact", "regular", "comfortable"] as const) {
    for (const coarse of [false, true]) {
      expect(resolveDensity("/none", pref, coarse, T)).toBeNull();
      expect(resolveDensity("/w/more", pref, coarse, T)).toBeNull();   // 끝이 다른 경로
      expect(resolveDensity("", pref, coarse, T)).toBeNull();
    }
  }
  expect(resolveDensity("/w", "auto", false, T)).toEqual({ tier: "work", density: "compact" });
  expect(resolveDensity("/w/", "auto", false, T)).toEqual({ tier: "work", density: "compact" });
});

test("단의 기본 밀도: 작업 → 촘촘 · 해석 → 보통 · 설명 → 넉넉", () => {
  expect(TIER_DEFAULT).toEqual({ work: "compact", read: "regular", present: "comfortable" });
  expect(resolveDensity("/w", "auto", false, T)).toEqual({ tier: "work", density: "compact" });
  expect(resolveDensity("/r", "auto", false, T)).toEqual({ tier: "read", density: "regular" });
  expect(resolveDensity("/p", "auto", false, T)).toEqual({ tier: "present", density: "comfortable" });
});

test("저장값이 단의 기본값을 이긴다 — 단은 그대로이고 밀도만 바뀐다", () => {
  expect(resolveDensity("/w", "regular", false, T)).toEqual({ tier: "work", density: "regular" });
  expect(resolveDensity("/w", "comfortable", false, T)).toEqual({ tier: "work", density: "comfortable" });
  expect(resolveDensity("/r", "compact", false, T)).toEqual({ tier: "read", density: "compact" });
  expect(resolveDensity("/p", "compact", false, T)).toEqual({ tier: "present", density: "compact" });
});

test("손가락 화면은 저장값을 이긴다(어떤 단이든 넉넉) ↔ 손가락 화면이 아니면 저장값 그대로", () => {
  for (const path of ["/w", "/r", "/p"]) {
    for (const pref of ["auto", "compact", "regular", "comfortable"] as const) {
      expect(resolveDensity(path, pref, true, T)?.density, `${path} ${pref}`).toBe("comfortable");
    }
  }
  expect(resolveDensity("/w", "compact", false, T)?.density).toBe("compact");
  expect(resolveDensity("/w", "compact", true, T)?.tier).toBe("work");   // 단은 바뀌지 않는다
});

test("고객에게 보이는 화면(lock)은 저장값 · 단과 무관하게 넉넉 ↔ 고정하지 않은 화면은 저장값을 따른다", () => {
  for (const pref of ["auto", "compact", "regular", "comfortable"] as const) {
    for (const coarse of [false, true]) {
      expect(resolveDensity("/c", pref, coarse, T)).toEqual({ tier: "present", density: "comfortable" });
      expect(resolveDensity("/wl", pref, coarse, T)).toEqual({ tier: "work", density: "comfortable" });
    }
  }
  expect(resolveDensity("/p", "compact", false, T)?.density).toBe("compact");
});

test("표의 앞줄이 이긴다(겹치는 무늬) · tierRoute 는 그 줄을 돌려준다", () => {
  const overlap: TierRoute[] = [{ pattern: /^\/x(\/|$)/, tier: "work", label: "앞" }, { pattern: /^\/x\/y\/?$/, tier: "read", label: "뒤" }];
  expect(resolveDensity("/x/y", "auto", false, overlap)).toEqual({ tier: "work", density: "compact" });
  expect(tierRoute("/x/y", overlap)?.label).toBe("앞");
  expect(tierRoute("/z", overlap)).toBeNull();
});

/** `html` 대역 — 속성 둘만 다룬다. */
function fakeEl(init: Record<string, string> = {}) {
  const attrs: Record<string, string> = { ...init };
  return {
    attrs,
    setAttribute(k: string, v: string) { attrs[k] = v; },
    removeAttribute(k: string) { delete attrs[k]; },
  };
}

test("속성은 둘이 함께 붙고 함께 떨어진다 — 다른 속성은 건드리지 않는다", () => {
  const el = fakeEl({ lang: "ko", class: "dark" });
  applyDensity(el, { tier: "work", density: "compact" });
  expect(el.attrs).toEqual({ lang: "ko", class: "dark", "data-tier": "work", "data-density": "compact" });
  applyDensity(el, { tier: "read", density: "comfortable" });
  expect(el.attrs).toEqual({ lang: "ko", class: "dark", "data-tier": "read", "data-density": "comfortable" });
  applyDensity(el, null);
  expect(el.attrs).toEqual({ lang: "ko", class: "dark" });
  applyDensity(el, null);                                             // 없는 것을 또 떼도 그대로
  expect(el.attrs).toEqual({ lang: "ko", class: "dark" });
});

/** 조각을 가짜 전역에서 돌린다 — 실제 브라우저의 것은 `density.spec.ts` 가 본다. */
function runBoot(code: string, o: { path: string; stored: string | null; coarse: boolean; storageThrows?: boolean; noMatchMedia?: boolean; mediaThrows?: boolean }) {
  const el = fakeEl();
  const document = { documentElement: el };
  const localStorage = { getItem(k: string) { if (o.storageThrows) throw new Error("막힘"); return k === DENSITY_KEY ? o.stored : null; } };
  const location = { pathname: o.path };
  const asked: string[] = [];
  const window: Record<string, unknown> = o.noMatchMedia ? {} : {
    matchMedia(q: string) { asked.push(q); if (o.mediaThrows) throw new Error("막힘"); return { matches: q === "(pointer: coarse)" ? o.coarse : false }; },
  };
  new Function("document", "localStorage", "location", "window", code)(document, localStorage, location, window);
  return { attrs: el.attrs, asked };
}
const asState = (attrs: Record<string, string>): DensityState | null =>
  "data-tier" in attrs || "data-density" in attrs ? ({ tier: attrs["data-tier"], density: attrs["data-density"] } as DensityState) : null;

test("★첫 그림 전 조각 = 순수 함수★ — 경로 × 저장값 × 손가락 화면 격자에서 같은 답", () => {
  const code = densityBoot(T);
  let n = 0, attached = 0;
  for (const path of ["/w", "/w/", "/r", "/p", "/c", "/wl", "/none", "/w/more", "/"]) {
    for (const stored of [null, "compact", "regular", "comfortable", "auto", "junk", ""]) {
      for (const coarse of [false, true]) {
        const got = asState(runBoot(code, { path, stored, coarse }).attrs);
        const want = resolveDensity(path, parsePref(stored), coarse, T);
        expect(got, `${path} · ${stored} · ${coarse}`).toEqual(want);
        n++; if (got) attached++;
      }
    }
  }
  expect(n).toBe(9 * 7 * 2);
  expect(attached).toBe(6 * 7 * 2);                                    // 공허하지 않다 — 붙는 칸과 붙지 않는 칸이 다 있다
  // 겹치는 무늬 — 조각도 표의 앞줄에서 멈춘다(끝까지 돌아 뒷줄을 고르지 않는다)
  const overlap: TierRoute[] = [{ pattern: /^\/x(\/|$)/, tier: "work", label: "앞" }, { pattern: /^\/x\/y\/?$/, tier: "present", label: "뒤", lock: true }];
  expect(asState(runBoot(densityBoot(overlap), { path: "/x/y", stored: null, coarse: false }).attrs)).toEqual({ tier: "work", density: "compact" });
  expect(asState(runBoot(densityBoot(overlap), { path: "/x/y", stored: null, coarse: false }).attrs)).toEqual(resolveDensity("/x/y", "auto", false, overlap));
  // 빈 표 — 조각은 아무것도 달지 않는다
  expect(asState(runBoot(densityBoot([]), { path: "/w", stored: "compact", coarse: true }).attrs)).toBeNull();
});

test("조각은 손가락 화면 질의를 그 글자로 묻고, 저장이나 질의가 던져도 던지지 않는다(자동 · 손가락 화면 아님으로)", () => {
  const code = densityBoot(T);
  expect(runBoot(code, { path: "/w", stored: "regular", coarse: false }).asked).toEqual(["(pointer: coarse)"]);
  expect(runBoot(code, { path: "/none", stored: "regular", coarse: true }).asked).toEqual([]);   // 표에 없으면 아무것도 묻지 않는다
  expect(asState(runBoot(code, { path: "/w", stored: "regular", coarse: false, storageThrows: true }).attrs)).toEqual({ tier: "work", density: "compact" });
  expect(asState(runBoot(code, { path: "/w", stored: "compact", coarse: true, storageThrows: true }).attrs)).toEqual({ tier: "work", density: "comfortable" });
  expect(asState(runBoot(code, { path: "/w", stored: "regular", coarse: true, noMatchMedia: true }).attrs)).toEqual({ tier: "work", density: "regular" });
  expect(asState(runBoot(code, { path: "/w", stored: "regular", coarse: true, mediaThrows: true }).attrs)).toEqual({ tier: "work", density: "regular" });
});

test("조각의 글: 내보낸 상수 = 실제 표로 지은 글 · 저장 열쇠를 싣는다 · 인라인 스크립트를 끊는 글자가 없다", () => {
  expect(DENSITY_BOOT).toBe(densityBoot());
  expect(DENSITY_BOOT).toBe(densityBoot(TIER_ROUTES));
  expect(DENSITY_KEY).toBe("alpha_density");
  expect(DENSITY_BOOT).toContain(JSON.stringify(DENSITY_KEY));
  expect(DENSITY_BOOT).not.toMatch(/<\/|<!--/);
  expect(() => new Function(DENSITY_BOOT)).not.toThrow();              // 문법이 맞다
});

// ── ★끄면 그대로 — 제품 경로는 표에 없다★ ─────────────────────────────────────────────────────────
// 화면 조각이 제 화면을 표에 넣을 때 이 두 목록을 같은 커밋에서 고친다(그 커밋이 그 화면의 골든을 다시 뜬다).
const ALLOWED_ROUTES = ["^\\/dev\\/density\\/?$", "^\\/screener\\/?$"];   // 개발 견본 + 종목 찾기(U1-b — 작업 단에 오른 첫 제품 화면)
const PRODUCT_PATHS = [
  "/", "/login", "/c", "/dashboard", "/screener/x", "/backtest", "/backtest/intraday", "/backtest/runs/abc/results", "/backtest/runs/abc/loading",
  "/backtest/runs/abc/compare", "/macro", "/macro/causal", "/insights", "/risk-tools", "/derivatives", "/allocation", "/my-account", "/my-account/journal",
  "/clients", "/clients/1", "/settings", "/admin/data", "/admin/live-trading", "/admin/realism", "/dev/ui", "/dev", "/dev/density/x",
];

test("★경로 표의 줄은 허용 목록과 같다 · 제품 경로는 어떤 저장값 · 어떤 화면에서도 속성이 없다★ ↔ 개발 견본은 작업 단", () => {
  expect(TIER_ROUTES.map((r) => r.pattern.source)).toEqual(ALLOWED_ROUTES);
  for (const r of TIER_ROUTES) expect(r.pattern.flags, "무늬에 g · y 깃발이 있으면 test 가 상태를 남긴다").toBe("");
  for (const path of PRODUCT_PATHS) {
    for (const pref of ["auto", "compact", "regular", "comfortable"] as const) {
      for (const coarse of [false, true]) expect(resolveDensity(path, pref, coarse), `${path} ${pref} ${coarse}`).toBeNull();
    }
    expect(asState(runBoot(DENSITY_BOOT, { path, stored: "compact", coarse: true }).attrs), path).toBeNull();
  }
  expect(resolveDensity("/dev/density", "auto", false)).toEqual({ tier: "work", density: "compact" });
  expect(resolveDensity("/dev/density/", "regular", false)).toEqual({ tier: "work", density: "regular" });
  // 종목 찾기(U1-b): 작업 단 · 기본은 촘촘 · 저장값을 따른다 · 손가락 화면은 넉넉. 첫 그림 전의 조각도 같은 답.
  expect(resolveDensity("/screener", "auto", false)).toEqual({ tier: "work", density: "compact" });
  expect(resolveDensity("/screener/", "comfortable", false)).toEqual({ tier: "work", density: "comfortable" });
  expect(resolveDensity("/screener", "compact", true), "손가락 화면은 저장값보다 앞선다").toEqual({ tier: "work", density: "comfortable" });
  expect(asState(runBoot(DENSITY_BOOT, { path: "/screener", stored: "regular", coarse: false }).attrs)).toEqual({ tier: "work", density: "regular" });
});
