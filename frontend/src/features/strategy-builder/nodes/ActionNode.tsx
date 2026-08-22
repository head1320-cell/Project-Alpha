"use client";

import { memo, useCallback } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { useFlowStore, type ActionData } from "@/features/strategy-builder/useFlowStore";
import { Zap, X } from "lucide-react";

const ACTIONS = ["BUY", "SELL", "HOLD"] as const;
const SIZE_TYPES = [
  { value: "percent", label: "%" },
  { value: "fixed",   label: "주" },
  { value: "all",     label: "전량" },
] as const;

const ACTION_COLORS: Record<string, { gradient: string; accent: string }> = {
  BUY:  { gradient: "linear-gradient(135deg, #00695c 0%, #00c853 100%)", accent: "#00e676" },
  SELL: { gradient: "linear-gradient(135deg, #b71c1c 0%, #ff1744 100%)", accent: "#ff5252" },
  HOLD: { gradient: "linear-gradient(135deg, #37474f 0%, #607d8b 100%)", accent: "#90a4ae" },
};

function ActionNode({ id, data, selected }: NodeProps<ActionData>) {
  const { updateNodeData, removeNode } = useFlowStore();

  const update = useCallback(
    (patch: Partial<ActionData>) => updateNodeData(id, patch),
    [id, updateNodeData],
  );

  const colors = ACTION_COLORS[data.action] ?? ACTION_COLORS.HOLD;

  return (
    <div
      style={{
        background: "#0a0e27",
        border: selected ? `2px solid ${colors.accent}` : "1px solid #1e2d4a",
        borderRadius: 10,
        width: 220,
        boxShadow: selected
          ? `0 0 20px ${colors.accent}40`
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
          background: colors.accent, border: "2px solid #0a0e27",
          left: -5,
        }}
      />

      {/* Header */}
      <div
        style={{
          background: colors.gradient,
          padding: "8px 12px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Zap size={14} color="#fff" />
          <span style={{ color: "#fff", fontSize: 12, fontWeight: 700 }}>
            {data.action === "BUY" ? "매수 실행" : data.action === "SELL" ? "매도 실행" : "보유 유지"}
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
        {/* Action selector */}
        <div style={{ display: "flex", gap: 4 }}>
          {ACTIONS.map((a) => {
            const ac = ACTION_COLORS[a];
            const isActive = data.action === a;
            return (
              <button
                key={a}
                onClick={() => update({ action: a })}
                style={{
                  flex: 1, padding: "5px 0", borderRadius: 4,
                  fontSize: 12, fontWeight: 700, cursor: "pointer",
                  border: `1px solid ${isActive ? ac.accent : "#1e2d4a"}`,
                  background: isActive ? `${ac.accent}20` : "#111633",
                  color: isActive ? ac.accent : "#6b7fa3",
                }}
              >
                {a === "BUY" ? "매수" : a === "SELL" ? "매도" : "보유"}
              </button>
            );
          })}
        </div>

        {/* Size type + value */}
        {data.action !== "HOLD" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <div>
              <label style={{
                fontSize: 10, fontWeight: 600, color: "#6b7fa3",
                textTransform: "uppercase", letterSpacing: "0.06em",
                display: "block", marginBottom: 3,
              }}>
                주문 방식
              </label>
              <select
                value={data.sizeType}
                onChange={(e) => update({ sizeType: e.target.value as ActionData["sizeType"] })}
                style={{
                  width: "100%", background: "#111633",
                  border: "1px solid #1e2d4a", borderRadius: 4,
                  padding: "5px 8px", color: "#e0e8f5",
                  fontSize: 12, cursor: "pointer", outline: "none",
                  appearance: "none" as const,
                }}
              >
                {SIZE_TYPES.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{
                fontSize: 10, fontWeight: 600, color: "#6b7fa3",
                textTransform: "uppercase", letterSpacing: "0.06em",
                display: "block", marginBottom: 3,
              }}>
                {data.sizeType === "percent" ? "비중 (%)" : data.sizeType === "fixed" ? "수량" : ""}
              </label>
              {data.sizeType !== "all" && (
                <input
                  type="number"
                  value={data.sizeValue}
                  onChange={(e) => update({ sizeValue: Number(e.target.value) })}
                  min={1}
                  style={{
                    width: "100%", background: "#111633",
                    border: "1px solid #1e2d4a", borderRadius: 4,
                    padding: "5px 6px", color: "#e0e8f5",
                    fontSize: 13, fontFamily: "'Roboto Mono', monospace",
                    outline: "none",
                  }}
                />
              )}
            </div>
          </div>
        )}

        {/* Stop Loss / Take Profit */}
        {data.action !== "HOLD" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <div>
              <label style={{
                fontSize: 10, fontWeight: 600, color: "#ff5252",
                textTransform: "uppercase", letterSpacing: "0.06em",
                display: "block", marginBottom: 3,
              }}>
                손절 (%)
              </label>
              <input
                type="number"
                value={data.stopLoss ?? ""}
                onChange={(e) => update({ stopLoss: e.target.value ? Number(e.target.value) : undefined })}
                placeholder="—"
                min={0} max={50} step={0.5}
                style={{
                  width: "100%", background: "#111633",
                  border: "1px solid #1e2d4a", borderRadius: 4,
                  padding: "5px 6px", color: "#ff5252",
                  fontSize: 13, fontFamily: "'Roboto Mono', monospace",
                  outline: "none",
                }}
              />
            </div>
            <div>
              <label style={{
                fontSize: 10, fontWeight: 600, color: "#00e676",
                textTransform: "uppercase", letterSpacing: "0.06em",
                display: "block", marginBottom: 3,
              }}>
                익절 (%)
              </label>
              <input
                type="number"
                value={data.takeProfit ?? ""}
                onChange={(e) => update({ takeProfit: e.target.value ? Number(e.target.value) : undefined })}
                placeholder="—"
                min={0} max={100} step={0.5}
                style={{
                  width: "100%", background: "#111633",
                  border: "1px solid #1e2d4a", borderRadius: 4,
                  padding: "5px 6px", color: "#00e676",
                  fontSize: 13, fontFamily: "'Roboto Mono', monospace",
                  outline: "none",
                }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(ActionNode);
