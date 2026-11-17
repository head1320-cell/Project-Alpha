"use client";
/**
 * 국면별 성과 나눔(K2a) · 하루 유형 비율(K2b)의 문이 실패했을 때 — 두 부품이 같은 규칙을 쓴다.
 * 로그인 만료는 로그인으로 · 거절(400 · 404 · 422 — 다시 물어도 같다)은 서버 사유만(재시도 없음) · 그 밖(닿지 못함 · 503 · 500)은 재시도.
 */
import Link from "next/link";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, RetryFail } from "@/shared/ui/tx";

const HERE = "/backtest/intraday";

export function RegimeRequestFailure({ status, error, again }: { status: number; error: string; again: () => void }) {
  if (status === 401) {
    return <Notice tone="danger" title="로그인 세션이 만료됐습니다.">다시 로그인하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link></Notice>;
  }
  if (status === 400 || status === 404 || status === 422) {
    return <Notice tone="danger" title="요청 거절"><span data-server>{error}</span></Notice>;
  }
  return <RetryFail title="요청 실패" onRetry={again}><span data-server>{error}</span></RetryFail>;
}
