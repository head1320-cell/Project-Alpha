import { SheetView } from "@/widgets/clients/SheetView";

export const metadata = {
  title: "고객 한 장",
  description: "서버가 다시 계산한 고객 포트폴리오 한 장을 보고, 인쇄하고, 고객 AI 를 미리 물어봐요",
};

/** /clients/<cid>/sheets/<sid> (CF 3부 PB4) — 화면은 `widgets/clients/SheetView`. */
export default function ClientSheetPage({ params }: { params: { cid: string; sid: string } }) {
  return <SheetView cid={params.cid} sid={params.sid} />;
}
