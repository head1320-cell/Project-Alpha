"use client";
/**
 * 질문 띠 — ★어떤 질문에 답했는지 밝힌다★ (CLAUDE.md §2 네 질문 · 2026-11-09 캔버스 성과 그림 문법 §4.1 시트 ①)
 * 이 결과가 답하는 것은 '전달'(과거에 이 규칙대로 했다면)이고, 답하지 않는 것(예측 스킬 · 경제적 가치)은 관문 레일의 `oos`·`economic` 역
 * 판정을 ★서버 그대로★ 보인다(상태 클래스 `pg-stn--{state}` + 글). 판정이 없으면 없다고 말한다 — 예전 판정을 붙이지 않는다.
 */
import type { PerfView } from "./perfView";

/** 관문 판정 하나(캔버스 `Gate` 와 구조가 같다 — shared 는 entities 를 모른다). */
export interface PerfGate { key: string; label: string; state: string }

const STATE_TEXT: Record<string, string> = {
  confirmed: "확인", assumed: "가정", partial: "부분 확인", unknown: "미상", skipped: "건너뜀", failed: "실패",
};

function GateChip({ gates, gateKey }: { gates: PerfGate[] | null; gateKey: "oos" | "economic" }) {
  if (gates === null) return null;
  const g = gates.find((x) => x.key === gateKey);
  if (!g) return <span className="pf-q-nogate">관문 ‘{gateKey}’ 판정이 보고서에 없습니다</span>;
  return (
    <span className={`pf-q-gate pg-stn--${g.state}`} data-gate={g.key}>
      <span className="pg-stn-dot" aria-hidden="true" />관문 ‘{g.label}’ {STATE_TEXT[g.state] ?? g.state}
    </span>
  );
}

export function QuestionStrip({ view, gates, noGatesText }: { view: PerfView; gates: PerfGate[] | null; noGatesText?: string }) {
  return (
    <section className="pf-q" aria-label="이 결과가 답하는 것과 답하지 않는 것">
      <div className="pf-q-row">
        <span className="pf-q-k">답하는 것</span>
        <span className="pf-q-v">{view.question} (네 질문 중 ② 전달 안정성)</span>
      </div>
      <div className="pf-q-row">
        <span className="pf-q-k">답하지 않는 것</span>
        <ul className="pf-q-list">
          <li>③ 예측 스킬: 신호의 예측력 <GateChip gates={gates} gateKey="oos" /></li>
          <li>④ 경제적 가치: 비용 차감 후 수익성 <GateChip gates={gates} gateKey="economic" /></li>
        </ul>
      </div>
      {gates === null && (
        <p className="pg-note pf-q-nogates">{noGatesText ?? "관문 판정이 없습니다 — 계산 전이거나, 결과가 낡았거나, 부분 계산이라 관문을 판정하지 않았습니다."}</p>
      )}
    </section>
  );
}
