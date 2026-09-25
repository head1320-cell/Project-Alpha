"use client";
/**
 * 노드 팔레트 — ★서버 카탈로그만 본다★ (BI3 → BJ2)
 * 퀀트 워크플로우 단계별(데이터 → 신호 → 생각 정하기 → 비중 정하기 → 확인하기 → 실행·기록)로
 * 쉬운 이름과 한 줄 설명을 보여 준다. 노드가 아직 없는 단계는 비워 두지 않고 "곧 추가돼요".
 * 클릭하면 캔버스 가운데에, 끌면 놓은 자리에 놓인다.
 */
import { useState } from "react";
import { Search } from "lucide-react";
import type { NodeCatalogEntry, WorkflowStage } from "@/entities/portfolio-graph";
import { STAGE_VAR } from "./GraphNode";

export const PALETTE_MIME = "application/x-pg-node";

export function NodePalette({ catalog, stages, onAdd, onTemplate }: {
  catalog: NodeCatalogEntry[];
  stages: WorkflowStage[];
  onAdd: (kind: string) => void;
  onTemplate: () => void;
}) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const match = (c: NodeCatalogEntry) => !needle || [c.plain_label, c.plain_description, c.type, c.label]
    .some((s) => s?.toLowerCase().includes(needle));
  const known = new Set(stages.map((s) => s.key));
  const groups = [...stages, ...[...new Set(catalog.map((c) => c.stage))]
    .filter((k) => !known.has(k)).map((k) => ({ key: k, label: k || "기타" }))];

  return (
    <aside className="pg-palette" aria-label="노드 추가">
      <label className="pg-search">
        <Search size={14} aria-hidden="true" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="무엇을 추가할까요?" aria-label="노드 찾기" />
      </label>
      {groups.map((st) => {
        const items = catalog.filter((c) => c.stage === st.key && match(c));
        if (needle && !items.length) return null;
        return (
          <section key={st.key} className="pg-palette-group">
            <h4 className="pg-palette-cat"><i style={{ background: STAGE_VAR[st.key] ?? "var(--pg-mute)" }} />{st.label}</h4>
            {items.length === 0 && <p className="pg-palette-soon">{st.label} 노드는 곧 추가돼요.</p>}
            {items.map((c) => (
              <button key={c.type} type="button" className="pg-palette-item" data-kind={c.type} draggable
                      title={`${c.label} (${c.type})`}
                      onDragStart={(e) => { e.dataTransfer.setData(PALETTE_MIME, c.type); e.dataTransfer.effectAllowed = "move"; }}
                      onClick={() => onAdd(c.type)}>
                <b>{c.plain_label}</b>
                <span>{c.plain_description}</span>
              </button>
            ))}
          </section>
        );
      })}
      {needle && !catalog.some(match) && <p className="pg-palette-soon">‘{q}’에 맞는 노드가 없어요.</p>}
      <button type="button" className="pg-template pg-quickstart" onClick={onTemplate}>
        <b>빠른 시작</b>
        <span>종목 3개로 비중을 정하고 과거로 돌려 보는 기본 흐름을 불러와요.</span>
      </button>
    </aside>
  );
}
