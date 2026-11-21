/**
 * 분봉 화면의 두 칸(G5 · 계획 문서 §6) — 언제 나누는지 · 설정 칸 폭의 범위 · 브라우저에 남기는 꼴. 순수 함수와 상수만.
 * ==========================================================================
 * ★두 칸은 가로 1280px 이상 · 세로 800px 이상일 때만★ — 1101px 에서는 결과 칸의 차트가 297 ~ 417px, 1280 × 720 에서는 칸 높이가 약 415px 라 버렸다(잰 값 · §6.0).
 * 설정 칸: 최소 440(400 에서 칸이 한 줄로 접혀 설정이 3,526px 로 길어진다 — 잰 값) · 기본 480 · 최대 = 작업 칸 − 구분선 16 − 결과 칸 최소 640.
 * ★선호 폭을 남기고 그릴 때 지금 작업 칸 폭으로 clamp★ 한다 — 창을 줄였다 늘리면 선호가 돌아온다. 남긴 꼴이 틀리면 기본값으로 그린다.
 */
import { clampSplit } from "@/shared/ui/split/split";

export const SPLIT_QUERY = "(min-width: 1280px) and (min-height: 800px)";
export const SPLIT_KEY = "itd.split";
export const SET_MIN = 440;
export const SET_DEFAULT = 480;
export const SET_STEP = 16;
export const BAR_W = 16;
export const OUT_MIN = 640;

export type SplitPref = { w: number; open: boolean };
export const DEFAULT_SPLIT: SplitPref = { w: SET_DEFAULT, open: true };

/** 브라우저에 남긴 글 → 선호. 폭은 양의 유한한 수만 · 접힘은 true/false 만 받는다(그 밖은 기본값 — 한 칸씩 따로). */
export function readSplit(raw: string | null): SplitPref {
  if (!raw) return DEFAULT_SPLIT;
  let v: unknown;
  try { v = JSON.parse(raw); } catch { return DEFAULT_SPLIT; }
  if (!v || typeof v !== "object" || Array.isArray(v)) return DEFAULT_SPLIT;
  const o = v as Record<string, unknown>;
  const w = typeof o.w === "number" && Number.isFinite(o.w) && o.w > 0 ? o.w : DEFAULT_SPLIT.w;
  const open = typeof o.open === "boolean" ? o.open : DEFAULT_SPLIT.open;
  return { w, open };
}

/** 작업 칸 폭에서 설정 칸이 가질 수 있는 최대(결과 칸 최소 640 · 구분선 16 을 남긴다). 최소보다 작을 수 있다 — 그때는 최소로 그린다. */
export const paneMax = (work: number): number => work - BAR_W - OUT_MIN;

/** 그릴 폭 — 선호를 지금 작업 칸으로 clamp(선호는 바꾸지 않는다). */
export const paneWidth = (pref: number, work: number): number => clampSplit(pref, SET_MIN, paneMax(work));
