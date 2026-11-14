"use client";
/**
 * 분봉 백테스트 ⑤ 결과 — 매매일지 결과와 ★같은 부품·같은 순서★(`features/journal-result`) + 이 화면에만 있는 것
 * ==========================================================================
 * 서버가 모의 체결을 만들어 매매일지 엔진으로 계산한다 — 그래서 승률·손익비·비용의 정의가 실거래 분석과 한 벌이다.
 * 이 화면에만 있는 것: 쓰인 분봉의 출처와 건너뛴 것 · 손익분기 비용 · 체결 가정에서 센 것 · 시행 횟수.
 * ★모든 숫자는 서버 값이다★ — 여기서는 고르고 서식만 입힌다. 미상은 N/A + 서버 사유. 권고·예측 문장을 만들지 않는다.
 */
import type { Origin, Simulation, Trial } from "@/entities/intraday";
import type { Journal } from "@/entities/trade-journal";
import {
  AfterLoss, Basis, Buckets, Costs, Extremes, PNL_KO, PnlCurve, SummaryTable, Trades, costChips, ratio2, signedWon,
} from "@/features/journal-result";
import { UNKNOWN_TEXT, num, pct } from "@/shared/lib/krFormat";
import { Answer, Notice, Section, type Chip } from "@/shared/ui/tx";

