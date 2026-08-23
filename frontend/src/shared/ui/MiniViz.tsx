// 모듈 미니 비주얼 (랜딩 page.tsx Visual 5종 이식) + 큰 모노 스탯 그리드 헬퍼.
// 순수 SVG/프레젠테이션 — 데이터 패칭/상태 없음. var(--bs-primary) → var(--t-accent)로 토큰화.
import React from "react";

export type MiniVizKind = "bars" | "line" | "heat" | "rows" | "gauge";

export function MiniViz({ kind, className = "t-miniviz" }: { kind: MiniVizKind; className?: string }) {
  if (kind === "bars") {
    const hs = [9, 14, 7, 18, 12, 22, 16, 27, 20, 31];
    return (
      <svg className={className} viewBox="0 0 120 36" preserveAspectRatio="xMidYMid meet">
        {hs.map((h, i) => (
          <rect key={i} x={i * 12 + 2} y={36 - h} width="7" height={h}
            fill={i === hs.length - 1 ? "var(--t-accent)" : "#d4d4d8"} />
        ))}
      </svg>
    );
  }
  if (kind === "line") {
    return (
      <svg className={className} viewBox="0 0 120 36" preserveAspectRatio="xMidYMid meet">
        <polyline points="2,30 22,26 42,29 62,18 82,21 102,10 118,13"
          fill="none" stroke="var(--t-accent)" strokeWidth="1.6" />
        <polyline points="2,32 22,31 42,32 62,28 82,29 102,24 118,26"
          fill="none" stroke="#d4d4d8" strokeWidth="1.2" />
      </svg>
    );
  }
  if (kind === "heat") {
    const cells = [0.35, 0.7, 1, 0.25, 0.5, 0.2, 1, 0.45, 0.3, 0.6, 0.15, 0.4];
    return (
      <svg className={className} viewBox="0 0 120 36" preserveAspectRatio="xMidYMid meet">
        {cells.map((o, i) => (
          <rect key={i} x={(i % 4) * 30 + 1} y={Math.floor(i / 4) * 12 + 1}
            width="27" height="10" fill="var(--t-accent)" opacity={0.12 + o * 0.55} />
        ))}
      </svg>
    );
  }
  if (kind === "rows") {
    return (
      <svg className={className} viewBox="0 0 120 36" preserveAspectRatio="xMidYMid meet">
        {[6, 16, 26].map((y, i) => (
          <g key={i}>
            <rect x="2" y={y} width={86 - i * 18} height="3.5" fill="#e4e4e7" />
            <rect x="2" y={y} width={40 - i * 8} height="3.5" fill="var(--t-accent)" opacity="0.65" />
          </g>
        ))}
      </svg>
    );
  }
  // gauge
  return (
    <svg className={className} viewBox="0 0 120 36" preserveAspectRatio="xMidYMid meet">
      <circle cx="60" cy="18" r="13" fill="none" stroke="#e4e4e7" strokeWidth="2.5" />
      <path d="M 60 5 A 13 13 0 0 1 72.3 22" fill="none" stroke="var(--t-accent)" strokeWidth="2.5" />
    </svg>
  );
}

// 큰 모노 KPI 스트립 (.tstat-grid / .tstat) — Risk·Macro·Company 공용
export function StatGrid({ children }: { children: React.ReactNode }) {
  return <div className="tstat-grid">{children}</div>;
}

export function Stat({ k, v, sub, valueColor }: {
  k: string;
  v: React.ReactNode;
  sub?: React.ReactNode;
  /** 토큰 색상 (예: "var(--color-bull)") — 값 텍스트에만 적용 */
  valueColor?: string;
}) {
  return (
    <div className="tstat">
      <span className="tstat-key">{k}</span>
      <div className="tstat-val" style={valueColor ? { color: valueColor } : undefined}>{v}</div>
      {sub != null && <div className="tstat-sub">{sub}</div>}
    </div>
  );
}
