import { Suspense } from "react";
import { ClientsView } from "@/widgets/clients/ClientsView";

export const metadata = {
  title: "고객",
  description: "관리하는 고객(별칭만)과 고객별 설계 문서를 보고, 정기 점검 문서를 만들어요",
};

/** /clients (CF 3부 PB3) — 화면은 `widgets/clients`. `useSearchParams`(?client=) 때문에 Suspense 로 감싼다. */
export default function ClientsPage() {
  return (
    <Suspense fallback={<p className="tx-sec-sub">고객 화면을 여는 중이에요.</p>}>
      <ClientsView />
    </Suspense>
  );
}