export const bp1 = (v: number | null | undefined): string => (typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(1)}bp` : UNKNOWN_TEXT);

/** 출처 등급 → 칩. 합성은 연습용 데이터, 미상은 미상, 실제 응답은 사실 표기. */
export const originChip = (o: Origin | null): Chip =>
  o?.grade === "E0" ? { label: "합성 분봉", tone: "practice" } : o?.grade === "E3" ? { label: "실제 분봉", tone: "plain" } : { label: "분봉 출처 미상", tone: "unknown" };

const BREAKEVEN_WHY: Record<string, string> = {
  loses_before_costs: "비용 전에도 손실이라 산출하지 않았습니다.",
  no_trades: "청산된 거래가 없어 산출하지 않았습니다.",
};

export function TrialLine({ trial }: { trial: Trial | null }) {
  if (!trial) return null;
  if (trial.family_n === null) {
    return <p className="tj-note itd-trial" data-recorded="false" data-server>{trial.message ?? "시행 횟수를 세지 못했습니다."}</p>;
  }
  return (
    <p className="tj-note itd-trial" data-recorded="true">
      이 종목과 기간에서 기록된 시행 {num(trial.family_n)}회 · 전체 {num(trial.user_total)}회
      {trial.new === false ? ` · 같은 설정을 ${num(trial.runs)}번째 실행(새 시행이 아님)` : ""}
      . 설정을 바꿔 다시 볼수록 좋아 보이는 결과가 우연히 나올 여지가 커집니다.
    </p>
  );
}

export type Sim = Simulation<Journal>;

export function IntradayResult({ sim }: { sim: Sim }) {
  const j = sim.journal;
  const d = sim.data;
  const slippage = sim.request.costs.slippage_ticks;
  if (sim.empty || !j) {
    return (
      <div className="tj-result itd-result" data-empty={sim.empty?.reason ?? "no_journal"}>
        <Notice tone="warn" title="결과 없음"><span data-server>{sim.empty?.message ?? "계산한 결과가 없습니다."}</span></Notice>
        {d.skipped_total > 0 ? <Used sim={sim} /> : null}
      </div>
    );
  }
  const basis = j.basis.pnl_basis;
  const closed = j.summary.gross.n;
  const head = basis === "net" && j.summary.net ? j.summary.net : j.summary.gross;
  const b = sim.breakeven;
  const chips: Chip[] = [originChip(sim.origin), ...costChips(j), { label: `슬리피지 가정 ${String(slippage)}틱`, tone: "assumed" }];
  return (
    <div className="tj-result itd-result">
      <p className="tx-sr" role="status">실행 완료: 청산된 모의 거래 {num(closed)}건</p>
      <Answer sentence={closed === 0 ? "청산된 모의 거래 없음" : `모의 거래 ${num(closed)}건의 ${PNL_KO[basis]} 실현손익 ${signedWon(head.total)}`}
              figures={closed === 0 ? [] : [
                { label: "승률", value: pct(head.win_rate) },
                { label: "손익비", value: ratio2(head.payoff) },
                { label: "거래당 기대값", value: signedWon(head.expectancy) },
                { label: "손익분기 비용(편도)", value: bp1(b?.bp) },
              ]}
              chips={chips} />
      <Used sim={sim} />
      {closed === 0 ? (
        <Notice tone="warn" title="이 기간에 규칙이 만든 거래가 없습니다.">진입 조건이 한 번도 충족되지 않았거나, 충족된 진입이 아래 ‘체결 가정에서 센 것’의 사유로 막혔습니다.</Notice>
      ) : (
        <>
          <SummaryTable j={j} />
          <Section title="누적 실현손익" sub="청산 순서대로 쌓은 실현손익과 고점 대비 하락(원)입니다. 진입 금액이 고정이라 수익률(%)과 MDD(%)는 산출하지 않습니다.">
            <PnlCurve points={j.curve.points} trades={j.trades} basis={j.curve.basis} maxDrawdown={j.curve.max_drawdown} maxDrawdownAt={j.curve.max_drawdown_at} />
          </Section>
          <Costs j={j} />
          <Section title="손익분기 비용" sub="비용 전 총손익을 총 거래 대금으로 나눈 값입니다. 편도 비용이 이만큼이면 손익이 0 이 됩니다.">
            <dl className="tj-cost-figs itd-breakeven">
              <div data-k="breakeven"><dt>버틸 수 있는 편도 비용</dt><dd>{bp1(b?.bp)}</dd></div>
              <div data-k="spent"><dt>실제로 든 편도 비용</dt><dd>{bp1(b?.spent_bp)}</dd></div>
            </dl>
            {b?.reason ? <p className="tj-note itd-breakeven-why">{BREAKEVEN_WHY[b.reason] ?? "산출하지 않았습니다."}</p> : null}
            {b && b.bp !== null && b.spent_bp === null ? <p className="tj-note">수수료율이나 매도세를 알 수 없어 실제로 든 비용은 산출하지 않았습니다.</p> : null}
          </Section>
          <Buckets j={j} />
          <AfterLoss j={j} />
          <Extremes j={j} />
          <Trades j={j} />
        </>
      )}
      <Section title="체결 가정에서 센 것" sub="규칙이 아니라 체결 가정 때문에 달라진 일의 횟수입니다. 가정을 바꾸면 결과가 달라집니다.">
        {sim.assumptions.length ? (
          <ul className="tj-plain-list itd-assumptions">
            {sim.assumptions.map((a) => <li key={a.key} data-key={a.key}><b>{num(a.count)}회</b> <span data-server>{a.label}</span></li>)}
          </ul>
        ) : <p className="tj-note">센 것 없음</p>}
        <TrialLine trial={sim.trial} />
      </Section>
      <Basis j={j} sub="이 결과는 과거 분봉 위에서 규칙을 돌려 만든 모의 체결을 집계한 것입니다. 향후 성과를 뜻하지 않습니다." />
      <Section title="분봉만으로는 알 수 없는 것" sub="아래 사정은 분봉에 표시가 없어 계산에 반영하지 못했습니다.">
        <ul className="tj-plain-list itd-unknowns">
          {sim.unknowns.map((u) => <li key={u.what}><b data-server>{u.label}</b> <span data-server>{u.reason}</span></li>)}
        </ul>
      </Section>
    </div>
  );
}

/** 쓰인 분봉 — 출처 · 거래일 · 종목×일 · 봉 · 건너뛴 것(사유별). */
function Used({ sim }: { sim: Sim }) {
  const d = sim.data;
  const reasons = new Map<string, string>();
  for (const s of d.skipped) if (!reasons.has(s.reason)) reasons.set(s.reason, s.message ?? s.reason);
  return (
    <Section title="쓰인 분봉" sub="규칙을 돌린 분봉의 범위와 출처, 사유와 함께 건너뛴 종목·일자입니다. 결함이 있는 봉은 고치지 않고 건너뜁니다.">
      <div className="itd-used">
        <p className="tj-read itd-used-read">
          거래일 {num(d.days)}일 · 종목×일 {num(d.sessions)}건 · 봉 {num(d.bars)}개 · 건너뛴 종목×일 {num(d.skipped_total)}건
          {d.shifted_days.length ? ` · 장 운영 시간이 달라 제외한 날 ${num(d.shifted_days.length)}일` : ""}
        </p>
        {sim.origin ? <p className="tj-note itd-origin" data-grade={sim.origin.grade ?? "unknown"} data-server>{sim.origin.grade_reason}</p> : null}
        {d.skipped_total > 0 ? (
          <ul className="tj-plain-list itd-skipped">
            {Object.entries(d.skipped_by_reason).map(([reason, count]) => (
              <li key={reason} data-reason={reason}><b>{num(count)}건</b> <span data-server>{reasons.get(reason) ?? reason}</span></li>
            ))}
          </ul>
        ) : null}
      </div>
    </Section>
  );
}
