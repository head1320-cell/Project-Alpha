"use client";
/**
 * 선 도구줄 (CF 3부 R5 — 사용자 결정 "고른 선 도구줄 + 선 우클릭" · 2026-10-31 "선 가운데 · 카드 위층")
 * ==========================================================================
 * 고른 선 하나에만 끊기 · 사이에 넣기 · 꺾는 점 · 묻기. React Flow `EdgeToolbar` 와 같은 변환(확대해도 크기 같음)을 쓰되 ★노드 위층★
 * (`ViewportPortal`)에 그린다 — 선 글자층은 카드 밑이라, 선이 카드 뒤를 지나면 도구줄이 깔려 누를 수 없었다. 자리는 그린 선 가운데(종류 알약 바로 위).
 * 동작은 `onTool` 하나로 캔버스가 받는다 — 우클릭 메뉴와 같은 길.
 */
import { useCallback, useLayoutEffect, useMemo, useRef, useState, type SyntheticEvent } from "react";
import { useStore, ViewportPortal } from "@xyflow/react";
import { ListPlus, MessageCircleQuestion, Scissors, Spline } from "lucide-react";
import { insertCandidates, josa, type InsertCandidate } from "@/entities/portfolio-graph";
import { useDismiss } from "./CanvasChrome";
import { PORT_PLAIN } from "./GraphNode";
import { usePortfolioGraph, type PgState } from "./store";
import type { Pt } from "./wirePath";

export type WireAction = "cut" | "insert" | "waypoint" | "ask";
export type WireToolFn = (edgeId: string, action: WireAction, arg?: InsertCandidate) => void;

/** 종류 알약(선 가운데) 위로 띄우는 거리 — 캔버스 좌표(알약 반 높이 + 조금). */
const PILL_GAP = 14;
/** 도구줄과 알약 사이 화면 여백 · 꺾는 점 반지름(화면 px — `.pg-waypoint` 12px). */
const GAP_PX = 6;
const DOT_R = 7;

/**
 * 도구줄 자리 — 알약 위가 기본, 그 자리가 이 선의 꺾는 점을 덮으면 알약 아래(점을 끌 수 없게 덮지 않는다 — R5 PNG·E2E 에서 찾음).
 * 둘 다 덮으면 덜 덮는 쪽(같으면 위). 크기는 화면에 그린 도구줄(확대와 무관)을 캔버스 좌표로 바꿔 잰다.
 */
export function toolbarPlace(at: Pt, via: Pt[], size: { w: number; h: number }, zoom: number): "above" | "below" {
  const halfW = (size.w / 2 + DOT_R) / zoom;
  const span = (place: "above" | "below"): [number, number] => (place === "above"
    ? [at.y - PILL_GAP - (GAP_PX + size.h + DOT_R) / zoom, at.y - PILL_GAP - (GAP_PX - DOT_R) / zoom]
    : [at.y + PILL_GAP + (GAP_PX - DOT_R) / zoom, at.y + PILL_GAP + (GAP_PX + size.h + DOT_R) / zoom]);
  const hits = (place: "above" | "below") => {
    const [y0, y1] = span(place);
    return via.filter((p) => Math.abs(p.x - at.x) < halfW && p.y > y0 && p.y < y1).length;
  };
  const up = hits("above");
  return up && hits("below") < up ? "below" : "above";
}

/** 선이 나르는 값의 타입과 쉬운 이름 — 보내는 노드의 출력 포트로(카탈로그). */
export function wireType(s: Pick<PgState, "edges" | "nodes" | "catalog" | "catalogMeta">, edgeId: string): { type: string | null; plain: string } {
  const e = s.edges.find((x) => x.id === edgeId);
  const kind = e && s.nodes.find((n) => n.id === e.source)?.data.kind;
  const type = s.catalog?.find((c) => c.type === kind)?.outputs.find((o) => o.name === e?.sourceHandle)?.type ?? null;
  return { type, plain: type ? (s.catalogMeta?.portPlain ?? PORT_PLAIN)[type] ?? type : "이 값" };
}
/** 넣을 노드가 없을 때의 까닭 — 도구줄 목록과 우클릭 메뉴가 같은 문장을 쓴다. */
export const insertNone = (plain: string) => `${josa(`‘${plain}’`, ["을", "를"])} 받아 ${josa(`‘${plain}’`, ["을", "를"])} 내는 노드가 없어요`;

