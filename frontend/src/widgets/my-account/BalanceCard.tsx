"use client";
/**
 * 잔고 (BV9) — `GET /broker-accounts/{id}/balance`.
 * ★미상 ≠ 0★ 서버가 주지 않은 칸은 "몰라요" + 사유. ★연습용이면 그렇다고 말한다★(`practice` = 서버 mock 게이트).
 * 서버에 닿지 못한 실패(다시 시도)와 증권사가 거절한 잔고(사유 + 원래 사유)를 가른다. 손익만 등락색 + 부호.
 */
import type { UseQueryResult } from "@tanstack/react-query";
import type { Balance, Position } from "@/entities/broker-account";
import { direction, num, pct, priceWon, signedPct } from "@/shared/lib/krFormat";
import { RetryFail, Unknown } from "@/shared/ui/tx";
import { useNames, when } from "./parts";

const money = (v: number | null, why: string) => (v === null || v === undefined ? <Unknown reason={why} /> : priceWon(v));

export function BalanceCard({ q }: { q: UseQueryResult<Balance> }) {
  const b = q.data;
  const positions = b?.state === "ok" ? b.positions : [];
  const names = useNames(positions.map((p) => p.ticker));
  return (
    <section className="tx-sec ma-bal" aria-labelledby="ma-bal-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="ma-bal-h">잔고</h2>
          {b ? <p className="tx-sec-sub">기준 {when(b.as_of) ?? "시각 몰라요"}</p> : null}
        </div>
        <div className="tx-sec-aside">
          {b?.practice ? <span className="tx-chip ma-bal-practice" data-tone="practice">연습용 잔고예요</span> : null}
          <button type="button" className="tx-btn tx-btn--sub ma-sm" onClick={() => void q.refetch()} disabled={q.isFetching}>새로 고침</button>
        </div>
      </header>
      <div className="tx-sec-body">
        {q.isError ? (
          <RetryFail title="잔고를 불러오지 못했어요" onRetry={() => void q.refetch()}>{q.error.message}</RetryFail>
        ) : !b ? (
          <p className="tx-sec-sub" aria-busy="true">잔고를 불러오는 중이에요.</p>
        ) : b.state === "failed" ? (
          <div className="ma-bal-failed" role="status">
            <p className="ma-strong">잔고를 받지 못했어요.</p>
            <p className="tx-sec-sub" data-server>{b.reason}</p>
            {b.detail ? (
              <details className="ma-raw"><summary>원래 사유 보기</summary><code data-server>{b.detail}</code></details>
            ) : null}
          </div>
        ) : (
          <>
            <dl className="ma-bal-figs">
              <div><dt>예수금</dt><dd className="ma-bal-cash">{money(b.cash_krw, "서버가 예수금을 주지 않았어요")}</dd></div>
              <div><dt>평가 자산</dt><dd className="ma-bal-total">{money(b.evaluated_total, "서버가 평가 자산을 주지 않았어요")}</dd></div>
            </dl>
            <AssetMix cash={b.cash_krw} positions={positions} label={(t) => names.known(t) ?? t} />
            {positions.length === 0 ? (
              <p className="tx-sec-sub">보유 종목이 없어요.</p>
            ) : (
              <ul className="ma-pos-l" aria-label="보유 종목">
                {positions.map((p) => {
                  const name = names.known(p.ticker);
                  const pnl = p.pnl_pct === null || p.pnl_pct === undefined ? null : p.pnl_pct / 100;
                  return (
                    <li key={p.ticker} className="ma-pos" data-ticker={p.ticker}>
                      <span className="ma-pos-n">
                        <strong>{name ?? p.ticker}</strong>
                        {name ? <span className="ma-code" data-mono>{p.ticker}</span> : null}
                      </span>
                      <span className="ma-pos-q">{p.quantity === null ? "수량 몰라요" : `${num(p.quantity)}주`}</span>
                      <span className="ma-pos-p">평균 {priceWon(p.avg_price)} · 지금 {priceWon(p.current_price)}</span>
                      <span className="tx-delta ma-pos-pnl" data-dir={direction(pnl)}>
                        {pnl === null ? "손익 몰라요" : signedPct(pnl)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            {names.failed ? <p className="tx-sec-sub">종목 이름을 확인하지 못해 코드로 보여요.</p> : null}
          </>
        )}
      </div>
    </section>
  );
}

/** 색 단계 — 예수금은 회색, 종목은 강조색(파랑) 하나의 진하기로만(판단 색을 쓰지 않는다). 여섯째부터는 같은 단계. */
const MIX_STEPS = 6;

/**
 * 자산 구성 막대 — 예수금과 종목별 평가액(서버 값)을 한 줄에 나눠 보인다. 그림은 서버 숫자의 비율일 뿐 새 판단이 아니다.
 * ★모르는 값이 하나라도 있으면 그리지 않고 그렇다고 말한다★(0 으로 메워 비율을 지어내지 않는다).
 */
function AssetMix({ cash, positions, label }: {
  cash: number | null; positions: Position[]; label: (ticker: string) => string;
}) {
  // 평가액이 정확히 0 인 줄(다 판 종목 — 연습용 체결기가 남긴다)은 칸을 그리지 않는다. 0 은 아는 값이라 '모름'과 다르다.
  const held = positions.filter((p) => p.eval_amount !== 0);
  const parts = [{ key: "cash", name: "예수금", v: cash }, ...held.map((p) => ({ key: p.ticker, name: label(p.ticker), v: p.eval_amount }))];
  if (parts.some((p) => p.v === null || p.v === undefined || p.v < 0)) {
    return <p className="tx-sec-sub ma-mix-none">자산 구성은 그리지 않았어요. 서버가 모르는 값을 줬어요.</p>;
  }
  const total = parts.reduce((s, p) => s + (p.v as number), 0);
  if (!(total > 0)) return null;
  const share = (v: number) => v / total;
  const step = (i: number) => String(Math.min(i, MIX_STEPS));
  return (
    <div className="ma-mix">
      <div className="ma-mix-bar" role="img"
           aria-label={`자산 구성: ${parts.map((p) => `${p.name} ${pct(share(p.v as number))}`).join(", ")}`}>
        {parts.map((p, i) => (
          <span key={p.key} className="ma-mix-seg" data-key={p.key} data-step={step(i)}
                style={{ width: `${(share(p.v as number) * 100).toFixed(3)}%` }} />
        ))}
      </div>
      <ul className="ma-mix-l">
        {parts.map((p, i) => (
          <li key={p.key} data-key={p.key}>
            <span className="ma-mix-key" data-step={step(i)} aria-hidden />
            <span className="ma-mix-n">{p.name}</span>
            <span className="ma-mix-v">{pct(share(p.v as number))}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
