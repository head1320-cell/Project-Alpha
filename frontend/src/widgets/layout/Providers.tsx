"use client";
// 대상 경로: frontend/src/components/layout/Providers.tsx
//
// react-query QueryClientProvider — 설치는 돼 있었으나 어디에도 마운트되지 않아 전혀
// 사용되지 않던 걸 배선. useState로 클라이언트를 1회만 생성(리렌더마다 재생성 방지).

import { useState, type ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createQueryClient } from "@/shared/api/queryClient";

export default function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(createQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
