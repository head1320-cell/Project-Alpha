"use client";

/**
 * Phase 5 Common Components
 * ==========================================================================
 *  · Skeleton / SkeletonText / SkeletonCard / SkeletonTable
 *  · TickValue       — 수치 변경 시 0.6초 flash + tabular-nums
 *  · RegimeBadge     — Phase 4 Stress 기반 모드 표시 (헤더)
 *  · MetricCard      — 균질 KPI 카드
 *  · Sparkline       — 미니 SVG line
 *  · CommandPalette  — Ctrl+K 전역 검색 (자체 구현)
 *  · CommandHint     — TopNav ⌘K 힌트
 */

import { useEffect, useState, useRef, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Search, Home, BarChart3, Shield, Calculator, Diamond, Sparkles, Globe,
  Wrench, ArrowRight, Hash, Command, CheckCircle2,
  TrendingUp, TrendingDown, Activity,
} from "lucide-react";
import { macroApi } from "@/lib/macroApi";

// ─── Skeleton ─────────────────────────────────────────────────────────────────

export function Skeleton({ className = "", style = {} }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} />;
}

export function SkeletonText({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="h-3" style={{ width: `${85 - i * 8}%` }} />
      ))}
    </div>
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`p-4 border border-default rounded-md ${className}`}>
      <Skeleton className="h-3 mb-3" style={{ width: "40%" }} />
      <Skeleton className="h-7 mb-2" style={{ width: "60%" }} />
      <Skeleton className="h-2" style={{ width: "80%" }} />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <Skeleton className="h-2 flex-grow" />
          <Skeleton className="h-2" style={{ width: "60px" }} />
          <Skeleton className="h-2" style={{ width: "40px" }} />
        </div>
      ))}
    </div>
  );
}

// ─── TickValue ────────────────────────────────────────────────────────────────

export function TickValue({
  value, format = "number", digits = 2, className = "", suffix = "",
}: {
  value: number | null | undefined;
  format?: "number" | "currency" | "percent";
  digits?: number;
  className?: string;
  suffix?: string;
}) {
  const [flash, setFlash] = useState<"" | "bull" | "bear">("");
  const prevRef = useRef<number | null>(null);

  useEffect(() => {
    if (value == null) return;
    const prev = prevRef.current;
    if (prev != null && prev !== value) {
      setFlash(value > prev ? "bull" : "bear");
      const t = setTimeout(() => setFlash(""), 600);
      prevRef.current = value;
      return () => clearTimeout(t);
    }
    prevRef.current = value;
  }, [value]);

  if (value == null) return <span className={className}>—</span>;

  const formatted =
    format === "currency" ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) :
    format === "percent"  ? `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%` :
    value.toLocaleString(undefined, { maximumFractionDigits: digits });

  const flashCls = flash === "bull" ? "animate-flash-bull" : flash === "bear" ? "animate-flash-bear" : "";
  return <span className={`tabular-nums ${flashCls} ${className}`}>{formatted}{suffix}</span>;
}

// ─── RegimeBadge ────────────────────────────────────────────────────────────────

interface RegimeInfo { regime: string; mode: "NORMAL" | "CAUTIOUS" | "DEFENSIVE"; stress: number; }

