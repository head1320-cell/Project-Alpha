"use client";
/**
 * 최근 주문 (BV9) — `GET /broker-accounts/{id}/orders`. 줄마다 서버 상태(번역)와 '멈춘 곳'(주문이 가는 길과 같은 함수).
 * 모르는 상태는 원문 그대로. 취소는 서버가 취소를 받는 상태(대기·보냄·일부 체결)에만, 확인 줄을 거쳐서.
 */
import { useState } from "react";
import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  MODE_KO, STATUS_KO, STOPS, cancelAccountOrder, stopOf, type CancelReply, type OrderRow,
} from "@/entities/broker-account";
import { num, priceWon } from "@/shared/lib/krFormat";
import { RetryFail } from "@/shared/ui/tx";
import { useNames, when } from "./parts";

const CANCELLABLE = new Set(["PENDING", "SUBMITTED", "PARTIAL_FILL"]);

/** 거르기 — 서버 상태를 무리로 나눌 뿐(새 판단 없음). 대기·모르는 상태는 '전체'에만 있다. */
type Filter = "all" | "sent" | "stopped" | "shadow";
const FILTERS: { key: Filter; label: string; has: (status: string) => boolean }[] = [
  { key: "all", label: "전체", has: () => true },
  { key: "sent", label: "보냄", has: (st) => ["SUBMITTED", "PARTIAL_FILL", "FILLED", "CANCELLED"].includes(st) },
  { key: "stopped", label: "멈춤", has: (st) => st === "REJECTED" || st === "FAILED" },
  { key: "shadow", label: "기록만", has: (st) => st === "SHADOW_LOGGED" },
];

function cancelSaid(r: CancelReply): { text: string; raw?: string } {
  if (r.status === "cancelled") return { text: "주문을 취소했어요." };
  if (r.status === "not_cancellable") {
    const cur = r.current ? STATUS_KO[r.current] ?? r.current : "다른";
    return { text: `이미 ‘${cur}’ 상태라 취소할 수 없어요.` };
  }
  if (r.status === "cancel_failed") return { text: "증권사가 취소를 받지 않았어요.", raw: r.error };
  return { text: "서버가 알 수 없는 답을 했어요.", raw: r.status };
}

export function OrderList({ accountId, q }: { accountId: string; q: UseQueryResult<{ count: number; orders: OrderRow[] }> }) {
  const qc = useQueryClient();
  const [asking, setAsking] = useState<string | null>(null);
  const [said, setSaid] = useState<{ text: string; raw?: string; fail?: boolean } | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const all = q.data?.orders ?? [];
  const rows = all.filter((o) => FILTERS.find((f) => f.key === filter)!.has(o.status));
  const names = useNames(all.map((o) => o.ticker));
  const cancel = useMutation({
    mutationFn: async (coid: string) => {
      const r = await cancelAccountOrder(accountId, coid);
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (r) => { setAsking(null); setSaid(cancelSaid(r)); void qc.invalidateQueries({ queryKey: ["acct", accountId] }); },
    onError: (e: Error) => { setAsking(null); setSaid({ text: "취소하지 못했어요.", raw: e.message, fail: true }); },
  });

  return (
    <section className="tx-sec ma-orders" aria-labelledby="ma-orders-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="ma-orders-h">최근 주문</h2>
          <p className="tx-sec-sub">이 계좌로 낸 주문이에요. 줄마다 어디서 멈췄는지 보여요.</p>
        </div>
        <div className="tx-sec-aside">
          <button type="button" className="tx-btn tx-btn--sub ma-sm" onClick={() => void q.refetch()} disabled={q.isFetching}>새로 고침</button>
        </div>
      </header>
      <div className="tx-sec-body">
        {said ? (
          <p className={`ma-ord-msg${said.fail ? " ma-err" : ""}`} role={said.fail ? "alert" : "status"}>
            {said.text}{said.raw ? <> <span data-server>{said.raw}</span></> : null}
          </p>
        ) : null}
        {q.isError ? (
          <RetryFail title="주문 목록을 불러오지 못했어요" onRetry={() => void q.refetch()}>{q.error.message}</RetryFail>
        ) : !q.data ? (
          <p className="tx-sec-sub" aria-busy="true">주문 목록을 불러오는 중이에요.</p>
        ) : all.length === 0 ? (
          <p className="tx-sec-sub">아직 낸 주문이 없어요.</p>
        ) : (
          <>
          <div className="ma-chips ma-ord-filter" role="group" aria-label="주문 거르기">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" className="ma-chip-b" data-f={f.key} aria-pressed={filter === f.key}
                      onClick={() => setFilter(f.key)}>
                {f.label} <span className="ma-chip-n">{all.filter((o) => f.has(o.status)).length}</span>
              </button>
            ))}
          </div>
          {rows.length === 0 ? <p className="tx-sec-sub ma-ord-none">이 무리에 든 주문이 없어요.</p> : (
          <ul className="ma-ord-l">
            {rows.map((o) => {
              const stop = stopOf(o.status, o.reason_code);
              const name = names.known(o.ticker);
              const status = STATUS_KO[o.status];
              return (
                <li key={o.client_order_id} className="ma-ord" data-coid={o.client_order_id}>
                  <span className="ma-ord-when">{when(o.created_at) ?? "시각 몰라요"}</span>
                  <span className="ma-ord-what">
                    <strong>{name ?? o.ticker}</strong>
                    {name ? <span className="ma-code" data-mono>{o.ticker}</span> : null}
                    <span className="ma-ord-side">{o.side === "BUY" ? "사기" : o.side === "SELL" ? "팔기" : <span data-server>{o.side}</span>}</span>
                    <span>{o.quantity === null ? "수량 몰라요" : `${num(o.quantity)}주`}</span>
                    <span>{priceWon(o.price)}</span>
                  </span>
                  <span className="ma-ord-state">
                    <span className="ma-ord-status">{status ?? <span data-server>{o.status}</span>}</span>
                    <span className="tx-chip ma-ord-stop" data-tone="plain" data-stop={stop}>
                      {stop === "unknown" ? "멈춘 곳 몰라요" : stop === "broker" ? "끝까지 갔어요" : `${STOPS.find((s) => s.key === stop)?.label}에서 멈춤`}
                    </span>
                    {o.execution_mode ? <span className="ma-ord-mode">{MODE_KO[o.execution_mode] ?? <span data-server>{o.execution_mode}</span>}</span> : null}
                  </span>
                  {o.error_message ? <span className="ma-ord-why" data-server>{o.error_message}</span> : null}
                  {CANCELLABLE.has(o.status) ? (
                    asking === o.client_order_id ? (
                      <span className="ma-confirm ma-ord-confirm" role="group" aria-label="주문 취소 확인">
                        <span>이 주문을 취소할까요?</span>
                        <button type="button" className="tx-btn tx-btn--main ma-sm ma-ord-cancel-yes" disabled={cancel.isPending}
                                onClick={() => cancel.mutate(o.client_order_id)}>취소하기</button>
                        <button type="button" className="tx-btn tx-btn--sub ma-sm ma-ord-cancel-no" onClick={() => setAsking(null)}>그대로 두기</button>
                      </span>
                    ) : (
                      <button type="button" className="tx-btn tx-btn--sub ma-sm ma-ord-cancel"
                              onClick={() => { setSaid(null); setAsking(o.client_order_id); }}>주문 취소</button>
                    )
                  ) : null}
                </li>
              );
            })}
          </ul>
          )}
          </>
        )}
      </div>
    </section>
  );
}
