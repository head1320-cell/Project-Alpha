import { redirect } from "next/navigation";

// Builder는 Backtester 모듈의 "전략 설계" 탭으로 편입됨.
// 기존 링크/북마크 호환을 위해 리다이렉트.
export default function BuilderRedirect() {
  redirect("/backtest");
}
