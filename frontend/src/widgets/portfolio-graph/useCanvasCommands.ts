"use client";
/**
 * 단축키 · 보기 켬끔(레인·미니맵·선 모양·추천 유령) · 명령 찾기 목록
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · 본체의 같은 자리에서 부른다 — 명령 목록은 예전처럼 열 때마다 새로 만든다).
 */
import { useEffect, useMemo, type MutableRefObject } from "react";
import { TEMPLATES } from "@/entities/portfolio-graph";
import type { useAiAssist } from "./AiAsk";
import { DRAWERS, type DrawerKey } from "./canvasConfig";
import { neighbour } from "./canvasGeometry";
import { exportCanvasPng } from "./canvasPng";
import { deleteNote } from "./canvasRules";
import { ALIGN_ITEMS } from "./guides";
import type { PaletteCommand } from "./CommandPalette";
import { toggle, type Panels } from "./panels";
import { usePortfolioGraph, type PgState } from "./store";
import { pickableIds } from "./storeShared";
import { readView, saveView } from "./view";
import { WIRE_SHAPES, type WireShape } from "./wirePath";

export interface CommandDeps {
  run: (targets?: string[]) => Promise<void>;
  runTo: (id: string) => Promise<void>;
  updatePanels: (f: (p: Panels) => Panels) => void;
  fit: () => void;
  setCmdOpen: (v: boolean) => void;
  setFindOpen: (v: boolean) => void;
  setKeysOpen: (v: boolean) => void;
  setGoalOpen: (v: boolean) => void;
  setDrawer: (k: DrawerKey | null) => void;
  focusRef: MutableRefObject<(id: string) => void>;
  askFocus: MutableRefObject<() => void>;
  leftShown: boolean;
  rightShown: boolean;
  panels: Panels;
  cmdOpen: boolean;
  openSay: () => void;
  ai: ReturnType<typeof useAiAssist>;
  strategySources: { key: string; label: string; sub: string; src: Parameters<PgState["addStrategy"]>[0] }[];
  addStrategy: (src: Parameters<PgState["addStrategy"]>[0]) => void;
  loadTemplate: (key: string) => void;
  /** 선 누르기와 같은 길(R6) — 초점 둔 선의 Enter·Space. */
  pickEdge: (id: string) => void;
}

