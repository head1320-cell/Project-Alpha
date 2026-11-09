"use client";
/**
 * 성과 시트 — '크게 보기' (2026-11-09 · 캔버스 성과 그림 문법 §4.1 시트)
 * 읽는 순서: ① 질문 띠(답하는 것 · 답하지 않는 것 = 관문 oos·economic 판정) → 머리(hero·라벨·숫자) → ② 큰 그림(360) → ③ 기간별(해마다 표 ·
 * 달마다 격자) → ④ 큰 낙폭 사건 → ⑤ 지표 여섯 묶음(펼친 채) → ⑥ 리밸런싱 기록 → ⑦ 노드 고유 절(다음 구간 예측 · 룩어헤드) → ⑧ 데이터와 한계 →
 * ⑨ 표로 보기. 공용 `Sheet`(native dialog · Esc · 초점 가두기)에 `.pg-sheet--wide` 를 더해 넓힌다. 값은 패널과 같은 `PerfView` 하나.
 */
import type { ReactNode } from "react";
import type { Gate } from "@/entities/portfolio-graph";
import { Sheet } from "@/shared/ui/tx/Sheet";
import { DrawdownEpisodes } from "./DrawdownEpisodes";
import { MetricGroups } from "./MetricGroups";
import { MonthGrid } from "./MonthGrid";
import { PerfCurve } from "./PerfCurve";
import { PerfFigures } from "./PerfFigures";
import { TrustAndUnmeasured } from "./PerfPanel";
import { PerfTableView, YearTable } from "./PerfTableView";
import type { PerfView } from "./perfView";
import { QuestionStrip } from "./QuestionStrip";
import { RebalanceTable } from "./RebalanceTable";

export function PerfSheet({ view, fallbackTitle, open, onClose, gates, after }: {
  view: PerfView; fallbackTitle: string; open: boolean; onClose: () => void; gates: Gate[] | null; after?: ReactNode;
}) {
  const title = view.explain?.title ?? fallbackTitle;
  return (
    <Sheet open={open} onClose={onClose} title={title} testId="perf" className="pg-sheet pg-sheet--wide">
      <div className="pg-pf pf-sheet">
        <QuestionStrip view={view} gates={gates} />
        <PerfFigures view={view} fallbackTitle={fallbackTitle} noTitle />
        <PerfCurve view={view} height={360} />
        <section className="pf-sec">
          <h4 className="pg-h4">기간별</h4>
          <YearTable view={view} />
          <MonthGrid view={view} />
        </section>
        <section className="pf-sec">
          <h4 className="pg-h4">큰 낙폭 사건</h4>
          <DrawdownEpisodes view={view} />
        </section>
        <MetricGroups view={view} open grid />
        <section className="pf-sec">
          <h4 className="pg-h4">리밸런싱 기록</h4>
          <RebalanceTable view={view} />
        </section>
        {after}
        <section className="pf-sec">
          <h4 className="pg-h4">데이터와 한계</h4>
          {(view.explain?.facts ?? []).map((f, i) => <p key={i} className="pg-note pf-fact">{f}</p>)}
          <TrustAndUnmeasured explain={view.explain} openUnmeasured />
        </section>
        <PerfTableView view={view} />
      </div>
    </Sheet>
  );
}
