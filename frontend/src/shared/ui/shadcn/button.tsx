"use client";
// shadcn/ui Button — **손으로 작성한 벤더링본**.
//
// 왜 CLI 가 아닌가: 이 환경의 에이전트 프록시가 ui.shadcn.com 을 403 CONNECT 로 거부한다
// (npm 레지스트리만 허용). 그래서 shadcn 의 공개 구조·API 를 그대로 따라 직접 작성했다.
// components.json 은 그대로 두었으니 호스트가 허용되면 `shadcn add button` 이 이 파일을
// 덮어써도 계약이 같다: cva variants + asChild(Slot) + forwardRef + cn().
//
// 색은 hex 를 복제하지 않고 globals.css §34 브릿지의 var() 를 참조한다 —
// 디자인 토큰의 단일 진실은 계속 --t-* 다.
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/shared/lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius)] " +
    "text-[13px] font-medium transition-colors " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-1 " +
    "disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90",
        secondary:
          "bg-[var(--secondary)] text-[var(--secondary-foreground)] border border-[var(--border)] hover:border-[var(--ring)]",
        outline:
          "border border-[var(--border)] bg-transparent text-[var(--foreground)] hover:border-[var(--ring)] hover:text-[var(--primary)]",
        ghost:
          "bg-transparent text-[var(--foreground)] hover:bg-[var(--muted)]",
        destructive:
          "bg-[var(--destructive)] text-[var(--destructive-foreground)] hover:opacity-90",
        link:
          "bg-transparent text-[var(--primary)] underline-offset-4 hover:underline",
      },
      // 데이터 밀도 우선 — shadcn 기본값보다 한 단계 조였다(터미널 UI 와 맞추기 위해).
      size: {
        sm: "h-7 px-2.5 text-[12px]",
        default: "h-8 px-3",
        lg: "h-9 px-4",
        icon: "h-8 w-8 p-0",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** true 면 자식 요소에 스타일을 넘긴다(<Link> 등을 버튼처럼 쓸 때). */
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
