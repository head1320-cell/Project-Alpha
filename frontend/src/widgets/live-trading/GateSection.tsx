"use client";
/**
 * 실계좌 관문 절 (BU9b · 서버 BV7 `/api/v1/admin/live-gate`) — 관리자만.
 * ==========================================================================
 * 운영자가 "무슨 근거로 · 누구에게" 실계좌를 여는지 선언하고 거둔다. 판정은 서버가 한다 — 화면은 서버 사유를 그대로 보인다.
 * 거두기는 확인 시트를 거친다. 지난 선언은 지우지 않고(서버도 지우지 않는다) 최신 먼저 보인다.
 */
import { useState } from "react";
import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Lock, LockOpen } from "lucide-react";
import { revokeLiveGate, type GateRecord, type GateState } from "@/entities/trading/liveGate";
import { krDateTime } from "@/shared/lib/krFormat";
import { RetryFail, Sheet } from "@/shared/ui/tx";
import { FIELD_KO, GateForm } from "./GateForm";

export function GateSection({ gate, onChanged }: { gate: UseQueryResult<GateState>; onChanged: () => void }) {
  const qc = useQueryClient();
  const [sheet, setSheet] = useState<"declare" | "revoke" | null>(null);
  const [said, setSaid] = useState<string | null>(null);
  const settle = (msg: string) => {
    setSheet(null); setSaid(msg);
    void qc.invalidateQueries({ queryKey: ["live", "gate"] });
    onChanged();
  };
  const revoke = useMutation({
    mutationFn: async () => {
      const r = await revokeLiveGate();
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (r) => settle(r.live_dropped_to_shadow
      ? "관문을 거뒀어요. 실계좌로 돌던 운영 계좌를 기록만으로 돌려놨어요." : "관문을 거뒀어요. 실계좌 주문이 다시 닫혔어요."),
  });
  const g = gate.data;
  const cur = g?.current ?? null;

  return (
    <section className="tx-sec lvg" aria-labelledby="lvg-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="lvg-h">실계좌 관문</h2>
          <p className="tx-sec-sub">운영자가 근거와 허용할 사용자를 선언해야 실계좌 주문이 열려요. 운영 계좌도 같은 관문 뒤에 있어요.</p>
        </div>
        {g ? (
          <div className="tx-sec-aside lvg-act">
            {cur ? (
              <button type="button" className="tx-btn tx-btn--sub lvg-revoke-open" onClick={() => { setSaid(null); revoke.reset(); setSheet("revoke"); }}>거두기</button>
            ) : null}
            <button type="button" className={`tx-btn ${cur ? "tx-btn--sub" : "tx-btn--main"} lvg-declare-open`}
                    onClick={() => { setSaid(null); setSheet("declare"); }}>{cur ? "새로 선언하기" : "선언하기"}</button>
          </div>
        ) : null}
      </header>
      <div className="tx-sec-body">
        {said ? <p className="lvg-said" role="status">{said}</p> : null}
        {gate.isError ? (
          <RetryFail title="실계좌 관문 기록을 불러오지 못했어요" onRetry={() => void gate.refetch()}>{gate.error.message}</RetryFail>
        ) : !g ? (
          <p className="tx-sec-sub" aria-busy="true">관문 기록을 불러오는 중이에요.</p>
        ) : (
          <>
            <div className="lvg-now" data-open={cur ? "true" : "false"}>
              {cur ? <LockOpen size={18} aria-hidden /> : <Lock size={18} aria-hidden />}
              <div>
                <p className="lvg-now-t">{cur ? "지금 열려 있어요" : "지금 닫혀 있어요"}</p>
                <p className="tx-sec-sub">
                  {cur ? `${cur.declared_by ?? "누군가"} 님이 ${krDateTime(cur.declared_at) ?? "언제인지 모르는 때"}에 선언했어요. 아래 사용자만 실계좌로 주문할 수 있어요.`
                    : "선언이 없어서 실계좌 주문은 누구에게도 열려 있지 않아요."}
                </p>
              </div>
            </div>
            {cur ? <GateFacts rec={cur} /> : null}
            <GateHistory items={g.history} />
          </>
        )}
      </div>

      <GateForm open={sheet === "declare"} hasCurrent={!!cur} onClose={() => setSheet(null)}
                onDone={(dropped) => settle(dropped ? "선언했어요. 실계좌로 돌던 운영 계좌를 기록만으로 돌려놨어요." : "선언했어요.")} />
      <Sheet open={sheet === "revoke"} onClose={() => setSheet(null)} title="실계좌 관문 거두기" testId="gate-revoke" className="lv-sheet"
             sub="거두면 실계좌 주문이 다시 닫혀요. 실계좌로 돌던 운영 계좌는 기록만으로 돌아가요. 선언 기록은 지우지 않아요.">
        {revoke.isError ? <p className="lv-err" role="alert">관문을 거두지 못했어요. <span data-server>{revoke.error.message}</span></p> : null}
        <div className="tx-confirm-act">
          <button type="button" className="tx-btn lv-btn-danger lvg-revoke-yes" disabled={revoke.isPending}
                  onClick={() => revoke.mutate()}>{revoke.isPending ? "거두는 중이에요" : "거두기"}</button>
          <button type="button" className="tx-btn tx-btn--sub lvg-revoke-no" onClick={() => setSheet(null)}>취소</button>
        </div>
      </Sheet>
    </section>
  );
}

function GateFacts({ rec }: { rec: GateRecord }) {
  return (
    <dl className="lvg-facts">
      {(["basis", "authority", "reference_no", "verified_at", "scope"] as const).map((k) => (
        <div key={k} className="lvg-fact" data-k={k}><dt>{FIELD_KO[k]}</dt><dd data-server>{rec[k]}</dd></div>
      ))}
      <div className="lvg-fact" data-k="allowed_users">
        <dt>{FIELD_KO.allowed_users}</dt>
        <dd><ul className="lvg-users">{rec.allowed_users.map((u) => <li key={u} className="tx-chip" data-tone="plain">{u}</li>)}</ul></dd>
      </div>
    </dl>
  );
}

function GateHistory({ items }: { items: GateRecord[] }) {
  if (!items.length) return <p className="tx-sec-sub lvg-hist-none">지난 선언이 없어요.</p>;
  return (
    <div className="lvg-hist">
      <p className="lvg-hist-h">지난 선언 {items.length}건</p>
      <ol className="lvg-hist-l">
        {items.map((h, i) => (
          <li key={`${h.declared_at}-${i}`} className="lvg-h" data-open={h.revoked_at ? "false" : "true"}>
            <span className="lvg-h-dot" aria-hidden />
            <div className="lvg-h-b">
              <p className="lvg-h-t">
                {krDateTime(h.declared_at) ?? "언제인지 몰라요"} · {h.declared_by ?? "누군가"} 님이 선언
                {h.revoked_at ? <> · {krDateTime(h.revoked_at) ?? "언제인지 모르는 때"}에 {h.revoked_by ?? "누군가"} 님이 거둠</> : <> · <strong>지금 열려 있어요</strong></>}
              </p>
              <details className="lvg-h-more">
                <summary>자세히</summary>
                <GateFacts rec={h} />
              </details>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
