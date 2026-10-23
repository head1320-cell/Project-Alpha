"use client";
/**
 * 떠 있는 판 · 맞춰 보기 · 확대 (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변)
 * ==========================================================================
 * 본체가 쓰던 자리에서 그대로 부른다(effect 순서 보존). 돌려주는 이름은 본체의 지역 변수 이름 그대로.
 */
import { useCallback, useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import { NODE_W } from "@/entities/portfolio-graph";
import { MAX_ZOOM, MIN_ZOOM, TIGHT_MIDDLE, TOOLBAR_H, fitClear, fitTop } from "./canvasGeometry";
import { DEFAULT_PANELS, NARROW_Q, floatInsets, readPanels, savePanels, type Panels } from "./panels";
import { usePortfolioGraph, type PgState } from "./store";
import { readView } from "./view";

export function useCanvasView(rf: RefObject<ReactFlowInstance | null>, canvasEl: RefObject<HTMLDivElement>, catalogReady: boolean) {
  // 떠 있는 판(BQ Q1) — 여닫기·폭. 넓은 화면에서 바꾼 것만 이 브라우저에 남긴다(좁은 화면은 늘 닫힌 채 시작).
  const [panels, setPanels] = useState<Panels>(DEFAULT_PANELS);
  const narrowNow = () => typeof window !== "undefined" && !!window.matchMedia?.(NARROW_Q).matches;
  useEffect(() => { setPanels(readPanels(narrowNow(), window.innerWidth >= 1440)); }, []);
  useEffect(() => {
    const v = readView(), g = usePortfolioGraph.getState();
    g.setLanes(v.lanes);
    g.setWireShape(v.wire);
    g.setMinimap(v.minimap);                          // CF5b — 사람이 켠 것만(기본 끔)
    g.setShowGhosts(v.ghosts);                        // CF6 — 기본 켬
  }, []);
  const updatePanels = useCallback((f: (p: Panels) => Panels) => {
    setPanels((p) => { const n = f(p); if (!narrowNow()) savePanels(n); return n; });
  }, []);
  // 판 사이 가운데가 좁으면(알약 + 선 범례 + 걸러 보기가 한 줄에 안 듦) 범례·걸러 보기를 한 줄 아래로(BQ Q2).
  const [tight, setTight] = useState(false);
  const leftShown = panels.left && !panels.focus;
  const rightShown = panels.right && !panels.focus;
  useEffect(() => {
    const el = canvasEl.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => { const ins = floatInsets(el); setTight(el.clientWidth - ins.left - ins.right < TIGHT_MIDDLE); };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    // 판 자체의 크기도 본다 — 왼쪽 목록은 카탈로그가 온 뒤에야 그려진다.
    el.closest(".pg-root")?.querySelectorAll(".pg-palette, .pg-side").forEach((x) => ro.observe(x));
    const t = setTimeout(measure, 0);                                   // 판이 열리고 닫힌 뒤의 폭
    return () => { ro.disconnect(); clearTimeout(t); };
  }, [leftShown, rightShown, panels.rightW, catalogReady, canvasEl]);

  // 맞춰 보기 — 불러온 직후엔 노드 크기를 아직 모를 수 있어, 잴 수 있을 때까지 프레임마다 다시(최대 20번). 한 번만 60ms 뒤에 하던 것은
  // 크기를 재기 전이면 조용히 건너뛰어, 불러온 흐름이 떠 있는 판 밑에 남는 일이 가끔 있었다(묶음 상자 E2E 가 3번에 1번 찾음).
  // E2b — 본체에선 그릴 때마다 새로 만들던 함수다. 참조(ref)만 읽으므로 한 번 만들어 두어도 같다 — 훅 밖에서 의존성에 넣을 수 있게 고정한다.
  const fit = useCallback((opts?: { minZoom?: number }) => {
    let tries = 0;
    const go = () => { if (!fitClear(rf.current, canvasEl.current, opts) && tries++ < 20) requestAnimationFrame(go); };
    setTimeout(go, 60);
  }, [rf, canvasEl]);
  /** 몇 노드만 맞춰 보기 — 막 생긴 노드는 크기를 잴 때까지 다시(위 `fit` 과 같은 까닭). */
  const fitIds = useCallback((ids: string[]) => {
    let tries = 0;
    const go = () => { if (!fitClear(rf.current, canvasEl.current, { ids, maxZoom: 1, duration: 250 }) && tries++ < 20) requestAnimationFrame(go); };
    setTimeout(go, 60);
  }, [rf, canvasEl]);
  /** 판 사이 보이는 가운데를 기준으로 확대·축소(BQ Q1). */
  const zoomBy = useCallback((k: number) => {
    const inst = rf.current;
    const el = canvasEl.current;
    if (!inst || !el) return;
    const vp = inst.getViewport();
    const ins = floatInsets(el);
    const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, vp.zoom * k));
    const cx = ins.left + (el.clientWidth - ins.left - ins.right) / 2;
    const cy = (el.clientHeight - ins.bottom) / 2;
    const r = z / vp.zoom;
    inst.setViewport({ x: cx - (cx - vp.x) * r, y: cy - (cy - vp.y) * r, zoom: z });
  }, [rf, canvasEl]);
  return { panels, setPanels, updatePanels, tight, leftShown, rightShown, fit, fitIds, zoomBy };
}

