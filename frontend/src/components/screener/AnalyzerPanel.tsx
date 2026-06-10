"use client";

import { useState, useEffect } from "react";
import { Grid3x3, Zap, AlertTriangle, PieChart, ShieldAlert, TrendingDown, Loader2 } from "lucide-react";
import {
  screenerApiAdvanced, analyzerApi,
  type FilterGroupNode, type CollinearityResult, type StressTestResult, type StressScenarios,
} from "@/lib/screenerApi";

// ═══════════════════════════════════════════════════════════════════════════════
// AnalyzerPanel (V3-M7+M8) — 후처리 메타분석 (FilterStack 하단)
// ═══════════════════════════════════════════════════════════════════════════════

export function AnalyzerPanel({ group, universe, liquidityFloor }: {
  group: FilterGroupNode;
  universe: string;
  liquidityFloor: string;
}) {
  const [collin, setCollin] = useState<CollinearityResult | null>(null);
  const [stress, setStress] = useState<StressTestResult | null>(null);
  const [scenarios, setScenarios] = useState<StressScenarios | null>(null);
  const [scenario, setScenario] = useState("rate_hike_200bp");
  const [loadingC, setLoadingC] = useState(false);
  const [loadingS, setLoadingS] = useState(false);

  useEffect(() => {
    analyzerApi.stressScenarios().then(setScenarios).catch(() => {});
  }, []);

  const runCollinearity = async () => {
    setLoadingC(true); setCollin(null);
    try {
      const r = await screenerApiAdvanced.runAdvanced({
        universe, filter_ast: group, limit: 50, liquidity_floor: liquidityFloor,
        analyzers: ["collinearity"],
      }) as { analyzers?: { collinearity?: CollinearityResult } };
      setCollin(r.analyzers?.collinearity || null);
    } catch { setCollin(null); } finally { setLoadingC(false); }
  };

  const runStress = async () => {
    setLoadingS(true); setStress(null);
    try {
      const r = await screenerApiAdvanced.runAdvanced({
        universe, filter_ast: group, limit: 50, liquidity_floor: liquidityFloor,
        analyzers: ["stress_test"], analyzer_params: { stress_test: { scenario } },
      }) as { analyzers?: { stress_test?: StressTestResult } };
      setStress(r.analyzers?.stress_test || null);
    } catch { setStress(null); } finally { setLoadingS(false); }
  };

  const corrColor = (v: number) => {
    const a = Math.abs(v);
    if (a >= 0.7) return v > 0 ? "#dc2626" : "#2563eb";
    if (a >= 0.4) return v > 0 ? "#f59e0b" : "#60a5fa";
    return "#e5e5e5";
  };

  return (
    <div className="space-y-3">
      {/* ── M7: 다중공선성 + 최적화 ── */}
      <div className="card-md p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Grid3x3 size={15} style={{ color: "#7c3aed" }} />
            <span className="text-sm font-bold text-primary">AI 팩터 진단 & 최적화</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded-full font-bold" style={{ background: "#f3e8ff", color: "#7c3aed" }}>M7</span>
          </div>
          <button onClick={runCollinearity} disabled={loadingC}
            className="text-[11px] px-3 py-1.5 rounded-md text-white flex items-center gap-1.5" style={{ background: "#7c3aed" }}>
            {loadingC ? <Loader2 size={12} className="animate-spin" /> : <PieChart size={12} />} 진단 실행
          </button>
        </div>

        {!collin && <div className="text-[11px] text-secondary">통과 종목의 팩터 상관·편향을 진단하고 포트폴리오 비중을 제안합니다.</div>}

        {collin && !collin.available && <div className="text-[11px] text-amber-600">{collin.error}</div>}

        {collin && collin.available && (
          <div className="space-y-3 animate-fade-in">
            {/* 경고 */}
            <div className="space-y-1">
              {collin.warnings?.map((w, i) => (
                <div key={i} className="text-[10px] flex items-start gap-1.5" style={{ color: w.includes("없음") || w.includes("양호") ? "#16a34a" : "#dc2626" }}>
                  <AlertTriangle size={10} className="mt-0.5 shrink-0" /> {w}
                </div>
              ))}
            </div>

            {/* 상관 매트릭스 히트맵 */}
            {collin.correlation && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-secondary mb-1">팩터 상관 매트릭스</div>
                <div className="overflow-x-auto">
                  <table className="text-[9px] border-collapse">
                    <thead><tr><th></th>{collin.correlation.labels.map(l => <th key={l} className="px-1 py-0.5 text-secondary font-mono" style={{ writingMode: "vertical-rl", height: 40 }}>{l}</th>)}</tr></thead>
                    <tbody>
                      {collin.correlation.matrix.map((row, i) => (
                        <tr key={i}>
                          <td className="px-1 py-0.5 text-secondary font-mono text-right whitespace-nowrap">{collin.correlation!.labels[i]}</td>
                          {row.map((v, j) => (
                            <td key={j} className="text-center font-mono" style={{ background: corrColor(v), color: Math.abs(v) >= 0.4 ? "#fff" : "#525252", width: 28, height: 20 }}>
                              {v.toFixed(1)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* 스타일 편중 */}
            {collin.style_concentration && (
              <div className="flex gap-1.5 flex-wrap">
                {Object.entries(collin.style_concentration).map(([s, p]) => (
                  <span key={s} className="text-[10px] px-2 py-0.5 rounded-full bg-light text-secondary">{s} {p}%</span>
                ))}
              </div>
            )}

            {/* 최적화 비중 */}
            {collin.optimization && (
              <div className="border-t border-default pt-2">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[11px] font-bold text-primary">{collin.optimization.method_label}</span>
                  <span className="text-[9px] text-secondary font-mono">유효종목 {collin.optimization.effective_n} · HHI {collin.optimization.concentration_hhi}</span>
                </div>
                <div className="space-y-1">
                  {collin.optimization.weights.slice(0, 5).map((w, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-[10px] text-primary flex-grow truncate">{w.corp_name || w.stock_code}</span>
                      <div className="w-24 h-1.5 bg-light rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, w.weight_pct * 8)}%`, background: "#7c3aed" }} />
                      </div>
                      <span className="text-[10px] font-mono text-secondary w-12 text-right">{w.weight_pct}%</span>
                    </div>
                  ))}
                </div>
                <div className="text-[9px] text-secondary mt-1.5">{collin.optimization.note}</div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── M8: 스트레스 테스트 ── */}
      <div className="card-md p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Zap size={15} style={{ color: "#ea580c" }} />
            <span className="text-sm font-bold text-primary">매크로 스트레스 테스트</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded-full font-bold" style={{ background: "#ffedd5", color: "#ea580c" }}>M8</span>
          </div>
          <button onClick={runStress} disabled={loadingS}
            className="text-[11px] px-3 py-1.5 rounded-md text-white flex items-center gap-1.5" style={{ background: "#ea580c" }}>
            {loadingS ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />} 시뮬 실행
          </button>
        </div>

        {/* 시나리오 선택 */}
        {scenarios && (
          <div className="flex gap-1 flex-wrap mb-3">
            {scenarios.scenarios.map(sc => (
              <button key={sc.id} onClick={() => setScenario(sc.id)} title={sc.description}
                className={`text-[10px] px-2 py-1 rounded border transition ${scenario === sc.id ? "bg-orange-600 text-white border-orange-600" : "border-default hover:border-orange-400 text-secondary"}`}>
                {sc.label}
              </button>
            ))}
          </div>
        )}

        {!stress && <div className="text-[11px] text-secondary">선택한 시나리오를 통과 종목에 가해 생존/탈락을 시뮬레이션합니다.</div>}

        {stress && !stress.available && <div className="text-[11px] text-amber-600">{stress.error}</div>}

        {stress && stress.available && (
          <div className="space-y-3 animate-fade-in">
            {/* 생존율 게이지 */}
            <div className="flex items-center gap-3">
              <div className="flex-grow">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] font-bold text-primary">{stress.scenario_label} 생존율</span>
                  <span className="text-sm font-mono font-bold" style={{ color: (stress.survival_rate || 0) >= 60 ? "#16a34a" : (stress.survival_rate || 0) >= 40 ? "#f59e0b" : "#dc2626" }}>
                    {stress.survival_rate}%
                  </span>
                </div>
                <div className="h-2 bg-light rounded-full overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{ width: `${stress.survival_rate}%`, background: (stress.survival_rate || 0) >= 60 ? "#16a34a" : (stress.survival_rate || 0) >= 40 ? "#f59e0b" : "#dc2626" }} />
                </div>
              </div>
              <div className="text-center">
                <div className="text-[9px] text-secondary">평균 충격</div>
                <div className="text-sm font-mono font-bold" style={{ color: "#dc2626" }}>{stress.avg_shock_pct}%</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* 취약 종목 */}
              <div>
                <div className="text-[10px] uppercase tracking-wider text-secondary mb-1 flex items-center gap-1"><ShieldAlert size={10} style={{ color: "#dc2626" }} /> 취약 ({stress.n_casualties})</div>
                <div className="space-y-0.5">
                  {stress.casualties?.slice(0, 5).map((c, i) => (
                    <div key={i} className="flex items-center justify-between text-[10px]">
                      <span className="text-primary truncate">{c.corp_name || c.stock_code}</span>
                      <span className="font-mono" style={{ color: "#dc2626" }}>{c.shock_pct}%</span>
                    </div>
                  ))}
                  {(!stress.casualties || stress.casualties.length === 0) && <div className="text-[10px] text-secondary">없음 — 전원 생존</div>}
                </div>
              </div>
              {/* 견고 종목 */}
              <div>
                <div className="text-[10px] uppercase tracking-wider text-secondary mb-1 flex items-center gap-1"><TrendingDown size={10} style={{ color: "#16a34a", transform: "rotate(180deg)" }} /> 견고</div>
                <div className="space-y-0.5">
                  {stress.most_resilient?.slice(0, 5).map((r, i) => (
                    <div key={i} className="flex items-center justify-between text-[10px]">
                      <span className="text-primary truncate">{r.corp_name || r.stock_code}</span>
                      <span className="font-mono" style={{ color: r.shock_pct >= 0 ? "#16a34a" : "#737373" }}>{r.shock_pct}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="text-[9px] text-secondary">{stress.note}</div>
          </div>
        )}
      </div>
    </div>
  );
}
