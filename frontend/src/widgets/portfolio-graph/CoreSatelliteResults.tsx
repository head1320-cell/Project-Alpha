"use client";
/**
 * 매매 몫 결합 노드의 결과(K4) — 두 판(국면 몫 · 몫 고정) 표 · 곡선 겹쳐 보기 · 몫의 길 · 서버 한계 문장
 * ==========================================================================
 * 구현 계획 2026-11-16 §7.5 · 설계 2026-11-17 §5. 화면은 새 수를 만들지 않는다. 서버 값을 고르고 서식만 입힌다.
 * 두 판은 늘 서버가 준 순서(국면 몫 → 몫 고정)이고 ★어느 줄도 칠하지 않는다★(이긴 쪽이 없다). 곡선은 두 실행 비교와 같은 부품
 * (`PerfCompare` · 서버의 `align_curves`)이다. 미상은 0 이 아니라 N/A 다. 합성 자료면 맨 위에 적는다.
 */
import type { ReactNode } from "react";
import { compareViewOf, type CompareCurves, type DdEpisode } from "@/shared/ui/perf/perfView";
import { PerfCompare } from "@/shared/ui/perf/PerfCompare";
import { DrawdownEpisodes } from "@/shared/ui/perf/DrawdownEpisodes";
import { UNKNOWN_TEXT, num } from "@/shared/lib/krFormat";
import { Notice } from "@/shared/ui/tx";
import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";
import { coreOf, gradeOf, pctOf, signedOf } from "./coreSatelliteFormat";

type Dict = Record<string, unknown>;
const dict = (v: unknown): Dict => (v && typeof v === "object" ? (v as Dict) : {});
const list = (v: unknown): Dict[] => (Array.isArray(v) ? v.map(dict) : []);
const finite = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const wonOf = (v: unknown): string => { const x = finite(v); return x === null ? UNKNOWN_TEXT : `${num(x)}원`; };

type CompareBlock = { curves: CompareCurves; labels?: { a?: string; b?: string };
  drawdowns?: { a?: DdEpisode[] | null; b?: DdEpisode[] | null }; practice?: boolean | null };

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

