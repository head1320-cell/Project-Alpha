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
  { m: "SHADOW", act: "mode-shadow", t: "기록만", d: "보내지 않아요" },
  { m: "PAPER", act: "mode-paper", t: "모의 체결", d: "실제 돈은 안 써요" },
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
  const gateWord = gate.isError ? "관문 몰라요" : !g ? "관문 확인 중" : g.current ? "관문 열림" : "관문 닫힘";

  return (
    <section className="tx-sec tx-path lv-path" aria-labelledby="lv-path-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="lv-path-h">주문이 가는 길</h2>
          <p className="tx-sec-sub">운영 계좌의 주문은 서버에서 이 순서로 지나가요. 전략이 낸 주문도, 관리자가 직접 낸 주문도 같아요.</p>
        </div>
      </header>
      <ol className="tx-path-l">
        <li className="tx-st" data-st="kill" data-blocked={k?.is_active ? "true" : undefined}>
          <span className="tx-st-dot" aria-hidden><OctagonX className="tx-st-ic" size={14} strokeWidth={2} /></span>
          <div className="tx-st-b">
            <p className="tx-st-name">비상 정지</p>
            <p className="tx-st-state">{killState(kill)}</p>
            <p className="tx-st-sub">
              {kill.failed ? <button type="button" className="lv-link" onClick={onRetryKill}>다시 시도</button>
                : ev ? <>사유 <span data-server>{ev.trigger_reason ?? "적히지 않았어요"}</span>{ev.triggered_at ? ` · ${krDateTime(ev.triggered_at) ?? ev.triggered_at}` : ""}</>
                : k?.is_active ? "정지 기록을 읽지 못했어요. 새 주문은 막혀 있어요."
                : "켜면 운영 계좌와 모든 사용자 계좌의 새 주문을 멈춰요."}
            </p>
          </div>
        </li>
        <li className="tx-st" data-st="risk">
          <span className="tx-st-dot" aria-hidden><ShieldCheck className="tx-st-ic" size={14} strokeWidth={2} /></span>
          <div className="tx-st-b">
            <p className="tx-st-name">위험 검사</p>
            <p className="tx-st-state">주문마다 서버가 따져요</p>
            <p className="tx-st-sub">가격, 하루 거래 한도, 장 시간 같은 것을 봐요. 걸리면 주문하지 않아요.</p>
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
                    <span className="tx-mode-t">{x.t}</span><span className="tx-mode-d">{cur === x.m ? "지금 이 모드예요" : x.d}</span>
                  </button>
                ))}
                <button type="button" className="tx-mode-b tx-mode-b--live" data-mode="LIVE" data-act="mode-live"
                        aria-pressed={cur === "LIVE"} data-locked={cur === "LIVE" ? "true" : undefined}
                        disabled={cur === null || cur === "LIVE" || change.isPending} onClick={() => { setAsking(false); onLive(); }}>
                  <span className="tx-mode-t"><Lock size={14} aria-hidden /> 실계좌</span>
                  <span className="tx-mode-d">{cur === "LIVE" ? "지금 이 모드예요" : gateWord}</span>
                </button>
              </div>
            ) : (
              <p className="tx-st-state">{mode.pending ? "확인하는 중이에요" : cur === null ? "확인하지 못했어요"
                : MODE_IS[cur] ?? <span data-server>{cur}</span>}</p>
            )}
            <p className="tx-st-sub">서버를 다시 켜면 기록만으로 돌아가요.</p>
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
                {MODE_TO[refused.mode] ?? `‘${refused.mode}’ 모드로`} 바꾸지 못했어요. <span data-server>{refused.reason}</span>
              </p>
            ) : null}
          </div>
        </li>
        <li className="tx-st" data-st="broker">
          <span className="tx-st-dot" aria-hidden><Send className="tx-st-ic" size={14} strokeWidth={2} /></span>
          <div className="tx-st-b">
            <p className="tx-st-name">보내는 곳</p>
            <p className="tx-st-state">{cur === null ? "모드를 몰라서 정할 수 없어요" : opDestination(cur, practice)}</p>
            <p className="tx-st-sub">
              {cur === "PAPER" && practice === false ? "서버의 증권사 연결이 모의투자가 아니면 서버가 거절해요."
                : cur === "LIVE" ? "실계좌 관문을 통과해야 실제로 주문해요."
                : "운영 계좌는 서버에 연결된 증권 계좌 하나예요."}
            </p>
          </div>
        </li>
      </ol>
    </section>
  );
}
