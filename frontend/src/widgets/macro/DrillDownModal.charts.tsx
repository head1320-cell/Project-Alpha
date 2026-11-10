"use client";
// 지표 흐름 창의 그림 — recharts 는 차트 파일에서만 import 한다(ADR 004 · 2026-11-10).
// 창(`DrillDownModal`) 자체가 `dynamic()` 으로 늦게 오므로 이 파일은 그 조각에 정적으로 따라온다(lazyChart 를 또 겹치지 않는다).
// 값은 호버 툴팁이 아니라 읽는 줄·표 쌍둥이에 있다(ADR 004 §2.4) — 처음 자리 = 마지막 달 · ←→ Home End · 마우스를 올려도 옮겨진다.
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, ReferenceDot, ReferenceLine } from "recharts";
import { ReadoutFrame, idxFromChartEvent, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { fmtNum } from "./cockpitParts";

/** 한 지표의 시계열 — 점선은 지난 5년 평균(서버 `mean_5y` · 없으면 그리지 않는다). */
export function DrillSeriesChart({ data, name, unit, mean5y }: { data: { t: string; v: number }[]; name: string; unit: string; mean5y: number | null | undefined }) {
  const anim = useChartAnimation();
  const rows: ReadRow[] = data.map((d) => ({ head: d.t, cells: [{ key: "v", label: name, text: [fmtNum(d.v), unit].filter(Boolean).join(" ") }] }));
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  const cur = idx >= 0 ? data[idx] : null;
  return (
    <ReadoutFrame id="drill-series" label={`${name} 흐름`} headLabel="달" rows={rows} idx={idx} onKeyDown={onKeyDown}>
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}
                 onMouseMove={(st) => { const i = idxFromChartEvent(st); if (i !== null) setIdx(i); }}>
        <defs><linearGradient id="mcgrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--tx-blue)" stopOpacity={0.24} /><stop offset="100%" stopColor="var(--tx-blue)" stopOpacity={0.02} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--tx-line)" vertical={false} />
        <XAxis dataKey="t" tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" minTickGap={24} />
        <YAxis tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" domain={["auto", "auto"]} width={48} />
        {mean5y != null && <ReferenceLine y={mean5y} stroke="var(--tx-mute)" strokeDasharray="3 3" />}
        <Area type="monotone" dataKey="v" stroke="var(--tx-blue)" strokeWidth={1.8} fill="url(#mcgrad)" isAnimationActive={anim} />
        {cur && <ReferenceLine x={cur.t} stroke="var(--tx-mute)" strokeWidth={1} />}
        {cur && Number.isFinite(cur.v) && <ReferenceDot x={cur.t} y={cur.v} r={4} fill="var(--tx-surface)" stroke="var(--tx-blue)" strokeWidth={2} />}
      </AreaChart>
    </ResponsiveContainer>
    </ReadoutFrame>
  );
}
