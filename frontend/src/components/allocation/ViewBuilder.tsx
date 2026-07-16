"use client";
// INVESTMENT THESIS — 사용자 뷰(Black-Litterman) 빌더.
// 각 뷰: 대상 자산(들) · 방향 · 크기(연 %) · 신뢰도 슬라이더 0~100.
// 슬라이더 드래그 중엔 로컬 상태만(백엔드 호출 0), 릴리스(커밋) 시 onCommit —
// Gemini 아키텍처 리뷰 ②(틱마다 솔버 호출 금지) 반영.
import React from "react";
import type { AllocationViewInput } from "@/lib/allocationApi";
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
        <div key={i} className="as-view">
          <div className="as-view-top">
            <input className="as-input as-view-label" placeholder={`테제 ${i + 1} (예: 반도체가 시장을 상회할 것)`}
              value={v.label || ""} onChange={(e) => patch(i, { label: e.target.value })} onBlur={onCommit} />
            <button className="as-x" title="뷰 삭제" onClick={() => removeView(i)}>×</button>
          </div>
          <div className="as-view-assets">
            {holdings.map((h) => (
              <button key={h.code} className={`as-chip${v.assets.includes(h.code) ? " on" : ""}`}
                onClick={() => { toggleAsset(i, h.code); }} onBlur={onCommit} title={h.code}>
                {h.name}
              </button>
            ))}
          </div>
          <div className="as-view-ctrl">
            <div className="as-seg">
              <button className={v.direction === 1 ? "on" : ""} onClick={() => { patch(i, { direction: 1 }); onCommit(); }}>▲ 상회</button>
              <button className={v.direction === -1 ? "on" : ""} onClick={() => { patch(i, { direction: -1 }); onCommit(); }}>▼ 하회</button>
            </div>
            <label className="as-mini">크기
              <input className="as-w-input num" type="number" min={0.5} max={30} step={0.5} value={v.magnitude_pct}
                onChange={(e) => patch(i, { magnitude_pct: parseFloat(e.target.value) || 0 })} onBlur={onCommit} />
              <span className="as-w-unit">%/년</span>
            </label>
            <label className="as-conf">
              <span className="as-mini">신뢰도 <b className="num">{Math.round(v.confidence)}%</b></span>
              <input type="range" min={0} max={100} step={5} value={v.confidence}
                onChange={(e) => patch(i, { confidence: parseFloat(e.target.value) })}
                onMouseUp={onCommit} onTouchEnd={onCommit} onKeyUp={onCommit} />
            </label>
          </div>
        </div>
      ))}
      <button className="as-add-view" onClick={addView} disabled={!holdings.length}>+ 뷰 추가</button>
    </div>
  );
}
