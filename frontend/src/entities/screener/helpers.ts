// 필터 AST 순수 헬퍼 — 빈 그룹 생성 · 조건 라벨링 (네트워크 호출 없음).
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import type { MacroGuidance } from "./model";
import type { FilterConditionNode, FilterGroupNode } from "@/shared/model";
export function emptyFilterGroup(): FilterGroupNode {
  return { logic: "AND", conditions: [], groups: [] };
}

// Helper: 조건 라벨 생성 (UI 표시용)
export function conditionLabel(cond: FilterConditionNode, fieldLabel: string): string {
  if (cond.rank_mode === "top_pct") return `${fieldLabel} 상위 ${cond.rank_value}%`;
  if (cond.rank_mode === "bottom_pct") return `${fieldLabel} 하위 ${cond.rank_value}%`;
  if (cond.rank_mode === "top_n") return `${fieldLabel} 상위 ${cond.rank_value}종목`;
  const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "=", between: "~" };
  if (cond.op === "between") return `${fieldLabel} ${cond.value}~${cond.value2}`;
  return `${fieldLabel} ${opMap[cond.op || "lt"]} ${cond.value}`;
}

export function guidanceFilterToNode(f: MacroGuidance["recommended_filters"][0]): FilterConditionNode {
  if (f.rank_mode) {
    return {
      field: f.field,
      rank_mode: f.rank_mode as FilterConditionNode["rank_mode"],
      rank_value: f.rank_value ?? null,
    };
  }
  return {
    field: f.field,
    op: (f.op ?? "lt") as FilterConditionNode["op"],
    value: f.value ?? null,
  };
}

export function conditionLabelV2(cond: FilterConditionNode, fieldLabel: (id: string) => string): string {
  if (cond.kind === "sentiment") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    const srcMap: Record<string, string> = { news_score: "뉴스", call_tone: "콜 톤" };
    return `💬 ${srcMap[cond.sentiment_source || ""] || cond.sentiment_source} ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "vector_sim") {
    return `👯 ${cond.vector_ticker} 유사도 ≥ ${cond.vector_threshold}`;
  }
  if (cond.kind === "behavioral") {
    return `🧠 ${fieldLabel(cond.behavior_signal || "")}`;
  }
  if (cond.kind === "graph") {
    const relMap: Record<string, string> = { supplier: "공급사", customer: "고객사", competitor: "경쟁사" };
    return `🕸 ${cond.graph_target} ${relMap[cond.graph_relation || ""]} ${cond.graph_depth}-hop`;
  }
  if (cond.kind === "estimate") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    return `🔮 ${fieldLabel(cond.estimate_field || "")} ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "z_score") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    const win = cond.z_window ? `${Math.round(cond.z_window / 4)}년` : "";
    return `📉 ${fieldLabel(cond.z_field || "")} ${win} Z ${opMap[cond.op || "lt"]} ${cond.value}σ`;
  }
  if (cond.kind === "technical") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    return `📊 ${fieldLabel(cond.indicator || "")} ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "event") {
    return `📅 ${fieldLabel(cond.event_type || "")} ${cond.within_days}일 이내`;
  }
  if (cond.kind === "formula") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "=", between: "~" };
    return `∑ (${cond.formula}) ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "peer") {
    const scopeLabel = cond.peer_scope === "market" ? "전체" : "섹터";
    if (cond.peer_stat === "rank_pct") return `⚖ ${fieldLabel(cond.field)} ${scopeLabel} 상위 ${cond.rank_value}%`;
    const statLabel = cond.peer_stat === "median" ? "중앙값" : "평균";
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    return `⚖ ${fieldLabel(cond.field)} ${opMap[cond.op || "lt"]} ${scopeLabel} ${statLabel}`;
  }
  return conditionLabel(cond, fieldLabel(cond.field));
}
