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
import { X } from "lucide-react";
import type { StrategyAI, StrategyDetail, TacticalHolding } from "@/entities/macro/analysisModel";
import type { Market } from "@/entities/macro/data";
import { loadStrategyAI } from "@/entities/macro/data";
import { regimeName } from "@/entities/macro/regimeKo";
import { Notice } from "@/shared/ui/tx";
import { HoldingsDonut, donutColor, SignalBadge, fmtPct, moveColor } from "./cockpitParts";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import { PerfCurve } from "@/shared/ui/perf/PerfCurve";
import { YearTable } from "@/shared/ui/perf/PerfTableView";
import { DrawdownEpisodes } from "@/shared/ui/perf/DrawdownEpisodes";
import type { PerfView } from "@/shared/ui/perf/perfView";

/** 서버 `perf` → `PerfView` ★옮기기만★ — 곡선은 처음 100 · 날짜 자리는 서버 달 라벨("24.03") · 낙폭은 서버 % · 해마다·사건은 서버가 주지 않는다. */
function strategyPerfView(d: StrategyDetail): PerfView {
  const pl = d.perf.perf_label ?? null;
  const dd = d.perf.drawdown_pct;
  // 서버가 점마다 실제 월말 날짜를 주면 그것으로(읽는 줄·가로 라벨이 진짜 날짜) · 못 주면 곡선의 달 라벨 그대로 + 서버 사유 글
  const dated = Array.isArray(d.perf.dates) && d.perf.dates.length === d.perf.curve.length;
  return {
    unit: "base100", dates: dated ? (d.perf.dates as string[]) : d.perf.curve.map((p) => String(p.t)),
    equity: d.perf.curve.map((p) => (Number.isFinite(p.v) ? p.v : null)),
    bench: null, benchLabel: null, drawdown: Array.isArray(dd) ? dd.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null)) : null,
    note: d.perf.dates_note ?? null, rebalances: [], question: "이 전략을 매월 리밸런싱했을 때의 과거 성과",
    learnFrom: null, asOf: null, practice: pl && typeof pl.data_real === "boolean" ? pl.data_real === false : null, perfLabel: pl,
    periods: dated ? (d.perf.periods ?? null) : null, drawdowns: dated ? (d.perf.drawdowns ?? null) : null,
    figures: [], summary: {}, metrics: null,
    cost: { bps: null, impact: null, nRebalances: null, turnoverAvg: null }, explain: null,
  };
}

/** 그림 + 해마다 + 큰 낙폭 사건 — 표 둘은 서버가 실제 월말 날짜를 줄 때만(날짜가 어림이면 그림과 사유 글만). 점이 달이라 셈 열은 "달". */
function StrategyPerf({ detail }: { detail: StrategyDetail }) {
  const view = strategyPerfView(detail);
  return (
    <div className="sm-perf">
      <PerfCurve view={view} height={200} title="과거로 돌려 본 성과" benchNoneText={null} />
      {view.periods && <><h4 className="pg-h4">연도별 수익률</h4><YearTable view={view} nLabel="달" /></>}
      {view.drawdowns && (view.drawdowns.length
        ? <><h4 className="pg-h4">주요 낙폭 구간</h4><DrawdownEpisodes view={view} compact /></>
        : <p className="pg-note">고점 아래로 내려간 달 없음</p>)}
    </div>
  );
}

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
        {loading && <div className="mc-modal-load">전략 설명 조회 중</div>}
        {!loading && failed && (
          <Notice tone="danger" title="전략 설명 조회 실패">
            서버 연결 실패 또는 계산 실패
            {onRetry && <div className="mc-act"><button type="button" className="tx-btn tx-btn--sub" onClick={onRetry}>재시도</button></div>}
          </Notice>
        )}
        {!loading && !failed && !detail && <div className="mc-modal-load">이 전략은 설명이 아직 없습니다</div>}
        {!loading && detail && (
          <div className="sm-body">
            <div className="sm-head">
              <div className="sm-head-l">
                <div className="sm-title">{detail.name}<span className="sm-fam" data-server>{detail.archetype_kr}</span></div>
                <SignalBadge signal={detail.signal} />
              </div>
              {onBacktest && <button type="button" className="mc-bt-btn sm tx-btn tx-btn--sub" onClick={() => onBacktest(detail)}>백테스트하기</button>}
            </div>
            <Section title="전략 개요"><p className="sm-text" data-server>{detail.profile.concept}</p></Section>
            <Section title="운용 방식">
              <ol className="sm-steps" data-server>{detail.profile.mechanism.map((m, i) => <li key={i}>{m}</li>)}</ol>
              {!!Object.keys(detail.profile.params).length && (
                <div className="sm-params">{Object.entries(detail.profile.params).map(([k, v]) => (
                  <span key={k} className="sm-param" data-server><em>{k}</em> {v}</span>
                ))}</div>
              )}
            </Section>
            <Section title="투자 논거"><p className="sm-text" data-server>{detail.profile.rationale}</p></Section>
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
              <Section title="현재 편입 자산">
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
                    {/* 성과 그림 문법 ③ (2026-11-09): 처음을 100으로 · 낙폭 물속(서버 drawdown_pct) · 실제 월말 날짜면 해마다·큰 낙폭 사건까지 · 어림이면 서버 사유 글 */}
                    <StrategyPerf detail={detail} />
                    {/* ★이 총수익·연평균이 무엇인가★ — `/macro/strategy/{sid}` 가 선언한다(Z3). */}
                    <div className="sm-perf-label"><PerfLabel value={detail.perf.perf_label} compact /></div>
                    <dl className="sm-perf-stats">
                      {([["총수익률", detail.perf.summary.total_return_pct, "move"], ["연평균 수익률", detail.perf.summary.cagr_pct, "move"],
                         ["최대 낙폭", detail.perf.summary.mdd_pct, "plain"], ["변동성", detail.perf.summary.vol_pct, "plain"],
                         ["최근 12개월", detail.perf.summary.recent_12m_pct, "move"]] as [string, number | null, "move" | "plain"][]).map(([k, v, kind]) => (
                        <div key={k} className="sm-perf-stat"><dt>{k}</dt><dd style={{ color: kind === "move" ? moveColor(v) : "var(--tx-ink)" }}>{fmtPct(v)}</dd></div>
                      ))}
                    </dl>
                  </>
                ) : <div className="mc-empty-sm">성과 곡선 자료 없음</div>}
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
                  {aiLoading ? "AI 분석을 만드는 중입니다" : ai ? "AI 분석 다시 만들기" : "AI 분석 만들기"}
                </button>
                {ai === undefined && !aiLoading && <span className="sm-ai-hint">현재 국면과 배분을 함께 분석해 이 전략의 적합성을 서술합니다. 관리자가 AI 키를 등록해야 하며, 호출마다 비용이 발생합니다.</span>}
                {ai === null && !aiLoading && (
                  <Notice tone="danger" title="AI 분석 수신 실패">서버 연결 또는 생성에 실패했습니다. 버튼을 다시 누르십시오.</Notice>
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
