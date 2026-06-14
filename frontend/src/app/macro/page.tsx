"use client";

import { useState, useEffect, type CSSProperties } from "react";
import { analysisApi, type MacroRegime } from "@/lib/screenerApi";
import PageHeader from "@/components/layout/PageHeader";
import SectionHead from "@/components/layout/SectionHead";
import { StatGrid, Stat } from "@/components/common/MiniViz";

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

      <PageHeader
        eyebrow="MACRO / REGIME INTELLIGENCE"
        index="03 / 05"
        title="Economic Regime Intelligence"
        intro="4-국면 매크로 레짐과 금리·환율 실데이터로 시장 국면을 진단하고, 전략적 자산배분·섹터 틸트에 활용합니다."
        status={regime ? `REGIME · ${regime.regime}` : "SOURCE: BOK·FRED"}
      />

      {loading && <div style={{ color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ LOADING ] 거시 데이터 수집 중...</div>}
      {err && <div style={{ color: "var(--color-bear)", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ ERROR ] {err}</div>}

      {regime && (
        <div className="animate-fade-in">
          <SectionHead label="REGIME MATRIX" index="01 / 03" />
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1fr)", gap: 16, alignItems: "start" }}>
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
            <StatGrid>
              <Stat
                k="Growth Axis"
                v={`${regime.growth_axis >= 0 ? "+" : ""}${regime.growth_axis.toFixed(2)}`}
                valueColor={regime.growth_axis >= 0 ? "var(--color-bull)" : "var(--color-bear)"}
                sub="실질 성장 모멘텀"
              />
              <Stat
                k="Inflation Axis"
                v={`${regime.inflation_axis >= 0 ? "+" : ""}${regime.inflation_axis.toFixed(2)}`}
                valueColor={regime.inflation_axis >= 0 ? "var(--color-bear)" : "var(--color-bull)"}
                sub="물가 기조"
              />
              <Stat
                k="Stress Index"
                v={regime.stress_score?.toFixed(0)}
                valueColor={regime.stress_score > 60 ? "var(--color-bear)" : regime.stress_score > 30 ? "var(--color-caution)" : "var(--color-bull)"}
                sub="시스템 리스크"
              />
              <Stat
                k="Confidence"
                v={`${(regime.confidence * 100).toFixed(0)}%`}
                sub={`국면 신뢰도 · ${regime.regime}`}
              />
            </StatGrid>
          </div>
          {regime.description && (
            <p style={{ fontSize: 13, color: "var(--t-muted)", marginTop: 16, maxWidth: 680, lineHeight: 1.7 }}>
              {regime.description}
            </p>
          )}

          <SectionHead label="KEY INDICATORS" index="02 / 03" />
          <div className="tmetrics-grid">
            <div className="tmetric-card">
              <span className="tmetric-label">2Y-10Y Spread</span>
              <span className="tmetric-value" style={{ color: regime.yield_inversion ? "var(--color-bear)" : "var(--t-ink)" }}>
                {regime.yield_curve?.spread_2y10y_bp != null ? `${Math.round(regime.yield_curve.spread_2y10y_bp)}bp` : "—"}
              </span>
              {regime.yield_inversion && <div className="tmetric-trend" style={{ color: "var(--color-bear)" }}>역전 — 침체 신호</div>}
            </div>
            <div className="tmetric-card">
              <span className="tmetric-label">Recommended Mode</span>
              <span className="tmetric-value" style={{ fontSize: 14, wordBreak: "break-word" }}>{regime.recommended_mode}</span>
            </div>
          </div>

          {regime.asset_tilts && Object.keys(regime.asset_tilts).length > 0 && (
            <>
              <SectionHead label="ASSET ALLOCATION" index="03 / 03" />
              <div style={{ border: "1px solid var(--t-border)", borderRadius: 2, padding: "14px 18px" }}>
                {Object.entries(regime.asset_tilts).map(([asset, tilt]) => {
                  const finite = Number.isFinite(tilt);
                  const color = !finite ? "var(--t-muted)" : tilt >= 0 ? "var(--color-bull)" : "var(--color-bear)";
                  const fillStyle: CSSProperties = {
                    width: finite ? `${Math.abs(tilt) * 50}%` : "0%",
                    background: color,
                    ...(tilt >= 0 ? { left: "50%" } : { right: "50%" }),
                  };
                  return (
                    <div key={asset} className="talloc-row">
                      <span className="talloc-name">{asset}</span>
                      <div className="talloc-track">
                        <div className="talloc-fill" style={fillStyle} />
                      </div>
                      <span className="talloc-val" style={{ color }}>
                        {finite ? `${tilt >= 0 ? "+" : ""}${(tilt * 100).toFixed(0)}%` : "—"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
