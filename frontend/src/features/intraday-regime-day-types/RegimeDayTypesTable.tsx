"use client";
/**
 * 하루 유형 비율 × 국면의 표 — 내 시행의 (날, 종목) 표본을 내 하루 유형 모형으로 배정해 그날 시가 전에 알던 국면별로 센 것 (구현 계획 §7.3 · K2b)
 * ==========================================================================
 * 행 = 유형 1 ~ K · 열 = 국면 1 ~ k · 국면 미상(표본이 있을 때만) · 합계 — 유형 수(4 ~ 16)가 국면 수(2 ~ 4)보다 많아 좁은 폭에서도 열이 여섯을 넘지 않는다.
 * 칸 = 그 묶음에서 유형을 정한 표본 가운데 비율 · 수 · 표본 안 분류 수. ★숫자는 서버 값을 서식만 한다★(국면들 + 미상 = 합계 · 비율도 서버가 낸다 —
 * 화면은 더하거나 나누지 않는다). 비율이 없으면(분류된 표본 0) N/A — 0% 가 아니다. 사유 · 사실 줄 · 한계 문장은 서버 글 그대로(`data-server`).
 * ★순위 · 강조가 없다★ — 국면 색은 번호의 표지일 뿐이다(국면별 성과 나눔 · 시장 국면 절과 같은 밝기 단계). 결과 화면과 캔버스 판이 함께 쓴다.
 */
import { useId } from "react";
import type { RegimeDayTypesAnswer, RegimeDayTypesBlock, RegimeDayTypesGroup } from "@/entities/intraday";
import { stateFill } from "@/entities/intraday";
import { num, pct, UNKNOWN_TEXT } from "@/shared/lib/krFormat";
import { Notice } from "@/shared/ui/tx";

const grade = (g: string | null) => g ?? "미상";

export function RegimeDayTypesTable({ a }: { a: RegimeDayTypesAnswer }) {
  const synthetic = [a.trial_grade, a.regime_grade, a.model.grade, a.samples_grade].includes("E0");
  return (
    <div className="itd-rdt-result" data-index={a.index} data-k={a.k} data-model={a.model.key}
         data-trial-grade={a.trial_grade ?? "unknown"} data-regime-grade={a.regime_grade ?? "unknown"}
         data-model-grade={a.model.grade ?? "unknown"} data-samples-grade={a.samples_grade ?? "unknown"}>
      <p className="itd-rdt-head">
        {a.name} · 국면 {a.k}개 · 모형 {a.model.key.slice(0, 8)} · <span className="itd-rdt-range">{a.from} ~ {a.to}</span>
        {` · 시행 등급 ${grade(a.trial_grade)} · 국면 등급 ${grade(a.regime_grade)} · 모형 등급 ${grade(a.model.grade)} · 표본 등급 ${grade(a.samples_grade)}`}
      </p>
      {synthetic ? (
        <div className="itd-rdt-synth">
          <Notice tone="warn" title="합성 자료가 들어 있습니다.">
            {a.coverage?.reason ? <><span data-server>{a.coverage.reason}</span> </> : null}유형 비율은 장치 확인용이며 시장에 대한 진술이 아닙니다.
          </Notice>
        </div>
      ) : null}
      {a.regime_grade === null && a.regime_grade_reason ? <p className="itd-why itd-rdt-grade"><span data-server>{a.regime_grade_reason}</span></p> : null}
      {a.samples_grade === null && a.samples_grade_reason ? (
        <p className="itd-why itd-rdt-samples-grade"><span data-server>{a.samples_grade_reason}</span></p>
      ) : null}
      <ul className="itd-rdt-facts">{a.model.facts.map((f) => <li key={f} data-server>{f}</li>)}</ul>
      {a.empty || !a.table ? (
        <div className="itd-rdt-empty" data-empty={a.empty?.reason ?? "no_table"}>
          <Notice tone="danger" title="하루 유형을 세지 않았습니다."><span data-server>{a.empty?.message ?? UNKNOWN_TEXT}</span></Notice>
        </div>
      ) : <TableBody a={a} t={a.table} />}
      <ul className="itd-rdt-notes">{a.notes.map((n) => <li key={n} data-server>{n}</li>)}</ul>
    </div>
  );
}

