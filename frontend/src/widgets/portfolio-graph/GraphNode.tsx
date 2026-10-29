"use client";
/**
 * 노드 카드 — ★카탈로그 하나로 모든 노드를 그린다★ (BI3 → BJ2 토스식 재단장)
 * ==========================================================================
 * 한 카드가 보여 주는 것(목업 승인본):
 *   단계 색 번호 · 쉬운 이름 · 상태 점 → 짧은 요약(서버 x-ui) → 실행 뒤 **큰 숫자 하나**(서버
 *   headline) → 증거 칩(연습용 · 가정 · 실패). 막힘·실패는 서버의 쉬운 말 사유를 그대로.
 * ★낡은 결과는 흐리게 + "예전 결과예요"★ — 그래프가 바뀐 뒤의 초록불은 거짓이다.
 * CF1 — 작업 노드(자리 고정): 모든 확대에서 같은 상자(`size.ts cardHeight`), 확대에 따라 안의 내용만 바뀐다.
 *   가까이 = 머리 · 소켓 줄(이름 늘 보임) · 설정 위젯 · 결과 자리 · 상태 줄 / 중간 = 머리 · 소켓 이름 · 요약 · 큰 숫자 / 멀리 = 이름·값.
 * CF2 — 소켓: 필수 = 타입색 채운 원 · 선택 = 빈 원 · 합치기의 전략 입력 = 네모 · 두 번 누르면 그 타입 빠른 추가.
 */
import { memo } from "react";
import { Handle, NodeToolbar, Position, useStore, type Node, type NodeProps } from "@xyflow/react";
import { ChevronDown, ChevronRight, GitBranch, Pin, PinOff, Play, Route } from "lucide-react";
import { cardFieldsOf, cardHeight, connectionProblem, FOLD_PORT_TOP, fmtDelta, fmtElapsed, headlineDelta, isSolo, needsGap, nodeSummary, PORT_GAP, PORT_TOP, type CatalogPort, type NodeExplain, type NodeLineage, type PgNodeData, type ProcedureSuggestion } from "@/entities/portfolio-graph";
import { NodeWidgets } from "./NodeWidgets";
import { Glance } from "./Glance";
import { StrategyDonut, type DonutSlice } from "./StrategyDonut";
import { usePortfolioGraph } from "./store";
import { parsePlace, placeToolbar } from "./toolbarPlace";

import { portColor } from "@/entities/portfolio-graph/ports";
/** 포트 타입의 쉬운 이름 — 설정 탭의 받는 것/내는 것·포트 이름표. 모르는 타입은 이름 그대로. */
export const PORT_PLAIN: Record<string, string> = {
  Universe: "종목", Returns: "수익률", Belief: "기대 수익", Views: "내 생각",
  Weights: "비중", RiskReport: "위험 나눔", BacktestResult: "과거 성과",
  Scenario: "시나리오", StressReport: "충격 결과", Scores: "점수", RegimeState: "경기 국면",
  TimingSignal: "타이밍 신호", Trades: "주문 목록", TargetVersion: "실행 목표", StrategyResult: "전략 묶음 성과",
  BacktestRun: "백테스트 실행", Client: "고객", Account: "계좌",
};

/** 워크플로우 단계 → 번호 배지 색(토큰). */
export const STAGE_VAR: Record<string, string> = {
  data: "var(--pg-st-data)", signal: "var(--pg-st-signal)", belief: "var(--pg-st-belief)",
  build: "var(--pg-st-build)", check: "var(--pg-st-check)", act: "var(--pg-st-act)",
};

const STATUS_TEXT = { ok: "완료", blocked: "막힘", failed: "실패" } as const;
// 포트 줄 치수(PORT_TOP·PORT_GAP)는 배치(`size.ts`)와 한 자리 — 배치가 카드 높이를 같은 식으로 셈한다(BS2).

