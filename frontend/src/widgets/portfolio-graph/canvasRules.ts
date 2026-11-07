/**
 * 연결 규칙 글 (CF 3부 E2a — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변)
 * ==========================================================================
 * 같은 쪽 점 · 겹친 옛 문서 · 연결 규칙 하나(다시 꽂는 중인 선은 뺀다) — 끄는 중 선·놓은 뒤 토스트·다시 꽂기가 같은 말을 쓴다.
 */
import { useCallback } from "react";
import type { Connection, Edge, FinalConnectionState } from "@xyflow/react";
import { cardsOverlap, connectionProblem, type ConnTry } from "@/entities/portfolio-graph";
import { PORT_PLAIN } from "./GraphNode";
import { usePortfolioGraph, type DeleteResult } from "./store";

/**
 * 지우기 토스트(R2) — 무엇이 사라졌는지 센 그대로. 0 인 부분은 말하지 않는다(계산 전이면 결과·하류 말 없음).
 * 결과 = 지운 노드 중 결과가 최신이던 것 · 하류 = 지워서 새로 예전 결과가 된 노드. [되돌리기] 한 번이면 모두 돌아온다.
 */
export function deleteNote(r: DeleteResult | null): string | null {
  if (!r) return null;
  const head = r.nodes ? `노드 ${r.nodes}개를 지웠어요` : `선 ${r.edges}개를 끊었어요`;
  const more = [r.results ? `그중 ${r.results}개는 계산 결과가 있었어요` : "",
                r.downstream ? `하류 노드 ${r.downstream}개는 이제 예전 결과예요` : ""].filter(Boolean);
  return `${head}${more.length ? ` — ${more.join(" · ")}` : ""}.`;
}

/** 같은 쪽 점끼리 이으려 할 때의 사유 — 놓은 뒤 토스트·끄는 중 사유 글·다시 꽂기가 같은 말을 쓴다. */
export const SAME_SIDE = {
  source: "내는 점끼리는 이을 수 없어요 — 내는 점에서 받는 점으로 이어요.",
  target: "받는 점끼리는 이을 수 없어요 — 내는 점에서 받는 점으로 이어요.",
} as const;
/** CF1 — 예전 크기(폭 150)로 놓인 문서를 불러왔을 때. 자동으로 옮기지 않는다(사용자의 배치를 말없이 바꾸지 않음). */
export const OVERLAP_NOTE = "예전 크기로 놓인 문서라 노드가 겹쳐요. 위 도구줄의 ‘자동 정리’를 누르면 다시 놓아요.";
export function overlapping(): boolean {
  const st = usePortfolioGraph.getState();
  return cardsOverlap(st.nodes, st.catalog);
}
/** 연결 규칙 하나(타입·한 입력 한 선·순환) — 다시 꽂는 중인 선은 빼고 본다(CF2). */
export function wireProblem(c: ConnTry): string | null {
  const st = usePortfolioGraph.getState();
  const edges = st.reconnecting ? st.edges.filter((e) => e.id !== st.reconnecting) : st.edges;
  return connectionProblem(c, st.nodes, edges, st.catalog ?? [], st.catalogMeta?.portPlain ?? PORT_PLAIN);
}

/** 연결 검사 · 선 끝 다시 꽂기 처리(CF 3부 E2b — 본체에서 옮김 · 동작 불변). */
export function useWireHandlers() {
  // ── 연결 규칙: 타입 일치 · 입력 하나에 링크 하나 · 순환 금지 ──────────────
  // v12 는 선 다시 꽂기에도 같은 검사를 부르며 선(Edge)을 넘길 수 있다 — 연결 모양으로 맞춰 같은 규칙에 넣는다.
  const isValidConnection = useCallback((c: Connection | Edge) => {
    const conn: Connection = { source: c.source, target: c.target, sourceHandle: c.sourceHandle ?? null, targetHandle: c.targetHandle ?? null };
    return !wireProblem(conn);
  }, []);
  // ── 선 끝 다시 꽂기(CF2) — 옮기는 선은 검사에서 뺀다(그 선 자신 때문에 거부되지 않게). 빈 곳에 놓으면 선은 그대로. ──
  const onReconnectStart = useCallback((_: unknown, edge: Edge) => { usePortfolioGraph.getState().setReconnecting(edge.id); }, []);
  const onReconnect = useCallback((old: Edge, c: Connection) => {
    const st = usePortfolioGraph.getState();
    if (st.reconnect(old.id, c)) st.setNote("선을 옮겨 꽂았어요.", true);
  }, []);
  const onReconnectEnd = useCallback((_: unknown, edge: Edge, __: unknown, fin: FinalConnectionState) => {
    const st = usePortfolioGraph.getState();
    const to = fin.toHandle;
    if (to && !fin.isValid && fin.fromHandle) {
      const from = fin.fromHandle;
      const why = from.type === to.type
        ? (from.type === "source" ? SAME_SIDE.source : SAME_SIDE.target)
        : wireProblem(from.type === "source"
            ? { source: from.nodeId, sourceHandle: from.id ?? null, target: to.nodeId, targetHandle: to.id ?? null }
            : { source: to.nodeId, sourceHandle: to.id ?? null, target: from.nodeId, targetHandle: from.id ?? null });
      if (why) st.setNote(`${why} 선은 그대로 두었어요.`);
    }
    st.setReconnecting(null);
    void edge;
  }, []);
  return { isValidConnection, onReconnectStart, onReconnect, onReconnectEnd };
}
