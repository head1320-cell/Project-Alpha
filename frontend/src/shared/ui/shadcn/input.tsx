// shadcn/ui Input — 손으로 작성한 벤더링본 (card.tsx·button.tsx 헤더의 이유와 동일).
// Radix 의존이 없는 순수 유틸리티 컴포넌트다.
//
// ★상류의 h-10 을 쓰지 않는다★ card.tsx 와 같은 이유 — 밀도가 이 제품의 요구사항이다.
// 상류 기본은 `h-10 px-3 py-2 text-sm`(40px). 자산 20개의 비중을 세로로 쌓는 화면에서
// 40px 행은 화면 한 폭을 입력창으로 버린다. 기본을 h-8(32px)로 정하고, 넓히고 싶은
// 소비처가 생기면 그때 className 으로 늘린다.
//
// ★숫자 입력의 스피너를 지우지 않는다★ `.as-w-input`(globals.css:3288)은
// -webkit-appearance:none 으로 스피너를 죽였는데, 그러면 마우스만 쓰는 사용자에게
// 미세 조정 수단이 사라진다. 여기서는 스피너를 두고, 비중 편집에는 Slider 를 짝지어
// 준다(A3 S3b) — 조정 수단을 빼앗지 않고 늘리는 쪽이다.
import * as React from "react";
import { cn } from "@/shared/lib/cn";

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-8 w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--background)]",
        "px-2.5 py-1 text-[12px] text-[var(--foreground)]",
        "placeholder:text-[var(--muted-foreground)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-1",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input };
