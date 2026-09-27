"use client";
/**
 * 노드 카드 — ★카탈로그 하나로 모든 노드를 그린다★ (BI3 → BJ2 토스식 재단장)
 * ==========================================================================
 * 한 카드가 보여 주는 것(목업 승인본):
 *   단계 색 번호 · 쉬운 이름 · 상태 점 → 짧은 요약(서버 x-ui) → 실행 뒤 **큰 숫자 하나**(서버
 *   headline) → 증거 칩(연습용 · 가정 · 실패). 막힘·실패는 서버의 쉬운 말 사유를 그대로.
 * ★낡은 결과는 흐리게 + "예전 결과예요"★ — 그래프가 바뀐 뒤의 초록불은 거짓이다.
 * 포트는 타입 색 점, 이름·타입은 마우스를 올리면(전문가용) 보인다.
 */
import { memo } from "react";
import { Handle, NodeToolbar, Position, type NodeProps } from "reactflow";
import { GitBranch, Pin, PinOff, Play, Route } from "lucide-react";
import { fmtDelta, fmtElapsed, headlineDelta, nodeSummary, type CatalogPort, type NodeExplain, type NodeLineage, type PgNodeData } from "@/entities/portfolio-graph";
import { Glance } from "./Glance";
import { StrategyDonut, type DonutSlice } from "./StrategyDonut";
import { usePortfolioGraph } from "./store";

/** 포트 타입 → 색. 모르는 타입은 회색, 카탈로그에 없는 포트는 빨간 점선. */
export const PORT_COLORS: Record<string, string> = {
  Universe: "#6366f1",
  Returns: "#0ea5e9",
  Belief: "#a855f7",
  Views: "#f59e0b",
  Weights: "#16a34a",
  RiskReport: "#ef4444",
  BacktestResult: "#14b8a6",
  // BK — 레포 도구 노드의 값
  Scenario: "#e11d48",
  StressReport: "#9f1239",
  Scores: "#65a30d",
  RegimeState: "#ca8a04",
  TimingSignal: "#ea580c",
  Trades: "#475569",
  TargetVersion: "#0f766e",
  StrategyResult: "#c026d3",
  BacktestRun: "#b45309",
};
/** 포트 타입의 쉬운 이름 — 설정 탭의 받는 것/내는 것·포트 이름표. 모르는 타입은 이름 그대로. */
export const PORT_PLAIN: Record<string, string> = {
  Universe: "종목", Returns: "수익률", Belief: "기대 수익", Views: "내 생각",
  Weights: "비중", RiskReport: "위험 나눔", BacktestResult: "과거 성과",
  Scenario: "시나리오", StressReport: "충격 결과", Scores: "점수", RegimeState: "경기 국면",
  TimingSignal: "타이밍 신호", Trades: "주문 목록", TargetVersion: "실행 목표", StrategyResult: "전략 묶음 성과",
  BacktestRun: "백테스트 실행",
};
const portColor = (t: string) => PORT_COLORS[t] ?? "#94a3b8";

/** 워크플로우 단계 → 번호 배지 색(토큰). */
export const STAGE_VAR: Record<string, string> = {
  data: "var(--pg-st-data)", signal: "var(--pg-st-signal)", belief: "var(--pg-st-belief)",
  build: "var(--pg-st-build)", check: "var(--pg-st-check)", act: "var(--pg-st-act)",
};

const STATUS_TEXT = { ok: "완료", blocked: "막힘", failed: "실패" } as const;
const PORT_TOP = 46;
const PORT_GAP = 22;

export type CanvasNodeData = PgNodeData & {
  num?: number;
  /** "여기까지 계산" — 캔버스가 채운다. 올리면 돌 경로가 밝아지고(미리보기), 누르면 이 노드와 조상만 계산한다(BL1). */
  onRunTo?: (id: string) => void;
  onPreviewRunTo?: (id: string | null) => void;
};

