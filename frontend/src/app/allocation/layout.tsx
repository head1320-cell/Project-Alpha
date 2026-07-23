"use client";
// Allocation Studio 공유 크롬 — 위저드(8단계 파이프라인)의 브레드크럼·헤더·인텐트·
// 컨텍스트 스트립·진행 트래커·하단 가이드 nav를 layout에서 렌더(자식 라우트 전환에도
// Provider 유지 → 상태 보존). /allocation(게이트)은 isGate 분기로 크롬 없이 bare 렌더.
import React, { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { AllocationProvider, PHASES, STAGES, stageIndex, useAllocation } from "@/components/allocation/AllocationProvider";
import { ContextStrip } from "@/components/allocation/ContextStrip";
import { WizardTracker } from "@/components/allocation/WizardTracker";

function StageChrome({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const idx = stageIndex(pathname);
  const stage = STAGES[idx];
  const phase = stage.phase ? PHASES.find((p) => p.key === stage.phase) : null;
  const { noteVisit, ensureFreshRun } = useAllocation();

  // 마지막 방문 스테이지 기록 (게이트의 Resume용)
  useEffect(() => { noteVisit(stage.href); }, [stage.href, noteVisit]);

  const isLast = idx === STAGES.length - 1;                 // 09 journal
  const nextStage = idx < STAGES.length - 1 ? STAGES[idx + 1] : null;
  const goNext = () => {
    if (!nextStage) return;
    if (nextStage.phase === "validation") ensureFreshRun();  // Validation 진입 시 stale이면 재최적화
    router.push(nextStage.href);
  };
  const nextLabel = nextStage?.label === "JOURNAL" ? "저널로 마무리"
    : nextStage ? `다음 단계로 — ${nextStage.n} ${nextStage.label}` : "";

  return (
    <div className="aas-root tpage-fade">
      {/* 이 단계에서 할 일 (Contextual Isolation 인텐트) — 헤더 블록(제목/브레드크럼/커버리지)은 제거됨 */}
      <div className="aas-intent"><b>이 단계에서 할 일</b> — {stage.intent}</div>

      {/* 컨텍스트 스트립 (레짐 + 카나리) */}
      <ContextStrip />

      {/* 위저드 진행 트래커 */}
      <WizardTracker />

      {/* 콘텐츠 (라우트 전환 페이드) */}
      <div key={pathname} className="aas-content">{children}</div>

      {/* 하단 가이드 nav — 단일 주 CTA "다음 단계로" */}
      <div className="aas-botnav">
        <button className="aas-botnav-prev" disabled={idx === 0}
          onClick={() => idx > 0 && router.push(STAGES[idx - 1].href)}>
          ← {idx > 0 ? `${STAGES[idx - 1].n} ${STAGES[idx - 1].label}` : "이전 단계"}
        </button>
        <span className="aas-botnav-mid num">RESEARCH PIPELINE · {phase ? `${phase.label} 단계` : stage.label}</span>
        {isLast
          ? <button className="aas-botnav-restart" onClick={() => router.push("/allocation")}>새 목표 (게이트로) →</button>
          : <button className="aas-botnav-next primary" onClick={goNext}>{nextLabel} →</button>}
      </div>
    </div>
  );
}

function LayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // 게이트(/allocation)는 크롬 없이 bare 렌더 (page.tsx가 GoalGate를 렌더) — Provider 안이라
  // 게이트에서 세팅한 시드가 상태로 유지되어 Construct로 그대로 이어짐.
  if (pathname === "/allocation") return <>{children}</>;
  return <StageChrome>{children}</StageChrome>;
}

export default function AllocationLayout({ children }: { children: React.ReactNode }) {
  return (
    <AllocationProvider>
      <LayoutInner>{children}</LayoutInner>
    </AllocationProvider>
  );
}
