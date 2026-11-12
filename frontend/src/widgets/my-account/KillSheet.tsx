"use client";
/**
 * 비상 정지 걸기·풀기 (BV9) — 시트(`shared/ui/tx/Sheet`).
 * ★청산은 '그대로 두기'(hold)만★(사용자 결정) — 새 주문과 미체결 주문만 멈추고 보유는 팔지 않는다. 고르는 칸이 없다.
 * 사유는 서버 규칙대로 4자 이상(기록에 남는다). 풀기는 이 계좌가 직접 건 정지에만 연다(부르는 쪽이 정한다).
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { resolveAccountKill, triggerAccountKill } from "@/entities/broker-account";
import { Sheet } from "@/shared/ui/tx";

const MIN_REASON = 4;   // 서버 AccountKillRequest.reason min_length
/** 자주 쓰는 사유 — 누르면 칸을 채울 뿐(고쳐 써도 된다). 기록에는 칸의 글이 남는다. */
const PRESETS = ["시장 급변동", "주문 오류 의심", "전략 재점검"];

export function KillSheet({ accountId, open, onClose, onDone }: {
  accountId: string; open: "kill" | "resolve" | null; onClose: () => void; onDone: (said: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const trigger = useMutation({
    mutationFn: async () => {
      const r = await triggerAccountKill(accountId, reason.trim());
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (r) => {
      const n = r.n_orders_cancelled;
      onDone(n === null || n === undefined ? "비상 정지를 발동했습니다. 미체결 주문 취소 건수는 미상입니다."
        : `비상 정지를 발동했습니다. 미체결 ${n}건을 취소했습니다.`);
      setReason("");
    },
  });
  const resolve = useMutation({
    mutationFn: async () => {
      const r = await resolveAccountKill(accountId, notes.trim());
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (r) => {
      onDone(r.status === "no_active_event" ? "이미 해제돼 있었습니다." : "비상 정지를 해제했습니다. 신규 주문 접수를 재개합니다.");
      setNotes("");
    },
  });

  return (
    <>
      <Sheet open={open === "kill"} onClose={onClose} title="비상 정지" testId="kill" className="ma-sheet"
             sub="신규 주문과 미체결 주문을 중단합니다. 보유 종목은 매도하지 않습니다.">
        <div className="ma-chips ma-kill-presets" role="group" aria-label="자주 사용하는 사유">
          {PRESETS.map((t) => (
            <button key={t} type="button" className="ma-chip-b ma-kill-preset" aria-pressed={reason === t} onClick={() => setReason(t)}>{t}</button>
          ))}
        </div>
        <label className="ma-field">
          <span className="ma-label">정지 사유</span>
          <textarea className="ma-input ma-textarea" name="ma-kill-reason" rows={3} maxLength={500}
                    value={reason} onChange={(e) => setReason(e.target.value)} />
          <span className="ma-hint">{MIN_REASON}자 이상 입력하십시오. 기록에 남습니다.</span>
        </label>
        {trigger.isError ? <p className="ma-err" role="alert">비상 정지 발동 실패. <span data-server>{trigger.error.message}</span></p> : null}
        <div className="ma-confirm-act tx-confirm-act">
          <button type="button" className="tx-btn ma-btn-danger ma-kill-go" disabled={reason.trim().length < MIN_REASON || trigger.isPending}
                  onClick={() => trigger.mutate()}>{trigger.isPending ? "설정 중" : "비상 정지 걸기"}</button>
          <button type="button" className="tx-btn tx-btn--sub" onClick={onClose}>닫기</button>
        </div>
      </Sheet>
      <Sheet open={open === "resolve"} onClose={onClose} title="비상 정지 풀기" testId="resolve" className="ma-sheet"
             sub="해제하면 이 계좌의 신규 주문 접수를 재개합니다.">
        <label className="ma-field">
          <span className="ma-label">메모(선택 사항)</span>
          <textarea className="ma-input ma-textarea" name="ma-kill-notes" rows={2} maxLength={500}
                    value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {resolve.isError ? <p className="ma-err" role="alert">비상 정지를 해제하지 못했습니다. <span data-server>{resolve.error.message}</span></p> : null}
        <div className="ma-confirm-act tx-confirm-act">
          <button type="button" className="tx-btn tx-btn--main ma-kill-resolve" disabled={resolve.isPending}
                  onClick={() => resolve.mutate()}>{resolve.isPending ? "해제 중" : "다시 열기"}</button>
          <button type="button" className="tx-btn tx-btn--sub" onClick={onClose}>닫기</button>
        </div>
      </Sheet>
    </>
  );
}
