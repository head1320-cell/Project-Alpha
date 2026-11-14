import { redirect } from "next/navigation";

/** 옛 주소 — 분봉 백테스트는 백테스트 메뉴 안의 모드가 됐다(ADR 006 §7). 끊지 않고 넘긴다. */
export default function IntradayMovedPage() {
  redirect("/backtest/intraday");
}
