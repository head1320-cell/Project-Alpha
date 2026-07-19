"use client";
// 위저드 진행 트래커 — 7 스테이지를 3 매크로 페이즈(SETUP/LOGIC/VALIDATION)로
// 묶고, 00 Overview·06 Journal은 북엔드 칩으로. 각 스텝 칩: 상태점(완료 시 accent) +
// 번호 + 라벨 + 파생 서브텍스트. 현재 페이즈 강조. 칩 클릭 점프 + ←/→ 키보드 이동
// (입력 포커스 시 제외). 완료 파생은 Provider의 stageComplete[] 단일 소스.
import React, { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { PHASES, STAGES, stageIndex, useAllocation } from "./AllocationProvider";
import { overallConfidence } from "./ViewBuilder";

export function WizardTracker() {
  const router = useRouter();
  const pathname = usePathname();
  const active = stageIndex(pathname);
  const { holdings, views, result, model, delta, scenario, scenarios, stageComplete, timingQ } = useAllocation();

  const totalW = holdings.reduce((a, h) => a + h.weight, 0);
  const conf = Math.round(overallConfidence(views));
  const scenLabel = scenarios.find((s) => s.id === scenario)?.label ?? "—";
  const isMock = !!result && (result.coverage as { source?: string }).source === "mock";
  const tm = timingQ.data && !timingQ.data.error ? timingQ.data : null;
  const timingSub = tm
    ? `${tm.canary.signal === "risk_on" ? "위험-온" : "위험-오프"} ${tm.canary.hits}/${tm.canary.total}`
    : "미평가";

  const sub = [
    result ? `${result.names.length} 자산` : "미실행",            // 00 overview
    holdings.length ? `${holdings.length}종목 · ${totalW.toFixed(0)}%` : "자산 없음", // 01 construct
    views.length ? `${views.length}뷰 · ${conf}%` : "뷰 없음",     // 02 thesis
    timingSub,                                                     // 03 timing
    `${model.toUpperCase()} · λ${delta.toFixed(1)}`,               // 04 optimize
    scenLabel,                                                     // 05 stress
    result ? "분해 준비" : "미실행",                                // 06 explain
    stageComplete[7] ? "저장됨" : "미기록",                         // 07 journal
  ];

  // ←/→ 로 이전/다음 스테이지 (입력 필드 포커스 시 제외)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "ArrowRight" && active < STAGES.length - 1) router.push(STAGES[active + 1].href);
      else if (e.key === "ArrowLeft" && active > 0) router.push(STAGES[active - 1].href);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, router]);

  const Step = (i: number) => (
    <button key={i} title={STAGES[i].desc}
      className={`aas-wiz-step${i === active ? " on" : ""}${stageComplete[i] ? " done" : ""}`}
      onClick={() => router.push(STAGES[i].href)}>
      <span className="aas-wiz-dot" />
      <span className="aas-wiz-meta">
        <span className="aas-wiz-lab"><b className="num">{STAGES[i].n}</b> {STAGES[i].label}</span>
        <span className="aas-wiz-sub num">{sub[i]}</span>
      </span>
    </button>
  );

  const Bookend = (i: number) => (
    <button title={STAGES[i].desc}
      className={`aas-wiz-book${i === active ? " on" : ""}${stageComplete[i] ? " done" : ""}`}
      onClick={() => router.push(STAGES[i].href)}>
      <span className="aas-wiz-dot" />
      <span className="num">{STAGES[i].n}</span>
      <span className="aas-wiz-booklab">{STAGES[i].label}</span>
    </button>
  );

  return (
    <div className="aas-wiz">
      {Bookend(0)}
      {PHASES.map((p, pi) => {
        const done = p.steps.every((si) => stageComplete[si]);
        const here = p.steps.includes(active);
        return (
          <React.Fragment key={p.key}>
            <span className="aas-wiz-sep" />
            <div className={`aas-wiz-phase${here ? " on" : ""}${done ? " done" : ""}`}>
              <div className="aas-wiz-phaselab">
                <b>{p.label}</b><em>{p.ko}</em>
                <span className="aas-wiz-phasenum num">{pi + 1}/3</span>
              </div>
              <div className="aas-wiz-steps">{p.steps.map(Step)}</div>
            </div>
          </React.Fragment>
        );
      })}
      <span className="aas-wiz-sep" />
      {Bookend(7)}
      <span className="aas-wiz-right">
        {isMock && <span className="aas-wiz-mock" title="현재 결과는 합성(mock) 데이터 기준">MOCK</span>}
        <button className="aas-wiz-gate" title="목표 선택으로 돌아가기" onClick={() => router.push("/allocation")}>☰ 목표</button>
        <span className="aas-wiz-kbd num" title="키보드 ←/→ 로 단계 이동">◀ ▶</span>
      </span>
    </div>
  );
}
