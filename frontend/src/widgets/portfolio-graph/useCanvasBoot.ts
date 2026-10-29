"use client";
/**
 * 처음 열 때 — 카탈로그를 받아 넘겨받은 흐름 · 작업 중 문서 · 기본 사슬 중 하나를 싣는다
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · 본체의 같은 자리에서 부른다).
 */
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { CORE_CHAIN_TEMPLATE, parseFile, portfolioGraphApi, restackDoc, type GraphDoc, type WorkflowStage } from "@/entities/portfolio-graph";
import { readWip } from "./canvasConfig";
import { ZOOM_FAR } from "./canvasGeometry";
import { OVERLAP_NOTE, overlapping } from "./canvasRules";
import type { LeftTab } from "./NodePalette";
import { usePortfolioGraph } from "./store";

/** 넘겨받은 흐름 — `restack`(기본 예): 코드가 만든 흐름을 새 카드 높이로 다시 쌓는다 · `isolate`(PB3 고객 문서): 연 뒤 되돌리기 기록을
 *  비워 이전 캔버스(이 탭의 작업 중 문서)로 되돌아가 고객 문서에 섞이지 않게 한다. */
export type BootDoc = { doc: GraphDoc; note: string; restack?: boolean; isolate?: boolean };

export function useCanvasBoot(initialDoc: BootDoc | null | undefined, bootNote: string | null | undefined,
                              setStages: (st: WorkflowStage[]) => void, setFileNote: (n: string | null) => void,
                              setLeftTabState: Dispatch<SetStateAction<LeftTab | null>>, fit: (opts?: { minZoom?: number }) => void): boolean {
  // 처음 싣기가 끝났나(PB3) — 작업 중 문서는 이 뒤부터 남긴다. 그 전에 남기면 싣기 전 캔버스(예: 고객 모드를 떠나며 비운 캔버스)가
  // 이 탭의 작업 중 문서를 덮는다.
  const [booted, setBooted] = useState(false);
  // ── 카탈로그 → 복원(세션) 또는 기본 사슬 ──────────────────────────────
  useEffect(() => {
    let alive = true;
    portfolioGraphApi.nodeTypes()
      .then((cat) => {
        if (!alive) return;
        setStages(cat.stages ?? []);
        usePortfolioGraph.getState().setStages(cat.stages ?? []);
        usePortfolioGraph.getState().setCatalog(cat.nodes);
        usePortfolioGraph.getState().setCatalogMeta({ gates: cat.gates ?? [], portPlain: cat.port_plain ?? {} });
        const st = usePortfolioGraph.getState();
        if (initialDoc) {
          // 다른 화면이 넘긴 흐름(예: 매크로 스냅샷) — 지금 캔버스가 있으면 되돌리기로 돌아갈 수 있다(loadDoc 이 기록한다).
          st.loadDoc(initialDoc.restack === false ? initialDoc.doc : restackDoc(initialDoc.doc, cat.nodes));
          if (initialDoc.isolate) usePortfolioGraph.setState({ past: [], future: [] });
          setFileNote(initialDoc.note + (!initialDoc.isolate && st.past.length ? " 이전 캔버스는 되돌리기(Ctrl+Z)로 돌아가요." : ""));
        } else {
          const saved = readWip();
          const parsed = saved ? parseFile(saved) : null;
          if (st.nodes.length === 0) {
            // 코드가 만든 기본 사슬만 새 카드 높이로 다시 쌓는다(CF1). 작업 중 문서는 사용자의 배치라 그대로 두고, 겹치면 말만 한다.
            if (parsed?.doc) st.loadDoc(parsed.doc, parsed.problems);
            else st.loadDoc(restackDoc(CORE_CHAIN_TEMPLATE, cat.nodes));
            if (parsed?.doc && overlapping()) setFileNote(OVERLAP_NOTE);
          }
          if (bootNote) setFileNote(bootNote);
        }
        // BT2 — 고른 탭이 없으면 처음 한 번만 정한다: 빈 캔버스는 절차부터(노드를 붙여도 탭이 바뀌지 않게 저장하지 않고 고정).
        setLeftTabState((t) => t ?? (usePortfolioGraph.getState().nodes.length === 0 ? "proc" : "add"));
        // 처음 열 때만 보통 확대 이상(사용자 결정 2026-10-17) — 자리 고정 상자로 전체를 담으면 멀리(이름·값만)로 열렸다.
        // 넘치면 fitClear 가 흐름의 시작(왼쪽 위)에 붙인다. 맞춤 단추·자동 정리는 그대로 전체를 담는다.
        fit({ minZoom: ZOOM_FAR });
        setBooted(true);
      })
      .catch((e: Error) => { if (alive) usePortfolioGraph.getState().setCatalog(null, e.message); });
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 처음 한 번만(넘겨받은 흐름은 열 때 한 번 싣는다)
  }, []);
  return booted;
}
