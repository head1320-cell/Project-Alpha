"use client";
/**
 * 주문이 가는 길 (BV9) — 비상 정지 → 위험 검사 → 실행 모드 → 증권사.
 * ==========================================================================
 * 평소에는 역마다 "지금 주문하면 여기서 무엇이 일어나나"를 서버 값으로 말하고, 주문을 내면 서버가 멈춘 역에 표시를 켠다.
 * 실행 모드 역에 세 칸(기록만 · 모의 체결 · 실계좌)이 있다. ★실계좌 칸은 요청을 보내지 않는다★ — 준비 목록만 펼친다(서버에 전환 길이 없다).
 * 모의 체결로 바꾸기는 확인 줄을 거친다(주문이 밖으로 나가기 시작하는 쪽). 기록만으로 돌아가기는 바로(더 안전한 쪽).
 */
import { useState } from "react";
import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Check, Lock, OctagonX, Send, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import {
  STATUS_KO, STOPS, destination, setAccountMode,
  type AccountKill, type AccountMode, type BrokerAccount, type OrderReply, type Readiness, type Stop,
} from "@/entities/broker-account";
import { RetryFail } from "@/shared/ui/tx";

export type Trace = { stop: Stop | "unknown"; reply: OrderReply };

export function OrderPath({ acc, mode, kill, ready, practice, trace }: {
  acc: BrokerAccount; mode: UseQueryResult<AccountMode>; kill: UseQueryResult<AccountKill>;
  ready: UseQueryResult<Readiness>; practice: boolean | null; trace: Trace | null;
}) {
  const id = acc.account_id;
  const qc = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [openReady, setOpenReady] = useState(false);
  const cur = mode.data?.mode ?? null;
  const change = useMutation({
    mutationFn: async (m: "SHADOW" | "PAPER") => {
      const r = await setAccountMode(id, m);
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: () => { setAsking(false); void qc.invalidateQueries({ queryKey: ["acct", id] }); },
  });
  const pick = (m: "SHADOW" | "PAPER") => {
    change.reset();
    if (m === cur) return;
    if (m === "PAPER") setAsking(true);
    else change.mutate("SHADOW");
  };

  const items = ready.data?.items ?? [];
  const okN = items.filter((i) => i.ok).length;
  const conn = items.find((i) => i.key === "connection");
  const stopIdx = trace ? STOPS.findIndex((s) => s.key === trace.stop) : -1;
  const hit = (i: number) => (stopIdx < 0 ? undefined : i < stopIdx ? "pass" : i === stopIdx ? "stop" : undefined);

  const k = kill.data;
  const killState = kill.isPending ? "확인하는 중이에요" : kill.isError ? "확인하지 못했어요"
    : k?.active && k.event ? "켜져 있어요" : k?.active ? "주문이 막혀 있어요" : "꺼져 있어요";
  const killSub = kill.isError ? <button type="button" className="ma-link" onClick={() => void kill.refetch()}>다시 시도</button>
    : k?.active && k.event ? <>사유 <span data-server>{k.event.trigger_reason ?? "적히지 않았어요"}</span></>
    : k?.active ? "이 계좌가 건 정지가 아니에요. 운영자 정지이거나 상태를 읽지 못했어요."
    : "켜면 새 주문과 미체결 주문을 멈춰요.";

  return (
    <section className="tx-sec ma-path" aria-labelledby="ma-path-h" data-stop={trace ? trace.stop : undefined}>
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="ma-path-h">주문이 가는 길</h2>
          <p className="tx-sec-sub">주문은 서버에서 이 순서로 지나가요. 주문을 내면 어디서 멈췄는지 여기 표시돼요.</p>
        </div>
      </header>
      <ol className="ma-path-l" key={trace?.reply.client_order_id ?? "idle"}>
        <li className="ma-st" data-st="kill" data-hit={hit(0)} data-blocked={k?.active ? "true" : undefined}>
          <span className="ma-st-dot" aria-hidden><OctagonX className="ma-st-ic" size={14} strokeWidth={2} /></span>
          <div className="ma-st-b">
            <p className="ma-st-name">비상 정지</p>
            <p className="ma-st-state">{killState}</p>
            <p className="ma-st-sub">{killSub}</p>
          </div>
        </li>
        <li className="ma-st" data-st="risk" data-hit={hit(1)}>
          <span className="ma-st-dot" aria-hidden><ShieldCheck className="ma-st-ic" size={14} strokeWidth={2} /></span>
          <div className="ma-st-b">
            <p className="ma-st-name">위험 검사</p>
            <p className="ma-st-state">주문마다 서버가 따져요</p>
            <p className="ma-st-sub">가격, 하루 거래 한도, 장 시간 같은 것을 봐요. 걸리면 주문하지 않아요.</p>
          </div>
        </li>
        <li className="ma-st ma-st--mode" data-st="mode" data-hit={hit(2)}>
          <span className="ma-st-dot" aria-hidden><SlidersHorizontal className="ma-st-ic" size={14} strokeWidth={2} /></span>
          <div className="ma-st-b">
            <p className="ma-st-name">실행 모드</p>
            <div className="ma-mode" role="group" aria-label="실행 모드">
              <button type="button" className="ma-mode-b" data-mode="SHADOW" aria-pressed={cur === "SHADOW"}
                      disabled={cur === null || change.isPending} onClick={() => pick("SHADOW")}>
                <span className="ma-mode-t">기록만</span><span className="ma-mode-d">보내지 않아요</span>
              </button>
              <button type="button" className="ma-mode-b" data-mode="PAPER" aria-pressed={cur === "PAPER"}
                      disabled={cur === null || change.isPending || !acc.is_paper} onClick={() => pick("PAPER")}>
                <span className="ma-mode-t">모의 체결</span><span className="ma-mode-d">실제 돈은 안 써요</span>
              </button>
              <button type="button" className="ma-mode-b ma-mode-b--live" data-mode="LIVE" aria-pressed={cur === "LIVE"}
                      aria-expanded={openReady} aria-controls="ma-ready" onClick={() => setOpenReady((o) => !o)}>
                <span className="ma-mode-t"><Lock size={14} aria-hidden /> 실계좌</span>
                <span className="ma-mode-d">{ready.data ? `준비 ${okN}/${items.length}` : ready.isError ? "준비 몰라요" : "준비 확인 중"}</span>
              </button>
            </div>
            {!acc.is_paper ? (
              <p className="ma-st-sub ma-mode-why">모의 체결은 모의투자 계좌에서만 써요. 이 계좌는 실계좌로 연결돼 있어요.</p>
            ) : null}
            <p className="ma-st-sub">
              {mode.data?.changed_by ? `${mode.data.changed_by} 님이 바꿨어요. ` : ""}서버를 다시 켜면 기록만으로 돌아가요.
            </p>
            {asking ? (
              <div className="ma-confirm ma-mode-confirm" role="group" aria-label="모의 체결로 바꾸기 확인">
                <p>모의 체결로 바꾸면 주문을 {practice === true ? "연습용 체결기로" : practice === false ? "증권사 모의 서버로" : "모의 체결로"} 보내요. 실제 돈은 쓰지 않아요.</p>
                <div className="ma-confirm-act">
                  <button type="button" className="tx-btn tx-btn--main ma-mode-yes" disabled={change.isPending}
                          onClick={() => change.mutate("PAPER")}>바꾸기</button>
                  <button type="button" className="tx-btn tx-btn--sub ma-mode-no" onClick={() => setAsking(false)}>취소</button>
                </div>
              </div>
            ) : null}
            {change.isError ? (
              <p className="ma-err ma-mode-err" role="alert">모드를 바꾸지 못했어요. <span data-server>{change.error.message}</span></p>
            ) : null}
          </div>
        </li>
        <li className="ma-st" data-st="broker" data-hit={hit(3)}>
          <span className="ma-st-dot" aria-hidden><Send className="ma-st-ic" size={14} strokeWidth={2} /></span>
          <div className="ma-st-b">
            <p className="ma-st-name">보내는 곳</p>
            <p className="ma-st-state">{cur === null ? "모드를 몰라서 정할 수 없어요" : destination(cur, practice)}</p>
            <p className="ma-st-sub">{conn ? <>연결 확인: <span data-server>{conn.reason}</span></> : "연결 확인 기록을 불러오는 중이에요."}</p>
          </div>
        </li>
      </ol>

      {trace ? <StopWhy trace={trace} practice={practice} /> : null}

      {openReady ? (
        <div className="ma-ready" id="ma-ready">
          <p className="ma-strong">실계좌로 가려면</p>
          {ready.isError ? (
            <RetryFail title="준비 목록을 불러오지 못했어요" onRetry={() => void ready.refetch()}>{ready.error.message}</RetryFail>
          ) : !ready.data ? (
            <p className="tx-sec-sub" aria-busy="true">준비 목록을 불러오는 중이에요.</p>
          ) : (
            <ul className="ma-ready-l">
              {items.map((i) => (
                <li key={i.key} className="ma-ready-i" data-key={i.key} data-ok={String(i.ok)}>
                  {i.ok ? <Check className="ma-ready-ic" size={16} aria-label="됐어요" /> : <X className="ma-ready-ic" size={16} aria-label="아직이에요" />}
                  <span data-server>{i.reason}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="tx-sec-sub">실계좌 전환은 아직 열리지 않아요. 이 화면에는 실계좌로 바꾸는 단추가 없어요.</p>
        </div>
      ) : null}
    </section>
  );
}

/**
 * 주문이 멈춘 곳 — 서버 상태·사유 코드를 옮긴다. 거절 사유·실패 원문은 보이게(무엇이 막았는지가 답이다),
 * 기록만·보냄의 서버 상투 문장은 닫힌 "서버 원문" 안에 그대로 둔다(지우지 않는다).
 */
function StopWhy({ trace, practice }: { trace: Trace; practice: boolean | null }) {
  const r = trace.reply;
  const where = practice === true ? "연습용 체결기" : practice === false ? "증권사 모의 서버" : null;
  const head = trace.stop === "unknown" ? "어디서 멈췄는지 몰라요"
    : trace.stop === "broker"
      ? (r.status === "FAILED" ? "보내다 실패했어요" : where ? `${where}까지 갔어요` : "끝까지 갔어요")
      : `${STOPS.find((s) => s.key === trace.stop)?.label}에서 멈췄어요`;
  const visible = r.status === "REJECTED" ? r.message : r.status === "FAILED" ? r.error : null;
  const tucked = visible ? null : r.message;
  const said = r.status === "SHADOW_LOGGED" ? "기록만 하고 보내지 않았어요."
    : r.status === "SUBMITTED" ? "주문을 받았어요."
    : STATUS_KO[r.status] ? `${STATUS_KO[r.status]}.` : null;
  return (
    <div className="ma-stop-why" role="status" data-status={r.status}>
      <p className="ma-strong">{head}</p>
      <p className="tx-sec-sub">
        {said ?? <>서버 상태 <span data-server>{r.status}</span>.</>}
        {visible ? <> <span data-server>{visible}</span></> : null}
        {r.kis_order_id ? <> 주문번호 <span data-mono data-server>{r.kis_order_id}</span></> : null}
      </p>
      {tucked ? (
        <details className="ma-raw"><summary>서버 원문 보기</summary><code data-server>{tucked}</code></details>
      ) : null}
    </div>
  );
}
