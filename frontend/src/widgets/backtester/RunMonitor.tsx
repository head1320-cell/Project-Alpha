"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RunMonitor — 백테스트 실행 로딩 페이지 (전용 잡 모니터, 스펙 §4)
//   run_id 상태를 폴링(refetchInterval)하며 실 단계·진행률·경과시간·활동 타임라인·
//   데이터 honesty 배지를 표시. completed → 결과 페이지로 replace. failed/cancelled →
//   전체 에러 상태(안전 재시도). 서버 영속 상태라 새로고침·직접 URL·네트워크 단절 복구.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  backtestRunApi, STAGE_LABELS, STAGE_ORDER, TERMINAL, type RunStatus,
} from "@/entities/backtest-run/api";

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

  // 설정 스냅샷(1회) — 진행률은 경량 status 폴링으로 분리.
  // ★키를 ["btrun","config"]로 분리★: 예전엔 ["btrun","full"]을 staleTime:Infinity로 심어
  // 결과 페이지가 같은 키를 읽어 "실행 시작 직후 스냅샷"(loading_data)을 영원히 렌더했다.
  const fullQ = useQuery({
    queryKey: ["btrun", "config", runId],
    queryFn: () => backtestRunApi.get(runId),
    staleTime: Infinity,
  });
  const statusQ = useQuery({
    queryKey: ["btrun", "status", runId],
    queryFn: () => backtestRunApi.status(runId),
    // 실행이 끝날 때까지 계속 폴링 — 에러가 나도 마지막 상태를 유지한 채 다음 tick이 다시 시도.
    // 404(진짜 없음)면 폴링 중지(만료·잘못된 링크), 종료 상태에서도 중지.
    refetchInterval: (q) => {
      if (q.state.data && TERMINAL.includes(q.state.data.status)) return false;
      if ((q.state.error as { httpStatus?: number } | null)?.httpStatus === 404) return false;
      return 1000;
    },
    refetchIntervalInBackground: true,
    // ★retry:false + networkMode:"always"★ — 폴링 쿼리에서 retryer는 순손해다.
    // react-query의 retryer는 재시도 대기 후 canContinue()에서 focusManager.isFocused()를
    // 확인하고, 탭이 숨겨져 있으면 timeout 없이 pause()한다. 그러면 1초 interval은 전부
    // dedupe되어 그 멈춘 promise를 돌려주고(continueRetry는 재개시키지 않음) 브라우저에서
    // 요청이 한 건도 나가지 않는다 — 사용자가 터미널을 보는 동안 UI가 마지막 스냅샷에
    // 얼어붙은 채 "재시도 중"만 띄우던 실제 원인. 폴링 자체가 재시도이므로 retryer를 빼고
    // networkMode:"always"로 숨겨진 탭에서도 새 요청이 시작되게 한다.
    retry: false,
    networkMode: "always",
  });

  const st = statusQ.data;                                   // 마지막으로 성공한 상태(에러 중에도 유지)
  const err = statusQ.error as { httpStatus?: number } | null;
  // 백엔드는 진짜 없는 실행만 404, DB 일시 오류는 503 → 404만 "만료/잘못된 링크"로 확정 처리.
  const trulyGone = statusQ.isLoadingError && err?.httpStatus === 404;
  // 1초 폴링 + retry:false라 한 번의 blip으로도 isError가 되므로, 연속 실패가 몇 번 쌓였을
  // 때만 표시(깜빡임 방지). failureCount는 성공하면 0으로 리셋된다.
  const reconnecting = statusQ.failureCount >= 3 && !!st && !TERMINAL.includes(st.status as RunStatus);

  // "재연결 중"(폴링 자체가 실패)과 "정상 응답이지만 진행이 오래 안 움직임"(느린 연산)은 원인이
  // 다르다. ★두 상태를 독립적으로 판정★ — 예전엔 stalled를 !reconnecting으로 억제해, 폴링이
  // 실패하는 동안에는 "오래 걸림"을 영원히 띄우지 못했다.
  const lastProgressRef = useRef<{ pct: number; at: number } | null>(null);
  const [stalled, setStalled] = useState(false);
  useEffect(() => {
    if (!st || TERMINAL.includes(st.status as RunStatus)) { lastProgressRef.current = null; setStalled(false); return; }
    const prev = lastProgressRef.current;
    if (prev == null || prev.pct !== st.progress_percent) {
      lastProgressRef.current = { pct: st.progress_percent, at: Date.now() };
      setStalled(false);
    }
  }, [st?.progress_percent, st?.status]);
  useEffect(() => {
    const t = setInterval(() => {
      const prev = lastProgressRef.current;
      if (prev) setStalled(Date.now() - prev.at > 45_000);
    }, 2000);
    return () => clearInterval(t);
  }, []);

  // 멈춘 폴링을 사용자가 직접 깨울 수 있는 탈출구 — refetch는 cancelRefetch:true로 나가므로
  // 어떤 이유로든 진행 중인 요청이 묶여 있어도 새 요청을 강제한다.
  const recheck = () => { void statusQ.refetch(); };

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
  // 엔진이 보고한 진행률. 유한한 숫자일 때만 숫자로 다룬다 — null/NaN 을 0 으로
  // 흘려보내면 "측정 안 됨" 이 "0% 진행" 으로 보인다.
  const pct = Number.isFinite(st?.progress_percent as number) ? (st!.progress_percent as number) : null;

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
              {/* ★있는 퍼센트는 지우지 않고, 없는 퍼센트는 지어내지 않는다★ (P8)
                  이 수치는 엔진이 **실제로 끝낸 일**에서 나온다 — 시뮬레이션 완료 일수
                  (`30 + 55*done/total`, backtest_run_routes.py:55-84). 경과 시간이나 UI
                  단계 수에서 만든 값이 아니므로 지울 이유가 없다. 출처를 화면에 밝힌다.

                  ★그런데 없을 때 0 을 적고 있었다★ progress_percent 컬럼은 nullable 인데
                  `Math.round(null)` 은 0 이다. 그래서 엔진이 아무것도 보고하지 않은 런이
                  "0% 진행" 으로 보였다 — 측정하지 않은 것과 0 을 같은 글자로 적는,
                  P5 에서 고친 것과 정확히 같은 결함이다. 이제 없으면 단계 목록만 보여준다. */}
              {pct != null && <span className="num brun-pct">{Math.round(pct)}% <em>엔진 보고</em></span>}
            </div>
            {pct != null
              ? <div className="brun-progress"><i style={{ width: `${Math.max(2, Math.min(100, pct))}%` }} /></div>
              : (
                <ol className="brun-phases">
                  {STAGE_ORDER.map((s) => (
                    <li key={s} className={`brun-phase${s === st.status ? " on" : ""}${
                      STAGE_ORDER.indexOf(s) < curIdx ? " past" : ""}`}>
                      {STAGE_LABELS[s] ?? s}
                    </li>
                  ))}
                </ol>
              )}
            <div className="brun-msg">
              {st.status_message}
              {stalled && (
                <span className="brun-stalled">· 이 실행은 예상보다 오래 걸리고 있습니다 (여전히 실행 중 — 취소/재시도 가능)</span>
              )}
              {reconnecting && (
                <>
                  <span className="brun-reconnect">
                    · 상태를 불러오지 못하고 있습니다 — 아래 숫자는 마지막으로 받은 값입니다.
                    서버에서는 계속 실행 중일 수 있습니다.
                  </span>
                  <button className="brun-recheck" onClick={recheck}>지금 다시 확인</button>
                </>
              )}
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
