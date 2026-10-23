"use client";
/**
 * 캔버스에 그릴 노드·선 (CF 3부 E2b — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변 · effect 없음)
 * ==========================================================================
 * 원인 경로 · 흐리기(들어가기·필터·절차) · 접힌 상자의 대리 포트 · 전략 띠 색과 몫 · 갈래 틀 · 선 모양과 표시.
 * 계산은 전부 스토어 상태에서 — 서버 결과의 값만 읽고 지어내지 않는다.
 */
import { useCallback, useMemo, type MutableRefObject } from "react";
import type { Node } from "@xyflow/react";
import { PORTFOLIO_NODE, cardHeight, cardWidth, fieldsOf, viaOf, type ProcedureSuggestion } from "@/entities/portfolio-graph";
import { portColor as portTypeColor } from "@/entities/portfolio-graph/ports";
import { branchDiffs, PG_BRANCH_TYPE, type BranchFrameData } from "./Branches";
import { matchFilter } from "./canvasConfig";
import { GROUP_PAD } from "./canvasGeometry";
import { PG_WIRE_TYPE, wireOf } from "./EvidenceEdge";
import { PORT_PLAIN } from "./GraphNode";
import { PG_GROUP_TYPE, type GroupFrameData } from "./GroupFrame";
import { toggle, type Panels } from "./panels";
import { usePortfolioGraph, type PgState } from "./store";
import { wireFlag, wireLook } from "./wireStyle";

