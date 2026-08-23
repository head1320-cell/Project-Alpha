"use client";

import { create } from "zustand";
import type {
  BuilderState, BuilderIndicator, BuilderCondition,
  BuilderConditionGroup, RiskManagement, ConditionOperator,
  ConditionOperand,
} from "@/entities/strategy/model";
import { getIndicatorById } from "./constants";

const DEFAULT_STATE: BuilderState = {
  metadata: { id: "my_strategy", name: "나의 전략", description: "", category: "trend", tags: [], author: "user" },
  indicators: [],
  entry: { logic: "AND", conditions: [] },
  exit:  { logic: "OR",  conditions: [] },
  risk: {
    stopLoss:     { enabled: false, percent: 5 },
    takeProfit:   { enabled: false, percent: 10 },
    trailingStop: { enabled: false, percent: 3 },
  },
};

interface BuilderStore extends BuilderState {
  // Actions
  loadState:      (state: BuilderState) => void;
  resetState:     () => void;
  updateMetadata: (patch: Partial<BuilderState["metadata"]>) => void;

  // Indicators
  addIndicator:    (indicatorId: string) => void;
  removeIndicator: (id: string) => void;
  updateIndicator: (id: string, params: Record<string, number | string>) => void;

  // Conditions
  addCondition:     (section: "entry" | "exit") => void;
  removeCondition:  (section: "entry" | "exit", id: string) => void;
  updateCondition:  (section: "entry" | "exit", id: string, patch: Partial<BuilderCondition>) => void;
  setLogic:         (section: "entry" | "exit", logic: "AND" | "OR") => void;

  // Risk
  updateRisk: (patch: Partial<RiskManagement>) => void;
}

let _aliasCounter = 0;
function makeAlias(indicatorId: string, existing: BuilderIndicator[]): string {
  const base = indicatorId.replace(/[^a-z0-9_]/gi, "_");
  const taken = new Set(existing.map((i) => i.alias));
  let n = 1;
  while (taken.has(`${base}_${n}`)) n++;
  return `${base}_${n}`;
}

function makeCondition(section: "entry" | "exit", indicators: BuilderIndicator[]): BuilderCondition {
  const first = indicators.find((i) => i.indicatorId !== "close");
  return {
    id: `${section}_${Date.now()}_${++_aliasCounter}`,
    left:  first
      ? { type: "indicator", indicatorAlias: first.alias, indicatorOutput: first.output }
      : { type: "price", priceField: "close" },
    operator: "greater_than",
    right: { type: "value", value: 0 },
  };
}

export const useBuilderStore = create<BuilderStore>((set, get) => ({
  ...DEFAULT_STATE,

  loadState: (state) => set({ ...state }),
  resetState: () => set({ ...DEFAULT_STATE }),

  updateMetadata: (patch) =>
    set((s) => ({ metadata: { ...s.metadata, ...patch } })),

  addIndicator: (indicatorId) =>
    set((s) => {
      const def = getIndicatorById(indicatorId);
      if (!def) return s;
      const params: Record<string, number | string> = {};
      def.params.forEach((p) => { params[p.name] = p.default; });
      const alias = makeAlias(indicatorId, s.indicators);
      const newInd: BuilderIndicator = {
        id: `${indicatorId}_${Date.now()}`,
        indicatorId, alias,
        params, output: def.defaultOutput,
      };
      return { indicators: [...s.indicators, newInd] };
    }),

  removeIndicator: (id) =>
    set((s) => ({ indicators: s.indicators.filter((i) => i.id !== id) })),

  updateIndicator: (id, params) =>
    set((s) => ({
      indicators: s.indicators.map((i) => i.id === id ? { ...i, params } : i),
    })),

  addCondition: (section) =>
    set((s) => {
      const cond = makeCondition(section, s.indicators);
      const group: BuilderConditionGroup = {
        ...(s[section] as BuilderConditionGroup),
        conditions: [...(s[section] as BuilderConditionGroup).conditions, cond],
      };
      return { [section]: group };
    }),

  removeCondition: (section, id) =>
    set((s) => {
      const group = s[section] as BuilderConditionGroup;
      return { [section]: { ...group, conditions: group.conditions.filter((c) => c.id !== id) } };
    }),

  updateCondition: (section, id, patch) =>
    set((s) => {
      const group = s[section] as BuilderConditionGroup;
      return {
        [section]: {
          ...group,
          conditions: group.conditions.map((c) => c.id === id ? { ...c, ...patch } : c),
        },
      };
    }),

  setLogic: (section, logic) =>
    set((s) => {
      const group = s[section] as BuilderConditionGroup;
      return { [section]: { ...group, logic } };
    }),

  updateRisk: (patch) =>
    set((s) => ({ risk: { ...s.risk, ...patch } })),
}));
