/**
 * /c — 고객 화면(CF 3부 PB6 · 유통 관문 뒤). 메뉴 없는 단독 한 화면 — 내용은 `widgets/share`.
 * 검색에 걸리지 않게(noindex) · 다른 곳으로 리퍼러를 보내지 않게(no-referrer). 토큰은 주소의 조각(#)이라 서버에 닿지 않는다.
 */
import type { Metadata } from "next";

import { ShareView } from "@/widgets/share";

export const metadata: Metadata = {
  title: "내 포트폴리오 한 장",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function SharePage() {
  return <ShareView />;
}
