"use client";
/**
 * 파일·템플릿 불러오기 · 목록에서 끌어 놓기(선 위에 놓으면 그 사이에 끼우기)
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · 본체의 같은 자리에서 부른다).
 */
import { useCallback, type Dispatch, type DragEvent, type RefObject, type SetStateAction } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import { NODE_W, TEMPLATES, restackDoc, type ParseResult } from "@/entities/portfolio-graph";
import { readGraphFile } from "@/features/portfolio-graph-io";
import { OVERLAP_NOTE, overlapping } from "./canvasRules";
import { PALETTE_KIND_PREFIX, PALETTE_MIME } from "./NodePalette";
import { usePortfolioGraph } from "./store";

export function useCanvasDrop(rf: RefObject<ReactFlowInstance | null>, setFileNote: (n: string | null) => void, fit: () => void,
                              setDragOver: (v: boolean) => void, setDropWire: Dispatch<SetStateAction<string | null>>,
                              addAt: (kind: string, pos?: { x: number; y: number }) => string) {
  const applyLoad = useCallback((r: ParseResult, fileName: string) => {
    if (!r.doc) {
      setFileNote(`「${fileName}」을 불러오지 않았어요 — ${r.problems.join(" ")} 캔버스는 그대로예요.`);
      return;
    }
    usePortfolioGraph.getState().loadDoc(r.doc, r.problems);
    setFileNote(`「${fileName}」을 불러왔어요 — 노드 ${r.doc.nodes.length}개, 링크 ${r.doc.edges.length}개.${overlapping() ? ` ${OVERLAP_NOTE}` : ""}`);
    fit();
  }, [fit, setFileNote]);

  const loadTemplate = useCallback((key: string) => {
    const t = TEMPLATES.find((x) => x.key === key) ?? TEMPLATES[0];
    const st = usePortfolioGraph.getState();
    st.loadDoc(restackDoc(t.doc, st.catalog));
    setFileNote(`‘${t.name}’을 불러왔어요. 종목·조건은 예시예요 — 노드를 눌러 바꿔 보세요.`);
    fit();
  }, [fit, setFileNote]);

  /**
   * 선 위에 놓기(BT4, KNIME 식) — 끄는 점 아래의 선을 찾고, 그 선의 타입을 받아 같은 타입을 내는 종류일 때만 끼울 수 있다.
   * 끼울 수 없으면 null — 그때는 예전처럼 그 자리에 놓는다(조용히 끼우지 않는다).
   */
  const insertSpot = useCallback((x: number, y: number, kind: string): { edge: string; i: string; o: string } | null => {
    const st = usePortfolioGraph.getState();
    const g = document.elementsFromPoint(x, y).map((el) => el.closest(".react-flow__edge")).find(Boolean);
    const id = g?.getAttribute("data-testid")?.replace(/^rf__edge-/, "");
    const e = id ? st.edges.find((x) => x.id === id) : undefined;
    if (!e) return null;
    const cat = st.catalog ?? [];
    const type = cat.find((c) => c.type === st.nodes.find((n) => n.id === e.source)?.data.kind)
      ?.outputs.find((p) => p.name === e.sourceHandle)?.type;
    const k = cat.find((c) => c.type === kind);
    const i = k?.inputs.find((p) => p.type === type);
    const o = k?.outputs.find((p) => p.type === type);
    return type && i && o ? { edge: e.id, i: i.name, o: o.name } : null;
  }, []);
  const onDragOverCanvas = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOver(e.dataTransfer.types.includes("Files"));
    const t = e.dataTransfer.types.find((x) => x.startsWith(PALETTE_KIND_PREFIX));
    const spot = t ? insertSpot(e.clientX, e.clientY, t.slice(PALETTE_KIND_PREFIX.length)) : null;
    setDropWire((w) => (w === (spot?.edge ?? null) ? w : spot?.edge ?? null));
  }, [insertSpot, setDragOver, setDropWire]);

  const onDrop = useCallback(async (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    setDropWire(null);
    const file = e.dataTransfer.files?.[0];
    if (file) { applyLoad(await readGraphFile(file), file.name); return; }
    const kind = e.dataTransfer.getData(PALETTE_MIME);
    if (!kind || !rf.current) return;
    const spot = insertSpot(e.clientX, e.clientY, kind);
    if (spot) {
      const st = usePortfolioGraph.getState();
      const at = rf.current.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      st.act(() => {
        st.insertOnEdge(spot.edge, kind, spot.i, spot.o, { x: at.x - NODE_W / 2, y: at.y - 30 });
        return "선 사이에 노드를 넣었어요.";
      });
      return;
    }
    addAt(kind, rf.current.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  }, [addAt, applyLoad, insertSpot, rf, setDragOver, setDropWire]);
  return { applyLoad, loadTemplate, onDragOverCanvas, onDrop };
}
