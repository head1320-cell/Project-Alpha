"use client";
// shadcn/ui ToggleGroup — 손으로 작성한 벤더링본 (CLI 차단 사유는 button.tsx 헤더 참조).
//
// 왜 Tabs 가 아니라 ToggleGroup 인가
// ─────────────────────────────────────────────────────────────────────────────
// 카탈로그 창의 "패밀리" 선택은 탭 패널 전환이 아니라 **목록을 좁히는 단일선택 필터**다
// (StressScenarioModal/AlphaFactorModal 둘 다 같은 목록에 필터만 바꿔 끼운다).
// Radix Tabs 를 쓰면 tabpanel 시맨틱을 약속하게 되는데 실제 구조가 그렇지 않다.
// ToggleGroup(type="single") 이 의미가 맞고, **roving focus + 화살표 키**를 공짜로 준다 —
// 스펙 §8.1 의 "keyboard navigation" 요구가 이걸로 충족된다.
//
// 기존 .tfm-fams 는 순수 <button> 이라 키보드로 그룹 내 이동이 불가능했다.
import * as React from "react";
import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";
import { cn } from "@/shared/lib/cn";

const ToggleGroup = React.forwardRef<
  React.ElementRef<typeof ToggleGroupPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Root>
>(({ className, ...props }, ref) => (
  <ToggleGroupPrimitive.Root ref={ref} className={cn("flex flex-wrap gap-1", className)} {...props} />
));
ToggleGroup.displayName = "ToggleGroup";

const ToggleGroupItem = React.forwardRef<
  React.ElementRef<typeof ToggleGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Item>
>(({ className, ...props }, ref) => (
  <ToggleGroupPrimitive.Item
    ref={ref}
    className={cn(
      "inline-flex items-center rounded-[var(--radius)] border border-[var(--border)] " +
        "bg-transparent px-2 py-1 text-[11px] text-[var(--foreground)] transition-colors " +
        "hover:border-[var(--ring)] " +
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] " +
        // 선택 상태 — Radix 가 data-state="on" 을 준다
        "data-[state=on]:border-[var(--primary)] data-[state=on]:bg-[var(--primary)] " +
        "data-[state=on]:text-[var(--primary-foreground)]",
      className,
    )}
    {...props}
  />
));
ToggleGroupItem.displayName = "ToggleGroupItem";

export { ToggleGroup, ToggleGroupItem };
