"use client";
// Research Timeline — Git식 연구 기록 (Research Memory 1단계).
// 하드코딩이 아니라 이 세션에서 실제로 일어난 사용자 액션의 클라이언트 사이드
// 로그(뷰 추가/재최적화/시나리오 전환/스터디 저장). 영속화(스터디에 저장)는 R2.
import React from "react";

export interface TimelineEvent { t: string; msg: string }

export function ResearchTimeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) {
    return <div className="as-empty">아직 기록 없음 — 뷰 추가·재최적화 등 연구 액션이 자동 기록됩니다.</div>;
  }
  return (
    <div className="as-timeline">
      {events.map((e, i) => (
        <div key={i} className="as-tl-item">
          <span className="as-tl-dot" style={i === 0 ? undefined : { opacity: 0.45 }} />
          <span className="as-tl-time">{e.t}</span>
          <span className="as-tl-msg">{e.msg}</span>
        </div>
      ))}
    </div>
  );
}
