"use client";
/**
 * 범용 그래프 노드 — ★카탈로그 하나로 모든 노드를 그린다★ (BI3)
 * ==========================================================================
 * 노드 종류를 화면에 하드코딩하지 않는다. 포트·라벨은 `GET …/graph/node-types` 에서 오고,
 * 새 노드가 서버에 등록되면 이 파일을 고치지 않아도 캔버스에 뜬다.
 *
 * 한 노드가 보여 주는 것: 포트(색 = 포트 타입) · 상태(ok·blocked·failed + 사유) ·
 * 검증 오류 · 데이터 등급. ★낡은 결과는 상태로 그리지 않는다★ — 그래프가 바뀐 뒤의 초록불은
 * 거짓이다.
 */
import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { CatalogPort, PgNodeData } from "@/entities/portfolio-graph";
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
};
const portColor = (t: string) => PORT_COLORS[t] ?? "#94a3b8";

const STATUS_TEXT = { ok: "완료", blocked: "막힘", failed: "실패" } as const;

function PortRow({ port, side, unknown }: { port: CatalogPort; side: "in" | "out"; unknown?: boolean }) {
  const color = unknown ? "var(--destructive)" : portColor(port.type);
  return (
    <div className={`pg-port pg-port--${side}${unknown ? " pg-port--unknown" : ""}`}
         title={unknown ? "카탈로그에 없는 포트 — 파일에 있던 링크를 버리지 않고 남겼습니다" : `${port.type}${port.required === false ? " (선택)" : ""}`}>
      <Handle
        type={side === "in" ? "target" : "source"}
        position={side === "in" ? Position.Left : Position.Right}
        id={port.name}
        className="pg-handle"
        style={{ background: unknown ? "transparent" : color, borderColor: color,
                 borderStyle: unknown ? "dashed" : "solid" }}
      />
      <span className="pg-port-name">{port.name}{port.required === false ? "?" : ""}</span>
      <span className="pg-port-type" style={{ color }}>{unknown ? "미상" : port.type}</span>
    </div>
  );
}

function GraphNodeImpl({ id, data, selected }: NodeProps<PgNodeData>) {
  const entry = usePortfolioGraph((s) => s.catalog?.find((c) => c.type === data.kind));
  const result = usePortfolioGraph((s) => (s.reportStale ? undefined : s.report?.nodes[id]));
  const stale = usePortfolioGraph((s) => s.reportStale && !!s.report?.nodes[id]);
  const validation = usePortfolioGraph((s) => s.validation);
  const errors = (validation?.errors ?? []).filter((e) => e.node_id === id);

  const unknown = !!data.unknownReason || !entry;
  const extraIn = (data.extraInputs ?? []).map((name) => ({ name, type: "?" }));
  const extraOut = (data.extraOutputs ?? []).map((name) => ({ name, type: "?" }));
  const grade = result?.provenance?.data_grade as string | null | undefined;
  const gradeKnown = result && "data_grade" in (result.provenance ?? {});

  return (
    <div className={`pg-node${selected ? " pg-node--selected" : ""}${unknown ? " pg-node--unknown" : ""}`}
         data-node-id={id} data-kind={data.kind}>
      <div className="pg-node-head">
        <span className="pg-node-title">{entry?.label ?? data.kind}</span>
        <span className="pg-node-kind">{data.kind}</span>
      </div>
      {unknown && (
        <div className="pg-node-unknown-why">{data.unknownReason ?? `모르는 노드 타입 "${data.kind}"`}</div>
      )}
      <div className="pg-node-ports">
        <div className="pg-node-col">
          {(entry?.inputs ?? []).map((p) => <PortRow key={p.name} port={p} side="in" />)}
          {extraIn.map((p) => <PortRow key={`x-${p.name}`} port={p} side="in" unknown />)}
        </div>
        <div className="pg-node-col pg-node-col--out">
          {(entry?.outputs ?? []).map((p) => <PortRow key={p.name} port={p} side="out" />)}
          {extraOut.map((p) => <PortRow key={`x-${p.name}`} port={p} side="out" unknown />)}
        </div>
      </div>
      {result && (
        <div className={`pg-node-status pg-node-status--${result.status}`} title={result.reason ?? undefined}>
          <span className="pg-node-status-k">{STATUS_TEXT[result.status]}</span>
          {result.reason && <span className="pg-node-status-why">{result.reason}</span>}
        </div>
      )}
      {stale && <div className="pg-node-stale">그래프가 바뀌었습니다 — 다시 실행하세요</div>}
      {gradeKnown && (
        <div className="pg-node-grade" title={(result?.provenance?.data_grade_reason as string) ?? undefined}>
          {grade === "E0" ? "E0 · 합성 데이터" : grade ? `${grade}` : "데이터 등급 미상"}
        </div>
      )}
      {errors.length > 0 && (
        <ul className="pg-node-errors">
          {errors.map((e, i) => <li key={i}><b>{e.code}</b> {e.message}</li>)}
        </ul>
      )}
    </div>
  );
}

export const GraphNode = memo(GraphNodeImpl);
