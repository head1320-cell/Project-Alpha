"use client";
// Execution Readiness Workspace (Full Expansion P4) — 실행 준비실.
// 목표 배분으로의 리밸런싱 주문 diff·비용·pre-trade·승인 워크플로.
// v1 범위: paper portfolio·rebalance preview·execution plan·approval workflow.
// 실 주문·계좌 제어·자동매매는 v1 범위 밖 (지시서).
import React from "react";
import { ExecutionRoom } from "@/components/allocation/ExecutionRoom";

export default function ExecutionWorkspace() {
  return <ExecutionRoom />;
}