export type CanvasNodeData = PgNodeData & {
  num?: number;
  /** "여기까지 계산" — 캔버스가 채운다. 올리면 돌 경로가 밝아지고(미리보기), 누르면 이 노드와 조상만 계산한다(BL1). */
  onRunTo?: (id: string) => void;
  /** 빠진 입력을 이을 노드 찾기(BT3) — 그 입력에서 선을 끈 것과 같다. */
  onNeed?: (id: string, port: string, type: string) => void;
  /** 고치는 법 단추(BT7) — 서버 절차의 이 노드 제안을 그대로 적용한다. */
  onFix?: (sug: ProcedureSuggestion) => void;
  onPreviewRunTo?: (id: string | null) => void;
  /** 소켓 두 번 누르기(CF2) — 그 소켓 타입으로 빠른 추가(입력이면 보내는 노드, 출력이면 받는 노드). */
  onSocket?: (id: string, port: string, type: string, side: "in" | "out") => void;
};

function chipsOf(ex: NodeExplain | null | undefined, lin?: NodeLineage): { cls: string; text: string }[] {
  const out: { cls: string; text: string }[] = [];
  // 계보(BK0) — 서버가 하류로 나른 사실. 과거 검증에 쓸 수 없는 값임을 노드에서 바로 말한다.
  if (lin?.pit === "forward_only") out.push({ cls: "assume", text: "지금 시점 전용" });
  if (lin?.overlay) out.push({ cls: "assume", text: "노출 조절됨" });
  const trust = ex?.trust ?? [];
  if (trust.some((t) => t.kind === "practice")) out.push({ cls: "unknown", text: "연습용 데이터" });
  else if (trust.some((t) => t.state === "unknown")) out.push({ cls: "unknown", text: "모르는 것 있음" });
  // 고른 방식이 답을 내지 못해 다른 비중을 썼다(CF3) — 가정 하나로 세면 묻히므로 따로 말한다.
  if (trust.some((t) => t.kind === "fallback")) out.push({ cls: "fallback", text: "고른 방식 대신함" });
  const nAssumed = trust.filter((t) => t.state === "assumed" && t.kind !== "fallback").length;
  if (nAssumed) out.push({ cls: "assume", text: nAssumed === 1 ? "가정 있음" : `가정 ${nAssumed}개` });
  if (trust.some((t) => t.state === "failed")) out.push({ cls: "fail", text: "지키지 못한 조건" });
  return out;
}

/**
 * 끄는 동안 이 포트에 이을 수 있나(BT4) — `can`(이을 수 있음) · `needs`(타입은 맞지만 받는 쪽이 요구하는 값을 보내는 쪽이
 * 선언하지 않음 — 이으면 서버가 "계산하면 실패해요"라고 말한다) · `off`(안 됨) · null(끄는 중이 아님·같은 쪽).
 */
function useDragFit(nodeId: string | undefined, port: CatalogPort, side: "in" | "out"): "can" | "needs" | "off" | null {
  const start = useStore((st) => {
    const h = st.connection.inProgress ? st.connection.fromHandle : null;
    return h?.nodeId && h.id ? `${h.nodeId}|${h.id}|${h.type}` : null;
  });
  if (!start || !nodeId) return null;
  const [sn, sh, stype] = start.split("|");
  if ((stype === "source") === (side === "out")) return null;              // 같은 쪽 점은 표시하지 않는다
  const g = usePortfolioGraph.getState();
  // 다시 꽂는 중인 선(CF2)은 빼고 본다 — 그 선 자신 때문에 "이미 이어져 있어요"가 되지 않게.
  const edges = g.reconnecting ? g.edges.filter((e) => e.id !== g.reconnecting) : g.edges;
  const c = side === "in" ? { source: sn, sourceHandle: sh, target: nodeId, targetHandle: port.name }
                          : { source: nodeId, sourceHandle: port.name, target: sn, targetHandle: sh };
  if (connectionProblem(c, g.nodes, edges, g.catalog ?? [], g.catalogMeta?.portPlain ?? PORT_PLAIN)) return "off";
  const kind = (id: string) => g.catalog?.find((x) => x.type === g.nodes.find((n) => n.id === id)?.data.kind);
  const out = kind(c.source)?.outputs.find((o) => o.name === c.sourceHandle);
  const inp = kind(c.target)?.inputs.find((i) => i.name === c.targetHandle);
  return needsGap(out, inp).length ? "needs" : "can";
}

