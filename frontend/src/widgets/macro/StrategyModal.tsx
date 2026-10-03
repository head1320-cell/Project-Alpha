"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// StrategyModal — 전략 자세히 (개념 · 작동 방식 · 근거 · 국면 적합도 · 보유 · 과거 성과 · 참고 문헌 · AI 분석)
//   백엔드 build_detail 병합 결과를 그린다. AI 분석은 단추를 눌렀을 때만.
// BU5b-2: 상세·AI 실패는 그 자리 alert + 다시 시도(예전엔 "불러올 수 없어요" 글자뿐, AI 실패는 조용히 단추로 돌아갔다) ·
//   적합도 막대 = 국면 식별색(판단색 아님) · 성과 = 등락색(변동성·최대 낙폭은 색 없음) · 보유 목록 색 = 도넛 조각 색(기타 접기 일치) ·
//   서버가 쓴 설명·참고 문헌은 그대로(`data-server`) · "mock" 꼬리표 대신 PerfLabel(이미 있음)이 데이터 종류를 말한다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/shared/ui/shadcn/dialog";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from "recharts";
import { X } from "lucide-react";
import type { StrategyAI, StrategyDetail, TacticalHolding } from "@/entities/macro/analysisModel";
import type { Market } from "@/entities/macro/data";
import { loadStrategyAI } from "@/entities/macro/data";
import { regimeName } from "@/entities/macro/regimeKo";
import { Notice } from "@/shared/ui/tx";
import { HoldingsDonut, donutColor, SignalBadge, fmtPct, moveColor, TIP_STYLE } from "./cockpitParts";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { PerfLabel } from "@/shared/ui/PerfLabel";

const Q_FILL: Record<string, string> = {
  Goldilocks: "var(--mc-q-goldilocks)", Reflation: "var(--mc-q-reflation)",
  Stagflation: "var(--mc-q-stagflation)", Disinflation: "var(--mc-q-disinflation)",
};

