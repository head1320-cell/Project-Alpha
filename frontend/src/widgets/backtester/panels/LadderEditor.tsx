"use client";
// 분할 래더 편집기 (젠포트 분할 매수/매도) — [가격변동 % + 비중 %] 행을 추가로 쌓는다.
// 보수적 해석: 래더는 신호 당일만 유효 — 도달한 단계만 체결, 미도달 단계는 소멸.

export interface LadderStep { movePct: number; weightPct: number }

const box: React.CSSProperties = {
  fontFamily: "var(--bs-font-mono)", fontSize: 13, width: 76, textAlign: "center",
  padding: "6px 8px", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", background: "var(--bg-card)", color: "var(--text-primary)",
};
const btn: React.CSSProperties = {
  fontSize: 12, color: "var(--text-secondary)", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", padding: "5px 10px", background: "var(--bg-card)", cursor: "pointer",
};

export default function LadderEditor({ steps, onChange, side }: {
  steps: LadderStep[]; onChange: (s: LadderStep[]) => void; side: "buy" | "sell";
}) {
  const total = steps.reduce((a, s) => a + (s.weightPct || 0), 0);
  const patch = (i: number, p: Partial<LadderStep>) =>
    onChange(steps.map((s, j) => (j === i ? { ...s, ...p } : s)));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      <div style={{ display: "flex", gap: 10, fontSize: 11, color: "var(--text-secondary)" }}>
        <span style={{ width: 76 }}>가격변동</span>
        <span style={{ width: 76 }}>{side === "buy" ? "매수 비중" : "매도 비중"}</span>
      </div>
      {steps.map((s, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input type="number" step={0.5} value={s.movePct}
            onChange={(e) => patch(i, { movePct: Number(e.target.value) || 0 })} style={box} />
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>%</span>
          <input type="number" step={5} min={1} max={100} value={s.weightPct}
            onChange={(e) => patch(i, { weightPct: Number(e.target.value) || 0 })} style={box} />
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>%</span>
          <button type="button" aria-label="단계 삭제" style={{ ...btn, padding: "4px 8px" }}
            onClick={() => onChange(steps.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <button type="button" style={btn} disabled={steps.length >= 10}
          onClick={() => onChange([...steps, { movePct: side === "buy" ? -1 * (steps.length) : 1 * (steps.length + 1), weightPct: 10 }])}>
          + 추가
        </button>
        <span style={{ fontSize: 11, color: total > 100 ? "#dc2626" : "var(--text-muted)" }}>
          비중 합 {total}% {total > 100 ? "— 100%를 넘을 수 없습니다" : ""}
        </span>
      </div>
      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
        기준가×(1+변동%)의 지정가 단계 — 당일 도달한 단계만 체결되고 미도달 단계는 소멸 (보수적)
      </span>
    </div>
  );
}
