"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 시나리오 × 3자 비교 — 이 충격이 왔을 때 타이밍이 얼마나 덜 맞는가 (스펙 §5 × Phase 7b).
//
// ★두 번째 3자 비교를 만들지 않는다★
// 다리(기준·타이밍만·타이밍+매크로)는 타이밍 데스크와 **같은** 백엔드 파생에서 온다.
// 여기서 하는 일은 그 노출을 시나리오 손실에 곱해 보여주는 것뿐이고, 규칙 구성도
// `ThreeWayPanel` 과 똑같은 방식으로 `timingCfg` 에서 뽑는다 — 두 화면이 서로 다른 규칙으로
// "같은 비교" 를 그리면 사용자는 어느 쪽을 믿어야 할지 알 수 없다.
//
// ★선형 근사라는 것을 숨기지 않는다★
// 노출을 줄인 포트폴리오는 상관 구조도 달라진다. 이 곱셈은 그것을 반영하지 못하고,
// 그 사실은 백엔드가 준 문장을 그대로 화면에 적는다.
//
// ★판정하지 못한 다리에는 숫자가 없다★
// 매크로 스냅샷이 없으면 세 번째 다리는 노출 0 의 unavailable 이다. 거기에 0% 손실을
// 적으면 만들지 못한 비교가 셋 중 가장 안전해 보인다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  allocationApi, MODEL_TYPE_SHORT,
  type ScenarioLeg, type TimingRuleSpec,
} from "@/entities/allocation/api";
import { useAllocation } from "./AllocationProvider";

const LEG_LABEL: Record<string, string> = {
  baseline: "기준 (타이밍 없음)",
  timing_only: "타이밍만",
  timing_macro: "타이밍 + 매크로",
};

function Leg({ name, leg }: { name: string; leg: ScenarioLeg }) {
  // ★유한한 숫자일 때만 숫자로 그린다★ 백엔드는 NaN·inf 를 null 로 내려보내는데, 여기서
  // `?? 0` 으로 받으면 그 다리가 "손실 0" 으로 보인다 — 값이 없는 것과 0 은 다른 사실이다.
  const loss = leg.shock_pct;
  const judged = typeof loss === "number" && Number.isFinite(loss)
    && typeof leg.exposure === "number" && Number.isFinite(leg.exposure);
  return (
    <div className={`as-s3w-leg ${name}`}>
      <div className="as-s3w-nm">{LEG_LABEL[name] ?? name}</div>
      {judged ? (
        <>
          <b className={`as-s3w-loss num ${(loss as number) < 0 ? "neg" : "pos"}`}>
            {(loss as number).toFixed(1)}%
          </b>
          <div className="as-s3w-exp num">
            노출 {Math.round((leg.exposure as number) * 100)}%
            {typeof leg.cash_pct === "number" && ` · 현금 ${leg.cash_pct.toFixed(0)}%`}
          </div>
        </>
      ) : (
        // 노출 0(현금)과 "알 수 없음" 은 다른 사실이다 — 같은 0% 로 적으면 구별이 사라진다.
        <div className="as-s3w-na">{leg.reason || "판정 불가 — 손실을 계산하지 않습니다"}</div>
      )}
    </div>
  );
}

export function ScenarioThreeWay({ packId, holdings, severity }: {
  packId: string;
  holdings: Record<string, number>;
  severity: number;
}) {
  const { timingCfg, attachedSnapshotId } = useAllocation();

  const catQ = useQuery({
    queryKey: ["allocation", "timing-factors"],
    queryFn: () => allocationApi.timingFactors(),
    staleTime: Infinity,
  });
  const catalogIds = useMemo(() => {
    const s = new Set<string>();
    (catQ.data?.groups ?? []).forEach((g) => g.factors.forEach((f) => s.add(f.id)));
    return s;
  }, [catQ.data]);

  // V2 엔진은 카탈로그 팩터만 평가한다 — 레거시 카나리 신호는 조용히 섞지 않고 제외한다
  // (`ThreeWayPanel` 과 같은 규칙: 두 화면의 "타이밍" 이 다른 것을 뜻하면 안 된다).
  const rules: TimingRuleSpec[] = useMemo(
    () => timingCfg.canaries
      .filter((c) => catalogIds.has(c.signal))
      .map((c) => ({
        factor_id: c.signal,
        universe: c.id ? [c.id] : [],
        params: c.params,
        threshold: c.threshold,
      } as TimingRuleSpec)),
    [timingCfg.canaries, catalogIds]);

  const holdingsKey = JSON.stringify(holdings);
  const q = useQuery({
    queryKey: ["allocation", "scenario-three-way", packId, holdingsKey, severity,
      timingCfg.market, JSON.stringify(rules), attachedSnapshotId],
    queryFn: () => allocationApi.scenarioThreeWay({
      holdings, pack_id: packId, severity,
      market: timingCfg.market, combination: "continuous",
      rules: rules as unknown as Record<string, unknown>[],
      regime_snapshot_id: attachedSnapshotId,
    }),
    enabled: rules.length > 0 && Object.keys(holdings).length > 0 && !!packId,
    retry: false,          // 422(정직한 거부)를 재시도하는 것은 의미가 없다
  });

  return (
    <section className={`as-card as-s3w${q.isLoading ? " as-loading" : ""}`}>
      <div className="as-card-title">
        시나리오 × 3자 비교 <span className="as-note-inline">이 충격에서 타이밍이 무엇을 바꾸나</span>
      </div>

      {rules.length === 0 && (
        <div className="as-empty">
          02 TIMING 에서 카탈로그 팩터를 하나 이상 추가하면 비교가 표시됩니다.
        </div>
      )}
      {rules.length > 0 && Object.keys(holdings).length === 0 && (
        <div className="as-empty">01 CONSTRUCT에서 포트폴리오를 구성하세요 →</div>
      )}
      {q.isError && <div className="as-err">비교를 불러오지 못했습니다.</div>}

      {q.data && (
        <>
          <div className="as-s3w-hd">
            <span className="as-s3w-pack">{q.data.pack.label}</span>
            {/* ★결과 옆의 model_type★ 카탈로그에만 있으면 숫자를 보는 자리에서 사라진다. */}
            <span className={`as-model-type mt-${q.data.model_type}`}>
              {MODEL_TYPE_SHORT[q.data.model_type]}
            </span>
            <span className="as-s3w-basis">{q.data.scenario.shock_basis}</span>
          </div>

          {q.data.composed ? (
            <div className="as-s3w-legs">
              {Object.entries(q.data.legs).map(([name, leg]) => (
                <Leg key={name} name={name} leg={leg} />
              ))}
            </div>
          ) : (
            <div className="as-empty">
              {q.data.scenario.reason
                || "이 시나리오의 충격을 구하지 못해 다리별 손실을 계산하지 않습니다 (0으로 채우지 않습니다)."}
            </div>
          )}

          {q.data.conflict && <div className="as-note as-s3w-conflict">{q.data.conflict}</div>}
          <div className="as-note">{q.data.composition_note}</div>
          <div className="as-note-inline num">{q.data.identity}</div>
        </>
      )}
    </section>
  );
}
