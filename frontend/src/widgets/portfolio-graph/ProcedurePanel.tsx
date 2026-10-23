"use client";
/**
 * 절차 탭 (BT2) — ★그래프가 스스로 절차를 말한다★
 * ==========================================================================
 * 서버 `procedure`(BT1)의 여섯 단계를 순서대로 그린다. 판정·문장은 서버가 쓰고, 여기서는 그리기만 한다.
 *
 * - 줄마다: 상태 표식 · 단계 이름 · 필수/권장/선택 · 한 줄 상태(서버) · 이 단계가 재는 관문.
 * - 비어 있거나 막힌 필수·권장 단계에는 `[‘…’ 붙이기]` — 서버가 준 한 걸음을 **선까지 이어서** 한 번에 한다.
 * - ★양방향★ 줄에 올리면(초점 포함) 그 단계 노드만 또렷하고 나머지는 흐려진다. 누르면 그 노드들로 옮겨 간다.
 *   캔버스에서 노드를 고르면 그 노드의 단계 줄에 표시가 켜진다.
 * - 번호는 실제로 순서가 있는 내용이라 쓴다(데이터 → … → 실행).
 */
import { AlertCircle, Check } from "lucide-react";
import type { Procedure, ProcedureStep, ProcedureSuggestion, GateState } from "@/entities/portfolio-graph";

const NEED_KO = { required: "필수", recommended: "권장", optional: "선택" } as const;

/** 이 단계를 채울 한 걸음 — 다음 한 걸음이 이 단계를 겨누면 그것, 아니면 이 단계가 재는 관문의 한 걸음. */
export function stepSuggestion(proc: Procedure, step: ProcedureStep, stageOf: (kind: string) => string | undefined): ProcedureSuggestion | null {
  if (step.state === "filled" || step.need === "optional") return null;
  const n = proc.next;
  if (n) {
    const touches = n.kind ? stageOf(n.kind) === step.key
      : n.attach.some((a) => step.node_ids.includes(a.target));
    if (touches) return n;
  }
  for (const g of step.feeds_gates) {
    const s = proc.by_gate[g];
    if (s && (!s.kind || stageOf(s.kind) === step.key)) return s;
  }
  return null;
}

export function ProcedurePanel({ procedure, error, gateLabel, gateState, hereStep, stageOf, onHover, onFocusNodes, onApply, onRetry }: {
  procedure: Procedure | null;
  /** 검증 요청이 서버에 닿지 못했을 때 — 절차를 지어내지 않고 그렇다고 말한다. */
  error: boolean;
  gateLabel: (key: string) => string;
  /** 계산한 뒤의 관문 상태(없으면 계산 전). */
  gateState: (key: string) => GateState | null;
  /** 고른 노드가 속한 단계 키. */
  hereStep: string | null;
  stageOf: (kind: string) => string | undefined;
  onHover: (ids: string[] | null) => void;
  onFocusNodes: (ids: string[]) => void;
  onApply: (s: ProcedureSuggestion) => void;
  onRetry: () => void;
}) {
  if (!procedure) {
    return (
      <div className="pg-proc-empty" role="status">
        {error ? (
          <>
            <p>절차를 불러오지 못했어요 — 서버에 닿지 않았어요.</p>
            <button type="button" className="pg-proc-retry" onClick={onRetry}>다시 시도</button>
          </>
        ) : <p>절차를 읽는 중이에요.</p>}
      </div>
    );
  }
  return (
    <div className="pg-proc-wrap">
      <ol className="pg-proc" aria-label="설계 절차">
        {procedure.steps.map((st, i) => {
          const sug = stepSuggestion(procedure, st, stageOf);
          const here = hereStep === st.key;
          const has = st.node_ids.length > 0;
          return (
            <li key={st.key} className={`pg-proc-step pg-proc-step--${st.state}${here ? " pg-proc-step--here" : ""}`}
                data-step={st.key} data-state={st.state} data-need={st.need}
                onMouseEnter={() => has && onHover(st.node_ids)} onMouseLeave={() => onHover(null)}>
              <span className="pg-proc-mark" aria-hidden="true">
                {st.state === "filled" ? <Check size={13} strokeWidth={3} /> : st.state === "blocked" ? <AlertCircle size={14} /> : i + 1}
              </span>
              <div className="pg-proc-body">
                <div className="pg-proc-head">
                  {has ? (
                    <button type="button" className="pg-proc-name" onClick={() => onFocusNodes(st.node_ids)}
                            onFocus={() => onHover(st.node_ids)} onBlur={() => onHover(null)}
                            aria-label={`${st.label} — 노드 ${st.node_ids.length}개로 옮겨 가기`}>{st.label}</button>
                  ) : <span className="pg-proc-name">{st.label}</span>}
                  <span className={`pg-proc-need pg-proc-need--${st.need}`}>{NEED_KO[st.need]}</span>
                </div>
                <p className="pg-proc-text">{st.text}</p>
                {st.feeds_gates.length > 0 && (
                  <ul className="pg-proc-gates" aria-label="이 단계가 재는 관문">
                    {st.feeds_gates.map((g) => {
                      const gs = gateState(g);
                      return <li key={g} className="pg-proc-gate" data-gate={g} data-state={gs ?? "idle"}>
                        <i aria-hidden="true" />{gateLabel(g)}</li>;
                    })}
                  </ul>
                )}
                {sug && (
                  <button type="button" className="pg-proc-fix" onClick={() => onApply(sug)} title={sug.text}>
                    {sug.action === "connect" ? "선 잇기" : `‘${sug.label}’ 붙이기`}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {procedure.done_text && <p className="pg-proc-done" role="status">{procedure.done_text}</p>}
    </div>
  );
}
