"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RunMonitor — 백테스트 실행 로딩 페이지 (전용 잡 모니터, 스펙 §4)
//   run_id 상태를 폴링(refetchInterval)하며 실 단계·진행률·경과시간·활동 타임라인·
//   데이터 honesty 배지를 표시. completed → 결과 페이지로 replace. failed/cancelled →
//   전체 에러 상태(안전 재시도). 서버 영속 상태라 새로고침·직접 URL·네트워크 단절 복구.
//   BU4: 답 한 문장("돌리는 중이에요 — 지금 단계") + 단계 막대 · 제출한 설정은 접힘 · 취소/재실행 실패를 삼키지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import {
  backtestRunApi, STAGE_LABELS, STAGE_ORDER, TERMINAL, type RunStatus,
} from "@/entities/backtest-run/api";
import { Notice, PageHead } from "@/shared/ui/tx";

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
  const [actErr, setActErr] = useState<{ what: string; detail: string } | null>(null);

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
  const err = statusQ.error as { httpStatus?: number; storeCause?: string; message?: string } | null;
  // 백엔드는 진짜 없는 실행만 404, DB 일시 오류는 503 → 404만 "만료/잘못된 링크"로 확정 처리.
  const trulyGone = statusQ.isLoadingError && err?.httpStatus === 404;
  // 1초 폴링 + retry:false라 한 번의 blip으로도 isError가 되므로, 연속 실패가 몇 번 쌓였을
  // 때만 표시(깜빡임 방지). failureCount는 성공하면 0으로 리셋된다.
  const reconnecting = statusQ.failureCount >= 3 && !!st && !TERMINAL.includes(st.status as RunStatus);
  // ★"연결이 불안정" 만으로는 다음에 어디를 팔지 알 수 없다★ 백엔드가 503 에 실어 준
  // 분류(커넥션 풀 고갈 / 저장소 잠김 / 접속 불가)를 그대로 한 줄 덧붙인다. 분류가
  // 없으면(네트워크 단절 등 서버에 닿지도 못한 경우) 아무 말도 지어내지 않는다.
  const storeCauseText = err?.httpStatus === 503 && err?.message ? err.message : null;

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
    return (
      <div className="tx-page brun-shell rs">
        <div className="brun-err rs-state">
          <Notice tone="warn" title="이 실행을 찾지 못했어요">만료되었거나 잘못된 링크일 수 있어요. 편집기에서 다시 실행해 주세요.</Notice>
          <div className="rs-acts"><Link href="/backtest" className="tx-btn tx-btn--sub">편집기로 돌아가기</Link></div>
        </div>
      </div>
    );
  }
  // 아직 첫 상태가 없음 — 로딩 중(또는 일시적 오류로 재시도 중, 폴링은 계속됨)
  if (!st) {
    return <div className="tx-page brun-shell rs"><div className="brun-loading">
      {statusQ.isError ? "실행 상태를 불러오는 중이에요 — 연결이 불안정해 다시 묻고 있어요" : "실행 상태를 불러오는 중이에요"}
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
  // 데이터 출처 — ★"실데이터" 라고 부르지 않는다★ mock 이면 연습용, 아니면 말하지 않는다(결과 화면 PerfLabel 이 말한다), 모르면 모른다.
  const dataChip = st.is_mock_data === true ? { label: "연습용 데이터", tone: "practice" }
    : st.is_mock_data == null ? { label: "데이터 출처를 아직 몰라요", tone: "unknown" } : null;

  const doCancel = async () => {
    setCancelling(true); setActErr(null);
    try { await backtestRunApi.cancel(runId); await statusQ.refetch(); }
    catch (e) { setActErr({ what: "실행을 취소하지 못했어요", detail: (e as Error).message || "알 수 없는 오류" }); }
    setCancelling(false);
  };
  const doRetry = async () => {
    setActErr(null);
    try { const r = await backtestRunApi.retry(runId); router.replace(`/backtest/runs/${r.run_id}/loading`); }
    catch (e) { setActErr({ what: "다시 실행하지 못했어요", detail: (e as Error).message || "알 수 없는 오류" }); }
  };
  const stageName = STAGE_LABELS[st.status] ?? st.status;

  return (
    <div className="tpage-fade tx-page brun-shell rs rs-run">
      <PageHead title={st.strategy_name} lede={<>백테스트 실행 <span className="rs-id" aria-label="실행 번호">{runId}</span></>} />

      {failed ? (
        <div className="brun-err-panel">
          <div className="brun-err-title">{st.status === "cancelled" ? "실행이 취소되었어요" : "실행이 실패했어요"}</div>
          {st.error_message && <div className="brun-err-msg">{st.error_message}</div>}
          {st.correlation_id && <div className="brun-err-cid">추적 번호 <span className="rs-id">{st.correlation_id}</span></div>}
          <div className="brun-err-actions rs-acts">
            <button type="button" className="tx-btn tx-btn--main" onClick={doRetry}>다시 실행</button>
            <Link href="/backtest" className="tx-btn tx-btn--sub">편집기로 돌아가기</Link>
          </div>
        </div>
      ) : (
        <>
          <section className="tx-answer rs-answer" aria-label="한 줄 답">
            <p className="tx-answer-s">백테스트를 돌리는 중이에요 — {stageName}</p>
            <ul className="tx-chips" aria-label="이 실행의 근거">
              {dataChip && <li className="tx-chip" data-tone={dataChip.tone}>{dataChip.label}</li>}
              <li className="tx-chip" data-tone="plain">지난 시간 {elapsedStr}</li>
            </ul>
            <div className="brun-progress-wrap">
              <div className="brun-progress-top">
                <span className="brun-stage">{stageName}</span>
                {/* ★있는 퍼센트는 지우지 않고, 없는 퍼센트는 지어내지 않는다★ (P8)
                    이 수치는 엔진이 **실제로 끝낸 일**에서 나온다 — 시뮬레이션 완료 일수
                    (`30 + 55*done/total`, backtest_run_routes.py:55-84). 출처를 화면에 밝힌다.
                    없으면(nullable) 0% 를 적지 않고 단계 목록만 보인다 — 측정 안 됨 ≠ 0% 진행. */}
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
                  <span className="brun-stalled">· 예상보다 오래 걸리고 있어요(여전히 실행 중이에요 — 취소하거나 기다릴 수 있어요)</span>
                )}
                {reconnecting && (
                  <>
                    <span className="brun-reconnect">
                      · 상태를 불러오지 못하고 있어요 — 위 숫자는 마지막으로 받은 값이에요.
                      서버에서는 계속 실행 중일 수 있어요.
                      {storeCauseText && ` (${storeCauseText})`}
                    </span>
                    <button type="button" className="brun-recheck" onClick={recheck}>지금 다시 확인</button>
                  </>
                )}
              </div>
            </div>
            <p className="rs-why">끝나면 결과 화면으로 저절로 옮겨 가요. 이 창을 닫아도 실행은 계속돼요.</p>
          </section>

          <section className="brun-card rs-card">
            <h2 className="brun-card-t">진행 단계</h2>
            <ul className="brun-timeline">
              {STAGE_ORDER.filter((s) => s !== "completed").map((s) => {
                const i = STAGE_ORDER.indexOf(s);
                const state = i < curIdx ? "done" : i === curIdx ? "active" : "pending";
                return (
                  <li key={s} className={`brun-tl ${state}`}>
                    <span className="brun-tl-dot" />
                    <span className="brun-tl-lab">{STAGE_LABELS[s]}</span>
                    {state === "done" && <span className="rs-tl-st">끝났어요</span>}
                    {state === "active" && <span className="rs-tl-st">하는 중</span>}
                  </li>
                );
              })}
            </ul>
            <div className="rs-acts">
              <button type="button" className="brun-btn tx-btn tx-btn--sub" disabled={cancelling} onClick={doCancel}>{cancelling ? "취소하는 중이에요" : "실행 취소"}</button>
            </div>
            {actErr && (
              <Notice tone="danger" title={actErr.what}>
                실행 상태는 그대로예요. 잠시 뒤 다시 눌러 주세요.
                <details className="scr-err-detail"><summary>자세히</summary><code>{actErr.detail}</code></details>
              </Notice>
            )}
          </section>

          <section className="brun-card rs-card">
            <details className="rs-cfg">
              <summary className="rs-more"><span>제출한 설정 보기</span><span className="rs-more-n">재현 스냅샷</span><ChevronDown size={18} aria-hidden className="rs-more-i" /></summary>
              <table className="brun-cfg">
                <tbody>
                  {CONFIG_ROWS.filter(([k]) => cfg[k] != null && cfg[k] !== "").map(([k, label]) => (
                    <tr key={k}><td>{label}</td><td className="num">{fmtVal(cfg[k])}</td></tr>
                  ))}
                  {Object.keys(cfg).length === 0 && <tr><td colSpan={2} className="brun-note">설정을 불러오는 중이에요</td></tr>}
                </tbody>
              </table>
              <p className="brun-note">가격·비용은 실행 전에 정한 추정이에요. 결과는 끝난 뒤 고정 주소에서 다시 볼 수 있어요.</p>
            </details>
          </section>
        </>
      )}
      {failed && actErr && (
        <Notice tone="danger" title={actErr.what}>
          잠시 뒤 다시 눌러 주세요.
          <details className="scr-err-detail"><summary>자세히</summary><code>{actErr.detail}</code></details>
        </Notice>
      )}
    </div>
  );
}
