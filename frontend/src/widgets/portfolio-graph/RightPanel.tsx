"use client";
/**
 * 오른쪽 창 — 폭 손잡이 · 고른 것의 이름 · 탭(이야기·설정·자세히·갈래·선) · 고른 것에게 묻기
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 의 `<aside className="pg-side">` 를 그대로 옮김 · 동작 불변).
 */
import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { Edge } from "@xyflow/react";
import { PanelRightClose } from "lucide-react";
import { COL, portfolioGraphApi, toDoc, type AskTarget, type NodeCatalogEntry, type NodeRunResult, type PgNode, type WorkflowStage } from "@/entities/portfolio-graph";
import type { Session } from "@/entities/session";
import { AiQuestion, type useAiQuestion } from "./AiQuestion";
import { AiStory, type useAiStory } from "./AiStory";
import { BranchCompare } from "./Branches";
import { SideResize } from "./CanvasChrome";
import { TABS } from "./canvasConfig";
import { PORT_PLAIN, STAGE_VAR } from "./GraphNode";
import { NodeResultPanel } from "./NodeResultPanel";
import { toggle, type Panels } from "./panels";
import { RunHistory } from "./RunHistory";
import { SettingsPanel } from "./SettingsPanel";
import { deleteNote } from "./canvasRules";
import { usePortfolioGraph, type PgState } from "./store";
import { StoryPanel } from "./StoryPanel";
import { WirePanel } from "./WirePanel";

