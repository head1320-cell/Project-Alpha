"use client";
// shadcn/ui Popover — 손으로 작성한 벤더링본. Radix Popover 조합.
//
// Dialog(같은 폴더)와 같은 이유로 **document.body 로 포털**된다. 컨테이너로 범위를 좁힌
// Playwright 단언은 포털된 내용을 놓치므로, 이걸 쓰는 스펙은 page 루트에서 단언해야 한다
// (e2e/radix-dialogs.spec.ts 가 Dialog 에 대해 세운 선례와 같다).
//
// Dialog 와 달리 오버레이가 없다 — Popover 는 모달이 아니고, 바깥을 가리지 않는다.
// 그래서 "근거를 펼쳐 두고 옆의 수치를 함께 읽는" 동작이 가능하다. 경고를 여기 넣지 않는
// 이유이기도 하다: 닫혀 있으면 보이지 않는다.
import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "@/shared/lib/cn";

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;
const PopoverAnchor = PopoverPrimitive.Anchor;
const PopoverClose = PopoverPrimitive.Close;

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = "start", sideOffset = 6, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref} align={align} sideOffset={sideOffset}
      className={cn("shad-popover", className)} {...props} />
  </PopoverPrimitive.Portal>
));
PopoverContent.displayName = "PopoverContent";

export { Popover, PopoverTrigger, PopoverAnchor, PopoverClose, PopoverContent };
