/**
 * 비용 분해 — 일봉 백테스트가 ★무엇을 부과했고 무엇을 못 쟀나★ (S1 · 2026-11-19)
 * ==========================================================================
 * 서버 `cost_model` 블록(엔진 `_cost_model_block`)을 그대로 보인다. 결과 화면(`widgets/backtester/BacktestResults`)과
 * 캔버스 '백테스트 결과 조회' 판(`widgets/portfolio-graph/BacktestResults`)이 같은 부품을 쓴다.
 *
 * ★모든 숫자와 사유는 서버 값이다★ — 이 파일은 고르고 서식만 입힌다(강조 표시 ★ · ** · ` 만 걷는다).
 * ★미상 ≠ 0★ — 끈 성분 · 미상 성분의 금액은 0 원이 아니라 N/A 이고, 미상인데 일부를 부과했으면 금액 뒤에 '일부'.
 * 실행 단위 블록의 `total_bps` · 성분 `bps` 는 늘 0 이라 쓰지 않는다. 미상 성분은 세지 않고 이름으로 적는다
 * (2026-11-19 전에 저장된 실행의 `n_unmeasurable` 은 늘 0 이었다).
 */
import type { CostModelBlock, CostPart, CostState, SellTaxBlock } from "@/entities/backtest/bridgeModel";
import { UNKNOWN_TEXT, num } from "@/shared/lib/krFormat";

const PARTS: CostPart[] = ["commission", "slippage", "tax", "spread", "impact"];
const PART_KO: Record<CostPart, string> = { commission: "수수료", slippage: "슬리피지", tax: "매도세", spread: "호가 스프레드", impact: "시장충격" };
const STATE_KO: Record<CostState, string> = { charged: "부과", off: "끔", unmeasurable: "미상", unsupported: "엔진에 없음" };

/** 서버 문장의 강조 표시를 걷는다 — 글자는 그대로. */
const plain = (s: string) => s.replace(/\*\*|★|`/g, "");
const wonText = (v: number) => `${num(v)}원`;
const pctOfBp = (bp: number) => `${(bp / 100).toFixed(2)}%`;

function amountText(state: CostState, krw: number): string {
  if (state === "charged") return wonText(krw);
  if (state === "unmeasurable" && krw > 0) return `${wonText(krw)} · 일부`;
  return UNKNOWN_TEXT;
}

function SellTax({ st }: { st: SellTaxBlock }) {
  return (
    <div className="cbd-tax">
      <p className="cbd-tax-h">매도세 · 거래일별 세율 <span className="cbd-tax-label">{st.label}</span></p>
      <p className="cbd-tax-n">매도 {num(st.n_sells)}건 · 부과 {num(st.n_charged)}건 · 미상 {num(st.n_unmeasured)}건</p>
      {st.rates_bp.length > 0 && (
        <ul className="cbd-rates" aria-label="세율별 매도 수">
          {st.rates_bp.map((r) => <li key={r.bp} className="cbd-rate">{pctOfBp(r.bp)} {num(r.n)}건</li>)}
        </ul>
      )}
      {st.unmeasured.length > 0 && (
        <ul className="cbd-unms" aria-label="미상 사유별 매도 수">
          {st.unmeasured.map((u) => (
            <li key={u.code} className="cbd-unm" data-code={u.code}><span data-server>{plain(u.message)}</span> <b className="cbd-unm-n">{num(u.n)}건</b></li>
          ))}
        </ul>
      )}
      {st.grades.length > 0 && <p className="tj-note cbd-grades">세율표 근거 등급 {st.grades.join(" · ")}</p>}
      <p className="tj-note cbd-tax-note" data-server>{plain(st.note)}</p>
      <p className="tj-note cbd-tax-rt" data-server>{plain(st.round_trip_note)}</p>
    </div>
  );
}

/** `block` 이 없으면(그 기능 전의 실행) 없다고 말한다 — 0 원 표를 그리지 않는다. */
export function CostBreakdown({ block }: { block: CostModelBlock | null | undefined }) {
  if (!block || typeof block !== "object" || !block.components) {
    return <p className="tj-note cbd-none">이 실행의 결과에는 비용 분해가 없습니다. 어떤 비용을 부과했는지 이 화면은 알 수 없습니다.</p>;
  }
  const rows = PARTS.map((p) => ({ p, c: block.components[p] }));
  const unmeasured = rows.filter((r) => r.c?.state === "unmeasurable").map((r) => PART_KO[r.p]);
  const why = rows.filter((r) => r.c?.reason);
  return (
    <div className="cbd">
      <p className="cbd-sum">
        <span>부과한 비용 합계 <b className="cbd-total">{wonText(block.total_krw)}</b></span>
        {unmeasured.length > 0 && <span className="cbd-unmeasured">재지 못한 성분 · {unmeasured.join(" · ")}</span>}
        {block.n_unmeasured_trades > 0 && <span className="cbd-ntrades">일부 비용을 재지 못한 거래 {num(block.n_unmeasured_trades)}건</span>}
      </p>
      <div className="tj-scroll-x">
        <table className="tj-table cbd-table">
          <thead><tr><th scope="col">성분</th><th scope="col">상태</th><th scope="col" className="tj-num">부과한 금액</th></tr></thead>
          <tbody>
            {rows.map(({ p, c }) => c ? (
              <tr key={p} data-part={p} data-state={c.state}>
                <th scope="row">{PART_KO[p]}</th>
                <td><span className="cbd-state" data-state={c.state}>{STATE_KO[c.state] ?? c.state}</span></td>
                <td className="tj-num cbd-krw">{amountText(c.state, c.krw)}</td>
              </tr>
            ) : (
              <tr key={p} data-part={p} data-state="missing">
                <th scope="row">{PART_KO[p]}</th>
                <td><span className="cbd-state" data-state="unmeasurable">미상</span></td>
                <td className="tj-num cbd-krw">{UNKNOWN_TEXT}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {why.length > 0 && (
        <ul className="tj-plain-list cbd-why" aria-label="성분별 사유">
          {why.map(({ p, c }) => <li key={p} data-part={p}><b>{PART_KO[p]}</b> <span data-server>{plain(c!.reason!)}</span></li>)}
        </ul>
      )}
      {block.sell_tax && <SellTax st={block.sell_tax} />}
      <p className="tj-note cbd-ver">비용 설정 판본 <code>{block.version}</code> · 같은 판본이면 같은 비용 설정으로 돌린 실행입니다.</p>
    </div>
  );
}
