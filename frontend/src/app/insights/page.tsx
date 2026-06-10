"use client";

import { useState, useEffect } from "react";
import { analysisApi, verdictColor, formatKrw, type ScreenerItem } from "@/lib/screenerApi";

const PRESET_TICKERS = [
  { code: "005930", name: "삼성전자" },
  { code: "000660", name: "SK하이닉스" },
  { code: "035420", name: "NAVER" },
  { code: "005380", name: "현대차" },
  { code: "051910", name: "LG화학" },
  { code: "035720", name: "카카오" },
];

export default function CompanyPage() {
  const [universe] = useState("kospi200");
  const [ticker, setTicker] = useState("005930");
  const [company, setCompany] = useState<ScreenerItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const lookup = async (code: string) => {
    setTicker(code); setLoading(true); setErr(null);
    try {
      const c = await analysisApi.companyLookup(universe, code);
      if (!c) setErr(`종목 ${code}을(를) 찾을 수 없습니다`);
      setCompany(c);
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  };

  const vc = company ? verdictColor(company.verdict) : null;

  // 최초 자동 조회 (삼성전자)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { lookup("005930"); }, []);

  return (
    <div>
      <div className="meta-stamp">
        SEC_CODE: {ticker}<br />
        EXCHANGE: KRX<br />
        STATUS: LIVE_FEED
      </div>

      <div className="terminal-breadcrumb">Modules / <span>Company Analysis</span></div>

      {/* 종목 선택 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value.replace(/[^0-9]/g, ""))}
          onKeyDown={(e) => e.key === "Enter" && lookup(ticker)}
          placeholder="종목코드"
          style={{ fontFamily: "var(--t-mono)", fontSize: 13, padding: "8px 12px", border: "1px solid var(--t-border)", borderRadius: 2, width: 120 }}
        />
        <button onClick={() => lookup(ticker)} style={{ fontFamily: "var(--t-mono)", fontSize: 12, padding: "8px 16px", background: "var(--t-accent)", color: "#fff", border: "none", borderRadius: 2, cursor: "pointer" }}>
          ANALYZE
        </button>
        <div style={{ width: 1, height: 24, background: "var(--t-border)", margin: "0 4px" }} />
        {PRESET_TICKERS.map((t) => (
          <button key={t.code} onClick={() => lookup(t.code)}
            style={{ fontSize: 12, padding: "6px 10px", border: `1px solid ${ticker === t.code ? "var(--t-accent)" : "var(--t-border)"}`, background: ticker === t.code ? "rgba(18,0,255,0.04)" : "#fff", color: ticker === t.code ? "var(--t-accent)" : "var(--t-muted)", borderRadius: 2, cursor: "pointer" }}>
            {t.name}
          </button>
        ))}
      </div>

      {loading && <div style={{ color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ LOADING ] 기업 분석 중...</div>}
      {err && <div style={{ color: "#dc2626", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ ERROR ] {err}</div>}

      {company && vc && (
        <div className="animate-fade-in">
          {/* 기업 헤더 */}
          <div className="tcompany-header">
            <div>
              <h1 style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.02em", margin: 0 }}>
                {company.corp_name}
                <span className="tticker-badge">{company.stock_code}</span>
              </h1>
              <div style={{ fontSize: 14, color: "var(--t-muted)", marginTop: 4 }}>{company.sector || "—"}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 28, fontWeight: 500, fontFamily: "var(--t-mono)" }}>
                ₩{company.current_price.toLocaleString()}
              </div>
              <div style={{ fontFamily: "var(--t-mono)", fontSize: 13, marginTop: 4 }}>
                <span className="tverdict" style={{ background: vc.bg, color: vc.fg }}>{company.verdict}</span>
              </div>
            </div>
          </div>

          {/* 메트릭 바 */}
          <div className="tmetrics-bar" style={{ marginBottom: 32 }}>
            {[
              { label: "Market Cap", value: company.market_cap_억 != null ? `₩${formatKrw(company.market_cap_억)}억` : "—" },
              { label: "P/E (LTM)", value: company.per != null ? `${company.per.toFixed(1)}x` : "—" },
              { label: "P/B", value: company.pbr != null ? `${company.pbr.toFixed(2)}x` : "—" },
              { label: "ROE", value: company.roe_pct != null ? `${company.roe_pct.toFixed(1)}%` : "—" },
              { label: "Div Yield", value: company.dividend_yield_pct != null ? `${company.dividend_yield_pct.toFixed(2)}%` : "—" },
              { label: "부채비율", value: company.debt_ratio_pct != null ? `${company.debt_ratio_pct.toFixed(0)}%` : "—" },
            ].map((m) => (
              <div key={m.label} className="tmetric-item">
                <span className="metric-label">{m.label}</span>
                <span className="metric-value">{m.value}</span>
              </div>
            ))}
          </div>

          {/* 가치평가 + 점수 */}
          <div className="tlayout-row">
            {/* 내재가치 vs 현재가 */}
            <div className="tsection-card">
              <div className="tsection-label">Intrinsic Value vs Price (RIM · DCF · DDM)</div>
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                  <span style={{ fontSize: 13, color: "var(--t-muted)" }}>통합 내재가치</span>
                  <span style={{ fontSize: 24, fontWeight: 600, fontFamily: "var(--t-mono)", color: vc.fg }}>
                    ₩{Math.round(company.intrinsic_value).toLocaleString()}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                  <span style={{ color: "var(--t-muted)" }}>괴리율</span>
                  <span style={{ fontFamily: "var(--t-mono)", fontWeight: 600, color: vc.fg }}>
                    {company.gap_pct >= 0 ? "+" : ""}{company.gap_pct.toFixed(1)}%
                  </span>
                </div>
              </div>
              <div className="tvaluation-row">
                <span className="v-model">RIM (잔여이익)</span>
                <span className="v-price">{company.rim_value != null ? `₩${Math.round(company.rim_value).toLocaleString()}` : "—"}</span>
              </div>
              <div className="tvaluation-row">
                <span className="v-model">DCF (현금흐름)</span>
                <span className="v-price">{company.dcf_value != null ? `₩${Math.round(company.dcf_value).toLocaleString()}` : "—"}</span>
              </div>
              <div className="tvaluation-row">
                <span className="v-model">DDM (배당할인)</span>
                <span className="v-price">{company.ddm_value != null ? `₩${Math.round(company.ddm_value).toLocaleString()}` : "—"}</span>
              </div>
            </div>

            {/* 점수 분해 */}
            <div className="tsection-card">
              <div className="tsection-label">Composite Score Breakdown</div>
              <div style={{ textAlign: "center", marginBottom: 20 }}>
                <div style={{ fontSize: 40, fontWeight: 600, fontFamily: "var(--t-mono)", color: vc.fg }}>
                  {company.composite_score.toFixed(1)}
                </div>
                <div style={{ fontSize: 11, color: "var(--t-muted)", fontFamily: "var(--t-mono)", textTransform: "uppercase" }}>Composite Score</div>
              </div>
              {[
                { label: "Valuation (괴리)", score: company.gap_score },
                { label: "Profitability (ROE)", score: company.roe_score },
                { label: "Stability (안정성)", score: company.stability_score },
              ].map((s) => (
                <div key={s.label} style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                    <span style={{ color: "var(--t-muted)" }}>{s.label}</span>
                    <span style={{ fontFamily: "var(--t-mono)" }}>{s.score?.toFixed(0) ?? "—"}</span>
                  </div>
                  <div style={{ height: 6, background: "var(--t-surface)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${Math.min(100, s.score ?? 0)}%`, background: "var(--t-accent)", borderRadius: 2 }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
