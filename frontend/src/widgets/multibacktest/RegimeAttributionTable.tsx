"use client";

import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";

interface RegimeRow {
  regime: string;
  n_days: number;
  n_days_pct: number;
  annualized_return_pct: number;
  volatility_pct: number;
  sharpe: number;
  allocation_effect_pct: number;
  macro_effect_pct: number;
  netting_effect_pct: number;
  cost_effect_pct: number;
  /**
   * 안 쓴 현금이 **번** 이자 (AL3). ★예전에는 `cost_effect_pct` 에 더해져
   * "거래 비용" 이라는 이름으로 나왔다★ — 부호도 성격도 반대인 둘이었다.
   * 현금 모델이 없는 엔진에서는 `null`(미측정)이지 `0` 이 아니다.
   */
  cash_effect_pct?: number | null;
  avg_systemic_risk?: number;
}

interface Props {
  rows: RegimeRow[];
  /** `/multibacktest/{run_id}/attribution` 이 실은 `perf_label`. 없으면 `unknown`. */
  perfLabel?: PerfLabelValue | null;
}

const REGIME_COLORS: Record<string, string> = {
  GOLDILOCKS:  "#69f0ae",
  REFLATION:   "#ffeb3b",
  STAGFLATION: "#ff5252",
  DEFLATION:   "#42a5f5",
};

const REGIME_LABELS: Record<string, string> = {
  GOLDILOCKS:  "Goldilocks (성장↑ 인플↓)",
  REFLATION:   "Reflation (성장↑ 인플↑)",
  STAGFLATION: "Stagflation (성장↓ 인플↑)",
  DEFLATION:   "Deflation (성장↓ 인플↓)",
};

export default function RegimeAttributionTable({ rows, perfLabel }: Props) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{
        padding: 24, textAlign: "center", color: "#6b7fa3", fontSize: 12,
        fontStyle: "italic",
      }}>
        {/* ★켜서 될 일이 아니다★ (BG6) — 예전 안내("매크로 오버레이 활성화 필요")는
            국면 분류기가 없는 저장소에서 따를 수 없는 지시였다. */}
        Regime 분해 데이터 없음 — 국면 분류기(regime_model)가 아직 없어 날짜별 국면을
        정하지 못했습니다(R4 전). 매크로 오버레이를 켜도 달라지지 않습니다.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      {/* ★국면별 알파도 시뮬레이션 위의 분해다★ — 라벨이 아예 없던 표다(Z3). */}
      <div style={{ marginBottom: 8 }}><PerfLabel value={perfLabel} /></div>
      {/* ★이 표가 `selection_effect_pct` 를 안 그리는 것은 옳았다★ (AL) — 그
          값은 오래도록 하드코딩된 `0` 이었다. 이제 백엔드가 `null`(미측정)을
          내므로, 화면도 왜 없는지를 말한다. */}
      <div style={{ marginBottom: 8, fontSize: 11, color: "#6b7fa3" }}>
        ※ 전략 선택 효과는 <b>측정되지 않았습니다</b> — 전략별 벤치마크 계열이 없어
        Brinson 선택항을 계산할 수 없습니다. 0 이 아니라 미상입니다.
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #1e2d4a" }}>
            <th style={{ ...thStyle, textAlign: "left" }}>국면</th>
            <th style={thStyle}>거래일</th>
            <th style={thStyle}>비중</th>
            <th style={thStyle}>연환산 수익</th>
            <th style={thStyle}>변동성</th>
            <th style={thStyle}>Sharpe</th>
            <th style={thStyle}>Alloc Effect</th>
            <th style={thStyle}>Macro Effect</th>
            <th style={thStyle}>Risk Score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const color = REGIME_COLORS[row.regime] || "#6b7fa3";
            return (
              <tr key={row.regime} style={{
                borderBottom: "1px solid #1e2d4a",
                background: `${color}08`,
              }}>
                <td style={{ ...tdStyle, textAlign: "left" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: 4,
                      background: color,
                    }} />
                    <div>
                      <div style={{ fontWeight: 700, color }}>
                        {row.regime}
                      </div>
                      <div style={{ fontSize: 9, color: "#6b7fa3" }}>
                        {REGIME_LABELS[row.regime] || ""}
                      </div>
                    </div>
                  </div>
                </td>
                <td style={tdStyle}>
                  <span style={{ fontFamily: "'Roboto Mono', monospace" }}>
                    {row.n_days}일
                  </span>
                </td>
                <td style={tdStyle}>
                  <span style={{ fontFamily: "'Roboto Mono', monospace",
                                   color: "#a7c8ff" }}>
                    {row.n_days_pct.toFixed(1)}%
                  </span>
                </td>
                <NumCell value={row.annualized_return_pct} suffix="%"
                          positiveColor="#69f0ae" negativeColor="#ff5252" />
                <NumCell value={row.volatility_pct} suffix="%"
                          positiveColor="#a7c8ff" negativeColor="#a7c8ff" />
                <NumCell value={row.sharpe}
                          positiveColor="#00e5ff" negativeColor="#ff5252"
                          threshold={1.0} />
                <NumCell value={row.allocation_effect_pct} suffix="%"
                          positiveColor="#69f0ae" negativeColor="#ff5252"
                          alwaysSign />
                <NumCell value={row.macro_effect_pct} suffix="%"
                          positiveColor="#69f0ae" negativeColor="#ff5252"
                          alwaysSign />
                <td style={tdStyle}>
                  {row.avg_systemic_risk !== null && row.avg_systemic_risk !== undefined ? (
                    <span style={{
                      fontFamily: "'Roboto Mono', monospace", fontWeight: 700,
                      color: row.avg_systemic_risk > 70 ? "#ff5252"
                             : row.avg_systemic_risk > 50 ? "#ff9800"
                             : "#69f0ae",
                    }}>
                      {row.avg_systemic_risk.toFixed(0)}
                    </span>
                  ) : (
                    <span style={{ color: "#4a5f80" }}>—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div style={{ marginTop: 8, fontSize: 10, color: "#6b7fa3",
                      textAlign: "center" }}>
        각 매크로 국면에서의 성과 분해 · 가장 많이 머문 국면의 alpha가 시스템 강점
      </div>
    </div>
  );
}

function NumCell({ value, suffix = "", positiveColor, negativeColor, threshold = 0, alwaysSign }: {
  value: number | undefined; suffix?: string;
  positiveColor: string; negativeColor: string;
  threshold?: number; alwaysSign?: boolean;
}) {
  if (value === undefined || value === null) {
    return <td style={tdStyle}><span style={{ color: "#4a5f80" }}>—</span></td>;
  }
  const color = value >= threshold ? positiveColor : negativeColor;
  const sign = alwaysSign && value >= 0 ? "+" : "";
  return (
    <td style={{ ...tdStyle, fontFamily: "'Roboto Mono', monospace",
                  color, fontWeight: 600 }}>
      {sign}{value.toFixed(2)}{suffix}
    </td>
  );
}

const thStyle: React.CSSProperties = {
  padding: "10px 8px", fontSize: 9, fontWeight: 700, color: "#6b7fa3",
  textTransform: "uppercase", letterSpacing: "0.05em",
  textAlign: "center" as const,
};

const tdStyle: React.CSSProperties = {
  padding: "10px 8px", textAlign: "center" as const,
  color: "#e0e8f5",
};
