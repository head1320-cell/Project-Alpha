"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// StrategyModal — 전략 상세 (개념·작동방식·근거·국면적합도·보유·과거성과·레퍼런스·AI)
//   백엔드 build_detail 병합 결과 렌더. AI 심층분석은 버튼 클릭 시 온디맨드.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from "recharts";
import { X, Sparkles, Play } from "lucide-react";
import type { StrategyDetail, StrategyAI, TacticalHolding } from "@/shared/api/screenerApi";
import type { Market } from "@/entities/macro/data";
import { loadStrategyAI } from "@/entities/macro/data";
import { HoldingsDonut, donutColor, SignalBadge, fmtPct } from "./cockpitParts";

const TIP = { background: "#fff", border: "1px solid var(--t-border)", borderRadius: 2, fontSize: 11, fontFamily: "var(--t-mono, monospace)" };

function fitColor(f: number): string {
  if (f >= 0.8) return "var(--color-bull)";
  if (f >= 0.55) return "var(--color-caution)";
  return "var(--color-bear)";
}
function perfColor(v: number | null | undefined): string {
  return (v ?? 0) >= 0 ? "var(--color-bull)" : "var(--color-bear)";
}

export default function StrategyModal({ detail, loading, currentQuad, market, onClose, onBacktest }: {
  detail: StrategyDetail | null; loading: boolean; currentQuad: string; market: Market;
  onClose: () => void; onBacktest?: (d: StrategyDetail) => void;
}) {
  const [ai, setAi] = useState<StrategyAI | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  const runAi = () => {
    if (!detail) return;
    setAiLoading(true);
    loadStrategyAI(detail.id, market).then((r) => setAi(r)).finally(() => setAiLoading(false));
  };

  return (
    <div className="mc-modal-bg" onClick={onClose}>
      <div className="sm-modal" onClick={(e) => e.stopPropagation()}>
        <button className="mc-modal-x" onClick={onClose}><X size={16} /></button>
        {loading && <div className="mc-modal-load">전략 상세 불러오는 중…</div>}
        {!loading && !detail && <div className="mc-modal-load">전략 상세를 불러올 수 없습니다.</div>}
        {!loading && detail && (
          <div className="sm-body">
            {/* 헤더 */}
            <div className="sm-head">
              <div className="sm-head-l">
                <div className="sm-title">{detail.name}<span className="sm-fam">{detail.archetype_kr}</span></div>
                <SignalBadge signal={detail.signal} />
              </div>
              {onBacktest && <button className="mc-bt-btn sm" onClick={() => onBacktest(detail)}><Play size={11} /> 백테스트</button>}
            </div>

            {/* 개념·작동·근거·국면 */}
            <Section title="개념"><p className="sm-text">{detail.profile.concept}</p></Section>
            <Section title="작동 방식">
              <ol className="sm-steps">{detail.profile.mechanism.map((m, i) => <li key={i}>{m}</li>)}</ol>
              {!!Object.keys(detail.profile.params).length && (
                <div className="sm-params">{Object.entries(detail.profile.params).map(([k, v]) => (
                  <span key={k} className="sm-param"><em>{k}</em> {v}</span>
                ))}</div>
              )}
            </Section>
            <Section title="경제적 근거"><p className="sm-text">{detail.profile.rationale}</p></Section>
            <Section title="유리·불리 국면"><p className="sm-text">{detail.profile.regime_note}</p></Section>

            {/* 국면 적합도 */}
            <Section title="국면 적합도">
              <div className="sm-fits">
                {detail.regime_fit.map((f) => {
                  const active = f.quadrant === currentQuad;
                  return (
                    <div key={f.quadrant} className={`sm-fit${active ? " on" : ""}`}>
                      <span className="sm-fit-lbl">{f.quadrant_kr.split("(")[0]}{active && <em>현재</em>}</span>
                      <div className="sm-fit-track"><i style={{ width: `${f.fit * 100}%`, background: fitColor(f.fit) }} /></div>
                      <span className="sm-fit-v">{Math.round(f.fit * 100)}</span>
                    </div>
                  );
                })}
              </div>
            </Section>

            {/* 보유 + 성과 (2단) */}
            <div className="sm-grid2">
              <Section title="현재 보유">
                <div className="sm-hold-wrap">
                  <HoldingsDonut holdings={detail.holdings} size={130} />
                  <div className="sm-holds">
                    {detail.holdings.slice(0, 8).map((h: TacticalHolding, idx) => (
                      <div key={h.ticker} className="sm-hold">
                        <i style={{ background: donutColor(idx) }} />
                        <span className="sm-hold-nm">{h.us_label}</span>
                        <span className="sm-hold-w">{h.weight}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Section>
              <Section title={<>전략 백테스트 <span className="sm-badge">월 리밸런스 · 시점평가 · {detail.sources.prices ? "실시세" : "mock"}</span></>}>
                {detail.perf.curve.length ? (
                  <>
                    <ResponsiveContainer width="100%" height={150}>
                      <AreaChart data={detail.perf.curve} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                        <defs><linearGradient id="smPerf" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--t-accent)" stopOpacity={0.25} /><stop offset="100%" stopColor="var(--t-accent)" stopOpacity={0.02} /></linearGradient></defs>
                        <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" vertical={false} />
                        <XAxis dataKey="t" tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" minTickGap={28} />
                        <YAxis tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" domain={["auto", "auto"]} width={38} />
                        <Tooltip contentStyle={TIP} />
                        <ReferenceLine y={100} stroke="var(--t-muted)" strokeDasharray="3 3" />
                        <Area type="monotone" dataKey="v" stroke="var(--t-accent)" strokeWidth={1.6} fill="url(#smPerf)" isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                    <div className="sm-perf-stats">
                      {([["총수익", detail.perf.summary.total_return_pct], ["CAGR", detail.perf.summary.cagr_pct],
                         ["MDD", detail.perf.summary.mdd_pct], ["변동성", detail.perf.summary.vol_pct],
                         ["최근 12M", detail.perf.summary.recent_12m_pct]] as [string, number | null][]).map(([k, v]) => (
                        <div key={k} className="sm-perf-stat"><span>{k}</span><b style={{ color: k === "변동성" ? "var(--t-ink)" : perfColor(v) }}>{v == null ? "—" : `${fmtPct(v)}`}</b></div>
                      ))}
                    </div>
                  </>
                ) : <div className="mc-empty-sm">성과 곡선 데이터 없음</div>}
              </Section>
            </div>

            {/* 레퍼런스 */}
            <Section title="레퍼런스">
              <ul className="sm-refs">
                {detail.profile.references.map((r, i) => (
                  <li key={i}><b>{r.authors}</b> ({r.year}). <em>{r.title}</em>{r.venue ? `. ${r.venue}` : ""}.</li>
                ))}
              </ul>
            </Section>

            {/* AI 심층분석 */}
            <Section title={<>AI 심층분석 <Sparkles size={12} style={{ verticalAlign: "middle", color: "var(--t-accent)" }} /></>}>
              <div className="sm-ai">
                <button className="sm-ai-btn" onClick={runAi} disabled={aiLoading}>
                  {aiLoading ? "생성 중…" : ai ? "다시 생성" : "AI 분석 생성"}
                </button>
                {!ai && !aiLoading && <span className="sm-ai-hint">현재 국면·배분을 종합해 이 전략의 적합성을 분석합니다 (ANTHROPIC_API_KEY 필요 · 토큰 비용).</span>}
                {ai?.error && <div className="sm-ai-err">{ai.error}</div>}
                {ai && !ai.error && ai.content && (
                  <div className="sm-ai-body">
                    <p className="sm-text">{ai.content}</p>
                    <div className="sm-ai-meta">{ai.tokens.toLocaleString()} 토큰 · ₩{ai.cost_krw.toFixed(1)}{ai.cached ? " · 캐시" : ""}</div>
                  </div>
                )}
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="sm-sec">
      <div className="sm-sec-h">{title}</div>
      {children}
    </div>
  );
}
