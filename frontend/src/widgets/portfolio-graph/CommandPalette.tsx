"use client";
/**
 * 명령 팔레트 (BL1 · Ctrl+K) — 노드 추가 · 템플릿 · 캔버스 동작을 한 칸에서 찾는다
 * ==========================================================================
 * 팔레트 검색과 같은 규칙(쉬운 이름·설명·종류 이름)으로 노드를 찾고, 동작은 이름으로 찾는다. 화살표로 고르고
 * Enter 로 실행, Esc 로 닫는다. 네이티브 `<dialog>` 라 초점 가두기·배경 비활성은 브라우저가 한다.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import type { NodeCatalogEntry } from "@/entities/portfolio-graph";

export interface PaletteCommand { id: string; label: string; hint?: string; group: string; keys?: string; run: () => void }

export function CommandPalette({ open, onClose, catalog, commands, onAddNode }: {
  open: boolean;
  onClose: () => void;
  catalog: NodeCatalogEntry[];
  commands: PaletteCommand[];
  onAddNode: (kind: string) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [at, setAt] = useState(0);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { d.showModal(); setQ(""); setAt(0); setTimeout(() => input.current?.focus(), 0); }
    if (!open && d.open) d.close();
  }, [open]);

  const items = useMemo<PaletteCommand[]>(() => {
    const needle = q.trim().toLowerCase();
    const hit = (...xs: (string | undefined)[]) => !needle || xs.some((x) => x?.toLowerCase().includes(needle));
    const nodes = catalog.filter((c) => hit(c.plain_label, c.plain_description, c.type, c.label)).map((c) => ({
      id: `node:${c.type}`, label: `${c.plain_label} 추가`, hint: c.plain_description, group: "노드 추가",
      run: () => onAddNode(c.type),
    }));
    const acts = commands.filter((c) => hit(c.label, c.hint, c.group));
    return [...acts, ...nodes].slice(0, 40);
  }, [q, catalog, commands, onAddNode]);

  const pick = (i: number) => { const it = items[i]; if (!it) return; onClose(); it.run(); };

  return (
    <dialog ref={ref} className="pg-cmd" aria-label="명령 찾기" onClose={onClose}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <label className="pg-cmd-search">
        <Search size={16} aria-hidden="true" />
        <input ref={input} value={q} placeholder="노드·템플릿·동작 찾기" aria-label="명령 찾기"
               aria-controls="pg-cmd-list" aria-activedescendant={items[at] ? `pg-cmd-${at}` : undefined}
               onChange={(e) => { setQ(e.target.value); setAt(0); }}
               onKeyDown={(e) => {
                 if (e.key === "ArrowDown") { e.preventDefault(); setAt((a) => Math.min(items.length - 1, a + 1)); }
                 else if (e.key === "ArrowUp") { e.preventDefault(); setAt((a) => Math.max(0, a - 1)); }
                 else if (e.key === "Enter") { e.preventDefault(); pick(at); }
               }} />
      </label>
      <ul id="pg-cmd-list" className="pg-cmd-list" role="listbox">
        {items.length === 0 && <li className="pg-cmd-empty">‘{q}’에 맞는 것이 없어요.</li>}
        {items.map((it, i) => (
          <li key={it.id} id={`pg-cmd-${i}`} role="option" aria-selected={i === at}
              className={`pg-cmd-item${i === at ? " on" : ""}`} data-cmd={it.id}
              onMouseEnter={() => setAt(i)} onClick={() => pick(i)}>
            <span className="pg-cmd-group">{it.group}</span>
            <b>{it.label}</b>
            {it.hint && <span className="pg-cmd-hint">{it.hint}</span>}
            {it.keys && <kbd className="pg-cmd-keys">{it.keys}</kbd>}
          </li>
        ))}
      </ul>
    </dialog>
  );
}
