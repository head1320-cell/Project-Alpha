"use client";
/**
 * 시장 국면의 사실 — 국면별 통계 · 같은 자료의 BIC(2 ~ 4 · 고르지 않는다) · 시드 일치도 · 전환 수 · 적합 줄 · 한계 문장 (구현 계획 §7.1 · K1)
 * 숫자는 서버 값을 서식만 한다. 한계 문장은 서버 글자 그대로(`data-server`). 국면에 뜻을 붙인 이름은 없다(번호와 통계만).
 */
import { useId } from "react";
import type { MarketRegimeAnswer } from "@/entities/intraday";
import { num, UNKNOWN_TEXT } from "@/shared/lib/krFormat";
import { bicText, dailyText, probText, stateFill, volText } from "./format";

export function RegimeFacts({ a }: { a: MarketRegimeAnswer }) {
  const valued = a.days.filter((d) => d.top !== null).length;
  const capId = useId();
  return (
    <div className="itd-mr-facts">
      <div className="itd-mr-tablebox">
      <p className="itd-mr-cap" id={capId}>국면별 통계(그날 가장 큰 국면으로 센 날 · 값이 있는 날 {valued.toLocaleString("ko-KR")}일 · 관측이며 결정에 쓰지 않습니다)</p>
      {/* 머리글만 낱말 단위로 줄을 바꿔 390px 에서도 다섯 칸이 다 보인다(값 칸은 쪼개지 않는다) — 더 좁으면 표가 옆으로 넘고, 넘는 상자는 키보드(Tab → ←→)로도 닿는다 */}
      <div className="itd-mr-scroll" role="region" tabIndex={0} aria-labelledby={capId}>
      <table className="pg-table itd-mr-states" aria-labelledby={capId}>
        <thead>
          <tr><th>국면</th><th className="pg-td-num">날 수</th><th className="pg-td-num">비중</th><th className="pg-td-num">일 수익 평균(로그)</th><th className="pg-td-num">실현 변동성(연율)</th></tr>
        </thead>
        <tbody>
          {a.states.map((s) => (
            <tr key={s.state} data-state={s.state}>
              <td><i className="itd-mr-chip" style={{ background: stateFill(s.state, a.k) }} aria-hidden="true" />국면 {s.state}</td>
              <td className="pg-td-num">{s.days.toLocaleString("ko-KR")}일</td>
              <td className="pg-td-num">{probText(s.share)}</td>
              <td className="pg-td-num">{dailyText(s.mean_return)}</td>
              <td className="pg-td-num">{volText(s.realized_vol)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      </div>
      <dl className="itd-mr-lines">
        <div className="itd-mr-bic">
          <dt>같은 자료의 BIC(낮을수록 자료에 잘 맞음 · 국면 수를 고르지 않습니다)</dt>
          <dd>
            {a.bic ? ["2", "3", "4"].map((k) => (
              <span key={k} className="itd-mr-bic-k">국면 {k}개 <b data-k={k}>{bicText(a.bic?.[k])}</b></span>
            )) : <span>{UNKNOWN_TEXT}</span>}
          </dd>
        </div>
        <div className="itd-mr-agree">
          <dt>난수 시드 일치도(조정 랜드 지수 · 마지막 적합 창)</dt>
          <dd>{a.agreement ? `최소 ${num(a.agreement.min, 3)} · 평균 ${num(a.agreement.mean, 3)} · 시드 ${a.agreement.seeds}개` : UNKNOWN_TEXT}</dd>
        </div>
        <div className="itd-mr-trans">
          <dt>국면 전환</dt>
          <dd>{a.transitions === null ? UNKNOWN_TEXT : `${a.transitions.toLocaleString("ko-KR")}번(값이 있는 날끼리)`}</dd>
        </div>
        <div className="itd-mr-fit">
          <dt>적합</dt>
          <dd>{a.fit ? `${a.fit.refits.toLocaleString("ko-KR")}번(달마다 한 번) · 창 ${a.fit.window_days.toLocaleString("ko-KR")}거래일 · 시드 ${a.fit.seeds}개`
            + (a.fit.failed ? ` · 수렴하지 않은 시드 ${a.fit.failed}개` : "") : UNKNOWN_TEXT}</dd>
        </div>
      </dl>
      <ul className="itd-mr-notes">
        {a.notes.map((n) => <li key={n} data-server>{n}</li>)}
      </ul>
    </div>
  );
}
