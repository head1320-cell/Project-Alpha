"use client";
// ArchiveDrawer 의 Radix 부분 — `next/dynamic` 으로 떼어내려고 분리했다.
//
// ★왜 분리하는가 (측정)★
// ArchiveDrawer 를 `@radix-ui/react-dialog` 로 바로 만들었더니 그 라우트들에 Radix Dialog
// 가 **처음** 들어가면서 alphalab 141 → 152 kB, journal 229 → 250 kB 였다. ADR 001 의
// 라우트당 4 kB 를 5배 넘긴다.
//
// 서랍은 **닫힌 채로 시작**한다 — 첫 페인트에 필요한 것은 트리거 버튼 하나뿐이다.
// ADR 001 개정판이 정확히 이 경우를 허용한다: "닫힌 채 시작하는 표면은 next/dynamic 과
// 함께라면 Radix 를 채택해도 된다." Phase A 가 WatchGroupModal·StrategyModal 에서 쓴
// 방법이고 ResearchIndexLists 가 같은 이유로 갈라져 있다.
import React from "react";
import {
  Dialog, DialogClose, DialogContent, DialogTitle,
} from "@/shared/ui/shadcn/dialog";

export default function ArchiveDrawerPanel({
  open, onOpenChange, title, hint, children, onCloseAutoFocus,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
  /** 닫힌 뒤 포커스를 어디로 돌릴지 — 호출자가 정한다. 아래 주석 참고. */
  onCloseAutoFocus?: (e: Event) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* ★닫기-자동포커스를 Radix 에게 맡기면 포커스가 body 로 떨어진다★
          이 패널은 `next/dynamic` 으로 떼어져 있어 **트리거를 누르는 시점에 Dialog 가
          아직 존재하지 않는다**. 그래서 Radix 가 "열기 전에 포커스가 있던 곳" 으로
          기억하는 대상이 트리거가 아니고, Escape 로 닫으면 포커스가 문서 처음으로
          떨어진다 — 키보드 사용자는 목록을 처음부터 다시 Tab 해야 한다.
          `WatchGroupModal.tsx:129` 가 같은 이유로 같은 처리를 하고 있고, 이쪽은
          되돌릴 대상(트리거)까지 알고 있으므로 복귀까지 호출자가 맡는다. */}
      <DialogContent className="as-arch" onCloseAutoFocus={onCloseAutoFocus}>
        <div className="as-arch-head">
          <DialogTitle className="as-arch-title">{title}</DialogTitle>
          {hint && <span className="as-arch-hint">{hint}</span>}
          <DialogClose className="as-arch-x" aria-label={`${title} 닫기`}>×</DialogClose>
        </div>
        <div className="as-arch-body">{children}</div>
      </DialogContent>
    </Dialog>
  );
}
