"use client";
/**
 * 판 배치(작업 공간 2단계 · G6 2a-1) — 한 그리드 상자 안의 열쇠 있는 판들 (설계 `docs/superpowers/specs/2026-11-19-workspace-panels-design.md` §5.3 · 계획 §9)
 * ==========================================================================
 * ★판은 한 그리드 상자(`.ws-grid`)의 열쇠 있는 자식이다★ — 배치가 바뀌어도 부모는 같고 자리(CSS grid)와 순서만 바뀐다. 그래서 옮기기 · 닫힌 판이 아닌 판의
 * 탭 바꾸기 · 좁은 창 쌓기를 오가도 절은 다시 마운트되지 않는다(절 안의 입력 · 계산 진행 · 화면 상태가 남고 시행을 남기는 문은 단추로만 불린다 — 시험이 건다).
 * 탭에서 가려진 판은 `hidden`(마운트 유지 · 초점이 가지 않음). DOM 순서 = 읽는 순서(열 → 칸 → 탭).
 * 열마다 위 · 아래 칸 비율이 달라도 상자는 하나다 — 행 트랙 20등분 · 칸 = 행 구간 · 칸 머리는 구간 위에 겹친다(높이 고정) · 판은 머리 높이만큼 내려 둔다.
 * 판 메뉴(키보드 · 정본)와 끌어 놓기(포인터 · 보조)는 같은 순수 함수 `move` 를 부른다. 창이 좁아 열이 들어가지 않으면 ★그리기만★ 오른쪽 열을 앞 열의 탭으로
 * 합친다(저장한 배치는 그대로 · 그 사실을 적는다 · 그동안 끌어 놓기는 쉰다). 1280 × 800 미만이면 같은 상자 안에서 판을 한 열로 쌓는다(`stacked`).
 * 낭독 영역 하나(polite) · 단축키 없음(WCAG 2.1.4) · 색은 `--tx-*` 토큰만 · 서버 · 계산 0줄.
 */
import { MoreHorizontal } from "lucide-react";
import { useCallback, useImperativeHandle, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type Ref } from "react";
import { Splitter } from "@/shared/ui/split/Splitter";
import { rove } from "@/shared/ui/tx";
import { dropAt, type Drop, type Geometry, type Rect } from "./dnd";
import { activate, areaName, close, colSplit, colWidths, eul, fold, locate, move, reopen, ro, type Layout, type Target } from "./layout";
import { LayoutMenu } from "./LayoutMenu";
import { MenuButton, type MenuItem } from "./MenuButton";
import { RowSplitter } from "./RowSplitter";
import { useWorkWidth } from "./useWorkWidth";
import type { WorkspaceState } from "./useWorkspace";

export type WorkspaceApi = {
  /** 그 판을 앞으로 낸다(닫혀 있으면 다시 연다) · 맨 위로 · focus 면 그 판의 탭에 초점. 바뀐 것이 있으면 낭독한다. */
  reveal: (id: string, focus?: boolean) => void;
};

const ROWS = 20;
const ORD = ["첫째", "둘째", "셋째"];
const DRAG_PX = 4;

function rectOf(el: Element | null): Rect | null {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.x, y: r.y, width: r.width, height: r.height };
}

/** 칸 (열 c 의 r 번째)의 행 구간 — 칸 하나면 전체 · 둘이면 아래 칸이 h(20등분). */
function rowSpan(layout: Layout, c: number, r: number): string {
  const col = layout.cols[c];
  if (col.rows.length < 2) return `1 / ${ROWS + 1}`;
  const k = Math.min(ROWS - 1, Math.max(1, Math.round((col.rows[1].h ?? 0.5) * ROWS)));
  return r === 0 ? `1 / ${ROWS + 1 - k}` : `${ROWS + 1 - k} / ${ROWS + 1}`;
}