type Col = { key: string; group: RegimeDayTypesGroup; state: number | null };

function columns(t: RegimeDayTypesBlock): Col[] {
  return [
    ...t.states.map((s) => ({ key: String(s.state), group: s as RegimeDayTypesGroup, state: s.state })),
    ...(t.unknown.samples > 0 ? [{ key: "unknown", group: t.unknown as RegimeDayTypesGroup, state: null }] : []),
    { key: "total", group: t.total, state: null },
  ];
}

const SUMMARY: { row: string; label: string; pick: (g: RegimeDayTypesGroup) => number }[] = [
  { row: "samples", label: "표본", pick: (g) => g.samples },
  { row: "classified", label: "유형을 정한 표본", pick: (g) => g.classified },
  { row: "in_sample", label: "표본 안 분류", pick: (g) => g.in_sample },
];

function TableBody({ a, t }: { a: RegimeDayTypesAnswer; t: RegimeDayTypesBlock }) {
  const capId = useId();
  const cols = columns(t);
  const excluded = Object.entries(t.total.excluded);
  return (
    <div className="itd-rdt-body">
      <div className="itd-rdt-tablebox">
        <p className="itd-rdt-cap" id={capId}>
          유형별 비율(열은 그날 시가 전에 알던 국면 · 칸은 그 묶음에서 유형을 정한 표본 가운데 비율과 수 · 관측이며 결정에 쓰지 않습니다)
        </p>
        {/* 좁은 폭에서는 칸 글자를 쪼개지 않고 표를 옆으로 넘긴다 — 넘는 상자는 키보드(Tab → ←→)로도 닿는다 */}
        <div className="itd-rdt-scroll" role="region" tabIndex={0} aria-labelledby={capId}>
          <table className="pg-table itd-rdt-table" aria-labelledby={capId}>
            <thead>
              <tr>
                <th>유형</th>
                {cols.map((c) => (
                  <th key={c.key} className="pg-td-num" data-col={c.key}>
                    {c.state !== null ? <><i className="itd-rs-chip" style={{ background: stateFill(c.state, t.k) }} aria-hidden="true" />국면 {c.state}</>
                      : c.key === "unknown" ? <><i className="itd-rs-chip itd-rs-chip--unknown" aria-hidden="true" />국면 미상</> : "합계"}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.total.types.map((row, j) => (
                <tr key={row.type} data-type={row.type}>
                  <th scope="row">유형 {row.type}</th>
                  {cols.map((c) => {
                    const cell = c.group.types[j];
                    return (
                      <td key={c.key} className="pg-td-num itd-rdt-cell" data-col={c.key}>
                        <span className="itd-rdt-share">{cell.share === null ? UNKNOWN_TEXT : pct(cell.share)}</span>{" "}
                        <span className="itd-rdt-n">{num(cell.n)}개{cell.in_sample ? ` · 표본 안 ${num(cell.in_sample)}` : ""}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
            <tfoot>
              {SUMMARY.map((s) => (
                <tr key={s.row} data-row={s.row}>
                  <th scope="row">{s.label}</th>
                  {cols.map((c) => <td key={c.key} className="pg-td-num" data-col={c.key}>{num(s.pick(c.group))}개</td>)}
                </tr>
              ))}
            </tfoot>
          </table>
        </div>
      </div>
      {excluded.length ? (
        <ul className="tj-plain-list itd-rdt-excluded">
          {excluded.map(([code, n]) => (
            <li key={code} data-reason={code}><b>뺀 표본 {num(n)}개</b> <span data-server>{a.excluded_messages[code] ?? code}</span></li>
          ))}
        </ul>
      ) : null}
      {t.unknown.reasons.length ? (
        <ul className="tj-plain-list itd-rdt-unknown">
          {t.unknown.reasons.map((r) => (
            <li key={r.reason}><b>국면 미상 {num(r.days)}일 · 표본 {num(r.samples)}개</b> <span data-server>{r.reason}</span></li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
