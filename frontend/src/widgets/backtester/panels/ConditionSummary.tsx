"use client";
// 설정 되읽기(오른쪽) — 지금 펼친 단계의 설정 전체를 읽기 전용으로 보인다. `buildSummary(strategy, tab)` 가 단일 소스.
// BU3: 요약 안의 탭 줄(매수/매도/매매대상)을 걷었다 — 왼쪽 단계가 이미 고르는 자리라 두 번 고르게 하지 않는다.
// ④ 돈·기간·비용은 `buildSummary` 의 매수 쪽 "포트 기본" 묶음이고, ① 무엇을 살까에서는 그 묶음을 뺀다(같은 줄을 두 번 보이지 않게).
// 판단이 아니라 사용자가 넣은 값이다 — 꺼진 값은 흐리게(`data-muted`) 둔다. "안 켬"과 "못 잼"을 가르는 문구는 `buildSummary` 그대로.

import { buildSummary, type BacktestStrategy } from "@/entities/backtest/strategy";

export type StepId = "buy" | "sell" | "universe" | "capital";

const STEP_NAME: Record<StepId, string> = { buy: "무엇을 살까", sell: "언제 팔까", universe: "어디서 고를까", capital: "돈·기간·비용" };
const CAPITAL_GROUP = "포트 기본";

/** ★아직 세지 않은 대상 수를 0으로 보이지 않는다★ 대상 수는 ③을 열 때 서버에 묻는다(`universe-count`) — 그 전의
 *  `matched·totalUniverse = 0` 은 "0종목"이 아니라 "모름"이다(미상 ≠ 0). 첫 화면에서 미리 묻지 않는 것은 요청 골든을 지키려고. */
const UNCOUNTED = "③을 열면 세어요";
export function stepGroups(s: BacktestStrategy, step: StepId) {
  if (step === "capital") return buildSummary(s, "buy").filter((g) => g.label === CAPITAL_GROUP);
  if (step === "buy") return buildSummary(s, "buy").filter((g) => g.label !== CAPITAL_GROUP);
  const groups = buildSummary(s, step);
  if (step !== "universe" || s.universe.totalUniverse > 0) return groups;
  return groups.map((g) => ({ ...g, rows: g.rows.map((r) =>
    r.label === "선택한 매매 대상" || r.label === "전체 종목" ? { ...r, value: UNCOUNTED, muted: true } : r) }));
}

export default function ConditionSummary({ s, step }: { s: BacktestStrategy; step: StepId }) {
  return (
    <section className="tbt-summary bte-sum" aria-label="지금 설정">
      <h2 className="bte-sum-h">지금 설정</h2>
      <p className="bte-sum-sub">{STEP_NAME[step]}</p>
      {stepGroups(s, step).map((g) => (
        <div key={g.label} className="bte-sum-g">
          <p className="bte-sum-gt">{g.label}</p>
          <dl className="bte-sum-rows">
            {g.rows.map((r, i) => (
              <div key={i} className="bte-sum-row" data-muted={r.muted ? "1" : "0"}>
                <dt>{r.label}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </section>
  );
}
