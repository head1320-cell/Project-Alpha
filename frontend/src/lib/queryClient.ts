// 대상 경로: frontend/src/lib/queryClient.ts
//
// 앱 전역 QueryClient — 탭(스크리너/매크로/컴퍼니) 이동마다 API가 매번 재로딩되던 문제 수정.
// 일봉(Daily) 기반 데이터라 장중에도 자주 안 바뀜 — staleTime 24h로 넉넉히.

import { QueryClient } from "@tanstack/react-query";

const DAY_MS = 1000 * 60 * 60 * 24;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: DAY_MS,
        gcTime: DAY_MS,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}
