"use client";
// 01 CONSTRUCT — 자산 구성. 좌 직접 구성(PortfolioBuilder) | 팩터 빌더(FactorBuilder) /
// 우 ALLOCATION MAP · WEIGHT COMPARISON(현재/캡가중/최적) · CONCENTRATION · DATA COVERAGE.
import React, { useMemo, useState } from "react";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { PortfolioBuilder } from "@/widgets/allocation/PortfolioBuilder";
import { FactorBuilder } from "@/widgets/allocation/FactorBuilder";
import { StrategyLibrary } from "@/widgets/allocation/StrategyLibrary";
import { SleeveStudio } from "@/widgets/allocation/SleeveStudio";
import { AllocationMap, WeightComparison, concentration } from "@/widgets/allocation/parts";

type ConstructMode = "direct" | "factor" | "strategy";

export default function ConstructStage() {
  const { holdings, setHoldingsReset, loadStudy, studiesVersion, result, goal, loadedStrategy, clearLoadedStrategy } = useAllocation();
  // 매크로 전략 목표로 진입했거나 이미 전략을 불러온 상태면 전략 모드로 착지
  const [mode, setMode] = useState<ConstructMode>(
    goal?.id === "strategy" || !!loadedStrategy ? "strategy" : "direct");

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
        <div className="as-seg as-fb-mode as-seg-3">
          <button className={mode === "direct" ? "on" : ""} onClick={() => setMode("direct")}>직접 구성</button>
          <button className={mode === "factor" ? "on" : ""} onClick={() => setMode("factor")}>팩터 빌더</button>
          <button className={mode === "strategy" ? "on" : ""} onClick={() => setMode("strategy")}>매크로 전략</button>
        </div>
        {mode === "direct"
          ? <PortfolioBuilder holdings={holdings} studiesVersion={studiesVersion}
              onChange={setHoldingsReset} onLoadStudy={loadStudy} />
          : mode === "factor"
            ? <FactorBuilder holdings={holdings} onApply={setHoldingsReset} />
            : <StrategyLibrary />}
      </aside>
      <main className="as-center">
        {loadedStrategy && (
          <div className="as-sl-banner">
            <span className="as-sl-banner-badge">매크로 전략</span>
            <span className="as-sl-banner-name">{loadedStrategy.name}</span>
            <span className="as-sl-banner-sig num">{loadedStrategy.signal}</span>
            <span className="as-note-inline">현재 비중 = 전략 원본 · 캡가중/최적화와 비교 후 재최적화 가능</span>
            <button className="as-sl-banner-x" title="전략 출처 해제" onClick={clearLoadedStrategy}>✕ 해제</button>
          </div>
        )}
        <section className="as-card">
          <div className="as-card-title">ALLOCATION MAP <span className="as-note-inline">현재 비중 · 블록 = 비중 비례</span></div>
          {holdings.length ? <AllocationMap items={holdings} />
            : <div className="as-empty">좌측에서 자산을 추가하세요 (2개 이상).</div>}
        </section>
        <section className="as-card">
          <div className="as-card-title">WEIGHT COMPARISON <span className="as-note-inline">■ {loadedStrategy ? "전략 원본" : "현재"} · ■ 캡가중 시장 · ■ 최적화</span></div>
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
        <SleeveStudio />
      </main>
    </div>
  );
}
