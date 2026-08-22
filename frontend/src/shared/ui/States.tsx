"use client";
// 대상 경로: frontend/src/components/layout/States.tsx
//
// 6개 화면(대시보드+5툴) 공용 로딩/빈/오류 상태 — 인스티튜셔널 터미널 톤으로 통일.
// 이전엔 페이지마다 제각각(인라인 [LOADING] 텍스트 · ca-pg-spin · tbt-empty)이었음.
// 차분하게: 모노 라벨 + 통일된 스피너. 스타일은 globals.css 의 .tstate-* 가 담당.

import type { ReactNode } from "react";

// ═══════════════════════════════════════════════════════════════════════════════
// ★없던 네 번째 상태: `unavailable`★ (UI/UX 현대화 P2)
//
// 이 파일에는 로딩·빈·오류 세 가지만 있었다. 그래서 "계산할 수 없다" 를 표현할 자리가
// 없었고, 화면들은 그것을 **빈 상태로 갈음**하거나 `—` 한 글자로 뭉개 왔다.
// 두 가지는 전혀 다른 사실이다:
//
//   empty        조회는 성공했고 해당하는 행이 0건이다.        → 사용자가 조건을 바꾸면 된다.
//   unavailable  애초에 계산·조회가 성립하지 않았다.           → 사용자가 할 수 있는 일이 없을 수도 있다.
//
// 둘을 같은 모양으로 그리면 "데이터가 없다" 가 "문제가 없다" 로 읽힌다. 리서치 도구에서
// 이건 단순한 표기 문제가 아니라 **신뢰도를 과장하는 방향의 거짓말**이다.
//
// 그래서 `unavailable` 은 사유를 **선택 항목으로 두지 않는다**(아래 AsyncStatus 참고).
// 타입 수준에서 강제하므로 사유 없는 unavailable 은 tsc 가 거부한다.
// ═══════════════════════════════════════════════════════════════════════════════

export function LoadingState({ label = "데이터를 불러오는 중", sub }: { label?: string; sub?: ReactNode }) {
  return (
    <div className="tstate tstate-loading" role="status" aria-live="polite">
      <span className="tstate-spinner" aria-hidden />
      <span>[ LOADING ] {label}…</span>
      {sub && <span className="tstate-sub">{sub}</span>}
    </div>
  );
}

export function EmptyState({ label = "표시할 데이터가 없습니다", sub }: { label?: string; sub?: ReactNode }) {
  return (
    <div className="tstate tstate-empty">
      <span className="tstate-glyph" aria-hidden>◇</span>
      <span>{label}</span>
      {sub && <span className="tstate-sub">{sub}</span>}
    </div>
  );
}

export function ErrorState({ label = "오류가 발생했습니다", sub }: { label?: string; sub?: ReactNode }) {
  return (
    <div className="tstate tstate-error" role="alert">
      <span>[ ERROR ] {label}</span>
      {sub && <span className="tstate-sub">{sub}</span>}
    </div>
  );
}

/**
 * 계산·조회가 성립하지 않은 상태. **사유가 필수**다.
 *
 * 빈 상태(◇)와 시각적으로 구별되어야 한다 — 같은 회색 여백으로 그리면 "0건" 과
 * 구분되지 않는다. 그렇다고 오류(빨강)도 아니다. 오류는 고장이지만 이것은 한계이고,
 * 한계를 고장처럼 그리면 사용자가 재시도로 해결하려 든다.
 */
export function UnavailableState({ label = "측정 불가", reason }: { label?: string; reason: ReactNode }) {
  return (
    <div className="tstate tstate-unavail">
      <span className="tstate-unavail-l">[ N/A ] {label}</span>
      <span className="tstate-sub">{reason}</span>
    </div>
  );
}

// ── AsyncState ────────────────────────────────────────────────────────────────

/**
 * 판별 유니온 — `unavailable` 만 `reason` 이 필수다.
 *
 * ★이 타입이 이 파일에서 가장 중요한 줄이다★ 정직함을 규약이 아니라 **컴파일 오류**로
 * 만든다. 리뷰어의 기억이나 주석에 기대면 언젠가 빠지지만, tsc 는 잊지 않는다.
 */
export type AsyncStatus =
  | { kind: "loading"; label?: string }
  | { kind: "error"; label?: string; reason?: ReactNode }
  | { kind: "empty"; label?: string; reason?: ReactNode }
  | { kind: "unavailable"; label?: string; reason: ReactNode }
  | { kind: "ready" };

/**
 * 네 가지 비-준비 상태를 한 곳에서 그린다. `ready` 일 때만 children 을 렌더한다.
 *
 * 화면마다 `isLoading ? … : data?.length ? … : <Empty/>` 를 새로 쓰면 그 삼항이
 * 늘어날 때마다 unavailable 이 조용히 빠진다 — 실제로 그렇게 빠져 왔다.
 * 여기로 모아 두면 네 갈래를 **한 번만** 옳게 쓰면 된다.
 */
export function AsyncState({ status, children }: { status: AsyncStatus; children?: ReactNode }) {
  switch (status.kind) {
    case "loading":     return <LoadingState label={status.label} />;
    case "error":       return <ErrorState label={status.label} sub={status.reason} />;
    case "empty":       return <EmptyState label={status.label} sub={status.reason} />;
    case "unavailable": return <UnavailableState label={status.label} reason={status.reason} />;
    case "ready":       return <>{children}</>;
  }
}