export function RightPanel({ s, rightShown, panels, updatePanels, setPanels, selected, selEdge, selEntry, selResult, order, staleSet, stages,
                             focusNode, nodeBadge, session, aiStory, askTarget, aiQ, askFocus, swapTo, runTo }: {
  s: PgState;
  rightShown: boolean;
  panels: Panels;
  updatePanels: (f: (p: Panels) => Panels) => void;
  setPanels: Dispatch<SetStateAction<Panels>>;
  selected: PgNode | undefined;
  selEdge: Edge | null;
  selEntry: NodeCatalogEntry | undefined;
  selResult: NodeRunResult | undefined;
  order: string[];
  staleSet: Set<string>;
  stages: WorkflowStage[];
  focusNode: (id: string) => void;
  nodeBadge: (id: string) => { num: number | null; name: string };
  session: Session;
  aiStory: ReturnType<typeof useAiStory>;
  askTarget: AskTarget | null;
  aiQ: ReturnType<typeof useAiQuestion>;
  askFocus: MutableRefObject<() => void>;
  swapTo: (id: string, kind: string) => void;
  runTo: (id: string) => Promise<void>;
}) {
  // 이야기 단계의 '숫자 자세히 보기' — 늘 같은 함수(R8 — 새 함수면 이야기 단계가 끌기 한 걸음마다 모두 다시 그려졌다).
  const setTab = s.setTab;
  const onStoryDetail = useCallback((id: string) => { focusNode(id); setTab("detail"); }, [focusNode, setTab]);
  return (
    <aside className="pg-side" aria-label="설명과 설정" hidden={!rightShown}>
      <SideResize width={panels.rightW} onChange={(w, done) => (done ? updatePanels : setPanels)((p) => ({ ...p, rightW: w }))} />
      <header className="pg-side-head">
        <h2 className="pg-side-title">
          {selected ? (
            <>
              <b className="pg-side-num" style={{ background: STAGE_VAR[selEntry?.stage ?? ""] ?? "var(--pg-st-data)" }}>{order.indexOf(selected.id) + 1}</b>
              <span>{selEntry?.plain_label ?? selected.data.kind}</span>
            </>
          ) : selEdge ? <span>선</span> : <span>이 설계 한눈에</span>}
        </h2>
        <button type="button" className="pg-panel-toggle" data-panel="right" aria-label="오른쪽 창 닫기 (])" title="오른쪽 창 닫기 (])"
                onClick={() => updatePanels((p) => toggle(p, "right"))}><PanelRightClose size={18} aria-hidden="true" /></button>
      </header>
      <nav className="pg-tabs" role="tablist">
        {TABS.filter(([k]) => (k !== "branches" || s.branches.length > 0) && (k !== "wire" || !!selEdge)).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={s.tab === k}
                  className={`pg-tab${s.tab === k ? " on" : ""}`} data-tab={k} onClick={() => s.setTab(k)}>{label}</button>
        ))}
      </nav>
      <div className="pg-panel">
        {s.tab === "story" && (
          <StoryPanel order={order} nodes={s.nodes} catalog={s.catalog ?? []} results={s.report?.nodes ?? null}
                      staleIds={staleSet} selectedId={s.selectedId} onSelect={focusNode}
                      onDetail={onStoryDetail}
                      top={<AiStory session={session} story={aiStory} badge={nodeBadge} onSelect={focusNode} />} />
        )}
        {s.tab === "branches" && (
          <BranchCompare branches={s.branches} nodes={s.nodes} catalog={s.catalog ?? []}
                         results={s.report?.nodes ?? null} staleIds={staleSet} />
        )}
        {s.tab === "wire" && selEdge && (
          <WirePanel edge={selEdge} nodes={s.nodes} edges={s.edges} catalog={s.catalog ?? []} results={s.report?.nodes ?? null}
                     stale={staleSet.has(selEdge.source)} errors={s.validation?.errors ?? []} plain={s.catalogMeta?.portPlain ?? PORT_PLAIN}
                     order={order} onFocus={focusNode}
                     relation={(s.report && !staleSet.has(selEdge.source) ? s.report.relations?.[selEdge.id] : null)
                               ?? s.validation?.relations?.[selEdge.id] ?? null}
                     record={s.report && !staleSet.has(selEdge.target) ? s.report.edges?.[selEdge.id] ?? null : null}
                     recordGap={!s.report ? null : staleSet.has(selEdge.target) ? "받는 노드가 예전 결과예요 — 다시 계산하면 점검해요."
                       : s.report.nodes[selEdge.source]?.status !== "ok" ? "보내는 노드가 계산되지 않아 점검하지 않았어요."
                       : "받는 노드를 이번에 계산하지 않아 점검하지 않았어요."}
                     onCut={() => { const st = usePortfolioGraph.getState(); st.act(() => deleteNote(st.deleteElements([], [selEdge.id]))); }}
                     onInsert={(k, i, o) => { const st = usePortfolioGraph.getState();
                       st.act(() => { st.insertOnEdge(selEdge.id, k, i, o); return "선 사이에 노드를 넣었어요."; }); }} />
        )}
        {s.tab !== "story" && s.tab !== "branches" && s.tab !== "wire" && !selected && (
          <p className="pg-empty">캔버스나 이야기에서 노드를 하나 골라 주세요.</p>
        )}
        {s.tab === "settings" && selected && (
          <SettingsPanel node={selected} entry={selEntry} nodes={s.nodes} edges={s.edges} catalog={s.catalog ?? []}
                         stageLabel={stages.find((x) => x.key === selEntry?.stage)?.label ?? null}
                         expert={s.expert} onExpert={s.setExpert}
                         onChange={(p) => s.updateParams(selected.id, p)} onRemove={() => s.act(() => deleteNote(s.deleteElements([selected.id], [])))}
                         onDuplicate={() => s.duplicateNode(selected.id)}
                         result={selResult} stale={staleSet.has(selected.id)}
                         onFocus={focusNode} onImpact={s.setProcHover} onSwap={(k) => swapTo(selected.id, k)}
                         onRewire={(port, src, h) => {
                           const st = usePortfolioGraph.getState();
                           st.act(() => { st.rewire(selected.id, port, src, h); return src ? "선을 이었어요." : "선을 뗐어요."; });
                         }}
                         onSave={() => portfolioGraphApi.save(toDoc(s.nodes, s.edges), selected.id, selResult?.view_hash ?? "")}
                         saveFollowUp={selected.data.kind === "backtest_setup" ? {
                           label: "결과 불러오기 노드 추가",
                           run: (runId) => {
                             // 시작한 실행을 읽는 노드를 설정 노드 오른쪽에 붙이고 고른다 — 링크는 없다(읽기는 run_id 로 한다).
                             const st = usePortfolioGraph.getState();
                             const id = st.addNode("backtest_load", { x: selected.position.x + COL, y: selected.position.y });
                             st.updateParams(id, { run_id: runId });
                             st.select(id);
                           },
                         } : null} />
        )}
        {s.tab === "detail" && selected && (
          <>
          <NodeResultPanel
            kind={selected.data.kind}
            result={selResult}
            stale={staleSet.has(selected.id)}
            params={selected.data.params}
            onReload={() => void runTo(selected.id)}
          />
          <h4 className="pg-h4 pg-history-h">계산 기록</h4>
          <RunHistory nodeId={selected.id} runs={s.runs} />
          </>
        )}
      </div>
      {askTarget && (askTarget.kind === "node" ? !!selected : !!selEdge) && (
        <AiQuestion q={aiQ} session={session} badge={nodeBadge} focusRef={askFocus}
                    target={askTarget.kind === "node" ? askTarget : { ...askTarget, source: selEdge!.source, targetNode: selEdge!.target }}
                    onRunTo={(id) => void runTo(id)} onGotoNode={focusNode}
                    onGotoEdge={(id) => usePortfolioGraph.getState().selectEdge(id)} />
      )}
    </aside>
  );
}
