"use client";
/**
 * 유령 노드(CF6) — 서버 규칙 추천(`procedure.next` · `by_gate`)을 캔버스 위에.
 * ★문서가 아니다★ — 노드 목록·저장·계산·미니맵에 들어가지 않는다(`ViewportPortal`). 진짜 카드 밑에 그리고 단추만 누름을 받는다 —
 * 카드나 빈 캔버스를 누르는 것을 가로채지 않는다. 자리는 `placeSuggestion`(옆 열 · 겹치면 그 아래 빈 자리) — [붙이기]가 같은 자리에 놓는다.
 * AI1 — 칩이 출처를 말한다: "규칙 추천" · "AI 추천"(서버 검사를 통과한 AI 이유) · 같은 추천이면 둘 다(규칙 글 + AI 이유 한 줄).
 */
import { Position, useStore, ViewportPortal, type InternalNode } from "@xyflow/react";
import { cardHeight, NEW_NODE, NODE_W, PORT_GAP, PORT_TOP, type Ghost, type NodeCatalogEntry } from "@/entities/portfolio-graph";
import { STAGE_VAR } from "./GraphNode";
import { wirePath, type WireShape } from "./wirePath";

/** 자리를 정한 유령 — 붙이는 추천은 카드 자리 `at`, 잇기만 하는 추천은 칩 자리 `chip`(둘 다 왼쪽 위 · 캔버스 좌표). */
export interface PlacedGhost extends Ghost { at: { x: number; y: number } | null; chip: { x: number; y: number } | null }

type Pt = { x: number; y: number };
interface GhostWire { ghost: string; from: string; to: string; action: string; d: string; mid: Pt }

/** 진짜 노드의 포트 가운데(캔버스 좌표) — 아직 재지 못했으면 null(그 선은 그리지 않는다). */
function handleAt(n: InternalNode | undefined, type: "source" | "target", id: string): Pt | null {
  const h = n?.internals.handleBounds?.[type]?.find((x) => x.id === id);
  if (!n || !h) return null;
  const p = n.internals.positionAbsolute;
  return { x: p.x + h.x + h.width / 2, y: p.y + h.y + h.height / 2 };
}

/** 유령 카드의 포트 자리 — 진짜 카드와 같은 줄(`PORT_TOP + i·PORT_GAP`). */
function ghostPort(g: PlacedGhost, entry: NodeCatalogEntry | undefined, side: "in" | "out", name: string): Pt {
  const list = (side === "in" ? entry?.inputs : entry?.outputs) ?? [];
  const i = Math.max(0, list.findIndex((p) => p.name === name));
  return { x: g.at!.x + (side === "in" ? 0 : NODE_W), y: g.at!.y + PORT_TOP + i * PORT_GAP };
}

/** 출처 칩 — 규칙 · AI · 둘 다. AI 칩은 따로 표시(`--ai`)해 규칙 추천으로 읽히지 않게 한다. */
function Chips({ g }: { g: PlacedGhost }) {
  return (
    <>
      {g.source === "rule" && <span className="pg-ghost-chip">규칙 추천</span>}
      {g.aiReason !== null && <span className="pg-ghost-chip pg-ghost-chip--ai">AI 추천</span>}
    </>
  );
}

/** 접근성 이름의 출처 — 칩과 같은 말. */
const sourceName = (g: PlacedGhost) => (g.source === "claude" ? "AI 추천" : g.aiReason !== null ? "규칙·AI 추천" : "규칙 추천");

