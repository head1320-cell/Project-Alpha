"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// Slider — shadcn API 모양, 네이티브 `<input type="range">` 구현
// ─────────────────────────────────────────────────────────────────────────────
// ★계획은 @radix-ui/react-slider 를 쓰기로 했다. 재 보고 취소했다★
//
// 계획에 적은 근거는 "Radix 는 aria-valuenow/min/max 와 방향키·Home/End 를 이미 갖고
// 있어서 테스트가 aria 로 물어볼 수 있다" 였다. **그 근거가 틀렸다.**
// 네이티브 range 입력은 UA 가 role=slider 와 aria-valuenow/min/max 를 접근성 트리에
// 직접 반영하고, 방향키·Home/End·PageUp/Down·포인터 드래그가 전부 기본 동작이다.
// Radix 가 그 위에 얹어 주는 것은 커스텀 렌더링뿐이고, 이 화면은 그게 필요 없다.
//
// 실측 (next build, First Load JS):
//   /allocation/construct  Radix 261 kB → 네이티브 251 kB   (-10 kB)
//   /dev/ui                Radix 138 kB → 네이티브 131 kB   (-7 kB)
// 접근성이 같고 10 kB 가 싸면 고를 것이 없다. `@radix-ui/react-slider` 는 제거했다.
//
// API 는 shadcn 모양(`value: number[]` · `onValueChange`)을 유지한다 — 나중에 범위
// 슬라이더(손잡이 2개)가 필요해져서 Radix 로 갈아타더라도 소비처를 안 고치기 위해서다.
// 외형은 §51 의 `.as-range` 가 담당한다(::-webkit-slider-thumb 는 유틸리티로 못 쓴다).
// ═══════════════════════════════════════════════════════════════════════════════
import * as React from "react";
import { cn } from "@/shared/lib/cn";

export interface SliderProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> {
  /** 단일 손잡이라 항상 길이 1. 배열인 것은 shadcn/Radix 계약을 맞추기 위해서다. */
  value: number[];
  onValueChange?: (value: number[]) => void;
}

const Slider = React.forwardRef<HTMLInputElement, SliderProps>(
  ({ className, value, min = 0, max = 100, step = 1, onValueChange, ...props }, ref) => (
    <input
      ref={ref}
      type="range"
      className={cn("as-range", className)}
      min={min}
      max={max}
      step={step}
      value={value[0]}
      onChange={(e) => onValueChange?.([parseFloat(e.target.value)])}
      {...props}
    />
  ),
);
Slider.displayName = "Slider";

export { Slider };
