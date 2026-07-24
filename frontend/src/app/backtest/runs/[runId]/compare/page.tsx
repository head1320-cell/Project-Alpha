"use client";
// 백테스트 실행 비교 페이지 — 고정 URL, 실행 A(현재) vs 실행 B(선택) 나란히 비교.
import React from "react";
import { useParams } from "next/navigation";
import { BacktestCompare } from "@/components/backtest/BacktestCompare";

export default function BacktestComparePage() {
  const params = useParams();
  return <BacktestCompare runId={String(params.runId)} />;
}
