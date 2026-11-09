"use client";
/**
 * 해마다 차이 — 해 · A · B · 차이(%p) (2026-11-09 · 성과 그림 문법 ③ §3.2)
 * ★서버 `yearly`(해 합집합) 그대로★ — 한쪽이 없는 해는 "주지 않았어요" · 차이는 "비교할 수 없어요"(0 이 아니다) · 일부 해는 표시.
 */
import { fmtSignedPct, fmtSignedPp, type PerfCompareView } from "./perfView";

export function CompareYearTable({ view }: { view: PerfCompareView }) {
  const rows = view.yearly;
  if (rows === null) return <p className="pg-note">해마다 차이는 이 결과에 없어요 — 서버가 해마다 수익을 주지 않았어요.</p>;
  if (!rows.length) return <p className="pg-note">해마다 수익이 없어요.</p>;
  return (
    <table className="pg-table pf-year-diff">
      <thead><tr><th>해</th><th className="pg-td-num">{view.a.label}</th><th className="pg-td-num">{view.b.label}</th><th className="pg-td-num">차이</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.year} data-partial={r.a_partial || r.b_partial ? "true" : "false"}>
            <td>{r.year}{r.a_partial || r.b_partial ? <small className="pf-partial"> (일부)</small> : null}</td>
            <td className="pg-td-num">{r.a_return_pct === null ? <span className="pf-na">주지 않았어요</span> : fmtSignedPct(r.a_return_pct)}</td>
            <td className="pg-td-num">{r.b_return_pct === null ? <span className="pf-na">주지 않았어요</span> : fmtSignedPct(r.b_return_pct)}</td>
            <td className={`pg-td-num${r.diff_pp === null ? "" : r.diff_pp >= 0 ? " pf-delta--up" : " pf-delta--down"}`}>
              {r.diff_pp === null ? <span className="pf-na">비교할 수 없어요</span> : fmtSignedPp(r.diff_pp)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
