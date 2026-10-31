"use client";
// 분할 래더 편집기 (젠포트 분할 매수/매도) — [가격변동 % + 비중 %] 행을 추가로 쌓는다.
// 보수적 해석: 래더는 신호 당일만 유효 — 도달한 단계만 체결, 미도달 단계는 소멸. BU3: 인라인 style → 클래스.

export interface LadderStep { movePct: number; weightPct: number }

export default function LadderEditor({ steps, onChange, side }: {
  steps: LadderStep[]; onChange: (s: LadderStep[]) => void; side: "buy" | "sell";
}) {
  const total = steps.reduce((a, s) => a + (s.weightPct || 0), 0);
  const patch = (i: number, p: Partial<LadderStep>) =>
    onChange(steps.map((s, j) => (j === i ? { ...s, ...p } : s)));
  const what = side === "buy" ? "사는" : "파는";
  return (
    <div className="bte-ladder">
      <div className="bte-ladder-h" aria-hidden><span>가격 변동</span><span>{what} 비중</span></div>
      {steps.map((s, i) => (
        <div key={i} className="bte-row">
          <input type="number" step={0.5} value={s.movePct} className="kit-num kit-num--sm" aria-label={`${i + 1}단계 가격 변동 %`}
            onChange={(e) => patch(i, { movePct: Number(e.target.value) || 0 })} />
          <span className="kit-unit">%</span>
          <input type="number" step={5} min={1} max={100} value={s.weightPct} className="kit-num kit-num--sm" aria-label={`${i + 1}단계 ${what} 비중 %`}
            onChange={(e) => patch(i, { weightPct: Number(e.target.value) || 0 })} />
          <span className="kit-unit">%</span>
          <button type="button" className="bte-icon-btn" aria-label={`${i + 1}단계 빼기`}
            onClick={() => onChange(steps.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <div className="bte-row">
        <button type="button" className="kit-chip" disabled={steps.length >= 10}
          onClick={() => onChange([...steps, { movePct: side === "buy" ? -1 * (steps.length) : 1 * (steps.length + 1), weightPct: 10 }])}>
          + 단계 더하기
        </button>
        <span className={`bte-note${total > 100 ? " bte-note--bad" : ""}`} role={total > 100 ? "alert" : undefined}>
          비중 합 {total}%{total > 100 ? " — 100%를 넘을 수 없어요" : ""}
        </span>
      </div>
      <p className="bte-note">기준가 × (1 + 변동%)에 단계별 지정가를 걸어요. 그날 닿은 단계만 체결되고 나머지는 사라져요(보수적).</p>
    </div>
  );
}
