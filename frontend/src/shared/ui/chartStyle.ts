// ═══════════════════════════════════════════════════════════════════════════════
// 차트 툴팁 스타일 — Recharts `contentStyle` 단일 출처
// ─────────────────────────────────────────────────────────────────────────────
// ★왜 parts.tsx 가 아니라 여기인가 (A6, 측정으로 되돌린 결정)★
// 처음에는 `parts.tsx` 에서 `TIP_STYLE` 을 export 하고 PolicyBacktest 가 그걸 import
// 했다. 진실은 하나였지만 **번들이 30kB 늘었다**: `/allocation/journal` 이 228 → 258 kB.
// 09 는 지금까지 parts.tsx 를 한 번도 import 하지 않았는데, 상수 하나를 가져오느라
// Sankey · Frontier · Heatmap · Donut · Correlation · shadcn Table 이 전부 저널 청크에
// 딸려 들어왔다. ADR 001 의 라우트당 4kB 선을 7배 넘긴다.
//
// 그래서 토큰만 의존성 없는 shared 모듈로 내린다 — 진실은 여전히 하나이고, import 는
// 이 파일 하나만 끌고 온다. (FSD: widgets → shared 는 허용 방향이다.)
//
// ★값의 유래★ A4-X3. 예전에는 `background: "#fff"` 가 박혀 있었고, 다크에서 글자색은
// --t-ink(#fafafa)로 뒤집히는데 배경은 흰색 그대로라 **약 1.04:1** 이었다. Recharts 는
// 인라인 style 만 받으므로 클래스가 아니라 CSS 변수를 직접 넣는다.
// ═══════════════════════════════════════════════════════════════════════════════

export const TIP_STYLE = {
  background: "var(--card)", color: "var(--foreground)",
  border: "1px solid var(--border)", borderRadius: 2,
  fontSize: 11, fontFamily: "var(--t-mono, monospace)",
} as const;
