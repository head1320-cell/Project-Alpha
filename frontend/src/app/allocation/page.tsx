"use client";
// /allocation = AAS 노드 캔버스 (BI3·BI4 · ADR 002 · 사용자 결정).
// 포트폴리오를 노드-링크 그래프로 설계·분석한다. 계산은 백엔드 그래프 실행기가 한다.
//
// ★단계별 마법사는 지웠다(BL4)★ — 모든 단계의 도구가 노드·서랍·저장 버튼이 된 뒤, 마법사 E2E 가 지키던 계약을 캔버스로
// 옮기고 지웠다(대응표 docs/specs/2026-09-27-bl4-wizard-contract-map.md). 옛 주소 `/allocation/<화면>` 은
// next.config.js 의 redirects 가 `?from=<화면>` 으로 이리 보낸다 — 캔버스가 그 화면의 일을 어디서 하는지 안내한다.
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";
import type { GraphDoc } from "@/entities/portfolio-graph";
// 템플릿 하나만 — 엔티티 전체(api·검증·포맷)를 첫 로드에 싣지 않는다.
import { macroSnapshotDoc } from "@/entities/portfolio-graph/templates";
import { LEGACY_SCREENS, isLegacyScreenKey, type LegacyScreen } from "@/entities/portfolio-graph/legacyScreens";

// 케이스 바는 react-query·배지를 싣는다 — 첫 로드(기준 120 kB)를 키우지 않게 따로 싣는다(BL2b).
const CaseBar = dynamic(() => import("@/features/case-bar/CaseBar"), { ssr: false });

// reactflow 는 무겁다 — 첫 로드에서 빼고 캔버스 청크로 싣는다(ADR 002 §2).
const PortfolioCanvas = dynamic(() => import("@/widgets/portfolio-graph/PortfolioCanvas"), {
  ssr: false,
  loading: () => (
    <div className="pg-loading"><Loader2 size={18} className="spin" /> 노드 캔버스를 불러오는 중…</div>
  ),
});

export default function AllocationCanvasPage() {
  // 다른 화면이 넘긴 흐름(BL2b) — `?snapshot=<id>`(매크로 화면의 국면 스냅샷) · `?from=<예전 화면>`(BL4 옛 주소).
  // 주소는 브라우저에서만 읽는다(정적 빌드에서 검색 파라미터를 기다리지 않게). 읽기 전(undefined)에는 캔버스를 그리지 않아 한 번만 싣는다.
  const [boot, setBoot] = useState<{ doc: GraphDoc; note: string } | null | undefined>(undefined);
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const [legacy, setLegacy] = useState<LegacyScreen | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const sid = q.get("snapshot");
    const from = q.get("from");
    setSnapshotId(sid);
    // 모르는 `from` 은 무시한다 — 지어낸 안내를 띄우지 않는다.
    setLegacy(isLegacyScreenKey(from) ? LEGACY_SCREENS[from] : null);
    setBoot(sid ? { doc: macroSnapshotDoc(sid),
                    note: `매크로 화면에서 가져온 국면 스냅샷 ${sid}로 ‘매크로 스냅샷 반영’ 흐름을 열었어요.` } : null);
  }, []);

  return (
    <div className="aas-root pg-page">
      {boot !== undefined && <PortfolioCanvas initialDoc={boot} legacy={legacy} topExtra={
        // 연구 케이스 — 매크로 화면과 같은 케이스 바. 캔버스 높이를 뺏지 않게 상단 바에서 펼친다(BL2b).
        <details className="pg-casebox">
          <summary className="pg-btn pg-btn--ghost" title="연구 케이스">케이스</summary>
          <div className="pg-casebox-panel"><CaseBar sessionSnapshotId={snapshotId} /></div>
        </details>
      } />}
    </div>
  );
}