export function useCanvasGraph(s: PgState, order: string[], path: Set<string>, staleSet: Set<string>,
                               refs: { runToRef: MutableRefObject<(id: string) => void>; previewRef: MutableRefObject<(id: string | null) => void>;
                                       runStrategyRef: MutableRefObject<(groupId: string) => void>; branchStrategyRef: MutableRefObject<(groupId: string) => void> },
                               onNeed: (id: string, port: string, type: string) => void, onFix: (sug: ProcedureSuggestion) => void,
                               onSocket: (id: string, port: string, type: string, side: "in" | "out") => void,
                               updatePanels: (f: (p: Panels) => Panels) => void, hoverEdge: string | null, dropWire: string | null) {
  const { runToRef, previewRef, runStrategyRef, branchStrategyRef } = refs;
  const cause = s.cause && staleSet.has(s.cause.from) ? null : s.cause;
  const causeSet = useMemo(() => new Set(cause?.path ?? []), [cause]);
  const live = useMemo(() => (s.report
    ? (staleSet.size ? Object.fromEntries(Object.entries(s.report.nodes).filter(([id]) => !staleSet.has(id))) : s.report.nodes)
    : null), [s.report, staleSet]);
  // 미니맵 칸(CF5b) — 노드 단계(카탈로그)와 표시(고름 > 실패 > 막힘, 지금 결과만).
  const stageOfNode = (id: string) => {
    const kind = s.nodes.find((x) => x.id === id)?.data.kind;
    return s.catalog?.find((c) => c.type === kind)?.stage ?? null;
  };
  const mmMark = (id: string): "picked" | "failed" | "blocked" | null =>
    s.picked.includes(id) || s.selectedId === id ? "picked"
      : live?.[id]?.status === "failed" ? "failed" : live?.[id]?.status === "blocked" ? "blocked" : null;
  // BM C2 — 들어간 상자·필터가 켜지면 나머지를 흐린다(원인 경로가 켜져 있으면 그것이 먼저다).
  const focusSet = useMemo(() => {
    const g = s.groups.find((x) => x.id === s.focusGroup);
    return g ? new Set(g.members) : null;
  }, [s.groups, s.focusGroup]);
  const filterSet = useMemo(() => {
    if (!s.filters.length || !live) return null;
    return new Set(s.nodes.map((n) => n.id).filter((id) => {
      const r = live[id];
      if (!r) return false;
      return s.filters.some((f) => matchFilter(f, r));
    }));
  }, [s.filters, s.nodes, live]);
  // BT2 — 절차 줄에 올린 동안은 그 단계 노드만 또렷하게(원인 경로가 켜져 있으면 그것이 먼저다).
  const procSet = useMemo(() => (s.procHover ? new Set(s.procHover) : null), [s.procHover]);
  const keep = cause ? causeSet : procSet ?? focusSet ?? filterSet;
  /** 노드 → 그 노드가 든 접힌 상자(대리 포트로 선을 다시 그린다). */
  const collapsedOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of s.groups) if (g.collapsed && g.id !== s.focusGroup) for (const id of g.members) m.set(id, g.id);
    return m;
  }, [s.groups, s.focusGroup]);
  const portColor = useCallback((nodeId: string, handle: string | null | undefined, side: "in" | "out") => {
    const kind = s.nodes.find((n) => n.id === nodeId)?.data.kind;
    const entry = s.catalog?.find((c) => c.type === kind);
    const p = (side === "out" ? entry?.outputs : entry?.inputs)?.find((x) => x.name === handle);
    return { color: portTypeColor(p?.type), plain: p ? PORT_PLAIN[p.type] ?? p.name : handle ?? "?" };
  }, [s.nodes, s.catalog]);
  const bandOf = useMemo(() => {
    const m = new Map<string, number>();
    for (const g of s.groups) if (g.kind === "strategy") for (const id of g.members) m.set(id, g.color ?? 0);
    return m;
  }, [s.groups]);

  /** 전략(출력 노드)의 몫 — 이은 포트폴리오 노드 결과의 서버 값(`view.strategies[port].share_pct`). 계산 전·모르면 null. */
  const shareByEdge = useCallback((target: string, port: string | null | undefined): number | null => {
    const r = live?.[target];
    if (!r || r.status !== "ok" || !port) return null;
    const rows = (r.view?.strategies as { port: string; share_pct: unknown }[] | undefined) ?? [];
    const v = rows.find((x) => x.port === port)?.share_pct;
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  }, [live]);
  /** 리밸런싱 주기의 쉬운 이름(BO O2) — 서버 x-ui 선택지. 카탈로그가 없으면 표시하지 않는다(지어내지 않는다). */
  const rebalUi = useMemo(() => fieldsOf(s.catalog?.find((c) => c.type === PORTFOLIO_NODE)?.params_schema ?? null)
    .find((f) => f.name === "rebalance")?.ui ?? null, [s.catalog]);
  const shareOf = useCallback((output: string | null): { share: number | null; linked: boolean; rebalance: string | null } => {
    const e = output ? s.edges.find((x) => x.source === output && s.nodes.find((n) => n.id === x.target)?.data.kind === PORTFOLIO_NODE) : undefined;
    const pf = e ? s.nodes.find((n) => n.id === e.target) : undefined;
    const set = (pf?.data.params.rebalance ?? {}) as Record<string, string>;
    const code = e?.targetHandle ? set[e.targetHandle] ?? (rebalUi?.empty_value as string | undefined) : undefined;
    return { share: e ? shareByEdge(e.target, e.targetHandle) : null, linked: !!e,
             rebalance: code ? rebalUi?.options?.[code] ?? null : null };
  }, [s.edges, s.nodes, shareByEdge, rebalUi]);

  const numbered = useMemo(() => {
    const num = new Map(order.map((id, i) => [id, i + 1]));
    const picked = new Set(s.picked);
    // 선택은 스토어가 진실 — 이야기 카드에서 고른 노드도, 상자로 여러 개 고른 노드도 캔버스에서 선택돼 보인다.
    const cards: Node[] = s.nodes.map((n) => ({
      ...n, hidden: collapsedOf.has(n.id), selected: picked.has(n.id) || n.id === s.selectedId,
      className: [path.has(n.id) && "pg-on-path",
                  keep && !keep.has(n.id) && "pg-dim",
                  cause && causeSet.has(n.id) && "pg-on-cause",
                  cause?.roots.includes(n.id) && "pg-cause-root"].filter(Boolean).join(" ") || undefined,
      data: { ...n.data, num: num.get(n.id), onRunTo: runToRef.current, onPreviewRunTo: previewRef.current, onNeed, onFix, onSocket },
    }));
    const frames: Node<GroupFrameData>[] = s.groups.map((g) => {
      const ms = s.nodes.filter((n) => g.members.includes(n.id));
      const strat = g.kind === "strategy";
      const x0 = Math.min(...ms.map((n) => n.position.x)) - GROUP_PAD;
      const y0 = Math.min(...ms.map((n) => n.position.y)) - GROUP_PAD - 30;
      // 상자 경계는 카드의 실제 폭·배치 높이로(BS2 — 예전 176·150 은 실제 카드와 달랐다).
      const x1 = Math.max(...ms.map((n) => n.position.x + cardWidth(n.data.kind))) + GROUP_PAD;
      const y1 = Math.max(...ms.map((n) => n.position.y + cardHeight(n.data.kind, s.catalog))) + GROUP_PAD;
      const inside = new Set(g.members);
      const collapsed = collapsedOf.has(g.members[0] ?? "") && !!g.collapsed;
      const proxyIn = collapsed ? s.edges.filter((e) => inside.has(e.target) && !inside.has(e.source)).map((e) => {
        const pc = portColor(e.target, e.targetHandle, "in");
        return { id: `in|${e.target}|${e.targetHandle}`, label: pc.plain, color: pc.color };
      }) : [];
      const outs = new Map<string, { id: string; label: string; color: string }>();
      if (collapsed) {
        for (const e of s.edges.filter((x) => inside.has(x.source) && !inside.has(x.target))) {
          const pc = portColor(e.source, e.sourceHandle, "out");
          outs.set(`${e.source}|${e.sourceHandle}`, { id: `out|${e.source}|${e.sourceHandle}`, label: pc.plain, color: pc.color });
        }
      }
      const dimmed = keep && !g.members.some((m) => keep.has(m));
      // 접은 전략 카드는 전략의 출력 노드 자리에 선다(BO O5) — 포트폴리오로 가는 선이 전략 폭만큼 길어지지 않게.
      // 자리는 여전히 노드에서 계산하므로 카드를 끌면 구성원이 함께 움직이는 규칙(차이만 옮김)은 그대로다.
      const outNode = collapsed && strat && g.output ? ms.find((n) => n.id === g.output) : undefined;
      const at = outNode ? { x: outNode.position.x, y: outNode.position.y } : { x: x0, y: y0 };
      return { id: `frame:${g.id}`, type: PG_GROUP_TYPE, position: at, zIndex: -1, selectable: false,
               className: dimmed ? "pg-dim" : undefined,
               data: { groupId: g.id, label: g.label, collapsed, members: g.members, width: x1 - x0, height: y1 - y0,
                       kind: g.kind === "strategy" ? "strategy" : "group", color: g.color ?? 0,
                       output: g.kind === "strategy" ? g.output ?? null : null, proxyIn, proxyOut: [...outs.values()],
                       ...(strat ? shareOf(g.output ?? null) : { share: null, linked: false, rebalance: null }),
                       onRunStrategy: runStrategyRef.current, onBranchStrategy: branchStrategyRef.current } };
    });
    // 갈래 틀(BM C3) — 복제 노드를 감싼 점선 상자. 바꾼 설정만 칩으로.
    const branchFrames: Node<BranchFrameData>[] = s.branches.flatMap((b) => {
      const ms = s.nodes.filter((n) => n.id in b.map);
      if (!ms.length) return [];
      const x0 = Math.min(...ms.map((n) => n.position.x)) - GROUP_PAD;
      const y0 = Math.min(...ms.map((n) => n.position.y)) - GROUP_PAD - 56;
      const x1 = Math.max(...ms.map((n) => n.position.x + cardWidth(n.data.kind))) + GROUP_PAD;
      const y1 = Math.max(...ms.map((n) => n.position.y + cardHeight(n.data.kind, s.catalog))) + GROUP_PAD;
      const root = s.nodes.find((n) => n.id === b.of_root);
      return [{ id: `branch:${b.id}`, type: PG_BRANCH_TYPE, position: { x: x0, y: y0 }, zIndex: -1, selectable: false, draggable: false,
                className: keep && !ms.some((m) => keep.has(m.id)) ? "pg-dim" : undefined,
                data: { branchId: b.id, label: b.label, width: x1 - x0, height: y1 - y0, diffs: branchDiffs(b, s.nodes, s.catalog ?? []),
                        rootName: s.catalog?.find((c) => c.type === root?.data.kind)?.plain_label ?? b.of_root } }];
    });
    return [...frames, ...branchFrames, ...cards];
  }, [s.nodes, s.groups, s.edges, order, s.selectedId, s.picked, path, collapsedOf, keep, cause, causeSet, portColor, s.branches, s.catalog, shareOf, onNeed, onFix, onSocket,
      runToRef, previewRef, runStrategyRef, branchStrategyRef]);
  /** 전달 점검 칩을 누르면(CF3b2) — 선을 누른 것과 같은 길(선 판) + 문제 줄로 내린다. */
  const onFlag = useCallback((edgeId: string) => {
    usePortfolioGraph.getState().selectEdge(edgeId);
    updatePanels((p) => (p.right ? p : toggle(p, "right")));
    requestAnimationFrame(() => document.querySelector('.pg-wire-row[data-row="issues"]')?.scrollIntoView({ block: "nearest" }));
  }, [updatePanels]);
  /** 한 노드만 골랐을 때 그 노드와 닿지 않은 선은 옅게(Houdini) — 흐리기 모드(원인·들어가기·필터)가 없을 때만. */
  const faintOthers = !keep && s.picked.length <= 1 ? s.selectedId : null;
  const edgesStyled = useMemo(() => {
    // 선 요약은 ★원천 포트의 요약★이다 — 한 포트에서 여러 선이 나가면 같은 글이 겹쳐 쌓였다. 포트마다 한 번만(BS2).
    const briefed = new Set<string>();
    return s.edges.map((e) => {
    const kind = s.nodes.find((n) => n.id === e.source)?.data.kind;
    const out = s.catalog?.find((c) => c.type === kind)?.outputs.find((p) => p.name === e.sourceHandle);
    const tkind = s.nodes.find((n) => n.id === e.target)?.data.kind;
    const inp = s.catalog?.find((c) => c.type === tkind)?.inputs.find((p) => p.name === e.targetHandle);
    const lit = path.has(e.source) && path.has(e.target);
    const src = live?.[e.source];
    const portKey = `${e.source}|${e.sourceHandle}`;
    const firstFromPort = !briefed.has(portKey);
    briefed.add(portKey);
    const wire = wireOf(src, e.sourceHandle && firstFromPort ? src?.briefs?.[e.sourceHandle] : null);
    const onCause = !!cause && causeSet.has(e.source) && causeSet.has(e.target);
    const kept = !keep || (keep.has(e.source) && keep.has(e.target));
    // 접힌 상자 — 안쪽끼리는 숨기고, 경계를 넘는 선은 상자의 대리 포트로(실제 링크는 그대로).
    const gs = collapsedOf.get(e.source);
    const gt = collapsedOf.get(e.target);
    const remap = gs && gs === gt ? { hidden: true }
      : { ...(gs ? { source: `frame:${gs}`, sourceHandle: `out|${e.source}|${e.sourceHandle}` } : {}),
          ...(gt ? { target: `frame:${gt}`, targetHandle: `in|${e.target}|${e.targetHandle}` } : {}) };
    const faint = faintOthers && e.source !== faintOthers && e.target !== faintOthers;
    const look = wireLook({ required: inp?.required, lit, onCause, targetHasResult: !!s.report?.nodes[e.target],
                            targetStale: staleSet.has(e.target), running: s.running, runningIds: s.runningIds });
    const cls = ["pg-wire", look.required ? "pg-wire--req" : "pg-wire--opt", look.stale && "pg-wire--stale",
                 look.flow && "pg-wire--flow", wire.evidence && `pg-wire--${wire.evidence}`, wire.forward && "pg-wire--forward",
                 lit && "pg-edge--path", onCause && "pg-edge--cause", !kept && "pg-dim", faint && "pg-edge--faint",
                 (gs || gt) && "pg-wire--proxy"].filter(Boolean).join(" ");
    const typeLabel = out ? (s.catalogMeta?.portPlain ?? PORT_PLAIN)[out.type] ?? out.type : null;
    return { ...e, ...remap, type: PG_WIRE_TYPE, data: { ...wire, typeLabel, hover: hoverEdge === e.id, flow: look.flow,
                                                         flag: wireFlag(s.report?.edges?.[e.id], staleSet.has(e.target)), onFlag,
                                                         waypoints: gs || gt ? [] : viaOf(e) },
             selected: e.id === s.selectedEdge,
             className: cls + (e.id === s.selectedEdge ? " pg-wire--picked" : "") + (e.id === dropWire ? " pg-wire--drop" : ""),
             style: { stroke: wire.evidence === "blocked" ? "var(--pg-wire-off)" : portTypeColor(out?.type),
                      strokeWidth: look.width } };
    });
  }, [s.edges, s.nodes, s.catalog, path, s.running, s.runningIds, s.report, staleSet, onFlag, live, cause, causeSet, keep, collapsedOf, faintOthers, hoverEdge, s.selectedEdge, s.catalogMeta, dropWire]);
  return { cause, live, stageOfNode, mmMark, bandOf, numbered, onFlag, edgesStyled };
}
