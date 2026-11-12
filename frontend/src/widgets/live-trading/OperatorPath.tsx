"use client";
/**
 * 운영 계좌 — 주문이 가는 길 (BU9b). 비상 정지 → 위험 검사 → 실행 모드 → 보내는 곳.
 * ==========================================================================
 * /내 계좌(BV9 `OrderPath`)와 같은 그림(공용 `.tx-path` — BU9b-0)이다. 운영 계좌도 서버의 같은 `execute_signal` 을 지난다.
 * 실행 모드 역의 세 칸: 기록만 = 바로(더 안전한 쪽) · 모의 체결 = 확인 줄 · 실계좌 = 시트(관문이 닫혀 있으면 서버가 사유와 함께 거절).
 * ★켜진 칸은 눌린 채 잠근다★ — 같은 모드를 다시 보내지 않는다(사용자 결정). 바꾸기에 실패하면 사유를 그대로 보인다.
 * 관리자가 아니면 칸을 단추로 만들지 않는다(쓰기 단추 0) — 지금 모드만 글로 말한다.
 */
import { useState } from "react";
import { useMutation, type UseQueryResult } from "@tanstack/react-query";
import { Lock, OctagonX, Send, ShieldCheck, SlidersHorizontal } from "lucide-react";
import type { GateState } from "@/entities/trading/liveGate";
import { setOperatorMode, type OpKill, type OpModeName } from "@/entities/trading/operator";
import { krDateTime } from "@/shared/lib/krFormat";
import { MODE_IS, MODE_TO, killState, opDestination, paperConfirm } from "./sentence";

type Read<T> = { pending: boolean; failed: boolean; value: T | null };

const MODES: { m: "SHADOW" | "PAPER"; act: string; t: string; d: string }[] = [
  { m: "SHADOW", act: "mode-shadow", t: "기록만", d: "전송하지 않습니다" },
  { m: "PAPER", act: "mode-paper", t: "모의 체결", d: "실제 돈은 안 씁니다" },
];

