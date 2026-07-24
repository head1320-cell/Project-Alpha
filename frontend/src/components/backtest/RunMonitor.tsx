"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RunMonitor — 백테스트 실행 로딩 페이지 (전용 잡 모니터, 스펙 §4)
//   run_id 상태를 폴링(refetchInterval)하며 실 단계·진행률·경과시간·활동 타임라인·
//   데이터 honesty 배지를 표시. completed → 결과 페이지로 replace. failed/cancelled →
//   전체 에러 상태(안전 재시도). 서버 영속 상태라 새로고침·직접 URL·네트워크 단절 복구.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  backtestRunApi, STAGE_LABELS, STAGE_ORDER, TERMINAL, type RunStatus,
} from "@/lib/backtestRunApi";

const CONFIG_ROWS: [string, string][] = [
  ["universe", "유니버스"], ["strategy_name", "전략"], ["start_date", "시작일"],
  ["end_date", "종료일"], ["benchmark", "벤치마크"], ["rebalance_frequency", "리밸런스"],
  ["initial_capital", "초기자본"], ["commission_rate", "수수료(bp)"], ["slippage_rate", "슬리피지(bp)"],
  ["buy_fill_type", "매수 체결가"], ["sell_fill_type", "매도 체결가"],
];

function fmtVal(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString("ko-KR");
  return String(v);
}

