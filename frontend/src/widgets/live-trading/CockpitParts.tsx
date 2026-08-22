"use client";
// Live Trading Cockpit 표시 컴포넌트 — 전부 props만 받는다.
// JSX·className 한 줄도 바꾸지 않고 그대로 옮겼다.
// (app/admin/live-trading/page.tsx에서 분리)

import type { ReactNode } from "react";
import { CheckCircle2, CircleAlert, Clock, X, XCircle } from "lucide-react";
import type { Order } from "@/entities/trading/liveModel";

export function ModeButton({ value, current, onClick, icon: Icon, color, label }: any) {
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

export function EquityCard({ label, value, icon: Icon, color, highlight }: any) {
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

export function Section({ title, subtitle, children }: any) {
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

export function OrderRow({ order }: { order: Order }) {
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

export function ConfirmModal({ icon: Icon, iconColor, title, description, warnings,
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

export function SpecBlock({ label, value, color }: any) {
  return (
    <div className="rounded-lg bg-[#0d0d0d] border border-zinc-900 p-3">
      <div className="text-[9px] uppercase tracking-widest text-zinc-500 font-bold mb-1">{label}</div>
      <div className="text-[11px] font-mono font-bold" style={{ color }}>{value}</div>
    </div>
  );
}

export function Th({ children, align = "left" }: any) {
  return (
    <th className={`px-4 py-3 text-[9px] uppercase tracking-wider text-zinc-500 font-bold text-${align}`}>
      {children}
    </th>
  );
}

export function Td({ children, align = "left", mono }: any) {
  return (
    <td className={`px-4 py-3 text-${align} ${mono ? "font-mono tabular-nums" : ""}`}>
      {children}
    </td>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-xl bg-[#0d0d0d] border border-dashed border-zinc-800 p-10 text-center">
      <div className="text-[11px] text-zinc-500 font-mono">{message}</div>
    </div>
  );
}

// Format helpers
export function fmtKrw(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 100_000_000) return `${(v / 100_000_000).toFixed(2)}억`;
  if (abs >= 10_000)      return `${(v / 10_000).toFixed(1)}만`;
  return v.toLocaleString();
}

