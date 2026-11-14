import { IntradayView } from "@/widgets/intraday/IntradayView";

export const metadata = {
  title: "백테스트 · 분봉 규칙",
  description: "정한 규칙을 과거 분봉에서 돌려 모의 체결을 집계하고 그 숫자를 어디까지 읽을 수 있는지 관문으로 점검합니다",
};

/** /backtest/intraday (백테스트 › 분봉 규칙) — 화면은 `widgets/intraday`. 따로 있던 `/intraday` 가 여기로 왔다(ADR 006 §7). */
export default function BacktestIntradayPage() {
  return <IntradayView />;
}
