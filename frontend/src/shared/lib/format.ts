// 표시용 포맷·색상 헬퍼 — API가 아니라 프레젠테이션 유틸이라 shared/lib에 둔다.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

export function verdictColor(verdict: string): {
  fg: string;
  bg: string;
  border: string;
} {
  if (verdict.includes("극심한 저평가"))
    return { fg: "var(--hx-t-15803d)", bg: "var(--hx-b-dcfce7)", border: "var(--hx-d-86efac)" };
  if (verdict.includes("저평가") && !verdict.includes("약간"))
    return { fg: "var(--hx-t-16a34a)", bg: "var(--hx-b-f0fdf4)", border: "var(--hx-d-bbf7d0)" };
  if (verdict === "약간 저평가")
    return { fg: "var(--hx-t-65a30d)", bg: "var(--hx-b-f7fee7)", border: "var(--hx-d-d9f99d)" };
  if (verdict === "적정")
    return { fg: "var(--hx-t-525252)", bg: "var(--hx-b-fafafa)", border: "var(--hx-d-e5e5e5)" };
  if (verdict === "약간 고평가")
    return { fg: "var(--hx-t-ea580c)", bg: "var(--hx-b-fff7ed)", border: "var(--hx-d-fed7aa)" };
  if (verdict.includes("극심한 고평가"))
    return { fg: "var(--hx-t-b91c1c)", bg: "var(--hx-b-fef2f2)", border: "var(--hx-d-fecaca)" };
  return { fg: "var(--hx-t-dc2626)", bg: "var(--hx-b-fef2f2)", border: "var(--hx-d-fecaca)" }; // 고평가
}

export function gapColor(gapPct: number): string {
  if (gapPct <= -30) return "var(--hx-t-15803d)";  // 짙은 녹색
  if (gapPct <= -15) return "var(--hx-t-16a34a)";
  if (gapPct <= -5)  return "var(--hx-t-65a30d)";
  if (gapPct <= 5)   return "var(--hx-t-737373)";  // 회색
  if (gapPct <= 15)  return "var(--hx-t-ea580c)";
  if (gapPct <= 30)  return "var(--hx-t-dc2626)";
  return "var(--hx-t-b91c1c)";                       // 짙은 빨강
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
