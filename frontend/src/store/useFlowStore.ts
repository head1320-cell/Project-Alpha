"use client";

import { create } from "zustand";
import {
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  type Connection,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  MarkerType,
} from "reactflow";

// ── Node data types ─────────────────────────────────────────────────────────

export interface DataSourceData {
  type: "datasource";
  symbol: string;
  universe: "KOSPI" | "KOSDAQ" | "CUSTOM";
  timeframe: "1D" | "1H" | "15M";
  lookback: number; // days
}

export interface IndicatorData {
  type: "indicator";
  indicatorId: string; // "rsi" | "macd" | "sma" | "ema" | "bb" | ...
  label: string;
  params: Record<string, number>;
  output: string; // "value" | "signal" | "histogram" | "upper" | "lower"
}

export interface ConditionData {
  type: "condition";
  operator: ">" | "<" | ">=" | "<=" | "==" | "crosses_above" | "crosses_below";
  compareValue?: number;
  logic: "AND" | "OR";
}

export interface ActionData {
  type: "action";
  action: "BUY" | "SELL" | "HOLD";
  sizeType: "percent" | "fixed" | "all";
  sizeValue: number;
  stopLoss?: number;
  takeProfit?: number;
}

export type FlowNodeData = DataSourceData | IndicatorData | ConditionData | ActionData;

// ── Default node factories ──────────────────────────────────────────────────

let _nodeId = 0;
function nextId() { return `node_${Date.now()}_${++_nodeId}`; }

export function createDataSourceNode(position: { x: number; y: number }): Node<DataSourceData> {
  return {
    id: nextId(),
    type: "dataSource",
    position,
    data: {
      type: "datasource",
      symbol: "005930",
      universe: "KOSPI",
      timeframe: "1D",
      lookback: 200,
    },
  };
}

export function createIndicatorNode(position: { x: number; y: number }, indicatorId = "rsi"): Node<IndicatorData> {
  const DEFAULTS: Record<string, { label: string; params: Record<string, number>; output: string }> = {
    rsi:   { label: "RSI",            params: { period: 14 },                       output: "value" },
    macd:  { label: "MACD",           params: { fast: 12, slow: 26, signal: 9 },    output: "value" },
    sma:   { label: "SMA",            params: { period: 20 },                       output: "value" },
    ema:   { label: "EMA",            params: { period: 20 },                       output: "value" },
    bb:    { label: "Bollinger Bands", params: { period: 20, std: 2 },              output: "upper" },
    atr:   { label: "ATR",            params: { period: 14 },                       output: "value" },
    stoch: { label: "Stochastic",     params: { k: 14, d: 3 },                     output: "value" },
    adx:   { label: "ADX",            params: { period: 14 },                       output: "value" },
    cci:   { label: "CCI",            params: { period: 20 },                       output: "value" },
    obv:   { label: "OBV",            params: {},                                   output: "value" },
    vwap:  { label: "VWAP",           params: {},                                   output: "value" },
    mfi:   { label: "MFI",            params: { period: 14 },                       output: "value" },
  };
  const d = DEFAULTS[indicatorId] ?? { label: indicatorId.toUpperCase(), params: { period: 14 }, output: "value" };
  return {
    id: nextId(),
    type: "indicator",
    position,
    data: {
      type: "indicator",
      indicatorId,
      label: d.label,
      params: { ...d.params },
      output: d.output,
    },
  };
}

export function createConditionNode(position: { x: number; y: number }): Node<ConditionData> {
  return {
    id: nextId(),
    type: "condition",
    position,
    data: {
      type: "condition",
      operator: ">",
      compareValue: 70,
      logic: "AND",
    },
  };
}

export function createActionNode(position: { x: number; y: number }): Node<ActionData> {
  return {
    id: nextId(),
    type: "action",
    position,
    data: {
      type: "action",
      action: "BUY",
      sizeType: "percent",
      sizeValue: 100,
      stopLoss: undefined,
      takeProfit: undefined,
    },
  };
}

// ── Store ────────────────────────────────────────────────────────────────────

interface FlowStore {
  // State
  nodes: Node[];
  edges: Edge[];

  // React Flow handlers
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;

  // CRUD
  addNode: (node: Node) => void;
  removeNode: (id: string) => void;
  updateNodeData: (id: string, data: Partial<FlowNodeData>) => void;

  // Bulk
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  clearAll: () => void;

  // Serialize
  toJSON: () => { nodes: Node[]; edges: Edge[] };
  fromJSON: (json: { nodes: Node[]; edges: Edge[] }) => void;
}

export const useFlowStore = create<FlowStore>((set, get) => ({
  nodes: [],
  edges: [],

  onNodesChange: (changes) =>
    set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) })),

  onEdgesChange: (changes) =>
    set((s) => ({ edges: applyEdgeChanges(changes, s.edges) })),

  onConnect: (connection: Connection) =>
    set((s) => ({
      edges: addEdge(
        {
          ...connection,
          animated: true,
          style: { stroke: "#1200ff", strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#1200ff" },
        },
        s.edges,
      ),
    })),

  addNode: (node) =>
    set((s) => ({ nodes: [...s.nodes, node] })),

  removeNode: (id) =>
    set((s) => ({
      nodes: s.nodes.filter((n) => n.id !== id),
      edges: s.edges.filter((e) => e.source !== id && e.target !== id),
    })),

  updateNodeData: (id, data) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, ...data } } : n,
      ),
    })),

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),
  clearAll: () => set({ nodes: [], edges: [] }),

  toJSON: () => {
    const { nodes, edges } = get();
    return { nodes, edges };
  },

  fromJSON: (json) =>
    set({ nodes: json.nodes ?? [], edges: json.edges ?? [] }),
}));
