"use client";
/**
 * 운영 계좌 시트 셋 (BU9b) — 실계좌로 바꾸기 · 비상 정지 · 비상 정지 풀기. 공용 시트(`shared/ui/tx/Sheet` — 네이티브 dialog:
 * Esc·초점 가두기·배경 비활성은 브라우저가 한다). 옛 `ConfirmModal`(div, Esc 없음)을 대신한다.
 * ★본문은 바이트 그대로★(`entities/trading/operator` 상수) — 사유 칸이 없다. 서버 기록에 남는 글을 그대로 보여 준다.
 * 실패는 시트 안에 서버 사유 그대로(비상 정지·풀기) · 실계좌 거절은 길의 실행 모드 역에(부르는 쪽이 받는다).
 */
import { useMutation, type UseQueryResult } from "@tanstack/react-query";
import type { GateState } from "@/entities/trading/liveGate";
import {
  KILL_BODY, LIVE_CONFIRM_TOKEN, RESOLVE_BODY, resolveOperatorKill, setOperatorLive, triggerOperatorKill,
} from "@/entities/trading/operator";
import { Sheet } from "@/shared/ui/tx";

export function LiveSheet({ open, gate, onClose, onSettled }: {
  open: boolean; gate: UseQueryResult<GateState>; onClose: () => void; onSettled: (refusedReason: string | null) => void;
}) {
  const go = useMutation({
    mutationFn: async () => {
      const r = await setOperatorLive();
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: () => onSettled(null),
    onError: (e: Error) => onSettled(e.message),
  });
  const g = gate.data;
  const users = g?.current?.allowed_users ?? [];
  return (
    <Sheet open={open} onClose={onClose} title="실계좌로 바꾸기" testId="live" className="lv-sheet"
           sub="운영 계좌 주문이 실제 돈으로 나갑니다. 증권사로 바로 주문을 보냅니다.">
      <div className={`lv-gate-line${g?.current ? " is-open" : ""}`} role="status">
        {gate.isError ? "실계좌 관문 상태 확인 실패. 서버가 판단합니다."
          : !g ? "실계좌 관문 상태 확인 중"
          : g.current ? <>실계좌 관문이 열려 있습니다. 허용한 사용자: {users.map((u) => <span key={u} className="tx-chip lv-user" data-tone="plain">{u}</span>)}</>
          : "실계좌 관문이 닫혀 있습니다. 서버가 사유와 함께 거절합니다."}
      </div>
      <ul className="lv-sheet-l">
        <li>주문마다 위험 검사(가격, 하루 거래 한도, 장 시간)는 그대로 걸립니다.</li>
        <li>비상 정지를 걸면 미체결 주문을 취소하고 새 주문을 멈춥니다.</li>
        <li>서버를 다시 켜면 기록만으로 돌아갑니다.</li>
      </ul>
      <p className="lv-said">함께 보내는 확인 코드 <code data-mono>{LIVE_CONFIRM_TOKEN}</code></p>
      <div className="tx-confirm-act">
        <button type="button" className="tx-btn lv-btn-danger" data-act="live-yes" disabled={go.isPending}
                onClick={() => go.mutate()}>{go.isPending ? "변경 중" : "실계좌로 바꾸기"}</button>
        <button type="button" className="tx-btn tx-btn--sub" data-act="live-no" onClick={onClose}>취소</button>
      </div>
    </Sheet>
  );
}

export function KillSheets({ open, onClose, onDone, onSettled }: {
  open: "kill" | "resolve" | null; onClose: () => void; onDone: (said: string) => void; onSettled: () => void;
}) {
  const trigger = useMutation({
    mutationFn: async () => {
      const r = await triggerOperatorKill();
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (r) => {
      const n = r.n_orders_cancelled;
      onDone(n === null || n === undefined ? "비상 정지를 걸었습니다. 미체결 주문을 몇 건 취소했는지는 미상입니다."
        : `비상 정지를 걸었습니다. 운영 계좌의 미체결 ${n}건을 취소했습니다.`);
    },
    // 옛 화면처럼 결과와 상관없이 다시 읽는다.
    onSettled: () => onSettled(),
  });
  const resolve = useMutation({
    mutationFn: async () => {
      const r = await resolveOperatorKill();
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (r) => onDone(r.status === "no_active_event" ? "이미 풀려 있었습니다." : "비상 정지를 풀었습니다. 새 주문을 다시 받습니다."),
    onSettled: () => onSettled(),
  });

  return (
    <>
      <Sheet open={open === "kill"} onClose={() => { trigger.reset(); onClose(); }} title="비상 정지" testId="kill" className="lv-sheet"
             sub="운영 계좌의 미체결 주문을 취소하고, 운영 계좌와 모든 사용자 계좌의 새 주문을 멈춥니다. 보유 종목은 팔지 않습니다.">
        <p className="lv-said">서버 기록에는 이렇게 남습니다 <code>{KILL_BODY.reason}</code> · 청산 방식 그대로 두기</p>
        {trigger.isError ? <p className="lv-err" role="alert">비상 정지를 걸지 못했습니다. <span data-server>{trigger.error.message}</span></p> : null}
        <div className="tx-confirm-act">
          <button type="button" className="tx-btn lv-btn-danger" data-act="kill-yes" disabled={trigger.isPending}
                  onClick={() => trigger.mutate()}>{trigger.isPending ? "설정 중" : "비상 정지 걸기"}</button>
          <button type="button" className="tx-btn tx-btn--sub" data-act="kill-no" onClick={() => { trigger.reset(); onClose(); }}>취소</button>
        </div>
      </Sheet>
      <Sheet open={open === "resolve"} onClose={() => { resolve.reset(); onClose(); }} title="비상 정지 풀기" testId="resolve" className="lv-sheet"
             sub="풀면 운영 계좌와 사용자 계좌가 다시 새 주문을 받습니다. 사용자가 자기 계좌에 건 정지는 그대로입니다.">
        <p className="lv-said">서버 기록에는 이렇게 남습니다 <code>{RESOLVE_BODY.notes}</code></p>
        {resolve.isError ? <p className="lv-err" role="alert">비상 정지를 풀지 못했습니다. <span data-server>{resolve.error.message}</span></p> : null}
        <div className="tx-confirm-act">
          <button type="button" className="tx-btn tx-btn--main" data-act="resolve-yes" disabled={resolve.isPending}
                  onClick={() => resolve.mutate()}>{resolve.isPending ? "해제 중" : "비상 정지 풀기"}</button>
          <button type="button" className="tx-btn tx-btn--sub" data-act="resolve-no" onClick={() => { resolve.reset(); onClose(); }}>취소</button>
        </div>
      </Sheet>
    </>
  );
}
