"use client";
// 국면 배지 + 국면 조회 훅.
// shared/ui/feedback.tsx에 있었지만 macroApi를 호출한다 — shared는 entity를 알아선 안 되므로
// 도메인을 아는 이 컴포넌트만 macro 엔티티로 올렸다(나머지 스켈레톤/카드류는 shared에 남음).

import { useEffect, useState } from "react";
import Link from "next/link";
import { Skeleton } from "@/shared/ui/feedback";
import { macroApi } from "./api";

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
