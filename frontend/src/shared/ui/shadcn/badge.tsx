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
