// shadcn/ui Badge — 손으로 작성한 벤더링본 (button.tsx 헤더의 이유와 동일).
// 클래스 없는 순수 유틸리티 컴포넌트라 Radix 의존이 없다.
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/shared/lib/cn";

const badgeVariants = cva(
  "inline-flex items-center rounded-[var(--radius)] border px-2 py-0.5 text-[10px] " +
    "font-medium leading-tight transition-colors",
  {
    variants: {
      variant: {
        default:     "border-transparent bg-[var(--primary)] text-[var(--primary-foreground)]",
        secondary:   "border-[var(--border)] bg-[var(--secondary)] text-[var(--secondary-foreground)]",
        outline:     "border-[var(--border)] bg-transparent text-[var(--foreground)]",
        destructive: "border-transparent bg-[var(--destructive)] text-[var(--destructive-foreground)]",

        // ── A9 추가 — ContextStrip 이 손으로 굴리던 상태 칩을 여기로 모은다 ──
        // ★`--color-caution`(#d97706)을 글자색으로 쓰지 않는다★ 흰 배경 3.18:1 로 AA 미달이고,
        // §56 이 `.as-ctx-stale` 에서 이미 같은 이유로 #854d0e 로 갈아 끼웠다(틴트 위 6.15:1).
        // 그래서 "칠하는 앰버"와 "읽는 앰버"를 토큰 두 개로 나눠 §59 에 정의했다.
        // (Phase 1 의 --warn-fg / --warn-mark 분리가 승인되면 그쪽이 이것을 대체한다.)
        warn:    "border-[var(--st-warn-bd)] bg-[var(--st-warn-bg)] text-[var(--st-warn-fg)]",
        bull:    "border-[var(--st-bull-bd)] bg-[var(--st-bull-bg)] text-[var(--st-bull-fg)]",
        bear:    "border-[var(--st-bear-bd)] bg-[var(--st-bear-bg)] text-[var(--st-bear-fg)]",
        neutral: "border-[var(--border)] bg-transparent text-[var(--muted-foreground)]",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
