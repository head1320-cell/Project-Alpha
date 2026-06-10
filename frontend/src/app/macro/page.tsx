"use client";

import { useState, useEffect } from "react";
import { analysisApi, type MacroRegime } from "@/lib/screenerApi";

const QUADRANTS = [
  { key: "Reflation", label: "Reflation", sub: "성장↑ / 인플↓" },
  { key: "Overheating", label: "Overheating", sub: "성장↑ / 인플↑" },
  { key: "Disinflation", label: "Disinflation", sub: "성장↓ / 인플↓" },
  { key: "Stagflation", label: "Stagflation", sub: "성장↓ / 인플↑" },
];

export default function MacroPage() {
  const [regime, setRegime] = useState<MacroRegime | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    analysisApi.macroRegime().then(setRegime).catch((e) => setErr(e.message)).finally(() => setLoading(false));
  }, []);

  const activeQuadrant = regime
    ? (QUADRANTS.find((q) => regime.regime.toLowerCase().includes(q.key.toLowerCase()))?.key
      ?? (regime.growth_axis >= 0
        ? (regime.inflation_axis >= 0 ? "Overheating" : "Reflation")
        : (regime.inflation_axis >= 0 ? "Stagflation" : "Disinflation")))
    : null;

  return (
    <div>
      <div className="meta-stamp">
        REF_ID: MACRO_SYS_112<br />
        SOURCE: BOK·FRED<br />
        AUTH: SIG_VERIFIED
      </div>

      <div className="terminal-breadcrumb">Modules / <span>Macro Analysis</span></div>
      <h1 className="terminal-h1">Economic Regime Intelligence</h1>

      {loading && <div style={{ color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ LOADING ] 거시 데이터 수집 중...</div>}
      {err && <div style={{ color: "#dc2626", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ ERROR ] {err}</div>}

      {regime && (
        <div className="animate-fade-in">
          <div className="tpanel">
            <div className="tpanel-label">
              <span>Economic Regime Indicator (Current)</span>
              <span style={{ color: "var(--t-accent)" }}>● {regime.regime}</span>
            </div>
            <div className="tregime">
              {QUADRANTS.map((q) => {
                const active = q.key === activeQuadrant;
                return (
                  <div key={q.key} className={`tquadrant${active ? " active" : ""}`}>
                    <span className="tquadrant-label" style={active ? { color: "var(--t-accent)" } : {}}>{q.label}</span>
                    <span className="tquadrant-sub">{q.sub}</span>
                    {active && <div className="tregime-dot" />}
                  </div>
                );
              })}
            </div>
            <div style={{ textAlign: "center", fontSize: 13, color: "var(--t-muted)", marginTop: 16, maxWidth: 600, marginLeft: "auto", marginRight: "auto" }}>
              {regime.description}
            </div>
          </div>

          <div className="tpanel">
            <div className="tpanel-label"><span>Key Indicators</span></div>
            <div className="tmetrics-grid">
              <div className="tmetric-card">
                <span className="tmetric-label">Growth Axis</span>
                <span className="tmetric-value" style={{ color: regime.growth_axis >= 0 ? "#16a34a" : "#dc2626" }}>
                  {regime.growth_axis >= 0 ? "+" : ""}{regime.growth_axis.toFixed(2)}
                </span>
              </div>
              <div className="tmetric-card">
                <span className="tmetric-label">Inflation Axis</span>
                <span className="tmetric-value" style={{ color: regime.inflation_axis >= 0 ? "#dc2626" : "#16a34a" }}>
                  {regime.inflation_axis >= 0 ? "+" : ""}{regime.inflation_axis.toFixed(2)}
                </span>
              </div>
              <div className="tmetric-card">
                <span className="tmetric-label">Stress Index</span>
                <span className="tmetric-value" style={{ color: regime.stress_score > 60 ? "#dc2626" : regime.stress_score > 30 ? "#d97706" : "#16a34a" }}>
                  {regime.stress_score?.toFixed(0)}
                </span>
              </div>
              <div className="tmetric-card">
                <span className="tmetric-label">Confidence</span>
                <span className="tmetric-value">{(regime.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="tmetric-card">
                <span className="tmetric-label">2Y-10Y Spread</span>
                <span className="tmetric-value" style={{ color: regime.yield_inversion ? "#dc2626" : "var(--t-ink)" }}>
                  {regime.yield_curve?.spread_2y10y_bp != null ? `${Math.round(regime.yield_curve.spread_2y10y_bp)}bp` : "—"}
                </span>
                {regime.yield_inversion && <div className="tmetric-trend" style={{ color: "#dc2626" }}>역전 — 침체 신호</div>}
              </div>
              <div className="tmetric-card">
                <span className="tmetric-label">Recommended Mode</span>
                <span className="tmetric-value" style={{ fontSize: 14, wordBreak: "break-word" }}>{regime.recommended_mode}</span>
              </div>
            </div>
          </div>

          {regime.asset_tilts && Object.keys(regime.asset_tilts).length > 0 && (
            <div className="tpanel">
              <div className="tpanel-label"><span>Regime-Based Asset Allocation</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {Object.entries(regime.asset_tilts).map(([asset, tilt]) => (
                  <div key={asset} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ width: 120, fontSize: 13, fontFamily: "var(--t-mono)" }}>{asset}</span>
                    <div style={{ flex: 1, height: 6, background: "var(--t-surface)", borderRadius: 2, position: "relative" }}>
                      <div style={{
                        position: "absolute", left: "50%", height: "100%",
                        width: `${Math.abs(tilt) * 50}%`,
                        background: tilt >= 0 ? "#16a34a" : "#dc2626",
                        transform: tilt >= 0 ? "none" : "translateX(-100%)",
                        borderRadius: 2,
                      }} />
                    </div>
                    <span style={{ width: 50, textAlign: "right", fontFamily: "var(--t-mono)", fontSize: 12, color: tilt >= 0 ? "#16a34a" : "#dc2626" }}>
                      {tilt >= 0 ? "+" : ""}{(tilt * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
