"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// WeightRow — 자산 한 줄의 비중 편집 컨트롤 (A3 S3b)
// ─────────────────────────────────────────────────────────────────────────────
// 숫자 Input + Slider + 삭제 버튼. 예전에는 `<input type="number">` 하나뿐이라
// 비중을 "고치려면" 항상 숫자를 타이핑해야 했고, 비율 감각은 화면 어디에도 없었다.
//
// ★두 컨트롤이 **한 값**을 공유한다★
// Input 과 Slider 가 각자 state 를 들면 반드시 어긋난다 — 반올림 시점이 다르고,
// 한쪽만 onBlur 로 커밋하면 다른 쪽이 낡는다. 그래서 둘 다 props 의 `weight` 를 읽고
// 둘 다 같은 `onWeight` 를 부른다. 로컬 state 는 없다. 어긋날 자리를 만들지 않는 편이
// "동기화 코드를 잘 짜는" 것보다 낫다 — A1 에서 서명 리터럴 두 개가 어긋났던 것과 같은 교훈.
//
// ★삭제 버튼에 이름을 준다★ 아이콘만 있는 버튼은 스크린리더에서 "버튼"으로만 읽힌다.
// 어느 자산을 지우는 버튼인지 종목명을 넣어 말해 준다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/shared/ui/shadcn/button";
import { Input } from "@/shared/ui/shadcn/input";
import { Slider } from "@/shared/ui/shadcn/slider";

export interface WeightRowProps {
  code: string;
  name: string;
  weight: number;
  onWeight: (code: string, w: number) => void;
  onRemove: (code: string) => void;
}

/** 0~100 으로 자르고 소수 1자리로 맞춘다 — Input 과 Slider 가 같은 함수를 통과한다. */
export function clampWeight(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return Math.round(Math.max(0, Math.min(100, v)) * 10) / 10;
}

export function WeightRow({ code, name, weight, onWeight, onRemove }: WeightRowProps) {
  const set = (v: number) => onWeight(code, clampWeight(v));

  return (
    // `.as-wrow` 는 E2E 계약이라 유지하고, 레이아웃 전용 수식자를 따로 붙인다 —
    // 같은 이름을 overview·timing 이 **다른 구조**로 쓰고 있기 때문이다(A4).
    <div className="as-holding as-wrow as-wrow-edit">
      <span className="as-holding-nm" title={code}>{name}</span>

      <Input
        className="as-w-input num"
        type="number"
        min={0}
        max={100}
        step={0.5}
        value={weight}
        aria-label={`${name} 비중 (%)`}
        onChange={(e) => set(parseFloat(e.target.value))}
      />
      <span className="as-w-unit">%</span>

      <Button
        variant="ghost"
        size="icon"
        className="as-wrow-del"
        aria-label={`${name} 제거`}
        onClick={() => onRemove(code)}
      >
        <Trash2 size={14} aria-hidden="true" />
      </Button>

      {/* 슬라이더는 이름과 입력 아래 전폭으로 — 좁은 레일에서 한 줄에 넣으면 둘 다 못 쓴다.
          aria-label 이 Input 과 같은 이름이면 스크린리더 목록에 같은 항목이 두 번 뜬다.
          그래서 여기만 "슬라이더"임을 밝힌다. */}
      <Slider
        className="as-wrow-slider"
        value={[weight]}
        min={0}
        max={100}
        step={0.5}
        aria-label={`${name} 비중 슬라이더 (%)`}
        onValueChange={([v]) => set(v)}
      />
    </div>
  );
}
