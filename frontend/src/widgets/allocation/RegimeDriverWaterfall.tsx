"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RegimeDriverWaterfall — 왜 이 국면인가 (A8, 설명가능성)
// ─────────────────────────────────────────────────────────────────────────────
// 25%(아무것도 모를 때) 에서 출발해 지표별 기여를 더하면 최종 확률에 **정확히**
// 도달한다. Shapley 효율성 공리이고, 서버가 잔차를 함께 주므로 화면이 스스로를
// 검산한다 — 잔차가 0 이 아니면 그 사실을 띄운다.
//
// ★두 층을 함께 보여 준다 — 실측이 그래야 한다고 말했다★
// 소비자물가의 **축 기여는 −0.111**(물가축을 낮춘다)인데 **골디락스 확률 기여 φ 는
// +0.103** 이다. 골디락스가 성장↑ 물가↓ 라 부호가 뒤집힌다. 축 기여만 보여 주면
// 화면이 "물가가 골디락스를 깎았다" 로 읽히는데 사실은 두 번째로 큰 양의 기여다.
// 그래서 φ(확률 기여)를 주 막대로, 축 기여를 보조 수치로 나란히 둔다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import { REGIME_COLORS, type RegimeDrivers } from "@/entities/macro/api";
import { EvidenceBadge } from "@/shared/ui/evidence";

const KO: Record<string, string> = {
  Goldilocks: "골디락스", Reflation: "리플레이션",
  Stagflation: "스태그플레이션", Disinflation: "디스인플레이션",
};

const pp = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%p`;

export function RegimeDriverWaterfall({ dr }: { dr: RegimeDrivers }) {
  if (!dr.available) {
    return <EvidenceBadge kind="unavailable" reason={dr.reason}>드라이버 분해 미가용</EvidenceBadge>;
  }

  const { drivers, baseline, probability, regime } = dr;
  // 막대 폭의 기준 — 가장 큰 절대 기여가 칸을 꽉 채우게 한다.
  const maxAbs = Math.max(...drivers.map((d) => Math.abs(d.phi)), 1e-6);
  const badResidual = Math.abs(dr.efficiency_residual) > 1e-6;

  return (
    <div className="as-rgd">
      <div className="as-rgd-lead">
        모든 지표가 <b>역사 평균</b>이면 네 국면이 각각 25% 입니다. 거기서 출발해 각 지표가{" "}
        <b style={{ color: REGIME_COLORS[regime]?.fg }}>{KO[regime] ?? regime}</b> 확률을
        얼마나 밀어올렸는지(내렸는지)를 더한 것이 아래입니다.
      </div>

      {/* 시작점 */}
      <div className="as-rgd-anchor">
        <span className="as-rgd-anchor-l">기저 — 모든 지표가 평균</span>
        <b className="num">{(baseline * 100).toFixed(1)}%</b>
      </div>

      <div className="as-rgd-rows">
        {drivers.map((d) => {
          const w = (Math.abs(d.phi) / maxAbs) * 50;   // 중앙 기준 좌우 최대 50%
          const up = d.phi >= 0;
          return (
            <div className="as-rgd-row" key={d.key}>
              <span className="as-rgd-name">
                {d.label}
                <em className="as-rgd-axis">{d.axis === "growth" ? "성장축" : "물가축"}</em>
              </span>
              <span className="as-rgd-track">
                <i className="as-rgd-zero" aria-hidden="true" />
                <i className={`as-rgd-bar ${up ? "up" : "dn"}`}
                  style={up ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
              </span>
              <b className={`as-rgd-phi num ${up ? "up" : "dn"}`}>{pp(d.phi)}</b>
              {/* 축 기여 — 부호가 φ 와 다를 수 있다. 그게 정보다. */}
              <span className="as-rgd-axc num"
                title={undefined}>축 {d.axis_contribution >= 0 ? "+" : ""}{d.axis_contribution.toFixed(3)}σ</span>
            </div>
          );
        })}
      </div>

      {/* 도착점 + 검산 */}
      <div className="as-rgd-anchor as-rgd-final">
        <span className="as-rgd-anchor-l">
          합계 — {KO[regime] ?? regime} 확률
        </span>
        <b className="num" style={{ color: REGIME_COLORS[regime]?.fg }}>
          {(probability * 100).toFixed(1)}%
        </b>
      </div>

      {/* ★화면이 스스로 검산한다★ */}
      <div className={`as-rgd-check${badResidual ? " bad" : ""}`} role="status">
        {badResidual ? (
          <>검산 실패 — 지표 기여의 합이 최종 확률과 <b className="num">
            {dr.efficiency_residual.toExponential(2)}</b> 만큼 어긋납니다. 이 분해는 믿지 마세요.</>
        ) : (
          <>검산 <b className="num">Σφ = {(dr.sum_phi * 100).toFixed(1)}%p</b> ={" "}
            <b className="num">{(probability * 100).toFixed(1)}% − {(baseline * 100).toFixed(1)}%</b>{" "}
            — 부분집합 {dr.n_coalitions}개를 전부 세어 구한 정확 Shapley 값이라 오차 없이 맞아떨어집니다.</>
        )}
      </div>

      <p className="as-rgd-note">
        축 기여(오른쪽 σ)와 확률 기여(φ)의 <b>부호가 다를 수 있습니다</b>. 예를 들어
        골디락스는 성장↑·물가↓ 이므로 물가축을 <b>낮추는</b> 지표는 축 기여가 음수이면서
        골디락스 확률에는 양으로 기여합니다 — 한쪽만 보면 정반대로 읽힙니다.
      </p>
    </div>
  );
}
