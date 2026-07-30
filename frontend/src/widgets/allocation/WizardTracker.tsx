"use client";
// 위저드 진행 트래커 — 7 스테이지를 3 매크로 페이즈(SETUP/LOGIC/VALIDATION)로
// 묶고, 00 Overview·06 Journal은 북엔드 칩으로. 각 스텝 칩: 상태점(완료 시 accent) +
// 번호 + 라벨 + 파생 서브텍스트. 현재 페이즈 강조. 칩 클릭 점프 + ←/→ 키보드 이동
// (입력 포커스 시 제외). 완료 파생은 Provider의 stageComplete 단일 소스.
//
// ★스테이지 참조는 전부 href★ — 예전엔 부제 배열·완료 배지·페이즈 소속이 배열 위치였고
// stageComplete[9] 가 하드코딩돼 있어서, 스테이지를 하나 끼우면 타입 에러 없이 전부
// 한 칸씩 밀렸다. 순서가 실제로 필요한 곳(←/→ 이동)만 인덱스를 쓴다.
import React, { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { BOOKENDS, PHASES, STAGES, stageIndex, useAllocation, type StageHref } from "./AllocationProvider";
import { overallConfidence } from "./ViewBuilder";

const BY_HREF = new Map(STAGES.map((s) => [s.href as StageHref, s]));

export function WizardTracker() {
  const router = useRouter();
  const pathname = usePathname();
  const active = stageIndex(pathname);              // ←/→ 이동에만 — 여기선 순서가 진짜 의미다
  const activeHref = STAGES[active].href as StageHref;
  const { holdings, views, result, model, delta, scenario, scenarios, stageComplete, timingQ, alphaTouched, executionTouched, attachedSnapshotId } = useAllocation();

  const totalW = holdings.reduce((a, h) => a + h.weight, 0);
  const conf = Math.round(overallConfidence(views));
  const scenLabel = scenarios.find((s) => s.id === scenario)?.label ?? "—";
  const isMock = !!result && (result.coverage as { source?: string }).source === "mock";
  const tm = timingQ.data && !timingQ.data.error ? timingQ.data : null;
  const timingSub = tm
    ? `${tm.canary.signal === "risk_on" ? "위험-온" : "위험-오프"} ${tm.canary.hits}/${tm.canary.total}`
    : "미평가";

  const sub: Record<StageHref, string> = {
    "/allocation/overview":  result ? `${result.names.length} 자산` : "미실행",
    "/allocation/macro":     attachedSnapshotId ? "스냅샷 연결됨" : "미연결",
    "/allocation/construct": holdings.length ? `${holdings.length}종목 · ${totalW.toFixed(0)}%` : "자산 없음",
    "/allocation/alphalab":  alphaTouched ? "검증됨" : "미검증",
    "/allocation/thesis":    views.length ? `${views.length}뷰 · ${conf}%` : "뷰 없음",
    "/allocation/timing":    timingSub,
    "/allocation/optimize":  `${model.toUpperCase()} · λ${delta.toFixed(1)}`,
    "/allocation/stress":    scenLabel,
    "/allocation/explain":   result ? "귀인 준비" : "미실행",
    "/allocation/execution": executionTouched ? "계획 검토" : "미준비",
    "/allocation/journal":   stageComplete["/allocation/journal"] ? "저장됨" : "미기록",
  };

  // ←/→ 로 이전/다음 스테이지 (입력 필드·열린 모달에서는 제외)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (el?.isContentEditable) return;
      // ★모달이 열려 있으면 스테이지를 이동하지 않는다★
      // window 리스너라 모달 안에서 누른 화살표까지 잡아채고 있었다. 그러면 팩터 창에서
      // 패밀리 칩을 화살표로 넘기려는 순간 페이지가 다음 스테이지로 넘어가고 창이
      // 언마운트되어, 설정 중이던 내용이 사라진다. 스펙 §8.1 의 키보드 내비게이션·포커스
      // 트랩 요구와도 정면으로 어긋난다.
      // (E2E 가 이 결함을 간헐적으로 잡고 있었다 — 포커스 이동이 라우팅보다 빠르면 통과해서
      //  "flaky 테스트" 처럼 보였다. 실제로는 제품 결함이 단정과 경쟁하고 있었다.)
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      if (e.key === "ArrowRight" && active < STAGES.length - 1) router.push(STAGES[active + 1].href);
      else if (e.key === "ArrowLeft" && active > 0) router.push(STAGES[active - 1].href);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, router]);

  const Step = (href: StageHref) => {
    const s = BY_HREF.get(href)!;
    return (
      <button key={href} title={s.desc}
        className={`aas-wiz-step${href === activeHref ? " on" : ""}${stageComplete[href] ? " done" : ""}`}
        onClick={() => router.push(href)}>
        <span className="aas-wiz-dot" />
        <span className="aas-wiz-meta">
          <span className="aas-wiz-lab"><b className="num">{s.n}</b> {s.label}</span>
          <span className="aas-wiz-sub num">{sub[href]}</span>
        </span>
      </button>
    );
  };

  const Bookend = (href: StageHref) => {
    const s = BY_HREF.get(href)!;
    return (
      <button title={s.desc}
        className={`aas-wiz-book${href === activeHref ? " on" : ""}${stageComplete[href] ? " done" : ""}`}
        onClick={() => router.push(href)}>
        <span className="aas-wiz-dot" />
        <span className="num">{s.n}</span>
        <span className="aas-wiz-booklab">{s.label}</span>
      </button>
    );
  };

  return (
    <div className="aas-wiz">
      {Bookend(BOOKENDS[0])}
      {PHASES.map((p, pi) => {
        const done = p.steps.every((h) => stageComplete[h]);
        const here = p.steps.includes(activeHref);
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
      {Bookend(BOOKENDS[BOOKENDS.length - 1])}
      <span className="aas-wiz-right">
        {isMock && <span className="aas-wiz-mock" title="현재 결과는 합성(mock) 데이터 기준">MOCK</span>}
        <button className="aas-wiz-gate" title="목표 선택으로 돌아가기" onClick={() => router.push("/allocation")}>☰ 목표</button>
        <span className="aas-wiz-kbd num" title="키보드 ←/→ 로 단계 이동">◀ ▶</span>
      </span>
    </div>
  );
}
