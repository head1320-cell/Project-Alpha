"use client";
/**
 * 캔버스 둘레의 작은 부품 (CF 3부 E2a — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변)
 * ==========================================================================
 * 확대 표시 · 고른 노드 막대 · 열린 메뉴 닫기 · 정렬 메뉴 · 확대율 · 보기 메뉴 · 이름 + 목표 칩 · 단계 레인 · 오른쪽 창 폭 손잡이.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import { ControlButton, NodeToolbar, Position, ViewportPortal, useStore } from "@xyflow/react";
import { AlignStartVertical, Check, Eye, Target } from "lucide-react";
import { GOALS, cardHeight, type GoalKey, type WorkflowStage } from "@/entities/portfolio-graph";
import { laneLayout } from "@/entities/portfolio-graph/lanes";
import { SELBAR_ROOM, SELBAR_W, zoomLevel } from "./canvasGeometry";
import { STAGE_VAR } from "./GraphNode";
import { ALIGN_ITEMS, type AlignKind } from "./guides";
import { RIGHT_W, clampW, floatCorner, floatInsets } from "./panels";
import { usePortfolioGraph } from "./store";
import { measuredH, measuredW } from "./toolbarPlace";
import { WIRE_SHAPES, type WireShape } from "./wirePath";

/** 확대 값을 캔버스 요소의 `data-zoom`·`--pg-z` 로 옮긴다 — 노드를 다시 그리지 않고 CSS 가 단계별로 보이고 숨긴다. */
export function ZoomWatch({ el }: { el: RefObject<HTMLDivElement> }) {
  const z = useStore((st) => st.transform[2]);
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    node.dataset.zoom = zoomLevel(z);
    node.style.setProperty("--pg-z", String(z));
  }, [z, el]);
  return null;
}
export function SelBar({ ids, children }: { ids: string[]; children: ReactNode }) {
  // 가로도 — 가운데에 두면 떠 있는 오른쪽 창·왼쪽 목록 밑으로 들어가는 경우 고른 노드의 끝에 맞춘다(E2E 가 찾음).
  const place = useStore((st) => {
    const [tx, ty, zoom] = st.transform;
    let top = Infinity, bottom = -Infinity, left = Infinity, right = -Infinity;
    for (const id of ids) {
      const n = st.nodeLookup.get(id);
      if (!n) continue;
      const p = n.internals.positionAbsolute;
      top = Math.min(top, p.y * zoom + ty);
      bottom = Math.max(bottom, (p.y + measuredH(n)) * zoom + ty);
      left = Math.min(left, p.x * zoom + tx);
      right = Math.max(right, (p.x + measuredW(n)) * zoom + tx);
    }
    const ins = floatInsets(st.domNode ?? null);
    const mid = (left + right) / 2;
    const align = mid + SELBAR_W / 2 > st.width - ins.right ? "end" : mid - SELBAR_W / 2 < ins.left ? "start" : "center";
    // 아래에 두면 켜진 미니맵(CF5b) 밑에 깔리는지 — 깔리면 단추를 누를 수 없다(CF5c E2E 가 찾음). 위에 자리가 있으면 위로.
    const mm = floatCorner(st.domNode ?? null);
    const barL = align === "end" ? right - SELBAR_W : align === "start" ? left : mid - SELBAR_W / 2;
    const underMap = !!mm && barL + SELBAR_W > mm.x && bottom + 14 + 44 > mm.y;
    const below = (st.height - ins.bottom - bottom >= SELBAR_ROOM && !underMap) || top < SELBAR_ROOM;
    return `${below ? "b" : "t"}|${align}`;
  });
  const [side, align] = place.split("|") as ["b" | "t", "start" | "center" | "end"];
  return (
    <NodeToolbar nodeId={ids} isVisible position={side === "b" ? Position.Bottom : Position.Top} align={align} offset={14}
                 className="pg-selbar">
      {children}
    </NodeToolbar>
  );
}

/** 열린 메뉴 닫기 — 바깥을 누르거나 Escape. 정렬·보기 메뉴가 같이 쓴다. */
export function useDismiss(open: boolean, close: () => void, ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!ref.current?.contains(e.target as HTMLElement)) close(); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("pointerdown", away);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("pointerdown", away); window.removeEventListener("keydown", esc); };
  }, [open, close, ref]);
}

