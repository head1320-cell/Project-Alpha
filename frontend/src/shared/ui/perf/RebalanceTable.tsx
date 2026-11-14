"use client";
/**
 * 리밸런싱 기록 — 날짜 · 회전율 · (있을 때만) 총 매매·순 매매(롱숏) · 참여율 충격 (2026-11-09 · 캔버스 성과 그림 문법 §4.1 시트 ⑥)
 * ★서버 `rebalances` 그대로★ — 날짜 기록이 없는 노드(불러오기·전략 묶음)는 그렇게 말하고 횟수는 아는 만큼만.
 */
import { fmtNum, fmtPct, type PerfView } from "./perfView";

export function RebalanceTable({ view }: { view: PerfView }) {
  const rows = view.rebalances;
  if (!rows.length) {
    const n = view.cost.nRebalances;
    return (
      <p className="pg-note pf-rebal-none">
        리밸런싱 날짜 기록이 없습니다{n === null ? " — 횟수도 미상입니다." : n > 0 ? ` — 횟수는 ${n}번입니다.` : " — 리밸런싱이 없었습니다."}
      </p>
    );
  }
  const hasLs = rows.some((r) => r.gross_pct !== null || r.net_pct !== null);
  const hasImpact = rows.some((r) => r.impact_bps !== null);
  return (
    <div className="pf-table-scroll">
      <table className="pg-table pf-rebal-table">
        <thead><tr><th>날짜</th><th className="pg-td-num">회전율</th>
          {hasLs && <><th className="pg-td-num">총 매매</th><th className="pg-td-num">순 매매</th></>}
          {hasImpact && <th className="pg-td-num">시장충격(bp)</th>}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.date}-${i}`}>
              <td>{r.date.slice(0, 10)}</td>
              <td className="pg-td-num">{fmtPct(r.turnover_pct)}</td>
              {hasLs && <><td className="pg-td-num">{fmtPct(r.gross_pct)}</td><td className="pg-td-num">{fmtPct(r.net_pct)}</td></>}
              {hasImpact && <td className="pg-td-num">{fmtNum(r.impact_bps, 1)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
