"use client";
// 백테스트 실행 로딩 페이지 — 전용 잡 모니터. run_id 상태를 폴링하고 완료 시 결과 페이지로.
import React from "react";
import { useParams } from "next/navigation";
import { RunMonitor } from "@/widgets/backtester/RunMonitor";

export default function BacktestLoadingPage() {
  const params = useParams();
  const runId = String(params.runId);
  return <RunMonitor runId={runId} />;
}
