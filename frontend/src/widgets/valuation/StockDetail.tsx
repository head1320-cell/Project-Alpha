"use client";

import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine, RadialBarChart, RadialBar,
  ComposedChart, Line, Cell,
} from "recharts";
import { TrendingDown, TrendingUp, Minus, Info, X } from "lucide-react";
import { screenerApi } from "@/entities/screener/api/core";
import type { ScreenerItem, ValuationDetail } from "@/shared/model";
import { formatKrw, formatPct, gapColor, verdictColor } from "@/shared/lib/format";

/**
 * StockDetail — 종목 가치평가 상세 대시보드
 * ─────────────────────────────────────────────────────────────
 *  · Price-Value Band: 현재가 vs RIM/DCF/DDM 적정가 비교 막대 + 평균선
 *  · Gap Gauge: 괴리율 Radial Bar (-100% ~ +100%)
 *  · Financial Snapshot: EPS/BPS/ROE/FCF/PER/PBR 등
 *  · Tooltip: 각 모델의 핵심 수식 표시
 */
interface StockDetailProps {
  item?: ScreenerItem | null;
  onClose?: () => void;
}

export default function StockDetail({ item, onClose }: StockDetailProps) {
  const [detail, setDetail] = useState<ValuationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!item) return;
    setLoading(true);
    setError("");
    screenerApi
      .evaluate(item.stock_code, item.current_price)
      .then(setDetail)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [item]);

  if (!item) {
    return (
      <div className="card-md h-full flex items-center justify-center text-secondary">
        <div className="text-center">
          <Info size={32} className="mx-auto mb-3 opacity-40" />
          <div className="text-sm">좌측에서 종목을 선택하면 상세 분석이 표시됩니다.</div>
        </div>
      </div>
    );
  }

  const colors = verdictColor(item.verdict);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="card-md p-4">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-bold text-primary">{item.corp_name}</h2>
              <span className="text-xs font-mono text-secondary">{item.stock_code}</span>
              {item.sector && (
                <span className="text-[10px] px-2 py-0.5 bg-light rounded text-secondary">
                  {item.sector}
                </span>
              )}
            </div>
            <div className="flex items-center gap-4 mt-2">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-secondary">현재가</div>
                <div className="text-2xl font-bold font-mono text-primary">
                  {item.current_price.toLocaleString()}원
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-secondary">적정가</div>
                <div className="text-2xl font-bold font-mono" style={{ color: colors.fg }}>
                  {item.intrinsic_value.toLocaleString()}원
                </div>
              </div>
            </div>
          </div>

          {onClose && (
            <button onClick={onClose}
                    className="p-1.5 hover:bg-light rounded transition">
              <X size={14} />
            </button>
          )}
        </div>

        {/* Verdict pill + Gap */}
        <div className="flex items-center gap-3 pt-3 border-t border-default">
          <span
            className="px-3 py-1 rounded-full text-xs font-bold"
            style={{ color: colors.fg, background: colors.bg, border: `1px solid ${colors.border}` }}
          >
            {item.verdict}
          </span>
          <div className="flex items-center gap-1.5">
            {item.gap_pct < 0 ? <TrendingDown size={14} color={colors.fg} /> :
             item.gap_pct > 0 ? <TrendingUp size={14} color={colors.fg} /> :
             <Minus size={14} color={colors.fg} />}
            <span className="text-sm font-bold font-mono" style={{ color: colors.fg }}>
              {formatPct(item.gap_pct, 2)}
            </span>
          </div>
          <div className="text-xs text-secondary">
            Composite Score: <span className="font-bold text-primary">{item.composite_score.toFixed(1)}</span> / 100
          </div>
        </div>
      </div>

      {/* Loading / Error */}
      {loading && (
        <div className="card-md p-8 text-center text-secondary text-sm">
          상세 분석 데이터 로딩 중...
        </div>
      )}
      {error && !loading && (
        <div className="card-md p-4 text-center text-sm" style={{ color: "#dc2626" }}>
          데이터 로드 실패: {error}
        </div>
      )}

      {/* Main charts grid */}
      {detail && !loading && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <PriceValueBand item={item} detail={detail} />
            <GapGauge gapPct={item.gap_pct} />
          </div>

          <ModelBreakdown detail={detail} />
          <ScoreBreakdown item={item} />
          <FinancialSnapshot detail={detail} item={item} />
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Price-Value Band — 현재가 vs 3-모델 적정가 비교
// ═══════════════════════════════════════════════════════════════════════════════

function PriceValueBand({ item, detail }: { item: ScreenerItem; detail: ValuationDetail }) {
  // 차트 데이터: 현재가 + 3-모델 적정가 + 통합 적정가
  const data = [
    { name: "현재가", value: item.current_price, color: "#111111" },
    {
      name: "RIM",
      value: item.rim_value ?? 0,
      color: "#16a34a",
      formula: "BPS + Σ(ROE-Ke)·BPS / (1+Ke)^t",
    },
    {
      name: "DCF",
      value: item.dcf_value ?? 0,
      color: "#10b981",
      formula: "ΣFCF / (1+WACC)^t + TV/(1+WACC)^n",
    },
    {
      name: "DDM",
      value: item.ddm_value ?? 0,
      color: "#22c55e",
      formula: "ΣD / (1+Ke)^t + Pn/(1+Ke)^n",
    },
    { name: "통합", value: item.intrinsic_value, color: "#0e7490" },
  ].filter(d => d.value > 0);

  return (
    <div className="card-md p-4">
      <div className="mb-3">
        <h3 className="text-sm font-bold text-primary">Price-Value Band</h3>
        <p className="text-[10px] text-secondary mt-0.5 font-mono">
          현재가 vs 3-모델 적정가 비교
        </p>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 12, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
          <XAxis dataKey="name" stroke="#737373" style={{ fontSize: 11 }} />
          <YAxis
            stroke="#737373"
            style={{ fontSize: 10 }}
            tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`}
          />
          <Tooltip
            cursor={{ fill: "rgba(0,0,0,0.04)" }}
            contentStyle={{
              background: "#fff",
              border: "1px solid #d4d4d8",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(v: number) => [`${v.toLocaleString()}원`, "적정가"]}
            labelFormatter={(label, payload) => {
              const d = payload?.[0]?.payload as { formula?: string } | undefined;
              return d?.formula ? `${label}: ${d.formula}` : label;
            }}
          />
          <ReferenceLine
            y={item.current_price}
            stroke="#000"
            strokeDasharray="4 2"
            label={{ value: "현재가", position: "right", fontSize: 9, fill: "#000" }}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((entry, idx) => (
              <Cell key={idx} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Gap Gauge — 괴리율 Radial Bar
// ═══════════════════════════════════════════════════════════════════════════════

function GapGauge({ gapPct }: { gapPct: number }) {
  // -100 ~ +100 범위를 0~100으로 정규화 (저평가는 우측)
  const normalized = Math.max(0, Math.min(100, 50 - gapPct));
  const color = gapColor(gapPct);

  return (
    <div className="card-md p-4">
      <div className="mb-3">
        <h3 className="text-sm font-bold text-primary">Gap Gauge</h3>
        <p className="text-[10px] text-secondary mt-0.5 font-mono">
          현재가 ↔ 적정가 괴리율 (저평가 ▶ 우측)
        </p>
      </div>
      <div className="relative" style={{ height: 240 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="60%"
            innerRadius="55%"
            outerRadius="90%"
            startAngle={180}
            endAngle={0}
            data={[{ value: normalized, fill: color }]}
          >
            <RadialBar
              background={{ fill: "#f3f4f6" }}
              dataKey="value"
              cornerRadius={6}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="mt-8 text-4xl font-bold font-mono" style={{ color }}>
            {formatPct(gapPct, 1)}
          </div>
          <div className="text-[10px] text-secondary mt-1 font-mono uppercase tracking-wider">
            {gapPct < 0 ? "저평가" : gapPct > 0 ? "고평가" : "적정"}
          </div>
        </div>
        {/* Scale labels */}
        <div className="absolute bottom-2 left-4 text-[9px] text-secondary font-mono">+50% 고평가</div>
        <div className="absolute bottom-2 right-4 text-[9px] text-secondary font-mono">-50% 저평가</div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Model Breakdown — 각 모델 적정가 + 가정 + 수식
// ═══════════════════════════════════════════════════════════════════════════════

const MODEL_INFO = {
  RIM: {
    name: "잔여이익모델 (Residual Income)",
    formula: "V = BPS + Σ (ROE - Kₑ) × BPS / (1 + Kₑ)ᵗ",
    best: "수익성 높은 기업 (ROE > Kₑ)",
    color: "#16a34a",
  },
  DCF: {
    name: "현금흐름할인법 (Discounted Cash Flow)",
    formula: "V = Σ FCFₜ / (1 + WACC)ᵗ + TV / (1 + WACC)ⁿ",
    best: "안정적 현금흐름 기업",
    color: "#10b981",
  },
  DDM: {
    name: "배당할인법 (Dividend Discount)",
    formula: "V = Σ Dₜ / (1 + Kₑ)ᵗ + Pₙ / (1 + Kₑ)ⁿ",
    best: "배당주 / 금융주",
    color: "#22c55e",
  },
};

function ModelBreakdown({ detail }: { detail: ValuationDetail }) {
  return (
    <div className="card-md p-4">
      <div className="mb-3">
        <h3 className="text-sm font-bold text-primary">Model Breakdown</h3>
        <p className="text-[10px] text-secondary mt-0.5 font-mono">
          각 모델별 가정 + 수식 + 산출 결과
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {detail.models.map((m) => {
          const info = MODEL_INFO[m.model];
          return (
            <div
              key={m.model}
              className="rounded-lg border border-default p-3 hover:shadow-sm transition"
              style={{ borderLeft: `3px solid ${info.color}` }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: info.color }}>
                  {m.model}
                </span>
                {!m.available && (
                  <span className="text-[9px] px-1.5 py-0.5 bg-light rounded text-secondary">
                    N/A
                  </span>
                )}
              </div>
              <div className="text-[10px] text-secondary mb-1">{info.name}</div>
              {m.available ? (
                <>
                  <div className="text-xl font-bold font-mono text-primary mb-2">
                    {m.intrinsic_value.toLocaleString()}원
                  </div>
                  <div className="text-[9px] font-mono text-secondary leading-relaxed bg-light p-1.5 rounded">
                    {info.formula}
                  </div>
                  {Object.entries(m.assumptions).slice(0, 3).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between text-[10px] mt-1 font-mono">
                      <span className="text-secondary">{k}</span>
                      <span className="text-primary">{typeof v === "number" ? v.toFixed(2) : String(v)}</span>
                    </div>
                  ))}
                </>
              ) : (
                <div className="text-[10px] text-secondary py-2">
                  {m.error || "데이터 부족"}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Score Breakdown — Composite 60/20/20
// ═══════════════════════════════════════════════════════════════════════════════

function ScoreBreakdown({ item }: { item: ScreenerItem }) {
  const data = [
    { name: "Gap (저평가)", value: item.gap_score, weight: 0.6, color: "#16a34a" },
    { name: "ROE (수익성)", value: item.roe_score, weight: 0.2, color: "#10b981" },
    { name: "Stability (안정성)", value: item.stability_score, weight: 0.2, color: "#22c55e" },
  ];

  return (
    <div className="card-md p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-primary">Composite Score Breakdown</h3>
          <p className="text-[10px] text-secondary mt-0.5 font-mono">
            저평가 60% + 수익성 20% + 안정성 20%
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold font-mono text-primary">
            {item.composite_score.toFixed(1)}
          </div>
          <div className="text-[10px] text-secondary">/ 100</div>
        </div>
      </div>
      <div className="space-y-3">
        {data.map((d) => (
          <div key={d.name}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-medium">{d.name}</span>
              <span className="text-[10px] font-mono">
                <span style={{ color: d.color, fontWeight: 600 }}>{d.value.toFixed(1)}</span>
                <span className="text-secondary"> × {d.weight}</span>
                <span className="text-secondary"> = {(d.value * d.weight).toFixed(1)}</span>
              </span>
            </div>
            <div className="h-2 bg-light rounded overflow-hidden">
              <div
                className="h-full rounded transition-all"
                style={{ width: `${d.value}%`, background: d.color }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Financial Snapshot — 핵심 재무 지표 테이블
// ═══════════════════════════════════════════════════════════════════════════════

function FinancialSnapshot({ detail, item }: { detail: ValuationDetail; item: ScreenerItem }) {
  const fin = detail.financial_summary;

  const rows = [
    {
      group: "수익성",
      items: [
        { label: "EPS (주당순이익)", value: fin.eps, format: "krw" },
        { label: "BPS (주당순자산)", value: fin.bps, format: "krw" },
        { label: "DPS (주당배당)",  value: fin.dps, format: "krw" },
        { label: "ROE",            value: fin.roe_pct, format: "pct" },
        { label: "ROA",            value: fin.roa_pct, format: "pct" },
      ],
    },
    {
      group: "가치평가 비율",
      items: [
        { label: "PER",            value: fin.per, format: "x" },
        { label: "PBR",            value: fin.pbr, format: "x" },
        { label: "배당수익률",       value: fin.dividend_yield_pct, format: "pct" },
        { label: "배당성향",         value: fin.payout_ratio_pct, format: "pct" },
      ],
    },
    {
      group: "재무 건전성",
      items: [
        { label: "부채비율",         value: fin.debt_ratio_pct, format: "pct" },
        { label: "매출액 (억)",      value: fin.revenue_억, format: "num" },
        { label: "영업이익 (억)",    value: fin.operating_profit_억, format: "num" },
        { label: "순이익 (억)",      value: fin.net_income_억, format: "num" },
        { label: "FCF (억)",        value: fin.fcf_억, format: "num" },
      ],
    },
  ];

  return (
    <div className="card-md p-4">
      <div className="mb-3">
        <h3 className="text-sm font-bold text-primary">Financial Snapshot</h3>
        <p className="text-[10px] text-secondary mt-0.5 font-mono">
          {fin.bsns_year}년 결산 기준 · DART 출처
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {rows.map((g) => (
          <div key={g.group}>
            <div className="text-[10px] uppercase tracking-wider font-bold text-secondary mb-2">
              {g.group}
            </div>
            <table className="w-full text-[11px]">
              <tbody>
                {g.items.map((it, i) => (
                  <tr
                    key={i}
                    className="border-b border-default last:border-0"
                  >
                    <td className="py-1.5 text-secondary">{it.label}</td>
                    <td className="py-1.5 text-right font-mono font-medium text-primary">
                      {it.value == null ? "—" :
                        it.format === "krw"  ? `${Number(it.value).toLocaleString()}원` :
                        it.format === "pct"  ? formatPct(it.value as number) :
                        it.format === "x"    ? `${Number(it.value).toFixed(2)}배` :
                                                 Number(it.value).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
