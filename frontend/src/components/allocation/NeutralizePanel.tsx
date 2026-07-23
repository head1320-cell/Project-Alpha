"use client";
// NeutralizePanel — 베타/섹터 중립화 (Full Expansion P3 잔여, Optimize 스테이지)
//   최적화된 비중을 베타중립/섹터중립으로 변환 → 달성 노출 리포트 → 포트폴리오 적용.
//   롱온리 베타중립 불가 시 정직 표기(롱숏 필요).
import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { sleeveApi, type NeutralizeResult } from "@/lib/sleeveApi";
import { useAllocation } from "./AllocationProvider";

export function NeutralizePanel() {
  const { result, holdingsMap, setHoldingsReset, holdings, logEvent } = useAllocation();
  const [mode, setMode] = useState<"beta" | "sector" | "both">("beta");
  const [dollarNeutral, setDollarNeutral] = useState(true);
  const [targetBeta, setTargetBeta] = useState(0);
  const [res, setRes] = useState<NeutralizeResult | null>(null);

  const src = result ? result.weights.optimized : holdingsMap;

  const mut = useMutation({
    mutationFn: () => sleeveApi.neutralize({ weights: src, mode, target_beta: targetBeta, dollar_neutral: dollarNeutral }),
    onSuccess: (d) => { setRes(d); logEvent(`중립화 — ${mode} (β목표 ${targetBeta})`); },
  });

  const apply = () => {
    if (!res?.weights) return;
    const nameOf = (c: string) => holdings.find((h) => h.code === c)?.name || result?.labels[c] || c;
    setHoldingsReset(Object.entries(res.weights).filter(([, w]) => Math.abs(w) > 1e-6)
      .map(([code, w]) => ({ code, name: nameOf(code), weight: w })));
    logEvent("중립화 비중 적용");
  };

  const b = res?.beta;
  const s = res?.sector;

  return (
    <section className="as-card as-neu">
      <div className="as-card-title">중립화 <span className="as-note-inline">베타/섹터 노출 제거</span></div>
      {Object.keys(src).length < 2 ? (
        <div className="as-empty">최적화 결과(2자산 이상)가 필요합니다.</div>
      ) : (
        <>
          <div className="as-neu-ctrl">
            <div className="as-seg as-seg-3">
              {(["beta", "sector", "both"] as const).map((m) => (
                <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
                  {m === "beta" ? "베타" : m === "sector" ? "섹터" : "둘다"}
                </button>
              ))}
            </div>
            {mode !== "sector" && (
              <label className="as-neu-opt">
                <input type="checkbox" checked={dollarNeutral} onChange={(e) => setDollarNeutral(e.target.checked)} />
                롱숏 허용(달러중립)
              </label>
            )}
            {mode !== "sector" && (
              <label className="as-neu-beta">목표 β
                <input className="num" type="number" step={0.1} value={targetBeta}
                  onChange={(e) => setTargetBeta(Number(e.target.value) || 0)} />
              </label>
            )}
            <button className="as-fb-apply" disabled={mut.isPending} onClick={() => mut.mutate()}>
              {mut.isPending ? "…" : "중립화"}
            </button>
          </div>

          {b && !b.error && (
            <div className="as-neu-rep">
              <span>베타 {b.achieved_beta} / 목표 {b.target_beta}
                {b.beta_hit ? <b className="as-neu-ok"> ✓달성</b> : <b className="as-neu-bad"> 미달</b>}</span>
              {!b.long_only_feasible && <div className="as-neu-warn">롱온리 불가 — 롱숏 필요(정직). {b.note}</div>}
            </div>
          )}
          {b?.error && <div className="as-note">{b.message}</div>}
          {s && !s.error && (
            <div className="as-neu-rep">
              <div className="as-note-inline">섹터 비중(후):</div>
              {Object.entries(s.sector_after_pct ?? {}).map(([sec, w]) => (
                <span key={sec} className="as-chip sm">{sec} <b className="num">{w}%</b></span>
              ))}
              <span className={s.neutral ? "as-neu-ok" : "as-neu-bad"}>{s.neutral ? "균등 달성" : `편차 ${s.max_deviation_pct}%`}</span>
            </div>
          )}
          {res && (
            <button className="as-chip on" onClick={apply}>중립화 비중 → 포트폴리오 적용</button>
          )}
          <div className="as-note">중립화는 최적화 비중을 변환합니다 — 적용 후 재최적화하면 다시 원 모델 배분으로 돌아갑니다(설계).</div>
        </>
      )}
    </section>
  );
}
