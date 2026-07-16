"use client";

import { useState, useEffect } from "react";
import { analysisApi } from "@/lib/screenerApi";
import SectionHead from "@/components/layout/SectionHead";
import { StatGrid, Stat, MiniViz } from "@/components/common/MiniViz";
import { LoadingState } from "@/components/layout/States";

type StressResult = Awaited<ReturnType<typeof analysisApi.stressTest>>;

export default function RiskPage() {
  const [scenarios, setScenarios] = useState<Array<{ id: string; label: string }>>([]);
  const [scenario, setScenario] = useState("rate_hike_200bp");
  const [universe, setUniverse] = useState("kospi200");
  const [result, setResult] = useState<StressResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    analysisApi.stressScenarios().then((d) => setScenarios(d.scenarios)).catch(() => {});
  }, []);

  const run = async (sc: string) => {
    setScenario(sc); setLoading(true);
    try {
      const r = await analysisApi.stressTest(universe, sc);
      setResult(r);
    } catch { /* noop */ }
    finally { setLoading(false); }
  };

  // 최초 자동 실행
  useEffect(() => { run("rate_hike_200bp"); /* eslint-disable-next-line */ }, []);

  const st = result?.analyzers?.stress_test;
  const casualties = st?.casualties ?? [];

  return (
    <div className="tpage-fade">
      <SectionHead label="STRESS SCENARIO" index="SELECT" />
      <div className="tscenario-bar">
        {scenarios.map((s) => (
          <button
            key={s.id}
            onClick={() => run(s.id)}
            className={`tchip-toggle${scenario === s.id ? " active" : ""}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {st && (
        <div className="animate-fade-in">
          <SectionHead label="EXPOSURE SUMMARY" index="01 / 02" />
          <StatGrid>
            <Stat
              k="Survival Rate"
              v={`${st.survival_rate}%`}
              valueColor={st.survival_rate >= 70 ? "var(--color-bull)" : st.survival_rate >= 40 ? "var(--color-caution)" : "var(--color-bear)"}
              sub={<>
                {st.scenario_label} · {st.n_survivors}/{st.n_survivors + st.n_casualties} 생존
                <div style={{ width: 56, marginTop: 8 }}><MiniViz kind="gauge" /></div>
              </>}
            />
            <Stat k="Survivors" v={st.n_survivors} valueColor="var(--color-bull)" sub="손실 한도 이내" />
            <Stat k="Casualties" v={st.n_casualties} valueColor="var(--color-bear)" sub="취약 종목" />
            <Stat k="Avg Shock" v={`${st.avg_shock_pct?.toFixed(1)}%`} valueColor="var(--color-bear)" sub="포트폴리오 평균 충격" />
          </StatGrid>

          <div className="tpage-section-head" style={{ marginTop: 28 }}>
            <span className="sh-label">STRESS CASUALTIES</span>
            <span className={`tdata-badge${result?.data_source.fully_real ? " real" : ""}`}>
              {result?.data_source.fully_real ? "REAL_DATA" : "MOCK_DATA"}
            </span>
          </div>
          <table className="trisk-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Company</th>
                <th className="num">Shock %</th>
                <th>Impact</th>
              </tr>
            </thead>
            <tbody>
              {casualties.slice(0, 12).map((c) => {
                const severity = Math.min(100, Math.abs(c.shock_pct) * 3);
                return (
                  <tr key={c.stock_code}>
                    <td style={{ fontFamily: "var(--t-mono)", fontWeight: 600 }}>{c.stock_code}</td>
                    <td>{c.corp_name}</td>
                    <td className="num" style={{ color: "var(--color-bear)" }}>{c.shock_pct?.toFixed(1)}%</td>
                    <td>
                      <div className="tsurvival-wrap">
                        <div className="tsurvival-bar">
                          <div className="tsurvival-fill" style={{ width: `${severity}%`, background: "var(--color-bear)" }} />
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {casualties.length === 0 && (
                <tr><td colSpan={4} style={{ textAlign: "center", padding: 32, color: "var(--color-bull)", fontFamily: "var(--t-mono)", fontSize: 12 }}>
                  ✓ 이 시나리오에서 취약 종목 없음 (전 종목 생존)
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {loading && <LoadingState label="스트레스 테스트 실행 중" />}
    </div>
  );
}
