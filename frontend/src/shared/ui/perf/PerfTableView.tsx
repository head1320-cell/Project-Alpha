"use client";
/**
 * 표로 보기 — 그림의 쌍둥이 (2026-11-09 · dataviz "모든 그림에는 표 쌍둥이") · 해마다 표 + 곡선 전체 날짜·값(긴 표는 스크롤).
 * ★같은 값★ — 서버 뷰에서 바로 읽는다(그림이 솎은 점이 아니라 전부).
 */
import { fmtPct, fmtSignedPct, fmtValue, type PerfView } from "./perfView";

/** 해마다 표 — 수익 · 그 해 안의 가장 크게 빠진 폭 · 거래일 · 일부 연도 표시(시트의 '기간별' 절과 표 쌍둥이가 같이 쓴다). */
export function YearTable({ view }: { view: PerfView }) {
  const yearly = view.periods?.yearly ?? [];
  if (!yearly.length) return null;
  return (
    <table className="pg-table pf-table-years">
      <thead><tr><th>해</th><th className="pg-td-num">수익</th><th className="pg-td-num">가장 크게 빠진 폭</th><th className="pg-td-num">거래일</th></tr></thead>
      <tbody>
        {yearly.map((r) => (
          <tr key={r.year}>
            <td>{r.year}{r.partial ? " (일부)" : ""}</td>
            <td className="pg-td-num">{fmtSignedPct(r.return_pct)}</td>
            <td className="pg-td-num">{fmtPct(r.max_drawdown_pct)}</td>
            <td className="pg-td-num">{r.n_days}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PerfTableView({ view }: { view: PerfView }) {
  return (
    <details className="pf-table">
      <summary>표로 보기</summary>
      <YearTable view={view} />
      <div className="pf-table-scroll">
        <table className="pg-table pf-table-curve">
          <thead><tr><th>날짜</th><th className="pg-td-num">포트폴리오</th>{view.bench && <th className="pg-td-num">벤치마크</th>}{view.drawdown && <th className="pg-td-num">낙폭</th>}</tr></thead>
          <tbody>
            {view.dates.map((d, i) => (
              <tr key={`${d}-${i}`}>
                <td>{d.slice(0, 10)}</td>
                <td className="pg-td-num">{fmtValue(view.unit, view.equity[i] ?? null)}</td>
                {view.bench && <td className="pg-td-num">{fmtValue(view.unit, view.bench[i] ?? null)}</td>}
                {view.drawdown && <td className="pg-td-num">{fmtPct(view.drawdown[i] ?? null)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
