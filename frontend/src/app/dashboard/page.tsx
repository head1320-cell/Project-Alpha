"use client";

/**
 * Command Center — 통합 인베스트먼트 대시보드 (Phase 5)
 * ==========================================================================
 * 플랫폼 진입 시 모든 엔진의 핵심 요약을 한눈에:
 *   · MacroRegimeStrip — Phase 4 국면 + RF + Stress
 *   · AIBriefingFeed   — Phase 3 일일 브리핑 (뉴스 피드)
 *   · TopPicksGrid     — Phase 2 스크리너 Top 3
 *   · LiveStatusBar    — Stage 13 실거래 상태
 *   · QuickNav         — 7개 카테고리 진입 그리드
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Sparkles, Globe, Diamond, Activity, Shield, Wrench, BarChart3,
  Calculator, ArrowRight, Loader2, AlertTriangle, CheckCircle2, Command,
} from "lucide-react";
import { Skeleton, SkeletonText } from "@/components/common";
import { macroApi, type RegimeState, REGIME_COLORS } from "@/lib/macroApi";
import { screenerApi, type ScreenerItem, verdictColor, formatPct } from "@/lib/screenerApi";
import { narrativeApi, type NarrativeResponse } from "@/lib/narrativeApi";
import { API_BASE } from "@/lib/apiBase";

export default function CommandCenter() {
  return (
    <div className="cockpit">
      <div className="max-w-[1600px] mx-auto px-4 lg:px-8 py-6 space-y-5">
        <HeroStrip />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2"><MacroRegimeStrip /></div>
          <LiveStatusBar />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2"><AIBriefingFeed /></div>
          <TopPicksGrid />
        </div>
        <QuickNav />
      </div>
    </div>
  );
}

function HeroStrip() {
  return (
    <div className="flex items-center justify-between flex-wrap gap-4 animate-fade-in">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <div className="w-2 h-2 rounded-full animate-pulse-glow" style={{ background: "#22c55e", ["--glow-color" as string]: "rgba(34,197,94,0.4)" } as React.CSSProperties} />
          <span className="text-[11px] font-mono uppercase tracking-widest" style={{ color: "var(--cockpit-muted)" }}>
            FICC Quant Platform · Command Center
          </span>
        </div>
        <h1 className="text-2xl lg:text-3xl font-bold" style={{ color: "var(--cockpit-text)" }}>
          통합 인베스트먼트 대시보드
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--cockpit-muted)" }}>
          Valuation · Screener · AI Narrative · Macro — 149개 API가 단일 콕핏에 통합되었습니다.
        </p>
      </div>
      <button
        onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}
        className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition hover:scale-105"
        style={{ background: "var(--cockpit-card)", border: "1px solid var(--cockpit-border)", color: "var(--cockpit-muted)" }}
      >
        <Command size={14} />
        <span className="font-mono text-xs">⌘K 로 빠른 검색</span>
      </button>
    </div>
  );
}

function MacroRegimeStrip() {
  const [state, setState] = useState<RegimeState | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    macroApi.regime().then(setState).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="cockpit-card p-5">
        <Skeleton className="h-4 mb-4" style={{ width: 120 }} />
        <div className="grid grid-cols-4 gap-4">{[0,1,2,3].map(i => <Skeleton key={i} className="h-16" />)}</div>
      </div>
    );
  }
  if (!state) return <div className="cockpit-card p-5 text-sm" style={{ color: "var(--cockpit-muted)" }}>매크로 데이터 로드 실패</div>;

  const rc = REGIME_COLORS[state.regime];
  const modeColor = state.recommended_mode === "DEFENSIVE" ? "#ef4444" : state.recommended_mode === "CAUTIOUS" ? "#f59e0b" : "#22c55e";

  return (
    <Link href="/macro" className="block">
      <div className="cockpit-card p-5 animate-fade-in" style={{ borderTop: `2px solid ${modeColor}` }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Globe size={15} style={{ color: "#0891b2" }} />
            <span className="text-sm font-bold" style={{ color: "var(--cockpit-text)" }}>매크로 국면</span>
          </div>
          <span className="px-2.5 py-1 rounded-full text-[11px] font-bold" style={{ background: `${rc.fg}22`, color: rc.fg }}>{state.regime}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <CockpitStat label="권고 모드" value={state.recommended_mode} color={modeColor} mono />
          <CockpitStat label="Stress Index" value={state.stress_score.toFixed(0)} suffix=" / 100" color={state.stress_score >= 60 ? "#ef4444" : state.stress_score >= 40 ? "#f59e0b" : "#22c55e"} />
          <CockpitStat label="Risk-Free (10Y)" value={state.dynamic_risk_free_rate != null ? (state.dynamic_risk_free_rate * 100).toFixed(2) : "—"} suffix="%" color="#22c55e" />
          <CockpitStat label="Yield Curve" value={state.yield_inversion ? "역전" : "정상"} suffix={state.inversion_severity != null ? ` ${state.inversion_severity.toFixed(0)}bp` : ""} color={state.yield_inversion ? "#ef4444" : "#22c55e"} mono />
        </div>
        <div className="mt-4 pt-3 text-xs flex items-center gap-1.5" style={{ borderTop: "1px solid var(--cockpit-border)", color: "var(--cockpit-muted)" }}>
          <span style={{ color: rc.fg }}>{state.description}</span>
          <ArrowRight size={11} className="ml-auto" />
        </div>
      </div>
    </Link>
  );
}

function CockpitStat({ label, value, suffix = "", color, mono = false }: { label: string; value: string; suffix?: string; color: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--cockpit-muted)" }}>{label}</div>
      <div className={`text-lg font-bold ${mono ? "" : "tabular-nums"}`} style={{ color }}>{value}<span className="text-xs opacity-70">{suffix}</span></div>
    </div>
  );
}

function LiveStatusBar() {
  const [health, setHealth] = useState<{ ok: boolean; mode?: string; kill?: string } | null>(null);

  useEffect(() => {
    const API = API_BASE;
    fetch(`${API}/api/v1/live/health`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setHealth(d ? { ok: true, mode: d.mode || "SHADOW", kill: d.kill_switch_status || "INACTIVE" } : { ok: false }))
      .catch(() => setHealth({ ok: false }));
  }, []);

  const killActive = health?.kill && health.kill !== "INACTIVE";

  return (
    <Link href="/admin/live-trading" className="block">
      <div className="cockpit-card p-5 h-full animate-fade-in">
        <div className="flex items-center gap-2 mb-4">
          <Activity size={15} style={{ color: killActive ? "#ef4444" : "#22c55e" }} />
          <span className="text-sm font-bold" style={{ color: "var(--cockpit-text)" }}>실거래 상태</span>
        </div>
        {!health ? <SkeletonText lines={3} /> : (
          <div className="space-y-3">
            <StatusRow label="API 연결" value={health.ok ? "연결됨" : "오프라인"} ok={health.ok} />
            <StatusRow label="거래 모드" value={health.mode || "SHADOW"} ok={true} neutral />
            <StatusRow label="Kill Switch" value={killActive ? "🚨 발동" : "정상"} ok={!killActive} />
          </div>
        )}
        <div className="mt-4 pt-3 text-[11px] flex items-center" style={{ borderTop: "1px solid var(--cockpit-border)", color: "var(--cockpit-muted)" }}>
          콕핏 열기 <ArrowRight size={11} className="ml-auto" />
        </div>
      </div>
    </Link>
  );
}

function StatusRow({ label, value, ok, neutral = false }: { label: string; value: string; ok: boolean; neutral?: boolean }) {
  const color = neutral ? "#94a3b8" : ok ? "#22c55e" : "#ef4444";
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs" style={{ color: "var(--cockpit-muted)" }}>{label}</span>
      <span className="flex items-center gap-1.5 text-sm font-medium" style={{ color }}>
        {!neutral && (ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />)}{value}
      </span>
    </div>
  );
}

function AIBriefingFeed() {
  const [briefing, setBriefing] = useState<NarrativeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const sample = {
      operations: { mode: "PAPER", orders_submitted: 23, orders_filled: 21, kill_switch_status: "INACTIVE" },
      market: { regime: "Reflation", systemic_risk_score: 46, vix: 16.8 },
      portfolio: { nav_krw: 100_840_000, daily_pnl_krw: 840_000, n_positions: 8 },
      alerts: [{ severity: "INFO", message: "리밸런싱 완료", time: "09:30" }],
    };
    narrativeApi.daily(sample).then(setBriefing).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const preview = briefing?.content ? briefing.content.replace(/[#*`>|-]/g, "").replace(/\n{2,}/g, "\n").slice(0, 600) : "";

  return (
    <div className="cockpit-card p-5 animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Sparkles size={15} style={{ color: "#8b5cf6" }} />
          <span className="text-sm font-bold" style={{ color: "var(--cockpit-text)" }}>AI 일일 브리핑</span>
          {briefing?.cached && <span className="text-[9px] px-1.5 py-0.5 rounded font-mono" style={{ background: "rgba(148,163,184,0.2)", color: "#94a3b8" }}>cached</span>}
        </div>
        <Link href="/insights?d=daily" className="text-[11px] flex items-center gap-1 transition hover:opacity-80" style={{ color: "#8b5cf6" }}>전체 보기 <ArrowRight size={11} /></Link>
      </div>
      {loading ? <SkeletonText lines={6} /> : (
        <div className="text-sm leading-relaxed whitespace-pre-line" style={{ color: "var(--cockpit-muted)" }}>
          {preview}{preview && <span style={{ color: "#8b5cf6" }}>... </span>}
        </div>
      )}
      {briefing && !loading && (
        <div className="mt-4 pt-3 text-[10px] font-mono flex items-center gap-3" style={{ borderTop: "1px solid var(--cockpit-border)", color: "var(--cockpit-muted)" }}>
          <span>{briefing.model}</span><span>·</span><span>{briefing.total_tokens} tokens</span>
          {briefing.cost_krw > 0 && <><span>·</span><span>{briefing.cost_krw.toFixed(1)}원</span></>}
          <span className="ml-auto">{new Date(briefing.timestamp).toLocaleString("ko-KR")}</span>
        </div>
      )}
    </div>
  );
}

function TopPicksGrid() {
  const [picks, setPicks] = useState<ScreenerItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    screenerApi.run({ universe: "kospi50", limit: 3, sort_by: "composite_score" })
      .then(r => setPicks(r.items)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  return (
    <div className="cockpit-card p-5 animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Diamond size={15} style={{ color: "#22c55e" }} />
          <span className="text-sm font-bold" style={{ color: "var(--cockpit-text)" }}>오늘의 저평가 Top 3</span>
        </div>
        <Link href="/screener" className="text-[11px] flex items-center gap-1 transition hover:opacity-80" style={{ color: "#22c55e" }}>전체 <ArrowRight size={11} /></Link>
      </div>
      {loading ? (
        <div className="space-y-3">{[0,1,2].map(i => <Skeleton key={i} className="h-14" />)}</div>
      ) : picks.length === 0 ? (
        <div className="text-sm py-4 text-center" style={{ color: "var(--cockpit-muted)" }}>데이터 없음</div>
      ) : (
        <div className="space-y-2">
          {picks.map((p, i) => {
            const vc = verdictColor(p.verdict);
            return (
              <Link key={p.stock_code} href={`/screener?stock=${p.stock_code}`}>
                <div className="flex items-center gap-3 p-2.5 rounded-lg transition hover:scale-[1.02]" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--cockpit-border)" }}>
                  <div className="w-7 h-7 rounded flex items-center justify-center text-xs font-bold flex-shrink-0" style={{ background: i === 0 ? "rgba(251,191,36,0.2)" : "rgba(148,163,184,0.15)", color: i === 0 ? "#fbbf24" : "#94a3b8" }}>{i + 1}</div>
                  <div className="flex-grow min-w-0">
                    <div className="text-sm font-bold truncate" style={{ color: "var(--cockpit-text)" }}>{p.corp_name}</div>
                    <div className="text-[10px] font-mono" style={{ color: "var(--cockpit-muted)" }}>{p.stock_code}</div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="text-sm font-bold tabular-nums" style={{ color: "#22c55e" }}>{p.composite_score.toFixed(1)}</div>
                    <div className="text-[10px] font-mono tabular-nums" style={{ color: vc.fg }}>{formatPct(p.gap_pct, 1)}</div>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

const NAV_ITEMS = [
  { label: "전략 빌더", href: "/builder", icon: Wrench, color: "#6366f1", desc: "DAG 비주얼 빌더" },
  { label: "백테스팅", href: "/backtest", icon: BarChart3, color: "#22c55e", desc: "PIT-safe 검증" },
  { label: "스크리너", href: "/screener", icon: Diamond, color: "#16a34a", desc: "RIM·DCF·DDM" },
  { label: "리스크 도구", href: "/risk-tools", icon: Shield, color: "#ef4444", desc: "VaR · 프론티어" },
  { label: "파생상품", href: "/derivatives", icon: Calculator, color: "#fbbf24", desc: "옵션 · XVA" },
  { label: "매크로", href: "/macro", icon: Globe, color: "#0891b2", desc: "4-Quadrant" },
  { label: "AI 인사이트", href: "/insights", icon: Sparkles, color: "#8b5cf6", desc: "6 도메인 분석" },
];

function QuickNav() {
  return (
    <div className="animate-fade-in-slow">
      <div className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--cockpit-muted)" }}>전체 도구</div>
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {NAV_ITEMS.map(item => {
          const Icon = item.icon;
          return (
            <Link key={item.href} href={item.href}>
              <div className="cockpit-card p-4 h-full">
                <Icon size={18} style={{ color: item.color }} />
                <div className="text-sm font-bold mt-2" style={{ color: "var(--cockpit-text)" }}>{item.label}</div>
                <div className="text-[10px] mt-0.5" style={{ color: "var(--cockpit-muted)" }}>{item.desc}</div>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