function Port({ port, side, index, unknown, label, missing, nodeId, folded, square, count, onSocket }: {
  port: CatalogPort; side: "in" | "out"; index: number; unknown?: boolean; label?: string; missing?: boolean; nodeId?: string;
  folded?: boolean; square?: boolean; count?: number; onSocket?: CanvasNodeData["onSocket"];
}) {
  const color = unknown ? "var(--pg-fail)" : portColor(port.type);
  const fit = useDragFit(unknown ? undefined : nodeId, port, side);
  // 소켓 모양(CF2) — 필수는 타입색으로 채운 원, 선택은 타입색 테두리의 빈 원, 여러 전략을 받는 칸(합치기)은 네모.
  const optional = side === "in" && port.required === false;
  const hollow = unknown || optional;
  return (
    <div className={`pg-port pg-port--${side}${unknown ? " pg-port--unknown" : ""}${missing ? " pg-port--missing" : ""}${fit ? ` pg-port--${fit}` : ""}${optional ? " pg-port--opt" : ""}`}
         style={{ top: folded ? FOLD_PORT_TOP : PORT_TOP + index * PORT_GAP }}
         title={unknown ? `${port.name} — 카탈로그에 없는 포트예요(파일의 링크를 버리지 않고 남겼어요)`
                        : `${label ? `${label} · ` : ""}${port.name} · ${port.type}${optional ? " (선택)" : ""}`}>
      <Handle type={side === "in" ? "target" : "source"} position={side === "in" ? Position.Left : Position.Right}
              id={port.name} className={`pg-handle${square ? " pg-handle--slot" : ""}`}
              onDoubleClick={unknown || !nodeId || !onSocket ? undefined : (e) => { e.stopPropagation(); onSocket(nodeId, port.name, port.type, side); }}
              style={{ background: hollow ? "var(--pg-paper)" : color, borderColor: hollow ? color : "var(--pg-paper)",
                       borderStyle: unknown ? "dashed" : "solid", borderRadius: square ? 3 : undefined }} />
      <span className="pg-port-name">{unknown ? `${port.name}(미상)` : label ?? PORT_PLAIN[port.type] ?? port.name}
        {optional && !unknown && <span className="pg-port-opt"> 선택</span>}
        {count !== undefined && count > 1 && <span className="pg-port-n"> {count}곳</span>}
        {fit === "needs" && <span className="pg-port-why"> · 보내는 쪽이 필요한 값을 주지 않을 수 있어요</span>}</span>
    </div>
  );
}

/** 한 노드 도구줄의 화면 크기(실측, 확대와 무관) — 자리 고르기에만 쓴다. */
const NODE_TOOLBAR_W = 190;
const NODE_TOOLBAR_H = 36;

