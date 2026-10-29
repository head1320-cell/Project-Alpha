"use client";
// /allocation = AAS 노드 캔버스 (BI3·BI4 · ADR 002 · 사용자 결정).
// 포트폴리오를 노드-링크 그래프로 설계·분석한다. 계산은 백엔드 그래프 실행기가 한다.
//
// ★단계별 마법사는 지웠다(BL4)★ — 모든 단계의 도구가 노드·서랍·저장 버튼이 된 뒤, 마법사 E2E 가 지키던 계약을 캔버스로
// 옮기고 지웠다(대응표 docs/specs/2026-09-27-bl4-wizard-contract-map.md). 옛 주소 `/allocation/<화면>` 은
// next.config.js 의 redirects 가 `?from=<화면>` 으로 이리 보낸다 — 캔버스가 그 화면의 일을 어디서 하는지 안내한다.
import { Suspense, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
// 타입만 — 고객 문서 모드(PB3)의 코드는 열 때 따로 싣는다.
import type { ClientDocCtx } from "@/widgets/portfolio-graph/clientMode";
import type { BootDoc } from "@/widgets/portfolio-graph/useCanvasBoot";
// 템플릿 하나만 — 엔티티 전체(api·검증·포맷)를 첫 로드에 싣지 않는다.
import { macroSnapshotDoc } from "@/entities/portfolio-graph/templates";
import { LEGACY_SCREENS, isLegacyScreenKey, type LegacyScreen } from "@/entities/portfolio-graph/legacyScreens";
// "설계에 넣기"(BU2) — 종목 찾기·홈이 넘긴 `?tickers=`. stock_master 로 확인한 종목만 싣는다(tickerBridge 가 판정).
import { bridgeFromTickers, bridgeFromCompany } from "@/entities/portfolio-graph/tickerBridge";

// 케이스 바는 react-query·배지를 싣는다 — 첫 로드(기준 120 kB)를 키우지 않게 따로 싣는다(BL2b).
const CaseBar = dynamic(() => import("@/features/case-bar/CaseBar"), { ssr: false });

const Loading = () => <div className="pg-loading"><Loader2 size={18} className="spin" /> 노드 캔버스를 불러오는 중…</div>;

// React Flow 는 무겁다 — 첫 로드에서 빼고 캔버스 청크로 싣는다(ADR 002 §2).
const PortfolioCanvas = dynamic(() => import("@/widgets/portfolio-graph/PortfolioCanvas"), { ssr: false, loading: Loading });
// PB3 고객 칩 — 고객 문서를 열 때만 싣는다.
const ClientDocChip = dynamic(() => import("@/widgets/portfolio-graph/ClientDocChip").then((m) => m.ClientDocChip), { ssr: false });

/**
 * 고객 문서(PB3 — `?client=`)를 열고 닫을 때 캔버스를 새로 세운다 — 같은 주소(`/allocation`) 안에서 메뉴로 일반 캔버스로 나가도
 * 고객 칩·고객 문서가 남지 않게(고객 모드를 떠나면 칩이 캔버스를 비우고, 새 캔버스가 이 탭의 작업 중 문서를 싣는다).
 * 첫 저장 뒤 주소에 `doc=` 이 붙어도 고객이 같으면 그대로 둔다.
 */
export default function AllocationCanvasPage() {
  return <Suspense fallback={<Loading />}><Keyed /></Suspense>;
}

function Keyed() {
  const cid = useSearchParams().get("client");
  return <AllocationCanvas key={cid ? `client:${cid}` : "generic"} />;
}

function AllocationCanvas() {
  // 다른 화면이 넘긴 흐름(BL2b) — `?snapshot=<id>`(매크로 화면의 국면 스냅샷) · `?from=<예전 화면>`(BL4 옛 주소) ·
  // `?tickers=`(종목 찾기·홈·기업 분석의 설계에 넣기) · `?company=`(기업 분석의 가정형 모형 → 기업 하나 깊게, BU6a+).
  // 주소는 브라우저에서만 읽는다(정적 빌드에서 검색 파라미터를 기다리지 않게). 읽기 전(undefined)에는 캔버스를 그리지 않아 한 번만 싣는다.
  const [boot, setBoot] = useState<BootDoc | null | undefined>(undefined);
  // PB3 — 고객 문서를 여는 중이면 그 고객·문서(칩이 쓴다). 이때는 이 탭의 작업 중 문서를 남기지 않는다.
  const [client, setClient] = useState<ClientDocCtx | null>(null);
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const [legacy, setLegacy] = useState<LegacyScreen | null>(null);
  // 넘겨받은 것을 싣지 못했을 때(예: 종목 이름 확인 실패) 문서 없이 말만 전한다 — 지금 캔버스는 그대로 둔다.
  const [bootNote, setBootNote] = useState<string | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const sid = q.get("snapshot");
    const from = q.get("from");
    const tickers = q.get("tickers");
    const cid = q.get("client");
    if (cid) {
      // 고객 문서(PB3) — 로그인·소유 확인은 서버가 한다. 못 열면 사유를 말하고 일반 캔버스로.
      let alive = true;
      void import("@/widgets/portfolio-graph/clientMode")
        .then((m) => m.openClientDoc(cid, q.get("doc"), q.get("new")))
        .then((r) => {
          if (!alive) return;
          if (r.ok) { setClient(r.ctx); setBoot(r.boot); } else { setBootNote(r.note); setBoot(null); }
        });
      return () => { alive = false; };
    }
    setSnapshotId(sid);
    // 모르는 `from` 은 무시한다 — 지어낸 안내를 띄우지 않는다.
    setLegacy(isLegacyScreenKey(from) ? LEGACY_SCREENS[from] : null);
    if (sid) {
      setBoot({ doc: macroSnapshotDoc(sid), note: `매크로 화면에서 가져온 국면 스냅샷 ${sid}로 ‘매크로 스냅샷 반영’ 흐름을 열었어요.` });
      return;
    }
    const company = q.get("company");
    if (tickers === null && company === null) { setBoot(null); return; }
    let alive = true;
    // `?company=`(기업 분석 → 기업 하나 깊게) 가 `?tickers=` 보다 먼저 — 둘 다 같은 확인 규칙(stock_master).
    void (company !== null ? bridgeFromCompany(company) : bridgeFromTickers(tickers)).then((b) => {
      if (!alive) return;
      if (b && b.doc) setBoot({ doc: b.doc, note: b.note });
      else { setBootNote(b?.note ?? null); setBoot(null); }
    });
    return () => { alive = false; };
  }, []);

  return (
    <div className="aas-root pg-page">
      {boot !== undefined && <PortfolioCanvas initialDoc={boot} bootNote={bootNote} legacy={legacy} persistWip={!client} topExtra={<>
        {client && <ClientDocChip ctx={client} />}
        {/* 연구 케이스 — 매크로 화면과 같은 케이스 바. 캔버스 높이를 뺏지 않게 상단 바에서 펼친다(BL2b). */}
        <details className="pg-casebox">
          <summary className="pg-btn pg-btn--ghost" title="연구 케이스">케이스</summary>
          <div className="pg-casebox-panel"><CaseBar sessionSnapshotId={snapshotId} /></div>
        </details>
      </>} />}
    </div>
  );
}
