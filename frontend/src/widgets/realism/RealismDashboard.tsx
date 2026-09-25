"use client";

import { useState, useMemo, useEffect } from "react";
import {
  ArrowRight, Loader2, RefreshCw, Server, GitBranch, Maximize2,
} from "lucide-react";

import RealismToggle from "./RealismToggle";
import RealismKPICards from "./RealismKPIs";
import ComparativeEquityChart from "./ComparativeEquityChart";
import ErosionWaterfall from "./ErosionWaterfall";
import LiquidityMonitor from "./LiquidityMonitor";

import {
  MOCK_IDEAL,
  MOCK_REALITY,
  MOCK_CAPACITIES,
  computeRealismKPIs,
  computeErosionWaterfall,
  type RealismBacktestResult,
} from "@/entities/realism/data";

import { unavailableReason } from "@/entities/realism/unavailable";
import { multibacktestApi } from "@/entities/multibacktest";
import { API_BASE } from "@/shared/api/apiBase";

// ═══════════════════════════════════════════════════════════════════════════════

export default function RealismDashboard() {
  const [mode, setMode] = useState<"ideal" | "reality">("reality");
  const [ideal, setIdeal] = useState<RealismBacktestResult>(MOCK_IDEAL);
  const [reality, setReality] = useState<RealismBacktestResult>(MOCK_REALITY);
  const [loading, setLoading] = useState(false);
  const [useMockData, setUseMockData] = useState(true);
  // ★백엔드가 실패하면 그 사유를 보인다★ (BF) — 모의 수치를 실데이터로 위장하지 않는다.
  const [backendNote, setBackendNote] = useState<string | null>(null);

  // Derived data
  const kpis = useMemo(() => computeRealismKPIs(ideal, reality), [ideal, reality]);
  const waterfall = useMemo(() => computeErosionWaterfall(ideal, reality), [ideal, reality]);

  // Fetch from backend (optional)
  const fetchLiveData = async () => {
    setLoading(true);
    try {
      // ★등록된 전략으로 돌린다★ (BG6) — 예전에는 존재하지 않는 `[1, 2, 3]` 을
      // 하드코딩했다. 등록된 전략이 없으면 돌리지 않고 그렇게 말한다.
      const registered = await multibacktestApi.strategies(true);
      if (registered.length === 0) {
        setIdeal(MOCK_IDEAL);
        setReality(MOCK_REALITY);
        setUseMockData(true);
        setBackendNote(
          "등록된 전략이 없습니다 — 멀티전략 페이지(전략 등록)에서 완료된 백테스트 실행을 "
          + "등록하세요. 아래 수치는 모의 데이터 그대로입니다.");
        return;
      }
      const baseConfig = {
        strategy_ids: registered.map((s) => s.id),
        start_date: "2023-01-01",
        end_date: "2024-12-31",
        initial_capital: 10_000_000_000,
        // ★hrp★ — hrp_macro 는 R4 전까지 서버가 422 로 막는다(매크로 피드·국면 분류기 부재).
        allocation_method: "hrp",
        rebalance_policy: "monthly",
        macro_overlay_enabled: false,
      };

      const [idealRes, realityRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/multibacktest/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...baseConfig, save: false }),
        }).then((r) => r.json()).catch(() => null),

        fetch(`${API_BASE}/api/v1/realism/backtest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...baseConfig,
            enable_market_impact: true,
            enable_cash_yield: true,
            enable_buying_power_check: true,
            enable_regime_adaptive: true,
          }),
        }).then((r) => r.json()).catch(() => null),
      ]);

      // ★둘 다 성공할 때만 실데이터다★ (BF) — 예전에는 실패해도 `setUseMockData(false)`
      // 를 불러 모의 수치를 둔 채 배지만 "Live Backend" 로 바꿨고, 하나만 성공하면
      // 실·모의가 한 화면에 섞였다.
      if (idealRes?.success && realityRes?.success) {
        setIdeal(idealRes);
        setReality(realityRes);
        setUseMockData(false);
        setBackendNote(null);
      } else {
        setIdeal(MOCK_IDEAL);
        setReality(MOCK_REALITY);
        setUseMockData(true);
        setBackendNote(
          unavailableReason(idealRes) ?? unavailableReason(realityRes)
            ?? "백엔드가 결과를 내지 않았습니다 — 아래 수치는 모의 데이터 그대로입니다.",
        );
      }
    } catch (e) {
      console.error(e);
      setIdeal(MOCK_IDEAL);
      setReality(MOCK_REALITY);
      setUseMockData(true);
      setBackendNote("백엔드에 닿지 못했습니다 — 아래 수치는 모의 데이터 그대로입니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white" style={{ fontFamily: "Inter, sans-serif" }}>
      {/* ═══ Header ════════════════════════════════════════════════════ */}
      <header className="border-b border-zinc-900 bg-gradient-to-b from-[#0d0d0d] to-[#0a0a0a]">
        <div className="max-w-[1600px] mx-auto px-8 py-6">
          <div className="flex items-start justify-between mb-6">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-1 h-10 bg-gradient-to-b from-[#DEFF9A] to-[#DAFFDE] rounded-full" />
                <div>
                  <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
                    Realism Panel
                    <span className="text-xs font-mono text-zinc-500 font-normal bg-zinc-900 px-2 py-0.5 rounded">
                      v12.0
                    </span>
                  </h1>
                  <p className="text-[11px] text-zinc-500 mt-0.5 font-mono tracking-wide">
                    Bridging the Gap · Stage 11 Ideal ↔ Stage 12 Production Reality
                  </p>
                </div>
              </div>
            </div>

            {/* Right utilities */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800">
                <div
                  className={`w-2 h-2 rounded-full ${
                    useMockData ? "bg-[#FFC857]" : "bg-[#DEFF9A]"
                  }`}
                  style={{ boxShadow: `0 0 8px ${useMockData ? "#FFC857" : "#DEFF9A"}` }}
                />
                <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                  {useMockData ? "Mock Data" : "Live Backend"}
                </span>
              </div>

              <button
                onClick={fetchLiveData}
                disabled={loading}
                className="
                  flex items-center gap-2 px-3 py-1.5 rounded-lg
                  bg-zinc-900 hover:bg-zinc-800 border border-zinc-800
                  text-[11px] font-medium text-zinc-300 transition-colors
                  disabled:opacity-50 disabled:cursor-not-allowed
                "
              >
                {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                Fetch Live
              </button>
            </div>
          </div>

          {backendNote && (
            <p className="text-[11px] text-[#FFC857] font-mono mb-2" role="status">
              {backendNote}
            </p>
          )}

          {/* Master Toggle */}
          <div className="flex justify-center py-4">
            <RealismToggle mode={mode} onChange={setMode} />
          </div>
        </div>
      </header>

      {/* ═══ Main Content ════════════════════════════════════════════ */}
      <main className="max-w-[1600px] mx-auto px-8 py-8 space-y-8">
        {/* ─ Section 1: KPI Cards (CORE) ─────────────────────────────── */}
        <section>
          <SectionHeader
            title="Realism KPIs"
            subtitle="4 institutional-grade metrics quantifying the backtest-to-reality fidelity"
            badge="CORE"
          />
          <RealismKPICards kpis={kpis} mode={mode} />
        </section>

        {/* ─ Section 2: Comparative Equity ───────────────────────────── */}
        <section>
          <SectionHeader
            title="Comparative Equity Curves"
            subtitle="Side-by-side ideal vs reality progression with macro regime overlay"
          />
          <ComparativeEquityChart ideal={ideal} reality={reality} mode={mode} />
        </section>

        {/* ─ Section 3: Erosion Waterfall ────────────────────────────── */}
        <section>
          <SectionHeader
            title="Alpha Erosion Waterfall"
            subtitle="Step-by-step decomposition: Ideal return → friction factors → Realistic outcome"
          />
          <ErosionWaterfall steps={waterfall} />
        </section>

        {/* ─ Section 4: Liquidity Monitor ────────────────────────────── */}
        <section>
          <SectionHeader
            title="Liquidity & Capacity Monitor"
            subtitle="Real-time per-strategy capacity utilization vs ADV thresholds"
          />
          <LiquidityMonitor capacities={MOCK_CAPACITIES} />
        </section>

        {/* ─ Footer: Tech specs ──────────────────────────────────────── */}
        <section className="pt-8 border-t border-zinc-900">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-[10px] font-mono">
            <TechSpec
              icon={Server}
              label="Backend"
              values={["Stage 11 (Ideal)", "Stage 12 (Reality)"]}
            />
            <TechSpec
              icon={GitBranch}
              label="API Routes"
              values={["/multibacktest/run", "/realism/backtest"]}
            />
            <TechSpec
              icon={Maximize2}
              label="Realism Hooks"
              values={["Market Impact · Cash Yield", "Buying Power · Capacity · Regime"]}
            />
            <TechSpec
              icon={ArrowRight}
              label="Next Stage"
              values={["Stage 13 — Live Trading", "KIS API Integration"]}
            />
          </div>
        </section>
      </main>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════

function SectionHeader({ title, subtitle, badge }: {
  title: string; subtitle: string; badge?: string;
}) {
  return (
    <div className="mb-4 flex items-end justify-between">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <h2 className="text-base font-bold text-white tracking-wide">
            {title}
          </h2>
          {badge && (
            <span
              className="px-1.5 py-0.5 rounded text-[8px] font-bold font-mono uppercase tracking-widest"
              style={{
                background: "rgba(222,255,154,0.1)",
                color: "#DEFF9A",
                border: "1px solid rgba(222,255,154,0.3)",
              }}
            >
              {badge}
            </span>
          )}
        </div>
        <p className="text-[11px] text-zinc-500 font-mono">{subtitle}</p>
      </div>
    </div>
  );
}

function TechSpec({ icon: Icon, label, values }: {
  icon: any; label: string; values: string[];
}) {
  return (
    <div className="p-3 rounded-lg bg-[#0d0d0d] border border-zinc-900">
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={10} className="text-[#DEFF9A]" />
        <span className="text-[9px] uppercase tracking-widest text-zinc-500 font-bold">
          {label}
        </span>
      </div>
      {values.map((v, i) => (
        <div key={i} className="text-zinc-400 text-[10px] leading-relaxed">
          {v}
        </div>
      ))}
    </div>
  );
}
