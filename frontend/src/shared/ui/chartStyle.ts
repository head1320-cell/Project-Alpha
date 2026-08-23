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

// ═══════════════════════════════════════════════════════════════════════════════
// 차트 애니메이션 스위치 (A12)
// ─────────────────────────────────────────────────────────────────────────────
// 여태 `isAnimationActive={false}` 가 21곳에 박혀 있었다. 스크린샷 결정성(스펙 v2 §7)은
// 얻었지만 실사용자도 애니메이션을 못 봤다. 이제 런타임에 정한다.
//
// ★`NEXT_PUBLIC_E2E` 로 하지 않는다 — 측정으로 기각한 방식이다★
// `NEXT_PUBLIC_*` 는 **빌드 타임에 인라인**된다(같은 함정을 `shared/api/apiBase.ts:22` 가
// 이미 사고 기록으로 남겨 뒀다). 그런데 `playwright.config.ts` 의 webServer 는
// `npx next start` — **이미 빌드된 `.next` 를 서빙**할 뿐 다시 빌드하지 않는다. 그래서
// config 에 env 를 주입해도 번들 안의 값은 빌드 시점(`undefined`)으로 굳어 있고, 토글은
// **조용히 무시되어 차트가 애니메이션된 채 스크린샷에 잡힌다**. 배선된 것처럼 보이는데
// 아무 일도 안 하는 형태이고, 통과시키려면 E2E 전용 빌드를 따로 떠야 해서
// **검증한 아티팩트와 배포할 아티팩트가 달라진다**.
//
// 런타임 신호는 두 개다. 하나는 진짜 사용자 설정이고 하나는 테스트 훅이다:
//   1. `prefers-reduced-motion: reduce` — a11y. 끄는 게 옳다.
//   2. `window.__MOTION_OFF__` — Playwright 가 `addInitScript` 로 세운다
//      (`e2e/helpers.ts` 의 `freezeCharts`). 문서 생성 전에 실행돼도 안전하도록
//      `documentElement.dataset` 이 아니라 window 전역을 쓴다.
//
// ★첫 렌더가 항상 false 인 것은 의도다★ SSR 에는 `window` 가 없다. 서버와 클라이언트가
// 다른 `isAnimationActive` 를 내면 하이드레이션이 어긋난다. 그래서 마운트 뒤에 켠다 —
// 사용자가 차트를 보는 시점이 정확히 그때이므로 손해도 없다.
// ═══════════════════════════════════════════════════════════════════════════════

import { useEffect, useState } from "react";

/** 지금 차트 애니메이션을 켜도 되는가. SSR·첫 렌더는 항상 `false`. */
export function useChartAnimation(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if ((window as unknown as { __MOTION_OFF__?: boolean }).__MOTION_OFF__ === true) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setOn(!mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return on;
}
