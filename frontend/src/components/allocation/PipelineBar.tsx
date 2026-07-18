"use client";
// 파이프라인 바 — 7단계 순차 리서치 프로세스 (Aladdin식 스테이지 바).
// 각 칩: 상태점(완료 시 accent 채움) + 번호 + 라벨 + 파생 서브텍스트 + 커넥터선.
// 활성 칩 accent 테두리+tint. ←/→ 키보드 이동(입력 포커스 시 제외).
import React, { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { STAGES, stageIndex, useAllocation } from "./AllocationProvider";
import { overallConfidence } from "./ViewBuilder";

export function PipelineBar() {
  const router = useRouter();
  const pathname = usePathname();
  const active = stageIndex(pathname);
  const { holdings, views, result, model, delta, scenario, scenarios, timeline } = useAllocation();

  const totalW = holdings.reduce((a, h) => a + h.weight, 0);
  const conf = Math.round(overallConfidence(views));
  const scenLabel = scenarios.find((s) => s.id === scenario)?.label ?? "—";

  // 단계별 완료 여부 + 서브텍스트 (파생)
  const done = [
    !!result,                                   // 00 overview: 최적화 결과 있으면 완료 표시
    holdings.length >= 2,                        // 01 construct
    views.length > 0,                            // 02 thesis
    !!result,                                    // 03 optimize
    !!result,                                    // 04 stress (히트맵은 결과 기반)
    !!result,                                    // 05 explain
    timeline.some((e) => e.msg.startsWith("스터디 저장")),  // 06 journal
  ];
  const sub = [
    result ? `${result.names.length} ASSETS · READY` : "미실행",
    holdings.length ? `${holdings.length} ASSETS · ${totalW.toFixed(1)}%` : "자산 없음",
    views.length ? `${views.length} VIEWS · CONF ${conf}%` : "뷰 없음",
    `${model.toUpperCase()} · λ ${delta.toFixed(1)}`,
    scenLabel,
    result ? "분해 준비됨" : "미실행",
    timeline.some((e) => e.msg.startsWith("스터디 저장")) ? "저장됨" : "미기록",
  ];

  // 키보드 ←/→ 로 이전/다음 스테이지
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

  return (
    <div className="aas-pipe">
      {STAGES.map((s, i) => (
        <div key={s.href} className="aas-pipe-seg">
          {i > 0 && <span className="aas-pipe-conn" />}
          <button className={`aas-pipe-chip${i === active ? " on" : ""}`} title={s.desc}
            onClick={() => router.push(s.href)}>
            <span className={`aas-pipe-dot${done[i] ? " done" : ""}`} />
            <span className="aas-pipe-n num">{s.n}</span>
            <span className="aas-pipe-meta">
              <span className="aas-pipe-label">{s.label}</span>
              <span className="aas-pipe-sub num">{sub[i]}</span>
            </span>
          </button>
        </div>
      ))}
      <span className="aas-pipe-kbd num">◀ ▶ 이동</span>
    </div>
  );
}
