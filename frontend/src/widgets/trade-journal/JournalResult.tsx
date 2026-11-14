"use client";
/**
 * 매매일지 결과 — 답 한 문장 → 비용 전·후 요약 → 누적 곡선 → 비용 → 구간별 → 거래 표 → 계산에서 빠진 것 → 값의 근거
 * ==========================================================================
 * ★모든 숫자는 서버 값이다★ — 이 파일은 고르고 서식만 입힌다(다시 계산하지 않는다 · 막대의 길이만 화면이 잰다).
 * ★미상은 N/A + 사유★ — 비용을 모르는 거래의 '비용 후'는 0 이 아니라 N/A 이고, 왜 모르는지 서버 사유를 옆에 적는다.
 * 값마다 근거 표지(관측 · 추론 · 가정 · 미상)가 따라간다. 관측만 한다 — 권고·예측 문장을 만들지 않는다.
 */
import type { Journal } from "@/entities/trade-journal";
import {
  AfterLoss, Basis, Buckets, Costs, Extremes, PNL_KO, PnlCurve, SummaryTable, Trades, amountWon, costChips, qty, ratio2, sign, signedWon,
} from "@/features/journal-result";
import { pct } from "@/shared/lib/krFormat";
import { Answer, Notice, Section, type Chip } from "@/shared/ui/tx";

type Extra = { lines: number[]; skipped: number; padded: number; sample: boolean };

export function JournalResult({ journal: j, extra }: { journal: Journal; extra: Extra }) {
  const basis = j.basis.pnl_basis;
  const closed = j.summary.gross.n;
  const head = basis === "net" && j.summary.net ? j.summary.net : j.summary.gross;
  return (
    <div className="tj-result">
      <p className="tx-sr" role="status">분석 완료: 청산된 거래 {closed.toLocaleString("ko-KR")}건</p>
      <Answer sentence={closed === 0 ? "청산된 거래 없음" : `거래 ${closed.toLocaleString("ko-KR")}건의 ${PNL_KO[basis]} 실현손익 ${signedWon(head.total)}`}
              figures={closed === 0 ? [] : [
                { label: "승률", value: pct(head.win_rate) },
                { label: "손익비", value: ratio2(head.payoff) },
                { label: "거래당 기대값", value: signedWon(head.expectancy) },
                { label: "손익분기 승률", value: pct(head.breakeven_win_rate) },
              ]}
              chips={chipsOf(j, extra.sample)} />
      {closed === 0 ? (
        <Notice tone="warn" title="매수와 매도가 짝을 이룬 거래가 파일에 없습니다.">
          승률·손익비는 청산된 거래로만 산출합니다. 아래 ‘계산에서 빠진 것’에서 미청산 수량과 버린 줄을 확인하십시오.
        </Notice>
      ) : (
        <>
          <SummaryTable j={j} />
          <Section title="누적 실현손익" sub="청산 순서대로 쌓은 실현손익과 고점 대비 하락(원)입니다. 계좌 평가금액을 알 수 없어 수익률(%)과 MDD(%)는 산출하지 않습니다.">
            <PnlCurve points={j.curve.points} trades={j.trades} basis={j.curve.basis} maxDrawdown={j.curve.max_drawdown} maxDrawdownAt={j.curve.max_drawdown_at} />
          </Section>
          <Costs j={j} />
          <Buckets j={j} />
          <AfterLoss j={j} />
          <Extremes j={j} />
          <Trades j={j} />
        </>
      )}
      <Excluded j={j} extra={extra} />
      <Basis j={j} />
    </div>
  );
}

// ── 근거 칩 ─────────────────────────────────────────────────────────────────

const chipsOf = (j: Journal, sample: boolean): Chip[] => [...(sample ? [{ label: "예시 파일", tone: "practice" } as Chip] : []), ...costChips(j)];

// ── 계산에서 빠진 것 ────────────────────────────────────────────────────────

function Excluded({ j, extra }: { j: Journal; extra: Extra }) {
  const n = (v: number) => v.toLocaleString("ko-KR");
  const parts = [`입력 ${n(j.inputs.rows)}줄`, `체결 ${n(j.inputs.fills)}건`, `버린 줄 ${n(j.rejects.count)}건`,
                 `매수 없는 매도 ${n(j.unmatched_sells.count)}건`, `미청산 ${n(j.open_positions.length)}종목`,
                 ...(extra.skipped ? [`제외로 지정한 줄 ${n(extra.skipped)}건`] : [])];
  const line = (row: number) => extra.lines[row] ?? null;
  return (
    <Section title="계산에서 빠진 것" sub="통계에 넣지 않은 줄과 그 사유입니다. 조용히 버리지 않습니다.">
      <div className="tj-excluded">
        <p className="tj-read">{parts.join(" · ")}</p>
        {j.rejects.count > 0 ? (
          <div>
            <h3 className="tj-h3">버린 줄</h3>
            <ul className="tj-rejects tj-plain-list">
              {j.rejects.sample.map((r) => (
                <li key={r.row}><b>{line(r.row) === null ? `${r.row + 1}번째 체결 줄` : `파일 ${line(r.row)}번째 줄`}</b> <span data-server>{r.message}</span></li>
              ))}
            </ul>
            {j.rejects.count > j.rejects.sample.length ? <p className="tj-note">전체 {n(j.rejects.count)}건 중 앞 {n(j.rejects.sample.length)}건입니다.</p> : null}
          </div>
        ) : null}
        {j.unmatched_sells.count > 0 ? (
          <div>
            <h3 className="tj-h3">매수 없는 매도</h3>
            <ul className="tj-unmatched tj-plain-list">
              {j.unmatched_sells.sample.map((u) => (
                <li key={u.row}><b data-mono>{u.symbol}</b> {qty(u.quantity)}주{line(u.row) === null ? "" : ` · 파일 ${line(u.row)}번째 줄`} <span data-server>{u.message}</span></li>
              ))}
            </ul>
          </div>
        ) : null}
        {j.open_positions.length > 0 ? (
          <div>
            <h3 className="tj-h3">미청산</h3>
            <p className="tj-note">남은 수량은 평가하지 않습니다(시세를 쓰지 않음). 이미 매도한 몫의 실현손익만 적으며 승률 통계에는 넣지 않습니다.</p>
            <ul className="tj-open tj-plain-list">
              {j.open_positions.map((p) => (
                <li key={`${p.symbol}-${p.opened_at}`}>
                  <b>{p.name ? <>{p.name} <span className="tj-code" data-mono>{p.symbol}</span></> : <span data-mono>{p.symbol}</span>}</b>
                  {" "}남은 수량 {qty(p.open_quantity)}주(매입 금액 {amountWon(p.open_amount)})
                  {p.sold_quantity > 0 ? <> · 매도한 {qty(p.sold_quantity)}주의 실현손익 비용 전 <span data-dir={sign(p.realized_gross)}>{signedWon(p.realized_gross)}</span>, 비용 후 <span data-dir={sign(p.realized_net)}>{signedWon(p.realized_net)}</span></> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {extra.padded > 0 ? <p className="tj-note">숫자로만 된 6자리 미만 종목코드 {n(extra.padded)}줄은 앞자리 0 을 채워 보냈습니다.</p> : null}
      </div>
    </Section>
  );
}
