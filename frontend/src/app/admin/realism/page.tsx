import { redirect } from "next/navigation";

/** 옛 주소 — 현실성 점검은 실거래 화면의 탭이 됐다(ST3c). 북마크가 깨지지 않게 그리로 보낸다. */
export default function RealismRedirect() {
  redirect("/admin/live-trading?tab=realism");
}
