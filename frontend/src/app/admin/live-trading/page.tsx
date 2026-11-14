import { Suspense } from "react";
import { LiveTradingView } from "@/widgets/live-trading/LiveTradingView";

export const metadata = {
  title: "실거래",
  description: "운영 계좌의 주문 전송 경로를 확인하고, 주문을 중단하고, 실계좌 관문을 관리합니다",
};

/** /admin/live-trading (BU9b · ST3b 탭) — 화면은 `widgets/live-trading/LiveTradingView`. `?tab=` 를 읽으므로 Suspense 로 감싼다. */
export default function LiveTradingPage() {
  return <Suspense fallback={null}><LiveTradingView /></Suspense>;
}
