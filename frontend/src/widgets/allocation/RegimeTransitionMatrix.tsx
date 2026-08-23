"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RegimeTransitionMatrix — 다음 달 어디로 갈 위험인가 (A8)
// ─────────────────────────────────────────────────────────────────────────────
// 4×4 히트맵. 셀은 **사후평균 + 90% 신용구간**이다. 점추정 하나만 찍으면 관측
// 1개짜리 행과 60개짜리 행이 화면에서 똑같아 보인다 — 그 둘을 구분하는 것이
// 이 표의 존재 이유다.
//
// ★수축된 행은 색이 아니라 글자로 말한다★
// 관측이 모자란 행은 값이 대부분 사전분포에서 온다. 그 사실을 채도나 테두리로만
// 표시하면 색각 이상 사용자에게는 없는 정보다(WCAG: 색만으로 의미 전달 금지).
// 행 옆에 사유 텍스트를 둔다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import { REGIME_COLORS, type Regime, type RegimeTransitions } from "@/entities/macro/api";
import { EvidenceBadge } from "@/shared/ui/evidence";

const KO: Record<string, string> = {
  Goldilocks: "골디락스", Reflation: "리플레이션",
  Stagflation: "스태그플레이션", Disinflation: "디스인플레이션",
};

const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

/**
 * 셀 배경 — 확률이 높을수록 진하게. 값은 **항상 글자로도** 있으므로 색은 보조다.
 *
 * ★알파 상한이 0.63 이었고 대비 감사가 잡았다★
 * 포화 강청색(`#1200ff`)을 0.63까지 깔면 그 위의 글자가 라이트에서 2.22:1
 * (본문 값), 1.76:1(신용구간)까지 떨어진다. 히트맵의 색이 **주 정보인 숫자를
 * 파괴**하고 있었다 — 배경은 보조인데 본말이 뒤집힌 것이다. 상한을 0.20 으로
 * 낮춰 색은 순위만 암시하고 판독은 숫자가 맡게 한다.
 */
function cellBg(p: number, isDiag: boolean): string {
  const a = (0.03 + 0.17 * Math.max(0, Math.min(1, p))).toFixed(3);
  return isDiag ? `rgb(18 0 255 / ${a})` : `rgb(113 113 122 / ${a})`;
}

export function RegimeTransitionMatrix({ tr }: { tr: RegimeTransitions }) {
  if (!tr.available) {
    return (
      <EvidenceBadge kind="unavailable" reason={tr.reason}>전이행렬 미가용</EvidenceBadge>
    );
  }

  const regimes = tr.regimes;
  const fc = tr.forecast;

  return (
    <div className="as-rgt">
      <div className="as-rgt-lead">
        현재 <b>{KO[tr.current] ?? tr.current}</b> 에서 <b>다음 달</b> 각 국면으로 갈 확률입니다.
        각 칸은 사후평균이고 아래 작은 숫자가 90% 신용구간 — <b>관측이 적을수록 구간이 넓어집니다.</b>
      </div>

      <div className="as-rgt-wrap">
        <table className="as-rgt-tbl">
          <thead>
            <tr>
              <th scope="col" className="as-rgt-corner">현재 ↓ / 다음 →</th>
              {regimes.map((r) => (
                <th key={r} scope="col" style={{ color: REGIME_COLORS[r]?.fg }}>{KO[r] ?? r}</th>
              ))}
              <th scope="col">관측</th>
              <th scope="col">기대 지속</th>
            </tr>
          </thead>
          <tbody>
            {tr.rows.map((row) => {
              const isCurrent = row.from === tr.current;
              return (
                <tr key={row.from} className={isCurrent ? "on" : undefined}>
                  <th scope="row" style={{ color: REGIME_COLORS[row.from]?.fg }}>
                    {KO[row.from] ?? row.from}
                    {isCurrent && <span className="as-rgt-now">현재</span>}
                  </th>
                  {regimes.map((to) => {
                    const m = row.mean[to] ?? 0;
                    const ci = row.ci90[to] ?? [0, 0];
                    return (
                      <td key={to} style={{ background: cellBg(m, to === row.from) }}>
                        <b className="num">{pct(m)}</b>
                        <span className="as-rgt-ci num">{pct(ci[0])}–{pct(ci[1])}</span>
                      </td>
                    );
                  })}
                  <td className="num as-rgt-n">{row.n}</td>
                  <td className="num as-rgt-dur">
                    {row.expected_duration_months == null
                      ? "—" : `${row.expected_duration_months}개월`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ★수축된 행은 글자로 말한다★ 색·채도만으로는 전달되지 않는다. */}
      {tr.rows.filter((r) => r.shrunk).map((r) => (
        <div key={r.from} className="as-rgt-shrunk" role="status">
          <b>{KO[r.from] ?? r.from}</b> 행: {r.reason}
        </div>
      ))}

      {/* k개월 사후예측 */}
      {fc.available ? (
        <div className="as-rgt-fc">
          <div className="as-rgt-fc-h">
            <b>{fc.k}개월 뒤 분포</b>
            <span className="as-note-inline">
              전이행렬을 사후분포에서 {fc.draws.toLocaleString()}회 뽑아 거듭제곱 —
              얇은 행의 불확실성이 여기까지 전달됩니다
            </span>
          </div>
          <div className="as-rgt-fc-rows">
            {regimes.map((r) => {
              const m = fc.mean[r] ?? 0;
              const ci = fc.ci90[r] ?? [0, 0];
              return (
                <div className="as-rgt-fc-row" key={r}>
                  <span className="as-rgt-fc-l">{KO[r] ?? r}</span>
                  <span className="as-rgt-fc-track">
                    <i style={{ width: `${(m * 100).toFixed(1)}%`, background: REGIME_COLORS[r]?.border }} />
                  </span>
                  <span className="as-rgt-fc-v num">{pct(m)}</span>
                  <span className="as-rgt-fc-ci num">{pct(ci[0])}–{pct(ci[1])}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <EvidenceBadge kind="unavailable" reason={fc.reason}>예측 미가용</EvidenceBadge>
      )}

      <div className="as-rgt-foot">
        전이 {tr.n_transitions}회 관측 · 사전분포 α(대각 {tr.prior.alpha_diag} / 비대각{" "}
        {tr.prior.alpha_off}) — {tr.prior.note}
      </div>
    </div>
  );
}

export type { Regime };
