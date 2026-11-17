/**
 * 시장 국면 번호의 색 — 시장 국면 절(K1)과 국면별 나눔(K2)이 같은 표지를 쓴다(그래서 두 feature 아래 entities 에 둔다).
 * 색은 토큰(`--itd-mr-s1..s7` · 라이트/다크 짝)에서 고른다 — 국면 수 2 · 3 · 4 에 1·7 / 1·4·7 / 1·3·5·7 단(같은 간격 · dataviz 순서형 검사 통과).
 * 번호의 표지일 뿐 순위가 아니다.
 */
const STEPS: Record<number, number[]> = { 2: [1, 7], 3: [1, 4, 7], 4: [1, 3, 5, 7] };

/** 국면 s(1부터) 의 칠 — 모르는 국면 수면 중립색(지어내지 않는다). */
export function stateFill(s: number, k: number): string {
  const step = STEPS[k]?.[s - 1];
  return step ? `var(--itd-mr-s${step})` : "var(--tx-mute)";
}
