/**
 * 떠 있는 판(BQ Q1) — 왼쪽 목록·오른쪽 창의 여닫기·폭. ★이 브라우저에만★ 남는 편의 상태(localStorage).
 * 못 읽거나 망가졌으면 기본값(둘 다 열림·오른쪽 392px) — 좁은 화면(≤820px)은 저장값과 관계없이 닫힌 채 시작한다.
 */
export const PANELS_KEY = "alpha_pg_panels";
export const RIGHT_W = { min: 300, max: 600, def: 392, defCompact: 344, step: 16 } as const;
export const NARROW_Q = "(max-width: 820px)";

export interface Panels {
  left: boolean;
  right: boolean;
  rightW: number;
  /** 집중 모드(\) — 두 판을 잠시 모두 닫는다. 끝내면 left·right 가 그대로 돌아온다. */
  focus: boolean;
}
export const DEFAULT_PANELS: Panels = { left: true, right: true, rightW: RIGHT_W.def, focus: false };

export const clampW = (w: number) => Math.round(Math.min(RIGHT_W.max, Math.max(RIGHT_W.min, w)));

/** `wide` = 1440px 이상 — 그보다 좁으면 처음 폭을 344px 로(가운데 캔버스가 예전 3열과 비슷하게 남도록). */
export function readPanels(narrow: boolean, wide = true): Panels {
  const base = { ...DEFAULT_PANELS, rightW: wide ? RIGHT_W.def : RIGHT_W.defCompact };
  if (narrow) return { ...base, left: false, right: false };
  try {
    const raw = typeof window === "undefined" ? null : localStorage.getItem(PANELS_KEY);
    if (!raw) return base;
    const v = JSON.parse(raw) as Partial<Panels>;
    return {
      left: typeof v.left === "boolean" ? v.left : true,
      right: typeof v.right === "boolean" ? v.right : true,
      rightW: typeof v.rightW === "number" && Number.isFinite(v.rightW) ? clampW(v.rightW) : base.rightW,
      focus: false,
    };
  } catch {
    return base;
  }
}

export function savePanels(p: Panels) {
  try { localStorage.setItem(PANELS_KEY, JSON.stringify({ left: p.left, right: p.right, rightW: p.rightW })); }
  catch { /* 적을 수 없으면 이번 방문에만 */ }
}

/** 여닫기 — 집중 모드에서 한쪽을 열면 집중을 끝내고 그쪽만 연다. */
export function toggle(p: Panels, which: "left" | "right" | "focus"): Panels {
  if (which === "focus") return { ...p, focus: !p.focus };
  if (p.focus) return { ...p, focus: false, left: which === "left", right: which === "right" };
  return { ...p, [which]: !p[which] };
}

/**
 * 캔버스(화면 좌표) 가운데 떠 있는 판이 가리는 폭 — 맞춰 보기·판 옮기기·메뉴 자리가 이만큼 비켜 선다.
 * 오른쪽 창이 아래 시트(좁은 화면)면 옆이 아니라 아래를 가린다.
 */
export function floatInsets(el: HTMLElement | null): { left: number; right: number; bottom: number } {
  const out = { left: 0, right: 0, bottom: 0 };
  const root = el?.closest(".pg-root");
  if (!el || !root) return out;
  const c = el.getBoundingClientRect();
  const shown = (sel: string) => {
    const x = root.querySelector<HTMLElement>(sel);
    return x && x.offsetParent !== null ? x.getBoundingClientRect() : null;
  };
  for (const sel of [".pg-palette", ".pg-palette-fab"]) {
    const r = shown(sel);
    if (r && r.width < c.width * 0.8) out.left = Math.max(out.left, r.right - c.left);
  }
  for (const sel of [".pg-side", ".pg-side-fab"]) {
    const r = shown(sel);
    if (!r) continue;
    if (r.width >= c.width * 0.8) out.bottom = Math.max(out.bottom, c.bottom - r.top);
    else out.right = Math.max(out.right, c.right - r.left);
  }
  return out;
}
