"use client";
/**
 * 운영 계좌 보유 종목 (BU9b) — `GET /api/v1/live/balance` 의 `positions`(증권사 잔고 그대로).
 * ★미상 ≠ 0★ 빠진 칸은 "몰라요". 이름은 서버가 준 이름, 없으면 종목 코드(지어내지 않는다). 손익만 등락색 + 부호.
 * 로그인이 필요하면(401) 그렇다고 말하고, 그 밖 실패는 서버 사유 + 다시 시도.
 */
import type { OpBalance } from "@/entities/trading/operator";
import type { Result } from "@/shared/api/result";
import { direction, num, priceWon, signedPct } from "@/shared/lib/krFormat";
import { RetryFail } from "@/shared/ui/tx";

export function Holdings({ result, onRetry }: { result: Result<OpBalance> | null; onRetry: () => void }) {
  const positions = result?.ok ? result.value.positions ?? null : null;
  return (
    <section className="tx-sec lv-hold" aria-labelledby="lv-hold-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="lv-hold-h">보유 종목</h2>
          <p className="tx-sec-sub">증권사 잔고 그대로예요. 10초마다 함께 새로 읽어요.</p>
        </div>
      </header>
      <div className="tx-sec-body">
        {!result ? (
          <p className="tx-sec-sub" aria-busy="true">잔고를 불러오는 중이에요.</p>
        ) : !result.ok ? (
          result.status === 401 ? <p className="tx-sec-sub">로그인해야 잔고를 볼 수 있어요.</p>
            : <RetryFail title="잔고를 불러오지 못했어요" onRetry={onRetry}>{result.error}</RetryFail>
        ) : positions === null ? (
          <p className="tx-sec-sub">서버가 보유 종목 목록을 주지 않았어요.</p>
        ) : positions.length === 0 ? (
          <p className="tx-sec-sub">보유 종목이 없어요.</p>
        ) : (
          <ul className="lv-pos-l" aria-label="보유 종목">
            {positions.map((p) => {
              const pnl = typeof p.pnl_pct === "number" ? p.pnl_pct / 100 : null;
              return (
                <li key={p.ticker} className="lv-pos" data-ticker={p.ticker}>
                  <span className="lv-pos-n">
                    <strong>{p.name || p.ticker}</strong>
                    {p.name ? <span className="lv-code" data-mono>{p.ticker}</span> : null}
                  </span>
                  <span className="lv-pos-q">{typeof p.quantity === "number" ? `${num(p.quantity)}주` : "수량 몰라요"}</span>
                  <span className="lv-pos-p">평균 {priceWon(p.avg_price)} · 지금 {priceWon(p.current_price)} · 평가 {priceWon(p.eval_amount)}</span>
                  <span className="tx-delta lv-pos-pnl" data-dir={direction(pnl)}>
                    {pnl === null ? "손익 몰라요" : signedPct(pnl)}
                    {typeof p.pnl_krw === "number" ? <span className="lv-pos-krw"> {p.pnl_krw > 0 ? "+" : ""}{priceWon(p.pnl_krw)}</span> : null}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