export function useRegimeInfo() {
  const [info, setInfo] = useState<RegimeInfo | null>(null);
  useEffect(() => {
    const load = async () => {
      try {
        const r = await macroApi.regime();
        setInfo({ regime: r.regime, mode: r.recommended_mode, stress: r.stress_score });
      } catch {}
    };
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);
  return info;
}

export function RegimeBadge() {
  const info = useRegimeInfo();
  if (!info) return <Skeleton className="h-5" style={{ width: 90 }} />;

  const color =
    info.mode === "DEFENSIVE" ? { bg: "#fee2e2", fg: "#b91c1c", dot: "#dc2626", glow: "#dc2626" } :
    info.mode === "CAUTIOUS"  ? { bg: "#fef3c7", fg: "#a16207", dot: "#f59e0b", glow: "#f59e0b" } :
                                  { bg: "#dcfce7", fg: "#15803d", dot: "#22c55e", glow: "#22c55e" };

  return (
    <Link
      href="/macro"
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-mono text-[10px] font-bold transition hover:scale-105"
      style={{ background: color.bg, color: color.fg }}
      title={`현재 시장 국면 — Stress ${info.stress.toFixed(0)} / 100`}
    >
      <span
        className="inline-block rounded-full animate-pulse-glow"
        style={{ width: 6, height: 6, background: color.dot, ["--glow-color" as string]: `${color.glow}66` } as React.CSSProperties}
      />
      <span className="uppercase tracking-wider">{info.regime}</span>
      <span className="opacity-60">·</span>
      <span>{info.stress.toFixed(0)}</span>
    </Link>
  );
}

// ─── MetricCard ────────────────────────────────────────────────────────────────

export function MetricCard({
  label, value, unit = "", delta, sublabel, color = "#1200ff", icon: Icon,
  loading = false, format = "number", digits = 2,
}: {
  label: string;
  value: number | string | null;
  unit?: string;
  delta?: number | null;
  sublabel?: string;
  color?: string;
  icon?: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  loading?: boolean;
  format?: "number" | "currency" | "percent";
  digits?: number;
}) {
  if (loading) return <SkeletonCard />;
  return (
    <div className="rounded-md border border-default bg-white p-3 hover:shadow-sm transition" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="flex items-center justify-between mb-1">
        <div className="text-[10px] uppercase tracking-wider text-secondary font-medium">{label}</div>
        {Icon && <Icon size={12} style={{ color, opacity: 0.6 }} />}
      </div>
      <div className="text-2xl font-bold text-primary tabular-nums">
        {typeof value === "number" ? <TickValue value={value} format={format} digits={digits} suffix={unit} /> : <>{value ?? "—"}{unit}</>}
      </div>
      <div className="flex items-center gap-2 mt-1 min-h-[14px]">
        {delta != null && (
          <span className="text-[10px] font-mono tabular-nums flex items-center gap-0.5" style={{ color: delta >= 0 ? "#16a34a" : "#dc2626" }}>
            {delta >= 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {delta >= 0 ? "+" : ""}{delta.toFixed(2)}%
          </span>
        )}
        {sublabel && <span className="text-[10px] text-secondary">{sublabel}</span>}
      </div>
    </div>
  );
}

// ─── Sparkline ────────────────────────────────────────────────────────────────

export function Sparkline({
  data, width = 80, height = 24, color = "#22c55e", className = "",
}: {
  data: number[]; width?: number; height?: number; color?: string; className?: string;
}) {
  if (!data || data.length < 2) return <span className={`inline-block ${className}`} style={{ width, height }} />;
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1;
  const step = width / (data.length - 1);
  const points = data.map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`).join(" ");
  const isUp = data[data.length - 1] >= data[0];
  const stroke = color === "auto" ? (isUp ? "#16a34a" : "#dc2626") : color;
  return (
    <span className={`sparkline inline-block ${className}`}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <polyline points={points} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    </span>
  );
}

// ─── Command Palette ────────────────────────────────────────────────────────────

interface CommandItem {
  id: string; label: string; description?: string; href: string;
  category: "메인" | "스크리너" | "분석" | "운영"; icon: React.ElementType;
}

const ALL_COMMANDS: CommandItem[] = [
  { id: "home", label: "홈 대시보드", href: "/", category: "메인", icon: Home },
  { id: "builder", label: "전략 빌더", href: "/builder", category: "메인", icon: Wrench },
  { id: "backtest", label: "백테스팅", href: "/backtest", category: "메인", icon: BarChart3 },
  { id: "screener", label: "종목 스크리너", href: "/screener", category: "메인", icon: Diamond },
  { id: "risk", label: "리스크 도구", href: "/risk-tools", category: "메인", icon: Shield },
  { id: "deriv", label: "파생상품 평가", href: "/derivatives", category: "메인", icon: Calculator },
  { id: "macro", label: "매크로 레이더", href: "/macro", category: "메인", icon: Globe },
  { id: "insights", label: "AI 인사이트", href: "/insights", category: "메인", icon: Sparkles },
  { id: "scr-top", label: "Top 저평가 종목", href: "/screener?sort=composite", category: "스크리너", icon: TrendingUp },
  { id: "scr-div", label: "고배당주 필터", href: "/screener?filter=dividend", category: "스크리너", icon: Hash },
  { id: "scr-qual", label: "재무 우량주", href: "/screener?filter=quality", category: "스크리너", icon: CheckCircle2 },
  { id: "ai-stock", label: "AI 종목 분석", href: "/insights?d=stock", category: "분석", icon: Sparkles },
  { id: "ai-portfolio", label: "AI 포트폴리오 보고서", href: "/insights?d=portfolio", category: "분석", icon: Sparkles },
  { id: "ai-macro", label: "AI 매크로 브리핑", href: "/insights?d=macro", category: "분석", icon: Sparkles },
  { id: "ai-ops", label: "AI 운영 사건 분석", href: "/insights?d=operations", category: "분석", icon: Sparkles },
  { id: "live", label: "실거래 콕핏", href: "/admin/live-trading", category: "운영", icon: Activity },
  { id: "multi-bt", label: "Multi-Backtest", href: "/admin/multi-backtest", category: "운영", icon: BarChart3 },
  { id: "realism", label: "Realism Engine", href: "/admin/realism", category: "운영", icon: Shield },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") { e.preventDefault(); setOpen(o => !o); }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) { setTimeout(() => inputRef.current?.focus(), 30); setQuery(""); setActiveIdx(0); }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ALL_COMMANDS;
    return ALL_COMMANDS.filter(c => (c.label + " " + (c.description || "") + " " + c.href).toLowerCase().includes(q));
  }, [query]);

  const grouped = useMemo(() => {
    const g: Record<string, CommandItem[]> = {};
    filtered.forEach(c => { g[c.category] = g[c.category] || []; g[c.category].push(c); });
    return g;
  }, [filtered]);

  const select = (cmd: CommandItem) => { setOpen(false); router.push(cmd.href); };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (filtered[activeIdx]) select(filtered[activeIdx]); }
  };

  if (!open) return null;
  let runningIdx = -1;

  return (
    <div className="cmd-palette-backdrop" onClick={() => setOpen(false)}>
      <div className="cmd-palette" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-default">
          <Search size={16} className="text-secondary" />
          <input
            ref={inputRef} value={query}
            onChange={e => { setQuery(e.target.value); setActiveIdx(0); }}
            onKeyDown={onKeyDown}
            placeholder="페이지, 종목, 도구 검색..."
            className="flex-grow text-sm outline-none bg-transparent text-primary"
          />
          <kbd className="text-[10px] font-mono px-1.5 py-0.5 bg-light rounded text-secondary border border-default">ESC</kbd>
        </div>
        <div className="max-h-[420px] overflow-y-auto">
          {filtered.length === 0 && <div className="p-6 text-center text-sm text-secondary">결과 없음</div>}
          {Object.entries(grouped).map(([category, items]) => (
            <div key={category}>
              <div className="px-4 pt-3 pb-1 text-[9px] uppercase tracking-wider text-secondary font-bold">{category}</div>
              {items.map(cmd => {
                runningIdx++;
                const isActive = runningIdx === activeIdx;
                const Icon = cmd.icon;
                return (
                  <button
                    key={cmd.id} onClick={() => select(cmd)} onMouseEnter={() => setActiveIdx(runningIdx)}
                    data-active={isActive ? "true" : "false"}
                    className="cmd-palette-item w-full flex items-center gap-3 px-4 py-2.5 text-left transition"
                  >
                    <div className="w-7 h-7 rounded bg-light flex items-center justify-center text-secondary flex-shrink-0"><Icon size={14} /></div>
                    <div className="flex-grow min-w-0"><div className="text-sm font-medium text-primary truncate">{cmd.label}</div></div>
                    <ArrowRight size={12} className="text-secondary flex-shrink-0" />
                  </button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="px-4 py-2 border-t border-default text-[10px] text-secondary flex items-center gap-3 font-mono">
          <span><kbd className="px-1 bg-light rounded">↑↓</kbd> 이동</span>
          <span><kbd className="px-1 bg-light rounded">↵</kbd> 선택</span>
          <span className="ml-auto">{filtered.length} 항목</span>
        </div>
      </div>
    </div>
  );
}

export function CommandHint() {
  return (
    <div
      className="hidden md:flex items-center gap-1 text-[10px] font-mono text-white/60 px-2 py-1 rounded border border-white/20 hover:border-white/40 transition cursor-pointer"
      onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}
      title="명령 팔레트 열기 (Ctrl+K)"
    >
      <Command size={10} /><span>K</span>
    </div>
  );
}
