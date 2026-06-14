"use client";

import { useState, useEffect } from "react";
import { analysisApi, verdictColor, formatKrw, type ScreenerItem } from "@/lib/screenerApi";
import PageHeader from "@/components/layout/PageHeader";
import SectionHead from "@/components/layout/SectionHead";
import { MiniViz } from "@/components/common/MiniViz";

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

      <PageHeader
        eyebrow="COMPANY / DEEP ANALYSIS"
        index="04 / 05"
        title="Company Analysis"
        intro="DART 재무 PIT(공시시차 반영) 기반 심층 분석 — RIM·DCF·DDM 내재가치와 점수 분해를 제공합니다."
        status="EXCHANGE: KRX"
      >
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
          <input
            className="tticker-input"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.replace(/[^0-9]/g, ""))}
            onKeyDown={(e) => e.key === "Enter" && lookup(ticker)}
            placeholder="종목코드"
          />
          <button className="tticker-analyze" onClick={() => lookup(ticker)}>ANALYZE</button>
          <span className="tticker-divider" />
          {PRESET_TICKERS.map((t) => (
            <button
              key={t.code}
              onClick={() => lookup(t.code)}
              className={`tchip-toggle${ticker === t.code ? " active" : ""}`}
            >
              {t.name}
            </button>
          ))}
        </div>
      </PageHeader>

      {loading && <div style={{ color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ LOADING ] 기업 분석 중...</div>}
      {err && <div style={{ color: "var(--color-bear)", fontFamily: "var(--t-mono)", fontSize: 13 }}>[ ERROR ] {err}</div>}

      {company && vc && (
        <div className="animate-fade-in">
          {/* 기업 헤더 (페이지 타이틀과 구분 — div로 강등하여 h1 중복 방지) */}
          <div className="tcompany-header">
            <div>
              <div style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.02em", margin: 0 }}>
                {company.corp_name}
                <span className="tticker-badge">{company.stock_code}</span>
              </div>
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

          <SectionHead label="KEY METRICS" index="01 / 03" />
          <div className="tmetrics-bar">
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

          <SectionHead label="VALUATION & SCORE" index="02 / 03" />
          <div className="tlayout-row">
            {/* 내재가치 vs 현재가 */}
            <div className="tsection-card">
              <div className="tsection-label">Intrinsic Value vs Price (RIM · DCF · DDM)</div>
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
              <div className="tmetric-rows">
                <div className="mr">
                  <span>통합 내재가치</span>
                  <span className="mr-val" style={{ color: vc.fg, fontSize: 14 }}>₩{Math.round(company.intrinsic_value).toLocaleString()}</span>
                </div>
                <div className="mr">
                  <span>현재가 대비 괴리율</span>
                  <span className="mr-val" style={{ color: vc.fg }}>{company.gap_pct >= 0 ? "+" : ""}{company.gap_pct.toFixed(1)}%</span>
                </div>
              </div>
            </div>

            {/* 점수 분해 */}
            <div className="tsection-card">
              <div className="tsection-label">Composite Score &amp; Breakdown</div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, gap: 16 }}>
                <div>
                  <div style={{ fontSize: 40, fontWeight: 600, fontFamily: "var(--t-mono)", color: vc.fg, lineHeight: 1, letterSpacing: "-0.02em" }}>
                    {company.composite_score.toFixed(1)}
                  </div>
                  <div className="tstat-sub" style={{ textTransform: "uppercase", marginTop: 6 }}>/ 100 · {company.verdict}</div>
                </div>
                <div style={{ width: 120, flexShrink: 0 }}><MiniViz kind="gauge" /></div>
              </div>
              <div className="tmetric-rows">
                {[
                  { label: "Valuation (괴리)", score: company.gap_score },
                  { label: "Profitability (ROE)", score: company.roe_score },
                  { label: "Stability (안정성)", score: company.stability_score },
                ].map((s) => (
                  <div key={s.label} className="mr">
                    <span>{s.label}</span>
                    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="mr-val">{s.score?.toFixed(0) ?? "—"}</span>
                      <span className="tscore-bar"><i style={{ width: `${Math.min(100, s.score ?? 0)}%` }} /></span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
