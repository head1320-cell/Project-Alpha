"use client";
// 01 CONSTRUCT — 자산 구성. 좌 컨트롤 패널(PortfolioBuilder / FactorBuilder / StrategyLibrary)
// 우 결과 패널: ALLOCATION MAP(스트립 + 도넛 + 범례) · WEIGHT COMPARISON(표) ·
// CONCENTRATION(HHI / 유효 종목수 / TOP3) · DATA COVERAGE.
import React, { useMemo, useState } from "react";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { PortfolioBuilder } from "@/widgets/allocation/PortfolioBuilder";
import { FactorBuilder } from "@/widgets/allocation/FactorBuilder";
import { StrategyLibrary } from "@/widgets/allocation/StrategyLibrary";
import { SleeveStudio } from "@/widgets/allocation/SleeveStudio";
import {
  AllocationDonut, AllocationMap, WeightComparison, concentration, type CmpRow,
} from "@/widgets/allocation/parts";
import { Badge } from "@/shared/ui/shadcn/badge";

type ConstructMode = "direct" | "factor" | "strategy";

export default function ConstructStage() {
  const {
    holdings, setHoldingsReset, loadStudy, studiesVersion, result, goal,
    loadedStrategy, clearLoadedStrategy, freshness,
  } = useAllocation();
  // 매크로 전략 목표로 진입했거나 이미 전략을 불러온 상태면 전략 모드로 착지
  const [mode, setMode] = useState<ConstructMode>(
    goal?.id === "strategy" || !!loadedStrategy ? "strategy" : "direct");

  // ★`?? 0` 을 없앴다★ 예전에는 최적화 전에도 캡가중·최적화가 `0` 으로 채워져서,
  // "아직 계산 안 함"과 "시장 비중이 정말 0%"가 화면에서 같은 모양이었다.
  // null 로 두면 표가 '미계산'이라고 쓴다 — 이 저장소의 0 ≠ 미계산 원칙 그대로다.
  const cmpRows: CmpRow[] = useMemo(() => holdings.map((h) => ({
    code: h.code, name: h.name,
    current: h.weight,
    market: result ? result.flow.market[h.code] ?? null : null,
    optimized: result ? result.weights.optimized[h.code] ?? null : null,
  })), [holdings, result]);

  const conc = useMemo(() => concentration(holdings.map((h) => h.weight)), [holdings]);

  // ★하드코딩된 가짜 커버리지를 제거했다★
  // 예전 폴백은 `"2019-07-17 ~ 2026-07-16 · 1,712 거래일"` 이라는 **문자열 리터럴**이었다.
  // 결과가 없을 때 이 값이 `.num` 서체로 렌더돼, 실제로 측정된 범위와 구분이 안 됐다.
  // 지어낸 수치를 사실처럼 적지 않는다(CLAUDE.md) — 없으면 없다고 쓴다.
  const cov = result
    ? `${result.coverage.start} ~ ${result.coverage.end} · ${result.coverage.n_obs} 거래일`
    : null;

  // 결과가 낡았으면 우측 패널이 그 사실을 말한다. 흐리게 만들지는 않는다 —
  // 50% 로 흐린 숫자는 AA 아래로 떨어지고, 그래도 여전히 읽히는 틀린 숫자다(A1).
  const stale = freshness.kind === "superseded";

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
              onChange={setHoldingsReset} onLoadStudy={loadStudy}
              optimized={result ? result.weights.optimized : null} />
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
          <div className="as-card-title">
            ALLOCATION MAP <span className="as-note-inline">현재 비중 · 블록·조각 = 비중 비례</span>
          </div>
          {holdings.length ? (
            <div className="as-alloc2">
              <AllocationMap items={holdings} />
              <AllocationDonut items={holdings} />
            </div>
          ) : <div className="as-empty">좌측에서 자산을 추가하세요 (2개 이상).</div>}
        </section>

        <section className="as-card">
          <div className="as-card-title">
            WEIGHT COMPARISON
            {/* 낡음은 중립(secondary)이 아니라 경고다 — ContextStrip 의 `미반영 변경`
                칩과 **같은 variant** 를 쓴다. 한 화면에 상태 배지 두 벌을 두지 않는다. */}
            {stale && <Badge variant="warn" className="as-stale-b">재계산 필요</Badge>}
          </div>
          {cmpRows.length ? <WeightComparison rows={cmpRows} />
            : <div className="as-empty">자산 추가 후 표시</div>}
          {!result && cmpRows.length > 0 && (
            <div className="as-note">캡가중·최적화 열은 상단 Re-optimize 실행 후 채워집니다.</div>
          )}
          {stale && (
            <div className="as-note">입력이 바뀐 뒤 재계산되지 않았습니다 — 캡가중·최적화 열은 이전 입력의 결과입니다.</div>
          )}
        </section>

        {/* ★두 카드를 한 장으로★ 값 4개에 `.as-card` 헤더 두 개를 쓰던 자리다.
            크롬이 데이터보다 많으면 밀도가 아니라 소음이다. */}
        <section className="as-card">
          <div className="as-card-title">CONCENTRATION &amp; COVERAGE</div>
          <div className="as-stats">
            <div className="as-stat">
              <span className="as-stat-k">HHI</span>
              <b className="as-stat-v num">{conc.hhi.toLocaleString(undefined, { maximumFractionDigits: 0 })}</b>
              <span className="as-stat-x">Σw² × 10,000 · 낮을수록 분산</span>
            </div>
            {/* ★임의 임계값을 만들지 않는다★ HHI 에 "1,500 미만이면 양호" 같은 밴드를
                붙이고 싶어지지만, 그건 반독점 심사 기준이지 포트폴리오 기준이 아니다.
                대신 **이미 참인 것**을 나란히 둔다 — 유효 6.2 / 보유 10종목 은
                설명이 필요 없고 지어낸 값이 하나도 없다. */}
            <div className="as-stat">
              <span className="as-stat-k">유효 종목수</span>
              <b className="as-stat-v num">{conc.neff.toFixed(1)}</b>
              <span className="as-stat-x num">
                {holdings.length ? `보유 ${holdings.length}종목 중` : "보유 없음"}
              </span>
            </div>
            <div className="as-stat">
              <span className="as-stat-k">TOP3 비중</span>
              <b className="as-stat-v num">{conc.top3.toFixed(1)}%</b>
              {/* 비율은 막대로도 — 숫자만으로는 100% 대비 위치가 안 읽힌다. */}
              <span className="as-conc-bar" aria-hidden="true">
                <i style={{ width: `${Math.min(100, conc.top3).toFixed(1)}%` }} />
              </span>
            </div>
          </div>
          <div className="as-conc-cov">
            <span className="as-stat-k">데이터 커버리지</span>
            {cov
              ? <span className="num as-cov">{cov}</span>
              : <span className="as-empty">최적화 실행 전에는 측정되지 않습니다.</span>}
          </div>
          <div className="as-note">
            유효 종목수 = 10,000 / HHI. 시총 미보유 자산은 중앙값 대체(캡가중 prior) ·
            팩터 결측 자산은 재정규화.
          </div>
        </section>

        {/* ★고급 설정은 접어 둔다★ SleeveStudio 는 슬리브 저장·결합·리스크예산·상관·군집을
            한꺼번에 펼치는 141줄짜리 패널이다. 자산을 담는 것이 목적인 화면에서 이게 늘
            펼쳐져 있으면 본 작업이 스크롤 아래로 밀린다. 네이티브 <details> 라 JS 0,
            키보드 접근은 기본 제공 — 랜딩 FAQ 가 쓰는 것과 같은 방식이다. */}
        <details className="as-adv">
          <summary className="as-adv-s">고급 — 슬리브 스튜디오 <span className="as-note-inline">전략 결합 · 리스크 예산 · 상관/군집</span></summary>
          <div className="as-adv-b"><SleeveStudio /></div>
        </details>
      </main>
    </div>
  );
}
