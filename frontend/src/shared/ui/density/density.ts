/**
 * 단 · 밀도 장치의 순수 규칙 (ADR 007 §7 · U0)
 * ==========================================================================
 * `html` 의 속성 둘 — `data-tier`(화면이 하는 일) · `data-density`(줄 높이와 여백의 단계) — 이 `globals.css` 끝의 토큰 블록을 다시 정한다.
 * ★속성이 없는 화면은 한 줄도 달라지지 않는다★ — 경로 표(`TIER_ROUTES`)에 있는 화면만 속성을 받는다.
 *
 * 밀도를 정하는 차례:
 *   ① 표에 없는 경로 → 속성 없음   ② 고객에게 보이는 화면(`lock`) → 넉넉   ③ 손가락 화면(`pointer: coarse`) → 넉넉
 *   ④ 이 브라우저의 저장값(`alpha_density`)   ⑤ 단의 기본값
 * 첫 그림 전에 도는 조각(`DENSITY_BOOT`)과 셸의 맞춤 훅(`useDensitySync`)은 이 파일의 같은 표 · 같은 차례에서 나온다
 * (`e2e/density-logic.spec.ts` 가 격자로 둘의 답을 견준다).
 *
 * 이 파일은 React 를 들이지 않는다 — 순수 스펙이 브라우저 없이 가져온다. 모양은 `shared/theme/theme.ts` 와 같다.
 */

export type Tier = "work" | "read" | "present";
export type Density = "compact" | "regular" | "comfortable";
/** 저장값 — 고르지 않았으면 자동(단의 기본값). */
export type DensityPref = "auto" | Density;
export interface DensityState { tier: Tier; density: Density }
/** `lock` — 고객에게 보이는 화면. 받는 사람은 밀도를 고르지 않았으므로 어떤 저장값에서도 넉넉이다. */
export interface TierRoute { pattern: RegExp; tier: Tier; label: string; lock?: boolean }

export const DENSITY_KEY = "alpha_density";
/** 화면 글자(용어집 §3.31). */
export const TIERS: [Tier, string][] = [["work", "작업 단"], ["read", "해석 단"], ["present", "설명 단"]];
export const DENSITIES: [Density, string][] = [["compact", "촘촘"], ["regular", "보통"], ["comfortable", "넉넉"]];
export const TIER_DEFAULT: Record<Tier, Density> = { work: "compact", read: "regular", present: "comfortable" };

/**
 * 단을 받는 화면. ★제품 화면은 아직 없다(U0)★ — 화면 조각이 제 화면을 옮길 때 한 줄씩 더하고, 그 커밋이 그 화면의 골든을 다시 뜬다.
 * 지금 있는 한 줄은 개발 견본이다: 조각 → 훅 → 화면 사이 이동을 실제 브라우저에서 돌려 보는 자리(`e2e/density.spec.ts`).
 * 줄을 더하면 `e2e/density-logic.spec.ts` 의 허용 목록이 실패한다 — 같은 커밋에서 함께 고친다.
 */
export const TIER_ROUTES: TierRoute[] = [
  { pattern: /^\/dev\/density\/?$/, tier: "work", label: "개발 견본 · 단과 밀도" },
];

/** 저장된 글자 → 저장값. 없는 값 · 모르는 값은 자동(지어내지 않는다 — 단의 기본값으로 그린다). */
export function parsePref(v: unknown): DensityPref {
  return v === "compact" || v === "regular" || v === "comfortable" ? v : "auto";
}

export function tierRoute(path: string, routes: TierRoute[] = TIER_ROUTES): TierRoute | null {
  return routes.find((r) => r.pattern.test(path)) ?? null;
}

/** 이 경로 · 이 저장값 · 이 화면에서 걸릴 단과 밀도. 표에 없는 경로는 `null`(속성을 달지 않는다). */
export function resolveDensity(path: string, pref: DensityPref, coarse: boolean, routes: TierRoute[] = TIER_ROUTES): DensityState | null {
  const r = tierRoute(path, routes);
  if (!r) return null;
  const density: Density = r.lock || coarse ? "comfortable" : pref !== "auto" ? pref : TIER_DEFAULT[r.tier];
  return { tier: r.tier, density };
}

/** 속성 둘을 함께 달거나 함께 뗀다 — 하나만 남는 상태는 없다. */
export function applyDensity(el: Pick<Element, "setAttribute" | "removeAttribute">, s: DensityState | null): void {
  if (!s) {
    el.removeAttribute("data-tier");
    el.removeAttribute("data-density");
    return;
  }
  el.setAttribute("data-tier", s.tier);
  el.setAttribute("data-density", s.density);
}

/** 이 브라우저의 저장값. 저장을 읽지 못하면(막힌 브라우저) 자동. */
export function readDensityPref(): DensityPref {
  try {
    return parsePref(window.localStorage.getItem(DENSITY_KEY));
  } catch {
    return "auto";
  }
}

/**
 * 첫 그림 전에 도는 조각의 글 — React 가 붙기 전에 속성을 달아, 넉넉하게 그렸다가 촘촘해지는 깜박임을 막는다.
 * 규칙은 `resolveDensity` 와 같다. 표에 없는 경로에서는 아무것도 읽지 않고 아무것도 달지 않는다.
 */
export function densityBoot(routes: TierRoute[] = TIER_ROUTES): string {
  const table = routes.map((r) => `[${r.pattern.toString()},${JSON.stringify(r.tier)},${r.lock ? 1 : 0}]`).join(",");
  return `(function(){try{var p=location.pathname,R=[${table}],m=null,i;`
    + `for(i=0;i<R.length;i++){if(R[i][0].test(p)){m=R[i];break}}if(!m)return;`
    + `var v=null;try{v=localStorage.getItem(${JSON.stringify(DENSITY_KEY)})}catch(e){}`
    + `var c=false;try{c=!!(window.matchMedia&&window.matchMedia("(pointer: coarse)").matches)}catch(e){}`
    + `var d=(m[2]||c)?"comfortable":(v==="compact"||v==="regular"||v==="comfortable")?v:${JSON.stringify(TIER_DEFAULT)}[m[1]];`
    + `var h=document.documentElement;h.setAttribute("data-tier",m[1]);h.setAttribute("data-density",d)}catch(e){}})();`;
}

export const DENSITY_BOOT = densityBoot();
