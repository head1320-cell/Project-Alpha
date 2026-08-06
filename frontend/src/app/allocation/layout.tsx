"use client";
// Allocation Studio 라우트 레이아웃 — **조립만 한다**.
// 크롬 자체(인텐트·컨텍스트 스트립·스테퍼·신선도 배너·하단 nav)는
// `widgets/allocation/StageChrome` 로 옮겼다(A1a): 라우트 파일 안의 private function 이라
// import 도 테스트도 되지 않던 것을, 앞으로 매 스텝이 손대는 이음매이므로 꺼냈다.
// layout 이 Provider 를 들고 있는 것은 그대로 — App Router 에서 layout 은 자식 라우트
// 전환에도 유지되므로 게이트 ↔ 각 스테이지 이동 시 상태가 증발하지 않는다.
import React from "react";
import { usePathname } from "next/navigation";
import { AllocationProvider } from "@/widgets/allocation/AllocationProvider";
import { StageChrome } from "@/widgets/allocation/StageChrome";

function LayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // 게이트(/allocation)는 크롬 없이 bare 렌더 (page.tsx가 GoalGate를 렌더) — Provider 안이라
  // 게이트에서 세팅한 시드가 상태로 유지되어 Construct로 그대로 이어짐.
  if (pathname === "/allocation") return <>{children}</>;
  return <StageChrome>{children}</StageChrome>;
}

export default function AllocationLayout({ children }: { children: React.ReactNode }) {
  return (
    <AllocationProvider>
      <LayoutInner>{children}</LayoutInner>
    </AllocationProvider>
  );
}
