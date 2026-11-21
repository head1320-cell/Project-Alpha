import { TradeJournalView } from "@/widgets/trade-journal/TradeJournalView";

export const metadata = {
  title: "내 계좌 · 매매일지",
  description: "체결 내역 파일로 왕복 거래의 승률·손익비·비용 비중을 집계합니다. 서버에 저장하지 않습니다",
};

/** /my-account/journal (내 계좌 › 매매일지) — 화면은 `widgets/trade-journal`. 따로 있던 `/trade-journal` 이 여기로 왔다(ADR 006 §7). */
export default function AccountJournalPage() {
  return <TradeJournalView />;
}
