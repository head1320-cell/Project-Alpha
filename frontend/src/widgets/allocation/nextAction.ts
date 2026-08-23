// ═══════════════════════════════════════════════════════════════════════════════
// 워크플로 다음 할 일 — 결정적 정책 (UI/UX 현대화 P3.5)
// ─────────────────────────────────────────────────────────────────────────────
// ★워크플로 권고이지 투자 권고가 아니다★
// "타이밍으로 계속", "입력이 바뀌었으니 재계산" 은 이 함수가 말해도 된다.
// "주식을 사라", "위험을 늘려라" 는 절대 안 된다.
//
// 그 경계를 규약이 아니라 **입력 타입**으로 지킨다: 아래 WorkflowState 에는 수익률·비중·
// 신호 상태·스트레스 점수가 하나도 없다. 시장 값이 들어올 자리가 없으므로 투자 권고를
// 만들래야 만들 수 없다. 새 필드를 넣고 싶어지면 그것이 곧 경계를 넘는 순간이다.
//
// 순수 함수인 이유: 화면 없이 8가지 상태를 전부 검사할 수 있어야 하기 때문이다.
// ═══════════════════════════════════════════════════════════════════════════════

/** UI/세션 상태만. 시장 값은 여기 들어오지 않는다(위 주석 참고). */
export interface WorkflowState {
  hasStudy: boolean;
  holdingsCount: number;
  hasSnapshot: boolean;
  hasRuleSet: boolean;
  hasResult: boolean;
  isResultStale: boolean;
  hasStressValidation: boolean;
  hasJournalEntry: boolean;
}

export interface NextAction {
  /** 안정 키 — E2E 가 라벨 문구가 아니라 이 값을 본다. */
  key: string;
  label: string;
  href: string;
  /** 왜 이것이 다음인가. 화면에 그대로 보인다(툴팁 아님). */
  why: string;
}

/**
 * 먼저 맞는 규칙이 이긴다. v2.1 §2.2 표를 그대로 옮기되 **두 곳을 고쳤다**.
 *
 * ★수정 1 — 규칙 1이 작업 중인 사용자를 게이트로 끌고 갔다★
 * 승인된 표는 "활성 스터디 없음 → 게이트" 가 1순위였다. 그런데 `activeStudy` 는 저널을
 * 저장해야 생긴다. 즉 자산을 담고 최적화까지 끝낸 사용자도 저널 전까지는 계속
 * "연구 시작 → 게이트" 를 보게 된다. 그래서 **아무것도 시작하지 않았을 때**로 좁혔다.
 *
 * ★수정 2 — 선택 단계가 차단 단계가 되어 있었다★
 * 규칙 3(매크로 스냅샷)은 "선택" 이라고 적혀 있지만, 먼저-맞는-규칙이 이기는 사슬에서
 * 선택 항목을 조건 없이 두면 **고정하지 않는 한 영원히 3번에 멈춘다**. 라벨에 "(선택)"
 * 을 붙여도 사슬은 진행되지 않는다. 그래서 3·4번은 첫 계산 **이전**에만 제안한다 —
 * 결과가 한 번 나온 뒤에는 다시 조르지 않는다.
 */
export function nextAction(s: WorkflowState): NextAction {
  // 1. 아무것도 시작하지 않았다 — 게이트가 목표를 정하는 입구다.
  if (!s.hasStudy && s.holdingsCount === 0 && !s.hasResult) {
    return { key: "start", label: "연구 시작", href: "/allocation",
      why: "아직 시작된 연구가 없습니다. 게이트에서 목표를 정하세요." };
  }
  // 2. 자산이 없으면 계산할 대상이 없다.
  if (s.holdingsCount === 0) {
    return { key: "construct", label: "자산 구성", href: "/allocation/construct",
      why: "보유 자산이 없어 최적화·검증을 할 대상이 없습니다." };
  }
  // 3·4. 계산 전 준비 — 선택이므로 첫 결과가 나온 뒤에는 제안하지 않는다.
  if (!s.hasResult && !s.hasSnapshot) {
    return { key: "snapshot", label: "매크로 근거 고정 (선택)", href: "/allocation/macro",
      why: "결정 시점의 국면을 스냅샷으로 고정하면 나중에 재현·귀인이 됩니다. 건너뛰어도 됩니다." };
  }
  if (!s.hasResult && !s.hasRuleSet) {
    return { key: "ruleset", label: "타이밍 규칙 저장 (선택)", href: "/allocation/timing",
      why: "저장된 규칙만 버전으로 남아 재현됩니다. 타이밍을 쓰지 않을 거라면 건너뛰어도 됩니다." };
  }
  // 5. ★낡은 결과로는 검증도 기록도 하지 않는다★ 6·7·8보다 앞선다.
  if (!s.hasResult || s.isResultStale) {
    return { key: "recalc", label: "입력이 바뀜 — 재계산", href: "/allocation/optimize",
      why: s.hasResult
        ? "입력이 바뀐 뒤 아직 재계산되지 않았습니다. 지금 수치는 이전 입력의 결과입니다."
        : "아직 최적화를 실행하지 않았습니다." };
  }
  // 6. 검증 없는 결과는 결론이 아니다.
  if (!s.hasStressValidation) {
    return { key: "stress", label: "시나리오 검증", href: "/allocation/stress",
      why: "이 결과를 충격 시나리오로 아직 검증하지 않았습니다." };
  }
  // 7. 기록되지 않은 결정은 나중에 귀인할 수 없다.
  if (!s.hasJournalEntry) {
    return { key: "journal", label: "결정 기록", href: "/allocation/journal",
      why: "결정을 기록해야 결정 시점이 고정되고 이후 실측과 대조할 수 있습니다." };
  }
  // 8. 흐름을 마쳤다 — 남은 일은 되돌아보는 것.
  return { key: "review", label: "리뷰 — 귀인 확인", href: "/allocation/explain",
    why: "연구 흐름이 한 바퀴 끝났습니다. 사전 기대와 사후 실측을 대조하세요." };
}