export function CoreSatelliteResult({ v }: { v: Dict }) {
  const req = dict(v.request), w = dict(v.window), grades = dict(v.grades);
  const panels = list(v.panels), months = list(v.months);
  const table = Array.isArray(req.table_pct) ? req.table_pct : [];
  const states = Math.max(table.length, ...months.map((m) => (Array.isArray(m.probs_pct) ? m.probs_pct.length : 0)));
  const notes = Array.isArray(v.notes) ? v.notes.map(String) : [];
  const cmp = v.compare && typeof v.compare === "object" ? (v.compare as CompareBlock) : null;
  const labelA = cmp?.labels?.a ?? "국면 몫", labelB = cmp?.labels?.b ?? "몫 고정";
  const view = cmp?.curves ? compareViewOf({ curves: cmp.curves, yearly: null, rows: null }, {
    unit: "x", labelA, labelB, question: "같은 평균 몫으로 고정한 판과 국면 몫 판의 곡선 차이",
    drawdownsA: cmp.drawdowns?.a ?? null, drawdownsB: cmp.drawdowns?.b ?? null, practice: cmp.practice ?? null,
  }) : null;
  const cost = finite(req.cost_bps);

  return (
    <div className="pg-csm">
      {v.synthetic ? (
        <Notice tone="practice" title="합성 자료 위의 숫자입니다">
          모의 시세 · 모의 지수 · 합성 분봉 가운데 하나 이상으로 계산했습니다. 계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.
        </Notice>
      ) : null}
      {/* 성과 숫자는 무슨 성과인지 말한다(Z4) — 서버가 선언한 라벨 그대로(두 판 모두 과거 위의 시뮬레이션). 없으면 PerfLabel 이 '미상'을 그린다. */}
      <div className="pg-perf"><PerfLabel value={v.perf_label as PerfLabelValue | undefined} scope="두 판" compact /></div>
      <KV rows={[
        ["기간", `${String(w.from ?? UNKNOWN_TEXT)} ~ ${String(w.to ?? UNKNOWN_TEXT)} · ${num(finite(w.days))}거래일`],
        ["지수 · 국면 수", <span key="i" data-server>{`${String(req.name ?? UNKNOWN_TEXT)} · ${num(finite(req.k))}개`}</span>],
        ["국면별 매매 몫", table.map((t, i) => `국면 ${i + 1} ${pctOf(t, 1)}`).join(" · ") || UNKNOWN_TEXT],
        ["매매 몫 자본", `${wonOf(req.capital)} · 하한 ${wonOf(v.needed_capital)}`],
        ["옮긴 몫의 비용 가정", cost === null ? UNKNOWN_TEXT : `${num(cost, cost % 1 === 0 ? 0 : 1)}bp(정책 백테스트와 같은 가정)`],
        ["자료 등급", `시행 ${gradeOf(grades.trial)} · 국면 ${gradeOf(grades.regime)} · 핵심 ${coreOf(grades.core_mock)}`],
      ]} />

      <div className="tj-scroll-x pg-csm-scroll" role="region" aria-label="두 판의 결과" tabIndex={0}>
        <table className="pg-table pg-csm-panels">
          <thead>
            <tr><th scope="col">판</th><th scope="col" className="pg-td-num">기간 수익률</th><th scope="col" className="pg-td-num">최대 낙폭</th>
              <th scope="col" className="pg-td-num">평균 몫</th><th scope="col" className="pg-td-num">옮긴 몫 비용</th></tr>
          </thead>
          <tbody>{panels.map((p) => (
            <tr key={String(p.key)} data-k={String(p.key)}>
              <th scope="row">{String(p.label ?? UNKNOWN_TEXT)} 판</th>
              <td className="pg-td-num">{signedOf(p.total_return_pct, 2)}</td>
              <td className="pg-td-num">{pctOf(p.max_drawdown_pct, 2)}</td>
              <td className="pg-td-num">{pctOf(p.avg_share_pct, 1)}</td>
              <td className="pg-td-num">{pctOf(p.cost_pct, 3)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="pg-note pg-csm-fixed">
        몫 고정 판은 같은 날 같은 비용으로 달마다 목표 몫 {pctOf(v.fixed_share_pct, 2)}(국면 몫 판의 날 가중 평균)로 되돌립니다.
      </p>

      {view ? (
        <>
          <PerfCompare view={view} height={220} title="국면 몫 판과 몫 고정 판의 곡선" />
          <p className="pg-note">A {labelA} 판 · B {labelB} 판. 각 판의 첫날 끝 값을 1로 맞췄습니다. 기간 수익률은 시작 자본 대비입니다.</p>
          <div className="pf-cmp-eps">
            <div><h4 className="pg-h4">A 의 주요 낙폭 구간</h4><DrawdownEpisodes episodes={view.drawdowns?.a ?? null} compact /></div>
            <div><h4 className="pg-h4">B 의 주요 낙폭 구간</h4><DrawdownEpisodes episodes={view.drawdowns?.b ?? null} compact /></div>
          </div>
        </>
      ) : <p className="pg-note pg-csm-none">곡선을 받지 못해 겹쳐 그리지 않았습니다.</p>}

      <h4 className="pg-h4">몫의 길</h4>
      <div className="tj-scroll-x pg-csm-scroll" role="region" aria-label="몫을 정한 날마다의 국면 확률과 목표 몫" tabIndex={0}>
        <table className="pg-table pg-csm-months">
          <thead>
            <tr><th scope="col">몫을 정한 날</th>
              {Array.from({ length: states }, (_, i) => <th key={i} scope="col" className="pg-td-num">국면 {i + 1} 확률</th>)}
              <th scope="col" className="pg-td-num">목표 몫</th><th scope="col" className="pg-td-num">옮긴 몫</th><th scope="col" className="pg-td-num">비용</th></tr>
          </thead>
          <tbody>{months.map((m) => {
            const probs = Array.isArray(m.probs_pct) ? m.probs_pct : [];
            return (
              <tr key={String(m.date)} data-date={String(m.date)}>
                <th scope="row">{String(m.date ?? UNKNOWN_TEXT)}</th>
                {Array.from({ length: states }, (_, i) => <td key={i} className="pg-td-num">{pctOf(probs[i], 1)}</td>)}
                <td className="pg-td-num">{pctOf(m.target_pct, 2)}</td>
                <td className="pg-td-num">{pctOf(m.moved_pct, 2)}</td>
                <td className="pg-td-num">{pctOf(m.cost_pct, 3)}</td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      <p className="pg-note">확률은 몫을 정한 날의 시가 전에 알던 값입니다(전 거래일 종가까지). 비용은 시작 자본 대비입니다.</p>

      {notes.length ? <ul className="pg-csm-notes">{notes.map((n) => <li key={n} data-server>{n}</li>)}</ul> : null}
    </div>
  );
}
