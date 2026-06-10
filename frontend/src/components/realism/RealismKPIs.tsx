"use client";

import { useEffect, useState } from "react";
import {
  Target, TrendingDown, Wallet, ShieldCheck,
  ArrowDownRight, ArrowUpRight, Activity, AlertTriangle,
} from "lucide-react";
import type { RealismKPIs } from "@/lib/realismData";
import { fmtPct, fmtKrw } from "@/lib/realismData";

interface Props {
  kpis: RealismKPIs;
  mode: "ideal" | "reality";
}

export default function RealismKPICards({ kpis, mode }: Props) {
  // Animated number reveal
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    setRevealed(false);
    const t = setTimeout(() => setRevealed(true), 50);
    return () => clearTimeout(t);
  }, [mode, kpis]);

  // Fidelity grade
  const fidelityGrade =
    kpis.fidelityScore >= 95 ? "A+" :
    kpis.fidelityScore >= 90 ? "A" :
    kpis.fidelityScore >= 85 ? "B+" :
    kpis.fidelityScore >= 80 ? "B" :
    kpis.fidelityScore >= 70 ? "C" : "D";

  const fidelityColor =
    kpis.fidelityScore >= 90 ? "#DEFF9A" :
    kpis.fidelityScore >= 80 ? "#DAFFDE" :
    kpis.fidelityScore >= 70 ? "#FFC857" : "#FF6B6B";

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
      {/* ─ Card 1: Fidelity Score (Hero) ─────────────────────────────── */}
      <div
        className={`
          relative overflow-hidden rounded-2xl p-6
          bg-[#111111] border border-zinc-800
          transition-all duration-700
          ${revealed ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}
          hover:border-[#DEFF9A]/30 group
        `}
        style={{
          backgroundImage: `
            radial-gradient(circle at top right, rgba(222,255,154,0.08), transparent 60%),
            linear-gradient(135deg, #111111 0%, #0d0d0d 100%)
          `,
        }}
      >
        {/* Decorative grid */}
        <svg
          className="absolute inset-0 w-full h-full opacity-[0.03] pointer-events-none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <pattern id="grid1" width="20" height="20" patternUnits="userSpaceOnUse">
              <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#DEFF9A" strokeWidth="0.5" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid1)" />
        </svg>

        <div className="relative">
          {/* Header */}
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-2">
              <div
                className="p-1.5 rounded-lg"
                style={{ background: "rgba(222,255,154,0.1)" }}
              >
                <Target size={14} color="#DEFF9A" />
              </div>
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-zinc-400">
                Fidelity Score
              </span>
            </div>
            <span
              className="px-2 py-0.5 rounded-md text-[10px] font-bold font-mono"
              style={{
                background: `${fidelityColor}15`,
                color: fidelityColor,
                border: `1px solid ${fidelityColor}30`,
              }}
            >
              {fidelityGrade}
            </span>
          </div>

          {/* Big Number */}
          <div className="flex items-baseline gap-1 mb-1">
            <span
              className="text-5xl font-bold font-mono leading-none tabular-nums tracking-tight"
              style={{ color: fidelityColor }}
            >
              {kpis.fidelityScore.toFixed(1)}
            </span>
            <span className="text-2xl font-bold text-zinc-500">%</span>
          </div>

          {/* Subtitle */}
          <div className="text-[10px] text-zinc-500 font-mono mt-3 leading-relaxed">
            Realistic CAGR ÷ Ideal CAGR
            <br />
            <span className="text-zinc-600">
              {fidelityGrade === "A+" || fidelityGrade === "A"
                ? "→ 백테스트 거의 실현 가능"
                : fidelityGrade.startsWith("B")
                ? "→ 마찰 손실 보통 — 수용 가능"
                : "→ 백테스트 과대평가 위험"}
            </span>
          </div>

          {/* Progress ring */}
          <div className="mt-4">
            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-1000 ease-out"
                style={{
                  width: revealed ? `${Math.min(kpis.fidelityScore, 100)}%` : "0%",
                  background: `linear-gradient(90deg, ${fidelityColor}, ${fidelityColor}80)`,
                  boxShadow: `0 0 12px ${fidelityColor}80`,
                }}
              />
            </div>
            <div className="flex justify-between text-[8px] text-zinc-700 mt-1 font-mono">
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
          </div>
        </div>
      </div>

      {/* ─ Card 2: Total Alpha Erosion ──────────────────────────────── */}
      <div
        className={`
          relative overflow-hidden rounded-2xl p-6
          bg-[#111111] border border-zinc-800
          transition-all duration-700 delay-75
          ${revealed ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}
          hover:border-[#FF6B6B]/30 group
        `}
        style={{
          backgroundImage: `
            radial-gradient(circle at top right, rgba(255,107,107,0.08), transparent 60%),
            linear-gradient(135deg, #111111 0%, #0d0d0d 100%)
          `,
        }}
      >
        <div className="relative">
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg" style={{ background: "rgba(255,107,107,0.1)" }}>
                <TrendingDown size={14} color="#FF6B6B" />
              </div>
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-zinc-400">
                Alpha Erosion
              </span>
            </div>
            <ArrowDownRight size={14} color="#FF6B6B" />
          </div>

          <div className="flex items-baseline gap-1 mb-1">
            <span className="text-5xl font-bold font-mono leading-none tabular-nums tracking-tight text-[#FF6B6B]">
              {kpis.totalAlphaErosionPct.toFixed(2)}
            </span>
            <span className="text-2xl font-bold text-zinc-500">%</span>
          </div>

          <div className="text-[10px] text-zinc-500 font-mono mt-3 leading-relaxed">
            Realistic - Ideal total return
            <br />
            <span className="text-zinc-600">
              → {fmtKrw(Math.abs(kpis.totalAlphaErosionPct / 100) * 10_000_000_000)}원 소실
            </span>
          </div>

          {/* Erosion breakdown bar */}
          <div className="mt-4 space-y-1.5">
            <ErosionRow
              label="Market Impact"
              value={kpis.marketImpactCostKrw}
              color="#FF6B6B"
              max={150_000_000}
              revealed={revealed}
            />
            <ErosionRow
              label="Capacity Drop"
              value={kpis.capacityReallocs * 8_000_000}
              color="#FFC857"
              max={150_000_000}
              revealed={revealed}
            />
          </div>
        </div>
      </div>

      {/* ─ Card 3: Annual Cash Yield ─────────────────────────────────── */}
      <div
        className={`
          relative overflow-hidden rounded-2xl p-6
          bg-[#111111] border border-zinc-800
          transition-all duration-700 delay-150
          ${revealed ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}
          hover:border-[#DAFFDE]/30 group
        `}
        style={{
          backgroundImage: `
            radial-gradient(circle at top right, rgba(218,255,222,0.08), transparent 60%),
            linear-gradient(135deg, #111111 0%, #0d0d0d 100%)
          `,
        }}
      >
        <div className="relative">
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg" style={{ background: "rgba(218,255,222,0.1)" }}>
                <Wallet size={14} color="#DAFFDE" />
              </div>
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-zinc-400">
                Annual Cash Yield
              </span>
            </div>
            <ArrowUpRight size={14} color="#DAFFDE" />
          </div>

          <div className="flex items-baseline gap-1 mb-1">
            <span className="text-5xl font-bold font-mono leading-none tabular-nums tracking-tight text-[#DAFFDE]">
              +{kpis.annualCashYieldPct.toFixed(2)}
            </span>
            <span className="text-2xl font-bold text-zinc-500">%</span>
          </div>

          <div className="text-[10px] text-zinc-500 font-mono mt-3 leading-relaxed">
            CD91 무위험 이자 (유휴 현금)
            <br />
            <span className="text-zinc-600">
              → +{fmtKrw(kpis.cashYieldKrw)}원 추가 수익
            </span>
          </div>

          {/* Cash position visualization */}
          <div className="mt-4">
            <div className="flex items-center justify-between text-[9px] text-zinc-500 mb-1.5">
              <span>유휴 현금 비중</span>
              <span className="font-mono text-zinc-300">~40%</span>
            </div>
            <div className="flex gap-0.5 h-1.5">
              {Array.from({ length: 20 }).map((_, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-sm transition-all duration-700"
                  style={{
                    background: i < 8 ? "#DAFFDE" : "#27272a",
                    opacity: revealed ? 1 : 0,
                    transitionDelay: `${i * 30}ms`,
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ─ Card 4: Order Fill Probability ────────────────────────────── */}
      <div
        className={`
          relative overflow-hidden rounded-2xl p-6
          bg-[#111111] border border-zinc-800
          transition-all duration-700 delay-225
          ${revealed ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}
          hover:border-[#DEFF9A]/30 group
        `}
        style={{
          backgroundImage: `
            radial-gradient(circle at top right, rgba(222,255,154,0.08), transparent 60%),
            linear-gradient(135deg, #111111 0%, #0d0d0d 100%)
          `,
        }}
      >
        <div className="relative">
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg" style={{ background: "rgba(222,255,154,0.1)" }}>
                <ShieldCheck size={14} color="#DEFF9A" />
              </div>
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-zinc-400">
                Order Fill Probability
              </span>
            </div>
            <Activity size={12} color="#DEFF9A" className="animate-pulse" />
          </div>

          <div className="flex items-baseline gap-1 mb-1">
            <span className="text-5xl font-bold font-mono leading-none tabular-nums tracking-tight text-[#DEFF9A]">
              {kpis.orderFillProbabilityPct.toFixed(1)}
            </span>
            <span className="text-2xl font-bold text-zinc-500">%</span>
          </div>

          <div className="text-[10px] text-zinc-500 font-mono mt-3 leading-relaxed">
            구매력 초과 미발생률
            <br />
            <span className="text-zinc-600">
              → 24회 리밸런싱 중 {(100 - kpis.orderFillProbabilityPct).toFixed(0)}건 truncated
            </span>
          </div>

          {/* Defensive mode indicator */}
          <div className="mt-4 flex items-center gap-3 p-2 rounded-lg bg-zinc-950/50 border border-zinc-800">
            <AlertTriangle size={11} color="#FFC857" />
            <div className="flex-1 text-[9px]">
              <div className="text-zinc-400 font-mono">Defensive Mode</div>
              <div className="text-zinc-600 font-mono">
                {kpis.defensiveDaysPct.toFixed(1)}% 거래일
              </div>
            </div>
            <div
              className="text-xs font-mono font-bold"
              style={{ color: kpis.defensiveDaysPct > 5 ? "#FFC857" : "#DEFF9A" }}
            >
              {kpis.defensiveDaysPct > 5 ? "WATCH" : "OK"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════

function ErosionRow({ label, value, color, max, revealed }: {
  label: string; value: number; color: string; max: number; revealed: boolean;
}) {
  const pct = Math.min((Math.abs(value) / max) * 100, 100);
  return (
    <div>
      <div className="flex items-center justify-between text-[9px] mb-0.5">
        <span className="text-zinc-500">{label}</span>
        <span className="text-zinc-300 font-mono tabular-nums">
          -{fmtKrw(Math.abs(value))}
        </span>
      </div>
      <div className="h-1 bg-zinc-900 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-1000"
          style={{
            width: revealed ? `${pct}%` : "0%",
            background: color,
            opacity: 0.6,
          }}
        />
      </div>
    </div>
  );
}
