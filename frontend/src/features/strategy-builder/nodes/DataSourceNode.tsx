"use client";

import { memo, useCallback } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { useFlowStore, type DataSourceData } from "@/features/strategy-builder/useFlowStore";
import { Database, X } from "lucide-react";

const UNIVERSES = ["KOSPI", "KOSDAQ", "CUSTOM"] as const;
const TIMEFRAMES = ["1D", "1H", "15M"] as const;

function DataSourceNode({ id, data, selected }: NodeProps<DataSourceData>) {
  const { updateNodeData, removeNode } = useFlowStore();

  const update = useCallback(
    (patch: Partial<DataSourceData>) => updateNodeData(id, patch),
    [id, updateNodeData],
  );

  return (
    <div
      style={{
        background: "#0a0e27",
        border: selected ? "2px solid #1200ff" : "1px solid #1e2d4a",
        borderRadius: 10,
        width: 240,
        boxShadow: selected
          ? "0 0 20px rgba(18,0,255,0.25)"
          : "0 4px 12px rgba(0,0,0,0.4)",
        fontFamily: "'Inter', sans-serif",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          background: "linear-gradient(135deg, #0d47a1 0%, #1200ff 100%)",
          padding: "8px 12px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Database size={14} color="#fff" />
          <span
            style={{
              color: "#fff",
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: "0.02em",
            }}
          >
            데이터 소스
          </span>
        </div>
        <button
          onClick={() => removeNode(id)}
          style={{
            background: "rgba(255,255,255,0.15)",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
            padding: 2,
            display: "flex",
            alignItems: "center",
          }}
        >
          <X size={12} color="#fff" />
        </button>
      </div>

      {/* Body */}
      <div
        style={{
          padding: "10px 12px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {/* Symbol */}
        <div>
          <label
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: "#6b7fa3",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              display: "block",
              marginBottom: 3,
            }}
          >
            종목 코드
          </label>
          <input
            value={data.symbol}
            onChange={(e) => update({ symbol: e.target.value })}
            style={{
              width: "100%",
              background: "#111633",
              border: "1px solid #1e2d4a",
              borderRadius: 4,
              padding: "5px 8px",
              color: "#e0e8f5",
              fontSize: 13,
              fontFamily: "'Roboto Mono', monospace",
              outline: "none",
            }}
            placeholder="005930"
          />
        </div>

        {/* Universe */}
        <div>
          <label
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: "#6b7fa3",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              display: "block",
              marginBottom: 3,
            }}
          >
            유니버스
          </label>
          <select
            value={data.universe}
            onChange={(e) =>
              update({ universe: e.target.value as DataSourceData["universe"] })
            }
            style={{
              width: "100%",
              background: "#111633",
              border: "1px solid #1e2d4a",
              borderRadius: 4,
              padding: "5px 8px",
              color: "#e0e8f5",
              fontSize: 12,
              cursor: "pointer",
              outline: "none",
              appearance: "none" as const,
            }}
          >
            {UNIVERSES.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>

        {/* Timeframe + Lookback row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
          <div>
            <label
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: "#6b7fa3",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                display: "block",
                marginBottom: 3,
              }}
            >
              타임프레임
            </label>
            <select
              value={data.timeframe}
              onChange={(e) =>
                update({
                  timeframe: e.target.value as DataSourceData["timeframe"],
                })
              }
              style={{
                width: "100%",
                background: "#111633",
                border: "1px solid #1e2d4a",
                borderRadius: 4,
                padding: "5px 8px",
                color: "#e0e8f5",
                fontSize: 12,
                cursor: "pointer",
                outline: "none",
                appearance: "none" as const,
              }}
            >
              {TIMEFRAMES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: "#6b7fa3",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                display: "block",
                marginBottom: 3,
              }}
            >
              기간 (일)
            </label>
            <input
              type="number"
              value={data.lookback}
              onChange={(e) => update({ lookback: Number(e.target.value) })}
              min={10}
              max={1000}
              step={10}
              style={{
                width: "100%",
                background: "#111633",
                border: "1px solid #1e2d4a",
                borderRadius: 4,
                padding: "5px 8px",
                color: "#e0e8f5",
                fontSize: 13,
                fontFamily: "'Roboto Mono', monospace",
                outline: "none",
              }}
            />
          </div>
        </div>
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 10,
          height: 10,
          background: "#1200ff",
          border: "2px solid #0a0e27",
          right: -5,
        }}
      />
    </div>
  );
}

export default memo(DataSourceNode);
