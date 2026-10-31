"use client";
/**
 * 증거 선 (BM C1 · Grasshopper 의 "선 모양 = 흐르는 데이터의 종류")
 * ==========================================================================
 * 선 색은 여전히 포트 타입(무엇이 흐르나), **선 모양은 계보**(어떤 근거로 흐르나) — 원천 노드의 서버 `lineage`·상태:
 *   실선         = 연습용 합성이 아님. ★'실데이터' 라고 부르지 않는다★ — DB 적재분의 등급은 미상일 수 있고, 그 등급은 노드가 말한다.
 *   점선         = 연습용(합성) 값이 흐른다(`lineage.practice`).
 *   가로 눈금    = 지금 시점 전용 — 과거 검증에 쓸 수 없는 값(`lineage.pit === "forward_only"`).
 *   끊긴 회색    = 원천이 막힘·실패라 값이 흐르지 않았다.
 * 계산 전·낡은 결과면 모양을 입히지 않는다(모르는 것을 주장하지 않는다). 선 가운데의 한 줄은 서버 `briefs` 다.
 * CF4c — 길은 보기 메뉴의 선 모양(곡선·직각·직선)과 문서의 경유점을 따른다(`wirePath`). 선을 두 번 누르면 그 자리에 경유점을
 * 끼우고, 고르거나 올린 선의 점은 끌어 옮기고 두 번 누르거나 Delete 로 지운다. 경유점은 화면 정보다(서버는 읽지 않는다).
 */
import { memo, useRef, useState, type MouseEvent } from "react";
import { BaseEdge, EdgeLabelRenderer, useReactFlow, type Edge, type EdgeProps } from "@xyflow/react";
import { BRIEF_DX, FLAG_DX, type NodeLineage, type NodeStatus } from "@/entities/portfolio-graph";
import type { WireFlag } from "./wireStyle";
import { insertAt, snapPt, wirePath, type Pt } from "./wirePath";
import { usePortfolioGraph } from "./store";
import { WireToolbar, type WireToolFn } from "./WireToolbar";

export const PG_WIRE_TYPE = "pgWire";

export type WireEvidence = "plain" | "practice" | "blocked" | null;

export type WireData = {
  evidence: WireEvidence;
  /** 지금 시점 전용 — 실선·점선과 함께 올 수 있어 따로 둔다. */
  forward: boolean;
  brief: string | null;
  /** 포트 타입 쉬운 이름(BT4) — 올리거나 고르면 선 가운데에 보인다. */
  typeLabel?: string | null;
  hover?: boolean;
  /** 계산 중 — 흐르는 점(CF3b1). xyflow `animated` 는 쓰지 않는다: 그 규칙은 선 안의 모든 path 를 대시로 바꿔 눈금을 지웠다. */
  flow?: boolean;
  /** 전달 점검(CF3b2) — 문제가 있을 때만. 받는 쪽 끝에 단추 하나, 누르면 선 판의 문제 줄로. */
  flag?: WireFlag | null;
  onFlag?: (edgeId: string) => void;
  /** 경유점(CF4c) — 문서의 `edges[].waypoints`. 접힌 상자의 대리 선에는 싣지 않는다(끝이 바뀌었다). */
  waypoints?: Pt[];
  /** 접힌 상자의 대리 선(R5) — 실제 끝이 상자 안에 숨어 있어 도구줄을 띄우지 않는다. */
  proxy?: boolean;
  /** 선 도구줄 동작(R5) — 우클릭 메뉴와 같은 길로 캔버스가 받는다. */
  onTool?: WireToolFn;
}

/** 원천 노드 결과 → 선 모양. 결과가 없거나 낡았으면 `null`(모양 없음). */
export function wireOf(src: { status: NodeStatus; lineage?: NodeLineage } | undefined, brief: string | null | undefined): WireData {
  if (!src) return { evidence: null, forward: false, brief: null };
  if (src.status !== "ok") return { evidence: "blocked", forward: false, brief: null };
  return {
    evidence: src.lineage?.practice ? "practice" : "plain",
    forward: src.lineage?.pit === "forward_only",
    brief: brief ?? null,
  };
}

export const WIRE_LEGEND: { key: string; label: string; help: string }[] = [
  { key: "plain", label: "실선", help: "연습용 합성이 아니에요 — 데이터 등급은 노드에서 확인해요" },
  { key: "practice", label: "점선", help: "연습용(합성) 값이 흘러요" },
  { key: "forward", label: "눈금", help: "지금 시점 전용 — 과거 검증에 쓸 수 없어요" },
  { key: "blocked", label: "끊긴 회색", help: "앞 단계가 막히거나 실패해 값이 흐르지 않았어요" },
];

