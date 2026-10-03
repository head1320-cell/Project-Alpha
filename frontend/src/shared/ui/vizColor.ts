/**
 * 그림 색 단계 — 수준(양쪽 색)·범주 (BU5b 에서 매크로 분석에 처음 두고 BU6 에서 기업 분석과 함께 쓰려고 shared 로 내렸다)
 * ==========================================================================
 * 색의 뜻은 넷이고 섞지 않는다(`widgets/macro/macroKo.ts` 머리 주석): 등락 = `--tx-up/down` · 수준 = 여기 `--mc-lv-*` ·
 * 판단 = 중립 · 범주 = 여기 `--mc-c-*`. 토큰 값은 globals.css BU5b 절(라이트/다크 짝).
 */

// ── 수준 색 단계 (z) ── 0.5·1·2 σ 를 경계로 쪽마다 3 단. 그리기 위한 구간일 뿐 판단이 아니다(값은 늘 글자로 함께 보인다).
export type LvStep = "neg-3" | "neg-2" | "neg-1" | "mid" | "pos-1" | "pos-2" | "pos-3";
export function zStep(z: number): LvStep {
  const a = Math.abs(z);
  if (a < 0.5) return "mid";
  const k = a < 1 ? 1 : a < 2 ? 2 : 3;
  return `${z > 0 ? "pos" : "neg"}-${k}` as LvStep;
}
/** z → 칸 바탕색. 모르면(null) 빈 칸 색 — 0 으로 칠하지 않는다. */
export function zFill(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return "var(--mc-lv-none)";
  return `var(--mc-lv-${zStep(z)})`;
}
/** 백분위(0..100) → 칸 바탕색. 50 이 가운데 — 위치를 z 처럼 같은 양쪽 색으로. */
export function pctFill(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "var(--mc-lv-none)";
  const t = (p - 50) / 50, a = Math.abs(t);
  if (a < 0.2) return "var(--mc-lv-mid)";
  const k = a < 0.5 ? 1 : a < 0.8 ? 2 : 3;
  return `var(--mc-lv-${t > 0 ? "pos" : "neg"}-${k})`;
}

/** 범주 계열 색(빨강·파랑 없음) — 7 개를 넘으면 "기타" 회색으로 접는다. dataviz 검증기 인접 쌍 통과(라이트·다크). */
export const CAT_N = 7;
export const catColor = (idx: number): string => (idx < CAT_N ? `var(--mc-c-${idx + 1})` : "var(--mc-c-etc)");

