"use client";
/**
 * 자세히 탭의 성과 요약 — 읽는 순서 하나 (2026-11-09 · 캔버스 성과 그림 문법 §4.1)
 * 머리(제목·hero·라벨·숫자 · '크게 보기') → 그림 하나 → 해마다 → 믿어도 되나요·재지 않은 것(서버 explain 그대로) → 지표 모두 → 표로 보기.
 * 노드마다 다른 절(룩어헤드·다음 구간·전략 비중·수익 나눠 보기…)은 부르는 쪽이 이 아래(`after`)에 그대로 둔다.
 * '크게 보기' 는 같은 `PerfView` 로 성과 시트(`PerfSheet`)를 연다 — 시트의 노드 고유 절은 `sheetAfter`.
 */
import { useState, type ReactNode } from "react";
import type { NodeExplain } from "@/entities/portfolio-graph";
import { MetricGroups } from "./MetricGroups";
import { PerfCurve } from "./PerfCurve";
import { PerfFigures } from "./PerfFigures";
import { PerfSheet } from "./PerfSheet";
import { PerfTableView } from "./PerfTableView";
import type { PerfView } from "./perfView";
import { PeriodBars } from "./PeriodBars";
import { useCanvasGates } from "./useCanvasGates";

const TRUST_TEXT = { confirmed: "확인", assumed: "가정", unknown: "몰라요", failed: "실패" } as const;

/** 믿어도 되나요(trust 칩) + 재지 않은 것 — 서버 explain 그대로. 패널과 시트가 같이 쓴다. */
export function TrustAndUnmeasured({ explain, openUnmeasured = false }: { explain: NodeExplain | null; openUnmeasured?: boolean }) {
  const trust = explain?.trust ?? [];
  const unmeasured = explain?.unmeasured ?? [];
  return (
    <>
      {trust.length > 0 && (
        <div className="pg-trust pf-trust">
          <div className="pg-trust-q">믿어도 되나요?</div>
          {trust.map((t, i) => (
            <div key={i} className="pg-trust-a"><span className={`pg-tag pg-tag--${t.state}`}>{TRUST_TEXT[t.state]}</span><span>{t.text}</span></div>
          ))}
        </div>
      )}
      {unmeasured.length > 0 && (
        <details className="pg-unmeasured pf-unmeasured" open={openUnmeasured || undefined}>
          <summary>재지 않은 것 {unmeasured.length}가지</summary>
          <ul>{unmeasured.map((u, i) => <li key={i}>{u}</li>)}</ul>
        </details>
      )}
    </>
  );
}

export function PerfPanel({ view, fallbackTitle, after, sheetAfter }: {
  view: PerfView; fallbackTitle: string; after?: ReactNode; sheetAfter?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const gates = useCanvasGates();
  const ex = view.explain;
  return (
    <div className="pg-pf">
      <PerfFigures view={view} fallbackTitle={fallbackTitle}
                   action={<button type="button" className="pg-btn pf-open" onClick={() => setOpen(true)}>크게 보기</button>} />
      <PerfCurve view={view} />
      <PeriodBars view={view} />
      {(ex?.facts ?? []).map((f, i) => <p key={i} className="pg-note pf-fact">{f}</p>)}
      <TrustAndUnmeasured explain={ex} />
      <MetricGroups view={view} />
      <PerfTableView view={view} />
      {after}
      <PerfSheet view={view} fallbackTitle={fallbackTitle} open={open} onClose={() => setOpen(false)} gates={gates} after={sheetAfter} />
    </div>
  );
}
