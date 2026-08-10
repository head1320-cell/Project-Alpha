"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// DrillDownModal — 지표 36개월 시계열 + 통계 (cockpitParts 에서 분리, Phase A)
//
// ★왜 파일을 나눴나★
// `cockpitParts.tsx` 는 HoldingsDonut·SignalBadge 등 **항상 쓰이는** 조각을 담고 있어
// /macro 첫 로드에 통째로 들어간다. Radix Dialog 를 쓰는 이 창이 그 안에 있으면
// `next/dynamic` 으로 떼어낼 방법이 없다 — 모듈이 이미 로드되기 때문이다(실측 +20 kB).
// 기본이 '닫힘' 인 창은 첫 로드에 있을 이유가 없으므로 자기 모듈로 내보낸다.
//
// 이 창은 파일명이 `*Modal.tsx` 가 아니어서 파일명 기반 감사 목록에서 빠져 있었고,
// 그래서 대화상자 의미론이 없다는 사실도 함께 묻혀 있었다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import { X } from "lucide-react";
import { zScoreColor, type MacroSeries } from "@/entities/macro/api";
import { Dialog, DialogContent, DialogTitle } from "@/shared/ui/shadcn/dialog";
import { fmtNum, fmtPct, fmtZ } from "./cockpitParts";
import { useChartAnimation } from "@/shared/ui/chartStyle";

const TIP_STYLE = { background: "#fff", border: "1px solid var(--t-border)", borderRadius: 2, fontSize: 11, fontFamily: "var(--t-mono, monospace)" };

export function DrillDownModal({ series, loading, onClose }: { series: MacroSeries | null; loading: boolean; onClose: () => void }) {
  const anim = useChartAnimation();
  const data = series ? series.timestamps.map((t, idx) => ({ t: t.length > 6 ? t.slice(2, 7) : t, v: series.values[idx] })) : [];
  // ★Radix Dialog 로 옮겼다 (Phase A)★ 이전에는 대화상자 의미론이 하나도 없었다.
  // 이 창은 파일명이 `*Modal.tsx` 가 아니라 감사의 파일명 기반 목록에서 빠졌었다 —
  // 같은 결함이 세 번째로 있었던 셈이다.
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="mc-modal" aria-describedby={undefined}>
        <DialogTitle className="sr-only">{series?.name ?? "지표 상세"}</DialogTitle>
        <button className="mc-modal-x" onClick={onClose} aria-label="닫기"><X size={16} /></button>
        {loading && <div className="mc-modal-load">시계열 불러오는 중…</div>}
        {!loading && !series && <div className="mc-modal-load">데이터를 불러올 수 없습니다.</div>}
        {!loading && series && (
          <>
            <div className="mc-modal-h">
              <div><b>{series.name}</b><span>{series.indicator} · {series.source}</span></div>
              <div className="mc-modal-latest"><b style={{ color: zScoreColor(series.z_score) }}>{fmtNum(series.latest)}</b><em>{series.unit}</em></div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
                <defs><linearGradient id="mcgrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--t-accent)" stopOpacity={0.28} /><stop offset="100%" stopColor="var(--t-accent)" stopOpacity={0.02} /></linearGradient></defs>
                <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" vertical={false} />
                <XAxis dataKey="t" tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" minTickGap={24} />
                <YAxis tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" domain={["auto", "auto"]} width={46} />
                <Tooltip contentStyle={TIP_STYLE} />
                {series.mean_5y != null && <ReferenceLine y={series.mean_5y} stroke="var(--t-muted)" strokeDasharray="3 3" />}
                <Area type="monotone" dataKey="v" stroke="var(--t-accent)" strokeWidth={1.6} fill="url(#mcgrad)" isAnimationActive={anim} />
              </AreaChart>
            </ResponsiveContainer>
            <div className="mc-modal-stats">
              {[["최근값", `${fmtNum(series.latest)} ${series.unit}`], ["5Y 평균", fmtNum(series.mean_5y)], ["5Y 표준편차", fmtNum(series.std_5y)], ["Z-Score", fmtZ(series.z_score)], ["백분위", series.percentile != null ? `${Math.round(series.percentile)}` : "—"], ["전년대비", fmtPct(series.yoy)]].map(([k, v]) => (
                <div key={k} className="mc-modal-stat"><span>{k}</span><b>{v}</b></div>
              ))}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
