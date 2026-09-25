"use client";
// /allocation/wizard = 마법사 진입점(목표 선택 게이트). BI4 에서 `/allocation` 에서 옮겼다 —
// `/allocation` 은 이제 노드 캔버스다(ADR 002). 공유 크롬(트래커/하단 nav) 없이 bare 렌더 —
// layout.tsx 의 분기가 처리. Overview 대시보드는 /allocation/overview.
import React from "react";
import { GoalGate } from "@/widgets/allocation/GoalGate";

export default function AllocationGatePage() {
  return <GoalGate />;
}
