"use client";
// /allocation = 위저드 진입점(목표 선택 게이트). 공유 크롬(트래커/하단 nav) 없이
// bare 렌더 — layout.tsx의 isGate 분기가 처리. Overview 대시보드는 /allocation/overview.
import React from "react";
import { GoalGate } from "@/components/allocation/GoalGate";

export default function AllocationGatePage() {
  return <GoalGate />;
}
