// RegimeSnapshot — 매크로 국면의 불변·버전화된 스냅샷 (백엔드 소유).
//
// AAS 는 이 객체를 **ID 로 참조**한다. 브라우저 메모리로 복사해 들고 다니지 않는다 —
// 그래야 새로고침·공유·재현이 성립한다.

/** 값의 출처/신선도. 백엔드 DataStatus 와 1:1. */
export type DataStatus = "real" | "mock" | "delayed" | "stale" | "partial" | "unavailable";

/**
 * 이 데이터를 **어디까지** 쓸 수 있는가. 백엔드가 빈티지 유무·이력 길이·공표지연
 * 모델링 여부에서 파생한다(프론트가 정하지 않는다).
 *
 * forward_only = 전방 리서치 맥락으로는 쓰되 **과거 시뮬레이션에서는 차단**.
 * 현재 대시보드 수집기는 빈티지를 모르므로 from-current 스냅샷은 전부 여기 해당한다.
 */
export type ResearchUsage = "backtest_eligible" | "forward_only" | "unavailable";

/** 관측치 신원 — 공표시각·빈티지가 없으면 재현이 성립하지 않는다. */
export interface MacroObservation {
  series_id: string;
  observation_period: string;
  release_timestamp: string;
  vintage_id: string;
  retrieved_at: string;
  value: number;
  data_status: DataStatus;
  market_cutoff?: string | null;
  execution_timestamp?: string | null;
}

export interface RegimeSnapshot {
  snapshot_id: string;
  created_at: number;
  as_of: string;
  growth_axis: number;
  inflation_axis: number;
  phase_probabilities: Record<string, number>;
  stress_score: number;
  confidence: number;
  observations: MacroObservation[];
  /**
   * 국면 라벨과 권고 모드 — Phase 4a 에서 **필드로** 승격됐다.
   * 이전에는 explanation 문자열 안에만 있어서 UI 가 표시 문구를 파싱해야 했다.
   * 후행 추가 열이라 구 스냅샷·마이그레이션 실패 시 null 이다(있는 척하지 않는다).
   */
  regime: string | null;
  recommended_mode: string | null;
  data_status: DataStatus;
  research_usage: ResearchUsage;
  model_version: string;
  engine_version: string;
  code_version: string;
  explanation: string;
}

/** 목록 응답 — 관측치 배열 대신 개수만 (payload 비대 방지). */
export type RegimeSnapshotSummary = Omit<RegimeSnapshot, "observations"> & {
  observation_count: number;
};

export interface CreateFromCurrentResult {
  recorded: boolean;
  snapshot_id: string | null;
  as_of?: string;
  research_usage?: ResearchUsage;
  data_status?: DataStatus;
  message?: string;
}

// ── 표시 헬퍼 ────────────────────────────────────────────────────────────────

export const USAGE_LABEL: Record<ResearchUsage, string> = {
  backtest_eligible: "과거 검증 가능",
  forward_only: "전방 전용",
  unavailable: "사용 불가",
};

/** 왜 그 등급인지 — UI 가 툴팁에 그대로 쓴다. 한계를 숨기지 않기 위한 문장이다. */
export const USAGE_REASON: Record<ResearchUsage, string> = {
  backtest_eligible: "빈티지 이력·공표지연이 모델링되어 과거 시뮬레이션에 쓸 수 있습니다.",
  forward_only:
    "개정 이력(빈티지)이 없어 과거 시점의 값을 재구성할 수 없습니다. " +
    "전방 리서치 맥락으로만 쓰이며 과거 시뮬레이션에서는 차단됩니다.",
  unavailable: "데이터 출처가 없습니다.",
};

export const STATUS_LABEL: Record<DataStatus, string> = {
  real: "실데이터", mock: "합성(mock)", delayed: "지연", stale: "오래됨",
  partial: "부분", unavailable: "없음",
};

/** 국면 확률에서 최빈 국면. 확률이 비면 null (임의로 고르지 않는다). */
export function dominantPhase(probs: Record<string, number>): { name: string; p: number } | null {
  const entries = Object.entries(probs || {});
  if (!entries.length) return null;
  const [name, p] = entries.reduce((a, b) => (b[1] > a[1] ? b : a));
  return { name, p };
}
