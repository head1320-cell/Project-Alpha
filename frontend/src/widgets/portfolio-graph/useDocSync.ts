"use client";
/**
 * 문서 따라가기 — 작업 중 문서를 이 탭에 보존 · 구조가 바뀌면 서버 검증
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · 본체의 같은 자리에서 부른다).
 */
import { useEffect, useMemo, useState } from "react";
import { portfolioGraphApi, type GraphDoc, type NodeCatalogEntry } from "@/entities/portfolio-graph";
import { WIP_KEY } from "./canvasConfig";
import { usePortfolioGraph } from "./store";

export function useDocSync(doc: GraphDoc, catalog: NodeCatalogEntry[] | null) {
  // ── 작업 중 상태 보존(편의용 — 신뢰 저장이 아니다. 저장은 내보내기) ─────────
  useEffect(() => {
    if (!catalog) return;
    try { sessionStorage.setItem(WIP_KEY, JSON.stringify(doc)); } catch { /* 용량 초과 등 — 편의 기능 */ }
  }, [doc, catalog]);

  // ── 구조가 바뀌면 서버 검증(위치 이동은 제외) ─────────────────────────
  // 경유점(CF4c)은 화면 정보라 뺀다 — 점을 끌 때마다 다시 검증하지 않는다.
  const structureKey = useMemo(() => JSON.stringify({
    n: doc.nodes.map((n) => [n.id, n.type, n.params]), e: doc.edges.map((e) => [e.id, e.source, e.source_port, e.target, e.target_port]),
  }), [doc]);
  // BT2 — 빈 캔버스도 검증한다(서버가 절차의 첫 걸음을 준다). 서버에 닿지 못하면 절차를 지어내지 않고 그렇다고 말한다.
  const [validateTick, setValidateTick] = useState(0);
  useEffect(() => {
    if (!catalog) { usePortfolioGraph.getState().setValidation(null); return; }
    const t = setTimeout(() => {
      portfolioGraphApi.validate(doc)
        .then((v) => usePortfolioGraph.getState().setValidation(v))
        .catch(() => { const g = usePortfolioGraph.getState(); g.setValidation(null); g.setValidationError(true); });
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 위치 변화로는 다시 검증하지 않는다
  }, [structureKey, catalog, validateTick]);
  return { setValidateTick };
}
