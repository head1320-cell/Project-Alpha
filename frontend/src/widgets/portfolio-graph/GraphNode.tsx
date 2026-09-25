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
import { Handle, Position, type NodeProps } from "reactflow";
import { nodeSummary, type CatalogPort, type NodeExplain, type NodeLineage, type PgNodeData } from "@/entities/portfolio-graph";
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
};
/** 포트 타입의 쉬운 이름 — 설정 탭의 받는 것/내는 것·포트 이름표. 모르는 타입은 이름 그대로. */
export const PORT_PLAIN: Record<string, string> = {
  Universe: "종목", Returns: "수익률", Belief: "기대 수익", Views: "내 생각",
  Weights: "비중", RiskReport: "위험 나눔", BacktestResult: "과거 성과",
  Scenario: "시나리오", StressReport: "충격 결과", Scores: "점수", RegimeState: "경기 국면",
  TimingSignal: "타이밍 신호", Trades: "주문 목록", TargetVersion: "실행 목표", StrategyResult: "전략 묶음 성과",
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

export type CanvasNodeData = PgNodeData & { num?: number };

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

function Port({ port, side, index, unknown }: { port: CatalogPort; side: "in" | "out"; index: number; unknown?: boolean }) {
  const color = unknown ? "var(--pg-fail)" : portColor(port.type);
  return (
    <div className={`pg-port pg-port--${side}${unknown ? " pg-port--unknown" : ""}`} style={{ top: PORT_TOP + index * PORT_GAP }}
         title={unknown ? `${port.name} — 카탈로그에 없는 포트예요(파일의 링크를 버리지 않고 남겼어요)`
                        : `${port.name} · ${port.type}${port.required === false ? " (선택)" : ""}`}>
      <Handle type={side === "in" ? "target" : "source"} position={side === "in" ? Position.Left : Position.Right}
              id={port.name} className="pg-handle"
              style={{ background: unknown ? "transparent" : color, borderColor: unknown ? color : "var(--pg-paper)",
                       borderStyle: unknown ? "dashed" : "solid" }} />
      <span className="pg-port-name">{unknown ? `${port.name}(미상)` : PORT_PLAIN[port.type] ?? port.name}</span>
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
  const errors = (validation?.errors ?? []).filter((e) => e.node_id === id);

  const unknown = !!data.unknownReason || !entry;
  const inputs: { p: CatalogPort; unknown?: boolean }[] = [
    ...(entry?.inputs ?? []).map((p) => ({ p })),
    ...(data.extraInputs ?? []).map((name) => ({ p: { name, type: "?" }, unknown: true })),
  ];
  const outputs: { p: CatalogPort; unknown?: boolean }[] = [
    ...(entry?.outputs ?? []).map((p) => ({ p })),
    ...(data.extraOutputs ?? []).map((name) => ({ p: { name, type: "?" }, unknown: true })),
  ];
  const minH = PORT_TOP + Math.max(inputs.length, outputs.length) * PORT_GAP;
  const ex = live?.explain;
  const headline = live?.status === "ok" ? ex?.headline : null;
  const summary = nodeSummary(entry, data.params ?? {});
  const state = live?.status ?? (stale && result ? "stale" : errors.length ? "warn" : "idle");

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
    <div className={`pg-node pg-node--${state}${selected ? " pg-node--selected" : ""}`} data-node-id={id} data-kind={data.kind}
         style={{ minHeight: minH }}>
      <div className="pg-node-k">
        <i className="pg-node-num" style={{ background: STAGE_VAR[entry.stage] ?? "var(--pg-st-data)" }}>{data.num ?? "·"}</i>
        <span className="pg-node-plain">{entry.plain_label}</span>
        <span className={`pg-node-dot pg-node-dot--${state}`} aria-hidden="true" />
      </div>
      <div className="pg-node-t">{summary ?? entry.plain_label}</div>
      {headline && headline.value !== null && (
        <div className="pg-node-v" title={headline.label}>
          {Number(headline.value).toFixed(1)}<small>{headline.unit} {headline.label.replace(/ 비중$/, "")}</small>
        </div>
      )}
      {live && live.status !== "ok" && ex && (
        <div className="pg-node-why">{ex.facts?.[0] ?? ex.title}</div>
      )}
      {stale && result && <div className="pg-node-why pg-node-stale">설정이 바뀌어서 예전 결과예요.</div>}
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
      {inputs.map((x, i) => <Port key={`i-${x.p.name}`} port={x.p} side="in" index={i} unknown={x.unknown} />)}
      {outputs.map((x, i) => <Port key={`o-${x.p.name}`} port={x.p} side="out" index={i} unknown={x.unknown} />)}
    </div>
  );
}

export const GraphNode = memo(GraphNodeImpl);
