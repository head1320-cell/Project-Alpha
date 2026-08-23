"use client";

import { useCallback, useRef, useState, type DragEvent } from "react";
import ReactFlow, {
  Background, Controls, MiniMap,
  type ReactFlowInstance,
  BackgroundVariant,
} from "reactflow";
import "reactflow/dist/style.css";

import {
  useFlowStore,
  createDataSourceNode,
  createIndicatorNode,
  createConditionNode,
  createActionNode,
} from "@/features/strategy-builder/useFlowStore";

import DataSourceNode from "./nodes/DataSourceNode";
import IndicatorNode from "./nodes/IndicatorNode";
import ActionNode from "./nodes/ActionNode";

import {
  Database, Activity, Zap, Trash2, Play, Download,
  X, TrendingUp, TrendingDown, BarChart3, Loader2,
} from "lucide-react";
import {
  LineChart, Line, AreaChart, Area,
  XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

// ── Node type registry ──────────────────────────────────────────────────────
const nodeTypes = {
  dataSource: DataSourceNode,
  indicator:  IndicatorNode,
  action:     ActionNode,
};

// ── Sidebar items ───────────────────────────────────────────────────────────
const SIDEBAR_ITEMS = [
  {
    category: "데이터",
    items: [
      { type: "dataSource", label: "데이터 소스", desc: "종목 · 유니버스", icon: Database, color: "#1200ff" },
    ],
  },
  {
    category: "지표",
    items: [
      { type: "indicator:rsi",   label: "RSI",              desc: "상대강도지수",     icon: Activity, color: "#e040fb" },
      { type: "indicator:macd",  label: "MACD",             desc: "이동평균수렴확산", icon: Activity, color: "#e040fb" },
      { type: "indicator:sma",   label: "SMA",              desc: "단순이동평균",     icon: Activity, color: "#00e5ff" },
      { type: "indicator:ema",   label: "EMA",              desc: "지수이동평균",     icon: Activity, color: "#00e5ff" },
      { type: "indicator:bb",    label: "Bollinger Bands",  desc: "볼린저밴드",       icon: Activity, color: "#00e5ff" },
      { type: "indicator:atr",   label: "ATR",              desc: "평균진폭",         icon: Activity, color: "#ff9100" },
      { type: "indicator:stoch", label: "Stochastic",       desc: "스토캐스틱",       icon: Activity, color: "#e040fb" },
      { type: "indicator:adx",   label: "ADX",              desc: "평균방향지수",     icon: Activity, color: "#ff9100" },
      { type: "indicator:cci",   label: "CCI",              desc: "상품채널지수",     icon: Activity, color: "#e040fb" },
      { type: "indicator:obv",   label: "OBV",              desc: "균형거래량",       icon: Activity, color: "#69f0ae" },
      { type: "indicator:vwap",  label: "VWAP",             desc: "거래량가중가격",   icon: Activity, color: "#69f0ae" },
      { type: "indicator:mfi",   label: "MFI",              desc: "자금흐름지수",     icon: Activity, color: "#e040fb" },
    ],
  },
  {
    category: "실행",
    items: [
      { type: "action", label: "매매 실행", desc: "매수 · 매도 · 보유", icon: Zap, color: "#00e676" },
    ],
  },
];

// ── Backtest result type ────────────────────────────────────────────────────
interface BacktestResult {
  success: boolean;
  message: string;
  parsed_strategy: Record<string, unknown>;
  statistics: {
    total_return_pct: number; cagr: number; max_drawdown_pct: number;
    sharpe_ratio: number; sortino_ratio: number; calmar_ratio: number;
    num_trades: number; win_rate: number; profit_factor: number;
    avg_trade_return: number; total_commission: number; total_slippage: number;
  };
  equity_curve: number[];
  equity_dates: string[];
  drawdown_curve: number[];
  monthly_returns: Array<{ year: number; month: number; return_pct: number }>;
  trades: Array<{
    date: string; ticker: string; side: string;
    price: number; quantity: number; value: number;
    pnl: number | null; reason: string;
  }>;
}

// ── Stat card inside results ────────────────────────────────────────────────
function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 10, fontWeight: 600, color: "#6b7fa3", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </span>
      <span style={{ fontSize: 15, fontWeight: 700, fontFamily: "'Roboto Mono', monospace", color: color ?? "#e0e8f5" }}>
        {value}
      </span>
    </div>
  );
}

