// ════════════════════════════════════════════════════════════════════════════
// 차트 공용 — 애니메이션 스위치
// ────────────────────────────────────────────────────────────────────────────
// 이 파일에는 예전에 Recharts 툴팁 스타일(`TIP_STYLE` · `TX_TIP_STYLE`)이 있었다. 2026-11-10 에 삭제 — 값은 호버 툴팁이 아니라
// 늘 보이는 읽는 줄에 있고(`shared/ui/chart/ChartReadout.tsx` · ADR 004 §2.4 · §6) `Tooltip` import 는 린트가 막는다.
// 표식 규격(선·점·격자·막대·축 글자)은 `shared/ui/chart/chartSpec.ts`.
// (A6 의 교훈은 그대로다: 공용 상수는 의존성 없는 shared 모듈에 둔다 — 위젯 파일에서 꺼내 쓰면 그 파일의 차트가 통째로 딸려 온다.)
// ════════════════════════════════════════════════════════════════════════════

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