/** 정렬·간격(CF4a) — 고른 카드 막대의 '정렬' 단추 하나 → 글자 항목(간격 맞추기는 셋 이상일 때만). 툴팁 없이 보이는 글. */
export function AlignMenu({ n, onPick }: { n: number; onPick: (k: AlignKind) => void }) {
  const [open, setOpen] = useState(false);
  const [dir, setDir] = useState<"down" | "up">("down");
  const ref = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  // 열 쪽 — 캔버스 안에 메뉴가 다 들어가는 쪽(아래 먼저). 둘 다 모자라면 넓은 쪽. 그리기 전에 정한다(깜빡임 없음).
  useLayoutEffect(() => {
    if (!open || !ref.current || !menu.current) return;
    const b = ref.current.getBoundingClientRect();
    const c = ref.current.closest(".pg-canvas")?.getBoundingClientRect();
    if (!c) return;
    const h = menu.current.offsetHeight + 8, below = c.bottom - b.bottom, above = b.top - c.top;
    setDir(below >= h || below >= above ? "down" : "up");
  }, [open]);
  useDismiss(open, useCallback(() => setOpen(false), []), ref);
  return (
    <div className="pg-align" ref={ref}>
      <button type="button" className="pg-selbar-b pg-align-open" aria-haspopup="menu" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        <AlignStartVertical size={14} aria-hidden="true" /> 정렬
      </button>
      {open && (
        <div className="pg-align-menu" role="menu" aria-label="정렬" data-dir={dir} ref={menu}>
          {ALIGN_ITEMS.filter((i) => n >= i.min).map((i) => (
            <button key={i.kind} type="button" role="menuitem" data-align={i.kind}
                    onClick={() => { setOpen(false); onPick(i.kind); }}>{i.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

/** 확대율(CF5b) — 지금 배율(%). 누르면 100%(떠 있는 판 사이 가운데 기준 — `zoomBy`). */
export function ZoomPct({ onReset }: { onReset: (zoom: number) => void }) {
  const z = useStore((st) => st.transform[2]);
  const pct = Math.round(z * 100);
  return (
    <ControlButton className="pg-zoom-pct" title="누르면 100%" aria-label={`확대율 ${pct}% — 누르면 100%`} onClick={() => onReset(z)}>
      {pct}%
    </ControlButton>
  );
}

/** '보기' 메뉴(CF4b·CF4c) — 도구줄 단추 하나. 단계 레인 켬/끔 · 켜졌을 때 '레인에 맞추기' · 선 모양(곡선·직각·직선). 명령 찾기(Ctrl+K)에도 같은 항목이 있다. */
export function ViewMenu({ lanes, onLanes, onFitLanes, wire, onWire, ghosts, onGhosts }:
  { lanes: boolean; onLanes: () => void; onFitLanes: () => void; wire: WireShape; onWire: (w: WireShape) => void;
    ghosts: boolean; onGhosts: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useDismiss(open, useCallback(() => setOpen(false), []), ref);
  return (
    <span className="pg-view-wrap" ref={ref}>
      <button type="button" className={`pg-icon-tool pg-view-open${lanes ? " on" : ""}`} aria-haspopup="menu" aria-expanded={open}
              aria-label="보기" title="보기 — 단계 레인" onClick={() => setOpen((v) => !v)}><Eye size={16} /></button>
      {open && (
        <div className="pg-view-menu" role="menu" aria-label="보기">
          <button type="button" role="menuitemcheckbox" aria-checked={lanes} data-view="lanes"
                  onClick={() => { setOpen(false); onLanes(); }}>
            <span className="pg-view-check" aria-hidden="true">{lanes && <Check size={14} />}</span>단계 레인 보기
          </button>
          {lanes && (
            <button type="button" role="menuitem" data-view="fit-lanes" onClick={() => { setOpen(false); onFitLanes(); }}>
              <span className="pg-view-check" aria-hidden="true" />레인에 맞추기
            </button>
          )}
          {/* CF6 — 서버 규칙 추천을 캔버스 위 유령 노드로(기본 켬). 꺼도 아래 '다음 한 걸음' 바는 글로 남는다. */}
          <button type="button" role="menuitemcheckbox" aria-checked={ghosts} data-view="ghosts"
                  onClick={() => { setOpen(false); onGhosts(); }}>
            <span className="pg-view-check" aria-hidden="true">{ghosts && <Check size={14} />}</span>추천 보기
          </button>
          <div className="pg-view-sep" role="separator" />
          <div role="group" aria-label="선 모양" className="pg-view-group">
            <span className="pg-view-h" aria-hidden="true">선 모양</span>
            {WIRE_SHAPES.map((w) => (
              <button key={w.shape} type="button" role="menuitemradio" aria-checked={wire === w.shape} data-wire={w.shape}
                      onClick={() => { setOpen(false); onWire(w.shape); }}>
                <span className="pg-view-check" aria-hidden="true">{wire === w.shape && <Check size={14} />}</span>{w.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </span>
  );
}

/**
 * 목표 칩(AI1 목표 — 사용자 결정 2026-10-23: 네 목표를 설계에 기억 + 고치기) — ★설계 이름 칸 안 오른쪽 끝의 작은 단추★.
 * 도구 막대는 이미 꽉 차 있어(오류 줄이 있으면 1440 에서 남는 폭 65px, 1024 에서 8px — 측정) 글 칩을 두면 두 줄이 됐다(PNG 검토에서 찾음) →
 * 이름 칸 폭 안에 넣는다. 목표가 있으면 파란 표시 + 제목 풍선말·이름, 메뉴에서 바꾸거나 없앤다. '목표로 시작'은 이름도 목표 제목으로 정한다.
 * 목표는 계산에 끼지 않고 ★AI 추천의 근거★다(서버가 키를 자기 문장으로 바꾼다). 규칙 추천은 목표와 무관하다고 메뉴가 말한다.
 */
export function NameWithGoal({ name, onName, goal, onGoal }: { name: string; onName: (v: string) => void;
                                                       goal: GoalKey | null; onGoal: (g: GoalKey | null) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useDismiss(open, useCallback(() => setOpen(false), []), ref);
  const title = goal ? GOALS.find((g) => g.key === goal)?.title ?? null : null;
  const label = `이 설계의 목표: ${title ?? "정하지 않았어요"}`;
  const pick = (g: GoalKey | null) => { setOpen(false); onGoal(g); };
  // 메뉴는 캔버스 왼쪽 끝(앱 탐색 줄 오른쪽)과 화면 오른쪽 끝 사이에 머문다 — 390 에서 칩이 가운데쯤이면 그대로 두면 넘친다.
  const [place, setPlace] = useState<{ dx: number; w: number } | null>(null);
  useEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const lo = (ref.current.closest(".pg-root")?.getBoundingClientRect().left ?? 0) + 8;
    const w = Math.min(300, window.innerWidth - lo - 8);              // 360 에선 캔버스 폭이 300 + 여백보다 좁다
    setPlace({ dx: Math.max(lo, Math.min(r.left, window.innerWidth - 8 - w)) - r.left, w });
  }, [open]);
  return (
    <span className="pg-goalchip-wrap" ref={ref}>
      <input className="pg-name" value={name} placeholder="이름 없는 설계" aria-label="설계 이름" onChange={(e) => onName(e.target.value)} />
      <button type="button" className={`pg-goalchip${goal ? " on" : ""}`} aria-haspopup="menu" aria-expanded={open}
              aria-label={label} title={`${label} — AI 추천이 이 목표에 비춰 다음 노드를 골라요`} onClick={() => setOpen((v) => !v)}>
        <Target size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="pg-goalchip-menu" role="menu" aria-label="이 설계의 목표" style={place ? { left: place.dx, width: place.w } : undefined}>
          <p className="pg-goalchip-h">이 설계의 목표</p>
          {GOALS.map((g) => (
            <button key={g.key} type="button" role="menuitemradio" aria-checked={goal === g.key} data-goal={g.key} onClick={() => pick(g.key)}>
              <span className="pg-view-check" aria-hidden="true">{goal === g.key && <Check size={14} />}</span>
              <span className="pg-goalchip-text"><span className="pg-goalchip-title">{g.title}</span><span className="pg-goalchip-sub">{g.sub}</span></span>
            </button>
          ))}
          <div className="pg-view-sep" role="separator" />
          <button type="button" role="menuitemradio" aria-checked={goal === null} data-goal="none" onClick={() => pick(null)}>
            <span className="pg-view-check" aria-hidden="true">{goal === null && <Check size={14} />}</span>목표 없음
          </button>
          <p className="pg-goalchip-note">AI 추천이 이 목표에 비춰 다음 노드를 골라요. 규칙 추천은 바뀌지 않아요.</p>
        </div>
      )}
    </span>
  );
}

/** 띠 머리 높이(캔버스 좌표) — 맨 위 노드 위로 이만큼 띠를 늘려 이름을 둔다. */
const LANE_HEAD = 72;

/**
 * 단계 레인(CF4b) — 서버 단계 순서대로 왼→오 세로 띠 여섯. ★노드가 아니다★(끌 수도 고를 수도 없다 · 누르기는 캔버스로 간다).
 * 띠 x·폭은 문서·카탈로그로만(`laneLayout`) — 지금 위치와 무관하다. 위아래만 노드를 덮도록 늘인다.
 */
export function StageLanes({ stages }: { stages: WorkflowStage[] }) {
  const nodes = usePortfolioGraph((st) => st.nodes);
  const edges = usePortfolioGraph((st) => st.edges);
  const catalog = usePortfolioGraph((st) => st.catalog);
  const geo = useMemo(() => {
    if (!catalog || !stages.length) return null;
    const { lanes } = laneLayout(nodes.map((n) => ({ id: n.id, kind: n.data.kind, position: n.position })), edges, catalog, stages);
    const h = (n: (typeof nodes)[number]) => measuredH(n) || cardHeight(n.data.kind, catalog);
    const top = Math.min(0, ...nodes.map((n) => n.position.y)) - LANE_HEAD;
    const bottom = Math.max(0, ...nodes.map((n) => n.position.y + h(n))) + 40;
    return { lanes, top, h: bottom - top };
  }, [nodes, edges, catalog, stages]);
  if (!geo) return null;
  return (
    <ViewportPortal>
      <div className="pg-lanes" aria-hidden="true">
        {geo.lanes.map((l) => (
          <div key={l.key} className="pg-lane" data-stage={l.key} data-count={l.count}
               style={{ left: l.x, top: geo.top, width: l.w, height: geo.h, ["--pg-lane-c" as string]: STAGE_VAR[l.key] ?? "var(--pg-st-data)" }}>
            <div className="pg-lane-head"><span className="pg-lane-name">{l.label}</span><span className="pg-lane-n">{l.count}개</span></div>
          </div>
        ))}
      </div>
    </ViewportPortal>
  );
}

/** 오른쪽 창 폭 손잡이(BQ Q1) — 끌거나, 초점을 두고 ←(넓게)·→(좁게)·Home·End. 300~600px. 끝났을 때만 이 브라우저에 남긴다. */
export function SideResize({ width, onChange }: { width: number; onChange: (w: number, done: boolean) => void }) {
  const drag = useRef<{ x: number; w: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const onKey = (e: ReactKeyboardEvent) => {
    const next = e.key === "ArrowLeft" ? width + RIGHT_W.step : e.key === "ArrowRight" ? width - RIGHT_W.step
      : e.key === "Home" ? RIGHT_W.min : e.key === "End" ? RIGHT_W.max : null;
    if (next === null) return;
    e.preventDefault();
    onChange(clampW(next), true);
  };
  const move = (e: ReactPointerEvent) => { if (drag.current) onChange(clampW(drag.current.w + (drag.current.x - e.clientX)), false); };
  const end = (e: ReactPointerEvent) => {
    if (!drag.current) return;
    onChange(clampW(drag.current.w + (drag.current.x - e.clientX)), true);
    drag.current = null;
    setDragging(false);
  };
  return (
    <div className="pg-side-resize" role="separator" aria-orientation="vertical" aria-label="오른쪽 창 폭"
         aria-valuemin={RIGHT_W.min} aria-valuemax={RIGHT_W.max} aria-valuenow={width} tabIndex={0}
         data-drag={dragging || undefined} onKeyDown={onKey}
         onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, w: width }; setDragging(true); }}
         onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
  );
}
