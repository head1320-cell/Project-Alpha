"use client";
/**
 * 노드 팔레트 — ★서버 카탈로그만 본다★ (BI3). 클릭하면 캔버스 가운데에, 끌면 놓은 자리에.
 */
import type { NodeCatalogEntry } from "@/entities/portfolio-graph";
import { PORT_COLORS } from "./GraphNode";

export const PALETTE_MIME = "application/x-pg-node";

export function NodePalette({ catalog, onAdd }: {
  catalog: NodeCatalogEntry[];
  onAdd: (kind: string) => void;
}) {
  const groups = new Map<string, NodeCatalogEntry[]>();
  for (const c of catalog) groups.set(c.category || "기타", [...(groups.get(c.category || "기타") ?? []), c]);
  return (
    <aside className="pg-palette" aria-label="노드 팔레트">
      {[...groups.entries()].map(([cat, items]) => (
        <div key={cat} className="pg-palette-group">
          <div className="pg-palette-cat">{cat}</div>
          {items.map((c) => {
            const out = c.outputs[0]?.type;
            return (
              <button key={c.type} type="button" className="pg-palette-item" data-kind={c.type}
                      draggable title={c.description}
                      onDragStart={(e) => {
                        e.dataTransfer.setData(PALETTE_MIME, c.type);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onClick={() => onAdd(c.type)}>
                <span className="pg-palette-dot" style={{ background: out ? PORT_COLORS[out] ?? "#94a3b8" : "#94a3b8" }} />
                <span className="pg-palette-label">{c.label}</span>
                <span className="pg-palette-kind">{c.type}</span>
              </button>
            );
          })}
        </div>
      ))}
    </aside>
  );
}
