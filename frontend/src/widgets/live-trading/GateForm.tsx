"use client";
/**
 * 실계좌 관문 선언 시트 (BU9b) — 여섯 칸(서버 `AUTH_FIELDS` 순서 = `GATE_FIELDS`)이 다 차야 보낼 수 있다.
 * 본문은 정확히 여섯 키(사용자는 배열). 서버가 거절하면(422) 사유를 그대로 + 사유에 든 칸 이름을 사람 말로 짚는다 — 시트는 닫지 않는다.
 * 모두에게 여는 값(`*`·모두 등)은 화면이 막지 않는다 — 서버가 받지 않고 그 사유를 보인다(판정은 서버 한곳).
 */
import { useState, type KeyboardEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { X } from "lucide-react";
import { GATE_FIELDS, WILDCARD_EXAMPLES, declareLiveGate, type GateField } from "@/entities/trading/liveGate";
import { Sheet } from "@/shared/ui/tx";

export const FIELD_KO: Record<GateField, string> = {
  basis: "근거", authority: "확인한 곳", reference_no: "확인 번호", verified_at: "확인한 날", scope: "범위", allowed_users: "허용할 사용자",
};
const HINT: Record<GateField, string> = {
  basis: "왜 실계좌를 여는지 적어요. 예: 본인 계좌로만 주문하는 개인 운영",
  authority: "근거를 확인한 기관이나 문서예요. 예: 한국투자증권 오픈API 약관",
  reference_no: "그 문서나 확인의 번호예요.",
  verified_at: "근거를 확인한 날이에요.",
  scope: "어디까지 여는지 적어요. 예: 운영 계좌 하나, 국내 주식",
  allowed_users: `이름을 하나씩 더해요. 모두에게 여는 값(예: ${WILDCARD_EXAMPLES.join(", ")})은 서버가 받지 않아요.`,
};
type Text = Exclude<GateField, "allowed_users">;
const EMPTY: Record<Text, string> = { basis: "", authority: "", reference_no: "", verified_at: "", scope: "" };

/** 서버 사유에 든 칸 이름(영문 키)을 사람 말로 — 거절 사유는 그대로 두고 아래에 한 줄 더한다. */
function fieldsIn(reason: string): string[] {
  return GATE_FIELDS.filter((f) => new RegExp(`\\b${f}\\b`).test(reason)).map((f) => FIELD_KO[f]);
}

export function GateForm({ open, hasCurrent, onClose, onDone }: {
  open: boolean; hasCurrent: boolean; onClose: () => void; onDone: (liveDropped: boolean) => void;
}) {
  const [text, setText] = useState(EMPTY);
  const [users, setUsers] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const declare = useMutation({
    mutationFn: async () => {
      const r = await declareLiveGate({ ...text, allowed_users: users });
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (r) => { setText(EMPTY); setUsers([]); setDraft(""); onDone(r.live_dropped_to_shadow); },
  });
  const addUser = () => {
    const u = draft.trim();
    if (!u) return;
    setUsers((xs) => (xs.includes(u) ? xs : [...xs, u]));
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => { if (e.key === "Enter") { e.preventDefault(); addUser(); } };
  const full = (Object.keys(EMPTY) as Text[]).every((k) => text[k].trim() !== "") && users.length > 0;
  const named = declare.isError ? fieldsIn(declare.error.message) : [];

  return (
    <Sheet open={open} onClose={() => { declare.reset(); onClose(); }} title="실계좌 관문 선언하기" testId="gate-declare" className="lv-sheet lvg-sheet"
           sub={hasCurrent ? "새로 선언하면 지금 선언은 거둔 것으로 남아요. 실계좌로 돌던 운영 계좌는 기록만으로 돌아가요."
             : "선언하면 허용한 사용자만 실계좌로 주문할 수 있어요. 무엇을 근거로 여는지 기록에 남아요."}>
      <form className="lvg-form" onSubmit={(e) => { e.preventDefault(); if (full) declare.mutate(); }}>
        {(Object.keys(EMPTY) as Text[]).map((k) => (
          <label key={k} className="lv-field" data-k={k}>
            <span className="lv-label">{FIELD_KO[k]}</span>
            <input className="lv-input" name={`gate-${k}`} type={k === "verified_at" ? "date" : "text"} maxLength={200}
                   value={text[k]} onChange={(e) => setText((t) => ({ ...t, [k]: e.target.value }))} />
            <span className="lv-hint">{HINT[k]}</span>
          </label>
        ))}
        <div className="lv-field" data-k="allowed_users">
          <label className="lv-label" htmlFor="gate-user">{FIELD_KO.allowed_users}</label>
          <div className="lvg-user-row">
            <input id="gate-user" className="lv-input" name="gate-user" maxLength={64} value={draft}
                   onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} />
            <button type="button" className="tx-btn tx-btn--sub lvg-user-add" disabled={!draft.trim()} onClick={addUser}>더하기</button>
          </div>
          {users.length ? (
            <ul className="lvg-users lvg-users--edit" aria-label="허용할 사용자">
              {users.map((u) => (
                <li key={u} className="tx-chip lvg-user" data-tone="plain" data-user={u}>
                  {u}
                  <button type="button" className="lvg-user-x" aria-label={`‘${u}’ 빼기`} onClick={() => setUsers((xs) => xs.filter((x) => x !== u))}>
                    <X size={12} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <span className="lv-hint">{HINT.allowed_users}</span>
        </div>
        {declare.isError ? (
          <div className="lv-err lvg-refused" role="alert">
            <p>선언하지 못했어요. <span data-server>{declare.error.message}</span></p>
            {named.length ? <p className="lvg-refused-k">다시 볼 칸: {named.join(", ")}</p> : null}
          </div>
        ) : null}
        <div className="tx-confirm-act">
          <button type="submit" className="tx-btn tx-btn--main lvg-declare-go" disabled={!full || declare.isPending}>
            {declare.isPending ? "선언하는 중이에요" : "선언하기"}
          </button>
          <button type="button" className="tx-btn tx-btn--sub" onClick={() => { declare.reset(); onClose(); }}>닫기</button>
        </div>
        {!full ? <p className="lv-hint lvg-need">여섯 칸을 모두 채우면 선언할 수 있어요.</p> : null}
      </form>
    </Sheet>
  );
}
