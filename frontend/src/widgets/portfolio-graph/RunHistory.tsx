"use client";
/**
 * 계산 기록 (BL1) — 이 노드가 지난 계산들에서 어땠는지 (n8n 실행 기록 · KNIME 노드 모니터에서 가져온 패턴)
 * ==========================================================================
 * 세션 최근 10회. 숫자는 서버 헤드라인 그대로이고, 바로 앞 계산과의 차이만 계산한다(같은 단위일 때만 — 단위가 다르면
 * 차이를 말하지 않는다). 부분 계산("여기까지")은 그렇다고 표시한다. 기록은 이 탭을 닫으면 사라진다 — 영구 기록은
 * 기록함(연구 기록·저널)의 일이다.
 */
import type { RunRecord } from "./store";

const STATUS = { ok: "완료", blocked: "막힘", failed: "실패" } as const;
const time = (t: number) => new Date(t).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function RunHistory({ nodeId, runs }: { nodeId: string; runs: RunRecord[] }) {
  const rows = runs.map((r) => ({ r, n: r.nodes[nodeId] })).filter((x) => x.n);
  if (rows.length === 0) return <p className="pg-note">이 노드는 아직 계산 기록이 없어요.</p>;
  return (
    <table className="pg-history">
      <thead><tr><th>언제</th><th>상태</th><th className="pg-td-num">결과</th><th className="pg-td-num">앞과 차이</th></tr></thead>
      <tbody>{rows.map(({ r, n }, i) => {
        const before = rows[i + 1]?.n;
        const diff = n.value != null && before?.value != null ? n.value - before.value : null;
        return (
          <tr key={r.at} className={i === 0 ? "pg-history-now" : undefined}>
            <td>{time(r.at)}{r.partial ? <span className="pg-history-part"> · 여기까지</span> : null}</td>
            <td><span className={`pg-tag pg-tag--${n.status === "ok" ? "confirmed" : n.status === "failed" ? "failed" : "unknown"}`}>{STATUS[n.status]}</span></td>
            <td className="pg-td-num">{n.headline ?? "—"}</td>
            <td className="pg-td-num">{diff == null ? "—" : diff === 0 ? "같음" : `${diff > 0 ? "+" : ""}${Number(diff.toFixed(2))}`}</td>
          </tr>
        );
      })}</tbody>
    </table>
  );
}
