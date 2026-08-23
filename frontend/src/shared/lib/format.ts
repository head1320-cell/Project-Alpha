// 표시용 포맷·색상 헬퍼 — API가 아니라 프레젠테이션 유틸이라 shared/lib에 둔다.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

export function verdictColor(verdict: string): {
  fg: string;
  bg: string;
  border: string;
} {
  if (verdict.includes("극심한 저평가"))
    return { fg: "#15803d", bg: "#dcfce7", border: "#86efac" };
  if (verdict.includes("저평가") && !verdict.includes("약간"))
    return { fg: "#16a34a", bg: "#f0fdf4", border: "#bbf7d0" };
  if (verdict === "약간 저평가")
    return { fg: "#65a30d", bg: "#f7fee7", border: "#d9f99d" };
  if (verdict === "적정")
    return { fg: "#525252", bg: "#fafafa", border: "#e5e5e5" };
  if (verdict === "약간 고평가")
    return { fg: "#ea580c", bg: "#fff7ed", border: "#fed7aa" };
  if (verdict.includes("극심한 고평가"))
    return { fg: "#b91c1c", bg: "#fef2f2", border: "#fecaca" };
  return { fg: "#dc2626", bg: "#fef2f2", border: "#fecaca" }; // 고평가
}

export function gapColor(gapPct: number): string {
  if (gapPct <= -30) return "#15803d";  // 짙은 녹색
  if (gapPct <= -15) return "#16a34a";
  if (gapPct <= -5)  return "#65a30d";
  if (gapPct <= 5)   return "#737373";  // 회색
  if (gapPct <= 15)  return "#ea580c";
  if (gapPct <= 30)  return "#dc2626";
  return "#b91c1c";                       // 짙은 빨강
}

export function formatKrw(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(1)}만`;
  return v.toLocaleString();
}

export function formatPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}
