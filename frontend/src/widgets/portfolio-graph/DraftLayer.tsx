"use client";
/**
 * 말로 설계(AI4)의 캔버스 미리보기 — ★문서가 아니다★(`ViewportPortal` — 노드 목록·저장·계산·미니맵에 들어가지 않는다). 유령(CF6)과 같은 결.
 *  · 더할 노드 = 점선 카드(`.pg-draft-node`, 단계 색) + 넣을 값 · 이을 선 = 점선(`.pg-draft-wire`, 유령끼리도) ·
 *    값이 바뀔 지금 노드 = 점선 테두리(`.pg-draft-touched`) + "말씀에서 값 n개".
 *  · 누름을 받지 않는다 — 받아들이기·버리기는 왼쪽 창 '말로' 탭에서. 자리는 `placeDraft`(받아들이면 같은 자리에 놓인다).
 */
import { Position, useStore, ViewportPortal } from "@xyflow/react";
import { cardHeight, NODE_W, PORT_GAP, PORT_TOP, type DraftBody, type NodeCatalogEntry } from "@/entities/portfolio-graph";
import { handleAt } from "./GhostLayer";
import { STAGE_VAR } from "./GraphNode";
import { wirePath, type WireShape } from "./wirePath";

type Pt = { x: number; y: number };
interface DraftWire { id: string; d: string }
interface Touched { id: string; x: number; y: number; w: number; h: number }

export function DraftLayer({ draft, at, catalog, shape }: {
  draft: DraftBody; at: Record<string, Pt>; catalog: NodeCatalogEntry[] | null; shape: WireShape;
}) {
  const entryOf = (kind: string) => catalog?.find((c) => c.type === kind);
  const fresh = new Map(draft.add.map((a) => [a.id, a]));
  /** 더할 노드의 포트 자리 — 진짜 카드와 같은 줄(`PORT_TOP + i·PORT_GAP`). */
  const portAt = (id: string, side: "in" | "out", name: string): Pt | null => {
    const a = fresh.get(id);
    const p = at[id];
    if (!a || !p) return null;
    const list = (side === "in" ? entryOf(a.kind)?.inputs : entryOf(a.kind)?.outputs) ?? [];
    const i = Math.max(0, list.findIndex((x) => x.name === name));
    return { x: p.x + (side === "in" ? 0 : NODE_W), y: p.y + PORT_TOP + i * PORT_GAP };
  };
  const touchedIds = [...new Set(draft.set.map((x) => x.node).filter((id) => !fresh.has(id)))];
  // 선 끝·테두리는 진짜 노드의 실측 — 노드를 옮기면 따라온다. 문자열로 비교해 같은 자리면 다시 그리지 않는다.
  const key = useStore((st) => {
    const wires: DraftWire[] = [];
    for (const c of draft.connect) {
      const s = fresh.has(c.source) ? portAt(c.source, "out", c.source_port) : handleAt(st.nodeLookup.get(c.source), "source", c.source_port);
      const t = fresh.has(c.target) ? portAt(c.target, "in", c.target_port) : handleAt(st.nodeLookup.get(c.target), "target", c.target_port);
      if (!s || !t) continue;
      wires.push({ id: c.id, d: wirePath(shape, s, t, [], { s: Position.Right, t: Position.Left }).d });
    }
    const touched: Touched[] = touchedIds.flatMap((id) => {
      const n = st.nodeLookup.get(id);
      if (!n) return [];
      const p = n.internals.positionAbsolute;
      return [{ id, x: p.x, y: p.y, w: n.measured?.width ?? NODE_W, h: n.measured?.height ?? 0 }];
    });
    return JSON.stringify({ wires, touched });
  });
  const { wires, touched } = JSON.parse(key) as { wires: DraftWire[]; touched: Touched[] };
  return (
    <ViewportPortal>
      <div className="pg-drafts" aria-label="말로 설계 초안 미리보기">
        <svg className="pg-draft-wires" aria-hidden="true">
          {wires.map((w) => <g key={w.id} className="pg-draft-wire" data-id={w.id}><path d={w.d} /></g>)}
        </svg>
        {touched.map((t) => {
          const n = draft.set.filter((x) => x.node === t.id).length;
          return (
            <div key={t.id} className="pg-draft-touched" data-node-id={t.id}
                 style={{ transform: `translate(${t.x - 6}px, ${t.y - 6}px)`, width: t.w + 12, height: t.h + 12 }}>
              <span className="pg-draft-chip">말씀에서 값 {n}개</span>
            </div>
          );
        })}
        {draft.add.map((a) => {
          const p = at[a.id];
          if (!p) return null;
          const entry = entryOf(a.kind);
          const vals = draft.set.filter((x) => x.node === a.id);
          return (
            <div key={a.id} className="pg-draft-node" data-id={a.id} data-kind={a.kind} role="group" aria-label={`초안: ${a.label} 더하기`}
                 style={{ transform: `translate(${p.x}px, ${p.y}px)`, width: NODE_W, height: cardHeight(a.kind, catalog),
                          ["--pg-stage" as string]: STAGE_VAR[entry?.stage ?? ""] ?? "var(--pg-st-data)" }}>
              <div className="pg-draft-head">
                <span className="pg-draft-tag">말로 설계</span>
                <span className="pg-draft-name">{a.label}</span>
              </div>
              {vals.length > 0 && (
                <ul className="pg-draft-vals">
                  {vals.map((x) => <li key={x.field} className="pg-draft-val">{x.label} <b>{x.display}</b></li>)}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </ViewportPortal>
  );
}
