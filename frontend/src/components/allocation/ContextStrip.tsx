"use client";
// 컨텍스트 스트립 — "포트폴리오를 짜기 전, 왜 이런 포지션을 잡는지"의 맥락 (Research OS ②)
//   좌: Current Regime 배지(실데이터, 매크로 탭과 캐시 키 공유 — 신규 fetch 0) + 권고 모드
//   우: 카나리 지표 4종(VIX·US10Y·HY Spread·10Y-2Y) — latest + z색 + 미니 스파크
// 결측은 "—" 정직 표기. 클릭 시 Macro Cockpit으로 연결.
import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { macroApi, REGIME_COLORS, zScoreColor, type RegimeState } from "@/lib/macroApi";
import { analysisApi, type MacroIndicator } from "@/lib/screenerApi";

const CANARY: { id: string; label: string }[] = [
  { id: "VIXCLS", label: "VIX" },
  { id: "DGS10", label: "US10Y" },
  { id: "BAMLH0A0HYM2", label: "HY SPD" },
  { id: "T10Y2Y", label: "10Y-2Y" },
];

function Spark({ values }: { values: number[] }) {
  const vals = values.filter((v) => Number.isFinite(v));
  if (vals.length < 3) return null;
  const w = 46; const h = 14;
  const min = Math.min(...vals); const max = Math.max(...vals);
  const range = max - min || 1;
  const pts = vals.map((v, i) =>
    `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / range) * (h - 4)).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="as-ctx-spark">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.1} opacity={0.55} />
    </svg>
  );
}

export function ContextStrip() {
  // 매크로 탭·대시보드와 동일 queryKey — react-query 캐시 공유(프리페치 포함)
  const regimeQ = useQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime().catch(() => null) });
  const dashQ = useQuery({ queryKey: ["macro", "dashboard"], queryFn: () => analysisApi.macroDashboard().catch(() => null) });

  const st = (regimeQ.data ?? null) as RegimeState | null;
  const kr = st?.markets?.kr ?? st;
  const rc = kr ? REGIME_COLORS[kr.regime] : null;
  const confPct = kr?.confidence != null ? Math.round(kr.confidence * (kr.confidence <= 1.5 ? 100 : 1)) : null;

  const byId = new Map<string, MacroIndicator>();
  (dashQ.data?.themes ?? []).forEach((t) => t.indicators.forEach((i) => byId.set(i.id, i)));

  return (
    <div className="as-ctx">
      <Link href="/macro" className="as-ctx-regime" title="Macro Cockpit 열기"
        style={rc ? { background: rc.bg, color: rc.fg, borderColor: rc.border } : undefined}>
        {kr ? <>CURRENT: {kr.regime} <b className="num">CONF {confPct}%</b></> : "REGIME —"}
      </Link>
      {st?.recommended_mode && (
        <span className="as-ctx-mode num" data-mode={st.recommended_mode}>{st.recommended_mode}</span>
      )}
      {st?.stress_score != null && (
        <span className="as-ctx-stress num" title="Stress Index (0~100)">
          STRESS {Math.round(st.stress_score)}
        </span>
      )}
      <span className="as-ctx-fill" />
      {CANARY.map(({ id, label }) => {
        const ind = byId.get(id);
        const color = ind ? zScoreColor(ind.z_score) : "var(--t-muted)";
        return (
          <span key={id} className="as-ctx-canary" style={{ color }}
            title={ind ? `${ind.name} · z ${ind.z_score?.toFixed(2) ?? "—"}` : `${label} — 데이터 없음`}>
            <em>{label}</em>
            <b className="num">{ind?.latest != null
              ? ind.latest.toFixed(Math.abs(ind.latest) >= 100 ? 0 : 2) : "—"}</b>
            {ind?.spark && <Spark values={ind.spark.slice(-24)} />}
          </span>
        );
      })}
    </div>
  );
}
