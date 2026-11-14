import { redirect } from "next/navigation";

/** 옛 주소 — 매매일지는 내 계좌 메뉴 안의 모드가 됐다(ADR 006 §7). 끊지 않고 넘긴다. */
export default function TradeJournalMovedPage() {
  redirect("/my-account/journal");
}
