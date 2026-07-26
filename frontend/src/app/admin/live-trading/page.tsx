"use client";

import { useState, useEffect, useCallback } from "react";
import {
  AlertOctagon, Power, Shield, Activity, Eye, FlaskConical, Zap,
  TrendingUp, TrendingDown, RefreshCw, X, Lock, Unlock,
  CircleAlert, CheckCircle2, XCircle, Clock,
} from "lucide-react";

import { API_BASE } from "@/shared/api/apiBase";

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

type Mode = "SHADOW" | "PAPER" | "LIVE";

interface Position {
  ticker: string;
  name?: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  eval_amount: number;
  pnl_pct: number;
  pnl_krw: number;
}

interface Balance {
  cash_krw: number;
  evaluated_total: number;
  stock_value: number;
  positions: Position[];
  n_positions: number;
}

interface Order {
  client_order_id: string;
  ticker: string;
  side: string;
  quantity: number;
  filled_quantity?: number;
  price?: number;
  status: string;
  execution_mode: string;
  strategy_id?: number;
  reason_code?: string;
  created_at: string;
}

interface KillStatus {
  is_active: boolean;
  active_event?: { event_id: string; trigger_reason: string; triggered_at: string };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════════════════════════════════════════

export default function LiveTradingPage() {
  const [mode, setMode] = useState<Mode>("SHADOW");
  const [balance, setBalance] = useState<Balance | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [killStatus, setKillStatus] = useState<KillStatus>({ is_active: false });
  const [loading, setLoading] = useState(false);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);

