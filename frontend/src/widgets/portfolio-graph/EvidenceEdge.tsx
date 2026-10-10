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
 */
import { memo } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "reactflow";
import { BRIEF_DX, type NodeLineage, type NodeStatus } from "@/entities/portfolio-graph";

export const PG_WIRE_TYPE = "pgWire";

export type WireEvidence = "plain" | "practice" | "blocked" | null;

export interface WireData {
  evidence: WireEvidence;
  /** 지금 시점 전용 — 실선·점선과 함께 올 수 있어 따로 둔다. */
  forward: boolean;
  brief: string | null;
  /** 포트 타입 쉬운 이름(BT4) — 올리거나 고르면 선 가운데에 보인다. */
  typeLabel?: string | null;
  hover?: boolean;
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

function EvidenceEdgeImpl({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data, selected }: EdgeProps<WireData>) {
  const [path, mx, my] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  // 라벨은 선 가운데가 아니라 ★원천 카드 바로 오른쪽 틈★에(BS2) — 가운데는 열을 건너뛰는 선에서 중간 카드 위에 떨어졌다
  // (실측: 확대 1 에서 라벨 17개 중 13개가 카드를 덮음). 라벨은 원천 포트의 요약이라 원천 옆이 맞는 자리이기도 하다.
  const lx = sourceX + BRIEF_DX;
  const ly = sourceY;
  return (
    <>
      {data?.forward && <path d={path} className="pg-wire-ticks" fill="none" style={{ stroke: style?.stroke }} />}
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      {data?.brief && (
        <EdgeLabelRenderer>
          <div className="pg-wire-brief" data-edge-id={id}
               style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}>{data.brief}</div>
        </EdgeLabelRenderer>
      )}
      {(data?.hover || selected) && data?.typeLabel && (
        <EdgeLabelRenderer>
          <div className="pg-wire-type" data-edge-id={id} style={{ transform: `translate(-50%, -50%) translate(${mx}px, ${my}px)` }}>
            {data.typeLabel}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const EvidenceEdge = memo(EvidenceEdgeImpl);
