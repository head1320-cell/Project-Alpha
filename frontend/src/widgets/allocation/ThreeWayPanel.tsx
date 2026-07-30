"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 3자 비교 — 기준 vs 타이밍만 vs 타이밍+매크로 (스펙 §8, Phase 7b).
//
// 이 패널이 답하는 질문은 "타이밍이 값을 하는가" 와 "매크로가 무엇을 바꿨는가" 두 개다.
// 기준(타이밍 없음)을 함께 그리지 않으면 타이밍 결과가 좋은지 나쁜지 알 수 없다.
//
// ★매크로는 노출을 줄이기만 한다 (one-way)★ 그리고 **끌 수 있다.**
// 끄면 타이밍 단독과 정확히 같아져야 한다 — 그것이 "조용한 오버라이드가 아니다" 의 실질이고,
// 토글이 장식이 아니라는 증거다.
//
// 오버레이의 출처는 **붙어 있는 국면 스냅샷**이다(라이브 매크로가 아니다). 스냅샷이 없으면
// 세 번째 다리를 지어내지 않고 사유를 적는다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  allocationApi, type CanaryInput, type SignalStateValue,
  type ThreeWayLeg, type TimingRuleSpec,
} from "@/entities/allocation/api";

const STATE_LABEL: Record<SignalStateValue, string> = {
  risk_on: "위험-온",
  risk_off: "위험-오프",
  // 결측은 위험-오프와 **다른 사실**이다 — 같은 말로 적으면 구별이 사라진다.
  unavailable: "판정 불가",
};

const LEG_LABEL: Record<string, string> = {
  baseline: "기준 (타이밍 없음)",
  timing_only: "타이밍만",
  timing_macro: "타이밍 + 매크로",
};

/** 조합 방식 — 백엔드 `COMBINATION_METHODS` 중 이 화면에서 고를 수 있는 것들. */
const COMBOS: { id: string; label: string }[] = [
  { id: "all", label: "전부 통과" },
  { id: "any", label: "하나라도" },
  { id: "continuous", label: "연속 비중" },
  { id: "regime_conditioned", label: "국면 조건부" },
];

function Leg({ name, leg }: { name: string; leg: ThreeWayLeg }) {
  const pct = Math.round(Math.max(0, Math.min(1, leg.exposure)) * 100);
  return (
    <div className={`as-3w-leg ${name}`}>
      <div className="as-3w-leg-hd">
        <span className="as-3w-leg-nm">{LEG_LABEL[name] ?? name}</span>
        <span className={`as-3w-state ${leg.state}`}>{STATE_LABEL[leg.state]}</span>
      </div>
      <div className="as-3w-exp">
        <b className="num">{pct}%</b>
        <span className="as-note-inline">위험자산 노출</span>
      </div>
      <div className="as-3w-bar"><i style={{ width: `${pct}%` }} /></div>
      {/* 팩터 집계는 세 다리가 공유한다 — 기준선만 타이밍을 쓰지 않으므로 뺀다. */}
      {name !== "baseline" && (
        <div className="as-3w-counts num">
          통과 {leg.on_count} · 이탈 {leg.off_count} · 결측 {leg.unavailable_count}
        </div>
      )}
      <p className="as-3w-why">{leg.explanation}</p>
    </div>
  );
}

