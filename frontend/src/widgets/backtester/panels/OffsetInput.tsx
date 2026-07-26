"use client";
// 체결 가격 기준 ± 오프셋% 입력 (젠포트 "전일종가 +0.5%" 지정가 모델).
// 0이 아니면 지정가 도달 검증 — 미도달 시 그날 미체결됨을 힌트로 안내.

const box: React.CSSProperties = {
  fontFamily: "var(--bs-font-mono)", fontSize: 13, width: 64, textAlign: "center",
  padding: "6px 8px", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", background: "var(--bg-card)", color: "var(--text-primary)",
};
const chip: React.CSSProperties = {
  fontSize: 11, color: "var(--text-secondary)", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", padding: "4px 7px", background: "var(--bg-card)", cursor: "pointer",
};

export default function OffsetInput({ value, onChange }: {
  value: number; onChange: (v: number) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <input type="number" step={0.1} min={-10} max={10} value={value}
          onChange={(e) => {
            const n = Number(e.target.value) || 0;
            onChange(Math.max(-10, Math.min(10, n)));
          }} style={box} />
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>%</span>
        {[-1, -0.5, 0, 0.5, 1].map((v) => (
          <button key={v} type="button" onClick={() => onChange(v)}
            style={{ ...chip, ...(value === v ? { borderColor: "var(--bs-primary)", color: "var(--bs-primary)" } : {}) }}>
            {v > 0 ? `+${v}%` : `${v}%`}
          </button>
        ))}
      </div>
      {value !== 0 && (
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          기준가×(1{value > 0 ? "+" : ""}{value}%)를 지정가로 주문 — 당일 미도달 시 그날 미체결
        </span>
      )}
    </div>
  );
}
