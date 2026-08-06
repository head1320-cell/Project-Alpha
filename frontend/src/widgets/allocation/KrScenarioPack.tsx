"use client";
// 국내 시나리오팩 (05 Stress — P3-b) — 7종 KR 시나리오의 팩터 기반 충격.
// 종목·팩터·슬리브별 P&L + VaR/CVaR 프록시 + 상관·변동성·유동성 가정 + 실행 가능성·헤지.
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { allocationApi } from "@/entities/allocation/api";
import { useAllocation } from "./AllocationProvider";

const col = (v: number) => (v >= 0 ? "var(--color-bull)" : "var(--color-bear)");

export function KrScenarioPack({ scenario: controlled, onPick }: {
  /** 통합 시나리오 창이 선택을 주도할 때 — 미지정이면 기존처럼 자체 상태 사용(하위호환). */
  scenario?: string;
  onPick?: (id: string) => void;
} = {}) {
  const { holdingsMap, canRun, severity } = useAllocation();
  const [own, setOwn] = useState("semi_selloff");
  const scenario = controlled ?? own;
  const setScenario = (id: string) => (onPick ? onPick(id) : setOwn(id));

  const catQ = useQuery({
    queryKey: ["allocation", "kr-scen-catalog"],
    queryFn: () => allocationApi.krScenarioCatalog().catch(() => null),
  });
  const codesKey = JSON.stringify(Object.keys(holdingsMap).sort());
  const runQ = useQuery({
    queryKey: ["allocation", "kr-scen", scenario, codesKey, severity],
    queryFn: () => allocationApi.krScenario({ holdings: holdingsMap, scenario, severity }).catch(() => null),
    enabled: canRun && !!scenario,
  });
  const cats = catQ.data?.scenarios ?? [];
  const r = runQ.data && !runQ.data.error ? runQ.data : null;

  return (
    <section className={`as-card${runQ.isLoading ? " as-loading" : ""}`} aria-busy={runQ.isLoading}>
      <div className="as-card-title">국내 시나리오팩 <span className="as-note-inline">7종 · 팩터 기반 충격 · 강도 {severity.toFixed(2)}×</span></div>
      {/* 통합 시나리오 창이 선택을 주도하면 중복 목록은 렌더하지 않는다
          (hidden 속성은 .as-scenario-list의 display:flex에 밀리므로 조건부 렌더) */}
      {!onPick && (
        <div className="as-scenario-list as-krs-list">
          {cats.map((s) => (
            <button key={s.id} title={`${s.description}\n출처: ${s.source}`}
              className={`as-scen${scenario === s.id ? " on" : ""}`} onClick={() => setScenario(s.id)}>
              <span>{s.label}</span>
            </button>
          ))}
        </div>
      )}
      {!canRun && <div className="as-empty">01 CONSTRUCT에서 자산 2개 이상 추가 →</div>}
      {canRun && runQ.isLoading && <div className="as-empty">시나리오 충격 계산 중…</div>}
      {runQ.data?.error && <div className="as-err">{runQ.data.message}</div>}
      {r && (
        <>
          <div className="as-krs-hero">
            <div><em>포트폴리오 충격</em><b className="num" style={{ color: col(r.portfolio_shock_pct ?? 0), fontSize: 20 }}>{r.portfolio_shock_pct}%</b></div>
            <div><em>VaR 95%</em><b className="num" style={{ color: "var(--color-bear)" }}>{r.risk_proxy?.var95_pct}%</b></div>
            <div><em>CVaR 95%</em><b className="num" style={{ color: "var(--color-bear)" }}>{r.risk_proxy?.cvar95_pct}%</b></div>
            <div><em>MDD 프록시</em><b className="num" style={{ color: "var(--color-bear)" }}>{r.risk_proxy?.mdd_proxy_pct}%</b></div>
          </div>
          <div className="as-note">{r.description}</div>

          <div className="as-krs-cols">
            <div>
              <div className="as-krs-h">팩터 귀속 <em>무엇이 때렸나</em></div>
              {(r.factor_attribution ?? []).map((f) => (
                <div key={f.factor} className="as-krs-frow">
                  <span>{f.label}</span>
                  <span className="num" style={{ color: col(f.contribution_pct) }}>{f.contribution_pct >= 0 ? "+" : ""}{f.contribution_pct}%</span>
                </div>
              ))}
            </div>
            <div>
              <div className="as-krs-h">가장 취약한 종목</div>
              {(r.most_vulnerable ?? []).map((v) => (
                <div key={v.stock_code} className="as-krs-frow">
                  <span>{v.corp_name}</span>
                  <span className="num" style={{ color: col(v.shock_pct) }}>{v.shock_pct}%</span>
                </div>
              ))}
            </div>
          </div>

          <div className="as-krs-assume">
            <span>상관 상승 <b className="num">+{r.assumptions?.correlation_rise}</b></span>
            <span>변동성 상승 <b className="num">+{Math.round((r.assumptions?.volatility_rise ?? 0) * 100)}%</b></span>
            <span>유동성 악화 <b className="num">{r.assumptions?.liquidity_deterioration}</b></span>
            <span>스트레스 변동성 <b className="num">{r.assumptions?.stressed_vol_pct}%</b></span>
          </div>
          <div className="as-krs-exec">
            <div><b>실행 가능성</b> {r.execution_feasibility}</div>
            <div><b>헤지</b> {r.hedge_note}</div>
          </div>
          {(r.notes ?? []).map((n, i) => <div key={i} className="as-note">• {n}</div>)}
        </>
      )}
    </section>
  );
}
