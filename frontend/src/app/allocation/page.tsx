"use client";
// /allocation = AAS 노드 캔버스 (BI3·BI4 · ADR 002 · 사용자 결정).
// 포트폴리오를 노드-링크 그래프로 설계·분석한다. 계산은 백엔드 그래프 실행기가 한다.
//
// ★마법사는 보존한다★(사용자 결정) — BK 로 모든 단계의 도구가 노드가 됐지만(대응표 `wizardNodeMap.ts`), 단계별
// 화면이 편한 사람은 위 "마법사 도구" 줄에서 연다. 캔버스의 옵티마이저 결과는 "도구로 보내기" 로 넘기는데,
// ★숫자가 아니라 입력★을 마법사 세션에 넣는다 — 마법사가 같은 /analyze 로 다시 구한다.
// 세션 세터를 부르는 것은 이 파일(app 계층)이다: 위젯끼리는 서로 import 하지 않는다(FSD).
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import type { GraphDoc, HandoffPayload } from "@/entities/portfolio-graph";
// 템플릿 하나만 — 엔티티 전체(api·검증·포맷)를 첫 로드에 싣지 않는다.
import { macroSnapshotDoc } from "@/entities/portfolio-graph/templates";
import type { AllocationModel, ConstraintsInput } from "@/entities/allocation";
import type { HandoffTarget, WizardAlias } from "@/widgets/portfolio-graph";
import { STAGES, WIZARD_GATE_HREF, useAllocation } from "@/widgets/allocation/AllocationProvider";
import { WIZARD_NODE_MAP } from "./wizardNodeMap";

// 케이스 바는 react-query·배지를 싣는다 — 첫 로드(기준 120 kB)를 키우지 않게 따로 싣는다(BL2b).
const CaseBar = dynamic(() => import("@/features/case-bar/CaseBar"), { ssr: false });

// reactflow 는 무겁다 — 첫 로드에서 빼고 캔버스 청크로 싣는다(ADR 002 §2).
const PortfolioCanvas = dynamic(() => import("@/widgets/portfolio-graph/PortfolioCanvas"), {
  ssr: false,
  loading: () => (
    <div className="pg-loading"><Loader2 size={18} className="spin" /> 노드 캔버스를 불러오는 중…</div>
  ),
});

/** 넘길 수 있는 도구 — 마법사 세션의 보유·뷰·모델을 읽는 단계들. */
const HANDOFF_TARGETS: HandoffTarget[] = (["/allocation/optimize", "/allocation/stress", "/allocation/timing",
  "/allocation/explain", "/allocation/execution", "/allocation/journal"] as const)
  .map((href) => ({ href, label: `${STAGES.find((s) => s.href === href)?.title ?? href}에서 보기` }));

/** 팔레트 검색 별칭 — 마법사 화면 이름(`06 STRESS Stress`)으로 그 일을 하는 노드를 찾는다 (BK W6). */
const WIZARD_ALIASES: WizardAlias[] = STAGES.map((s) => ({
  name: `${s.n} ${s.label} ${s.title}`, short: `${s.n} ${s.label}`, nodes: WIZARD_NODE_MAP[s.href] }));

export default function AllocationCanvasPage() {
  const router = useRouter();
  const alloc = useAllocation();
  // 넘긴 뒤 **다음 렌더**에서 계산을 켠다 — 세터가 반영된 값으로 `/analyze` 를 불러야 한다.
  // 마법사는 하단 nav 로 검증 단계에 들어갈 때만 스스로 재계산하므로, 직접 이동하면 결과가
  // 비어 있다. ★같은 경로(ensureFreshRun)★를 부를 뿐 계산을 새로 짜지 않는다.
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  // 다른 화면이 넘긴 흐름(BL2b) — `?snapshot=<id>`(매크로 화면의 국면 스냅샷). 주소는 브라우저에서만 읽는다
  // (정적 빌드에서 검색 파라미터를 기다리지 않게). 읽기 전(undefined)에는 캔버스를 그리지 않아 한 번만 싣는다.
  const [boot, setBoot] = useState<{ doc: GraphDoc; note: string } | null | undefined>(undefined);
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  useEffect(() => {
    const sid = new URLSearchParams(window.location.search).get("snapshot");
    setSnapshotId(sid);
    setBoot(sid ? { doc: macroSnapshotDoc(sid),
                    note: `매크로 화면에서 가져온 국면 스냅샷 ${sid}로 ‘매크로 스냅샷 반영’ 흐름을 열었어요.` } : null);
  }, []);
  useEffect(() => {
    if (!pendingHref) return;
    alloc.ensureFreshRun();
    router.push(pendingHref);
    setPendingHref(null);
  }, [pendingHref, alloc, router]);

  const handoff = (p: HandoffPayload, target: HandoffTarget) => {
    alloc.setHoldingsReset(p.tickers.map((code) => ({
      code, name: p.labels[code] ?? code, weight: Math.round((p.weightsPct[code] ?? 0) * 100) / 100,
    })));
    alloc.setViewsLogged(p.views);
    alloc.setModel(p.model as AllocationModel);
    if (p.delta !== undefined) alloc.setDelta(p.delta);
    if (p.tau !== undefined) alloc.setTau(p.tau);
    alloc.setConstraints((p.constraints as ConstraintsInput | null) ?? null);
    alloc.setGoal({ id: "canvas", label: "노드 캔버스에서 넘김" });
    alloc.logEvent(`노드 캔버스에서 넘김 — ${p.model.toUpperCase()} · ${p.tickers.length}자산 · 뷰 ${p.views.length}개`);
    setPendingHref(target.href);
  };

  return (
    <div className="aas-root pg-page">
      {boot !== undefined && <PortfolioCanvas initialDoc={boot} onHandoff={handoff} handoffTargets={HANDOFF_TARGETS} wizardAliases={WIZARD_ALIASES} topExtra={<>
        {/* 연구 케이스 — 매크로 화면과 같은 케이스 바. 캔버스 높이를 뺏지 않게 상단 바에서 펼친다(BL2b). */}
        <details className="pg-wizard pg-casebox">
          <summary className="pg-btn pg-btn--ghost" title="연구 케이스">케이스</summary>
          <div className="pg-casebox-panel"><CaseBar sessionSnapshotId={snapshotId} /></div>
        </details>
        <details className="pg-wizard">
          <summary className="pg-btn pg-btn--ghost">단계별 마법사</summary>
          <nav className="pg-wizard-links" aria-label="마법사 도구">
            <p className="pg-wizard-links-why">같은 도구를 단계별 화면으로 쓰고 싶을 때 열어요. 팔레트에서 화면 이름으로 찾으면 그 일을 하는 노드가 나와요.</p>
            <Link href={WIZARD_GATE_HREF} className="pg-wizard-link">목표 선택</Link>
            {STAGES.map((s) => (
              <Link key={s.href} href={s.href} className="pg-wizard-link">{s.title}</Link>
            ))}
          </nav>
        </details>
      </>} />}
    </div>
  );
}
