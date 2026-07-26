"use client";
// 대상 경로: frontend/src/components/layout/States.tsx
//
// 6개 화면(대시보드+5툴) 공용 로딩/빈/오류 상태 — 인스티튜셔널 터미널 톤으로 통일.
// 이전엔 페이지마다 제각각(인라인 [LOADING] 텍스트 · ca-pg-spin · tbt-empty)이었음.
// 차분하게: 모노 라벨 + 통일된 스피너. 스타일은 globals.css 의 .tstate-* 가 담당.

import type { ReactNode } from "react";

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
