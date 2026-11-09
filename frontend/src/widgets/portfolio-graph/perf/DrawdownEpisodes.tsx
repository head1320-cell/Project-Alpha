"use client";
/**
 * 큰 낙폭 사건 — 고점·바닥·회복(없으면 "아직 고점을 되찾지 못했어요")·깊이·바닥까지/회복까지 며칠 (2026-11-09 · 캔버스 성과 그림 문법 §4.1 시트 ④)
 * ★서버 `drawdowns` 그대로★(깊이순 셋) — 회복 `null` 은 0일이 아니라 '아직'이다.
 */
import { fmtPct, type PerfView } from "./perfView";

export function DrawdownEpisodes({ view }: { view: PerfView }) {
  const eps = view.drawdowns;
  if (eps === null) return <p className="pg-note">큰 낙폭 사건은 이 결과에 없어요 — 서버가 낙폭 사건을 주지 않았어요.</p>;
  if (!eps.length) return <p className="pg-note">고점 아래로 내려간 적이 없어요 — 낙폭 사건이 없어요.</p>;
  return (
    <table className="pg-table pf-dd-eps">
      <thead><tr><th>고점</th><th>바닥</th><th className="pg-td-num">깊이</th><th className="pg-td-num">바닥까지</th><th>되찾은 날</th><th className="pg-td-num">되찾기까지</th></tr></thead>
      <tbody>
        {eps.map((e, i) => (
          <tr key={`${e.peak_date}-${i}`} className="pf-dd-ep" data-recovered={e.recovery_date ? "true" : "false"}>
            <td>{e.peak_date.slice(0, 10)}</td>
            <td>{e.trough_date.slice(0, 10)}</td>
            <td className="pg-td-num pf-delta--down">{fmtPct(-Math.abs(e.depth_pct))}</td>
            <td className="pg-td-num">{e.days_to_trough}일</td>
            {e.recovery_date
              ? <><td>{e.recovery_date.slice(0, 10)}</td><td className="pg-td-num">{e.days_to_recover ?? "—"}일</td></>
              : <td colSpan={2} className="pf-dd-ep-open">아직 고점을 되찾지 못했어요</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
