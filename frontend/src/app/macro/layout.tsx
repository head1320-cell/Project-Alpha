"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// /macro 레이아웃 — 케이스 컨텍스트 + 스튜디오 내비 (M1-U)
// ─────────────────────────────────────────────────────────────────────────────
// `/macro` 를 **국면·매크로 지능 브레인**으로 만드는 껍데기. 루트(`/macro`)의
// MacroCockpit 3탭은 **한 글자도 건드리지 않는다** — `.mc-*` 는 15개 스펙의 계약이다.
//
// CaseBar 는 `/allocation/*` 크롬과 **같은 컴포넌트**다. 두 화면을 잇는 것은 링크가
// 아니라 같은 케이스를 보고 있다는 사실이고, 그 사실을 양쪽이 같은 말로 해야 한다.
// 여기서는 `sessionSnapshotId` 를 넘기지 않는다 — `/macro` 에는 AAS 세션 스냅샷 개념이
// 없으므로, 없는 것을 있는 척 비교하지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import { CaseBar } from "@/features/case-bar/CaseBar";
import { StudioNav } from "@/widgets/macro/StudioNav";

export default function MacroLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="ms-root">
      <CaseBar />
      <StudioNav />
      {children}
    </div>
  );
}
