"use client";
/**
 * 운영 계좌 최근 주문 20건 (BU9b) — `GET /api/v1/live/orders?limit=20`.
 * 줄마다 서버 상태(번역 — 모르면 원문)와 '멈춘 곳'(/내 계좌 `stopOf` 와 같은 함수 — 서버 열거값 번역만).
 * 취소 단추는 없다(옛 화면에도 없었다 — 새 요청은 만들지 않는다). 거르기는 서버 상태를 무리로 나눌 뿐이다.
 */
import { useState } from "react";
import { MODE_KO, STATUS_KO, STOPS, stopOf } from "@/entities/broker-account";
import type { OpOrders } from "@/entities/trading/operator";
import type { Result } from "@/shared/api/result";
import { krDateTime, num, priceWon } from "@/shared/lib/krFormat";
import { RetryFail } from "@/shared/ui/tx";

type Filter = "all" | "sent" | "stopped" | "shadow";
const FILTERS: { key: Filter; label: string; has: (status: string) => boolean }[] = [
  { key: "all", label: "전체", has: () => true },
  { key: "sent", label: "보냄", has: (st) => ["SUBMITTED", "PARTIAL_FILL", "FILLED", "CANCELLED"].includes(st) },
  { key: "stopped", label: "멈춤", has: (st) => st === "REJECTED" || st === "FAILED" },
  { key: "shadow", label: "기록만", has: (st) => st === "SHADOW_LOGGED" },
];

export function OperatorOrders({ result, onRetry }: { result: Result<OpOrders> | null; onRetry: () => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const all = result?.ok ? result.value.orders : [];
  const rows = all.filter((o) => FILTERS.find((f) => f.key === filter)!.has(o.status));
  return (
    <section className="tx-sec lv-orders" aria-labelledby="lv-orders-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="lv-orders-h">최근 주문</h2>
          <p className="tx-sec-sub">운영 계좌로 나간 주문을 최근 20건까지 보여요. 모든 모드가 섞여 있고, 줄마다 어디서 멈췄는지 보여요.</p>
        </div>
      </header>
      <div className="tx-sec-body">
        {!result ? (
          <p className="tx-sec-sub" aria-busy="true">주문 목록을 불러오는 중이에요.</p>
        ) : !result.ok ? (
          result.status === 401 ? <p className="tx-sec-sub">로그인해야 주문 목록을 볼 수 있어요.</p>
            : <RetryFail title="주문 목록을 불러오지 못했어요" onRetry={onRetry}>{result.error}</RetryFail>
        ) : all.length === 0 ? (
          <p className="tx-sec-sub">아직 나간 주문이 없어요.</p>
        ) : (
          <>
            <div className="lv-chips lv-ord-filter" role="group" aria-label="주문 거르기">
              {FILTERS.map((f) => (
                <button key={f.key} type="button" className="lv-chip-b" data-f={f.key} aria-pressed={filter === f.key}
                        onClick={() => setFilter(f.key)}>
                  {f.label} <span className="lv-chip-n">{all.filter((o) => f.has(o.status)).length}</span>
                </button>
              ))}
            </div>
            {rows.length === 0 ? <p className="tx-sec-sub lv-ord-none">이 무리에 든 주문이 없어요.</p> : (
              <ul className="lv-ord-l">
                {rows.map((o) => {
                  const stop = stopOf(o.status, o.reason_code);
                  const status = STATUS_KO[o.status];
                  const filled = typeof o.filled_quantity === "number" && typeof o.quantity === "number"
                    ? `체결 ${num(o.filled_quantity)}/${num(o.quantity)}주` : typeof o.quantity === "number" ? `${num(o.quantity)}주` : "수량 몰라요";
                  return (
                    <li key={o.client_order_id} className="lv-ord" data-coid={o.client_order_id} data-status={o.status}>
                      <span className="lv-ord-when">{krDateTime(o.created_at) ?? "시각 몰라요"}</span>
                      <span className="lv-ord-what">
                        <strong data-mono>{o.ticker}</strong>
                        <span className="lv-ord-side">
                          {o.side === "BUY" ? "사기" : o.side === "SELL" ? "팔기" : <span data-server>{o.side}</span>}
                        </span>
                        <span>{filled}</span>
                        {o.price !== undefined ? <span>{priceWon(o.price)}</span> : null}
                        {typeof o.strategy_id === "number" ? <span className="lv-ord-strat">{o.strategy_id === 0 ? "직접 낸 주문" : `전략 ${o.strategy_id}`}</span> : null}
                      </span>
                      <span className="lv-ord-state">
                        <span className="lv-ord-status">{status ?? <span data-server>{o.status}</span>}</span>
                        <span className="tx-chip lv-ord-stop" data-tone="plain" data-stop={stop}>
                          {stop === "unknown" ? "멈춘 곳 몰라요" : stop === "broker" ? "끝까지 갔어요" : `${STOPS.find((s) => s.key === stop)?.label}에서 멈춤`}
                        </span>
                        {o.execution_mode ? <span className="lv-ord-mode">{MODE_KO[o.execution_mode] ?? <span data-server>{o.execution_mode}</span>}</span> : null}
                      </span>
                      {o.error_message || (o.status === "REJECTED" && o.reason_code) ? (
                        <span className="lv-ord-why" data-server>{o.error_message ?? o.reason_code}</span>
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
