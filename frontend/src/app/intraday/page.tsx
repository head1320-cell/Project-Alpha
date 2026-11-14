import { IntradayView } from "@/widgets/intraday/IntradayView";

export const metadata = {
  title: "분봉 백테스트",
  description: "정한 규칙을 과거 분봉에서 돌려 모의 체결을 집계하고 그 숫자를 어디까지 읽을 수 있는지 관문으로 점검합니다",
};

/** /intraday (분봉 백테스트) — 화면은 `widgets/intraday`. */
export default function IntradayPage() {
  return <IntradayView />;
}
