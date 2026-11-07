"use client";
/**
 * 캔버스 위 도구줄 — 편집 단추 · 전략 추가 · 미니맵·보기·명령 찾기 · 이름과 목표 · 결과 요약 · 서랍 · 불러오기·내보내기 · 계산하기
 * (CF 3부 E2b — `PortfolioCanvas.tsx` 의 `<header className="pg-toolbar">` 를 그대로 옮김 · 동작 불변).
 */
import type { ReactNode } from "react";
import { Boxes, Command, ImageDown, LayoutGrid, LayoutList, Loader2, Map as MapIcon, Plus, Redo2, Sparkles, Undo2 } from "lucide-react";
import { toDoc, type ParseResult } from "@/entities/portfolio-graph";
import { ExportButton, ImportControl } from "@/features/portfolio-graph-io";
import { MoreMenu } from "./CanvasAssist";
import { exportCanvasPng } from "./canvasPng";
import { NameWithGoal, ViewMenu } from "./CanvasChrome";
import { DRAWERS, type DrawerKey } from "./canvasConfig";
import type { PgState } from "./store";
import type { WireShape } from "./wirePath";

export function CanvasToolbar({ s, fit, setGoalOpen, stratOpen, setStratOpen, strategySources, addStrategy, toggleMinimap, toggleLanes,
                                fitToLanes, setWire, toggleGhosts, setCmdOpen, nErrors, runStale, applyLoad, drawer, setDrawer, topExtra, run }: {
  s: PgState;
  fit: () => void;
  setGoalOpen: (v: boolean) => void;
  stratOpen: boolean;
  setStratOpen: (f: (o: boolean) => boolean) => void;
  strategySources: { key: string; label: string; sub: string; src: Parameters<PgState["addStrategy"]>[0] }[];
  addStrategy: (src: Parameters<PgState["addStrategy"]>[0]) => void;
  toggleMinimap: () => void;
  toggleLanes: () => void;
  fitToLanes: () => void;
  setWire: (w: WireShape) => void;
  toggleGhosts: () => void;
  setCmdOpen: (v: boolean) => void;
  nErrors: number;
  runStale: () => Promise<void>;
  applyLoad: (r: ParseResult, fileName: string) => void;
  drawer: DrawerKey | null;
  setDrawer: (k: DrawerKey) => void;
  topExtra?: ReactNode;
  run: () => Promise<void>;
}) {
  return (
    <header className="pg-toolbar">
      <h1 className="pg-title">포트폴리오 설계</h1>

      <div className="pg-edit-tools" role="toolbar" aria-label="편집">
        <button type="button" className="pg-icon-tool" aria-label="되돌리기 (Ctrl+Z)" title="되돌리기 (Ctrl+Z)"
                disabled={s.past.length === 0} onClick={s.undo}><Undo2 size={16} /></button>
        <button type="button" className="pg-icon-tool" aria-label="다시하기 (Ctrl+Shift+Z)" title="다시하기 (Ctrl+Shift+Z)"
                disabled={s.future.length === 0} onClick={s.redo}><Redo2 size={16} /></button>
        <button type="button" className="pg-icon-tool" aria-label="자동 정리" title="자동 정리"
                disabled={s.nodes.length === 0} onClick={() => { s.autoLayout(); fit(); }}><LayoutGrid size={16} /></button>
        <button type="button" className="pg-icon-tool" aria-label="고른 노드 묶기 (Ctrl+G)" title="고른 노드 묶기 (Ctrl+G)"
                disabled={s.picked.length < 2} onClick={() => s.groupPicked()}><Boxes size={16} /></button>
        <button type="button" className="pg-icon-tool pg-goal-open" aria-label="목표로 시작" title="목표로 시작 — 무엇을 하려는지 고르면 흐름을 만들어 계산해요"
                disabled={!s.catalog} onClick={() => setGoalOpen(true)}><Sparkles size={16} /></button>
        <button type="button" className={`pg-icon-tool pg-simple-toggle${s.simple ? " on" : ""}`} aria-pressed={s.simple}
                aria-label="간단히 보기" title="간단히 보기 — 노드 없이 정할 것과 결과만" onClick={() => s.setSimple(!s.simple)}>
          <LayoutList size={16} />
        </button>
        <span className="pg-strat-menu-wrap">
          <button type="button" className="pg-strat-add" aria-haspopup="menu" aria-expanded={stratOpen}
                  disabled={!s.catalog} onClick={() => setStratOpen((o) => !o)}>
            <Plus size={15} aria-hidden="true" /><span className="pg-strat-add-tl">전략 추가</span>
          </button>
          {stratOpen && (
            <div className="pg-strat-menu" role="menu" aria-label="전략 추가">
              <p className="pg-strat-menu-h">새 전략 띠로 넣고 ‘전략 합치기’에 이어요</p>
              {strategySources.map((x) => (
                <button key={x.key} type="button" role="menuitem" className="pg-strat-item" data-source={x.key}
                        onClick={() => addStrategy(x.src)}>
                  <b>{x.label}</b><span>{x.sub}</span>
                </button>
              ))}
            </div>
          )}
        </span>
        <button type="button" className={`pg-icon-tool${s.showMinimap ? " on" : ""}`} aria-pressed={s.showMinimap}
                aria-label="미니맵" title="미니맵" onClick={toggleMinimap}><MapIcon size={16} /></button>
        <ViewMenu lanes={s.showLanes} onLanes={toggleLanes} onFitLanes={fitToLanes} wire={s.wireShape} onWire={setWire}
                  ghosts={s.showGhosts} onGhosts={toggleGhosts} />
        <button type="button" className="pg-icon-tool pg-cmd-open" aria-label="명령 찾기 (Ctrl+K)" title="명령 찾기 (Ctrl+K)"
                onClick={() => setCmdOpen(true)}><Command size={16} /></button>
      </div>
      <NameWithGoal name={s.name} onName={s.setName} goal={s.goal} onGoal={s.setGoal} />
      <span className="pg-toolbar-spacer" />
      {nErrors > 0 && <span className="pg-summary pg-summary--err">설정을 확인할 곳이 {nErrors}군데 있어요</span>}
      {s.reportStale && (
        <span className="pg-summary pg-summary--stale" data-count={s.staleIds.length}>
          예전 결과 {s.staleIds.length}개
          <button type="button" className="pg-stale-run" disabled={s.running} onClick={() => void runStale()}
                  title="바뀐 노드와 그 하류만 다시 계산해요">바뀐 곳만 계산</button>
        </span>
      )}
      {s.report?.partial && !s.reportStale && (
        <span className="pg-summary pg-summary--partial">여기까지 계산 · {s.report.partial.computed.length}개</span>
      )}
      {s.report && !s.reportStale && !s.report.partial && (
        <span className="pg-summary">
          완료 {Object.values(s.report.nodes).filter((r) => r.status === "ok").length} · 막힘{" "}
          {Object.values(s.report.nodes).filter((r) => r.status === "blocked").length} · 실패{" "}
          {Object.values(s.report.nodes).filter((r) => r.status === "failed").length}
          {/* 좁은 화면에서도 누르지 않고 보이는 연습용 표시(BQ Q1) — 오른쪽 창이 닫혀 있고 노드 칩이 멀리 확대에서 숨어도 합성 수가 실데이터처럼 읽히지 않게. */}
          {Object.values(s.report.nodes).some((r) => r.lineage?.practice) && (
            <b className="pg-summary-practice" title="연습용 합성 데이터로 계산한 결과예요 — 실제 시세가 아니에요"> · 연습용</b>
          )}
        </span>
      )}
      <MoreMenu drawers={DRAWERS} onDrawer={(k) => setDrawer(k as DrawerKey)} onImport={applyLoad} canExport={s.nodes.length > 0}
                getDoc={() => toDoc(s.nodes, s.edges, { name: s.name || undefined, ...(s.goal ? { goal: s.goal } : {}), exported_at: new Date().toISOString() }, s.groups, s.branches, s.pinned, s.folded)} />
      <nav className="pg-drawers" aria-label="서랍">
        {DRAWERS.map((d) => (
          <button key={d.key} type="button" className="pg-drawer-open" aria-haspopup="dialog" title={d.sub}
                  aria-expanded={drawer === d.key} onClick={() => setDrawer(d.key)}>
            <d.Icon size={15} aria-hidden="true" /><span className="pg-tl">{d.label}</span>
          </button>
        ))}
      </nav>
      {topExtra}
      <ImportControl onLoad={applyLoad} />
      <ExportButton getDoc={() => toDoc(s.nodes, s.edges, { name: s.name || undefined, ...(s.goal ? { goal: s.goal } : {}), exported_at: new Date().toISOString() }, s.groups, s.branches, s.pinned, s.folded)}
                    disabled={s.nodes.length === 0} />
      {/* 그림(R7) — 그래프 전체를 PNG 한 장으로 · 아래 띠에 이름·때·결과의 성격 */}
      <button type="button" className="pg-export-png pg-btn" disabled={s.nodes.length === 0} onClick={() => void exportCanvasPng()}
              aria-label="그래프 전체를 그림(PNG)으로 받기 — 아래 띠에 이름·때·결과의 성격을 적어요">
        <ImageDown size={13} aria-hidden="true" /> <span className="pg-tl">그림</span>
      </button>
      <button type="button" className="pg-run pg-btn pg-btn--primary" onClick={() => void run()} title="Ctrl+Enter"
              disabled={s.running || !s.catalog || s.nodes.length === 0}>
        {s.running ? <><Loader2 size={14} className="spin" /> 계산하는 중{s.runningIds ? ` · ${s.runningIds.length}개` : ""}</> : "계산하기"}
      </button>
    </header>
  );
}
