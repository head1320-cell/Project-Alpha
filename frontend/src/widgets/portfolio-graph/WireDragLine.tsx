"use client";
/**
 * 끄는 중 연결선 (CF 3부 E2a — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변)
 */
import { useStore, type ConnectionLineComponentProps } from "@xyflow/react";
import { portColor as portTypeColor } from "@/entities/portfolio-graph/ports";
import { SAME_SIDE, wireProblem } from "./canvasRules";
import { usePortfolioGraph } from "./store";
import { wirePath } from "./wirePath";

/**
 * 끄는 중 연결선(CF2) — 보내는 타입 색의 곡선. 손잡이 위에 올렸는데 이을 수 없으면 선을 회색 점선으로 바꾸고, 왜 안 되는지를
 * 커서 옆에 ★보이는 글★로 쓴다(툴팁 아님). 글자는 확대와 상관없이 화면 12px(= 12 / 확대율). 문장은 놓은 뒤 토스트와 같다.
 */
export function WireDragLine({ fromX, fromY, toX, toY, fromPosition, toPosition, fromHandle, toHandle, connectionStatus }: ConnectionLineComponentProps) {
  const zoom = useStore((st) => st.transform[2]);
  const st = usePortfolioGraph.getState();
  const kind = st.nodes.find((n) => n.id === fromHandle.nodeId)?.data.kind;
  const entry = st.catalog?.find((c) => c.type === kind);
  const type = (fromHandle.type === "source" ? entry?.outputs : entry?.inputs)?.find((p) => p.name === fromHandle.id)?.type;
  const bad = connectionStatus === "invalid";
  let why: string | null = null;
  if (bad && toHandle) {
    why = toHandle.type === fromHandle.type ? SAME_SIDE[fromHandle.type]
      : wireProblem(fromHandle.type === "source"
          ? { source: fromHandle.nodeId, sourceHandle: fromHandle.id ?? null, target: toHandle.nodeId, targetHandle: toHandle.id ?? null }
          : { source: toHandle.nodeId, sourceHandle: toHandle.id ?? null, target: fromHandle.nodeId, targetHandle: fromHandle.id ?? null });
  }
  const shape = usePortfolioGraph((x) => x.wireShape);
  const { d } = wirePath(shape, { x: fromX, y: fromY }, { x: toX, y: toY }, [], { s: fromPosition, t: toPosition });
  const k = 1 / (zoom || 1);
  // 사유 글은 끌어 온 쪽에 쓴다 — 오른쪽으로 끌면 커서 왼쪽(오른쪽 판 밑으로 잘리지 않게), 왼쪽으로 끌면 커서 오른쪽. " — " 에서 두 줄로.
  const back = toX >= fromX;
  const tx = toX + (back ? -14 : 14) * k;
  const lines = why ? why.split(" — ") : [];
  return (
    <g className={`pg-drag-wire${bad ? " pg-drag-wire--bad" : ""}`} data-type={type ?? ""}>
      <path d={d} fill="none" stroke={bad ? "var(--pg-mute)" : type ? portTypeColor(type) : "var(--pg-blue)"}
            strokeWidth={2.5 * k} strokeDasharray={bad ? `${6 * k} ${4 * k}` : undefined} />
      {why && (
        <text className="pg-drag-why" x={tx} y={toY - (12 + 16 * (lines.length - 1)) * k} textAnchor={back ? "end" : "start"}
              fontSize={12 * k} strokeWidth={4 * k} role="status">
          {lines.map((l, i) => <tspan key={i} x={tx} dy={i ? 16 * k : 0}>{i ? ` — ${l}` : l}</tspan>)}
        </text>
      )}
    </g>
  );
}
