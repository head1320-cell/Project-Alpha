"use client";
/**
 * 캔버스 손길 (BN N3 · ComfyUI·Blender 의 링크 끌어 놓기 검색 · 우클릭 메뉴 · 찾기 · 단축키 한 장)
 * ==========================================================================
 * ★규칙을 새로 정하지 않는다★ — 빠른 추가의 후보는 서버 카탈로그에서 **포트 타입이 맞는 노드**만(연결 규칙과 같은 타입 일치),
 * 메뉴의 동작은 이미 있는 스토어 동작(여기까지 계산 · 갈래 · 복제 · 그림 고정 · 원인 · 지우기)을 부를 뿐이다.
 * 모든 판은 키보드로 쓸 수 있다: ↑↓ 로 고르고 Enter, Esc 로 닫는다. 같은 동작은 명령 찾기(Ctrl+K)에도 있다.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Download, MoreHorizontal, Search, Undo2, Upload, X } from "lucide-react";
import { quickAddItems, type GraphDoc, type NodeCatalogEntry, type ParseResult } from "@/entities/portfolio-graph";
import { downloadGraph, readGraphFile } from "@/features/portfolio-graph-io";
import { PORT_PLAIN } from "./GraphNode";
import { usePortfolioGraph } from "./store";

/** 판 바깥을 누르거나 Esc 면 닫는다. */
function useDismiss(ref: React.RefObject<HTMLElement>, onClose: () => void) {
  useEffect(() => {
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("mousedown", down);
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("mousedown", down); window.removeEventListener("keydown", key, true); };
  }, [ref, onClose]);
}

/** 캔버스 위에 떠 있는 판(BQ Q1)이 가리는 폭 — `panels.floatInsets` 가 잰다. */
export type Insets = { left: number; right: number; bottom: number };
const NO_INSET: Insets = { left: 0, right: 0, bottom: 0 };

/** 화면 가장자리에서 판이 잘리지 않게 자리를 당긴다(캔버스 안 좌표). 캔버스가 창 아래로 이어지면 **보이는 부분**에 맞춘다.
 *  떠 있는 왼쪽 목록·오른쪽 창 밑으로도 들어가지 않는다(BQ Q1). */
function clampAt(x: number, y: number, box: DOMRect | undefined, w: number, h: number, inset: Insets = NO_INSET) {
  if (!box) return { left: x, top: y };
  const visH = typeof window === "undefined" ? box.height : Math.min(box.height, window.innerHeight - box.top);
  const visW = typeof window === "undefined" ? box.width : Math.min(box.width, window.innerWidth - box.left);
  return { left: Math.max(8 + inset.left, Math.min(x, visW - w - 8 - inset.right)),
           top: Math.max(8, Math.min(y, visH - h - 8 - inset.bottom)) };
}

export interface QuickAddState {
  /** 캔버스 안 좌표(판 자리) · 화면 좌표(노드를 놓을 자리). */
  x: number; y: number; clientX: number; clientY: number;
  /** 선을 끌어 온 포트 — 없으면(빈 곳 우클릭) 타입으로 거르지 않는다. */
  from: { node: string; handle: string; side: "source" | "target"; type: string } | null;
}