export function RunMonitor({ runId }: { runId: string }) {
  const router = useRouter();
  const [now, setNow] = useState(() => Date.now());
  const [cancelling, setCancelling] = useState(false);

  // 설정 스냅샷(1회) — 진행률은 경량 status 폴링으로 분리
  const fullQ = useQuery({ queryKey: ["btrun", "full", runId], queryFn: () => backtestRunApi.get(runId), staleTime: Infinity });
  const statusQ = useQuery({
    queryKey: ["btrun", "status", runId],
    queryFn: () => backtestRunApi.status(runId),
    // 실행이 끝날 때까지 계속 폴링 — 에러가 나도 마지막 상태를 유지한 채 재시도(로딩 페이지를
    // 일시적 프록시 504/DB hiccup으로 죽이지 않음). 종료 상태에서만 폴링 중지.
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 1000),
    refetchIntervalInBackground: true,
    // 404(진짜 없음)는 재시도 없이 즉시 확정 → 잘못된/만료 링크는 빠르게 안내. 그 외(5xx/네트워크)는
    // 일시적 → 최대 4회 재시도로 blip 흡수(로딩 페이지를 죽이지 않음).
    retry: (count, e) => ((e as { httpStatus?: number })?.httpStatus === 404 ? false : count < 4),
    retryDelay: (i) => Math.min(1000 * 2 ** i, 4000),
  });

  const st = statusQ.data;                                   // 마지막으로 성공한 상태(에러 중에도 유지)
  const err = statusQ.error as { httpStatus?: number } | null;
  // 백엔드는 진짜 없는 실행만 404, DB 일시 오류는 503 → 404만 "만료/잘못된 링크"로 확정 처리.
  const trulyGone = statusQ.isLoadingError && err?.httpStatus === 404;
  const reconnecting = statusQ.isError && !!st && !TERMINAL.includes(st.status as RunStatus);

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (st?.status === "completed") router.replace(`/backtest/runs/${runId}/results`);
  }, [st?.status, runId, router]);

  // 진짜 없는 실행(첫 로드 404): 만료/잘못된 링크
  if (trulyGone) {
    return <div className="brun-shell"><div className="brun-err">실행을 찾을 수 없습니다 — 만료되었거나 잘못된 링크일 수 있습니다.
      <button className="brun-btn" onClick={() => router.push("/backtest")}>← 전략 편집기로</button></div></div>;
  }
  // 아직 첫 상태가 없음 — 로딩 중(또는 일시적 오류로 재시도 중, 폴링은 계속됨)
  if (!st) {
    return <div className="brun-shell"><div className="brun-loading">
      {statusQ.isError ? "실행 상태를 불러오는 중 — 연결이 불안정해 재시도 중입니다…" : "실행 상태 불러오는 중…"}
    </div></div>;
  }

  const cfg = (fullQ.data?.input_snapshot ?? {}) as Record<string, unknown>;
  const startMs = (st.started_at ?? st.created_at) * 1000;
  const elapsed = Math.max(0, Math.floor((now - startMs) / 1000));
  const elapsedStr = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;
  const curIdx = STAGE_ORDER.indexOf(st.status as RunStatus);
  const failed = st.status === "failed" || st.status === "cancelled";
  const mockBadge = st.is_mock_data === true ? "MOCK 데이터" : st.is_mock_data === false ? "실데이터" : "데이터 소스 확인 중";

  const doCancel = async () => {
    setCancelling(true);
    try { await backtestRunApi.cancel(runId); await statusQ.refetch(); } catch { /* ignore */ }
    setCancelling(false);
  };
  const doRetry = async () => {
    try { const r = await backtestRunApi.retry(runId); router.replace(`/backtest/runs/${r.run_id}/loading`); } catch { /* ignore */ }
  };

  return (
    <div className="brun-shell">
      <header className="brun-head">
        <div>
          <div className="brun-crumb num">BACKTEST RUN · {runId}</div>
          <h1 className="brun-title">{st.strategy_name}</h1>
        </div>
        <div className="brun-head-r">
          <span className={`brun-badge ${st.is_mock_data === false ? "real" : "mock"}`}>{mockBadge}</span>
          <span className="brun-elapsed num">경과 {elapsedStr}</span>
        </div>
      </header>

      {failed ? (
        <div className="brun-err-panel">
          <div className="brun-err-title">{st.status === "cancelled" ? "실행이 취소되었습니다" : "실행이 실패했습니다"}</div>
          {st.error_message && <div className="brun-err-msg">{st.error_message}</div>}
          {st.correlation_id && <div className="brun-err-cid num">추적 ID: {st.correlation_id}</div>}
          <div className="brun-err-actions">
            <button className="brun-btn primary" onClick={doRetry}>다시 실행</button>
            <button className="brun-btn" onClick={() => router.push("/backtest")}>← 전략 편집기로</button>
          </div>
        </div>
      ) : (
        <>
          <div className="brun-progress-wrap">
            <div className="brun-progress-top">
              <span className="brun-stage">{STAGE_LABELS[st.status] ?? st.status}</span>
              <span className="num">{Math.round(st.progress_percent)}%</span>
            </div>
            <div className="brun-progress"><i style={{ width: `${Math.max(2, Math.min(100, st.progress_percent))}%` }} /></div>
            <div className="brun-msg">
              {st.status_message}
              {reconnecting && <span className="brun-reconnect">· 연결이 불안정합니다 — 재시도 중</span>}
            </div>
          </div>

          <div className="brun-grid">
            <section className="brun-card">
              <div className="brun-card-t">활동 타임라인</div>
              <ul className="brun-timeline">
                {STAGE_ORDER.filter((s) => s !== "completed").map((s) => {
                  const i = STAGE_ORDER.indexOf(s);
                  const state = i < curIdx ? "done" : i === curIdx ? "active" : "pending";
                  return (
                    <li key={s} className={`brun-tl ${state}`}>
                      <span className="brun-tl-dot" />
                      <span className="brun-tl-lab">{STAGE_LABELS[s]}</span>
                    </li>
                  );
                })}
              </ul>
              <button className="brun-btn" disabled={cancelling} onClick={doCancel}>{cancelling ? "취소 중…" : "실행 취소"}</button>
            </section>

            <section className="brun-card">
              <div className="brun-card-t">제출한 설정 <span className="brun-note">재현 스냅샷</span></div>
              <table className="brun-cfg">
                <tbody>
                  {CONFIG_ROWS.filter(([k]) => cfg[k] != null && cfg[k] !== "").map(([k, label]) => (
                    <tr key={k}><td>{label}</td><td className="num">{fmtVal(cfg[k])}</td></tr>
                  ))}
                  {Object.keys(cfg).length === 0 && <tr><td colSpan={2} className="brun-note">설정 로딩 중…</td></tr>}
                </tbody>
              </table>
              <div className="brun-note">가격·비용은 사전 추정 · 결과는 완료 후 고정 URL에서 재현 가능합니다.</div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
