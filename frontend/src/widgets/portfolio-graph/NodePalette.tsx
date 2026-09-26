"use client";
/**
 * 노드 팔레트 — ★서버 카탈로그만 본다★ (BI3 → BJ2 → BK W6)
 * 퀀트 워크플로우 단계별(데이터 → 신호 → 생각 정하기 → 비중 정하기 → 확인하기 → 실행·기록)로
 * 쉬운 이름과 한 줄 설명을 보여 준다. 노드가 서른 개 가까이 되어 단계마다 **접고 펼 수 있고**(개수 표시),
 * 검색은 쉬운 이름·설명·종류 이름에 더해 **마법사 화면 이름**(STRESS·Stress·06 …)으로도 찾는다 —
 * `WIZARD_NODE_MAP`. 맨 아래 "빠른 시작" 은 템플릿 넷. 클릭하면 캔버스 가운데에, 끌면 놓은 자리에 놓인다.
 */
import { useState } from "react";
import { ChevronDown, Search } from "lucide-react";
import { TEMPLATES, type NodeCatalogEntry, type WorkflowStage } from "@/entities/portfolio-graph";
import { STAGE_VAR } from "./GraphNode";

export const PALETTE_MIME = "application/x-pg-node";

/** 마법사 화면 하나와 그 일을 하는 노드들 — app 계층이 대응표로 채운다(위젯끼리는 서로 모른다). */
export interface WizardAlias { name: string; short: string; nodes: readonly string[] }

export function NodePalette({ catalog, stages, aliases = [], onAdd, onTemplate }: {
  catalog: NodeCatalogEntry[];
  stages: WorkflowStage[];
  aliases?: WizardAlias[];
  onAdd: (kind: string) => void;
  onTemplate: (key: string) => void;
}) {
  /** 노드 종류 → 그 일을 하던 마법사 화면(검색·툴팁용). */
  const wizardOf: Record<string, WizardAlias[]> = {};
  for (const a of aliases) for (const t of a.nodes) (wizardOf[t] ??= []).push(a);
  const [q, setQ] = useState("");
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const needle = q.trim().toLowerCase();
  const match = (c: NodeCatalogEntry) => !needle || [c.plain_label, c.plain_description, c.type, c.label, ...(wizardOf[c.type] ?? []).map((a) => a.name)]
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
        const all = catalog.filter((c) => c.stage === st.key);
        const items = all.filter(match);
        if (needle && !items.length) return null;
        const open = !!needle || !closed[st.key];                 // 찾는 중에는 늘 펼친다
        const body = `pg-palette-body-${st.key}`;
        return (
          <section key={st.key} className="pg-palette-group" data-stage={st.key}>
            <h4 className="pg-palette-cat">
              <button type="button" className="pg-palette-toggle" aria-expanded={open} aria-controls={body}
                      onClick={() => setClosed((c) => ({ ...c, [st.key]: open }))}>
                <i style={{ background: STAGE_VAR[st.key] ?? "var(--pg-mute)" }} />
                <span className="pg-palette-cat-name">{st.label}</span>
                <span className="pg-palette-count">{needle ? `${items.length}/${all.length}` : all.length}</span>
                <ChevronDown size={14} aria-hidden="true" className={`pg-palette-chev${open ? "" : " pg-palette-chev--closed"}`} />
              </button>
            </h4>
            <div id={body} hidden={!open}>
              {all.length === 0 && <p className="pg-palette-soon">{st.label} 노드는 곧 추가돼요.</p>}
              {items.map((c) => (
                <button key={c.type} type="button" className="pg-palette-item" data-kind={c.type} draggable
                        title={`${c.label} (${c.type})${wizardOf[c.type] ? ` · 마법사 ${wizardOf[c.type].map((a) => a.short).join(", ")}` : ""}`}
                        onDragStart={(e) => { e.dataTransfer.setData(PALETTE_MIME, c.type); e.dataTransfer.effectAllowed = "move"; }}
                        onClick={() => onAdd(c.type)}>
                  <b>{c.plain_label}</b>
                  <span>{c.plain_description}</span>
                </button>
              ))}
            </div>
          </section>
        );
      })}
      {needle && !catalog.some(match) && <p className="pg-palette-soon">‘{q}’에 맞는 노드가 없어요.</p>}
      <section className="pg-quickstart" aria-label="빠른 시작">
        <h4 className="pg-quickstart-h">빠른 시작</h4>
        {TEMPLATES.map((t) => (
          <button key={t.key} type="button" className="pg-template" data-template={t.key} onClick={() => onTemplate(t.key)}>
            <b>{t.name}</b>
            <span>{t.description}</span>
          </button>
        ))}
      </section>
    </aside>
  );
}
