"use client";

import TerminalBacktester from "@/components/backtest/TerminalBacktester";

// Backtester — 젠포트식 단일 화면: 매수 조건 / 매도 조건 / 매매 대상
// (전략 설계 빌더는 /builder 라우트에서 계속 사용 가능)
export default function BacktestPage() {
  return <TerminalBacktester />;
}
