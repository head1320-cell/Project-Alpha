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
// BU5a — 순서: (경제 흐름 첫 화면만) 제목 → 스튜디오 줄 → 케이스 줄 → 화면. 제목이 내비 아래에 있으면 무엇을 보는 화면인지가
// 늦게 읽힌다. 스튜디오 화면은 경로 머리(Breadcrumb "경제 흐름 › 잠재 요인")와 자기 머리가 있어 여기서 제목을 또 달지 않는다(h1 하나).
import React from "react";
import { usePathname } from "next/navigation";
import { CaseBar } from "@/features/case-bar/CaseBar";
import { StudioNav } from "@/widgets/macro/StudioNav";
import { PageHead } from "@/shared/ui/tx";

export default function MacroLayout({ children }: { children: React.ReactNode }) {
  const root = usePathname() === "/macro";
  return (
    <div className={`ms-root${root ? " ms-root--home" : ""}`}>
      {root && <PageHead title="경제 흐름" lede="경기와 물가가 어느 쪽으로 가는지 봐요." />}
      <StudioNav />
      <CaseBar />
      {children}
    </div>
  );
}
