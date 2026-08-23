// shadcn/ui Progress — Radix 없이 작성한 벤더링본(div + role="progressbar" + aria-*).
// 상류는 @radix-ui/react-progress 를 쓰지만, 이 컴포넌트가 하는 일은 폭 계산과 aria 4개가
// 전부라 의존성을 추가할 이유가 없다. Slider 는 키보드 상호작용 때문에 Radix 를 썼다 —
// 여기는 상호작용이 없다.
//
// ═══════════════════════════════════════════════════════════════════════════════
// ★"Progress 프리미티브를 만들지 말라"던 결정과 모순되지 않는다★
// 계획 v2 §7 은 일반 Progress 를 **거부**했다. 이유는 명시적이었다: 진행률 바는
// "엔진이 산출하지 않는 백분율"이 있는 것처럼 보이게 만들고, 그러면 다른 화면에서도
// 가짜 퍼센트를 붙이고 싶어진다. 그 판단은 지금도 유효하다.
//
// 이 소비처는 정반대 경우다. 여기서 그리는 값은 **사용자가 직접 입력한 비중의 합**이다.
// 클라이언트에서 정확히 계산되고, 추정이 개입할 자리가 없으며, 100% 라는 목표값이
// 도메인에 실재한다(포트폴리오 비중 합). 즉 "모르는 진행률을 아는 척"하는 것이 아니라
// "아는 합계를 그리는" 것이다.
//
// 그래서 규칙은 이렇게 남는다: 값이 **측정된 것**이면 Progress 를 써도 된다.
// 값이 추정·경과시간·단계 수에서 나온 것이면 쓰지 말고 단계 목록을 써라(§7 의 원래 결론).
// 이 주석이 없으면 두 결정이 서로 모순돼 보이므로 반드시 남긴다.
// ═══════════════════════════════════════════════════════════════════════════════
import * as React from "react";
import { cn } from "@/shared/lib/cn";

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 현재 값. null 이면 "측정되지 않음" — 0 과 구별해서 바를 그리지 않는다. */
  value: number | null;
  /** 100% 기준값. 비중 합계는 100 이 목표다. */
  max?: number;
  /** 스크린리더용 이름. role="progressbar" 는 이름 없이는 무의미하다. */
  label: string;
  /** 목표를 벗어난 상태(예: 합계 ≠ 100) — 색만이 아니라 클래스로도 구분된다. */
  tone?: "default" | "warn";
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value, max = 100, label, tone = "default", ...props }, ref) => {
    const known = value != null && Number.isFinite(value);
    const pct = known ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        // ★미계산이면 aria-valuenow 를 아예 붙이지 않는다★ 0 을 넣으면 스크린리더가
        // "0퍼센트"라고 읽는다 — 이 저장소에서 0 ≠ 미계산 이다.
        aria-valuenow={known ? value : undefined}
        data-tone={tone}
        className={cn(
          "relative h-1.5 w-full overflow-hidden rounded-full bg-[var(--secondary)]",
          className,
        )}
        {...props}
      >
        {known && (
          <div
            className={cn(
              "h-full transition-[width] duration-150",
              tone === "warn" ? "bg-[var(--destructive)]" : "bg-[var(--primary)]",
            )}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
    );
  },
);
Progress.displayName = "Progress";

export { Progress };