export function useCanvasCommands(s: PgState, d: CommandDeps) {
  const { run, runTo, updatePanels, fit, setCmdOpen, setFindOpen, setKeysOpen, setGoalOpen, setDrawer, focusRef, askFocus,
          leftShown, rightShown, panels, cmdOpen, openSay, ai, strategySources, addStrategy, loadTemplate, pickEdge } = d;
  // 단축키 — 입력 칸에 있을 때는 가로채지 않는다. Ctrl/⌘+Enter 계산 · Ctrl/⌘+D 복제 · Ctrl/⌘+A 모두 고르기 · Esc 관문 닫기 → 고르기 풀기.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      if (t?.closest("dialog")) return;                   // 서랍·명령 찾기 안의 키는 그 대화상자 몫이다
      const st = usePortfolioGraph.getState();
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === "k") { e.preventDefault(); setCmdOpen(true); }
      else if (mod && k === "f") { e.preventDefault(); setFindOpen(true); }
      else if ((e.key === "?" || (e.key === "/" && e.shiftKey)) && !mod) { e.preventDefault(); setKeysOpen(true); }
      else if (mod && e.key === "Enter" && !st.running) { e.preventDefault(); void run(); }
      else if (e.shiftKey && e.key === "Enter" && !st.running && st.selectedId) { e.preventDefault(); void runTo(st.selectedId); }
      // 초점 둔 선·노드의 Enter·Space = 누르기(R6) — ★감싸개 그 자체★에 초점일 때만(카드 안 입력 칸은 위에서 빠지고, 단추는 제 몫).
      // React Flow 의 키보드 고르기는 화면의 '고른 선'(`selectedEdge`)을 바꾸지 못해 선이 골라지지 않았다. 노드는 누르기와 같게 고른 선도 푼다.
      else if (!mod && !e.altKey && !e.shiftKey && (e.key === "Enter" || e.key === " ") && t
               && (t.classList.contains("react-flow__edge") || t.classList.contains("react-flow__node"))) {
        const id = t.getAttribute("data-id") ?? "";
        if (t.classList.contains("react-flow__edge")) { e.preventDefault(); pickEdge(id); }
        else if (!id.includes(":")) { e.preventDefault(); st.select(id); }
      }
      else if (mod && k === "z" && !e.shiftKey) { e.preventDefault(); st.undo(); }
      else if (mod && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); st.redo(); }
      else if (mod && k === "c") { if (st.copy()) e.preventDefault(); }
      else if (mod && k === "v") { if (st.paste()) e.preventDefault(); }
      else if (mod && k === "g") { e.preventDefault(); st.groupPicked(); }
      else if (mod && k === "d" && st.selectedId) { e.preventDefault(); st.duplicateNode(st.selectedId); }
      // 모두 고르기(R2) — 캔버스나 빈 곳에 초점일 때만(도구줄 단추 위에서는 브라우저 몫) · 보이는 노드만 · 들어간 상자면 그 멤버만.
      else if (mod && k === "a" && !e.shiftKey && (!t || t === document.body || !!t.closest(".pg-canvas"))) { e.preventDefault(); st.pickIds(pickableIds(st)); }
      else if (!mod && !e.altKey && e.key === "[") { e.preventDefault(); updatePanels((p) => toggle(p, "left")); }
      else if (!mod && !e.altKey && e.key === "]") { e.preventDefault(); updatePanels((p) => toggle(p, "right")); }
      else if (!mod && !e.altKey && e.key === "\\") { e.preventDefault(); updatePanels((p) => toggle(p, "focus")); }
      else if (e.key === "Escape" && st.cause) st.showCause(null);
      else if (e.key === "Escape" && st.focusGroup) { st.setFocusGroup(null); fit(); }
      else if (e.key === "Escape" && st.openGate) st.setOpenGate(null);
      // 고르기 풀기(R2) — ★맨 끝★. 메뉴·판의 Esc 는 잡는 단계에서 먼저 먹고 멈춘다(여기까지 오지 않는다).
      else if (e.key === "Escape" && (st.picked.length || st.selectedId || st.selectedEdge)) { st.select(null); st.selectEdge(null); }
      else if (e.altKey && e.key.startsWith("Arrow") && st.selectedId) {
        // 키보드로 노드 사이 이동(접근성) — ←→ 선을 따라 앞·뒤 단계, ↑↓ 흐름 번호 순서.
        const next = neighbour(st.selectedId, e.key, st.nodes, st.edges);
        if (next) { e.preventDefault(); focusRef.current(next); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, runTo, updatePanels, fit, focusRef, setCmdOpen, setFindOpen, setKeysOpen, pickEdge]);

  // 단계 레인(CF4b) — 켬/끔은 이 브라우저에 남긴다. 맞추기는 되돌리기 한 번 + 맞춰 보기.
  const toggleLanes = () => {
    const v = !usePortfolioGraph.getState().showLanes;
    usePortfolioGraph.getState().setLanes(v);
    saveView({ ...readView(), lanes: v });
  };
  const fitToLanes = () => { usePortfolioGraph.getState().fitToLanes(); fit(); };
  // 미니맵(CF5b) — 도구줄·명령 찾기·모서리 [접기]가 같은 켬/끔을 쓰고, 이 브라우저에 남긴다.
  const toggleMinimap = () => {
    const v = !usePortfolioGraph.getState().showMinimap;
    usePortfolioGraph.getState().setMinimap(v);
    saveView({ ...readView(), minimap: v });
  };
  // 선 모양(CF4c) — 보기만 바꾼다. 이 브라우저에 남긴다.
  const setWire = (w: WireShape) => { usePortfolioGraph.getState().setWireShape(w); saveView({ ...readView(), wire: w }); };
  const toggleGhosts = () => {
    const v = !usePortfolioGraph.getState().showGhosts;
    usePortfolioGraph.getState().setShowGhosts(v);
    saveView({ ...readView(), ghosts: v });
  };
  // 카드 결과(2026-11-12) — 보통·먼 확대에서도 결과를 보일지. 켬/끔은 이 브라우저에 남긴다(문서가 아니다).
  const toggleCardResults = () => {
    const v = !usePortfolioGraph.getState().showCardResults;
    usePortfolioGraph.getState().setCardResults(v);
    saveView({ ...readView(), cardResults: v });
  };

  const multiPicked = s.picked.length > 1;
  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "run", group: "계산", label: "전체 계산하기", keys: "Ctrl+Enter", run: () => void run() },
    { id: "find", group: "보기", label: "캔버스에서 노드 찾기", keys: "Ctrl+F", run: () => setFindOpen(true) },
    { id: "keys", group: "도움말", label: "단축키 보기", keys: "?", run: () => setKeysOpen(true) },
    ...(s.selectedId ? [
      { id: "dup", group: "편집", label: "선택한 노드 복제", keys: "Ctrl+D", run: () => { const st = usePortfolioGraph.getState(); if (st.selectedId) st.duplicateNode(st.selectedId); } },
      { id: "pin", group: "보기", label: s.pinned.includes(s.selectedId) ? "선택한 노드 그림 고정 해제" : "선택한 노드 그림 고정",
        run: () => { const st = usePortfolioGraph.getState(); if (st.selectedId) st.togglePin(st.selectedId); } },
      { id: "remove", group: "편집", label: "선택한 노드 삭제", keys: "Delete",
        run: () => { const st = usePortfolioGraph.getState(); const id = st.selectedId; if (id) st.act(() => deleteNote(st.deleteElements([id], []))); } },
    ] : []),
    { id: "select-all", group: "편집", label: "모두 선택", keys: "Ctrl+A", hint: "보이는 노드를 모두 선택합니다 — 들어간 상자 안이면 그 상자 노드만",
      run: () => { const st = usePortfolioGraph.getState(); st.pickIds(pickableIds(st)); } },
    ...(multiPicked ? [
      { id: "delete-picked", group: "편집", label: `선택한 노드 ${s.picked.length}개 삭제`, keys: "Delete", hint: "삭제 후 [되돌리기] 한 번으로 모두 복원됩니다",
        run: () => { const st = usePortfolioGraph.getState(); st.act(() => deleteNote(st.deleteElements(st.picked, []))); } },
      ...ALIGN_ITEMS.filter((i) => s.picked.length >= i.min).map((i) => ({ id: `align:${i.kind}`, group: "편집", label: `정렬: ${i.label}`,
        run: () => usePortfolioGraph.getState().alignPicked(i.kind) })),
    ] : []),
    { id: "goal", group: "시작", label: "목표로 새로 시작", hint: "작업 목적 · 종목 · 기간을 선택하면 흐름을 구성해 계산합니다",
      run: () => setGoalOpen(true) },
    { id: "simple", group: "보기", label: s.simple ? "캔버스로 돌아가기" : "간단히 보기", hint: "노드 없이 설정 항목과 결과만 표시합니다",
      run: () => { const st = usePortfolioGraph.getState(); st.setSimple(!st.simple); } },
    ...(s.selectedId ? [{ id: "run-to", group: "계산", label: "선택한 노드까지 계산", keys: "Shift+Enter",
                          run: () => void runTo(usePortfolioGraph.getState().selectedId!) }] : []),
    { id: "undo", group: "편집", label: "되돌리기", keys: "Ctrl+Z", run: () => usePortfolioGraph.getState().undo() },
    ...(s.nodes.length ? [{ id: "export-png", group: "파일", label: "그림(PNG)으로 받기", hint: "그래프 전체를 한 장으로 — 아래 띠에 이름·시각·결과의 성격",
                            run: () => void exportCanvasPng() }] : []),
    { id: "redo", group: "편집", label: "다시하기", keys: "Ctrl+Shift+Z", run: () => usePortfolioGraph.getState().redo() },
    { id: "layout", group: "보기", label: "자동 정리", hint: "흐름 순서대로 왼쪽에서 오른쪽으로 배치합니다",
      run: () => { usePortfolioGraph.getState().autoLayout(); fit(); } },
    { id: "panel-left", group: "보기", label: leftShown ? "왼쪽 목록 닫기" : "왼쪽 목록 열기", keys: "[",
      run: () => updatePanels((p) => toggle(p, "left")) },
    { id: "panel-right", group: "보기", label: rightShown ? "오른쪽 창 닫기" : "오른쪽 창 열기", keys: "]",
      run: () => updatePanels((p) => toggle(p, "right")) },
    { id: "panel-focus", group: "보기", label: panels.focus ? "집중 끝내기" : "집중해서 보기", keys: "\\",
      hint: "왼쪽 목록과 오른쪽 창을 잠시 모두 닫습니다", run: () => updatePanels((p) => toggle(p, "focus")) },
    { id: "minimap", group: "보기", label: s.showMinimap ? "미니맵 끄기" : "미니맵 켜기",
      run: toggleMinimap },
    { id: "lanes", group: "보기", label: s.showLanes ? "단계 레인 끄기" : "단계 레인 보기", hint: "흐름 여섯 단계를 왼쪽에서 오른쪽 세로 띠로 표시합니다",
      run: toggleLanes },
    ...(s.showLanes ? [{ id: "fit-lanes", group: "보기", label: "레인에 맞추기", hint: "노드를 각 단계 띠 안으로 이동합니다", run: fitToLanes }] : []),
    { id: "ghosts", group: "보기", label: s.showGhosts ? "추천 유령 끄기" : "추천 유령 보기",
      hint: "서버 규칙이 제안한 다음 노드를 추가할 위치에 반투명하게 표시합니다", run: toggleGhosts },
    { id: "card-results", group: "보기", label: s.showCardResults ? "카드 결과 숨기기" : "카드에 결과 표시",
      hint: "보통·먼 확대에서도 노드 카드에 작은 그림 · 사실 줄 · 증거 칩을 표시합니다", run: toggleCardResults },
    ...(s.selectedId || s.selectedEdge ? [{ id: "ask-here", group: "AI", label: s.selectedId ? "선택한 노드에게 묻기" : "선택한 선에게 묻기",
      hint: "오른쪽 창 아래 칸에서 계산 결과에 대해 Claude 에게 질의합니다(로그인 · 계산 후)",
      run: () => { updatePanels((p) => (p.right ? p : toggle(p, "right"))); window.setTimeout(() => askFocus.current(), 60); } }] : []),
    { id: "say", group: "AI", label: "말로 설계", hint: "자연어로 현재 캔버스를 수정하는 초안을 받습니다(로그인 · 수락할 때만 반영됩니다)",
      run: openSay },
    { id: "ai-ask", group: "추천", label: "AI 에게 다음 노드 묻기",
      hint: "현재 그래프를 Claude 에게 전송해 다음에 추가할 노드를 질의합니다(로그인 · 누를 때만)", run: () => { void ai.ask(); } },
    ...WIRE_SHAPES.map((w) => ({ id: `wire:${w.shape}`, group: "보기", label: `선 모양: ${w.label}`,
                                 hint: "선을 두 번 누르면 경유점을 추가해 경로를 변경할 수 있습니다", run: () => setWire(w.shape) })),
    { id: "group", group: "편집", label: "선택한 노드 묶기", keys: "Ctrl+G", hint: "노드를 두 개 이상 선택하십시오",
      run: () => usePortfolioGraph.getState().groupPicked() },
    ...(s.selectedId ? [{ id: "branch", group: "비교", label: "선택한 노드에서 대안 만들기",
                          hint: "그 노드와 하류를 복제해 설정만 바꿔 비교합니다(한 노드에 4개까지)",
                          run: () => { const st = usePortfolioGraph.getState(); if (st.selectedId) st.act(() => st.makeBranch(st.selectedId!)); } }] : []),
    ...(multiPicked ? [{ id: "branch-picked", group: "비교", label: "선택한 노드로 대안 만들기",
                                 hint: "선택한 노드만 복제해 설정을 바꿔 비교합니다 — 뿌리는 흐름 맨 앞(한 뿌리에 4개까지)",
                                 run: () => { const st = usePortfolioGraph.getState(); st.act(() => st.branchPicked()); } }] : []),
    { id: "strategy-picked", group: "전략", label: "선택한 노드를 전략으로 묶기", hint: "비중 출력 노드가 포함돼야 합니다",
      run: () => { const st = usePortfolioGraph.getState(); st.act(() => st.strategyPicked()); } },
    { id: "compare-picked", group: "비교", label: "선택한 노드 견고성 비교",
      hint: "비중을 산출하는 노드 2~4개를 선택해 평시·위기 상관과 낙폭 구간의 중첩을 비교합니다",
      run: () => { const st = usePortfolioGraph.getState(); st.act(() => st.comparePicked()); } },
    ...strategySources.map((x) => ({ id: `strategy:${x.key}`, group: "전략", label: `전략 추가: ${x.label}`, hint: x.sub,
                                     run: () => addStrategy(x.src) })),
    ...DRAWERS.map((d) => ({ id: `drawer:${d.key}`, group: "서랍", label: `${d.label} 열기`, hint: d.sub,
                             run: () => setDrawer(d.key) })),
    ...TEMPLATES.map((t) => ({ id: `tpl:${t.key}`, group: "템플릿", label: `${t.name} 불러오기`, hint: t.description,
                               run: () => loadTemplate(t.key) })),
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 명령은 열 때마다 새로 만든다
  ], [s.selectedId, s.selectedEdge, multiPicked, s.picked.length, s.showMinimap, s.showLanes, s.showGhosts, s.showCardResults, ai.ask, cmdOpen, strategySources, s.simple, leftShown, rightShown, panels.focus, s.nodes.length]);
  return { toggleLanes, fitToLanes, toggleMinimap, setWire, toggleGhosts, toggleCardResults, commands };
}