function chipsOf(ex: NodeExplain | null | undefined, lin?: NodeLineage): { cls: string; text: string }[] {
  const out: { cls: string; text: string }[] = [];
  // 계보(BK0) — 서버가 하류로 나른 사실. 과거 검증에 쓸 수 없는 값임을 노드에서 바로 말한다.
  if (lin?.pit === "forward_only") out.push({ cls: "assume", text: "지금 시점 전용" });
  if (lin?.overlay) out.push({ cls: "assume", text: "노출 조절됨" });
  const trust = ex?.trust ?? [];
  if (trust.some((t) => t.state === "unknown" && t.text.includes("연습용"))) out.push({ cls: "unknown", text: "연습용 데이터" });
  else if (trust.some((t) => t.state === "unknown")) out.push({ cls: "unknown", text: "모르는 것 있음" });
  const nAssumed = trust.filter((t) => t.state === "assumed").length;
  if (nAssumed) out.push({ cls: "assume", text: nAssumed === 1 ? "가정 있음" : `가정 ${nAssumed}개` });
  if (trust.some((t) => t.state === "failed")) out.push({ cls: "fail", text: "지키지 못한 조건" });
  return out;
}

function Port({ port, side, index, unknown, label, missing }: {
  port: CatalogPort; side: "in" | "out"; index: number; unknown?: boolean; label?: string; missing?: boolean;
}) {
  const color = unknown ? "var(--pg-fail)" : portColor(port.type);
  return (
    <div className={`pg-port pg-port--${side}${unknown ? " pg-port--unknown" : ""}${missing ? " pg-port--missing" : ""}`} style={{ top: PORT_TOP + index * PORT_GAP }}
         title={unknown ? `${port.name} — 카탈로그에 없는 포트예요(파일의 링크를 버리지 않고 남겼어요)`
                        : `${label ? `${label} · ` : ""}${port.name} · ${port.type}${port.required === false ? " (선택)" : ""}`}>
      <Handle type={side === "in" ? "target" : "source"} position={side === "in" ? Position.Left : Position.Right}
              id={port.name} className="pg-handle"
              style={{ background: unknown ? "transparent" : color, borderColor: unknown ? color : "var(--pg-paper)",
                       borderStyle: unknown ? "dashed" : "solid" }} />
      <span className="pg-port-name">{unknown ? `${port.name}(미상)` : label ?? PORT_PLAIN[port.type] ?? port.name}</span>
    </div>
  );
}

