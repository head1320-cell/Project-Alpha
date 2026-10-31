"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// EvidenceBadge — 증거 상태의 **시각 처리** 단일 출처 (UI/UX 현대화 P2)
// ─────────────────────────────────────────────────────────────────────────────
// ★왜 새 어휘를 만들지 않는가★
// 도메인 어휘는 이미 있다 — `DataStatus`(real·mock·delayed·stale·partial·unavailable),
// `ResearchUsage`(backtest_eligible·forward_only·unavailable), `SignalState`,
// attribution 의 `Basis`(real·mock·unavailable). 여기에 다섯 번째를 더하면 진실이
// 다섯 곳이 된다.
//
// 그래서 이 컴포넌트는 **의미를 정의하지 않는다**. 네 가지 *시각 처리* 만 정의하고,
// 도메인 열거형 → 처리 매핑은 그 열거형을 아는 계층(widgets/entities)이 한다.
// FSD 상 shared 는 entities 를 import 할 수 없으므로 구조적으로도 이쪽이 유일한 길이다.
//
// ★기존 코드에서 관찰된 팔레트를 그대로 쓴다★ (globals.css)
//   .as-attr-basis.real        초록  — 실측
//   .as-attr-basis.mock        호박  — 합성
//   .as-attr-basis.unavailable 회색 테두리 — 없음
//   .as-ctx-stale / .as-ctx-mock / .as-usage-forward_only  호박 — 주의
// 새 색을 도입하지 않는다. 이미 화면이 쓰는 색이 곧 사용자가 학습한 언어다.
//
// ★사유는 title= 로 숨기지 않는다★
// ContextStrip 이 title= 16개로 근거를 숨겨 온 것이 이번 현대화의 최대 발견이다.
// 호버는 키보드·터치 사용자에게 존재하지 않는다. 그래서 `reason` 은 **보이는 텍스트**로
// 렌더된다. 정상 상태의 부연은 EvidenceDrawer 로 가고, 경고는 여기 남는다.
// ═══════════════════════════════════════════════════════════════════════════════

import type { ReactNode } from "react";

/**
 * 시각 처리 네 가지. 도메인 개념이 아니라 **읽는 사람이 받아야 할 신호**다.
 *
 *  measured     실제로 측정·계산된 값이다.
 *  estimated    값은 있으나 합성·추정·근사다. 결론의 근거로 쓸 때 주의가 필요하다.
 *  caution      값은 있으나 재현·최신성·정합성에 문제가 있다(stale · drift · forward_only).
 *  unavailable  값이 없다. 0 이 아니라 **없음**이다.
 */
export type EvidenceKind = "measured" | "estimated" | "caution" | "unavailable";

/**
 * `unavailable` 과 `caution` 은 사유가 필수다 — 그 두 가지야말로 사용자가
 * "왜?" 를 묻는 상태이고, 답이 없으면 배지는 장식이 된다.
 */
export type EvidenceBadgeProps =
  | { kind: "measured" | "estimated"; children: ReactNode; reason?: ReactNode; className?: string }
  | { kind: "caution" | "unavailable"; children: ReactNode; reason: ReactNode; className?: string };

export function EvidenceBadge({ kind, children, reason, className = "" }: EvidenceBadgeProps) {
  return (
    <span className={`tev tev-${kind} ${className}`.trim()}>
      <span className="tev-l">{children}</span>
      {reason && <span className="tev-r">{reason}</span>}
    </span>
  );
}
