"use client";
// 체결 가격 기준 ± 오프셋% 입력 (젠포트 "전일종가 +0.5%" 지정가 모델).
// 0이 아니면 지정가 도달 검증 — 미도달 시 그날 미체결됨을 문장으로 알린다. BU3: 인라인 style → kit 클래스.

export default function OffsetInput({ value, onChange }: {
  value: number; onChange: (v: number) => void;
}) {
  return (
    <div className="bte-col">
      <div className="bte-row">
        <input type="number" step={0.1} min={-10} max={10} value={value} className="kit-num kit-num--sm" aria-label="기준가에서 더하거나 뺄 %"
          onChange={(e) => {
            const n = Number(e.target.value) || 0;
            onChange(Math.max(-10, Math.min(10, n)));
          }} />
        <span className="kit-unit">%</span>
        <span className="kit-chips">
          {[-1, -0.5, 0, 0.5, 1].map((v) => (
            <button key={v} type="button" className="kit-chip" aria-pressed={value === v} onClick={() => onChange(v)}>
              {v > 0 ? `+${v}%` : `${v}%`}
            </button>
          ))}
        </span>
      </div>
      {value !== 0 && (
        <p className="bte-note">기준가 × (1 {value > 0 ? "+" : "−"} {Math.abs(value)}%)를 지정가로 주문해요. 그날 닿지 않으면 체결되지 않아요.</p>
      )}
    </div>
  );
}
