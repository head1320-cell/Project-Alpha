/**
 * Glide Path · Contribution — 응답 타입 (AO5)
 * ==========================================================================
 * `POST /api/v1/accounts/glidepath` (`src/api/glidepath_routes.py`)
 *
 * ★이번에 화면은 만들지 않는다★ — AA5·AB4·AD4 와 같은 선택이다. 붙일 자리
 * (Allocation Studio 파이프라인의 새 칸)는 범위가 따로이고, 타입만 먼저 둔다.
 * 안 만든 것을 안 만들었다고 적는다.
 *
 * ★숫자는 전부 `| null` 이다★ — 전제(기간·곡선·분류·적립)가 하나라도 선언되지
 * 않으면 서버가 숫자를 내지 않고 사유를 낸다. 화면이 `?? 0` 으로 채우면 그 순간
 * "미상" 이 "0" 이 되고, 그것이 `CLAUDE.md` §4 가 금지하는 바로 그 일이다.
 */

/** 축 상태 — `src/engine/run_evidence.py` 와 **같은 어휘**. */
export type AxisState = "ok" | "degraded" | "unknown";
/** 롤업 판정 — 같은 파일의 넷. */
export type EvidenceStatus = "verified" | "partial" | "unverified" | "unknown";
/** 격차의 부호. ★`unknown` 은 0 이 아니다★ — 목표가 관측 구간 안이라는 뜻. */
export type GapState = "above" | "below" | "unknown";
/** 적립 대상. 미선언이면 서버가 개월 수를 내지 않는다. */
export type ContributionBucket = "risky" | "safe";
/** 이 적립이 격차를 좁히는가 벌리는가. */
export type ContributionDirection = "closes" | "widens" | "unknown";
/** 한도 판정 — `src/domain/account_policy.py`. ★미판정은 통과가 아니다★ */
export type LimitVerdict = "pass" | "breach" | "undetermined";

export interface Interval {
  lo: number;
  hi: number;
}

export interface GlideAxis {
  state: AxisState;
  reason: string | null;
  [key: string]: unknown;
}

export interface GlideEvidence {
  status: EvidenceStatus;
  axes: Record<string, GlideAxis>;
  applicable: string[];
  ok_axes: string[];
  broken_axes: string[];
  unknown_axes: string[];
  summary: string;
  note: string;
}

export interface GlideGap {
  state: GapState;
  /** 관측 하한 − 목표. ★`state === "unknown"` 이면 부호를 믿으면 안 된다★ */
  lo: number | null;
  hi: number | null;
  sign: 1 | -1 | null;
  reason: string | null;
}

export interface GlideBlock {
  years_remaining: number | null;
  years_reason: string | null;
  /** 선언된 곡선 위의 목표 비중(%). 곡선 미선언이면 `null`. */
  target_pct: number | null;
  /** 끝점 고정 등 — 값이 있으면 그 목표는 **보간된 값이 아니다**. */
  curve_reason: string | null;
  observed: { lo: number | null; hi: number | null };
  gap: GlideGap;
  note: string;
}

export interface ContributionBlock {
  available: boolean;
  direction: ContributionDirection;
  /** 도달 개월 수 **구간**. ★점으로 접지 않는다★ — 미배정분이 폭을 만든다. */
  months: Interval | null;
  gap: GlideGap;
  reason: string | null;
  note: string;
}

export interface RiskyShare {
  available: boolean;
  reason: string | null;
  unknown_classes: string[];
  declared_risky_classes?: string[];
  unassigned_pct: number | null;
  interval: (Interval & { lo_assumes: string; hi_assumes: string }) | null;
  mix: {
    available: boolean;
    reason: string | null;
    by_class: Record<string, number>;
    assigned_pct: number | null;
    unassigned_pct: number | null;
    unassigned: unknown;
  };
}

export interface LimitJudgement {
  kind: string;
  direction: "max" | "min";
  limit: {
    kind: string;
    value: number | null;
    source: string | null;
    as_of: string | null;
    reason: string | null;
  };
  observed: Interval | null;
  verdict: LimitVerdict;
  reason: string | null;
}

export interface AccountLimits {
  account_type: string;
  verdicts: LimitJudgement[];
  summary: Record<LimitVerdict, number>;
  ignored_limits: string[];
  note: string | null;
}

export interface GlidePathResponse {
  account_type: string;
  glide: GlideBlock;
  contribution: ContributionBlock;
  risky_share: RiskyShare;
  evidence: GlideEvidence;
  limits: AccountLimits;
  scope_note: string;
  /** ★최적화기는 이 목표를 모른다★ — 화면이 이 문장을 지우면 안 된다. */
  optimizer_note: string;
}

/** 요청 — 곡선 위의 한 점. ★서버는 이름 있는 프리셋을 갖지 않는다★ */
export interface GlideCurvePoint {
  years_to_target: number;
  risky_target_pct: number;
}

/** 요청 — 앞으로의 적립 **계획**. ★실적이 아니다★ */
export interface ContributionPlanInput {
  monthly_krw: number | null;
  bucket: ContributionBucket | null;
  portfolio_value_krw: number | null;
}

export interface GlidePathRequest {
  account_type: string;
  holdings: Record<string, number>;
  /** `null` 은 "선언하지 않았다", `[]` 는 "위험자산이 없다고 선언했다". */
  risky_asset_classes: string[] | null;
  horizon_days?: number | null;
  target_retirement_year?: number | null;
  curve?: GlideCurvePoint[] | null;
  contribution?: ContributionPlanInput | null;
  limits?: {
    kind: string;
    value: number | null;
    source: string | null;
    as_of: string | null;
  }[];
  /** ★실적★ — 올해 이미 납입한 금액. 연간 한도 판정의 관측값이다. */
  contributed_ytd_krw?: number | null;
  /** ★실적★ — 누적 납입액. 총 납입 한도 판정의 관측값이다. */
  total_contributed_krw?: number | null;
}
