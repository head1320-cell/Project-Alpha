"use client";
/**
 * 해마다 수익 — 등락 막대(부호와 함께) · 부분 연도는 '일부' 라고 (2026-11-09 · 캔버스 성과 그림 문법 §4.1)
 * ★서버 `periods.yearly` 그대로★ — 연환산하지 않은 값이고 화면도 다시 계산하지 않는다. 없으면 없다고 말한다.
 */
import { fmtSignedPct, type PerfView } from "./perfView";

export function PeriodBars({ view }: { view: PerfView }) {
  const rows = view.periods?.yearly ?? null;
  if (!rows) return <p className="pg-note pg-pf-years-none">해마다 수익은 이 결과에 없어요 — 서버가 기간별 수익을 주지 않았어요.</p>;
  if (!rows.length) return <p className="pg-note pg-pf-years-none">해마다 수익을 셀 만큼 긴 곡선이 아니에요.</p>;
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(r.return_pct)));
  return (
    <div className="pg-pf-years">
      <h4 className="pg-h4">해마다</h4>
      <ul className="pg-pf-year-list">
        {rows.map((r) => {
          const w = Math.min(50, (Math.abs(r.return_pct) / max) * 50);
          return (
            <li key={r.year} className="pg-pf-year" data-partial={r.partial ? "true" : "false"}>
              <span className="pg-pf-year-lab">{r.year}{r.partial ? <small> 일부</small> : null}</span>
              <span className="pg-pf-year-track" aria-hidden="true">
                <i className={`pg-pf-year-bar pg-pf-year-bar--${r.return_pct >= 0 ? "up" : "down"}`}
                   style={r.return_pct >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
              </span>
              <span className={`pg-pf-year-val pg-pf-delta--${r.return_pct >= 0 ? "up" : "down"}`}>{fmtSignedPct(r.return_pct)}</span>
            </li>
          );
        })}
      </ul>
      {rows.some((r) => r.partial) && <p className="pg-note">‘일부’는 1월부터 12월까지 다 채우지 않은 해예요 — 그 기간 수익 그대로이고 연환산하지 않았어요.</p>}
    </div>
  );
}
