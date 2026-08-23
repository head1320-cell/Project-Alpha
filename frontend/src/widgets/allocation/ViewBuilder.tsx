"use client";
// INVESTMENT THESIS — 사용자 뷰(Black-Litterman) 빌더.
// Research OS: 단순 폼이 아니라 `[테제] ➔ [자산] ➔ [방향·크기] ➔ [신뢰도]`의
// 인과관계 노드 체인으로 렌더 (Gemini ③). 동작 로직(onChange/onCommit)은 이전과
// 동일 — 태그 구조와 클래스만 변경. 슬라이더 드래그 중 로컬만, 릴리스 시 재최적화.
import React from "react";
import type { AllocationViewInput } from "@/entities/allocation/api";
import type { Holding } from "./PortfolioBuilder";

export function overallConfidence(views: AllocationViewInput[]): number {
  const vs = views.filter((v) => v.assets.length > 0);
  if (!vs.length) return 0;
  return vs.reduce((a, v) => a + v.confidence, 0) / vs.length;
}

export function ViewBuilder({ views, holdings, onChange, onCommit }: {
  views: AllocationViewInput[];
  holdings: Holding[];
  onChange: (next: AllocationViewInput[]) => void;   // 드래그 중 (로컬만)
  onCommit: () => void;                               // 릴리스/변경 확정 시 재최적화
}) {
  const patch = (idx: number, p: Partial<AllocationViewInput>) => {
    onChange(views.map((v, i) => (i === idx ? { ...v, ...p } : v)));
  };

  const addView = () => {
    const firstCode = holdings[0]?.code;
    onChange([...views, {
      assets: firstCode ? [firstCode] : [],
      direction: 1, magnitude_pct: 3, confidence: 60,
      label: "",
    }]);
  };

  const removeView = (idx: number) => {
    onChange(views.filter((_, i) => i !== idx));
    onCommit();
  };

  const toggleAsset = (idx: number, code: string) => {
    const v = views[idx];
    const has = v.assets.includes(code);
    patch(idx, { assets: has ? v.assets.filter((a) => a !== code) : [...v.assets, code] });
  };

  return (
    <div className="as-views">
      {views.length === 0 && (
        <div className="as-empty">뷰 없음 — 시장균형(캡가중) 그대로. &quot;+ 뷰 추가&quot;로 테제를 입력하세요.</div>
      )}
      {views.map((v, i) => (
        <div key={i} className="as-chain">
          {/* ① 테제 */}
          <span className="as-chain-node as-chain-thesis">
            <input placeholder={`테제 ${i + 1} (예: 반도체 강세)`}
              value={v.label || ""} onChange={(e) => patch(i, { label: e.target.value })} onBlur={onCommit} />
          </span>
          <span className="as-chain-arrow">➔</span>
          {/* ② 대상 자산 */}
          <span className="as-chain-node" style={{ gap: 4, flexWrap: "wrap" }}>
            {holdings.length === 0 && <em className="as-note-inline">자산 없음</em>}
            {holdings.map((h) => (
              <button key={h.code} className={`as-chip sm${v.assets.includes(h.code) ? " on" : ""}`}
                onClick={() => { toggleAsset(i, h.code); }} onBlur={onCommit} title={h.code}>
                {h.name}
              </button>
            ))}
          </span>
          <span className="as-chain-arrow">➔</span>
          {/* ③ 방향·크기 */}
          <span className="as-chain-node accent">
            <button className="as-chip sm" style={{ border: "none", background: "none", padding: 0,
              color: v.direction === 1 ? "var(--color-bull)" : "var(--color-bear)", fontWeight: 600 }}
              title="클릭으로 상회/하회 전환"
              onClick={() => { patch(i, { direction: v.direction === 1 ? -1 : 1 }); onCommit(); }}>
              {v.direction === 1 ? "▲ Overweight" : "▼ Underweight"}
            </button>
            <input className="as-w-input num" style={{ width: 44 }} type="number" min={0.5} max={30} step={0.5}
              value={v.magnitude_pct}
              onChange={(e) => patch(i, { magnitude_pct: parseFloat(e.target.value) || 0 })} onBlur={onCommit} />
            <span className="as-w-unit">%/년</span>
          </span>
          <span className="as-chain-arrow">➔</span>
          {/* ④ 신뢰도 */}
          <span className="as-chain-conf">
            <input type="range" min={0} max={100} step={5} value={v.confidence}
              onChange={(e) => patch(i, { confidence: parseFloat(e.target.value) })}
              onMouseUp={onCommit} onTouchEnd={onCommit} onKeyUp={onCommit} />
            <b className="num">{Math.round(v.confidence)}%</b>
          </span>
          <button className="as-x" title="뷰 삭제" onClick={() => removeView(i)}>×</button>
        </div>
      ))}
      <button className="as-add-view" onClick={addView} disabled={!holdings.length}>+ 뷰 추가</button>
    </div>
  );
}