/** 화면이 따라가기 — 상자에 들어가기 · 고른 노드가 판 밑이면 판만 옮기기 · 고르면 오른쪽 창 열기 · 갈래를 만들면 함께 보이기(본체의 같은 자리에서 부른다). */
export function useViewFollow(s: PgState, rf: RefObject<ReactFlowInstance | null>, canvasEl: RefObject<HTMLDivElement>, ctx: unknown,
                              leftShown: boolean, rightShown: boolean, setPanels: Dispatch<SetStateAction<Panels>>) {
  // 들어가기 — 그 상자에 맞춰 확대하고, 나오면 전체로.
  useEffect(() => {
    if (!rf.current) return;
    const g = s.groups.find((x) => x.id === s.focusGroup);
    if (g) setTimeout(() => fitClear(rf.current, canvasEl.current, { ids: g.members, maxZoom: 1.2, duration: 250 }), 30);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 들어가고 나올 때만
  }, [s.focusGroup]);
  // 고른 노드가 캔버스 위쪽 띠(선 범례·걸러 보기 판)에 있으면 도구줄이 그 판 밑에 깔린다 — 도구줄이 보이도록 판만 살짝 내린다(BP P1).
  // 도구줄을 노드 아래로 뒤집으면 아래 노드를 가려 그 노드를 누르려던 손이 '갈래 만들기' 를 누른다(첫 시도에서 E2E 가 찾았다).
  // 고른 노드가 떠 있는 판(BQ Q1) 밑에 있어도 판을 옆으로 옮겨 보이게 한다 — 이미 보이면 움직이지 않는다.
  useEffect(() => {
    const inst = rf.current;
    const id = s.selectedId;
    // 우클릭으로 고른 경우엔 움직이지 않는다 — 메뉴가 그 자리에 떠 있는데 판이 밀리면 가리키던 곳이 어긋난다(도구줄도 안 보인다).
    if (!inst || !id || s.picked.length > 1 || ctx) return;
    // 창이 막 열린 뒤의 폭을 재도록 한 박자 늦게.
    const t = setTimeout(() => {
      const n = inst.getInternalNode(id);
      const el = canvasEl.current;
      if (!n || !el) return;
      const vp = inst.getViewport();
      const top = n.internals.positionAbsolute.y * vp.zoom + vp.y;
      const left = n.internals.positionAbsolute.x * vp.zoom + vp.x;
      const right = left + (n.measured?.width ?? NODE_W) * vp.zoom;
      const ins = floatInsets(el);
      const need = fitTop(el) + TOOLBAR_H;
      const dy = top < need ? need - top : 0;
      let dx = 0;
      const maxRight = el.clientWidth - ins.right - 16;
      if (right > maxRight) dx = maxRight - right;
      if (left + dx < ins.left + 16) dx = ins.left + 16 - left;
      if (dx || dy) inst.setViewport({ ...vp, x: vp.x + dx, y: vp.y + dy }, { duration: 200 });
    }, 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 고를 때·창이 열리고 닫힐 때만
  }, [s.selectedId, rightShown, leftShown]);
  // 노드를 고르면 오른쪽 창이 열린다 — × 로 닫았으면 다음에 고를 때 다시 열린다. 집중 모드(\)에서는 고르기만.
  useEffect(() => {
    if (s.selectedId) setPanels((p) => (p.focus || p.right ? p : { ...p, right: true }));
  }, [s.selectedId, setPanels]);
  // 갈래를 막 만들었으면 원본 뿌리와 새 갈래가 함께 보이게 옮긴다(복제는 원본 아래에 놓인다).
  const nBranches = useRef(s.branches.length);
  useEffect(() => {
    const grew = s.branches.length > nBranches.current;
    nBranches.current = s.branches.length;
    const b = s.branches[s.branches.length - 1];
    if (!grew || !b || !rf.current) return;
    const ids = [...Object.keys(b.map), ...Object.values(b.map)];
    setTimeout(() => fitClear(rf.current, canvasEl.current, { ids, minZoom: 0.6, maxZoom: 1, duration: 250 }), 30);
  }, [s.branches, rf, canvasEl]);
}
