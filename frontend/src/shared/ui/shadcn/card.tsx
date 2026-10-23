// shadcn/ui Card — 손으로 작성한 벤더링본 (badge.tsx·button.tsx 헤더의 이유와 동일).
// Radix 의존이 없는 순수 유틸리티 컴포넌트라 번들 비용이 사실상 cva + 클래스 문자열뿐이다.
//
// ★상류 기본값을 그대로 쓰지 않는다 — 밀도가 이 제품의 요구사항이다★
// shadcn 기본 Card 는 CardHeader/CardContent 에 `p-6`(24px)을 준다. 지표를 빽빽하게 읽는
// 리서치 화면에서 그 값은 카드 네 장만 놓아도 화면 한 폭을 여백으로 버린다.
// 흔한 대응은 소비처마다 `p-6` 을 `p-3` 으로 덮는 것인데, 그러면
//   ① 같은 의도가 파일마다 흩어지고,
//   ② Tailwind 유틸리티끼리 경쟁하면서 CSS 특이도 충돌이 늘어난다
//      (tests/test_css_specificity_guard.py 의 KNOWN_COLLISIONS 22건이 전부 그 유형이다).
// 그래서 **덮지 않고 처음부터 조인 값으로 정의한다.** 넓히고 싶은 소비처가 생기면 그때
// className 으로 늘리면 된다 — 기본값이 조밀한 쪽이 이 저장소에서는 옳은 기본값이다.
//
// 색은 §34 토큰 브릿지를 참조한다. 우리 토큰은 hex 라서 shadcn 관례인 hsl(var(--x)) 가
// 성립하지 않는다 — bg-[var(--card)] 형태로 직접 쓴다(§34 주석에 이유가 적혀 있다).

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/shared/lib/cn";

/**
 * ★asChild 를 둔 이유★ (A2a)
 * 카드 전체가 클릭 대상인 화면이 있다(목표 게이트의 프리셋 카드). 그때 `<div>` 인 Card 를
 * 그대로 쓰면 셋 중 하나를 골라야 한다:
 *   ① div 에 onClick — 탭으로 닿지 않고 Enter/Space 도 안 먹는다(직접 구현해야 한다),
 *   ② 카드 안에 버튼 — 클릭 영역이 카드가 아니라 버튼만큼으로 줄어든다,
 *   ③ 버튼 안에 카드 — 버튼 안에 버튼이 생길 수 있고 시맨틱이 뒤집힌다.
 * Slot 으로 자식에게 클래스를 넘기면 DOM 노드가 **진짜 `<button>`** 이 된다 —
 * 탭 스톱 하나, Enter/Space 무료, `:disabled` 동작, 그리고 기존 `.aas-goal` 클래스 유지.
 * Button 이 이미 같은 계약을 쓰고 있고(button.tsx), @radix-ui/react-slot 은 이미 의존성이다.
 * 기본값은 false 라 기존 소비처는 한 글자도 바뀌지 않는다.
 */
export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  asChild?: boolean;
}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "div";
    return (
      <Comp
        ref={ref}
        className={cn(
          "rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)]",
          className,
        )}
        {...props}
      />
    );
  },
);
Card.displayName = "Card";

/** 헤더는 본문보다 한 단계 더 조인다 — 제목 한 줄에 24px 을 쓸 이유가 없다. */
const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex flex-col gap-0.5 border-b border-[var(--border)] px-3 py-2", className)}
      {...props}
    />
  ),
);
CardHeader.displayName = "CardHeader";

/**
 * 상류는 `<h3>` 로 고정돼 있다. 여기서는 `as` 로 레벨을 고를 수 있게 했다 — 상류와 다른
 * 유일한 지점이고, 이유가 있다: 카드가 페이지의 최상위 구획이면 `<h1>` 다음은 `<h2>` 여야
 * 하는데, 고정된 h3 는 레벨을 건너뛴다. 스크린리더의 헤딩 목록이 이 페이지의 목차라서
 * 건너뛴 레벨은 "빠진 항목"으로 읽힌다. 기본값은 상류와 같은 h3 로 둔다.
 */
type CardTitleTag = "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
export interface CardTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
  as?: CardTitleTag;
}
const CardTitle = React.forwardRef<HTMLHeadingElement, CardTitleProps>(
  ({ className, as: Tag = "h3", ...props }, ref) => (
    <Tag
      ref={ref}
      className={cn("text-sm font-semibold leading-tight tracking-tight", className)}
      {...props}
    />
  ),
);
CardTitle.displayName = "CardTitle";

const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn("text-xs leading-snug text-[var(--muted-foreground)]", className)} {...props} />
  ),
);
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("p-3", className)} {...props} />
  ),
);
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex items-center gap-2 border-t border-[var(--border)] px-3 py-2", className)}
      {...props}
    />
  ),
);
CardFooter.displayName = "CardFooter";

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter };
