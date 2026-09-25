"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Layers, RefreshCw, Database, Loader2, Activity, GitMerge,
  TrendingUp, BarChart3, GitBranch,
} from "lucide-react";

import BacktestConfigPanel from "@/widgets/multibacktest/BacktestConfigPanel";
import WeightTimeseriesChart from "@/widgets/multibacktest/WeightTimeseriesChart";
import EquityWithRegimeBand from "@/widgets/multibacktest/EquityWithRegimeBand";
import AttributionWaterfall from "@/widgets/multibacktest/AttributionWaterfall";
import RegimeAttributionTable from "@/widgets/multibacktest/RegimeAttributionTable";
import CounterfactualCompare from "@/widgets/multibacktest/CounterfactualCompare";
import RegisterStrategyPanel from "@/widgets/multibacktest/RegisterStrategyPanel";

import { unavailableReason } from "@/entities/realism/unavailable";
import {
  multibacktestApi,
  type MultistrategyAvailability,
  type RegisteredStrategy,
  type SourcesBlock,
} from "@/entities/multibacktest";
import { API_BASE } from "@/shared/api/apiBase";
import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";

// ═══════════════════════════════════════════════════════════════════════════════
import { KPICard, Section, btnStyle, headerStyle, loadingStyle } from "@/widgets/multibacktest/DashboardParts";