export function GhostLayer({ ghosts, catalog, shape, hot, gateLabel, onApply, onDismiss }: {
  ghosts: PlacedGhost[]; catalog: NodeCatalogEntry[] | null; shape: WireShape; hot: string | null;
  gateLabel: (key: string) => string; onApply: (g: PlacedGhost) => void; onDismiss: (g: PlacedGhost) => void;
}) {
  const entryOf = (kind: string | null) => (kind ? catalog?.find((c) => c.type === kind) : undefined);
  // 선 끝은 진짜 노드의 실측 포트 — 노드를 옮기면 따라온다. 문자열로 비교해 같은 자리면 다시 그리지 않는다.
  const wiresKey = useStore((st) => {
    const out: GhostWire[] = [];
    for (const g of ghosts) {
      for (const a of g.attach) {
        let s: Pt | null, t: Pt | null;
        if (a.target === NEW_NODE && g.at) { s = handleAt(st.nodeLookup.get(a.source), "source", a.source_port); t = ghostPort(g, entryOf(g.kind), "in", a.target_port); }
        else if (a.source === NEW_NODE && g.at) { s = ghostPort(g, entryOf(g.kind), "out", a.source_port); t = handleAt(st.nodeLookup.get(a.target), "target", a.target_port); }
        else { s = handleAt(st.nodeLookup.get(a.source), "source", a.source_port); t = handleAt(st.nodeLookup.get(a.target), "target", a.target_port); }
        if (!s || !t) continue;
        const { d, mid } = wirePath(shape, s, t, [], { s: Position.Right, t: Position.Left });
        out.push({ ghost: g.key, action: g.action, d, mid,
                   from: a.source === NEW_NODE ? g.kind ?? "" : a.source, to: a.target === NEW_NODE ? g.kind ?? "" : a.target });
      }
    }
    return JSON.stringify(out);
  });
  const wires = JSON.parse(wiresKey) as GhostWire[];
  // 잇기 칩은 선 가운데가 아니라 빈 자리에 있다(이웃 열 사이는 좁아 카드에 깔렸다) — 선 가운데에서 칩까지 점선 끈.
  const leads = ghosts.flatMap((g) => {
    const mid = g.chip && wires.find((w) => w.ghost === g.key)?.mid;
    return mid && g.chip ? [{ key: g.key, x1: mid.x, y1: mid.y, x2: g.chip.x + NODE_W / 2, y2: g.chip.y }] : [];
  });
  return (
    <ViewportPortal>
      <div className="pg-ghosts">
        <svg className="pg-ghost-wires" aria-hidden="true">
          {wires.map((w, i) => (
            <g key={i} className={`pg-ghost-wire${hot === w.ghost ? " pg-ghost-wire--hot" : ""}`} data-from={w.from} data-to={w.to} data-action={w.action}>
              <path d={w.d} />
            </g>
          ))}
          {leads.map((l) => <line key={l.key} className={`pg-ghost-lead${hot === l.key ? " pg-ghost-wire--hot" : ""}`} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} />)}
        </svg>
        {ghosts.map((g) => {
          const hotCls = hot === g.key ? " pg-ghost--hot" : "";
          const common = { "data-source": g.source === "rule" && g.aiReason !== null ? "rule claude" : g.source,
                           "data-next": String(g.isNext), "data-action": g.action, "data-gates": g.gates.join(" ") };
          // 규칙 유령에 AI 가 같은 추천을 냈으면 그 이유 한 줄(AI 만의 유령은 `text` 가 곧 이유다).
          const reason = g.source === "rule" && g.aiReason !== null
            ? <p className="pg-ghost-reason"><span className="pg-ghost-reason-k">AI</span> {g.aiReason}</p> : null;
          const acts = (
            <div className="pg-ghost-acts">
              <button type="button" className="pg-ghost-add" onClick={() => onApply(g)}>{g.action === "connect" ? "잇기" : "붙이기"}</button>
              <button type="button" className="pg-ghost-x" aria-label={`이 추천 닫기${g.label ? ` — ${g.label}` : ""}`} onClick={() => onDismiss(g)}>닫기</button>
            </div>
          );
          if (!g.at) {
            // 잇기만 하는 추천 — 카드 없이 점선 + 빈 자리의 칩(점선 끈으로 선 가운데와 잇는다).
            if (!g.chip) return null;
            return (
              <div key={g.key} className={`pg-ghost pg-ghost--connect${hotCls}`} role="group" aria-label={`${sourceName(g)}: 잇기`} {...common}
                   style={{ transform: `translate(${g.chip.x}px, ${g.chip.y}px)`, width: NODE_W }}>
                <Chips g={g} />
                <p className="pg-ghost-text">{g.text}</p>
                {reason}
                {acts}
              </div>
            );
          }
          const entry = entryOf(g.kind);
          const ports = g.attach.map((a) => (a.target === NEW_NODE ? { side: "in" as const, name: a.target_port } : a.source === NEW_NODE ? { side: "out" as const, name: a.source_port } : null))
            .filter((p): p is { side: "in" | "out"; name: string } => !!p);
          return (
            <div key={g.key} className={`pg-ghost${hotCls}`} role="group" aria-label={`${sourceName(g)}: ${g.label ?? g.kind}`} data-kind={g.kind ?? ""}
                 data-x={g.at.x} data-y={g.at.y} {...common}
                 style={{ transform: `translate(${g.at.x}px, ${g.at.y}px)`, width: NODE_W, height: cardHeight(g.kind!, catalog),
                          ["--pg-stage" as string]: STAGE_VAR[entry?.stage ?? ""] ?? "var(--pg-st-data)" }}>
              <div className="pg-ghost-head">
                <Chips g={g} />
                <span className="pg-ghost-name">{g.label ?? g.kind}</span>
              </div>
              <p className="pg-ghost-text">{g.text}</p>
              {reason}
              {g.gates.length > 0 && <p className="pg-ghost-gates">잴 수 있게 되는 관문 · {g.gates.map(gateLabel).join(" · ")}</p>}
              {acts}
              {ports.map((p) => {
                const ghostPt = ghostPort(g, entry, p.side, p.name);
                return <span key={`${p.side}.${p.name}`} className={`pg-ghost-port pg-ghost-port--${p.side}`} aria-hidden="true"
                             style={{ top: ghostPt.y - g.at!.y }} />;
              })}
            </div>
          );
        })}
      </div>
    </ViewportPortal>
  );
}
