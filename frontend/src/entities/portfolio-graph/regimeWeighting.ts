/**
 * 최적화 노드의 국면 가중 블록(M3) — 서버 `allocation_graph_nodes._regime_block` 의 모양 그대로.
 * ==========================================================================
 * 방식 이름 · 열화 사유 · 점수는 서버 값이다(화면이 이름을 짓거나 다시 계산하지 않는다). 재지 못한 칸은 0 이 아니라 "—".
 * 점수의 숫자 칸은 국면 예측 비교(M2)와 같은 서식(`entities/macro/skill.ts`)을 쓴다 — 같은 점수가 두 화면에서 다르게 보이지 않게.
 * 이 슬라이스는 다른 엔티티 슬라이스를 들이지 않는다(FSD) — 국면 이름은 그리는 위젯이 넘긴다(`distRows` 의 `nameOf`).
 */

export type Weighting = "hard" | "probabilistic" | "gmm";

/** 같은 경로의 워크포워드 점수 — 후보 `gmm_start` 의 값(`regime_gmm_start.skill_summary`). */
export interface RegimeSkill {
  available: boolean;
  k: number;
  n_eval: number;
  hits: number | null;
  hit_rate: number | null;
  brier: number | null;
  gain: number | null;
  baseline: { key: string; name: string; hit_rate: number | null; brier: number | null } | null;
  evidence: { e_value: number; peak: number; saturated: boolean; passed: boolean } | null;
  evidence_reason: string | null;
  threshold: number | null;
  note: string;
}

export interface RegimeBlock {
  /** 조건부 추정을 만들었는가 — 아니면 `used` 는 `null` 이고 `reason` 이 있다. */
  available: boolean;
  /** 만들었고 관문이 막지 않아 비중에 쓰였는가. */
  applied: boolean;
  reason: string | null;
  requested: Weighting;
  requested_name: string;
  used: Weighting | null;
  used_name: string | null;
  source: string | null;
  h_hold: number | null;
  /** 보유 기간 평균 국면 분포(혼합에 쓴 π̄) — 오늘 국면 유지면 `null`. */
  pi_bar: Record<string, number> | null;
  /** GMM 시작 분포(지금 점의 시드 평균 소속 확률) — GMM 을 썼을 때만. */
  pi0: Record<string, number> | null;
  label: string | null;
  skill: RegimeSkill | null;
  stability: { seeds: number; modal: string; agree: number; stable: boolean } | null;
  robustness: { available: boolean; resamples?: number; agree?: number; share?: number; label?: string; reason?: string; note?: string } | null;
  /** 열화 사유 — 요청한 방식을 쓰지 못한 까닭(두 겹일 수 있다). 비어 있으면 요청한 방식 그대로다. */
  fallbacks: string[];
  /** 혼합이 추정하지 못해 빼고 재정규화한 국면 → 사유. 그 국면은 `pi_bar` 에 없다(0 이 아니다). */
  dropped_regimes: Record<string, string>;
  /** 위 사실의 서버 문장(해설의 가정 줄과 같은 글). */
  dropped_notes: string[];
  path_source: string | null;
}

const REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"] as const;

const pctOf = (v: number | undefined): string =>
  (typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : "—");

/**
 * 국면 분포 표의 줄 — 국면 넷을 늘 같은 순서로. 혼합이 뺀 국면의 보유 기간 칸은 "추정 불가"(0% 로 그리지 않는다) ·
 * 그 밖에 값이 없는 칸은 "—". `nameOf` 는 국면 코드 → 화면 이름(위젯이 `entities/macro/regimeKo.regimeName` 을 넘긴다).
 */
export function distRows(b: RegimeBlock, nameOf: (regime: string) => string):
  { key: string; name: string; start: string; held: string; dropped: boolean }[] {
  return REGIMES.map((r) => {
    const dropped = r in (b.dropped_regimes ?? {});
    return { key: r, name: nameOf(r), start: pctOf(b.pi0?.[r]), held: dropped ? "추정 불가" : pctOf(b.pi_bar?.[r]), dropped };
  });
}
