import { Suspense } from "react";
import { MyAccountView } from "@/widgets/my-account/MyAccountView";

export const metadata = {
  title: "내 계좌",
  description: "연결한 증권 계좌의 주문 전송 경로를 확인하고, 모의 주문을 제출하고, 비상 정지를 설정합니다",
};

/** /my-account (BV9) — 화면은 `widgets/my-account`. `useSearchParams`(?account=) 때문에 Suspense 로 감싼다. */
export default function MyAccountPage() {
  return (
    <Suspense fallback={<p className="tx-sec-sub">내 계좌 로딩 중</p>}>
      <MyAccountView />
    </Suspense>
  );
}
