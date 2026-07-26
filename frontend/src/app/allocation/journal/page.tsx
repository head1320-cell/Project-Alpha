"use client";
// Decision Journal Workspace — 단순 타임라인이 아닌 구조화 저널:
//   Macro View → Changed(가설/변화) → Reason(이유) → Result(결과, 자동 스냅샷)
//   → Review(사후 검증, 나중에 편집). 세션 타임라인은 보조 피드로 함께.
import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { macroApi, type RegimeState } from "@/entities/macro/api";
import {
  deleteStudy, listStudies, updateStudyReview, type AllocationStudy,
} from "@/shared/lib/allocationStorage";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { ResearchRunsPanel } from "@/widgets/allocation/ResearchRunsPanel";
import { ResearchTimeline } from "@/widgets/allocation/ResearchTimeline";
import { DecisionJournal } from "@/widgets/allocation/DecisionJournal";
import { StrategyHealthPanel } from "@/widgets/allocation/StrategyHealthPanel";
import { PolicyBacktest } from "@/widgets/allocation/PolicyBacktest";

function ReviewEditor({ study, onSaved }: { study: AllocationStudy; onSaved: () => void }) {
  const [text, setText] = useState(study.review || "");
  const [editing, setEditing] = useState(false);
  if (!editing) {
    return (
      <div className="as-jr-review">
        <em>Review(사후 검증)</em>
        {study.review
          ? <p>{study.review}</p>
          : <p className="as-note">미작성 — 시간이 지난 뒤 실제 결과와 대조해 기록하세요.</p>}
        <button className="as-chip sm" onClick={() => setEditing(true)}>{study.review ? "수정" : "작성"}</button>
      </div>
    );
  }
  return (
    <div className="as-jr-review">
      <em>Review(사후 검증)</em>
      <textarea className="as-input" rows={2} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="예: 3개월 후 실제로 반도체가 시장을 7%p 상회 — 뷰 방향은 맞았으나 신뢰도가 과소했음" />
      <div className="as-wl-row">
        <button className="as-chip on" onClick={() => { updateStudyReview(study.id, text.trim()); setEditing(false); onSaved(); }}>저장</button>
        <button className="as-chip" onClick={() => { setText(study.review || ""); setEditing(false); }}>취소</button>
      </div>
    </div>
  );
}

export default function JournalWorkspace() {
  const { result, views, holdings, timeline, saveStudyFull, studiesVersion, bumpStudies, canRun } = useAllocation();
  const [studies, setStudies] = useState<AllocationStudy[]>([]);
  const [name, setName] = useState("");
  const [changed, setChanged] = useState("");
  const [reason, setReason] = useState("");
  const [macroView, setMacroView] = useState("");

  const regimeQ = useQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime().catch(() => null) });
  const st = (regimeQ.data ?? null) as RegimeState | null;
  const kr = st?.markets?.kr ?? st;

  useEffect(() => { setStudies(listStudies()); }, [studiesVersion]);
  // Macro View 자동 스냅샷 (편집 가능 — 사용자가 자기 언어로 다듬을 수 있게)
  useEffect(() => {
    if (kr && !macroView) {
      setMacroView(`${kr.regime} (신뢰도 ${Math.round((kr.confidence ?? 0) * 100)}%) · ${st?.recommended_mode ?? ""} · Stress ${Math.round(st?.stress_score ?? 0)}`);
    }
  }, [kr, st, macroView]);

  const pfSummary = result?.summary?.portfolio;
  const canJournal = canRun && !!result;

  const submit = () => {
    saveStudyFull(name, {
      macro_view: macroView.trim() || undefined,
      changed: changed.trim() || undefined,
      reason: reason.trim() || undefined,
    });
    setName(""); setChanged(""); setReason("");
  };

  return (
    <div className="as-ws2 as-ws-jr">
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">정책 백테스트 (Walk-Forward · OOS)
            <span className="as-note-inline">현재 모델·뷰·제약을 시점 밖으로 재현 — 신뢰도 검증</span></div>
          <PolicyBacktest />
        </section>
        <section className="as-card">
          <div className="as-card-title">NEW JOURNAL ENTRY <span className="as-note-inline">Macro View → Changed → Reason → Result → Review</span></div>
          <label className="as-jr-field"><em>이름</em>
            <input className="as-input" placeholder="예: AI Capex 사이클 1차 검증" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="as-jr-field"><em>Macro View <span className="as-note-inline">현재 국면 자동 스냅샷 — 편집 가능</span></em>
            <input className="as-input" value={macroView} onChange={(e) => setMacroView(e.target.value)} />
          </label>
          <label className="as-jr-field"><em>Changed (가설/변화)</em>
            <input className="as-input" placeholder="예: 반도체 뷰 신뢰도 60→80%로 상향, HRP→BL 전환" value={changed} onChange={(e) => setChanged(e.target.value)} />
          </label>
          <label className="as-jr-field"><em>Reason (이유)</em>
            <input className="as-input" placeholder="예: HBM 수주 서프라이즈 + 카나리(HY 스프레드) 안정" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="as-jr-field"><em>Result (자동 스냅샷)</em>
            {pfSummary ? (
              <div className="as-note num" style={{ color: "var(--t-ink)" }}>
                기대수익 {pfSummary.expected_return_pct}% · 변동성 {pfSummary.volatility_pct}% · Sharpe {pfSummary.sharpe}
                {" · "}{holdings.length}종목 · 뷰 {views.length}개
              </div>
            ) : <div className="as-note">Re-optimize 실행 시 결과가 자동 첨부됩니다</div>}
          </div>
          <button className="as-run" disabled={!canJournal} onClick={submit}>저널 저장</button>
          {!canJournal && <div className="as-note">포트폴리오 구성 + Re-optimize 후 저장 가능</div>}
        </section>
        <section className="as-card">
          <div className="as-card-title">SESSION TIMELINE <span className="as-note-inline">이번 세션 실기록</span></div>
          <ResearchTimeline events={timeline} />
        </section>
        <StrategyHealthPanel />
      </aside>
      <main className="as-center">
        <ResearchRunsPanel />
        <DecisionJournal />
        <section className="as-card">
          <div className="as-card-title">QUICK NOTES <span className="as-note-inline">{studies.length}건 · localStorage(세션 메모)</span></div>
          {studies.length === 0 && <div className="as-empty">저장된 저널 없음 — 좌측에서 첫 엔트리를 기록하세요.</div>}
          {studies.map((s) => (
            <div key={s.id} className="as-jr-entry">
              <div className="as-jr-head">
                <b>{s.name}</b>
                <span className="num as-note-inline">{s.savedAt.slice(0, 16).replace("T", " ")} · {Object.keys(s.holdings).length}종목 · {s.model.toUpperCase()}</span>
                <button className="as-x" title="삭제" onClick={() => { deleteStudy(s.id); bumpStudies(); }}>×</button>
              </div>
              <div className="as-jr-grid">
                <div><em>Macro View</em><p>{s.macro_view || "—"}</p></div>
                <div><em>Changed</em><p>{s.changed || "—"}</p></div>
                <div><em>Reason</em><p>{s.reason || "—"}</p></div>
                <div><em>Result</em><p className="num">{s.result_summary || s.note || "—"}</p></div>
              </div>
              <ReviewEditor study={s} onSaved={bumpStudies} />
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
