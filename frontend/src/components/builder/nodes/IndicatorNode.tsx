"use client";

import { memo, useCallback } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { useFlowStore, type IndicatorData } from "@/store/useFlowStore";
import { Activity, X } from "lucide-react";

const INDICATORS = [
  { id: "rsi",   label: "RSI",              params: ["period"] },
  { id: "macd",  label: "MACD",             params: ["fast", "slow", "signal"] },
  { id: "sma",   label: "SMA",              params: ["period"] },
  { id: "ema",   label: "EMA",              params: ["period"] },
  { id: "bb",    label: "Bollinger Bands",   params: ["period", "std"] },
  { id: "atr",   label: "ATR",              params: ["period"] },
  { id: "stoch", label: "Stochastic",       params: ["k", "d"] },
  { id: "adx",   label: "ADX",              params: ["period"] },
  { id: "cci",   label: "CCI",              params: ["period"] },
  { id: "obv",   label: "OBV",              params: [] },
  { id: "vwap",  label: "VWAP",             params: [] },
  { id: "mfi",   label: "MFI",              params: ["period"] },
];

const OUTPUTS: Record<string, string[]> = {
  rsi:   ["value"],
  macd:  ["value", "signal", "histogram"],
  sma:   ["value"],
  ema:   ["value"],
  bb:    ["upper", "middle", "lower"],
  atr:   ["value"],
  stoch: ["k", "d"],
  adx:   ["value"],
  cci:   ["value"],
  obv:   ["value"],
  vwap:  ["value"],
  mfi:   ["value"],
};

// Color per indicator category
const INDICATOR_COLORS: Record<string, string> = {
  rsi: "#e040fb", macd: "#e040fb", stoch: "#e040fb", cci: "#e040fb", mfi: "#e040fb",
  sma: "#00e5ff", ema: "#00e5ff", bb: "#00e5ff",
  atr: "#ff9100", adx: "#ff9100",
  obv: "#69f0ae", vwap: "#69f0ae",
};

function IndicatorNode({ id, data, selected }: NodeProps<IndicatorData>) {
  const { updateNodeData, removeNode } = useFlowStore();

  const update = useCallback(
    (patch: Partial<IndicatorData>) => updateNodeData(id, patch),
    [id, updateNodeData],
  );

  const changeIndicator = useCallback(
    (newId: string) => {
      const def = INDICATORS.find((i) => i.id === newId);
      if (!def) return;
      const newParams: Record<string, number> = {};
      def.params.forEach((p) => {
        const defaults: Record<string, number> = {
          period: 14, fast: 12, slow: 26, signal: 9, std: 2, k: 14, d: 3,
        };
        newParams[p] = defaults[p] ?? 14;
      });
      update({
        indicatorId: newId,
        label: def.label,
        params: newParams,
        output: (OUTPUTS[newId] ?? ["value"])[0],
      });
    },
    [update],
  );

  const accent = INDICATOR_COLORS[data.indicatorId] ?? "#1200ff";
  const indDef = INDICATORS.find((i) => i.id === data.indicatorId);
  const outputs = OUTPUTS[data.indicatorId] ?? ["value"];

  return (
    <div
      style={{
        background: "#0a0e27",
        border: selected ? `2px solid ${accent}` : "1px solid #1e2d4a",
        borderRadius: 10,
        width: 240,
        boxShadow: selected
          ? `0 0 20px ${accent}40`
          : "0 4px 12px rgba(0,0,0,0.4)",
        fontFamily: "'Inter', sans-serif",
        overflow: "hidden",
      }}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 10, height: 10,
          background: accent, border: "2px solid #0a0e27",
          left: -5,
        }}
      />

      {/* Header */}
      <div
        style={{
          background: `linear-gradient(135deg, ${accent}cc 0%, ${accent} 100%)`,
          padding: "8px 12px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Activity size={14} color="#fff" />
          <span style={{ color: "#fff", fontSize: 12, fontWeight: 700 }}>
            {data.label}
          </span>
        </div>
        <button
          onClick={() => removeNode(id)}
          style={{
            background: "rgba(255,255,255,0.15)", border: "none",
            borderRadius: 4, cursor: "pointer", padding: 2,
            display: "flex", alignItems: "center",
          }}
        >
          <X size={12} color="#fff" />
        </button>
      </div>

      {/* Body */}
      <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
        {/* Indicator selector */}
        <div>
          <label style={{
            fontSize: 10, fontWeight: 600, color: "#6b7fa3",
            textTransform: "uppercase", letterSpacing: "0.06em",
            display: "block", marginBottom: 3,
          }}>
            지표
          </label>
          <select
            value={data.indicatorId}
            onChange={(e) => changeIndicator(e.target.value)}
            style={{
              width: "100%", background: "#111633",
              border: "1px solid #1e2d4a", borderRadius: 4,
              padding: "5px 8px", color: "#e0e8f5",
              fontSize: 12, cursor: "pointer", outline: "none",
              appearance: "none" as const,
            }}
          >
            {INDICATORS.map((ind) => (
              <option key={ind.id} value={ind.id}>{ind.label}</option>
            ))}
          </select>
        </div>

        {/* Dynamic params */}
        {indDef && indDef.params.length > 0 && (
          <div style={{
            display: "grid",
            gridTemplateColumns: indDef.params.length > 2 ? "1fr 1fr 1fr" : `repeat(${indDef.params.length}, 1fr)`,
            gap: 6,
          }}>
            {indDef.params.map((p) => (
              <div key={p}>
                <label style={{
                  fontSize: 10, fontWeight: 600, color: "#6b7fa3",
                  textTransform: "uppercase", letterSpacing: "0.06em",
                  display: "block", marginBottom: 3,
                }}>
                  {p}
                </label>
                <input
                  type="number"
                  value={data.params[p] ?? 14}
                  onChange={(e) =>
                    update({ params: { ...data.params, [p]: Number(e.target.value) } })
                  }
                  min={1}
                  max={500}
                  style={{
                    width: "100%", background: "#111633",
                    border: "1px solid #1e2d4a", borderRadius: 4,
                    padding: "5px 6px", color: "#e0e8f5",
                    fontSize: 13, fontFamily: "'Roboto Mono', monospace",
                    outline: "none",
                  }}
                />
              </div>
            ))}
          </div>
        )}

        {/* Output selector */}
        {outputs.length > 1 && (
          <div>
            <label style={{
              fontSize: 10, fontWeight: 600, color: "#6b7fa3",
              textTransform: "uppercase", letterSpacing: "0.06em",
              display: "block", marginBottom: 3,
            }}>
              출력
            </label>
            <div style={{ display: "flex", gap: 4 }}>
              {outputs.map((o) => (
                <button
                  key={o}
                  onClick={() => update({ output: o })}
                  style={{
                    flex: 1,
                    padding: "3px 6px",
                    borderRadius: 4,
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: "pointer",
                    border: `1px solid ${data.output === o ? accent : "#1e2d4a"}`,
                    background: data.output === o ? `${accent}25` : "#111633",
                    color: data.output === o ? accent : "#6b7fa3",
                  }}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 10, height: 10,
          background: accent, border: "2px solid #0a0e27",
          right: -5,
        }}
      />
    </div>
  );
}

export default memo(IndicatorNode);
