"use client";
/**
 * 주문 내기 (BV9) — `POST /broker-accounts/{id}/orders`.
 * ==========================================================================
 * ★stock_master 가 이름을 준 코드만 받는다★(모르는 코드·확인 실패면 단추 꺼짐 — 가짜 종목코드를 보내지 않는다).
 * ★사기/팔기는 기본값이 없다★(돈이 걸린 선택). ★가격은 늘 필요하다★ — 서버 위험 검사가 가격을 모르면 거절한다(시장가도 '기준 가격').
 * 모드를 모르거나 비상 정지 중이면 받지 않는다(이유를 보인다). 보내기 전에 확인 줄이 무엇을 어디로 보내는지 말한다.
 * 결과는 '주문이 가는 길'이 그린다(서버가 멈춘 역). 요청 자체가 실패하면 여기 alert — 결과처럼 그리지 않는다.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  MODE_KO, destination, stopOf, submitAccountOrder, type ExecMode, type OrderRequest, type Position,
} from "@/entities/broker-account";
import { num, pct, priceWon } from "@/shared/lib/krFormat";
import { useNames } from "./parts";
import type { Trace } from "./OrderPath";

const CODE = /^\d{6}$/;

const QTY_STEPS = [1, 10, 100];

export function OrderForm({ accountId, mode, killActive, practice, onTrace, holdings, cash }: {
  /** undefined = 아직 불러오는 중 · null = 확인하지 못함(서버 실패). */
  accountId: string; mode: ExecMode | null | undefined; killActive: boolean | null | undefined; practice: boolean | null;
  onTrace: (t: Trace) => void;
  /** 잔고의 보유 종목(서버 값) — '보유에서 고르기'·'보유 전부' 에만 쓴다. 잔고를 못 받았으면 빈 목록. */
  holdings: Position[];
  /** 예수금(서버 값) — 주문 금액이 예수금의 몇 %인지 보일 때만. 모르면 null(비율을 보이지 않는다). */
  cash: number | null;
}) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [side, setSide] = useState<"BUY" | "SELL" | null>(null);
  const [qty, setQty] = useState("");
  const [type, setType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState("");
  const [asking, setAsking] = useState(false);
  const [priceFrom, setPriceFrom] = useState<string | null>(null);
  const codeOk = CODE.test(code);
  const holdingNames = useNames(holdings.map((h) => h.ticker));
  const held = holdings.find((h) => h.ticker === code && (h.quantity ?? 0) > 0) ?? null;
  const names = useNames(codeOk ? [code] : []);
  const name = codeOk ? names.known(code) : null;
  const quantity = /^\d+$/.test(qty) ? Number(qty) : NaN;
  const priceN = Number(price.replace(/,/g, ""));
  const filled = name !== null && side !== null && quantity > 0 && Number.isFinite(priceN) && priceN > 0;
  const blocked = mode === null ? "실행 모드를 확인하지 못해 주문을 받지 않아요."
    : killActive === null ? "비상 정지 상태를 확인하지 못해 주문을 받지 않아요."
    : killActive ? "비상 정지 중이라 주문을 받지 않아요." : null;
  const loading = mode === undefined || killActive === undefined;

  const send = useMutation({
    mutationFn: async (body: OrderRequest) => {
      const r = await submitAccountOrder(accountId, body);
      if (!r.ok) throw new Error(r.error);
      return r.value;
    },
    onSuccess: (reply) => {
      setAsking(false);
      onTrace({ stop: stopOf(reply.status, reply.reason), reply });
      void qc.invalidateQueries({ queryKey: ["acct", accountId] });
    },
    onError: () => setAsking(false),
  });

  const body = (): OrderRequest => ({
    strategy_id: 0, ticker: code, side: side ?? "BUY", quantity, price: priceN, order_type: type, source: "manual",
  });
  const verb = side === "SELL" ? "팔아요" : "사요";
  const what = type === "LIMIT"
    ? `${name}(${code}) ${quantity}주를 지정가 ${priceWon(priceN)}에 ${verb}.`
    : `${name}(${code}) ${quantity}주를 시장가로 ${verb}. 기준 가격은 ${priceWon(priceN)}이에요.`;

  return (
    <form className="tx-sec ma-order" aria-labelledby="ma-order-h" noValidate aria-busy={send.isPending}
          onSubmit={(e) => { e.preventDefault(); if (filled && !blocked && !loading) setAsking(true); }}>
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="ma-order-h">주문 내기</h2>
          <p className="tx-sec-sub">보내기 전에 무엇을 어디로 보내는지 한 번 더 보여 드려요.</p>
        </div>
      </header>
      <div className="tx-sec-body ma-form">
        {holdings.some((h) => (h.quantity ?? 0) > 0) ? (
          <div className="ma-field">
            <span className="ma-label" id="ma-hold-l">보유에서 고르기</span>
            <div className="ma-holds" role="group" aria-labelledby="ma-hold-l">
              {holdings.filter((h) => (h.quantity ?? 0) > 0).map((h) => (
                <button key={h.ticker} type="button" className="ma-hold" data-ticker={h.ticker} aria-pressed={code === h.ticker}
                        onClick={() => {
                          setCode(h.ticker); setAsking(false);
                          if (h.current_price && h.current_price > 0) { setPrice(String(h.current_price)); setPriceFrom("잔고의 지금 값으로 채웠어요. 바꿔도 돼요."); }
                        }}>
                  <span className="ma-hold-n">{holdingNames.known(h.ticker) ?? h.ticker}</span>
                  <span className="ma-hold-q">{num(h.quantity)}주</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <label className="ma-field">
          <span className="ma-label">종목 코드</span>
          <input className="ma-input" name="ma-ticker" inputMode="numeric" maxLength={6} autoComplete="off"
                 value={code} onChange={(e) => { setCode(e.target.value.trim()); setPriceFrom(null); setAsking(false); }} />
          {!codeOk ? <span className="ma-hint">숫자 6자리예요.</span>
            : name ? <span className="ma-ticker-name">{name}</span>
            : names.failed ? <span className="ma-ticker-bad">종목을 확인하지 못했어요. 확인된 종목만 주문해요.</span>
            : names.pending ? <span className="ma-hint">종목을 확인하는 중이에요.</span>
            : <span className="ma-ticker-bad">알 수 없는 종목 코드예요.</span>}
        </label>
        {/* 넓으면 둘씩 나란히(사기/팔기 · 방식 / 수량 · 가격) — 폼을 짧게 해 잔고·최근 주문 옆에 선다 */}
        <div className="ma-pair">
          <div className="ma-field">
            <span className="ma-label" id="ma-side-l">사기 또는 팔기</span>
            <div className="ma-seg ma-side" role="group" aria-labelledby="ma-side-l">
              {([["BUY", "사기"], ["SELL", "팔기"]] as const).map(([k, l]) => (
                <button key={k} type="button" data-side={k} className="ma-seg-b" aria-pressed={side === k}
                        onClick={() => { setSide(k); setAsking(false); }}>{l}</button>
              ))}
            </div>
          </div>
          <div className="ma-field">
            <span className="ma-label" id="ma-type-l">주문 방식</span>
            <div className="ma-seg ma-type" role="group" aria-labelledby="ma-type-l">
              {([["LIMIT", "지정가"], ["MARKET", "시장가"]] as const).map(([k, l]) => (
                <button key={k} type="button" data-type={k} className="ma-seg-b" aria-pressed={type === k}
                        onClick={() => { setType(k); setAsking(false); }}>{l}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="ma-pair">
          <div className="ma-field">
            <label className="ma-label" htmlFor="ma-qty">수량(주)</label>
            <input className="ma-input" id="ma-qty" name="ma-qty" inputMode="numeric" autoComplete="off"
                   value={qty} onChange={(e) => { setQty(e.target.value.trim()); setAsking(false); }} />
            <div className="ma-chips" role="group" aria-label="수량 빠르게 더하기">
              {QTY_STEPS.map((n) => (
                <button key={n} type="button" className="ma-chip-b" data-add={n}
                        onClick={() => { setQty(String((Number.isFinite(quantity) ? quantity : 0) + n)); setAsking(false); }}>+{n}</button>
              ))}
              {held ? (
                <button type="button" className="ma-chip-b ma-qty-all"
                        onClick={() => { setQty(String(held.quantity)); setAsking(false); }}>보유 전부 {num(held.quantity)}주</button>
              ) : null}
            </div>
          </div>
          <label className="ma-field">
            <span className="ma-label">{type === "LIMIT" ? "주문 가격(원)" : "기준 가격(원)"}</span>
            <input className="ma-input" name="ma-price" inputMode="numeric" autoComplete="off"
                   value={price} onChange={(e) => { setPrice(e.target.value.trim()); setPriceFrom(null); setAsking(false); }} />
            {priceFrom ? <span className="ma-hint ma-price-from">{priceFrom}</span> : null}
            {type === "MARKET" ? (
              <span className="ma-hint">시장가도 서버가 거래 한도를 재려면 기준 가격이 필요해요. 이 가격에 체결된다는 뜻은 아니에요.</span>
            ) : null}
          </label>

        </div>
        {quantity > 0 && priceN > 0 ? (
          <p className="ma-amount">
            <span className="ma-amount-k">주문 금액 어림</span>
            <strong className="ma-amount-v">{priceWon(quantity * priceN)}</strong>
            {cash !== null && cash > 0 ? <span className="ma-amount-r">예수금의 {pct((quantity * priceN) / cash)}</span> : null}
            <span className="ma-hint">수수료와 세금은 빠졌어요.</span>
          </p>
        ) : null}
        {blocked ? <p className="ma-order-why">{blocked}</p> : null}
        {asking && mode ? (
          <div className="ma-confirm ma-order-confirm" role="group" aria-label="주문 확인">
            <p>{what} 지금 모드는 {MODE_KO[mode] ?? mode}이라 {destination(mode, practice)}.</p>
            <div className="ma-confirm-act">
              <button type="button" className="tx-btn tx-btn--main ma-order-send" disabled={send.isPending}
                      onClick={() => send.mutate(body())}>{send.isPending ? "보내는 중이에요" : "주문 내기"}</button>
              <button type="button" className="tx-btn tx-btn--sub ma-order-edit" onClick={() => setAsking(false)}>고치기</button>
            </div>
          </div>
        ) : (
          <button type="submit" className="tx-btn tx-btn--main ma-order-check" disabled={!filled || blocked !== null || loading}>주문 확인</button>
        )}
        {send.isError ? (
          <p className="ma-err" role="alert">주문을 보내지 못했어요. <span data-server>{send.error.message}</span></p>
        ) : null}
        {send.isSuccess ? <p className="ma-order-result tx-sec-sub" role="status">서버가 답했어요. 위 ‘주문이 가는 길’에서 어디까지 갔는지 보여요.</p> : null}
      </div>
    </form>
  );
}
