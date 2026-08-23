"use client";
// Alpha Lab 표시 컴포넌트 — lint 배지 · 분위 막대 · 롱숏 곡선. props만 받는다.
// JSX·className 불변 (app/allocation/alphalab/page.tsx에서 분리).

import type { LintResult } from "@/entities/alpha/api";

export function LintBadges({ lint }: { lint: LintResult | null }) {
  if (!lint) return null;
  if (!lint.issues.length) return <div className="as-note" style={{ color: "var(--color-bull)" }}>✓ lint 통과 — 이슈 없음</div>;
  return (
    <div className="as-al-lint">
      {lint.issues.map((i, k) => (
        <div key={k} className={`as-al-lint-item ${i.level}`}>
          <b>{i.level.toUpperCase()}</b> {i.message}
        </div>
      ))}
    </div>
  );
}

export function QuantileBars({ q }: { q: { n: number; ann_return_pct: (number | null)[]; monotonicity: number | null } }) {
  const vals = q.ann_return_pct.map((v) => v ?? 0);
  const maxAbs = Math.max(...vals.map(Math.abs), 1);
  return (
    <div>
      <div className="as-al-qbars">
        {vals.map((v, i) => (
          <div key={i} className="as-al-qcol" title={`Q${i + 1}: 연 ${v}%`}>
            <div className="as-al-qbar" style={{
              height: `${Math.abs(v) / maxAbs * 64}px`,
              background: v >= 0 ? "var(--color-bull)" : "var(--color-bear)",
              alignSelf: v >= 0 ? "flex-end" : "flex-start",
            }} />
            <span className="num">Q{i + 1}</span>
          </div>
        ))}
      </div>
      <div className="as-note num">분위별 연수익(저→고) · 모노토닉 {q.monotonicity ?? "—"}</div>
    </div>
  );
}

export function LsCurve({ curve }: { curve: number[] }) {
  if (curve.length < 3) return null;
  const W = 560, H = 120;
  const min = Math.min(...curve), max = Math.max(...curve);
  const rng = max - min || 1;
  const pts = curve.map((v, i) =>
    `${(i / (curve.length - 1)) * W},${H - ((v - min) / rng) * H}`).join(" ");
  const up = curve[curve.length - 1] >= curve[0];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 120, borderBottom: "1px solid var(--t-border)", borderLeft: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={up ? "var(--color-bull)" : "var(--color-bear)"} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
