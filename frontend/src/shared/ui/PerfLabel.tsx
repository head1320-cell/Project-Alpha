"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// PerfLabel — 성과 숫자 옆에 ★"이 수치가 무엇인가"★ 를 적는다 (Z3)
//
// 설계: `docs/plans` Z · 애드덤 §4 / 합격기준 #3 · 백엔드 어휘는
//       `src/domain/perf_kind.py` 가 단일 출처다.
//
// ★라벨을 프런트가 지어내면 장식이다★
// ─────────────────────────────────────────────────────────────────────────────
// "백테스트 페이지니까 BACKTEST" 는 사실이 아니라 **배치**다. 같은 컴포넌트를 다른
// 데이터로 재사용하는 순간 거짓말이 된다. 그래서 이 컴포넌트는 **응답이 말한 것만**
// 그린다. 응답이 아무 말도 안 했으면 `unknown` + 왜 모르는지다 — ★추론하지 않는다★.
//
// ★두 축을 섞지 않는다★
// ─────────────────────────────────────────────────────────────────────────────
//   kind       무슨 **성과**인가   백테스트 / 모의투자 / 섀도 / 테스트베드 / 실계좌
//   data_real  무슨 **데이터**인가  실데이터인가 합성인가
// 둘은 독립이다. 실데이터 백테스트도, mock 데이터 모의투자도 있다.
//
// ★기존 배지 넷과 다른 것을 말한다★ — `brun-badge`(시점 정합) · `tbt-prov`(데이터
// 출처) · `as-bt-badge`(데이터+OOS) · CockpitParts 인라인(실행 모드). 그 넷은 한 글자도
// 건드리지 않는다(E2E 계약, ADR 001). 이 컴포넌트는 **성과의 종류**만 말하므로 같은
// 화면에 축이 다른 배지가 둘 이상 보일 수 있다 — 그것은 결함이 아니라 사실이다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 백엔드 `src/domain/perf_kind.py::PERF_KINDS` 의 사본. 순서까지 같다. */
export const PERF_KINDS = [
  "backtest", "paper", "shadow", "ra_testbed", "live", "unknown",
] as const;

export type PerfKind = (typeof PERF_KINDS)[number];

/** 응답이 싣는 `perf_label` 의 모양 (`PerfLabel.to_dict()`). */
export interface PerfLabelValue {
  kind: string;
  kind_reason?: string | null;
  data_real?: boolean | null;
  data_reason?: string | null;
}

const KIND_TEXT: Record<PerfKind, string> = {
  backtest: "백테스트",
  paper: "모의투자",
  shadow: "섀도",
  ra_testbed: "테스트베드",
  live: "실계좌",
  unknown: "미상",
};

/** 마우스오버로 읽는 한 줄 — 라벨이 **무엇을 주장하는지** 적는다. */
const KIND_HINT: Record<PerfKind, string> = {
  backtest: "과거 데이터 위의 시뮬레이션이에요 — 실제로 체결된 적이 없어요.",
  paper: "모의투자 계좌에서 실시간으로 집행된 결과예요 — 실제 자금이 아니에요.",
  shadow: "신호만 기록하고 주문은 내지 않았어요.",
  ra_testbed: "표준 심사 환경(테스트베드)의 성과예요.",
  live: "실계좌에서 실제 자금으로 집행된 결과예요.",
  unknown: "이 수치가 무엇에서 나왔는지 응답이 말하지 않았어요.",
};

/** ★응답에 라벨이 아예 없을 때의 사유★ — 비어 있는 것과 모르는 것을 구별한다. */
export const PERF_LABEL_MISSING_REASON =
  "이 응답은 수치의 종류를 말하지 않아요";

function isKnownKind(k: string): k is PerfKind {
  return (PERF_KINDS as readonly string[]).includes(k);
}

/**
 * 응답 값 → 그릴 수 있는 라벨.
 *
 * ★없거나 알아보지 못하면 `unknown` 이다★ — `backtest` 로 기울지 않는다. 기울면
 * 다음 사람이 **확인되지 않은 수치를 시뮬레이션 결과로** 읽는다(백엔드
 * `execution_label` 이 `paper` 로 기울지 않는 것과 같은 이유).
 */
export function resolvePerfLabel(
  value: PerfLabelValue | null | undefined,
): { kind: PerfKind; kindReason: string | null; dataReal: boolean | null; dataReason: string | null } {
  if (!value || typeof value.kind !== "string") {
    return { kind: "unknown", kindReason: PERF_LABEL_MISSING_REASON,
             dataReal: null, dataReason: null };
  }
  if (!isKnownKind(value.kind)) {
    return {
      kind: "unknown",
      kindReason: `알아보지 못한 종류예요(본 값: ${JSON.stringify(value.kind)})`,
      dataReal: value.data_real ?? null,
      dataReason: value.data_reason ?? null,
    };
  }
  return {
    kind: value.kind,
    kindReason: value.kind_reason ?? null,
    dataReal: value.data_real ?? null,
    dataReason: value.data_reason ?? null,
  };
}

const DATA_TEXT = (real: boolean | null) =>
  real === true ? "실데이터" : real === false ? "합성데이터" : "데이터 미상";

export interface PerfLabelProps {
  /** 응답이 실은 `perf_label`. 없으면 `unknown` 을 그린다. */
  value?: PerfLabelValue | null;
  /** 여럿을 나란히 그릴 때 무엇의 라벨인지 (예: `"A"`, 전략명). */
  scope?: string;
  /** 사유 문장을 접는다 — 표 헤더처럼 자리가 좁을 때. 툴팁에는 남는다. */
  compact?: boolean;
}

/**
 * 성과 상태 라벨.
 *
 * ```tsx
 * import { PerfLabel } from "@/shared/ui/PerfLabel";
 * <PerfLabel value={run.perf_label} scope="A" />
 * ```
 *
 * ★배럴(`@/shared/ui`)로 import 하지 않는다★ — 그 배럴은 무게 경고가 붙어 있다.
 */
export function PerfLabel({ value, scope, compact = false }: PerfLabelProps) {
  const { kind, kindReason, dataReal, dataReason } = resolvePerfLabel(value);
  const reasons = [kindReason, dataReason].filter(Boolean) as string[];
  const title = [KIND_HINT[kind], ...reasons].join(" · ");

  return (
    <span className={`perf-label perf-label--${kind}`} title={title}>
      {scope && <span className="perf-label__scope">{scope}</span>}
      <span className="perf-label__kind">{KIND_TEXT[kind]}</span>
      <span className="perf-label__data">{DATA_TEXT(dataReal)}</span>
      {!compact && reasons.length > 0 && (
        <span className="perf-label__why">{reasons.join(" · ")}</span>
      )}
    </span>
  );
}

export default PerfLabel;
