"use client";
/**
 * 국면별 성과 나눔의 표 — 내 시행의 일별 손익을 그날 시가 전에 알던 시장 국면별로 나눈 것 (구현 계획 §7.3 · K2a)
 * ==========================================================================
 * 숫자는 서버 값을 서식만 한다(국면들 + 미상 = 합계는 서버가 맞춘다). 한계 문장 · 사유는 서버 글 그대로(`data-server`).
 * ★순위 · 이긴 국면의 색 강조가 없다★ — 국면 색은 번호의 표지일 뿐이다(시장 국면 절과 같은 밝기 단계).
 * 거래 수를 남기지 않은 옛 시행이면 거래 · 승률은 N/A + 서버 사유다(0 이 아니다). 결과 화면과 캔버스 판이 함께 쓴다.
 * 미상 줄 · 합계 줄의 승률과 합계의 '확률 0.5 미만' 도 서버 값이다 — 미상 줄의 '확률 0.5 미만' 만 N/A(그날 확률이 없다).
 */
import { useId } from "react";
import type { RegimeSplitAnswer, RegimeSplitBlock } from "@/entities/intraday";
import { stateFill } from "@/entities/intraday";
import { num, pct, signedWon, UNKNOWN_TEXT } from "@/shared/lib/krFormat";
import { Notice } from "@/shared/ui/tx";

const BASIS_KO: Record<string, string> = { net: "비용 뒤", gross: "비용 전" };

const count = (v: number | null, unit: string) => (v === null ? UNKNOWN_TEXT : `${num(v)}${unit}`);
const rate = (v: number | null) => (v === null ? UNKNOWN_TEXT : pct(v));

export function RegimeSplitTable({ a }: { a: RegimeSplitAnswer }) {
  const synthetic = a.trial_grade === "E0" || a.regime_grade === "E0";
  return (
    <div className="itd-rs-result" data-index={a.index} data-k={a.k} data-trial-grade={a.trial_grade ?? "unknown"}
         data-regime-grade={a.regime_grade ?? "unknown"}>
      <p className="itd-rs-head">
        {a.name} · 국면 {a.k}개 · <span className="itd-rs-range">{a.from} ~ {a.to}</span>
        {` · 시행 등급 ${a.trial_grade ?? "미상"} · 국면 등급 ${a.regime_grade ?? "미상"}`}
      </p>
      {synthetic ? (
        <div className="itd-rs-synth">
          <Notice tone="warn" title="합성 자료가 들어 있습니다.">
            {a.coverage?.reason ? <><span data-server>{a.coverage.reason}</span> </> : null}국면별 숫자는 장치 확인용이며 시장에 대한 진술이 아닙니다.
          </Notice>
        </div>
      ) : null}
      {a.regime_grade === null && a.regime_grade_reason ? <p className="itd-why itd-rs-grade"><span data-server>{a.regime_grade_reason}</span></p> : null}
      {a.empty || !a.split ? (
        <div className="itd-rs-empty" data-empty={a.empty?.reason ?? "no_split"}>
          <Notice tone="danger" title="국면별로 나누지 않았습니다."><span data-server>{a.empty?.message ?? UNKNOWN_TEXT}</span></Notice>
        </div>
      ) : <SplitBody a={a} s={a.split} />}
      <ul className="itd-rs-notes">{a.notes.map((n) => <li key={n} data-server>{n}</li>)}</ul>
    </div>
  );
}

function SplitBody({ a, s }: { a: RegimeSplitAnswer; s: RegimeSplitBlock }) {
  const capId = useId();
  const basis = s.basis ? BASIS_KO[s.basis] ?? s.basis : "기준 미상";
  return (
    <div className="itd-rs-body">
      <div className="itd-rs-tablebox">
        <p className="itd-rs-cap" id={capId}>
          국면별 몫(그날 가장 큰 국면으로 센 거래일 · 시행 거래일 {num(s.total.days)}일 · 손익은 {basis} · 관측이며 결정에 쓰지 않습니다)
        </p>
        {/* 좁은 폭에서는 칸 글자를 쪼개지 않고 표를 옆으로 넘긴다 — 넘는 상자는 키보드(Tab → ←→)로도 닿는다 */}
        <div className="itd-rs-scroll" role="region" tabIndex={0} aria-labelledby={capId}>
          <table className="pg-table itd-rs-table" aria-labelledby={capId}>
            <thead>
              <tr>
                <th>국면</th><th className="pg-td-num">거래일</th><th className="pg-td-num">확률 0.5 미만</th>
                <th className="pg-td-num">거래</th><th className="pg-td-num">손익({basis})</th><th className="pg-td-num">승률</th>
              </tr>
            </thead>
            <tbody>
              {s.states.map((r) => (
                <tr key={r.state} data-state={r.state}>
                  <td><i className="itd-rs-chip" style={{ background: stateFill(r.state, a.k) }} aria-hidden="true" />국면 {r.state}</td>
                  <td className="pg-td-num">{num(r.days)}일</td>
                  <td className="pg-td-num">{num(r.low_conf_days)}일</td>
                  <td className="pg-td-num">{count(r.trades, "건")}</td>
                  <td className="pg-td-num">{signedWon(r.pnl)}</td>
                  <td className="pg-td-num">{rate(r.win_rate)}</td>
                </tr>
              ))}
              {s.unknown.days > 0 ? (
                <tr data-state="unknown">
                  <td><i className="itd-rs-chip itd-rs-chip--unknown" aria-hidden="true" />국면 미상</td>
                  <td className="pg-td-num">{num(s.unknown.days)}일</td>
                  <td className="pg-td-num">{UNKNOWN_TEXT}</td>
                  <td className="pg-td-num">{count(s.unknown.trades, "건")}</td>
                  <td className="pg-td-num">{signedWon(s.unknown.pnl)}</td>
                  <td className="pg-td-num">{rate(s.unknown.win_rate)}</td>
                </tr>
              ) : null}
            </tbody>
            <tfoot>
              <tr data-state="total">
                <th scope="row">합계</th>
                <td className="pg-td-num">{num(s.total.days)}일</td>
                <td className="pg-td-num">{num(s.total.low_conf_days)}일</td>
                <td className="pg-td-num">{count(s.total.trades, "건")}</td>
                <td className="pg-td-num">{signedWon(s.total.pnl)}</td>
                <td className="pg-td-num">{rate(s.total.win_rate)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
      {s.unknown.reasons.length ? (
        <ul className="tj-plain-list itd-rs-unknown">
          {s.unknown.reasons.map((r) => <li key={r.reason}><b>국면 미상 {num(r.days)}일</b> <span data-server>{r.reason}</span></li>)}
        </ul>
      ) : null}
      {!s.trades_known && s.trades_reason ? <p className="itd-why itd-rs-trades-why"><span data-server>{s.trades_reason}</span></p> : null}
      <dl className="itd-rs-lines">
        <div className="itd-rs-trans"><dt>국면 전환</dt><dd>{num(s.transitions)}번(국면이 있는 거래일끼리)</dd></div>
      </dl>
    </div>
  );
}
