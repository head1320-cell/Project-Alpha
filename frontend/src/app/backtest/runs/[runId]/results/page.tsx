"use client";
// 백테스트 결과 페이지 — 고정 URL, 새로고침·북마크·재방문 가능한 전용 분석 워크스페이스.
import React from "react";
import { useParams } from "next/navigation";
import { BacktestResults } from "@/components/backtest/BacktestResults";

export default function BacktestResultsPage() {
  const params = useParams();
  return <BacktestResults runId={String(params.runId)} />;
}