/** 그린 선(화면의 path)에서 캔버스 좌표의 두 끝과 가운데 — 선 모양·경유점이 반영된 실제 선. */
export function drawnWire(edgeId: string): { src: Pt; tgt: Pt; mid: Pt } | null {
  const el = document.querySelector<SVGPathElement>(`.react-flow__edge[data-id="${CSS.escape(edgeId)}"] path.react-flow__edge-path`);
  if (!el) return null;
  const len = el.getTotalLength();
  const at = (t: number) => { const q = el.getPointAtLength(len * t); return { x: q.x, y: q.y }; };
  return { src: at(0), tgt: at(1), mid: at(0.5) };
}

/** 도구줄 안 누름이 선(React 나무로는 선의 자식)까지 번지면 선 누르기(오른쪽 창 열기)가 또 일어난다 — 여기서 멈춘다. */
const stop = (e: SyntheticEvent) => e.stopPropagation();

export function WireToolbar({ id, at, via, onTool }: { id: string; at: Pt; via: Pt[]; onTool: WireToolFn }) {
  const zoom = useStore((st) => st.transform[2]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  // 그린 도구줄의 화면 크기(목록은 절대 위치라 빠진다) — 처음엔 어림값, 그린 뒤 잰 값으로.
  const [size, setSize] = useState({ w: 300, h: 40 });
  useLayoutEffect(() => {
    const r = ref.current?.getBoundingClientRect();
    if (r && (Math.abs(r.width - size.w) > 1 || Math.abs(r.height - size.h) > 1)) setSize({ w: r.width, h: r.height });
  }, [size]);
  const place = toolbarPlace(at, via, size, zoom);
  const catalog = usePortfolioGraph((s) => s.catalog);
  const type = usePortfolioGraph((s) => wireType(s, id).type);
  const plain = usePortfolioGraph((s) => wireType(s, id).plain);
  const cands = useMemo(() => insertCandidates(type, catalog ?? []), [type, catalog]);
  useDismiss(open, useCallback(() => setOpen(false), []), ref);
  return (
    <ViewportPortal>
      <div ref={ref} className="pg-edge-tb nodrag nopan" data-edge-id={id} data-place={place} role="toolbar" aria-label="고른 선"
           style={{ transform: place === "above"
             ? `translate(${at.x}px, ${at.y - PILL_GAP}px) scale(${1 / zoom}) translate(-50%, -100%) translate(0, -${GAP_PX}px)`
             : `translate(${at.x}px, ${at.y + PILL_GAP}px) scale(${1 / zoom}) translate(-50%, 0) translate(0, ${GAP_PX}px)` }}
           onClick={stop} onPointerDown={stop} onMouseDown={stop} onDoubleClick={stop} onContextMenu={stop}>
        <button type="button" className="pg-edge-tb-b" data-action="cut" aria-label="이 선 끊기 — 토스트의 되돌리기나 Ctrl+Z 로 돌려요"
                onClick={() => onTool(id, "cut")}><Scissors size={14} aria-hidden="true" />끊기</button>
        <button type="button" className="pg-edge-tb-b" data-action="insert" aria-expanded={open} aria-haspopup="menu" aria-label="선 사이에 노드 넣기"
                onClick={() => setOpen((v) => !v)}><ListPlus size={14} aria-hidden="true" />사이에 넣기</button>
        <button type="button" className="pg-edge-tb-b" data-action="waypoint" aria-label="선 가운데에 꺾는 점 넣기 — 끌어서 길을 바꿔요"
                onClick={() => onTool(id, "waypoint")}><Spline size={14} aria-hidden="true" />꺾는 점</button>
        <button type="button" className="pg-edge-tb-b" data-action="ask" aria-label="이 선에 대해 AI 에게 묻기 — 오른쪽 창의 묻기 칸으로"
                onClick={() => onTool(id, "ask")}><MessageCircleQuestion size={14} aria-hidden="true" />묻기</button>
        {open && (
          <div className="pg-edge-tb-list" role="menu" aria-label="사이에 넣을 노드">
            {cands.length ? cands.map((c) => (
              <button key={c.kind} type="button" role="menuitem" className="pg-edge-tb-item" data-kind={c.kind}
                      onClick={() => { setOpen(false); onTool(id, "insert", c); }}>
                <b>{c.label}</b><span>{c.sub}</span>
              </button>
            )) : <p className="pg-edge-tb-empty">{insertNone(plain)}.</p>}
          </div>
        )}
      </div>
    </ViewportPortal>
  );
}