  // Polling
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [modeRes, balRes, ordRes, killRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/live/mode`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v1/live/balance`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v1/live/orders?limit=20`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v1/live/kill-switch/status`).then((r) => r.json()).catch(() => null),
      ]);

      if (modeRes?.mode) setMode(modeRes.mode);
      if (balRes) setBalance(balRes);
      if (ordRes?.orders) setOrders(ordRes.orders);
      if (killRes) setKillStatus(killRes);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10_000);
    return () => clearInterval(interval);
  }, [refresh]);

  // Mode change
  const handleModeChange = async (newMode: Mode) => {
    if (newMode === "LIVE") {
      setShowLiveConfirm(true);
      return;
    }
    await fetch(`${API_BASE}/api/v1/live/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: newMode, actor: "admin" }),
    });
    refresh();
  };

  const confirmLiveMode = async () => {
    await fetch(`${API_BASE}/api/v1/live/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: "LIVE", actor: "admin",
        confirm_token: "EXPLICIT_LIVE_CONFIRMED",
      }),
    });
    setShowLiveConfirm(false);
    refresh();
  };

  // Kill switch
  const triggerKill = async () => {
    await fetch(`${API_BASE}/api/v1/live/kill-switch/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reason: "Manual emergency stop from cockpit",
        liquidation_mode: "hold",
        actor: "admin",
      }),
    });
    setShowKillConfirm(false);
    refresh();
  };

  const resolveKill = async () => {
    await fetch(`${API_BASE}/api/v1/live/kill-switch/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resolved_by: "admin",
        notes: "Manual resolution from cockpit",
      }),
    });
    refresh();
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white" style={{ fontFamily: "Inter, sans-serif" }}>
      {/* Mode banner — LIVE 모드일 때 강한 경고 */}
      {mode === "LIVE" && (
        <div className="bg-gradient-to-r from-[#FF6B6B]/20 via-[#FF6B6B]/30 to-[#FF6B6B]/20 border-b border-[#FF6B6B]/40 py-1.5">
          <div className="max-w-[1600px] mx-auto px-8 text-center text-[11px] font-bold uppercase tracking-[0.2em] text-[#FF6B6B] animate-pulse">
            ⚡ LIVE TRADING ACTIVE · REAL MONEY · EVERY ORDER COUNTS
          </div>
        </div>
      )}

      {/* Kill switch banner */}
      {killStatus.is_active && (
        <div className="bg-[#FF6B6B] py-2">
          <div className="max-w-[1600px] mx-auto px-8 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <AlertOctagon size={18} className="text-black animate-pulse" />
              <span className="text-[12px] font-bold uppercase tracking-wider text-black">
                Kill Switch Active · {killStatus.active_event?.trigger_reason}
              </span>
            </div>
            <button
              onClick={resolveKill}
              className="text-[10px] font-bold uppercase tracking-wider text-black bg-black/20 hover:bg-black/30 px-3 py-1 rounded"
            >
              Resolve
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      <header className="border-b border-zinc-900">
        <div className="max-w-[1600px] mx-auto px-8 py-6">
          <div className="flex items-start justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="w-1 h-10 bg-gradient-to-b from-[#FF6B6B] to-[#DEFF9A] rounded-full" />
              <div>
                <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
                  Live Trading Cockpit
                  <span className="text-xs font-mono text-zinc-500 font-normal bg-zinc-900 px-2 py-0.5 rounded">
                    Stage 13
                  </span>
                </h1>
                <p className="text-[11px] text-zinc-500 mt-0.5 font-mono tracking-wide">
                  KIS API · 5-layer safety · audit trail · regime-adaptive
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button onClick={refresh}
                       className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-[11px] text-zinc-300">
                <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
                Refresh
              </button>
              {/* KILL SWITCH BUTTON */}
              <button
                onClick={() => setShowKillConfirm(true)}
                disabled={killStatus.is_active}
                className="
                  flex items-center gap-2 px-4 py-2 rounded-lg
                  bg-[#FF6B6B] hover:bg-[#ff5050] disabled:bg-zinc-800 disabled:cursor-not-allowed
                  text-black font-bold text-[11px] uppercase tracking-wider
                  border border-[#FF6B6B] disabled:border-zinc-700
                  transition-all
                "
                style={{
                  boxShadow: killStatus.is_active ? "none" : "0 0 24px rgba(255,107,107,0.4)",
                }}
              >
                <Power size={14} />
                Kill Switch
              </button>
            </div>
          </div>

          {/* Mode Selector */}
          <div className="flex justify-center">
            <div className="flex items-center bg-[#0f0f0f] rounded-full p-1.5 border border-zinc-800 gap-1">
              <ModeButton
                value="SHADOW"
                current={mode}
                onClick={() => handleModeChange("SHADOW")}
                icon={Eye}
                color="#6b7280"
                label="Shadow · Signal Only"
              />
              <ModeButton
                value="PAPER"
                current={mode}
                onClick={() => handleModeChange("PAPER")}
                icon={FlaskConical}
                color="#DEFF9A"
                label="Paper · Mock Trading"
              />
              <ModeButton
                value="LIVE"
                current={mode}
                onClick={() => handleModeChange("LIVE")}
                icon={Zap}
                color="#FF6B6B"
                label="Live · Real Money ⚡"
              />
            </div>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="max-w-[1600px] mx-auto px-8 py-8 space-y-6">
        {/* Equity row */}
        <div className="grid grid-cols-4 gap-4">
          <EquityCard
            label="총 평가자산"
            value={fmtKrw(balance?.evaluated_total || 0)}
            icon={TrendingUp}
            color="#DEFF9A"
            highlight
          />
          <EquityCard
            label="가용 현금"
            value={fmtKrw(balance?.cash_krw || 0)}
            icon={Shield}
            color="#DAFFDE"
          />
          <EquityCard
            label="주식 평가액"
            value={fmtKrw(balance?.stock_value || 0)}
            icon={Activity}
            color="#7DD3FC"
          />
          <EquityCard
            label="보유 종목"
            value={`${balance?.n_positions || 0}개`}
            icon={Lock}
            color="#FFC857"
          />
        </div>

        {/* Positions table */}
        <Section title="Live Positions" subtitle={`KIS 잔고 기준 실시간 · 10초 polling`}>
          {!balance?.positions?.length ? (
            <EmptyState message="현재 보유 포지션 없음" />
          ) : (
            <div className="rounded-xl bg-[#0d0d0d] border border-zinc-800 overflow-hidden">
              <table className="w-full text-[11px]">
                <thead className="bg-[#111111] border-b border-zinc-800">
                  <tr>
                    <Th>종목</Th><Th align="right">수량</Th>
                    <Th align="right">매입가</Th><Th align="right">현재가</Th>
                    <Th align="right">평가액</Th><Th align="right">손익</Th>
                  </tr>
                </thead>
                <tbody>
                  {balance.positions.map((p) => (
                    <tr key={p.ticker} className="border-b border-zinc-900 hover:bg-zinc-900/50 transition">
                      <Td>
                        <div className="font-bold text-white">{p.ticker}</div>
                        {p.name && <div className="text-[9px] text-zinc-500">{p.name}</div>}
                      </Td>
                      <Td align="right" mono>{p.quantity.toLocaleString()}</Td>
                      <Td align="right" mono>{p.avg_price.toLocaleString()}</Td>
                      <Td align="right" mono>{p.current_price.toLocaleString()}</Td>
                      <Td align="right" mono>{fmtKrw(p.eval_amount)}</Td>
                      <Td align="right" mono>
                        <span style={{ color: p.pnl_pct >= 0 ? "#DEFF9A" : "#FF6B6B", fontWeight: 700 }}>
                          {p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct.toFixed(2)}%
                        </span>
                        <div className="text-[9px]" style={{ color: p.pnl_krw >= 0 ? "#DAFFDE" : "#FF6B6B" }}>
                          {p.pnl_krw >= 0 ? "+" : ""}{fmtKrw(p.pnl_krw)}
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        {/* Recent orders */}
        <Section title="Order Queue" subtitle={`최근 ${orders.length}건 · 모든 모드 포함`}>
          {!orders.length ? (
            <EmptyState message="주문 이력 없음 — POST /api/v1/live/orders/submit으로 발주" />
          ) : (
            <div className="rounded-xl bg-[#0d0d0d] border border-zinc-800 overflow-hidden">
              <table className="w-full text-[11px]">
                <thead className="bg-[#111111] border-b border-zinc-800">
                  <tr>
                    <Th>주문 ID</Th><Th>모드</Th><Th>전략</Th><Th>종목</Th>
                    <Th align="right">수량</Th><Th>상태</Th><Th>시각</Th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <OrderRow key={o.client_order_id} order={o} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        {/* Tech specs */}
        <div className="pt-4 grid grid-cols-4 gap-4 border-t border-zinc-900 mt-8">
          <SpecBlock label="Mode" value={mode} color={
            mode === "LIVE" ? "#FF6B6B" : mode === "PAPER" ? "#DEFF9A" : "#6b7280"
          } />
          <SpecBlock label="Kill Switch" value={killStatus.is_active ? "ACTIVE" : "STANDBY"}
                       color={killStatus.is_active ? "#FF6B6B" : "#DEFF9A"} />
          <SpecBlock label="Polling" value="10s interval" color="#7DD3FC" />
          <SpecBlock label="Backend" value="KIS API · Stage 13" color="#FFC857" />
        </div>
      </main>

      {/* ─── LIVE 확인 모달 ───────────────────────────── */}
      {showLiveConfirm && (
        <ConfirmModal
          icon={Zap} iconColor="#FF6B6B"
          title="LIVE 모드 진입"
          description="실거래 모드로 전환합니다. 이 시점부터 모든 주문은 실제 자금이 이동됩니다."
          warnings={[
            "주문 검증 통과 시 KIS API로 실제 발주",
            "Kill Switch는 모든 미체결을 즉시 취소",
            "Daily turnover, position size, drawdown 한도 자동 적용",
          ]}
          confirmLabel="실거래 진입 (Confirmed)"
          confirmColor="#FF6B6B"
          onConfirm={confirmLiveMode}
          onCancel={() => setShowLiveConfirm(false)}
        />
      )}

      {/* ─── Kill Switch 확인 모달 ───────────────────── */}
      {showKillConfirm && (
        <ConfirmModal
          icon={Power} iconColor="#FF6B6B"
          title="Kill Switch 발동"
          description="모든 거래를 즉시 중단합니다."
          warnings={[
            "모든 미체결 주문 일괄 취소",
            "신규 주문 거부 (재개까지)",
            "감사 로그에 CRITICAL 기록",
            "포지션은 hold 모드로 유지 (수동 청산 필요)",
          ]}
          confirmLabel="🚨 EXECUTE KILL"
          confirmColor="#FF6B6B"
          onConfirm={triggerKill}
          onCancel={() => setShowKillConfirm(false)}
        />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Components
// ═══════════════════════════════════════════════════════════════════════════════

function ModeButton({ value, current, onClick, icon: Icon, color, label }: any) {
  const active = current === value;
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 px-5 py-2.5 rounded-full text-[11px] font-semibold uppercase tracking-wider transition-all duration-300"
      style={{
        background: active ? color : "transparent",
        color: active ? "#000" : "#52525b",
        boxShadow: active ? `0 0 24px ${color}80` : "none",
      }}
    >
      <Icon size={12} />
      {label}
    </button>
  );
}

function EquityCard({ label, value, icon: Icon, color, highlight }: any) {
  return (
    <div
      className="relative overflow-hidden rounded-xl p-5 bg-[#111111] border border-zinc-800"
      style={{
        backgroundImage: highlight
          ? `radial-gradient(circle at top right, ${color}10, transparent 60%)`
          : undefined,
        borderColor: highlight ? `${color}30` : undefined,
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-zinc-500">
          {label}
        </span>
        <Icon size={12} color={color} />
      </div>
      <div className="text-2xl font-bold font-mono tabular-nums" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function Section({ title, subtitle, children }: any) {
  return (
    <section>
      <div className="mb-3">
        <h2 className="text-sm font-bold text-white tracking-wide">{title}</h2>
        <p className="text-[11px] text-zinc-500 font-mono mt-0.5">{subtitle}</p>
      </div>
      {children}
    </section>
  );
}

function OrderRow({ order }: { order: Order }) {
  const statusColors: Record<string, string> = {
    PENDING:      "#FFC857",
    SUBMITTED:    "#7DD3FC",
    FILLED:       "#DEFF9A",
    PARTIAL_FILL: "#DAFFDE",
    CANCELLED:    "#a1a1aa",
    REJECTED:     "#FF6B6B",
    FAILED:       "#FF6B6B",
    SHADOW_LOGGED:"#6b7280",
  };
  const modeColors: Record<string, string> = {
    SHADOW: "#6b7280", PAPER: "#DEFF9A", LIVE: "#FF6B6B",
  };
  const statusColor = statusColors[order.status] || "#71717a";
  const StatusIcon =
    order.status === "FILLED" ? CheckCircle2 :
    order.status === "REJECTED" || order.status === "FAILED" ? XCircle :
    order.status === "CANCELLED" ? X :
    Clock;

  return (
    <tr className="border-b border-zinc-900 hover:bg-zinc-900/50">
      <Td>
        <div className="font-mono text-[10px] text-zinc-300">{order.client_order_id.slice(0, 14)}</div>
        {order.reason_code && (
          <div className="text-[9px] text-zinc-600 mt-0.5">{order.reason_code}</div>
        )}
      </Td>
      <Td>
        <span
          className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase"
          style={{
            background: `${modeColors[order.execution_mode]}15`,
            color: modeColors[order.execution_mode] || "#a1a1aa",
            border: `1px solid ${modeColors[order.execution_mode]}30`,
          }}
        >
          {order.execution_mode}
        </span>
      </Td>
      <Td mono>{order.strategy_id || "—"}</Td>
      <Td>
        <span className="font-bold text-white">{order.ticker}</span>
        <span className={`ml-2 text-[10px] font-bold ${order.side === "BUY" ? "text-[#DEFF9A]" : "text-[#FF6B6B]"}`}>
          {order.side}
        </span>
      </Td>
      <Td align="right" mono>
        {order.filled_quantity || 0} / {order.quantity}
      </Td>
      <Td>
        <div className="flex items-center gap-1.5">
          <StatusIcon size={11} color={statusColor} />
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: statusColor }}>
            {order.status}
          </span>
        </div>
      </Td>
      <Td mono>
        <span className="text-[10px] text-zinc-500">
          {new Date(order.created_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </span>
      </Td>
    </tr>
  );
}

function ConfirmModal({ icon: Icon, iconColor, title, description, warnings,
                          confirmLabel, confirmColor, onConfirm, onCancel }: any) {
  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-8">
      <div className="bg-[#111111] border border-zinc-800 rounded-2xl p-8 max-w-md w-full">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-3 rounded-xl" style={{ background: `${iconColor}15` }}>
            <Icon size={24} color={iconColor} />
          </div>
          <div>
            <h2 className="text-lg font-bold">{title}</h2>
            <p className="text-[11px] text-zinc-500 mt-0.5">{description}</p>
          </div>
        </div>

        <ul className="space-y-2 mb-6 mt-4">
          {warnings.map((w: string, i: number) => (
            <li key={i} className="flex items-start gap-2 text-[11px] text-zinc-400">
              <CircleAlert size={11} className="text-[#FFC857] mt-0.5 flex-shrink-0" />
              <span>{w}</span>
            </li>
          ))}
        </ul>

        <div className="flex gap-3">
          <button onClick={onCancel}
                   className="flex-1 py-2.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-[11px] font-bold uppercase tracking-wider text-zinc-300">
            Cancel
          </button>
          <button onClick={onConfirm}
                   className="flex-1 py-2.5 rounded-lg font-bold text-[11px] uppercase tracking-wider text-black"
                   style={{ background: confirmColor }}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function SpecBlock({ label, value, color }: any) {
  return (
    <div className="rounded-lg bg-[#0d0d0d] border border-zinc-900 p-3">
      <div className="text-[9px] uppercase tracking-widest text-zinc-500 font-bold mb-1">{label}</div>
      <div className="text-[11px] font-mono font-bold" style={{ color }}>{value}</div>
    </div>
  );
}

function Th({ children, align = "left" }: any) {
  return (
    <th className={`px-4 py-3 text-[9px] uppercase tracking-wider text-zinc-500 font-bold text-${align}`}>
      {children}
    </th>
  );
}

function Td({ children, align = "left", mono }: any) {
  return (
    <td className={`px-4 py-3 text-${align} ${mono ? "font-mono tabular-nums" : ""}`}>
      {children}
    </td>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-xl bg-[#0d0d0d] border border-dashed border-zinc-800 p-10 text-center">
      <div className="text-[11px] text-zinc-500 font-mono">{message}</div>
    </div>
  );
}

// Format helpers
function fmtKrw(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 100_000_000) return `${(v / 100_000_000).toFixed(2)}억`;
  if (abs >= 10_000)      return `${(v / 10_000).toFixed(1)}만`;
  return v.toLocaleString();
}