export function ThreeWayPanel({
  canaries, market, snapshotId,
}: {
  canaries: CanaryInput[];
  market: "kr" | "us";
  /** 붙어 있는 국면 스냅샷 ID. null 이면 매크로 다리는 정직하게 판정 불가로 온다. */
  snapshotId: string | null;
}) {
  const [overlayOn, setOverlayOn] = useState(true);
  const [combination, setCombination] = useState("continuous");

  // 카탈로그가 팩터 id 의 단일 진실 — 프론트에 목록을 복제하지 않는다.
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

  // V2 엔진은 카탈로그 팩터만 평가한다. 레거시 카나리 신호(score_13612·ma_day…)는
  // 3-상태 판정 대상이 아니므로 **조용히 섞지 않고** 제외하고, 몇 개를 뺐는지 밝힌다.
  const rules: TimingRuleSpec[] = useMemo(
    () => canaries
      .filter((c) => catalogIds.has(c.signal))
      // 임계는 사용자가 고른 값을 그대로 보낸다 — 과거 미리보기와 같은 뜻이어야 한다.
      // 방향은 보내지 않는다(카탈로그 소유).
      .map((c) => ({
        factor_id: c.signal,
        universe: c.id ? [c.id] : [],
        params: c.params,
        threshold: c.threshold,
      } as TimingRuleSpec)),
    [canaries, catalogIds]);
  const skipped = canaries.length - rules.length;

  const q = useQuery({
    queryKey: ["allocation", "timing-three-way", market, combination, overlayOn,
      snapshotId, JSON.stringify(rules)],
    queryFn: () => allocationApi.timingThreeWay({
      market, combination, rules,
      regime_snapshot_id: snapshotId,
      overlay_enabled: overlayOn,
    }),
    enabled: rules.length > 0,
    retry: false,          // 422(정직한 거부)를 재시도하는 것은 의미가 없다
  });

  const legs = q.data?.legs;
  const ov = q.data?.overlay ?? null;

  return (
    <section className={`as-card as-3w${q.isFetching ? " as-loading" : ""}`}>
      <div className="as-card-title">
        3자 비교
        <span className="as-note-inline">기준 · 타이밍만 · 타이밍+매크로</span>
        <label className="as-3w-toggle" title="매크로 국면 오버레이를 규칙과 독립적으로 끕니다">
          <input type="checkbox" checked={overlayOn}
            onChange={(e) => setOverlayOn(e.target.checked)} />
          <span>매크로 오버레이</span>
        </label>
      </div>

      <div className="as-3w-combo">
        <span className="as-3w-combo-k">조합</span>
        <div className="as-seg">
          {COMBOS.map((c) => (
            <button key={c.id} className={combination === c.id ? "on" : ""}
              onClick={() => setCombination(c.id)}>{c.label}</button>
          ))}
        </div>
      </div>

      {rules.length === 0 && (
        <div className="as-3w-empty as-empty">
          3-상태 판정이 가능한 팩터가 없습니다 — 좌측 &ldquo;팩터 추가&rdquo;로 카탈로그 팩터를
          담으면 비교가 나타납니다. 레거시 카나리 신호(13612 점수·이동평균 등)는 V2 3-상태
          엔진의 평가 대상이 아니므로 이 비교에 섞지 않습니다.
        </div>
      )}
      {q.isError && (
        <div className="as-3w-err as-err">{(q.error as Error).message}</div>
      )}

      {legs && (
        <>
          <div className="as-3w-legs">
            {(["baseline", "timing_only", "timing_macro"] as const).map((n) => (
              <Leg key={n} name={n} leg={legs[n]} />
            ))}
          </div>

          {q.data?.conflict && <div className="as-3w-conflict">{q.data.conflict}</div>}

          {ov ? (
            <div className="as-3w-ov">
              <span className="as-3w-ov-k">매크로 국면</span>
              <b>{ov.regime}</b>
              <span className="num">{ov.recommended_mode}</span>
              <span className="as-note-inline">
                신뢰도 {ov.confidence.toFixed(2)} · 스트레스 {ov.stress_score.toFixed(1)}/100
                {" · "}노출 상한 {ov.exposure_cap.toFixed(2)}
              </span>
              {!ov.usable && (
                <span className="as-3w-ov-na">
                  국면을 읽지 못해 조정에 쓰지 않았습니다 — &ldquo;중립&rdquo;이 아니라 &ldquo;모른다&rdquo;입니다.
                </span>
              )}
              {!ov.enabled && (
                <span className="as-3w-ov-off">껐습니다 — 타이밍 단독 판단이 그대로 적용됩니다.</span>
              )}
            </div>
          ) : (
            <div className="as-3w-ov as-3w-ov-none">
              국면 스냅샷이 붙어 있지 않아 매크로 비교를 만들 수 없습니다 — 03 MACRO 에서
              스냅샷을 적용하면 세 번째 다리가 채워집니다. 비교를 지어내지 않습니다.
            </div>
          )}

          <div className="as-note">
            매크로는 노출을 <b>줄이기만</b> 합니다(one-way). 국면이 좋아 보인다고 노출을 올려
            주면 국면 모델이 틀렸을 때 손실이 증폭됩니다 — 줄이는 실수는 기회를 놓치고, 키우는
            실수는 자본을 잃습니다.
            {skipped > 0 && ` 레거시 카나리 ${skipped}개는 이 비교에서 제외했습니다.`}
          </div>
        </>
      )}
    </section>
  );
}