export function OperatorPath({ mode, kill, practice, isAdmin, gate, refused, onRefused, onWritten, onLive, onRetryKill }: {
  mode: Read<OpModeName>; kill: Read<OpKill>; practice: boolean | null; isAdmin: boolean;
  gate: UseQueryResult<GateState>;
  refused: { mode: string; reason: string } | null; onRefused: (r: { mode: string; reason: string } | null) => void;
  onWritten: () => void; onLive: () => void; onRetryKill: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const cur = mode.value;
  const change = useMutation({
    mutationFn: async (m: "SHADOW" | "PAPER") => {
      const r = await setOperatorMode(m);
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: () => { setAsking(false); onRefused(null); },
    onError: (e: Error, m) => { setAsking(false); onRefused({ mode: m, reason: e.message }); },
    // 옛 화면처럼 결과와 상관없이 다시 읽는다(골든 — 쓰기 뒤 읽기 넷).
    onSettled: () => onWritten(),
  });
  const pick = (m: "SHADOW" | "PAPER") => {
    if (m === cur) return;
    onRefused(null);
    if (m === "PAPER") setAsking(true);
    else change.mutate("SHADOW");
  };

  const k = kill.value;
  const ev = k?.is_active ? k.active_event : null;
  const g = gate.data;
  const gateWord = gate.isError ? "관문 미상" : !g ? "관문 확인 중" : g.current ? "관문 열림" : "관문 닫힘";

  return (
    <section className="tx-sec tx-path lv-path" aria-labelledby="lv-path-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="lv-path-h">주문이 가는 길</h2>
          <p className="tx-sec-sub">운영 계좌의 주문은 서버에서 이 순서로 처리됩니다. 전략 주문과 관리자 수동 주문 모두 동일합니다.</p>
        </div>
      </header>
      <ol className="tx-path-l">
        <li className="tx-st" data-st="kill" data-blocked={k?.is_active ? "true" : undefined}>
          <span className="tx-st-dot" aria-hidden><OctagonX className="tx-st-ic" size={14} strokeWidth={2} /></span>
          <div className="tx-st-b">
            <p className="tx-st-name">비상 정지</p>
            <p className="tx-st-state">{killState(kill)}</p>
            <p className="tx-st-sub">
              {kill.failed ? <button type="button" className="lv-link" onClick={onRetryKill}>재시도</button>
                : ev ? <>사유 <span data-server>{ev.trigger_reason ?? "적히지 않았습니다"}</span>{ev.triggered_at ? ` · ${krDateTime(ev.triggered_at) ?? ev.triggered_at}` : ""}</>
                : k?.is_active ? "정지 기록 읽기 실패. 새 주문은 막혀 있습니다."
                : "켜면 운영 계좌와 모든 사용자 계좌의 신규 주문을 중단합니다."}
            </p>
          </div>
        </li>
        <li className="tx-st" data-st="risk">
          <span className="tx-st-dot" aria-hidden><ShieldCheck className="tx-st-ic" size={14} strokeWidth={2} /></span>
          <div className="tx-st-b">
            <p className="tx-st-name">위험 검사</p>
            <p className="tx-st-state">주문마다 서버가 따집니다</p>
            <p className="tx-st-sub">가격·일일 거래 한도·장 운영 시간 등을 점검합니다. 위반 시 주문하지 않습니다.</p>
          </div>
        </li>
        <li className="tx-st" data-st="mode">
          <span className="tx-st-dot" aria-hidden><SlidersHorizontal className="tx-st-ic" size={14} strokeWidth={2} /></span>
          <div className="tx-st-b">
            <p className="tx-st-name">실행 모드</p>
            {isAdmin ? (
              <div className="tx-modes lv-modes" role="group" aria-label="실행 모드">
                {MODES.map((x) => (
                  <button key={x.m} type="button" className="tx-mode-b" data-mode={x.m} data-act={x.act}
                          aria-pressed={cur === x.m} data-locked={cur === x.m ? "true" : undefined}
                          disabled={cur === null || cur === x.m || change.isPending} onClick={() => pick(x.m)}>
                    <span className="tx-mode-t">{x.t}</span><span className="tx-mode-d">{cur === x.m ? "현재 모드입니다" : x.d}</span>
                  </button>
                ))}
                <button type="button" className="tx-mode-b tx-mode-b--live" data-mode="LIVE" data-act="mode-live"
                        aria-pressed={cur === "LIVE"} data-locked={cur === "LIVE" ? "true" : undefined}
                        disabled={cur === null || cur === "LIVE" || change.isPending} onClick={() => { setAsking(false); onLive(); }}>
                  <span className="tx-mode-t"><Lock size={14} aria-hidden /> 실계좌</span>
                  <span className="tx-mode-d">{cur === "LIVE" ? "현재 모드입니다" : gateWord}</span>
                </button>
              </div>
            ) : (
              <p className="tx-st-state">{mode.pending ? "확인 중" : cur === null ? "확인 실패"
                : MODE_IS[cur] ?? <span data-server>{cur}</span>}</p>
            )}
            <p className="tx-st-sub">서버를 재시작하면 기록만 모드로 복귀합니다.</p>
            {asking ? (
              <div className="tx-confirm lv-paper-confirm" role="group" aria-label="모의 체결로 바꾸기 확인">
                <p>{paperConfirm(practice)}</p>
                <div className="tx-confirm-act">
                  <button type="button" className="tx-btn tx-btn--main" data-act="paper-yes" disabled={change.isPending}
                          onClick={() => change.mutate("PAPER")}>바꾸기</button>
                  <button type="button" className="tx-btn tx-btn--sub" data-act="paper-no" onClick={() => setAsking(false)}>취소</button>
                </div>
              </div>
            ) : null}
            {refused ? (
              <p className="live-mode-refused lv-err" role="alert" data-mode={refused.mode}>
                {MODE_TO[refused.mode] ?? `‘${refused.mode}’ 모드로`} 바꾸지 못했습니다. <span data-server>{refused.reason}</span>
              </p>
            ) : null}
          </div>
        </li>
        <li className="tx-st" data-st="broker">
          <span className="tx-st-dot" aria-hidden><Send className="tx-st-ic" size={14} strokeWidth={2} /></span>
          <div className="tx-st-b">
            <p className="tx-st-name">전송 대상</p>
            <p className="tx-st-state">{cur === null ? "모드를 몰라서 정할 수 없습니다" : opDestination(cur, practice)}</p>
            <p className="tx-st-sub">
              {cur === "PAPER" && practice === false ? "서버의 증권사 연결이 모의투자가 아니면 서버가 거절합니다."
                : cur === "LIVE" ? "실계좌 관문을 통과해야 실제로 주문합니다."
                : "운영 계좌는 서버에 연결된 증권 계좌 하나입니다."}
            </p>
          </div>
        </li>
      </ol>
    </section>
  );
}