// ── Tooltip for chart ───────────────────────────────────────────────────────
function ChartTip({ active, payload }: { active?: boolean; payload?: Array<{ value: number }> }) {
  if (!active || !payload?.length) return null;
  const v = payload[0].value;
  return (
    <div style={{ background: "#0a0e27", border: "1px solid #1e2d4a", borderRadius: 6, padding: "6px 10px", fontSize: 12, color: "#e0e8f5", fontFamily: "'Roboto Mono', monospace" }}>
      ₩{v.toLocaleString()}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════════

import { API_BASE } from "@/shared/api/apiBase";
import { useChartAnimation } from "@/shared/ui/chartStyle";

export default function StrategyCanvas() {
  const anim = useChartAnimation();
  const {
    nodes, edges,
    onNodesChange, onEdgesChange, onConnect,
    addNode, clearAll, toJSON,
  } = useFlowStore();

  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const rfInstance = useRef<ReactFlowInstance | null>(null);

  // ── Backtest state ──────────────────────────────────────────────────────
  const [loading, setLoading]   = useState(false);
  const [result, setResult]     = useState<BacktestResult | null>(null);
  const [error, setError]       = useState("");
  const [showPanel, setShowPanel] = useState(false);

  // ── Drag & Drop handlers ────────────────────────────────────────────────
  const onDragStart = useCallback((e: DragEvent, nodeType: string) => {
    e.dataTransfer.setData("application/reactflow", nodeType);
    e.dataTransfer.effectAllowed = "move";
  }, []);

  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const type = e.dataTransfer.getData("application/reactflow");
      if (!type || !rfInstance.current || !reactFlowWrapper.current) return;

      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = rfInstance.current.project({
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      });

      let newNode;
      if (type === "dataSource") {
        newNode = createDataSourceNode(position);
      } else if (type.startsWith("indicator:")) {
        newNode = createIndicatorNode(position, type.split(":")[1]);
      } else if (type === "action") {
        newNode = createActionNode(position);
      }

      if (newNode) addNode(newNode);
    },
    [addNode],
  );

  // ── Backtest — POST to FastAPI ──────────────────────────────────────────
  const handleBacktest = useCallback(async () => {
    const json = toJSON();

    if (json.nodes.length === 0) {
      setError("캔버스에 노드를 추가하세요.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setShowPanel(true);

    try {
      const resp = await fetch(`${API_BASE}/api/v1/backtest/graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nodes: json.nodes,
          edges: json.edges,
          initial_capital: 100_000_000,
          commission_rate: 0.0015,
          slippage_rate: 0.0005,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `HTTP ${resp.status}`);
      }

      const data: BacktestResult = await resp.json();

      if (!data.success) {
        setError(data.message || "백테스트 실패");
      } else {
        setResult(data);
      }
    } catch (e) {
      setError((e as Error).message || "서버 연결 오류");
    } finally {
      setLoading(false);
    }
  }, [toJSON]);

  // ── Export JSON ─────────────────────────────────────────────────────────
  const handleExport = useCallback(() => {
    const json = toJSON();
    const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "strategy-flow.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [toJSON]);

  // ── Equity chart data ──────────────────────────────────────────────────
  const eqData = result?.equity_curve.map((v, i) => ({
    i,
    v,
    dd: (result.drawdown_curve[i] ?? 0) * 100,
  })) ?? [];

  return (
    <div style={{ display: "flex", height: "calc(100vh - 56px)", background: "#060a1a" }}>

      {/* ══ Left Sidebar: Node Palette ══ */}
      <aside style={{
        width: 220, background: "#0a0e27", borderRight: "1px solid #1e2d4a",
        display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0,
      }}>
        <div style={{
          padding: "12px 14px", borderBottom: "1px solid #1e2d4a",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#6b7fa3", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            노드 팔레트
          </span>
          <button onClick={clearAll} title="전체 삭제" style={{
            background: "none", border: "none", cursor: "pointer", color: "#6b7fa3", padding: 2, display: "flex",
          }}>
            <Trash2 size={13} />
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "8px 10px" }}>
          {SIDEBAR_ITEMS.map((cat) => (
            <div key={cat.category} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#4a5f80", textTransform: "uppercase", letterSpacing: "0.08em", padding: "0 4px 6px" }}>
                {cat.category}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {cat.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <div key={item.type} draggable
                      onDragStart={(e) => onDragStart(e, item.type)}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "7px 10px", borderRadius: 6,
                        border: "1px solid #1e2d4a", background: "#0f1538",
                        cursor: "grab", transition: "all 0.15s", userSelect: "none",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.borderColor = item.color; e.currentTarget.style.background = `${item.color}10`; }}
                      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "#1e2d4a"; e.currentTarget.style.background = "#0f1538"; }}
                    >
                      <div style={{ width: 26, height: 26, borderRadius: 5, background: `${item.color}20`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        <Icon size={13} color={item.color} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "#e0e8f5", lineHeight: 1.2 }}>{item.label}</div>
                        <div style={{ fontSize: 10, color: "#4a5f80", marginTop: 1 }}>{item.desc}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div style={{ padding: "10px 14px", borderTop: "1px solid #1e2d4a", fontSize: 10, color: "#4a5f80", lineHeight: 1.5 }}>
          노드를 드래그하여 캔버스에 놓으세요.<br />노드 사이를 마우스로 연결합니다.
        </div>
      </aside>

      {/* ══ Canvas ══ */}
      <div ref={reactFlowWrapper} style={{ flex: 1, position: "relative" }}
        onDragOver={onDragOver} onDrop={onDrop}>
        <ReactFlow
          nodes={nodes} edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onInit={(instance) => { rfInstance.current = instance; }}
          nodeTypes={nodeTypes}
          fitView snapToGrid snapGrid={[16, 16]}
          style={{ background: "#060a1a" }}
          defaultEdgeOptions={{ animated: true, style: { stroke: "#1200ff", strokeWidth: 2 } }}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#1a2040" />
          <Controls style={{ background: "#0a0e27", border: "1px solid #1e2d4a", borderRadius: 8 }} />
          <MiniMap
            style={{ background: "#0a0e27", border: "1px solid #1e2d4a", borderRadius: 8 }}
            nodeColor={(n) => n.type === "dataSource" ? "#1200ff" : n.type === "indicator" ? "#e040fb" : "#00e676"}
            maskColor="rgba(6,10,26,0.7)"
          />
        </ReactFlow>

        {/* Top-right action bar */}
        <div style={{ position: "absolute", top: 12, right: showPanel ? 420 : 12, display: "flex", gap: 8, zIndex: 10, transition: "right 0.3s" }}>
          <button onClick={handleExport} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "8px 14px", borderRadius: 6, border: "1px solid #1e2d4a",
            background: "#0a0e27", color: "#6b7fa3", fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}>
            <Download size={13} /> JSON
          </button>
          <button onClick={handleBacktest} disabled={loading} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "8px 16px", borderRadius: 6, border: "none",
            background: loading ? "#2a2f5a" : "linear-gradient(135deg, #0d47a1 0%, #1200ff 100%)",
            color: "#fff", fontSize: 13, fontWeight: 700, cursor: loading ? "wait" : "pointer",
            boxShadow: "0 2px 12px rgba(18,0,255,0.3)", opacity: loading ? 0.7 : 1,
          }}>
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {loading ? "실행 중..." : "백테스트 실행"}
          </button>
        </div>

        {/* Bottom-left stats */}
        <div style={{
          position: "absolute", bottom: 12, left: 12, display: "flex", gap: 12,
          padding: "6px 12px", borderRadius: 6, background: "rgba(10,14,39,0.9)",
          border: "1px solid #1e2d4a", fontSize: 11, color: "#6b7fa3", zIndex: 10,
        }}>
          <span>노드 <strong style={{ color: "#e0e8f5", fontFamily: "'Roboto Mono', monospace" }}>{nodes.length}</strong></span>
          <span style={{ color: "#1e2d4a" }}>│</span>
          <span>연결 <strong style={{ color: "#e0e8f5", fontFamily: "'Roboto Mono', monospace" }}>{edges.length}</strong></span>
        </div>
      </div>

      {/* ══ Right Panel: Results ══ */}
      {showPanel && (
        <aside style={{
          width: 400, background: "#0a0e27", borderLeft: "1px solid #1e2d4a",
          display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0,
          animation: "slideInRight 0.3s ease-out",
        }}>
          {/* Panel header */}
          <div style={{
            padding: "12px 16px", borderBottom: "1px solid #1e2d4a",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <BarChart3 size={14} color="#1200ff" />
              <span style={{ fontSize: 13, fontWeight: 700, color: "#e0e8f5" }}>백테스트 결과</span>
            </div>
            <button onClick={() => setShowPanel(false)} style={{
              background: "none", border: "none", cursor: "pointer", color: "#6b7fa3", padding: 2, display: "flex",
            }}>
              <X size={14} />
            </button>
          </div>

          {/* Panel body */}
          <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>

            {/* Loading */}
            {loading && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "60px 0", gap: 12 }}>
                <Loader2 size={28} color="#1200ff" className="animate-spin" />
                <span style={{ fontSize: 13, color: "#6b7fa3" }}>그래프 파싱 + 백테스트 실행 중...</span>
              </div>
            )}

            {/* Error */}
            {error && !loading && (
              <div style={{
                padding: "12px 14px", borderRadius: 6,
                background: "rgba(255,77,109,0.1)", border: "1px solid rgba(255,77,109,0.3)",
                color: "#ff5252", fontSize: 12, lineHeight: 1.5,
              }}>
                {error}
              </div>
            )}

            {/* Results */}
            {result && !loading && (
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {/* Message */}
                <div style={{ fontSize: 12, color: "#69f0ae", background: "rgba(105,240,174,0.08)", padding: "8px 10px", borderRadius: 6, border: "1px solid rgba(105,240,174,0.2)" }}>
                  {result.message}
                </div>

                {/* Key stats */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                  <Stat label="총수익률" value={`${result.statistics.total_return_pct >= 0 ? "+" : ""}${result.statistics.total_return_pct.toFixed(2)}%`}
                    color={result.statistics.total_return_pct >= 0 ? "#69f0ae" : "#ff5252"} />
                  <Stat label="CAGR" value={`${result.statistics.cagr.toFixed(2)}%`}
                    color={result.statistics.cagr >= 0 ? "#69f0ae" : "#ff5252"} />
                  <Stat label="Max DD" value={`${result.statistics.max_drawdown_pct.toFixed(2)}%`} color="#ff5252" />
                  <Stat label="Sharpe" value={result.statistics.sharpe_ratio.toFixed(3)}
                    color={result.statistics.sharpe_ratio >= 1 ? "#69f0ae" : "#e0e8f5"} />
                  <Stat label="Sortino" value={result.statistics.sortino_ratio.toFixed(3)} />
                  <Stat label="Calmar" value={result.statistics.calmar_ratio.toFixed(3)} />
                  <Stat label="거래횟수" value={String(result.statistics.num_trades)} />
                  <Stat label="승률" value={`${result.statistics.win_rate.toFixed(1)}%`}
                    color={result.statistics.win_rate >= 50 ? "#69f0ae" : "#ff5252"} />
                  <Stat label="수익계수" value={result.statistics.profit_factor.toFixed(3)}
                    color={result.statistics.profit_factor >= 1 ? "#69f0ae" : "#ff5252"} />
                </div>

                {/* Equity Curve */}
                {eqData.length > 0 && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: "#6b7fa3", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                      자산 추이
                    </div>
                    <div style={{ background: "#060a1a", borderRadius: 6, padding: "8px 4px", border: "1px solid #1e2d4a" }}>
                      <ResponsiveContainer width="100%" height={140}>
                        <AreaChart data={eqData}>
                          <defs>
                            <linearGradient id="eqG" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#1200ff" stopOpacity={0.2} />
                              <stop offset="95%" stopColor="#1200ff" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <XAxis dataKey="i" hide />
                          <YAxis hide />
                          <Tooltip content={<ChartTip />} />
                          <Area isAnimationActive={anim} dataKey="v" stroke="#1200ff" strokeWidth={1.5} fill="url(#eqG)" dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Drawdown */}
                {eqData.length > 0 && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: "#6b7fa3", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                      낙폭 (Drawdown)
                    </div>
                    <div style={{ background: "#060a1a", borderRadius: 6, padding: "8px 4px", border: "1px solid #1e2d4a" }}>
                      <ResponsiveContainer width="100%" height={80}>
                        <AreaChart data={eqData}>
                          <defs>
                            <linearGradient id="ddG" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#ff5252" stopOpacity={0.2} />
                              <stop offset="100%" stopColor="#ff5252" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <XAxis dataKey="i" hide />
                          <YAxis hide />
                          <ReferenceLine y={0} stroke="#1e2d4a" />
                          <Area isAnimationActive={anim} dataKey="dd" stroke="#ff5252" strokeWidth={1} fill="url(#ddG)" dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Cost summary */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, padding: "10px", background: "#0f1538", borderRadius: 6, border: "1px solid #1e2d4a" }}>
                  <Stat label="총 수수료" value={`₩${result.statistics.total_commission.toLocaleString()}`} />
                  <Stat label="슬리피지" value={`₩${result.statistics.total_slippage.toLocaleString()}`} />
                </div>

                {/* Trades list */}
                {result.trades.length > 0 && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: "#6b7fa3", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                      체결 내역 ({result.trades.length})
                    </div>
                    <div style={{ maxHeight: 200, overflowY: "auto", borderRadius: 6, border: "1px solid #1e2d4a" }}>
                      {result.trades.map((t, i) => (
                        <div key={i} style={{
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "6px 10px", borderBottom: "1px solid #1e2d4a",
                          fontSize: 11,
                        }}>
                          {t.side === "buy"
                            ? <TrendingUp size={11} color="#69f0ae" />
                            : <TrendingDown size={11} color="#ff5252" />}
                          <span style={{ color: "#6b7fa3", fontFamily: "'Roboto Mono', monospace", width: 72, flexShrink: 0 }}>
                            {t.date}
                          </span>
                          <span style={{
                            fontSize: 10, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
                            background: t.side === "buy" ? "rgba(105,240,174,0.15)" : "rgba(255,82,82,0.15)",
                            color: t.side === "buy" ? "#69f0ae" : "#ff5252",
                          }}>
                            {t.side === "buy" ? "매수" : "매도"}
                          </span>
                          <span style={{ flex: 1, fontFamily: "'Roboto Mono', monospace", color: "#e0e8f5", textAlign: "right" }}>
                            {t.quantity.toLocaleString()}주
                          </span>
                          {t.pnl !== null && (
                            <span style={{
                              fontFamily: "'Roboto Mono', monospace",
                              color: t.pnl >= 0 ? "#69f0ae" : "#ff5252", fontSize: 11, width: 80, textAlign: "right",
                            }}>
                              {t.pnl >= 0 ? "+" : ""}{t.pnl.toLocaleString()}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Parsed strategy info */}
                <details style={{ fontSize: 11, color: "#4a5f80" }}>
                  <summary style={{ cursor: "pointer", userSelect: "none", padding: "4px 0" }}>파싱된 그래프 구조</summary>
                  <pre style={{
                    marginTop: 8, padding: 10, borderRadius: 6,
                    background: "#060a1a", border: "1px solid #1e2d4a",
                    color: "#6b7fa3", fontSize: 10, fontFamily: "'Roboto Mono', monospace",
                    overflow: "auto", maxHeight: 200, whiteSpace: "pre-wrap",
                  }}>
                    {JSON.stringify(result.parsed_strategy, null, 2)}
                  </pre>
                </details>
              </div>
            )}
          </div>
        </aside>
      )}

      {/* Slide-in animation */}
      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        .animate-spin {
          animation: spin 0.7s linear infinite;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
