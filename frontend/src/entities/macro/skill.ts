/**
 * 국면 예측 비교(M2)의 칸 글자 — 캔버스 결과 판(`MacroW2Results`)과 매크로 화면(`MacroIntelPanel`)이 같은 규칙으로 쓴다.
 * ==========================================================================
 * 값은 서버 그대로다(다시 계산하지 않는다). 재지 못한 칸은 0 이 아니라 "—".
 * ★고르지 않는다★ 이 파일에는 후보를 줄 세우거나 '가장 나은 것'을 고르는 함수가 없다 — 표는 서버의 고정 순서로 그린다.
 * 숫자 칸 넷은 필요한 칸만 받는다 — 배분의 국면 가중 블록(M3)이 실은 같은 점수(후보 `gmm_start`)도 같은 규칙으로 쓴다.
 */
import type { SkillCandidate } from "./studios";

const ok = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/**
 * 후보 이름 — 서버 이름표 그대로이되 '×' 와 뒤 낱말 사이만 줄바꿈 없는 띄어쓰기(U+00A0)로 바꾼다.
 * 좁은 칸에서 'GMM 시작 분포 ×' / '전이' 처럼 '×' 가 줄 끝에 홀로 남지 않게 한다(글자는 같다 — 화면 읽기 · 복사도 같은 글).
 */
export const skillName = (c: SkillCandidate): string => c.name.replace(/ × /g, " ×\u00a0");

/** 적중률(가장 높은 확률의 국면 = 실현) — 정수 %. */
export const skillHit = (c: Pick<SkillCandidate, "hit_rate">): string => (ok(c.hit_rate) ? `${(c.hit_rate * 100).toFixed(0)}%` : "—");

/** 브라이어 점수의 평균 — 0(확신하고 맞힘) ~ 2(확신하고 틀림). */
export const skillBrier = (c: Pick<SkillCandidate, "brier">): string => (ok(c.brier) ? c.brier.toFixed(3) : "—");

/** 오늘 국면 유지 대비 브라이어 이득 — 양이면 유지보다 확률을 잘 맞혔다. 음수 부호는 '−'(U+2212). */
export const skillGain = (c: Pick<SkillCandidate, "gain">): string =>
  (ok(c.gain) ? `${c.gain >= 0 ? "+" : "−"}${Math.abs(c.gain).toFixed(3)}` : "—");

/**
 * 순차 증거(e-값)의 최고값 — 상한(10¹²)에 닿았으면 그렇게 적는다.
 * 기준을 넘었는지는 글자 '*'로도 말한다(색만으로 말하지 않는다 · 표 아래 범례가 뜻을 적는다).
 */
export const skillEvidence = (c: Pick<SkillCandidate, "evidence">): string => {
  const e = c.evidence;
  if (!e || !ok(e.peak)) return "—";
  const v = e.saturated ? "10¹² 이상" : e.peak >= 1000 ? Math.round(e.peak).toLocaleString("ko-KR") : e.peak.toFixed(2);
  return e.passed ? `${v}*` : v;
};

/** 기준을 넘은 후보가 하나라도 있는가 — 범례 '*' 줄을 낼지(없으면 범례도 없다). */
export const skillAnyPassed = (cs: SkillCandidate[]): boolean => cs.some((c) => Boolean(c.evidence?.passed));