export function Workspace({ ws, stacked, render, api, onManage }: {
  ws: WorkspaceState;
  /** 좁은 창 — 같은 상자 안에서 판을 한 열로 쌓는다(머리 · 판 메뉴 · 구분선 없음). */
  stacked: boolean;
  /** 판 내용 — 판 id 를 받아 그 판의 절을 돌려준다. */
  render: (id: string) => ReactNode;
  api?: Ref<WorkspaceApi>;
  /** '배치 관리' — 시트는 부르는 화면이 판 배치를 끄고 켜도 같은 자리에 둔다. */
  onManage: () => void;
}) {
  const { spec } = ws;
  const saved = ws.layout;
  const screen = spec.screen;
  const [measure, work] = useWorkWidth();
  const known = work > 0 ? work : Number.POSITIVE_INFINITY;
  const view = useMemo(() => (stacked ? { layout: saved, folded: 0 } : fold(saved, known, spec)), [stacked, saved, known, spec]);
  const L = view.layout;
  const folded = view.folded > 0;
  const lastCol = L.cols.length - 1;
  const widths = colWidths(L, known, spec);
  const [zoom, setZoom] = useState<string | null>(null);
  const [override, setOverride] = useState<string | null>(null);
  const [live, setLive] = useState({ text: "", n: 0 });
  const [drag, setDrag] = useState<{ id: string; box: CSSProperties | null; chip: { style: CSSProperties; text: string; ok: boolean } } | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const suppressClick = useRef(false);
  const tabEls = useRef(new Map<string, HTMLButtonElement>());

  const gridEl = useCallback((el: HTMLDivElement | null) => { gridRef.current = el; measure(el); }, [measure]);
  const nameOf = (id: string) => spec.panels.find((p) => p.id === id)?.name ?? id;
  // 판 안 첫 절이 판 이름을 제목으로 다는 판(`PanelSpec.titled`) — 같은 이름의 제목이 둘 서지 않게 CSS 가 하나를 그리지 않는다(판 안 구조는 그대로)
  const titled = new Set(spec.panels.filter((p) => p.titled).map((p) => p.id));
  const say = (text: string) => setLive((s) => ({ text, n: s.n + 1 }));
  const tabId = (id: string) => `ws-t-${screen}-${id}`;
  const panelId = (id: string) => `ws-p-${screen}-${id}`;
  const nameId = (id: string) => `ws-n-${screen}-${id}`;
  /** 그 판의 탭에 초점 — 쌓은 좁은 창에는 탭이 없어 판에(tabIndex -1). 다음 그림 뒤에. */
  const focusTab = (id: string) => requestAnimationFrame(() => (document.getElementById(tabId(id)) ?? document.getElementById(panelId(id)))?.focus());

  /** 칸의 앞 탭 — 합쳐 보인 칸(마지막 열의 위 칸)에서는 그리기에만 고른 탭(override)이 먼저. */
  const activeOf = (c: number, r: number): string => {
    const a = L.cols[c].rows[r];
    if (folded && c === lastCol && r === 0 && override && a.tabs.includes(override)) return override;
    return a.active;
  };
  /** 판이 보이게 탭을 고른다 — 합쳐 보인 칸은 그리기에만(저장한 배치는 그 판의 저장 자리가 같을 때만 바꾼다). */
  const pickTab = (id: string) => {
    const at = locate(L, id);
    if (!at) return;
    if (folded && at.col === lastCol && at.row === 0) {
      setOverride(id);
      const s = locate(saved, id);
      if (s && s.col === at.col && s.row === 0 && saved.cols[s.col].rows[0].active !== id) ws.setLayout(activate(saved, id));
      return;
    }
    if (L.cols[at.col].rows[at.row].active !== id) ws.setLayout(activate(saved, id));
  };
  /** 옮긴 뒤 그 판이 합쳐 보인 칸에 들면 그리기에서도 앞 탭으로. */
  const followFold = (next: Layout, id: string) => {
    const v = fold(next, known, spec);
    const at = locate(v.layout, id);
    setOverride(v.folded && at && at.col === v.layout.cols.length - 1 && at.row === 0 ? id : null);
  };
  const doMove = (id: string, target: Target) => {
    const r = move(saved, id, target, spec);
    if (!r.ok) { say(r.reason); return; }
    ws.setLayout(r.layout);
    setZoom(null);
    followFold(r.layout, id);
    const where = areaName(r.layout, r.at.col, r.at.row);
    const merged = !stacked && fold(r.layout, known, spec).folded > 0 ? " 창이 좁아 합쳐 보입니다." : "";
    say(`‘${nameOf(id)}’ 판을 ${where}${ro(where)} 옮겼습니다.${merged}`);
    focusTab(id);
  };
  const doClose = (id: string) => {
    const at = locate(L, id);
    const r = close(saved, id, spec);
    if (!r.ok) { say(r.reason); return; }
    ws.setLayout(r.layout);
    setZoom(null);
    say(`‘${nameOf(id)}’ 판을 닫았습니다. ‘배치’ 메뉴에서 다시 열 수 있습니다.`);
    const v = fold(r.layout, known, spec).layout;
    const next = at && v.cols[at.col]?.rows[at.row] ? v.cols[at.col].rows[at.row].active : v.cols[0].rows[0].active;
    focusTab(next);
  };
  const doReopen = (id: string) => {
    const r = reopen(saved, id, spec);
    if (!r.ok) { say(r.reason); return; }
    ws.setLayout(r.layout);
    setZoom(null);
    followFold(r.layout, id);
    say(`‘${nameOf(id)}’ 판을 다시 열었습니다.`);
    focusTab(id);
  };
  const toggleZoom = (key: string, c: number, r: number) => {
    if (zoom === key) { setZoom(null); say("배치로 되돌렸습니다."); return; }
    setZoom(key);
    say(`${areaName(L, c, r)}만 크게 보입니다. Escape로 되돌립니다.`);
  };
  /** 막대의 '배치로 되돌리기' — 단추가 사라지므로 초점은 크게 보던 칸의 앞 탭으로. */
  const unzoom = () => {
    if (!zoom) return;
    const [c, r] = zoom.split(":").map(Number);
    setZoom(null);
    say("배치로 되돌렸습니다.");
    if (L.cols[c]?.rows[r]) focusTab(activeOf(c, r));
  };

  useImperativeHandle(api, () => ({
    reveal: (id: string, focus = false) => {
      if (saved.closed.includes(id)) { doReopen(id); return; }
      const at = locate(L, id);
      if (!at) return;
      const changed = !stacked && activeOf(at.col, at.row) !== id;
      if (!stacked) pickTab(id);
      if (zoom && zoom !== `${at.col}:${at.row}`) setZoom(null);
      if (changed) say(`‘${nameOf(id)}’ 판을 앞으로 냈습니다.`);
      requestAnimationFrame(() => {
        const el = document.getElementById(panelId(id));
        if (!el) return;
        if (stacked) { if (focus) el.scrollIntoView({ block: "start" }); }
        else el.scrollTo?.({ top: 0 });
      });
      if (focus && !stacked) focusTab(id);
    },
  }));

  /** 판 메뉴의 항목 — 옮기기(저장한 배치의 다른 칸 · 새 열 · 이 열 위 · 아래 새 칸 — `move` 가 받는 것만) · 이 칸만 크게 · 닫기. */
  const panelItems = (key: string, c: number, r: number, id: string): MenuItem[] => {
    const s = locate(saved, id);
    const moves: MenuItem[] = [];
    const add = (label: string, target: Target, k: string) => { if (move(saved, id, target, spec).ok) moves.push({ kind: "item", key: k, label, onSelect: () => doMove(id, target) }); };
    if (s) {
      saved.cols.forEach((col, sc) => col.rows.forEach((a, sr) => {
        if (sc === s.col && sr === s.row) return;
        add(areaName(saved, sc, sr), { kind: "tab", col: sc, row: sr, index: a.tabs.length }, `to-${sc}-${sr}`);
      }));
      add("새 열(왼쪽 끝)", { kind: "col", index: 0 }, "col-first");
      add("새 열(오른쪽 끝)", { kind: "col", index: saved.cols.length }, "col-last");
      add("이 열 위에 새 칸", { kind: "row", col: s.col, pos: "top" }, "row-top");
      add("이 열 아래에 새 칸", { kind: "row", col: s.col, pos: "bottom" }, "row-bottom");
    }
    const items: MenuItem[] = [];
    if (moves.length) items.push({ kind: "group", key: "move", label: "옮기기", items: moves }, { kind: "sep", key: "sep" });
    items.push({ kind: "item", key: "zoom", role: "menuitemcheckbox", checked: zoom === key, label: "이 칸만 크게", onSelect: () => toggleZoom(key, c, r) });
    if (spec.panels.find((p) => p.id === id)?.closable) items.push({ kind: "item", key: "close", label: "닫기", onSelect: () => doClose(id) });
    return items;
  };

  // ── 끌어 놓기(포인터 · 보조) — 4px 넘게 움직여야 끌기 · Escape 로 취소 · 메뉴와 같은 move · 합쳐 보이는 동안은 쉰다 ──
  const geometry = (): Geometry => {
    const grid = gridRef.current;
    const g = rectOf(grid);
    const areas: Geometry["areas"] = [];
    const cols: Rect[] = [];
    if (!grid || !g) return { cols, areas };
    L.cols.forEach((col, ci) => {
      let x = Number.POSITIVE_INFINITY;
      let right = Number.NEGATIVE_INFINITY;
      col.rows.forEach((a, ri) => {
        const head = rectOf(grid.querySelector(`.ws-head[data-area="${ci}:${ri}"]`));
        const body = rectOf(document.getElementById(panelId(activeOf(ci, ri))));
        if (!head || !body) return;
        x = Math.min(x, head.x);
        right = Math.max(right, head.x + head.width);
        areas.push({ col: ci, row: ri, head, body, tabs: a.tabs.map((id) => ({ id, rect: rectOf(tabEls.current.get(id) ?? null) ?? head })) });
      });
      cols.push({ x, y: g.y, width: right - x, height: g.height });
    });
    return { cols, areas };
  };
  const boxStyle = (d: Drop | null): CSSProperties | null => {
    const s = rectOf(stageRef.current);
    if (!d || !s) return null;
    return { left: d.box.x - s.x, top: d.box.y - s.y, width: d.box.width, height: d.box.height };
  };
  /** 놓일 자리의 이름 — 판 메뉴의 옮기기 항목과 같은 말. */
  const whereOf = (t: Target): string => {
    if (t.kind === "tab") return areaName(saved, t.col, t.row);
    if (t.kind === "row") return `${ORD[t.col]} 열 ${t.pos === "top" ? "위" : "아래"}에 새 칸`;
    return t.index === 0 ? "새 열(왼쪽 끝)" : t.index >= saved.cols.length ? "새 열(오른쪽 끝)" : `새 열(${ORD[t.index - 1]} 열 뒤)`;
  };
  const chipOf = (id: string, d: Drop | null, x: number, y: number) => {
    const s = rectOf(stageRef.current);
    const style: CSSProperties = s ? { left: x - s.x + 14, top: y - s.y + 18 } : { left: 0, top: 0 };
    return { style, ok: !!d, text: `${nameOf(id)} · ${d ? whereOf(d.target) : "놓을 수 없는 자리"}` };
  };
  const onTabPointerDown = (e: ReactPointerEvent<HTMLButtonElement>, id: string) => {
    if (e.button !== 0 || stacked || zoom) return;
    const start = { x: e.clientX, y: e.clientY };
    let geo: Geometry | null = null;
    let drop: Drop | null = null;
    const onMove = (ev: PointerEvent) => {
      if (!geo) {
        if (Math.hypot(ev.clientX - start.x, ev.clientY - start.y) <= DRAG_PX) return;
        if (folded) { cleanup(); return; }               // 합쳐 보이는 동안은 판 메뉴로 옮긴다(사유 글이 판 위에 있다)
        geo = geometry();
      }
      ev.preventDefault();
      drop = dropAt(geo, { x: ev.clientX, y: ev.clientY }, saved, id, spec);
      setDrag({ id, box: boxStyle(drop), chip: chipOf(id, drop, ev.clientX, ev.clientY) });
    };
    const onUp = () => {
      const was = geo;
      const at = drop;
      cleanup();
      if (!was) return;
      // 놓은 뒤 따라오는 click 하나(같은 판에서 놓았을 때)는 탭 고르기로 읽지 않는다 — 그 이벤트 차례가 끝나면 걷는다
      suppressClick.current = true;
      setTimeout(() => { suppressClick.current = false; }, 0);
      if (at) doMove(id, at.target);
      else say("놓을 수 없는 자리라 옮기지 않았습니다.");
    };
    /** 브라우저가 포인터를 거둔 것(터치 구르기 등) — 옮기지 않는다. */
    const onCancel = () => {
      const was = geo;
      cleanup();
      if (was) say("옮기기를 취소했습니다.");
    };
    const onKey = (ev: globalThis.KeyboardEvent) => {
      if (ev.key !== "Escape" || !geo) return;
      ev.preventDefault();
      ev.stopPropagation();
      cleanup();
      say("옮기기를 취소했습니다.");
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey, true);
      setDrag(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey, true);
  };

  const onRootKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && zoom && !e.defaultPrevented) { setZoom(null); say("배치로 되돌렸습니다."); }
  };

  // ── 그리기 ──────────────────────────────────────────────────────────────
  const els: ReactNode[] = [];
  L.cols.forEach((col, ci) => {
    col.rows.forEach((a, ri) => {
      const key = `${ci}:${ri}`;
      const act = activeOf(ci, ri);
      const zoomed = zoom === key;
      const offZoom = !!zoom && !zoomed;
      const place: CSSProperties = zoomed ? { gridColumn: "1 / -1", gridRow: `1 / ${ROWS + 1}` } : { gridColumn: String(2 * ci + 1), gridRow: rowSpan(L, ci, ri) };
      if (!stacked && ri === 1) {
        els.push(<RowSplitter key={`r:${ci}`} className="ws-row-bar" label={`${ORD[ci]} 열 아래 칸 높이`} value={a.h ?? 0.5} hidden={!!zoom}
                              style={{ gridColumn: String(2 * ci + 1), gridRow: rowSpan(L, ci, 1) }}
                              heightOf={() => gridRef.current?.clientHeight ?? 0}
                              onChange={(h, done) => { const next = structuredClone(saved); if (next.cols[ci]?.rows[1]) { next.cols[ci].rows[1].h = h; ws.setLayout(next, done); } }} />);
      }
      if (!stacked) {
        const opts = a.tabs.map((id) => ({ value: id, label: nameOf(id) }));
        els.push(
          <div key={`h:${key}`} className="ws-head" data-area={key} data-row={ri} style={place} hidden={offZoom || undefined}>
            <div className="ws-tabs" role="tablist" aria-label={`${areaName(L, ci, ri)}의 판`}>
              {a.tabs.map((id) => (
                <button key={id} ref={(el) => { if (el) tabEls.current.set(id, el); else tabEls.current.delete(id); }} type="button" role="tab"
                        id={tabId(id)} className="ws-tab" data-tab={id} aria-selected={id === act} aria-controls={panelId(id)} tabIndex={id === act ? 0 : -1}
                        onClick={() => { if (suppressClick.current) { suppressClick.current = false; return; } pickTab(id); }}
                        onKeyDown={(e) => rove(e, opts, act, pickTab, a.tabs.map((t) => tabEls.current.get(t) ?? null))}
                        onPointerDown={(e) => onTabPointerDown(e, id)}>
                  {nameOf(id)}
                </button>
              ))}
            </div>
            <MenuButton className="ws-menu-open" label={`‘${nameOf(act)}’ 판 메뉴`} items={panelItems(key, ci, ri, act)}>
              <MoreHorizontal size={16} aria-hidden />
            </MenuButton>
          </div>,
        );
      }
      for (const id of a.tabs) {
        els.push(
          <section key={`p:${id}`} id={panelId(id)} className="ws-panel" data-panel={id} data-area={key} data-row={ri}
                   data-titled={titled.has(id) ? "" : undefined} role={stacked ? "region" : "tabpanel"} aria-labelledby={stacked ? nameId(id) : tabId(id)} tabIndex={stacked ? -1 : 0}
                   hidden={stacked ? undefined : (offZoom || id !== act) || undefined} style={stacked ? undefined : place}>
            <h2 className="ws-panel-name" id={nameId(id)}>{nameOf(id)}</h2>
            {render(id)}
          </section>,
        );
      }
    });
    if (!stacked && ci < L.cols.length - 1) {
      const sp = colSplit(L, ci, widths, known, spec);
      els.push(
        <div key={`s:${ci}`} className="ws-col-slot" style={{ gridColumn: String(2 * ci + 2), gridRow: `1 / ${ROWS + 1}` }} hidden={!!zoom || undefined}>
          <Splitter className="ws-col-bar" label={`${ORD[sp.col]} 열 폭`} side={sp.side} value={sp.value} min={sp.min} max={Number.isFinite(sp.max) ? sp.max : sp.value} step={16}
                    onChange={(w, done) => { const next = structuredClone(saved); if (next.cols[sp.col] && next.cols[sp.col].w !== null) { next.cols[sp.col].w = w; ws.setLayout(next, done); } }} />
        </div>,
      );
    }
  });

  const n = saved.cols.length;
  const merged = ORD.slice(n - view.folded, n).join(" · ");
  const into = ORD[n - view.folded - 1];
  const notes = [
    ...ws.notes,
    ...(folded ? [`창이 좁아 ${merged} 열${eul("열")} ${into} 열의 탭으로 합쳐 보입니다. 넓히면 저장한 배치로 돌아갑니다. 합쳐 보이는 동안에는 끌어 놓기 대신 판 메뉴로 옮깁니다.`] : []),
    ...(stacked ? ["창이 좁아 판을 한 열로 쌓아 보입니다. 넓히면 저장한 배치로 돌아갑니다."] : []),
  ];
  const template = widths.map((w) => (w === null ? "minmax(0, 1fr)" : `${w}px`)).join(" 16px ");
  const zoomName = (() => {
    if (!zoom || stacked) return null;
    const [c, r] = zoom.split(":").map(Number);
    return L.cols[c]?.rows[r] ? areaName(L, c, r) : null;
  })();

  return (
    <div className="ws" data-mode={stacked ? "stack" : "tabs"} data-dragging={drag?.id} onKeyDown={onRootKey}>
      <div className="ws-bar">
        <LayoutMenu ws={ws} work={work} stacked={stacked} onReopen={(id) => doReopen(id)} onManage={onManage} />
        {zoomName ? (
          <div className="ws-zoom-note">
            <span>{zoomName}만 크게 보입니다. Escape로 되돌립니다.</span>
            <button type="button" className="tx-btn tx-btn--sub ws-unzoom" onClick={unzoom}>배치로 되돌리기</button>
          </div>
        ) : null}
        {notes.length ? <div className="ws-notes">{notes.map((t) => <p key={t} className="ws-note">{t}</p>)}</div> : null}
      </div>
      <p className="tx-sr ws-live" role="status" aria-live="polite">{live.text}{live.n % 2 ? "​" : ""}</p>
      <div className="ws-stage" ref={stageRef}>
        <div className="ws-grid" ref={gridEl} style={stacked ? undefined : { gridTemplateColumns: template }}>{els}</div>
        {drag?.box ? <div className="ws-drop" style={drag.box} aria-hidden="true" /> : null}
        {drag ? <div className="ws-drag-chip" style={drag.chip.style} data-ok={drag.chip.ok} aria-hidden="true">{drag.chip.text}</div> : null}
      </div>
    </div>
  );
}
