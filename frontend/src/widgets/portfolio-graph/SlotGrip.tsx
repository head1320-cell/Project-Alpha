"use client";
/**
 * 결과 칸 손잡이 (CF 3부 R3 — 사용자 결정 "결과 칸 높이만")
 * ==========================================================================
 * React Flow 의 크기 손잡이(아래 가장자리 선)를 ★결과 칸 높이★로 옮긴다 — 노드 크기는 store 가 버리고(`onNodesChange`),
 * 움직인 만큼을 결과 칸(`resizeSlot` — 기본 ~ 세 배)에 더한다. 카드 높이는 그 결과 칸으로 다시 계산된다(`nodeHeight`).
 * 끌기 한 번 = 되돌리기 한 단계(처음 바뀔 때 한 번만 기록).
 */
import { useRef } from "react";
import { NodeResizeControl, ResizeControlVariant } from "@xyflow/react";
import { slotHeight } from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "./store";

export function SlotGrip({ id, kind, slotH, minH, maxH }: { id: string; kind: string; slotH?: number; minH: number; maxH: number }) {
  const start = useRef<{ h: number; slot: number; recorded: boolean } | null>(null);
  return (
    <NodeResizeControl position="bottom" variant={ResizeControlVariant.Line} className="pg-node-resize" minHeight={minH} maxHeight={maxH}
                       onResizeStart={(_, p) => { start.current = { h: p.height, slot: slotHeight(kind, slotH), recorded: false }; }}
                       onResize={(_, p) => {
                         const s0 = start.current;
                         if (s0 && usePortfolioGraph.getState().resizeSlot(id, s0.slot + (p.height - s0.h), !s0.recorded)) s0.recorded = true;
                       }}
                       onResizeEnd={() => { start.current = null; }} />
  );
}
