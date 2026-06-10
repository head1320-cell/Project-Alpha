"use client";

import { useState, useEffect } from "react";
import { analysisApi } from "@/lib/screenerApi";

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
    <div>
      <div className="meta-stamp">
        REF_ID: ALPHA_RM_104<br />
        MKT: KR_CLOSE<br />
        AUTH: SIG_VERIFIED
      </div>

      <div className="terminal-breadcrumb">Modules / <span>Risk Analysis</span></div>
      <h1 className="terminal-h1">Portfolio Exposure &amp; Sensitivity</h1>

      {/* 시나리오 선택 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24, flexWrap: "wrap" }}>
        {scenarios.map((s) => (
          <button
            key={s.id}
            onClick={() => run(s.id)}
            style={{
              fontFamily: "var(--t-mono)", fontSize: 12, padding: "8px 14px",
              border: `1px solid ${scenario === s.id ? "var(--t-accent)" : "var(--t-border)"}`,
              background: scenario === s.id ? "rgba(18,0,255,0.04)" : "#fff",
              color: scenario === s.id ? "var(--t-accent)" : "var(--t-muted)",
              borderRadius: 2, cursor: "pointer",
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* 핵심 지표 */}
      {st && (
        <div className="animate-fade-in">
          <div className="tmetrics-grid" style={{ marginBottom: 24 }}>
            <div className="tmetric-card">
              <span className="tmetric-label">Survival Rate</span>
              <span className="tmetric-value" style={{ color: st.survival_rate >= 70 ? "#16a34a" : st.survival_rate >= 40 ? "#d97706" : "#dc2626" }}>
                {st.survival_rate}%
              </span>
              <div className="tmetric-trend">시나리오: {st.scenario_label}</div>
            </div>
            <div className="tmetric-card">
              <span className="tmetric-label">Survivors</span>
              <span className="tmetric-value" style={{ color: "#16a34a" }}>{st.n_survivors}</span>
              <div className="tmetric-trend">생존 종목</div>
            </div>
            <div className="tmetric-card">
              <span className="tmetric-label">Casualties</span>
              <span className="tmetric-value" style={{ color: "#dc2626" }}>{st.n_casualties}</span>
              <div className="tmetric-trend">취약 종목</div>
            </div>
            <div className="tmetric-card">
              <span className="tmetric-label">Avg Shock</span>
              <span className="tmetric-value" style={{ color: "#dc2626" }}>{st.avg_shock_pct?.toFixed(1)}%</span>
              <div className="tmetric-trend">평균 충격</div>
            </div>
          </div>

          {/* 스트레스 취약 종목 테이블 */}
          <div className="tpanel" style={{ padding: 0 }}>
            <div className="tpanel-label" style={{ padding: "24px 24px 0" }}>
              <span>Stress Test Casualties — {st.scenario_label}</span>
              <span style={{ fontFamily: "var(--t-mono)", fontSize: 10, padding: "2px 8px", borderRadius: 2, background: result?.data_source.fully_real ? "#dcfce7" : "#fafafa", color: result?.data_source.fully_real ? "#15803d" : "var(--t-muted)", border: "1px solid var(--t-border)" }}>
                {result?.data_source.fully_real ? "REAL_DATA" : "MOCK_DATA"}
              </span>
            </div>
            <table className="trisk-table" style={{ marginTop: 16 }}>
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
                      <td className="num" style={{ color: "#dc2626" }}>{c.shock_pct?.toFixed(1)}%</td>
                      <td>
                        <div className="tsurvival-wrap">
                          <div className="tsurvival-bar">
                            <div className="tsurvival-fill" style={{ width: `${severity}%`, background: "#dc2626" }} />
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {casualties.length === 0 && (
                  <tr><td colSpan={4} style={{ textAlign: "center", padding: 32, color: "#16a34a", fontFamily: "var(--t-mono)", fontSize: 12 }}>
                    ✓ 이 시나리오에서 취약 종목 없음 (전 종목 생존)
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {loading && <div style={{ color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ RUNNING ] 스트레스 테스트 실행 중...</div>}
    </div>
  );
}
