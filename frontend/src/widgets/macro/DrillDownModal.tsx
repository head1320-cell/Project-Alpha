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
// BU5b: 실패(요청 오류)와 빈 시계열을 가른다 — 실패는 창 안 alert + [다시 시도]. 통계 이름은 한국어(σ·z 풀이),
//   최근 값은 수준 색이 아니라 잉크(색으로 판단하지 않는다) · 선은 한 계열 강조색 · 툴팁 글꼴은 고정폭이 아니다.
import React from "react";
import { X } from "lucide-react";
import type { MacroSeries } from "@/entities/macro/api";
import { Dialog, DialogContent, DialogTitle } from "@/shared/ui/shadcn/dialog";
import { Notice } from "@/shared/ui/tx";
import { fmtNum, fmtPct, fmtZ } from "./cockpitParts";
import { DrillSeriesChart } from "./DrillDownModal.charts";   // recharts 는 차트 파일에서만(ADR 004) — 이 창이 이미 dynamic() 이라 정적으로 가져온다

export function DrillDownModal({ series, loading, failed, onRetry, onClose }: { series: MacroSeries | null; loading: boolean; failed?: boolean; onRetry?: () => void; onClose: () => void }) {
  const data = series ? series.timestamps.map((t, idx) => ({ t: t.length > 6 ? t.slice(0, 7).replace("-", ".") : t, v: series.values[idx] })) : [];
  // ★Radix Dialog 로 옮겼다 (Phase A)★ 이전에는 대화상자 의미론이 하나도 없었다.
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="mc-modal" aria-describedby={undefined}>
        <DialogTitle className="sr-only">{series?.name ?? "지표 흐름"}</DialogTitle>
        <button type="button" className="mc-modal-x" onClick={onClose} aria-label="닫기"><X size={16} /></button>
        {loading && <div className="mc-modal-load">36개월 흐름 조회 중</div>}
        {!loading && failed && (
          <Notice tone="danger" title="지표 흐름 조회 실패">
            서버 연결 실패 또는 계산 실패
            {onRetry && <div className="mc-act"><button type="button" className="tx-btn tx-btn--sub" onClick={onRetry}>재시도</button></div>}
          </Notice>
        )}
        {!loading && !failed && !series && <div className="mc-modal-load">이 지표는 흐름 자료 없음</div>}
        {!loading && series && (
          <>
            <div className="mc-modal-h">
              <div><b>{series.name}</b><span><span data-mono>{series.indicator}</span> · <span data-server>{series.source}</span></span></div>
              <div className="mc-modal-latest"><b>{fmtNum(series.latest)}</b><em>{series.unit}</em></div>
            </div>
            <DrillSeriesChart data={data} name={series.name} unit={series.unit} mean5y={series.mean_5y} />
            <p className="mc-modal-note">점선은 지난 5년 평균입니다.</p>
            <dl className="mc-modal-stats">
              {[["최근 값", `${fmtNum(series.latest)} ${series.unit}`], ["지난 5년 평균", fmtNum(series.mean_5y)], ["지난 5년 표준편차", fmtNum(series.std_5y)],
                ["z(평균 대비 편차)", fmtZ(series.z_score)], ["최근 5년 백분위", series.percentile != null ? `${Math.round(series.percentile)}%` : "N/A"], ["전년 대비", fmtPct(series.yoy)]].map(([k, v]) => (
                <div key={k} className="mc-modal-stat"><dt>{k}</dt><dd>{v}</dd></div>
              ))}
            </dl>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
