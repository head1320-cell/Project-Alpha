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
  open, onOpenChange, title, hint, children,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="as-arch">
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
