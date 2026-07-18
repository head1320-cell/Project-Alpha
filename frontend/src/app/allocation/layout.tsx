"use client";
// Allocation Studio 공유 크롬 — 7단계 파이프라인의 브레드크럼·헤더·컨텍스트
// 스트립·파이프라인 바·하단 nav를 layout에서 렌더(자식 라우트 전환에도 유지 →
// 상태 보존). 각 하부 page는 순수 콘텐츠만 렌더. (Claude Design 핸드오프 구현)
import React from "react";
import { useRouter, usePathname } from "next/navigation";
import { AllocationProvider, STAGES, stageIndex, useAllocation } from "@/components/allocation/AllocationProvider";
import { ContextStrip } from "@/components/allocation/ContextStrip";
import { PipelineBar } from "@/components/allocation/PipelineBar";

function StageChrome({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const idx = stageIndex(pathname);
  const stage = STAGES[idx];
  const { canRun, pending, lastRun, runAnalyze, result } = useAllocation();
  const isMock = result && (result.coverage as { source?: string }).source === "mock";
  const cov = result
    ? `${result.coverage.start} ~ ${result.coverage.end} · ${result.coverage.n_obs}일`
    : "2019-07-17 ~ 2026-07-16 · 1,712일";

  return (
    <div className="aas-root tpage-fade">
      {/* 브레드크럼 */}
      <div className="aas-crumb num">
        MODULE 06 / ALLOCATION STUDIO / <span>{stage.n} {stage.label}</span>
      </div>

      {/* 페이지 헤더 */}
      <div className="aas-header">
        <div className="aas-header-tt">
          <div className="aas-header-title">Allocation Studio — {stage.title}</div>
          <div className="aas-header-desc">{stage.desc}</div>
        </div>
        <span className="aas-header-sp" />
        {isMock && <span className="aas-header-mock">MOCK 데이터</span>}
        <span className="aas-header-cov num">{cov} · 최근 실행 {lastRun}</span>
        <button className="aas-run" disabled={!canRun || pending} onClick={() => runAnalyze()}
          title={canRun ? "재최적화" : "자산 2개 이상 필요 (01 CONSTRUCT)"}>
          {pending ? "최적화 중…" : "RE-OPTIMIZE"}
        </button>
      </div>

      {/* 컨텍스트 스트립 (레짐 + 카나리) */}
      <ContextStrip />

      {/* 파이프라인 바 */}
      <PipelineBar />

      {/* 콘텐츠 (라우트 전환 페이드) */}
      <div key={pathname} className="aas-content">{children}</div>

      {/* 하단 nav */}
      <div className="aas-botnav">
        <button className="aas-botnav-prev" disabled={idx === 0}
          onClick={() => idx > 0 && router.push(STAGES[idx - 1].href)}>
          ← {idx > 0 ? `${STAGES[idx - 1].n} ${STAGES[idx - 1].label}` : "이전 스테이지"}
        </button>
        <span className="aas-botnav-mid num">RESEARCH PIPELINE · {stage.n} {stage.label}</span>
        <button className="aas-botnav-next" disabled={idx === STAGES.length - 1}
          onClick={() => idx < STAGES.length - 1 && router.push(STAGES[idx + 1].href)}>
          {idx < STAGES.length - 1 ? `${STAGES[idx + 1].n} ${STAGES[idx + 1].label}` : "마지막 스테이지"} →
        </button>
      </div>
    </div>
  );
}

export default function AllocationLayout({ children }: { children: React.ReactNode }) {
  return (
    <AllocationProvider>
      <StageChrome>{children}</StageChrome>
    </AllocationProvider>
  );
}
