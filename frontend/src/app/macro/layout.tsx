"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// /macro 레이아웃 — 제목 + 스튜디오 내비 (M1-U → BU5a · BU5a+)
// ─────────────────────────────────────────────────────────────────────────────
// `/macro` 를 **국면·매크로 지능 브레인**으로 만드는 껍데기. 예전엔 케이스 줄(CaseBar)이
// 여기 있었다 — 캔버스와 같은 부품으로 "같은 연구"를 말하려던 것. BU5a+ 에서 사용자 지시로 걷었고
// 케이스는 캔버스 케이스 칸(`app/allocation/page.tsx`)에서 고르고 만든다.
// ═══════════════════════════════════════════════════════════════════════════════
// BU5a — 순서: (매크로 분석 첫 화면만) 제목 → 스튜디오 줄 → 화면. 제목이 내비 아래에 있으면 무엇을 보는 화면인지가
// 늦게 읽힌다. 스튜디오 화면은 경로 머리(Breadcrumb "매크로 분석 › 잠재 요인")와 자기 머리가 있어 여기서 제목을 또 달지 않는다(h1 하나).
import React from "react";
import { usePathname } from "next/navigation";
import { StudioNav } from "@/widgets/macro/StudioNav";
import { PageHead } from "@/shared/ui/tx";

export default function MacroLayout({ children }: { children: React.ReactNode }) {
  const root = usePathname() === "/macro";
  return (
    <div className={`ms-root${root ? " ms-root--home" : ""}`}>
      {root && <PageHead title="매크로 분석" lede="경기와 물가가 어느 쪽으로 가는지 봐요." />}
      <StudioNav />
      {children}
    </div>
  );
}
