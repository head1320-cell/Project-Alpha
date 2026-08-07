"use client";
// 국내 시나리오팩 (05 Stress — P3-b) — 7종 KR 시나리오의 팩터 기반 충격.
// 종목·팩터·슬리브별 P&L + VaR/CVaR 프록시 + 상관·변동성·유동성 가정 + 실행 가능성·헤지.
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { allocationApi } from "@/entities/allocation/api";
import { useAllocation } from "./AllocationProvider";

const col = (v: number) => (v >= 0 ? "var(--color-bull)" : "var(--color-bear)");

/** 히어로 한 칸. 값이 없으면 숫자도 색도 그리지 않고 **없다고 쓴다**. */
function Hero({ label, v, color, big = false }: {
  label: string; v: number | null | undefined; color?: string; big?: boolean;
}) {
  const has = v != null && Number.isFinite(v);
  return (
    <div>
      <em>{label}</em>
      {has
        ? <b className="num" style={{ color, fontSize: big ? 20 : undefined }}>{v}%</b>
        : <b className="as-krs-na">산출 불가</b>}
    </div>
  );
}

/** 가정 한 줄. 결측은 0 이 아니라 미상이다. */
function Assume({ k, v, pre = "", suf = "", scale = 1 }: {
  k: string; v: number | string | null | undefined; pre?: string; suf?: string; scale?: number;
}) {
  if (v == null || (typeof v === "number" && !Number.isFinite(v))) {
    return <span>{k} <b className="as-krs-na">미상</b></span>;
  }
  // scale 이 걸린 칸(변동성 상승: 비율→%)만 반올림한다. 나머지는 원래 그대로 찍혔고,
  // 무조건 round 하면 `+0.3` 이 `+0` 이 된다 — 지어낸 0 을 고치다 새로 만드는 셈이다.
  const shown = typeof v === "number" ? (scale === 1 ? v : Math.round(v * scale)) : v;
  return <span>{k} <b className="num">{pre}{shown}{suf}</b></span>;
}

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
          {/* ★히어로 4칸은 결측을 `%` 만 남기고 색은 칠하고 있었다 (A6-Z)★
              `col(r.portfolio_shock_pct ?? 0)` 는 null 을 0 으로 만들어 **초록**을 입히고,
              값 자리에는 `{null}%` → 외로운 `%` 만 찍혔다. 초록 배지 옆의 빈 퍼센트는
              "충격 없음" 으로 읽힌다. 나머지 세 칸(VaR·CVaR·MDD)은 값이 없어도 무조건
              bear 색이 박혀 있었다 — 없는 값에 방향을 칠하지 않는다. */}
          <div className="as-krs-hero">
            <Hero label="포트폴리오 충격" v={r.portfolio_shock_pct} big
              color={r.portfolio_shock_pct == null ? undefined : col(r.portfolio_shock_pct)} />
            <Hero label="VaR 95%" v={r.risk_proxy?.var95_pct} color="var(--color-bear)" />
            <Hero label="CVaR 95%" v={r.risk_proxy?.cvar95_pct} color="var(--color-bear)" />
            <Hero label="MDD 프록시" v={r.risk_proxy?.mdd_proxy_pct} color="var(--color-bear)" />
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

          {/* 가정이 없으면 `?? 0` 이 "변동성 상승 +0%" 를 만들었다 — 가정을 못 읽은 것과
              "변동성이 안 오른다고 가정했다" 는 정반대의 뜻이다. */}
          <div className="as-krs-assume">
            <Assume k="상관 상승" v={r.assumptions?.correlation_rise} pre="+" />
            <Assume k="변동성 상승" v={r.assumptions?.volatility_rise} pre="+" suf="%" scale={100} />
            <Assume k="유동성 악화" v={r.assumptions?.liquidity_deterioration} />
            <Assume k="스트레스 변동성" v={r.assumptions?.stressed_vol_pct} suf="%" />
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