/** 선을 빈 곳에 놓으면 — "이 값을 받는(내는) 노드" 만 보이는 작은 찾기 목록. */
export function QuickAdd({ at, catalog, stageKeys, fromKind, box, inset, onPick, onClose }: {
  at: QuickAddState; catalog: NodeCatalogEntry[]; stageKeys: string[]; fromKind: string | null; box: DOMRect | undefined; inset?: Insets;
  onPick: (kind: string, port: string | null) => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  useDismiss(ref, onClose);
  const from = at.from;
  // 순서는 흐름 단계(BO O5) — 끌어 온 노드의 다음 단계가 먼저(받는 선이면 앞 단계가 먼저).
  const items = useMemo(() => quickAddItems(catalog, from ? { ...from, kind: fromKind } : null, stageKeys, q),
                        [catalog, from, fromKind, stageKeys, q]);
  const pos = clampAt(at.x, at.y, box, 300, 390, inset);
  const title = !from ? "여기에 노드 추가"
    : from.side === "source" ? `‘${PORT_PLAIN[from.type] ?? from.type}’을 받는 노드` : `‘${PORT_PLAIN[from.type] ?? from.type}’을 내는 노드`;
  return (
    <div ref={ref} className="pg-quick" role="dialog" aria-label={title} style={pos} data-type={from?.type ?? ""}>
      <p className="pg-quick-h">{title}</p>
      <label className="pg-quick-search">
        <Search size={14} aria-hidden="true" />
        <input autoFocus value={q} placeholder="이름으로 찾기" aria-label="노드 찾기" role="combobox" aria-expanded
               aria-controls="pg-quick-list" aria-activedescendant={items[active] ? `pg-quick-${active}` : undefined}
               onChange={(e) => { setQ(e.target.value); setActive(0); }}
               onKeyDown={(e) => {
                 if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
                 else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
                 else if (e.key === "Enter" && items[active]) { e.preventDefault(); onPick(items[active].c.type, items[active].port); }
               }} />
      </label>
      <ul id="pg-quick-list" className="pg-quick-list" role="listbox">
        {items.length === 0 && <li className="pg-quick-empty">{q ? `‘${q}’에 맞는 노드가 없어요.` : "이 값을 이을 수 있는 노드가 없어요."}</li>}
        {items.map(({ c, port }, i) => (
          <li key={c.type} id={`pg-quick-${i}`} role="option" aria-selected={i === active} className="pg-quick-item" data-kind={c.type}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); onPick(c.type, port); }}>
            <b>{c.plain_label}</b><span>{c.plain_description}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface MenuItem { key: string; label: string; icon?: ReactNode; danger?: boolean; disabled?: boolean; run: () => void }

/** 우클릭 메뉴 — 노드 · 빈 곳. 첫 항목에 초점, ↑↓ Enter Esc. */
export function ContextMenu({ x, y, box, inset, items, label, onClose }: {
  x: number; y: number; box: DOMRect | undefined; inset?: Insets; items: MenuItem[]; label: string; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, onClose);
  useEffect(() => { ref.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus(); }, []);
  const move = (dir: 1 | -1) => {
    const bs = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
    const i = bs.indexOf(document.activeElement as HTMLButtonElement);
    bs[(i + dir + bs.length) % bs.length]?.focus();
  };
  return (
    <div ref={ref} className="pg-ctx" role="menu" aria-label={label} style={clampAt(x, y, box, 230, items.length * 34 + 16, inset)}
         onKeyDown={(e) => {
           if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
           else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
         }}>
      {items.map((it) => (
        <button key={it.key} type="button" role="menuitem" className={`pg-ctx-item${it.danger ? " pg-ctx-item--danger" : ""}`}
                data-action={it.key} disabled={it.disabled} onClick={() => { onClose(); it.run(); }}>
          {it.icon}{it.label}
        </button>
      ))}
    </div>
  );
}

/** 캔버스 찾기(Ctrl+F) — 노드 쉬운 이름·요약·id 로. 고르면 그 노드로 옮기고 고른다. */
export function FindBar({ nodes, onPick, onClose }: {
  nodes: { id: string; label: string; sub: string }[]; onPick: (id: string) => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  useDismiss(ref, onClose);
  const needle = q.trim().toLowerCase();
  const hits = needle ? nodes.filter((n) => [n.label, n.sub, n.id].some((x) => x.toLowerCase().includes(needle))).slice(0, 12) : [];
  return (
    <div ref={ref} className="pg-find" role="search" aria-label="캔버스에서 노드 찾기">
      <label className="pg-find-box">
        <Search size={15} aria-hidden="true" />
        <input autoFocus value={q} placeholder="노드 이름으로 찾기" aria-label="노드 이름으로 찾기" role="combobox" aria-expanded={hits.length > 0}
               aria-controls="pg-find-list" aria-activedescendant={hits[active] ? `pg-find-${active}` : undefined}
               onChange={(e) => { setQ(e.target.value); setActive(0); }}
               onKeyDown={(e) => {
                 if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(hits.length - 1, a + 1)); }
                 else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
                 else if (e.key === "Enter" && hits[active]) { e.preventDefault(); onPick(hits[active].id); onClose(); }
               }} />
        <button type="button" className="pg-find-x" aria-label="찾기 닫기" onClick={onClose}><X size={14} aria-hidden="true" /></button>
      </label>
      {needle && (
        <ul id="pg-find-list" className="pg-find-list" role="listbox">
          {hits.length === 0 && <li className="pg-quick-empty">‘{q}’에 맞는 노드가 없어요.</li>}
          {hits.map((n, i) => (
            <li key={n.id} id={`pg-find-${i}`} role="option" aria-selected={i === active} className="pg-find-item" data-node-id={n.id}
                onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); onPick(n.id); onClose(); }}>
              <b>{n.label}</b><span>{n.sub}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export const SHORTCUTS: [string, string][] = [
  ["Ctrl+Enter", "계산하기"],
  ["Shift+Enter", "고른 노드까지 계산"],
  ["Ctrl+K", "명령 찾기"],
  ["Ctrl+F", "캔버스에서 노드 찾기"],
  ["Ctrl+Z / Ctrl+Shift+Z", "되돌리기 / 다시하기"],
  ["Ctrl+C / Ctrl+V", "복사 / 붙여넣기"],
  ["Ctrl+D", "고른 노드 복제"],
  ["Ctrl+G", "고른 노드 묶기"],
  ["Delete", "고른 노드·선 지우기"],
  ["Alt+← →", "선을 따라 앞·뒤 단계로"],
  ["Alt+↑ ↓", "흐름 번호 순서로"],
  ["[", "왼쪽 목록 열고 닫기"],
  ["]", "오른쪽 창 열고 닫기"],
  ["\\", "집중해서 보기 — 두 판을 잠시 모두 닫기·다시 열기"],
  ["Esc", "원인 경로 · 들어간 상자 · 판 닫기"],
  ["?", "이 목록"],
];

/** 단축키 한 장(`?`) — 네이티브 dialog(초점 가두기·Esc 는 브라우저). */
export function ShortcutSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="pg-keys" aria-label="단축키" onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <header className="pg-keys-head">
        <h2>단축키</h2>
        <button type="button" className="pg-sheet-x" aria-label="닫기" onClick={onClose}><X size={18} /></button>
      </header>
      <dl className="pg-keys-list">
        {SHORTCUTS.map(([k, v]) => (
          <div key={k}><dt><kbd>{k}</kbd></dt><dd>{v}</dd></div>
        ))}
      </dl>
      <p className="pg-keys-foot">노드·빈 곳을 오른쪽 단추로 누르면 할 수 있는 일이 나와요. 선을 빈 곳에 놓으면 그 값을 이을 노드를 찾을 수 있어요.</p>
    </dialog>
  );
}

/**
 * 안내 줄(BN N3) — 되돌릴 수 있는 동작 뒤의 안내에는 [되돌리기] 가 붙고 8초 뒤 스스로 닫힌다.
 * 마우스를 올리거나 초점이 있거나 계산 중이면 기다린다. 되돌릴 수 없는 안내(사유·경고)는 사람이 닫을 때까지 남는다.
 */
export const NOTE_MS = 8000;
export function NoteLine() {
  const note = usePortfolioGraph((s) => s.note);
  const undoable = usePortfolioGraph((s) => s.noteUndo && s.past.length > 0);
  const running = usePortfolioGraph((s) => s.running);
  const [hold, setHold] = useState(false);
  useEffect(() => {
    if (!undoable || hold || running) return;
    const t = setTimeout(() => usePortfolioGraph.getState().setNote(null), NOTE_MS);
    return () => clearTimeout(t);
  }, [undoable, hold, running, note]);
  if (!note) return null;
  return (
    <p className={`pg-banner pg-note${undoable ? " pg-note--undoable" : ""}`} role="status"
       onMouseEnter={() => setHold(true)} onMouseLeave={() => setHold(false)}
       onFocus={() => setHold(true)} onBlur={() => setHold(false)}>
      {note}
      {undoable && (
        <button type="button" className="pg-note-undo"
                onClick={() => { const st = usePortfolioGraph.getState(); st.undo(); st.setNote("되돌렸어요."); }}>
          <Undo2 size={13} aria-hidden="true" /> 되돌리기
        </button>
      )}
      <button type="button" className="pg-note-x" aria-label="안내 닫기" onClick={() => usePortfolioGraph.getState().setNote(null)}>
        <X size={13} aria-hidden="true" />
      </button>
    </p>
  );
}

/** 좁은 폭(<1280)의 "더 보기" — 서랍 · 불러오기 · 내보내기를 한 메뉴로(넓을 때는 CSS 로 숨고 원래 단추가 보인다). */
export function MoreMenu({ drawers, onDrawer, onImport, getDoc, canExport }: {
  drawers: { key: string; label: string }[]; onDrawer: (k: string) => void;
  onImport: (r: ParseResult, fileName: string) => void; getDoc: () => GraphDoc; canExport: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismissWhen(open, ref, close);
  return (
    <span className="pg-more-wrap" ref={ref}>
      <button type="button" className="pg-more" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <MoreHorizontal size={15} aria-hidden="true" /> 더 보기
      </button>
      {open && (
        <div className="pg-more-menu" role="menu" aria-label="더 보기">
          {drawers.map((d) => (
            <button key={d.key} type="button" role="menuitem" className="pg-ctx-item" data-drawer={d.key}
                    onClick={() => { setOpen(false); onDrawer(d.key); }}>{d.label}</button>
          ))}
          <button type="button" role="menuitem" className="pg-ctx-item" onClick={() => file.current?.click()}>
            <Upload size={14} aria-hidden="true" /> 불러오기
          </button>
          <button type="button" role="menuitem" className="pg-ctx-item pg-more-export" disabled={!canExport}
                  onClick={() => { setOpen(false); downloadGraph(getDoc()); }}>
            <Download size={14} aria-hidden="true" /> 내보내기
          </button>
        </div>
      )}
      <input ref={file} type="file" accept=".json,application/json" className="pg-more-import-input" hidden
             onChange={async (e) => {
               const f = e.target.files?.[0];
               e.target.value = "";
               setOpen(false);
               if (f) onImport(await readGraphFile(f), f.name);
             }} />
    </span>
  );
}

function useDismissWhen(on: boolean, ref: React.RefObject<HTMLElement>, onClose: () => void) {
  useEffect(() => {
    if (!on) return;
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("mousedown", down);
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("mousedown", down); window.removeEventListener("keydown", key); };
  }, [on, ref, onClose]);
}
