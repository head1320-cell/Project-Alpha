"use client";
// shadcn/ui Dialog — 손으로 작성한 벤더링본. Radix Dialog 조합.
//
// ★이 파일이 Phase 5 에 포함된 이유★
// Radix 는 Overlay/Content 를 **document.body 로 포털**한다 — 컴포넌트의 DOM 서브트리 밖이다.
// 컨테이너로 범위를 좁힌 Playwright 단언(e2e/dev-ui.spec.ts 는 .devui 루트로 스코프한다)은
// 포털된 내용을 놓친다. ADR 001 이 이 위험을 명시했고, Phase 6 의 모달 4개 통합 전에
// 지금 한 번 드러내 두려고 Dialog 를 스캐폴드에 넣었다.
//
// 스타일은 globals.css §34 의 .shad-overlay / .shad-content 를 쓴다 — 포털 대상이
// Tailwind content 스캔 범위 밖이 아니라, 오버레이가 앱 컨테이너 밖에서 스타일되어야 하므로
// 클래스로 고정하는 편이 예측 가능하다.
import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/shared/lib/cn";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogPortal = DialogPrimitive.Portal;
const DialogClose = DialogPrimitive.Close;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay ref={ref} className={cn("shad-overlay", className)} {...props} />
));
DialogOverlay.displayName = "DialogOverlay";

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content ref={ref} className={cn("shad-content", className)} {...props}>
      {children}
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = "DialogContent";

function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-3 flex flex-col gap-1", className)} {...props} />;
}

function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mt-4 flex justify-end gap-2", className)} {...props} />;
}

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref}
    className={cn("text-[14px] font-semibold text-[var(--foreground)]", className)} {...props} />
));
DialogTitle.displayName = "DialogTitle";

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description ref={ref}
    className={cn("text-[12px] text-[var(--muted-foreground)]", className)} {...props} />
));
DialogDescription.displayName = "DialogDescription";

export {
  Dialog, DialogTrigger, DialogPortal, DialogClose, DialogOverlay,
  DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription,
};