function GraphNodeImpl({ id, data, selected }: NodeProps<Node<CanvasNodeData>>) {
  const entry = usePortfolioGraph((s) => s.catalog?.find((c) => c.type === data.kind));
  const report = usePortfolioGraph((s) => s.report);
  // 이 노드의 결과만 본다(BT5) — 다른 곳을 바꿔도 이 카드는 낡지 않는다(하류일 때만 낡는다).
  const stale = usePortfolioGraph((s) => s.staleIds.includes(id));
  const validation = usePortfolioGraph((s) => s.validation);
  const result = report?.nodes[id];
  const live = result && !stale ? result : undefined;
  // 혼자 쓰는 도구(BT6) — 입력도 출력도 없다. 포트를 지어 붙이지 않고 그렇다고 말한다.
  const solo = !!entry && isSolo(entry);
  // 고치는 법(BT7) — 서버가 쓴 문장과 제안 그대로. 빠진 입력이 없으면 서버가 내지 않는다(화면이 판단하지 않는다).
  const fix = usePortfolioGraph((s) => s.validation?.procedure?.fixes?.[id] ?? null);
  const running = usePortfolioGraph((s) => s.running);
  const single = usePortfolioGraph((s) => s.picked.length <= 1);
  // 도구줄 자리(BS2) — 위 가운데가 다른 카드를 덮으면 덜 덮는 자리로. 보일 때만 잰다.
  const place = parsePlace(useStore((st) => (selected && single
    ? placeToolbar(st, [id], NODE_TOOLBAR_W, NODE_TOOLBAR_H, 8) : `${Position.Top}|center`)));
  const pinned = usePortfolioGraph((s) => s.pinned.includes(id));
  const togglePin = usePortfolioGraph((s) => s.togglePin);
  const folded = usePortfolioGraph((s) => s.folded.includes(id));
  const toggleFold = usePortfolioGraph((s) => s.toggleFold);
  const catalog = usePortfolioGraph((s) => s.catalog);
  // 나가는 선 수(CF2) — 출력 소켓마다. 같은 내용이면 다시 그리지 않게 글자로.
  const outKey = usePortfolioGraph((s) => s.edges.filter((e) => e.source === id).map((e) => e.sourceHandle ?? "").join("|"));
  const showCause = usePortfolioGraph((s) => s.showCause);
  // 갈래(BM C3) — 이 노드가 복제본이면 원본 id. 원본 대비 Δ 는 헤드라인 이름·단위가 같을 때만.
  const origId = usePortfolioGraph((s) => s.branches.find((b) => id in b.map)?.map[id] ?? null);
  const origResult = usePortfolioGraph((s) => (origId && !s.staleIds.includes(origId) ? s.report?.nodes[origId] : undefined));
  // 종착점(BN N1) — 전략 합치기 노드는 몫 도넛. 포트 → 이은 전략의 띠 색·이름(화면 정보) · 몫은 서버 결과 그대로.
  // 셀렉터는 문자열(JSON)을 돌려 같은 내용이면 다시 그리지 않는다 — 전략 이름에 어떤 글자가 들어가도 깨지지 않게 JSON.
  const portBandKey = usePortfolioGraph((s) => {
    if (data.kind !== "portfolio_combine") return "[]";
    return JSON.stringify(s.edges.filter((e) => e.target === id).map((e) => {
      const g = s.groups.find((x) => x.kind === "strategy" && x.members.includes(e.source));
      return [e.targetHandle ?? "", g ? g.color ?? 0 : null, g?.label ?? ""];
    }));
  });
  const portBand = JSON.parse(portBandKey) as [string, number | null, string][];
  // 필수 입력이 비었는데 서버가 이미 말한 것(missing_input)은 아래 "이어 주세요" 한 줄로 쉽게 바꿔 보인다(같은 사실 — BN N3).
  const errors = (validation?.errors ?? []).filter((e) => e.node_id === id && e.code !== "missing_input");
  // 비어 있는 필수 입력 — 연결 규칙과 같은 판정(필수 · 들어오는 선 없음). 포트에 고리, 제목 아래 한 줄.
  const linkedIn = usePortfolioGraph((s) => s.edges.filter((e) => e.target === id).map((e) => e.targetHandle).join("|"));
  const runningHere = usePortfolioGraph((s) => s.running && !!s.runningIds?.includes(id));

  const unknown = !!data.unknownReason || !entry;
  const inputs: { p: CatalogPort; unknown?: boolean }[] = [
    ...(entry?.inputs ?? []).map((p) => ({ p })),
    ...(data.extraInputs ?? []).map((name) => ({ p: { name, type: "?" }, unknown: true })),
  ];
  // 전략 합치기(BN N1) — 여덟 자리를 다 늘어놓지 않는다: 이은 자리 + 꼭 필요한 자리 + 빈 자리 하나만. 이은 자리의 이름은 전략 이름.
  const combine = data.kind === "portfolio_combine";
  const linkedPorts = new Map(portBand.map(([port, , name]) => [port, name] as const));
  const portLabels = (data.params?.labels ?? {}) as Record<string, unknown>;
  let spare = false;
  const shownInputs = combine ? inputs.filter((x) => {
    if (x.unknown || linkedPorts.has(x.p.name) || x.p.required !== false) return true;
    if (!spare) { spare = true; return true; }
    return false;
  }) : inputs;
  const inLabel = (name: string): string | undefined => {
    if (!combine) return undefined;
    if (!linkedPorts.has(name)) return "전략 더 잇기";
    const l = portLabels[name];
    return typeof l === "string" && l.trim() ? l : linkedPorts.get(name) || undefined;
  };
  const outputs: { p: CatalogPort; unknown?: boolean }[] = [
    ...(entry?.outputs ?? []).map((p) => ({ p })),
    ...(data.extraOutputs ?? []).map((name) => ({ p: { name, type: "?" }, unknown: true })),
  ];
  const rows = Math.max(shownInputs.length, outputs.length);
  const minH = PORT_TOP + rows * PORT_GAP;
  const linkedSet = new Set(linkedIn ? linkedIn.split("|") : []);
  const missing = (entry?.inputs ?? []).filter((p) => p.required !== false && !linkedSet.has(p.name));
  const ex = live?.explain;
  const headline = live?.status === "ok" ? ex?.headline : null;
  const summary = nodeSummary(entry, data.params ?? {});
  const state = live?.status ?? (stale && result ? "stale" : errors.length ? "warn" : "idle");
  // 제목 줄 경고(Blender) — 서버 trust 의 '지키지 못함'·'모름' 수. 설정 오류는 따로 빨갛게 적힌다.
  const warns = live?.status === "ok" ? (ex?.trust ?? []).filter((t) => t.state === "failed" || t.state === "unknown") : [];
  const glance = live?.status === "ok" ? live.glance ?? null : null;
  const elapsed = typeof live?.elapsed_ms === "number" ? live.elapsed_ms : null;
  // 작업 노드(CF1) — 카드 위젯 칸(서버 x-ui 기본 칸 중 카드에 맞는 것)과 상자 높이(모든 확대에서 같다).
  const cw = cardFieldsOf(entry?.params_schema ?? null, data.params ?? {});
  const boxH = cardHeight(data.kind, catalog);
  const outCount = (name: string) => (outKey ? outKey.split("|").filter((h) => h === name).length : 0);

  if (unknown) {
    return (
      <div className={`pg-node pg-node--unknown${selected ? " pg-node--selected" : ""}`} data-node-id={id} data-kind={data.kind}
           style={{ minHeight: minH }}>
        <div className="pg-node-k">모르는 노드</div>
        <div className="pg-node-t">{data.kind}</div>
        <div className="pg-node-why">{data.unknownReason ?? `모르는 노드 타입 "${data.kind}"`}</div>
        {inputs.map((x, i) => <Port key={`i-${x.p.name}`} port={x.p} side="in" index={i} unknown />)}
        {outputs.map((x, i) => <Port key={`o-${x.p.name}`} port={x.p} side="out" index={i} unknown />)}
        {live && (
          <div className={`pg-node-status pg-node-status--${live.status}`}>
            <span className="pg-node-status-k">{STATUS_TEXT[live.status]}</span>
            <span className="pg-node-status-why">{live.reason}</span>
          </div>
        )}
      </div>
    );
  }

  const slotEmpty = !live && !(stale && result) && missing.length === 0 && !fix && errors.length === 0;
  return (
    <div className={`pg-node pg-node--${state}${selected ? " pg-node--selected" : ""}${live?.previous ? " pg-node--previous" : ""}${pinned ? " pg-node--pinned" : ""}${solo ? " pg-node--solo" : ""}${folded ? " pg-node--folded" : ""}`}
         data-node-id={id} data-kind={data.kind}
         style={{ minHeight: folded ? undefined : boxH, ["--pg-stage" as string]: STAGE_VAR[entry.stage] ?? "var(--pg-st-data)",
                  ["--pg-i" as string]: data.num ?? 0, ["--pg-rows" as string]: rows }}>
      <NodeToolbar isVisible={selected && single} position={place.position} align={place.align} offset={8}>
        {/* 촘촘한 격자(BS2)에서 도구줄이 옆 카드를 덮지 않게 짧게 — 주 동작만 글, 나머지는 아이콘 + 이름(aria-label·title).
            예전 386px(단축키 글·세 단추 글)은 확대 0.64 에서 카드 네 장 폭이었다. 단축키는 title·aria-keyshortcuts 로. */}
        <button type="button" className="pg-run-to" disabled={running} title="여기까지 계산 (Shift+Enter)" aria-keyshortcuts="Shift+Enter"
                onMouseEnter={() => data.onPreviewRunTo?.(id)} onMouseLeave={() => data.onPreviewRunTo?.(null)}
                onFocus={() => data.onPreviewRunTo?.(id)} onBlur={() => data.onPreviewRunTo?.(null)}
                onClick={() => { data.onPreviewRunTo?.(null); data.onRunTo?.(id); }}>
          <Play size={12} aria-hidden="true" /> 여기까지 계산
        </button>
        <button type="button" className="pg-branch-make pg-tb-icon" aria-label="갈래 만들기"
                onClick={() => { const st = usePortfolioGraph.getState(); st.act(() => st.makeBranch(id)); }}
                title="갈래 만들기 — 이 노드와 같은 전략 안의 하류를 복제해 설정만 바꿔 나란히 봐요">
          <GitBranch size={14} aria-hidden="true" />
        </button>
        <button type="button" className="pg-pin pg-tb-icon" aria-pressed={pinned} onClick={() => togglePin(id)}
                aria-label={pinned ? "그림 고정 풀기" : "그림 고정"}
                title={pinned ? "그림 고정 풀기" : "그림 고정 — 멀리서 볼 때도 이 노드의 작은 그림을 보여요"}>
          {pinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}
        </button>
      </NodeToolbar>
      <div className="pg-node-k">
        <i className="pg-node-num" style={{ background: STAGE_VAR[entry.stage] ?? "var(--pg-st-data)" }}>{data.num ?? "·"}</i>
        <span className="pg-node-plain">{entry.plain_label}</span>
        {warns.length > 0 && (
          <span className="pg-node-warn" role="img" aria-label={`확인할 것 ${warns.length}개`}
                title={warns.map((t) => t.text).join("\n")}>!{warns.length}</span>
        )}
        <span className={`pg-node-dot pg-node-dot--${runningHere ? "running" : state}`} aria-hidden="true" />
        <button type="button" className="pg-node-fold nodrag" aria-pressed={folded} aria-label={folded ? "노드 펴기" : "노드 접기"}
                title={folded ? "펴기 — 소켓·설정·결과를 다시 보여요" : "접기 — 머리 줄만 남겨요"}
                onClick={(e) => { e.stopPropagation(); toggleFold(id); }}>
          {folded ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
        </button>
      </div>
      <div className="pg-node-far" aria-hidden="true">
        <span className="pg-node-far-name">{entry.plain_label}</span>
        <span className={`pg-node-far-v pg-node-far-v--${state}`}>
          {headline && headline.value !== null
            ? <>{Number.isInteger(Number(headline.value)) ? Number(headline.value) : Number(headline.value).toFixed(1)}<small>{headline.unit}</small></>
            : live ? STATUS_TEXT[live.status] : stale && result ? "예전 결과" : "계산 전"}
        </span>
      </div>
      {/* 소켓 줄 자리 — 소켓(핸들·이름)은 아래 .pg-port 가 같은 높이에 그린다(포트 DOM 은 그대로 — E2E 계약). */}
      {rows > 0 && <div className="pg-node-sockets" aria-hidden="true" />}
      <div className={`pg-node-t${cw.fields.length ? "" : " pg-node-t--keep"}`}>{summary ?? entry.plain_label}</div>
      {solo && <div className="pg-node-solo">선 없이 혼자 계산해요</div>}
      <NodeWidgets id={id} fields={cw.fields} more={cw.more} params={data.params ?? {}} schema={entry.params_schema ?? null} />
      {headline && headline.value !== null && (
        <div className="pg-node-v" title={headline.label}>
          {Number.isInteger(Number(headline.value)) ? Number(headline.value) : Number(headline.value).toFixed(1)}<small>{headline.unit} {headline.label.replace(/ 비중$/, "")}</small>
        </div>
      )}
      {/* 결과 자리 — 작은 그림 · 막힘 사유 · 고치는 법 · 예전 결과 안내가 나눠 쓴다(넘치면 그때만 카드가 자란다). */}
      <div className="pg-node-slot">
        {missing.length > 0 && (
          <div className="pg-node-need" role="note">
            {data.onNeed ? missing.map((p, i) => (
              <span key={p.name}>{i > 0 && ", "}
                <button type="button" className="pg-node-need-btn nodrag" data-port={p.name}
                        aria-label={`‘${PORT_PLAIN[p.type] ?? p.name}’을 낼 노드 찾기`}
                        onClick={(e) => { e.stopPropagation(); data.onNeed?.(id, p.name, p.type); }}>‘{PORT_PLAIN[p.type] ?? p.name}’</button>
              </span>
            )) : missing.map((p) => `‘${PORT_PLAIN[p.type] ?? p.name}’`).join(", ")}을 이어 주세요
          </div>
        )}
        {fix && data.onFix && (
          <div className="pg-node-fix" role="note">
            <span className="pg-node-fix-text">{fix.text}</span>
            <button type="button" className="pg-node-fix-btn nodrag" data-action={fix.action}
                    onClick={(e) => { e.stopPropagation(); data.onFix?.(fix); }}>
              {fix.action === "add" && fix.label ? `‘${fix.label}’ 붙이기` : "이어 주기"}
            </button>
          </div>
        )}
        {live && live.status !== "ok" && ex && (
          <div className="pg-node-why">{ex.facts?.[0] ?? ex.title}</div>
        )}
        {live && live.status !== "ok" && (
          <button type="button" className="pg-cause-btn nodrag" onClick={(e) => { e.stopPropagation(); showCause(id); }}
                  title="계산하지 못한 앞 단계를 따라 첫 원인까지 밝혀요">
            <Route size={12} aria-hidden="true" /> 원인 따라가기
          </button>
        )}
        {origId && live && (() => {
          const d = headlineDelta(origResult, live);
          return d ? <div className="pg-node-delta" title="같은 이름·단위의 헤드라인끼리 뺀 값이에요">원본 대비 <b>{fmtDelta(d)}</b></div> : null;
        })()}
        {combine && portBand.length > 0 && (() => {
          const rowsOut = (live?.status === "ok" ? (live.view?.strategies as { port: string; label: string; share_pct: unknown }[] | undefined) : undefined) ?? [];
          const slices: DonutSlice[] = portBand.map(([port, color, name]) => {
            const row = rowsOut.find((r) => r.port === port);
            const v = row?.share_pct;
            return { port, label: row?.label ?? (name || port), share: typeof v === "number" && Number.isFinite(v) ? v : null,
                     color: color === null ? "var(--pg-mute)" : `var(--pg-band-${color})` };
          });
          return <div className="pg-node-terminal"><StrategyDonut slices={slices} /></div>;
        })()}
        {glance && data.kind !== "portfolio_combine" && <div className="pg-node-glance"><Glance glance={glance} /></div>}
        {stale && result && <div className="pg-node-why pg-node-stale">설정이 바뀌어서 예전 결과예요.</div>}
        {live?.previous && <div className="pg-node-why pg-node-stale">이번에 계산하지 않았어요 — 이전 계산 결과예요.</div>}
        {errors.length > 0 && (
          <ul className="pg-node-errors">{errors.map((e, i) => <li key={i}>{e.message}</li>)}</ul>
        )}
        {slotEmpty && <div className="pg-node-slot-empty">계산하면 결과가 여기에 보여요</div>}
      </div>
      <div className="pg-node-foot">
        {live?.status === "ok" && chipsOf(ex, live.lineage).length > 0 && (
          <div className="pg-node-ev">{chipsOf(ex, live.lineage).map((c) => <span key={c.text} className={`pg-tag pg-tag--${c.cls}`}>{c.text}</span>)}</div>
        )}
        {elapsed !== null && (
          <div className="pg-node-time" title="이 노드의 계산 시간(서버)">계산 {fmtElapsed(elapsed)}</div>
        )}
      </div>
      {live && (
        <div className={`pg-node-status pg-node-status--${live.status}`} title={live.reason ?? undefined}>
          <span className="pg-node-status-k">{STATUS_TEXT[live.status]}</span>
          {live.reason && <span className="pg-node-status-why">{live.reason}</span>}
        </div>
      )}
      {shownInputs.map((x, i) => <Port key={`i-${x.p.name}`} port={x.p} side="in" index={i} unknown={x.unknown} label={inLabel(x.p.name)}
                                        missing={!x.unknown && missing.some((m) => m.name === x.p.name)} nodeId={id}
                                        folded={folded} square={combine && !x.unknown} onSocket={data.onSocket} />)}
      {outputs.map((x, i) => <Port key={`o-${x.p.name}`} port={x.p} side="out" index={i} unknown={x.unknown} nodeId={id}
                                   folded={folded} count={outCount(x.p.name)} onSocket={data.onSocket} />)}
    </div>
  );
}

export const GraphNode = memo(GraphNodeImpl);
