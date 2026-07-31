"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 타이밍 오버레이 — Optimize 의 **명시적 입력** (스펙 §8, Phase 10c).
//
// §8: "Optimize 는 타이밍 산출을 제약/오버레이/목표위험 조정으로 받고 **전략 비중을 조용히
// 덮어쓰지 않는다**. before/after 비중·회전율·집중도·베타·팩터 노출·비가능 사유를 보인다."
//
// ★이 패널은 전략 비중을 건드리지 않는다★
// 노출 배율을 곱한 **결과를 보여줄 뿐**이고, 오버레이를 끄면 원래 비중이 그대로 돌아온다.
// (04 TIMING 의 "권고 배분으로 교체" 는 별개의 파괴적 동작이다 — 그쪽은 위험-오프일 때
// 방어자산으로 갈아타므로 배율로는 재현할 수 없고, 그래서 남겨 두되 교체임을 명시한다.)
//
// ★일방향★ 노출은 1 을 넘지 못한다. 오버레이가 노출을 키울 수 있으면 "리스크 관리" 가
// 조용히 레버리지가 된다 — 매크로 오버레이가 지키는 것과 같은 규칙.
//
// ★계산하지 않은 것을 계산한 척하지 않는다★
// 균일 배율은 위험자산 **사이의** 상대 비중을 바꾸지 않는다. 그래서 팩터 틸트(x-ray z-score)와
// 위험자산 내 집중도는 **불변**이고, 그 사실을 적는다 — 그럴듯한 Δ 를 지어내는 대신.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";

import { useAllocation } from "./AllocationProvider";

/** 허핀달 지수 → 유효 종목 수. 비중은 % 단위. */
function hhiNeff(weights: number[]): { hhi: number; neff: number } {
  const tot = weights.reduce((a, b) => a + b, 0);
  if (tot <= 0) return { hhi: 0, neff: 0 };
  const hhi = weights.reduce((a, w) => a + (w / tot) ** 2, 0);
  return { hhi, neff: hhi > 0 ? 1 / hhi : 0 };
}

export function TimingOverlayPanel() {
  const {
    timingOverlay, clearTimingOverlay, holdings, holdingsMap, result,
  } = useAllocation();

  // 기준은 **최적화 결과가 있으면 그것**, 없으면 사용자가 담은 비중. 오버레이는 마지막 단계다.
  const before: Record<string, number> = result?.weights.optimized ?? holdingsMap;
  const codes = Object.keys(before);
  const labels = result?.labels ?? {};
  const nameOf = (c: string) =>
    labels[c] || holdings.find((h) => h.code === c)?.name || c;

  if (!timingOverlay) {
    return (
      <section className="as-card as-tov">
        <div className="as-card-title">
          타이밍 오버레이 <span className="as-note-inline">전략 비중을 유지한 채 노출만 조정</span>
        </div>
        <div className="as-empty">
          04 TIMING 에서 <b>오버레이로 적용</b>하면 여기에 before/after 가 표시됩니다.
          전략 비중은 그대로 두고 노출만 줄이는 방식입니다.
        </div>
      </section>
    );
  }

  const e = Math.max(0, Math.min(1, timingOverlay.exposure));
  const after: Record<string, number> = {};
  codes.forEach((c) => { after[c] = (before[c] ?? 0) * e; });
  const cashAfter = codes.reduce((a, c) => a + (before[c] ?? 0), 0) * (1 - e);

  // 회전율 = Σ|after − before| / 2 (편도). 현금으로 빠지는 만큼이 곧 매도다.
  const turnover = codes.reduce((a, c) => a + Math.abs((after[c] ?? 0) - (before[c] ?? 0)), 0) / 2;
  const riskBefore = hhiNeff(codes.map((c) => before[c] ?? 0));
  const withCash = hhiNeff([...codes.map((c) => after[c] ?? 0), cashAfter]);
  const rep = result?.constraints_report;

  return (
    <section className="as-card as-tov">
      <div className="as-card-title">
        타이밍 오버레이
        <span className="as-note-inline">전략 비중 유지 · 노출만 조정</span>
        <button className="as-chip as-tov-off" onClick={clearTimingOverlay}>오버레이 해제</button>
      </div>

      <div className="as-tov-head">
        <div><span>위험자산 노출</span><b className="num as-tov-exp">{(e * 100).toFixed(0)}%</b></div>
        <div><span>현금</span><b className="num">{cashAfter.toFixed(1)}%</b></div>
        <div><span>회전율(편도)</span><b className="num">{turnover.toFixed(1)}%</b></div>
      </div>

      <table className="as-metrics as-tov-table">
        <thead><tr><th>자산</th><th>before</th><th>after</th><th>Δ</th></tr></thead>
        <tbody>
          {codes.map((c) => {
            const b = before[c] ?? 0; const a = after[c] ?? 0;
            return (
              <tr key={c}>
                <td>{nameOf(c)}</td>
                <td className="num">{b.toFixed(1)}%</td>
                <td className="num">{a.toFixed(1)}%</td>
                {/* 오버레이는 줄이기만 하므로 Δ 는 0 이하다 — 양수가 보이면 일방향이 깨진 것이다. */}
                <td className="num as-tov-d">{(a - b).toFixed(1)}%p</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="as-tov-conc">
        <div><span>집중도(위험자산 내)</span>
          <b className="num">HHI {riskBefore.hhi.toFixed(3)} · 유효 {riskBefore.neff.toFixed(1)}종목</b>
          <em className="as-note-inline">불변 — 균일 배율은 상대 비중을 바꾸지 않습니다</em></div>
        <div><span>집중도(현금 포함)</span>
          <b className="num">HHI {withCash.hhi.toFixed(3)} · 유효 {withCash.neff.toFixed(1)}종목</b></div>
      </div>

      {/* ★지어내지 않는다★ 베타·팩터 노출의 절대값은 이 화면이 갖고 있지 않다. 대신 균일
          배율이 그것들에 어떻게 작용하는지는 산술적으로 확정적이라, 그 사실만 적는다. */}
      <div className="as-note">
        포트폴리오 <b>베타는 노출에 비례해 {(e * 100).toFixed(0)}% 로 축소</b>됩니다(현금 베타 0).
        <b> 팩터 틸트(x-ray z-score)는 변하지 않습니다</b> — 위험자산을 같은 배율로 줄이면
        상대 노출이 그대로이기 때문입니다. 절대 팩터 노출량은 같은 비율로 줄어듭니다.
      </div>

      {/* §8: 비가능 사유를 함께 — 오버레이가 제약을 푸는 것은 아니다 */}
      {rep && rep.status !== "ok" && (
        <div className={rep.status === "infeasible" ? "as-err" : "as-note"}>
          제약 상태: <b>{rep.status}</b>
          {rep.reason ? ` — ${rep.reason}` : ""}
          {rep.violations.length > 0 && (
            <ul className="as-tov-viol">
              {rep.violations.map((v, i) => <li key={i}>{v.kind} — {v.detail}</li>)}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