export default function MultiBacktestPage() {
  const [strategies, setStrategies] = useState<RegisteredStrategy[]>([]);
  const [availability, setAvailability] = useState<MultistrategyAvailability | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [attribution, setAttribution] = useState<any>(null);
  const [lastConfig, setLastConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [screenerTickers, setScreenerTickers] = useState<string[]>([]);

  // M4: 스크리너에서 전달된 종목 수신 (?tickers=...)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const t = params.get("tickers");
    if (t) setScreenerTickers(t.split(",").filter(Boolean));
  }, []);

  // ★전략은 멀티전략 레지스트리에서 온다★ (BG6) — 예전에는 그래프 전략 목록
  // (`/api/v1/strategies`)을 읽었는데, 그 id 는 이 엔진이 모르는 id 였다.
  const loadStrategies = useCallback(async () => {
    try {
      setStrategies(await multibacktestApi.strategies(true));
    } catch (e) {
      // ★빈 목록으로 조용히 넘기지 않는다★ — 못 읽었다고 말한다.
      setStrategies([]);
      setError(`등록된 전략을 읽지 못했습니다 — ${String(e)}`);
    }
  }, []);

  // 초기 로드
  const loadInit = useCallback(async () => {
    setLoading(true);
    try {
      const [rRes, avail] = await Promise.all([
        fetch(`${API_BASE}/api/v1/multibacktest/runs?limit=10`).then((r) => r.json()).catch(() => ({ runs: [] })),
        multibacktestApi.availability().catch(() => null),
        loadStrategies(),
      ]);
      setRuns(rRes.runs || []);
      setAvailability(avail);
      // ★빈 목록으로 조용히 넘기지 않는다★ (BF) — 서브시스템이 없으면 그 사유를 보인다.
      const why = unavailableReason(rRes) ?? (avail && !avail.available ? avail.reason : null);
      if (why) setError(why);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [loadStrategies]);

  useEffect(() => { loadInit(); }, [loadInit]);

  // 백테스트 실행
  const handleRun = useCallback(async (config: any) => {
    setRunning(true);
    setError("");
    setResult(null);
    setAttribution(null);
    setLastConfig(config);
    try {
      const res = await fetch(`${API_BASE}/api/v1/multibacktest/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...config, save: true }),
      });
      const data = await res.json();
      if (!data.success) {
        setError(data.message || unavailableReason(data) || "실행 실패");
        return;
      }
      setResult(data);

      // Attribution 자동 호출
      if (data.run_id) {
        const attrRes = await fetch(
          `${API_BASE}/api/v1/multibacktest/${data.run_id}/attribution`
        );
        const attrData = await attrRes.json();
        if (attrData.available) {
          setAttribution(attrData);
        }
      }

      // Runs 목록 갱신
      loadInit();
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }, [loadInit]);

  // 과거 run 로드
  const loadRun = useCallback(async (runId: number) => {
    setRunning(true);
    setError("");
    try {
      const [runRes, attrRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/multibacktest/${runId}`).then((r) => r.json()),
        fetch(`${API_BASE}/api/v1/multibacktest/${runId}/attribution`).then((r) => r.json()),
      ]);
      const why = unavailableReason(runRes);
      if (why) {
        setError(why);
        return;
      }

      // run 데이터 → result 형태로 변환
      const synthetic = {
        success: true,
        run_id: runId,
        perf_label: runRes.perf_label,
        sources: runRes.sources,
        summary: {
          total_return_pct: runRes.run.total_return_pct,
          annualized_return_pct: runRes.run.annualized_return_pct,
          sharpe_ratio: runRes.run.sharpe_ratio,
          max_drawdown_pct: runRes.run.max_drawdown_pct,
          calmar_ratio: runRes.run.calmar_ratio,
          netting_total_savings: runRes.run.netting_total_savings,
          total_trades: runRes.run.total_trades,
          n_rebalances: runRes.run.n_rebalances,
          n_trading_days: runRes.run.n_trading_days,
        },
        daily_records: (runRes.daily || []).map((d: any) => {
          // strategy_daily 매핑
          const weights: any = {};
          (runRes.strategy_daily || [])
            .filter((sd: any) => sd.trade_date === d.trade_date)
            .forEach((sd: any) => {
              weights[String(sd.strategy_id)] = sd.weight;
            });
          return {
            date: d.trade_date,
            portfolio_equity: d.portfolio_equity,
            portfolio_return: d.portfolio_return,
            cumulative_return: d.cumulative_return,
            drawdown_pct: d.drawdown_pct,
            regime: d.regime,
            rebalanced: Boolean(d.rebalanced),
            weights,
          };
        }),
        strategy_names: {} as Record<number, string>,
      };

      // 전략 이름 가져오기
      strategies.forEach((s) => {
        synthetic.strategy_names[s.id] = s.name;
      });

      setResult(synthetic);
      if (attrRes.available) setAttribution(attrRes);

      // 설정 복원
      try {
        const cfg = JSON.parse(runRes.run.config_json || "{}");
        setLastConfig(cfg);
      } catch {}
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }, [strategies]);

  if (loading) {
    return (
      <div style={loadingStyle}>
        <Loader2 size={32} className="spin" color="#1200ff" />
        <div style={{ marginTop: 12, fontSize: 12, color: "#6b7fa3" }}>
          통합 백테스트 페이지 로딩 중...
        </div>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: "100vh", background: "#060a1a", color: "#e0e8f5",
      fontFamily: "'Inter', sans-serif", padding: "24px 32px",
    }}>
      {/* Header */}
      <header style={headerStyle}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: 0,
                         display: "flex", alignItems: "center", gap: 10 }}>
            <BarChart3 size={22} color="#1200ff" />
            Multi-Strategy 통합 백테스트
          </h1>
          <p style={{ fontSize: 12, color: "#6b7fa3", marginTop: 4 }}>
            HRP + Stage 9 매크로 · 일별 동적 배분 · 5-Factor 분해 · Counterfactual 분석
          </p>
        </div>
        <button onClick={loadInit} style={btnStyle}>
          <RefreshCw size={13} />
          새로고침
        </button>
      </header>

      {/* M4: 스크리너에서 전달된 종목 배너 */}
      {screenerTickers.length > 0 && (
        <div style={{
          background: "linear-gradient(135deg, rgba(34,197,94,0.12) 0%, rgba(18,0,255,0.06) 100%)",
          border: "1px solid rgba(34,197,94,0.3)", borderRadius: 8,
          padding: "12px 16px", marginBottom: 16,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <BarChart3 size={15} style={{ color: "#22c55e" }} />
            <span style={{ fontSize: 13, fontWeight: 700, color: "#fff" }}>
              스크리너에서 {screenerTickers.length}종목 전달됨
            </span>
            <span style={{ fontSize: 11, color: "rgba(255,255,255,0.6)", fontFamily: "monospace" }}>
              {screenerTickers.slice(0, 10).join(", ")}{screenerTickers.length > 10 ? ` 외 ${screenerTickers.length - 10}종목` : ""}
            </span>
          </div>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.55)", marginTop: 4 }}>
            아래 전략 설정에서 이 종목들로 멀티 전략 백테스트를 구성하세요. (PIT-safe · 5-Factor Attribution)
          </div>
        </div>
      )}

      {/* 전략 등록 (BG6) */}
      <Section title="전략 등록" icon={Database}
                subtitle="완료된 백테스트 실행을 다시 돌려 자산곡선이 저장본과 같을 때만 등록합니다">
        <RegisterStrategyPanel strategies={strategies} onChanged={loadStrategies} />
      </Section>

      {/* 설정 패널 */}
      <Section title="백테스트 설정" icon={Layers}
                subtitle={`등록된 전략 ${strategies.length}개 · 과거 실행 ${runs.length}개`}>
        <BacktestConfigPanel
          strategies={strategies}
          onRun={handleRun}
          running={running}
          availability={availability}
        />
      </Section>

      {/* 과거 실행 */}
      {runs.length > 0 && (
        <Section title="과거 실행 이력" icon={Database}
                  subtitle={`${runs.length}개 저장됨`}>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
            gap: 10,
          }}>
            {runs.slice(0, 6).map((r) => (
              <button key={r.id} onClick={() => loadRun(r.id)}
                       style={{
                         padding: 12, textAlign: "left",
                         background: "#0a0e27", border: "1px solid #1e2d4a",
                         borderRadius: 4, cursor: "pointer",
                       }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#e0e8f5",
                                marginBottom: 4 }}>
                  #{r.id} · {r.run_name?.slice(0, 30) || "Untitled"}
                </div>
                <div style={{ fontSize: 9, color: "#6b7fa3",
                                fontFamily: "'Roboto Mono', monospace" }}>
                  {r.start_date} ~ {r.end_date} · {r.allocation_method}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 6,
                                fontSize: 10, fontFamily: "'Roboto Mono', monospace" }}>
                  <span style={{ color: r.total_return_pct >= 0 ? "#69f0ae" : "#ff5252",
                                   fontWeight: 700 }}>
                    {r.total_return_pct >= 0 ? "+" : ""}{r.total_return_pct?.toFixed(1)}%
                  </span>
                  <span style={{ color: "#a7c8ff" }}>
                    Sharpe {r.sharpe_ratio?.toFixed(2)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </Section>
      )}

      {/* 에러 */}
      {error && (
        <div style={{
          padding: "10px 16px", marginBottom: 16,
          background: "rgba(255,82,82,0.1)",
          border: "1px solid rgba(255,82,82,0.3)",
          borderRadius: 6, fontSize: 12, color: "#ffab91",
        }}>
          {error}
        </div>
      )}

      {/* 결과 영역 */}
      {result && result.summary && (
        <>
          {/* KPI 카드 */}
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(5, 1fr)",
            gap: 10, marginBottom: 16,
          }}>
            <KPICard label="Total Return"
                      value={`${result.summary.total_return_pct >= 0 ? "+" : ""}${result.summary.total_return_pct?.toFixed(2)}%`}
                      color={result.summary.total_return_pct >= 0 ? "#69f0ae" : "#ff5252"}
                      highlight />
            <KPICard label="Annualized"
                      value={`${result.summary.annualized_return_pct >= 0 ? "+" : ""}${result.summary.annualized_return_pct?.toFixed(2)}%/yr`}
                      color="#00e5ff" />
            <KPICard label="Sharpe"
                      value={result.summary.sharpe_ratio?.toFixed(3) ?? "—"}
                      color="#ffeb3b" />
            <KPICard label="Max DD"
                      value={`${result.summary.max_drawdown_pct?.toFixed(2)}%`}
                      color="#ff5252" />
            <KPICard label="Calmar"
                      value={result.summary.calmar_ratio?.toFixed(2) ?? "—"}
                      color="#e040fb" />
          </div>

          {/* ★이 수치가 무엇에서 나왔는가★ (BG6) — 라벨은 원천 실행들의 mock 여부로 */}
          <ResultProvenance perfLabel={result.perf_label} sources={result.sources}
                            netting={result.summary.netting}
                            nettingTotal={result.summary.netting_total_savings} />

          {/* Equity + Regime */}
          <Section title="자산 곡선 + 매크로 국면" icon={TrendingUp}
                    subtitle={`${result.summary.n_trading_days}일 시뮬레이션`}>
            <EquityWithRegimeBand
              daily={result.daily_records}
              initialCapital={lastConfig?.initial_capital || 10_000_000}
            />
          </Section>

          {/* 가중치 시계열 */}
          <Section title="가중치 시계열 (Time-Varying Allocation)" icon={Activity}
                    subtitle={`${result.summary.n_rebalances}회 동적 리밸런싱`}>
            <WeightTimeseriesChart
              daily={result.daily_records}
              strategyNames={result.strategy_names || {}}
            />
          </Section>

          {/* Attribution Waterfall + Regime Table */}
          {attribution && (
            <>
              <Section title="5-Factor Attribution Waterfall"
                        icon={GitBranch}
                        subtitle="베이스라인 → 각 의사결정 효과 → 최종 수익">
                <AttributionWaterfall waterfall={attribution.waterfall || []} />
              </Section>

              <Section title="Regime-Conditional Alpha"
                        icon={Activity}
                        subtitle="매크로 국면별 알파 분해">
                <RegimeAttributionTable rows={attribution.regime_breakdown || []}
                                        perfLabel={attribution.perf_label} />
              </Section>
            </>
          )}

          {/* Counterfactual */}
          <Section title="Counterfactual — What-If 분석"
                    icon={GitMerge}
                    subtitle="원본 vs 5개 대안 시나리오 · 의사결정 가치 정량화">
            <CounterfactualCompare baseConfig={lastConfig} />
          </Section>
        </>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .spin { animation: spin 1s linear infinite; }
      `}</style>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════

function dataText(mock: boolean | null | undefined): string {
  if (mock === true) return "mock";
  if (mock === false) return "실데이터";
  return "데이터 미상";
}

/** 결과의 출처 — 원천 실행 · 데이터 축 · 네팅 근거. ★응답이 말한 것만★ 그린다. */
function ResultProvenance({ perfLabel, sources, netting, nettingTotal }: {
  perfLabel?: PerfLabelValue | null;
  sources?: SourcesBlock | null;
  netting?: {
    enabled: boolean; basis: string; assumptions: string[];
    n_measured_days: number; n_unmeasured_days: number;
    first_unmeasured_reason: string | null;
  } | null;
  nettingTotal?: number | null;
}) {
  return (
    <div style={{
      padding: "10px 14px", marginBottom: 16, background: "#0a0e27",
      border: "1px solid #1e2d4a", borderRadius: 6, fontSize: 11, color: "#a7c8ff",
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      <div><PerfLabel value={perfLabel} /></div>
      <div>
        <span style={{ color: "#6b7fa3" }}>출처 · </span>
        {!sources ? "응답에 출처가 없습니다(과거 실행일 수 있습니다)."
          : !sources.available ? sources.reason
          : sources.strategies.map((s) => (
            <span key={s.strategy_id} style={{ marginRight: 10 }}>
              #{s.strategy_id}{s.name ? ` ${s.name}` : ""} ←{" "}
              {s.registered ? `${s.source_run_id} (${dataText(s.is_mock_data)})` : (s.reason ?? "원천 미상")}
            </span>
          ))}
      </div>
      {netting && (
        <div>
          <span style={{ color: "#6b7fa3" }}>네팅 (보고 전용 · 수익률에 더하지 않음) · </span>
          {!netting.enabled ? "꺼짐"
            : <>
                절감 {nettingTotal == null ? "미상" : `${Math.round(nettingTotal).toLocaleString()}원`}
                {" · "}잰 날 {netting.n_measured_days} / 못 잰 날 {netting.n_unmeasured_days}
                {netting.first_unmeasured_reason ? ` · ${netting.first_unmeasured_reason}` : ""}
                <span title={netting.assumptions.join("\n")} style={{ color: "#6b7fa3" }}>
                  {" "}· 근거 {netting.basis} (가정 {netting.assumptions.length}개)
                </span>
              </>}
        </div>
      )}
    </div>
  );
}

