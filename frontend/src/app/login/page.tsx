"use client";

/**
 * /login — 메뉴 없는 단독 한 화면(BU8b). 내용은 `widgets/login`(폼 + '로그인이 여는 것' 지도).
 * `useSearchParams`(돌아갈 곳 `?next=`)는 Suspense 경계 안에서 읽어야 정적 빌드가 깨지지 않는다(BU7c 파생 화면과 같은 방식).
 */
import { Suspense } from "react";

import { LoginView } from "@/widgets/login";

export default function LoginPage() {
  return <Suspense fallback={null}><LoginView /></Suspense>;
}
