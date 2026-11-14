import { TradeJournalView } from "@/widgets/trade-journal/TradeJournalView";

export const metadata = {
  title: "매매일지",
  description: "체결 내역 파일로 왕복 거래의 승률·손익비·비용 비중을 집계합니다. 서버에 저장하지 않습니다",
};

/** /trade-journal (매매일지 v1) — 화면은 `widgets/trade-journal`. */
export default function TradeJournalPage() {
  return <TradeJournalView />;
}
