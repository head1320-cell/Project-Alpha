"use client";

import { Droplets, BatteryCharging, Shuffle, AlertCircle } from "lucide-react";
import type { StrategyCapacity } from "@/entities/realism/data";
import { fmtKrw } from "@/entities/realism/data";

interface Props {
  capacities: StrategyCapacity[];
}

const STATUS_COLOR = {
  safe:    "#DEFF9A",
  warning: "#FFC857",
  danger:  "#FF6B6B",
};

const STATUS_LABEL = {
  safe:    "정상",
  warning: "주의",
  danger:  "한계",
};

export default function LiquidityMonitor({ capacities }: Props) {
  const totalUsed = capacities.reduce((sum, c) => sum + c.used_krw, 0);
  const totalCapacity = capacities.reduce((sum, c) => sum + c.capacity_krw, 0);
  const avgUtil = capacities.reduce((sum, c) => sum + c.utilization_pct, 0) / capacities.length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-bold text-white tracking-wide uppercase flex items-center gap-2">
            <Droplets size={14} className="text-[#DEFF9A]" />
            Liquidity & Capacity Monitor
          </h3>
          <p className="text-[10px] text-zinc-500 mt-1 font-mono">
            ADV 5% × 5-day holding · safety buffer 0.7
          </p>
        </div>
        <div className="text-right">
          <div className="text-[9px] uppercase text-zinc-500 font-bold">Total Utilization</div>
          <div className="text-xl font-bold font-mono text-[#DEFF9A] tabular-nums">
            {avgUtil.toFixed(1)}%
          </div>
        </div>
      </div>

      {/* 3-pane Strategy Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        {capacities.map((cap) => (
          <CapacityCard key={cap.id} cap={cap} />
        ))}
      </div>

      {/* Aggregate */}
      <div className="rounded-xl bg-[#0d0d0d] border border-zinc-800 p-4 grid grid-cols-3 gap-4">
        <AggStat
          icon={Droplets}
          label="총 사용량"
          value={fmtKrw(totalUsed) + "원"}
          color="#DEFF9A"
        />
        <AggStat
          icon={BatteryCharging}
          label="총 수용량"
          value={fmtKrw(totalCapacity) + "원"}
          color="#DAFFDE"
        />
        <AggStat
          icon={Shuffle}
          label="재배분 발생"
          value={`${capacities.filter((c) => c.status !== "safe").length}건`}
          color={capacities.some((c) => c.status === "danger") ? "#FF6B6B" : "#FFC857"}
        />
      </div>
    </div>
  );
}

function CapacityCard({ cap }: { cap: StrategyCapacity }) {
  const color = STATUS_COLOR[cap.status];
  const statusLabel = STATUS_LABEL[cap.status];

  return (
    <div
      className={`
        relative overflow-hidden rounded-xl p-4
        bg-[#111111] border transition-colors duration-300
      `}
      style={{
        borderColor: cap.status === "danger" ? `${color}40` :
                     cap.status === "warning" ? `${color}30` : "#27272a",
        backgroundImage: cap.status !== "safe"
          ? `radial-gradient(circle at top right, ${color}08, transparent 60%)`
          : undefined,
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[11px] font-bold text-white">
            {cap.name}
          </div>
          <div className="text-[9px] text-zinc-500 font-mono mt-0.5">
            ADV {cap.adv_pct.toFixed(1)}% · #{cap.id}
          </div>
        </div>

        <div
          className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider"
          style={{
            background: `${color}15`,
            color,
            border: `1px solid ${color}30`,
          }}
        >
          {cap.status === "danger" && <AlertCircle size={9} />}
          {statusLabel}
        </div>
      </div>

      {/* Gauge Bar */}
      <div className="mb-2">
        <div className="flex items-baseline justify-between mb-1.5">
          <span
            className="text-2xl font-bold font-mono tabular-nums leading-none"
            style={{ color }}
          >
            {cap.utilization_pct}
          </span>
          <span className="text-xs font-bold text-zinc-600 ml-0.5">%</span>
        </div>

        {/* Segmented bar (10 segments) */}
        <div className="flex gap-0.5 h-2">
          {Array.from({ length: 20 }).map((_, i) => {
            const threshold = (i + 1) * 5;
            const active = threshold <= cap.utilization_pct;
            const isWarning = threshold > 70 && threshold <= 90;
            const isDanger = threshold > 90;
            const segColor = !active
              ? "#1a1a1a"
              : isDanger
              ? "#FF6B6B"
              : isWarning
              ? "#FFC857"
              : "#DEFF9A";
            return (
              <div
                key={i}
                className="flex-1 rounded-sm transition-all duration-300"
                style={{
                  background: segColor,
                  boxShadow: active && isDanger ? `0 0 4px ${segColor}` : "none",
                }}
              />
            );
          })}
        </div>
      </div>

      {/* Footer stats */}
      <div className="grid grid-cols-2 gap-2 pt-2 border-t border-zinc-800">
        <div>
          <div className="text-[9px] text-zinc-500 uppercase tracking-wider">사용</div>
          <div className="text-[10px] font-mono text-zinc-300 mt-0.5">
            {fmtKrw(cap.used_krw)}
          </div>
        </div>
        <div>
          <div className="text-[9px] text-zinc-500 uppercase tracking-wider">한계</div>
          <div className="text-[10px] font-mono text-zinc-300 mt-0.5">
            {fmtKrw(cap.capacity_krw)}
          </div>
        </div>
      </div>

      {/* Danger pulse indicator */}
      {cap.status === "danger" && (
        <div
          className="absolute top-2 right-2 w-2 h-2 rounded-full bg-[#FF6B6B] animate-pulse"
          style={{ boxShadow: "0 0 8px #FF6B6B" }}
        />
      )}
    </div>
  );
}

function AggStat({ icon: Icon, label, value, color }: {
  icon: any; label: string; value: string; color: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon size={11} color={color} />
        <span className="text-[9px] uppercase tracking-wider text-zinc-500 font-bold">
          {label}
        </span>
      </div>
      <div className="text-base font-bold font-mono tabular-nums" style={{ color }}>
        {value}
      </div>
    </div>
  );
}
