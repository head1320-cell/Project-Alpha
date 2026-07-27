"use client";

/**
 * shared/ui/feedback — 데이터 없이 렌더되는 피드백/표시 프리미티브.
 * ==========================================================================
 *  · Skeleton / SkeletonText / SkeletonCard / SkeletonTable
 *  · TickValue       — 수치 변경 시 0.6초 flash + tabular-nums
 *  · MetricCard      — 균질 KPI 카드
 *  · Sparkline       — 미니 SVG line
 *
 *  (RegimeBadge / useRegimeInfo 는 macroApi 의존이라 entities/macro 로 이동)
 *  (CommandPalette / CommandHint 는 삭제 — 도달 불가 코드였다. 커밋 메시지 참고)
 */

import { useEffect, useState, useRef } from "react";
import { TrendingUp, TrendingDown } from "lucide-react";

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
  // size 는 `string | number` 여야 한다 — lucide 아이콘의 시그니처가 그렇고, 이 프로젝트의
  // 아이콘은 전부 lucide 다. `number` 로 좁혀 두면 icon={Activity} 가 tsc 에서 거부된다.
  // (이 컴포넌트는 소비자가 0개였던 탓에 그 사실이 드러난 적이 없었다.)
  icon?: React.ComponentType<{ size?: string | number; style?: React.CSSProperties }>;
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
