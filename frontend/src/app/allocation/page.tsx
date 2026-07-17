"use client";
// Central Hub (Master Cockpit) — 전체 워크플로우 요약. 각 위젯 우측 [↗]로
// 해당 마이크로 워크스페이스로 드릴다운 (Master-Detail 패턴).
import React from "react";
import Link from "next/link";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { ResearchTimeline } from "@/components/allocation/ResearchTimeline";
import {
  FactorXRayBars, FrontierChart, RiskContribDonut, fmtSign,
} from "@/components/allocation/parts";

function HubCard({ title, to, children }: { title: string; to?: string; children: React.ReactNode }) {
  return (
    <section className="as-card">
      <div className="as-card-title">
        {title}
        {to && <Link href={to} className="as-expand" title="워크스페이스로 확장">↗</Link>}
      </div>
      {children}
    </section>
  );
}

export default function AllocationHub() {
  const {
    holdings, result, canRun, pending, runAnalyze, xrayQ, stressQ, timeline, delta,
  } = useAllocation();
  const totalW = holdings.reduce((a, h) => a + h.weight, 0);

  return (
    <div className="as-hub">
      {/* 실행 바 */}
      <div className="as-hub-bar">
        <span className="as-note-inline">
          {holdings.length
            ? `포트폴리오 ${holdings.length}종목 · 합 ${totalW.toFixed(1)}%`
            : "Thesis 워크스페이스에서 자산을 추가하세요 (2개 이상)"}
        </span>
        {result && (
          <span className="as-coverage num">
            {(result.coverage as { source?: string }).source === "mock" && (
              <span className="as-badge" style={{ color: "#a16207", borderColor: "#a16207", marginRight: 6 }}>MOCK 데이터</span>
            )}
            {result.coverage.start} ~ {result.coverage.end} · {result.coverage.n_obs}일
          </span>
        )}
        <button className="as-run" style={{ maxWidth: 180, marginLeft: "auto" }}
          disabled={!canRun || pending} onClick={() => runAnalyze()}>
          {pending ? "최적화 중…" : "Re-optimize"}
        </button>
      </div>

      <div className="as-hub-grid">
        <HubCard title="PORTFOLIO" to="/allocation/thesis">
          {holdings.length === 0 && <div className="as-empty">자산 없음 — Thesis에서 구성</div>}
          {holdings.slice(0, 6).map((h) => (
            <div key={h.code} className="as-wrow">
              <span className="as-wrow-nm">{h.name}</span>
              <div className="as-wrow-bar"><i style={{ width: `${Math.min(h.weight, 100)}%` }} /></div>
              <span className="num">{h.weight.toFixed(1)}%</span>
            </div>
          ))}
          {holdings.length > 6 && <div className="as-note">+{holdings.length - 6}종목</div>}
        </HubCard>

        <HubCard title="EFFICIENT FRONTIER" to="/allocation/optimizer">
          {result ? <FrontierChart result={result} lam={delta} height={210} />
            : <div className="as-empty" style={{ height: 210, display: "flex", alignItems: "center", justifyContent: "center" }}>Re-optimize 실행 시 표시</div>}
        </HubCard>

        <HubCard title="OPTIMIZED WEIGHTS" to="/allocation/explainability">
          {result ? Object.entries(result.weights.optimized).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([c, w]) => (
            <div key={c} className="as-wrow">
              <span className="as-wrow-nm">{result.labels[c] || c}</span>
              <div className="as-wrow-bar"><i style={{ width: `${Math.min(w, 100)}%` }} /></div>
              <span className="num">{w.toFixed(1)}%</span>
            </div>
          )) : <div className="as-empty">Re-optimize 실행 시 표시</div>}
        </HubCard>

        <HubCard title="FACTOR EXPOSURE" to="/allocation/thesis">
          {xrayQ.data?.factors?.length
            ? <FactorXRayBars factors={xrayQ.data.factors.slice(0, 6)} />
            : <div className="as-empty">{holdings.length ? "계산 중…" : "포트폴리오 구성 후 표시"}</div>}
        </HubCard>

        <HubCard title="ROBUSTNESS" to="/allocation/robustness">
          {stressQ.data?.available && stressQ.data.mode === "hypothetical" && (
            <div className="as-robust-row">
              <span>{stressQ.data.label}</span>
              <span>추정 충격 <b className="num" style={{ color: (stressQ.data.portfolio_shock_pct ?? 0) >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(stressQ.data.portfolio_shock_pct ?? 0, 1)}%</b></span>
            </div>
          )}
          {stressQ.data?.available && stressQ.data.mode === "historical" && (
            <div className="as-robust-row">
              <span>{stressQ.data.label}</span>
              <span>최대낙폭 <b className="num" style={{ color: "var(--color-bear)" }}>{stressQ.data.max_dd_pct?.toFixed(1)}%</b></span>
            </div>
          )}
          {!stressQ.data?.available && <div className="as-empty">{holdings.length ? "시나리오 계산 중…" : "포트폴리오 구성 후 표시"}</div>}
          <div className="as-note">기댓값 변동 → 비중 민감도 히트맵은 Robustness 워크스페이스에서</div>
        </HubCard>

        <HubCard title="RISK CONTRIBUTION" to="/allocation/explainability">
          {result ? <RiskContribDonut contributions={result.risk_contributions} labels={result.labels} size={104} />
            : <div className="as-empty">Re-optimize 실행 시 표시</div>}
        </HubCard>

        <HubCard title="RESEARCH TIMELINE" to="/allocation/journal">
          <ResearchTimeline events={timeline.slice(0, 6)} />
        </HubCard>
      </div>
    </div>
  );
}