function EvidenceEdgeImpl({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data, selected }: EdgeProps<Edge<WireData>>) {
  const shape = usePortfolioGraph((st) => st.wireShape);
  const via = data?.waypoints ?? [];
  const src = { x: sourceX, y: sourceY }, tgt = { x: targetX, y: targetY };
  const { d: path, mid } = wirePath(shape, src, tgt, via, { s: sourcePosition, t: targetPosition });
  const mx = mid.x, my = mid.y;
  const { screenToFlowPosition } = useReactFlow();
  // 두 번 누르기 = 경유점 끼우기(가장 가까운 구간 뒤). 캔버스의 두 번 누르기 확대는 선에서 일어나지 않는다(xyflow 가 선에 nopan 을 붙인다).
  const addHere = (ev: MouseEvent) => {
    const p = snapPt(screenToFlowPosition({ x: ev.clientX, y: ev.clientY }));
    usePortfolioGraph.getState().addWaypoint(id, insertAt(src, tgt, via, p), p);
  };
  // 점 끌기 — 끌기 시작(첫 움직임)에 되돌리기 한 번을 남긴다. 점에 올라가 있는 동안은 선을 벗어나도 점을 숨기지 않는다.
  const drag = useRef<{ i: number; moved: boolean } | null>(null);
  const [overDot, setOverDot] = useState(false);
  const [dragging, setDragging] = useState(false);
  const showDots = selected || !!data?.hover || overDot || dragging;
  // 라벨은 선 가운데가 아니라 ★원천 카드 바로 오른쪽 틈★에(BS2) — 가운데는 열을 건너뛰는 선에서 중간 카드 위에 떨어졌다
  // (실측: 확대 1 에서 라벨 17개 중 13개가 카드를 덮음). 라벨은 원천 포트의 요약이라 원천 옆이 맞는 자리이기도 하다.
  const lx = sourceX + BRIEF_DX;
  const ly = sourceY;
  return (
    <>
      {data?.forward && <path d={path} className="pg-wire-ticks" fill="none" style={{ stroke: style?.stroke }} />}
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} interactionWidth={0} />
      <path d={path} fill="none" strokeOpacity={0} strokeWidth={20} className="react-flow__edge-interaction" onDoubleClick={addHere} />
      {data?.flow && <path d={path} className="pg-wire-flowdots" fill="none" style={{ stroke: style?.stroke }} />}
      {data?.brief && (
        <EdgeLabelRenderer>
          <div className="pg-wire-brief" data-edge-id={id}
               style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}>{data.brief}</div>
        </EdgeLabelRenderer>
      )}
      {data?.flag && (
        <EdgeLabelRenderer>
          <button type="button" className="pg-wire-flag nodrag nopan" data-edge-id={id} data-level={data.flag.level} data-count={data.flag.count}
                  aria-label={`전달 점검 ${data.flag.count}건: ${data.flag.first}`}
                  style={{ transform: `translate(-50%, -50%) translate(${targetX - FLAG_DX}px, ${targetY}px)` }}
                  onClick={(ev) => { ev.stopPropagation(); data.onFlag?.(id); }}>
            <span className="pg-wire-flag-n">{data.flag.count}</span>
          </button>
        </EdgeLabelRenderer>
      )}
      {via.length > 0 && (
        <EdgeLabelRenderer>
          {via.map((p, i) => (
            <button key={i} type="button" className="pg-waypoint nodrag nopan" data-edge-id={id} data-i={i} data-show={showDots || undefined}
                    aria-label={`경유점 ${i + 1} — 끌어서 옮기고, 두 번 누르거나 Delete 로 지워요`}
                    style={{ transform: `translate(-50%, -50%) translate(${p.x}px, ${p.y}px)` }}
                    onPointerEnter={() => setOverDot(true)} onPointerLeave={() => setOverDot(false)}
                    onPointerDown={(ev) => { ev.stopPropagation(); ev.currentTarget.setPointerCapture(ev.pointerId); drag.current = { i, moved: false }; setDragging(true); }}
                    onPointerMove={(ev) => {
                      const g = drag.current;
                      if (!g || g.i !== i) return;
                      usePortfolioGraph.getState().moveWaypoint(id, i, snapPt(screenToFlowPosition({ x: ev.clientX, y: ev.clientY })), !g.moved);
                      g.moved = true;
                    }}
                    onPointerUp={(ev) => { ev.currentTarget.releasePointerCapture(ev.pointerId); drag.current = null; setDragging(false); }}
                    onDoubleClick={(ev) => { ev.stopPropagation(); usePortfolioGraph.getState().removeWaypoint(id, i); }}
                    onKeyDown={(ev) => {
                      if (ev.key !== "Delete" && ev.key !== "Backspace") return;
                      ev.preventDefault();
                      ev.stopPropagation();                // 선 지우기(Delete)로 번지지 않게
                      usePortfolioGraph.getState().removeWaypoint(id, i);
                    }} />
          ))}
        </EdgeLabelRenderer>
      )}
      {(data?.hover || selected) && data?.typeLabel && (
        <EdgeLabelRenderer>
          <div className="pg-wire-type" data-edge-id={id} style={{ transform: `translate(-50%, -50%) translate(${mx}px, ${my}px)` }}>
            {data.typeLabel}
          </div>
        </EdgeLabelRenderer>
      )}
      {selected && !data?.proxy && data?.onTool && <WireToolbar id={id} at={mid} via={via} onTool={data.onTool} />}
    </>
  );
}

export const EvidenceEdge = memo(EvidenceEdgeImpl);
