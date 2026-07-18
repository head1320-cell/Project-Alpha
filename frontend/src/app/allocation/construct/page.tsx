"use client";
// 01 CONSTRUCT — 자산 구성. 좌 PortfolioBuilder / 우 ALLOCATION MAP · WEIGHT
// COMPARISON(현재/캡가중/최적) · CONCENTRATION(HHI·TOP3·Neff) · DATA COVERAGE.
import React, { useMemo } from "react";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { PortfolioBuilder } from "@/components/allocation/PortfolioBuilder";
import { AllocationMap, WeightComparison, concentration } from "@/components/allocation/parts";

export default function ConstructStage() {
  const { holdings, setHoldingsReset, loadStudy, studiesVersion, result } = useAllocation();

  const cmpRows = useMemo(() => holdings.map((h) => ({
    code: h.code, name: h.name,
    current: h.weight,
    market: result?.flow.market[h.code] ?? 0,
    optimized: result?.weights.optimized[h.code] ?? 0,
  })), [holdings, result]);

  const conc = useMemo(() => concentration(holdings.map((h) => h.weight)), [holdings]);
  const cov = result
    ? `${result.coverage.start} ~ ${result.coverage.end} · ${result.coverage.n_obs} 거래일`
    : "2019-07-17 ~ 2026-07-16 · 1,712 거래일";

  return (
    <div className="as-ws2">
      <aside>
        <PortfolioBuilder holdings={holdings} studiesVersion={studiesVersion}
          onChange={setHoldingsReset} onLoadStudy={loadStudy} />
      </aside>
      <main className="as-center">
        <section className="as-card">
          <div className="as-card-title">ALLOCATION MAP <span className="as-note-inline">현재 비중 · 블록 = 비중 비례</span></div>
          {holdings.length ? <AllocationMap items={holdings} />
            : <div className="as-empty">좌측에서 자산을 추가하세요 (2개 이상).</div>}
        </section>
        <section className="as-card">
          <div className="as-card-title">WEIGHT COMPARISON <span className="as-note-inline">■ 현재 · ■ 캡가중 시장 · ■ 최적화</span></div>
          {cmpRows.length ? <WeightComparison rows={cmpRows} />
            : <div className="as-empty">자산 추가 후 표시</div>}
          {!result && cmpRows.length > 0 && (
            <div className="as-note">캡가중·최적화 비교는 상단 Re-optimize 실행 후 채워집니다.</div>
          )}
        </section>
        <div className="as-mid2">
          <section className="as-card">
            <div className="as-card-title">CONCENTRATION</div>
            <div className="aas-conc">
              <span>HHI <b>{conc.hhi.toLocaleString(undefined, { maximumFractionDigits: 0 })}</b></span>
              <span>TOP3 <b>{conc.top3.toFixed(1)}%</b></span>
              <span>유효 종목수 <b>{conc.neff.toFixed(1)}</b></span>
            </div>
            <div className="as-note">HHI = Σw² × 10,000 — 낮을수록 분산. 유효 종목수 = 10,000 / HHI.</div>
          </section>
          <section className="as-card">
            <div className="as-card-title">DATA COVERAGE</div>
            <div className="num" style={{ fontSize: 10.5 }}>{cov}</div>
            <div className="as-note">시총 미보유 자산은 중앙값 대체(캡가중 prior). 팩터 결측 자산은 재정규화.</div>
          </section>
        </div>
      </main>
    </div>
  );
}
