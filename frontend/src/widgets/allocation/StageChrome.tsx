"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// StageChrome — Allocation Studio 의 공유 크롬 (A1a)
// ─────────────────────────────────────────────────────────────────────────────
// 인텐트 → 컨텍스트 스트립 → 스티키 파이프라인 스테퍼 → 신선도 배너 → 콘텐츠 → 하단 nav.
//
// ★왜 layout.tsx 에서 꺼냈나★
// 이 컴포넌트는 앞으로 매 스텝이 손대는 이음매인데, `app/allocation/layout.tsx` 안의
// private function 이라 import 도 테스트도 되지 않았다. 라우트 파일은 조립만 하고
// 조립되는 것은 widgets 에 둔다 — FSD 방향(app → widgets)과도 맞는다.
//
// ★클래스 이름은 E2E 계약이다★ 이 저장소는 data-testid 를 쓰지 않는다.
// 아래 이름들은 스펙이 직접 선택하므로 바꾸면 스펙도 같이 고쳐야 한다:
//   .aas-intent(route-health·research-shell) · .aas-content(aas·route-health·responsive)
//   .aas-botnav-next(responsive·research-shell) · .aas-botnav-why + data-next(research-shell)
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { PHASES, STAGES, stageIndex, useAllocation } from "./AllocationProvider";
import { changedLabels } from "./analyzeSignature";
import { ContextStrip } from "./ContextStrip";
import { WizardTracker } from "./WizardTracker";
import { nextAction } from "./nextAction";

/**
 * 결과 신선도 배너.
 *
 * ★브리프의 `opacity-50` 오버레이를 쓰지 않았다 — 측정 결과 때문이다★
 * 결과 패널을 50% 로 흐리면 그 안의 숫자가 WCAG AA(4.5:1) 아래로 떨어진다. 오늘 백테스트
 * 화면에서 정확히 그 유형의 결함을 계산으로 찾아 고쳤다. 게다가 흐린 숫자는 **여전히 읽히는
 * 틀린 숫자**다 — 읽지 말라는 뜻이면 읽기 어렵게 만들 것이 아니라 낡았다고 말해야 한다.
 *
 * 그래서: 숫자는 전각 대비로 두고, 무엇이 바뀌었는지 배너로 적고, 다음 행동을 붙인다.
 * WizardTracker 가 이미 쓰는 방식(낡은 부제를 "재계산 필요"로 갈아끼움)의 연장이다.
 */
function FreshnessBanner() {
  const { freshness, canRun, pending, runAnalyze } = useAllocation();
  if (freshness.kind === "fresh") return null;

  const superseded = freshness.kind === "superseded";
  // ★무엇이 바뀌었는지 모르면 모른다고 적는다★ diffAgainstSignature 는 이전 서명을
  // 파싱하지 못하면 null 을 준다. 그 경우 그럴듯한 목록을 지어내지 않는다.
  const what = superseded && freshness.changed?.length ? changedLabels(freshness.changed) : null;

  return (
    <div className={`aas-fresh aas-fresh-${freshness.kind}`} role="status">
      <span className="aas-fresh-k">{superseded ? "재계산 필요" : "미계산"}</span>
      <span className="aas-fresh-r">
        {superseded
          ? what
            ? `${what} 이(가) 바뀐 뒤 아직 재계산되지 않았습니다 — 지금 보이는 수치는 이전 입력의 결과입니다.`
            : "입력이 바뀐 뒤 아직 재계산되지 않았습니다 — 지금 보이는 수치는 이전 입력의 결과입니다."
          : canRun
            ? "아직 최적화를 실행하지 않았습니다 — 이 화면에는 표시할 결과가 없습니다."
            : "자산을 2개 이상 담아야 최적화를 실행할 수 있습니다."}
      </span>
      {canRun && (
        <button className="aas-fresh-b" disabled={pending} onClick={() => runAnalyze()}>
          {pending ? "계산 중…" : "지금 재계산"}
        </button>
      )}
    </div>
  );
}

export function StageChrome({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const idx = stageIndex(pathname);
  const stage = STAGES[idx];
  const phase = stage.phase ? PHASES.find((p) => p.key === stage.phase) : null;
  const {
    noteVisit, ensureFreshRun, activeStudy, holdings, attachedSnapshotId,
    activeRuleSet, result, isResultStale, stressQ, stageComplete,
  } = useAllocation();

  // 마지막 방문 스테이지 기록 (게이트의 Resume용)
  useEffect(() => { noteVisit(stage.href); }, [stage.href, noteVisit]);

  // ★단일 워크플로 다음 할 일★ (P3.5)
  // 예전에는 언제나 "배열의 다음 칸" 이었다. 그래서 자산도 없는데 "다음 단계로 — 02 THESIS"
  // 라고 말하곤 했다. 이제는 nextAction() 이 **UI 상태만 보고** 정한다. 방향이 아니라
  // 할 일을 말하므로, 목적지가 뒤 스테이지여도(예: 근거 고정) 문구가 어긋나지 않는다.
  // 선형 이동 수단은 그대로 남아 있다 — 왼쪽 이전 버튼과 위저드의 ←/→ 키.
  const na = nextAction({
    hasStudy: !!activeStudy,
    holdingsCount: holdings.length,
    hasSnapshot: !!attachedSnapshotId,
    hasRuleSet: !!activeRuleSet,
    hasResult: !!result,
    isResultStale,
    hasStressValidation: !!stressQ.data?.available,
    hasJournalEntry: stageComplete["/allocation/journal"],
  });
  const naTarget = STAGES.find((s) => s.href === na.href) ?? null;
  const goNext = () => {
    // Validation 단계로 들어갈 때 stale 이면 재최적화 — 기존 동작을 그대로 지킨다.
    if (naTarget?.phase === "validation") ensureFreshRun();
    router.push(na.href);
  };

  return (
    <div className="aas-root tpage-fade">
      {/* 이 단계에서 할 일 (Contextual Isolation 인텐트) — 헤더 블록(제목/브레드크럼/커버리지)은 제거됨 */}
      <div className="aas-intent"><b>이 단계에서 할 일</b> — {stage.intent}</div>

      {/* 컨텍스트 스트립 (레짐 + 카나리) */}
      <ContextStrip />

      {/* 위저드 진행 트래커 — 스크롤해도 붙어 있다(§49) */}
      <WizardTracker />

      {/* 결과 신선도 — 모든 스테이지에서 같은 자리에 같은 말로 */}
      <FreshnessBanner />

      {/* 콘텐츠 (라우트 전환 페이드) */}
      <div key={pathname} className="aas-content">{children}</div>

      {/* 하단 가이드 nav — 단일 주 CTA. 이유는 버튼 옆에 **보이는 텍스트**로 적는다. */}
      <div className="aas-botnav">
        <button className="aas-botnav-prev" disabled={idx === 0}
          onClick={() => idx > 0 && router.push(STAGES[idx - 1].href)}>
          ← {idx > 0 ? `${STAGES[idx - 1].n} ${STAGES[idx - 1].label}` : "이전 단계"}
        </button>
        <span className="aas-botnav-mid num">RESEARCH PIPELINE · {phase ? `${phase.label} 단계` : stage.label}</span>
        <span className="aas-botnav-why" data-next={na.key}>{na.why}</span>
        <button className="aas-botnav-next primary" onClick={goNext}>
          {na.label}{naTarget ? ` — ${naTarget.n} ${naTarget.label}` : ""} →
        </button>
      </div>
    </div>
  );
}