function GraphNodeImpl({ id, data, selected }: NodeProps<CanvasNodeData>) {
  const entry = usePortfolioGraph((s) => s.catalog?.find((c) => c.type === data.kind));
  const report = usePortfolioGraph((s) => s.report);
  const stale = usePortfolioGraph((s) => s.reportStale);
  const validation = usePortfolioGraph((s) => s.validation);
  const result = report?.nodes[id];
  const live = result && !stale ? result : undefined;
  const running = usePortfolioGraph((s) => s.running);
  const single = usePortfolioGraph((s) => s.picked.length <= 1);
  const pinned = usePortfolioGraph((s) => s.pinned.includes(id));
  const togglePin = usePortfolioGraph((s) => s.togglePin);
  const showCause = usePortfolioGraph((s) => s.showCause);
  // 갈래(BM C3) — 이 노드가 복제본이면 원본 id. 원본 대비 Δ 는 헤드라인 이름·단위가 같을 때만.
  const origId = usePortfolioGraph((s) => s.branches.find((b) => id in b.map)?.map[id] ?? null);
  const origResult = usePortfolioGraph((s) => (origId && !s.reportStale ? s.report?.nodes[origId] : undefined));
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
  const minH = PORT_TOP + Math.max(shownInputs.length, outputs.length) * PORT_GAP;
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

  return (
    <div className={`pg-node pg-node--${state}${selected ? " pg-node--selected" : ""}${live?.previous ? " pg-node--previous" : ""}${pinned ? " pg-node--pinned" : ""}`}
         data-node-id={id} data-kind={data.kind}
         style={{ minHeight: minH, ["--pg-stage" as string]: STAGE_VAR[entry.stage] ?? "var(--pg-st-data)",
                  ["--pg-i" as string]: data.num ?? 0 }}>
      <NodeToolbar isVisible={selected && single} position={Position.Top} offset={8}>
        <button type="button" className="pg-run-to" disabled={running}
                onMouseEnter={() => data.onPreviewRunTo?.(id)} onMouseLeave={() => data.onPreviewRunTo?.(null)}
                onFocus={() => data.onPreviewRunTo?.(id)} onBlur={() => data.onPreviewRunTo?.(null)}
                onClick={() => { data.onPreviewRunTo?.(null); data.onRunTo?.(id); }}>
          <Play size={12} aria-hidden="true" /> 여기까지 계산 <kbd>Shift+Enter</kbd>
        </button>
        <button type="button" className="pg-branch-make"
                onClick={() => { const st = usePortfolioGraph.getState(); st.act(() => st.makeBranch(id)); }}
                title="이 노드와 같은 전략 안의 하류를 복제해 설정만 바꿔 나란히 봐요">
          <GitBranch size={12} aria-hidden="true" /> 갈래 만들기
        </button>
        <button type="button" className="pg-pin" aria-pressed={pinned} onClick={() => togglePin(id)}
                title="멀리서 볼 때도 이 노드의 작은 그림을 보여요">
          {pinned ? <PinOff size={12} aria-hidden="true" /> : <Pin size={12} aria-hidden="true" />}
          {pinned ? "그림 고정 풀기" : "그림 고정"}
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
      </div>
      <div className="pg-node-far" aria-hidden="true">
        <span className="pg-node-far-name">{entry.plain_label}</span>
        <span className={`pg-node-far-v pg-node-far-v--${state}`}>
          {headline && headline.value !== null
            ? <>{Number.isInteger(Number(headline.value)) ? Number(headline.value) : Number(headline.value).toFixed(1)}<small>{headline.unit}</small></>
            : live ? STATUS_TEXT[live.status] : stale && result ? "예전 결과" : "계산 전"}
        </span>
      </div>
      <div className="pg-node-t">{summary ?? entry.plain_label}</div>
      {missing.length > 0 && (
        <div className="pg-node-need" role="note">
          {missing.map((p) => `‘${PORT_PLAIN[p.type] ?? p.name}’`).join(", ")}을 이어 주세요
        </div>
      )}
      {headline && headline.value !== null && (
        <div className="pg-node-v" title={headline.label}>
          {Number.isInteger(Number(headline.value)) ? Number(headline.value) : Number(headline.value).toFixed(1)}<small>{headline.unit} {headline.label.replace(/ 비중$/, "")}</small>
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
        const rows = (live?.status === "ok" ? (live.view?.strategies as { port: string; label: string; share_pct: unknown }[] | undefined) : undefined) ?? [];
        const slices: DonutSlice[] = portBand.map(([port, color, name]) => {
          const row = rows.find((r) => r.port === port);
          const v = row?.share_pct;
          return { port, label: row?.label ?? (name || port), share: typeof v === "number" && Number.isFinite(v) ? v : null,
                   color: color === null ? "var(--pg-mute)" : `var(--pg-band-${color})` };
        });
        return <div className="pg-node-terminal"><StrategyDonut slices={slices} /></div>;
      })()}
      {glance && data.kind !== "portfolio_combine" && <div className="pg-node-glance"><Glance glance={glance} /></div>}
      {elapsed !== null && (
        <div className="pg-node-time" title="이 노드의 계산 시간(서버)">계산 {fmtElapsed(elapsed)}</div>
      )}
      {stale && result && <div className="pg-node-why pg-node-stale">설정이 바뀌어서 예전 결과예요.</div>}
      {live?.previous && <div className="pg-node-why pg-node-stale">이번에 계산하지 않았어요 — 이전 계산 결과예요.</div>}
      {live?.status === "ok" && chipsOf(ex, live.lineage).length > 0 && (
        <div className="pg-node-ev">{chipsOf(ex, live.lineage).map((c) => <span key={c.text} className={`pg-tag pg-tag--${c.cls}`}>{c.text}</span>)}</div>
      )}
      {errors.length > 0 && (
        <ul className="pg-node-errors">{errors.map((e, i) => <li key={i}>{e.message}</li>)}</ul>
      )}
      {live && (
        <div className={`pg-node-status pg-node-status--${live.status}`} title={live.reason ?? undefined}>
          <span className="pg-node-status-k">{STATUS_TEXT[live.status]}</span>
          {live.reason && <span className="pg-node-status-why">{live.reason}</span>}
        </div>
      )}
      {shownInputs.map((x, i) => <Port key={`i-${x.p.name}`} port={x.p} side="in" index={i} unknown={x.unknown} label={inLabel(x.p.name)}
                                        missing={!x.unknown && missing.some((m) => m.name === x.p.name)} />)}
      {outputs.map((x, i) => <Port key={`o-${x.p.name}`} port={x.p} side="out" index={i} unknown={x.unknown} />)}
    </div>
  );
}

export const GraphNode = memo(GraphNodeImpl);
