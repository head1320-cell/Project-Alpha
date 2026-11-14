"use client";
/**
 * 큰 낙폭 사건 — 고점·바닥·회복(없으면 "아직 고점을 되찾지 못했어요")·깊이·바닥까지/회복까지 며칠 (2026-11-09 · 캔버스 성과 그림 문법 §4.1 시트 ④)
 * ★서버 `drawdowns` 그대로★(깊이순 셋) — 회복 `null` 은 0일이 아니라 '아직'이다.
 */
import { fmtPct, type DdEpisode, type PerfView } from "./perfView";

/** `view.drawdowns` 를 그리거나, 둘 겹쳐 보기처럼 실행마다 따로 줄 때는 `episodes` 로.
 *  `compact` — 좁은 자리(캔버스 패널 · /macro 전략 창)용: 날짜 "24.11.29" · '아직이에요' · 칸 사이 10px. 값은 같고 서식만(검수 2026-11-09 — 넓은 표는 그 자리에서 가로로 잘렸다). */
export function DrawdownEpisodes({ view, episodes, compact = false }: { view?: PerfView; episodes?: DdEpisode[] | null; compact?: boolean }) {
  const eps = episodes !== undefined ? episodes : (view?.drawdowns ?? null);
  const fmtD = (d: string) => (compact ? d.slice(2, 10).replace(/-/g, ".") : d.slice(0, 10));
  if (eps === null) return <p className="pg-note">주요 낙폭 구간은 이 결과에 없습니다 — 서버가 낙폭 구간을 제공하지 않았습니다.</p>;
  if (!eps.length) return <p className="pg-note">고점 대비 하락한 적이 없습니다 — 낙폭 구간이 없습니다.</p>;
  return (
    <div className="pf-eps-wrap">
    <table className={`pg-table pf-dd-eps${compact ? " pf-dd-eps--compact" : ""}`}>
      <thead><tr><th>고점</th><th>저점</th><th className="pg-td-num">낙폭</th><th className="pg-td-num">하락 기간</th><th>회복일</th><th className="pg-td-num">회복 기간</th></tr></thead>
      <tbody>
        {eps.map((e, i) => (
          <tr key={`${e.peak_date}-${i}`} className="pf-dd-ep" data-recovered={e.recovery_date ? "true" : "false"}>
            <td>{fmtD(e.peak_date)}</td>
            <td>{fmtD(e.trough_date)}</td>
            <td className="pg-td-num pf-delta--down">{fmtPct(-Math.abs(e.depth_pct))}</td>
            <td className="pg-td-num">{e.days_to_trough}일</td>
            {e.recovery_date
              ? <><td>{fmtD(e.recovery_date)}</td><td className="pg-td-num">{e.days_to_recover ?? "—"}일</td></>
              : <td colSpan={2} className="pf-dd-ep-open">{compact ? "미회복" : "고점 미회복"}</td>}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