export default function StrategyModal({ detail, loading, failed, onRetry, currentQuad, market, onClose, onBacktest }: {
  detail: StrategyDetail | null; loading: boolean;
  /** 상세 요청이 실패했다(빈 상세와 다르다) */
  failed?: boolean; onRetry?: () => void;
  currentQuad: string; market: Market;
  onClose: () => void; onBacktest?: (d: StrategyDetail) => void;
}) {
  const anim = useChartAnimation();
  // undefined = 아직 안 물음 · null = 실패 · 값 = 받음
  const [ai, setAi] = useState<StrategyAI | null | undefined>(undefined);
  const [aiLoading, setAiLoading] = useState(false);
  const runAi = () => {
    if (!detail) return;
    setAiLoading(true);
    loadStrategyAI(detail.id, market).then((r) => setAi(r)).finally(() => setAiLoading(false));   // 로더는 실패를 null 로 준다
  };
  const holds = detail?.holdings ?? [];
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm-modal" aria-describedby={undefined}>
        {/* 접근 가능한 이름 — 불러오는 중·실패에도 이름이 있어야 하므로 늘 그린다. */}
        <DialogTitle className="sr-only">{detail?.name ?? "전략 자세히"}</DialogTitle>
        <button type="button" className="mc-modal-x" onClick={onClose} aria-label="닫기"><X size={16} /></button>
        {loading && <div className="mc-modal-load">전략 설명을 불러오는 중이에요</div>}
        {!loading && failed && (
          <Notice tone="danger" title="전략 설명을 불러오지 못했어요">
            서버에 닿지 못했거나 계산이 실패했어요.
            {onRetry && <div className="mc-act"><button type="button" className="tx-btn tx-btn--sub" onClick={onRetry}>다시 시도</button></div>}
          </Notice>
        )}
        {!loading && !failed && !detail && <div className="mc-modal-load">이 전략은 설명이 아직 없어요</div>}
        {!loading && detail && (
          <div className="sm-body">
            <div className="sm-head">
              <div className="sm-head-l">
                <div className="sm-title">{detail.name}<span className="sm-fam" data-server>{detail.archetype_kr}</span></div>
                <SignalBadge signal={detail.signal} />
              </div>
              {onBacktest && <button type="button" className="mc-bt-btn sm tx-btn tx-btn--sub" onClick={() => onBacktest(detail)}>백테스트하기</button>}
            </div>
            <Section title="어떤 전략인가요"><p className="sm-text" data-server>{detail.profile.concept}</p></Section>
            <Section title="어떻게 움직이나요">
              <ol className="sm-steps" data-server>{detail.profile.mechanism.map((m, i) => <li key={i}>{m}</li>)}</ol>
              {!!Object.keys(detail.profile.params).length && (
                <div className="sm-params">{Object.entries(detail.profile.params).map(([k, v]) => (
                  <span key={k} className="sm-param" data-server><em>{k}</em> {v}</span>
                ))}</div>
              )}
            </Section>
            <Section title="왜 통한다고 보나요"><p className="sm-text" data-server>{detail.profile.rationale}</p></Section>
            <Section title="잘 맞는 국면 · 안 맞는 국면"><p className="sm-text" data-server>{detail.profile.regime_note}</p></Section>
            <Section title="국면 적합도(0~100)">
              <div className="sm-fits">
                {detail.regime_fit.map((f) => {
                  const active = f.quadrant === currentQuad;
                  return (
                    <div key={f.quadrant} className={`sm-fit${active ? " on" : ""}`} data-regime={f.quadrant}>
                      <span className="sm-fit-lbl">{regimeName(f.quadrant)}{active && <em>지금</em>}</span>
                      <div className="sm-fit-track" aria-hidden><i style={{ width: `${f.fit * 100}%`, background: Q_FILL[f.quadrant] ?? "var(--mc-neutral)" }} /></div>
                      <span className="sm-fit-v">{Math.round(f.fit * 100)}</span>
                    </div>
                  );
                })}
              </div>
            </Section>
            <div className="sm-grid2">
              <Section title="지금 담고 있는 것">
                <div className="sm-hold-wrap">
                  <HoldingsDonut holdings={holds} size={130} />
                  <div className="sm-holds">
                    {holds.slice(0, 8).map((h: TacticalHolding, idx) => (
                      <div key={h.ticker} className="sm-hold">
                        <i style={{ background: donutColor(idx, holds.length) }} aria-hidden />
                        <span className="sm-hold-nm">{h.us_label}</span>
                        <span className="sm-hold-w">{h.weight}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Section>
              <Section title="과거로 돌려 본 성과(월마다 비중 조정)">
                {detail.perf.curve.length ? (
                  <>
                    <ResponsiveContainer width="100%" height={150}>
                      <AreaChart data={detail.perf.curve} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
                        <defs><linearGradient id="smPerf" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--tx-blue)" stopOpacity={0.22} /><stop offset="100%" stopColor="var(--tx-blue)" stopOpacity={0.02} /></linearGradient></defs>
                        <CartesianGrid strokeDasharray="2 2" stroke="var(--tx-line)" vertical={false} />
                        <XAxis dataKey="t" tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" minTickGap={28} />
                        <YAxis tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" domain={["auto", "auto"]} width={40} />
                        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number | string) => [Number(v).toFixed(1), "가치(처음 100)"]} />
                        <ReferenceLine y={100} stroke="var(--tx-mute)" strokeDasharray="3 3" />
                        <Area type="monotone" dataKey="v" stroke="var(--tx-blue)" strokeWidth={1.8} fill="url(#smPerf)" isAnimationActive={anim} />
                      </AreaChart>
                    </ResponsiveContainer>
                    {/* ★이 총수익·연평균이 무엇인가★ — `/macro/strategy/{sid}` 가 선언한다(Z3). */}
                    <div className="sm-perf-label"><PerfLabel value={detail.perf.perf_label} compact /></div>
                    <dl className="sm-perf-stats">
                      {([["총수익률", detail.perf.summary.total_return_pct, "move"], ["연평균 수익률", detail.perf.summary.cagr_pct, "move"],
                         ["최대 낙폭", detail.perf.summary.mdd_pct, "plain"], ["변동성", detail.perf.summary.vol_pct, "plain"],
                         ["최근 12개월", detail.perf.summary.recent_12m_pct, "move"]] as [string, number | null, "move" | "plain"][]).map(([k, v, kind]) => (
                        <div key={k} className="sm-perf-stat"><dt>{k}</dt><dd style={{ color: kind === "move" ? moveColor(v) : "var(--tx-ink)" }}>{fmtPct(v)}</dd></div>
                      ))}
                    </dl>
                    <p className="sm-note">점선은 처음 값(100)이에요.</p>
                  </>
                ) : <div className="mc-empty-sm">성과 곡선 자료가 없어요</div>}
              </Section>
            </div>
            <Section title="참고 문헌">
              <ul className="sm-refs" data-server>
                {detail.profile.references.map((r, i) => (
                  <li key={i}><b>{r.authors}</b> ({r.year}). <em>{r.title}</em>{r.venue ? `. ${r.venue}` : ""}.</li>
                ))}
              </ul>
            </Section>
            <Section title="AI 분석">
              <div className="sm-ai">
                <button type="button" className="sm-ai-btn tx-btn tx-btn--sub" onClick={runAi} disabled={aiLoading}>
                  {aiLoading ? "AI 분석을 만드는 중이에요" : ai ? "AI 분석 다시 만들기" : "AI 분석 만들기"}
                </button>
                {ai === undefined && !aiLoading && <span className="sm-ai-hint">지금 국면과 배분을 함께 읽고 이 전략이 맞는지 써 드려요. 관리자가 AI 키를 넣어야 하고, 부를 때마다 비용이 들어요.</span>}
                {ai === null && !aiLoading && (
                  <Notice tone="danger" title="AI 분석을 받지 못했어요">서버에 닿지 못했거나 만들기에 실패했어요. 단추를 다시 눌러 주세요.</Notice>
                )}
                {ai?.error && <div className="sm-ai-err" data-server>{ai.error}</div>}
                {ai && !ai.error && ai.content && (
                  <div className="sm-ai-body">
                    <p className="sm-text" data-server>{ai.content}</p>
                    <div className="sm-ai-meta">{ai.tokens.toLocaleString()} 토큰 · {ai.cost_krw.toFixed(1)}원{ai.cached ? " · 저장해 둔 답" : ""}</div>
                  </div>
                )}
              </div>
            </Section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, children }: { title: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="sm-sec">
      <h3 className="sm-sec-h">{title}</h3>
      {children}
    </section>
  );
}
