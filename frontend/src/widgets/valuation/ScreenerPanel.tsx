"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Search, RefreshCw, Loader2, TrendingDown, TrendingUp, Minus,
  ChevronRight, Sliders, Award,
} from "lucide-react";
import { screenerApi } from "@/entities/screener/api/core";
import { type ScreenerFilters, type ScreenerResponse } from "@/entities/screener/model";
import type { ScreenerItem } from "@/shared/model/domain";
import { formatPct, verdictColor } from "@/shared/lib/format";

/**
 * ScreenerPanel — 필터 컨트롤 + 결과 리더보드 + Quick Flip
 * ─────────────────────────────────────────────────────────────
 *  · 좌측: Universe + Filter 슬라이더
 *  · 우측: 정렬된 종목 카드 리스트 (Composite Score, Gap, ROE 시각화)
 *  · 종목 클릭 → onSelect 콜백 (부모가 StockDetail 표시)
 */
interface ScreenerPanelProps {
  onSelect: (item: ScreenerItem) => void;
  selectedTicker?: string;
}

export default function ScreenerPanel({ onSelect, selectedTicker }: ScreenerPanelProps) {
  const [universe, setUniverse] = useState("kospi50");
  const [filters, setFilters] = useState<ScreenerFilters>({
    min_roe_pct: 5,
    max_gap_pct: 0,    // 저평가만
    require_positive_fcf: true,
  });
  const [sortBy, setSortBy] = useState("composite_score");
  const [limit, setLimit] = useState(30);

  const [response, setResponse] = useState<ScreenerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  const runScreener = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await screenerApi.run({
        universe,
        filters,
        sort_by: sortBy,
        limit,
      });
      setResponse(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [universe, filters, sortBy, limit]);

  useEffect(() => {
    runScreener();
  }, []);  // 초기 1회만

  const items = response?.items ?? [];
  const filteredItems = query
    ? items.filter(
        (it) =>
          it.corp_name.toLowerCase().includes(query.toLowerCase()) ||
          it.stock_code.includes(query),
      )
    : items;

  return (
    <div className="space-y-3">
      {/* Top control bar */}
      <div className="card-md p-3">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Universe */}
          <select
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            className="input text-xs py-1.5 px-2"
            style={{ width: 130 }}
          >
            <option value="kospi50">KOSPI 50</option>
            <option value="kospi200">KOSPI 200</option>
            <option value="kosdaq150">KOSDAQ 150</option>
            <option value="mapped">DART 매핑</option>
          </select>

          {/* Sort by */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="input text-xs py-1.5 px-2"
            style={{ width: 150 }}
          >
            <option value="composite_score">📊 종합 점수</option>
            <option value="gap_pct">💎 괴리율</option>
            <option value="roe_pct">📈 ROE</option>
            <option value="per">PER (낮은 순)</option>
            <option value="pbr">PBR (낮은 순)</option>
            <option value="dividend_yield_pct">배당수익률</option>
          </select>

          {/* Limit */}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="input text-xs py-1.5 px-2"
            style={{ width: 90 }}
          >
            <option value="20">Top 20</option>
            <option value="30">Top 30</option>
            <option value="50">Top 50</option>
            <option value="100">Top 100</option>
          </select>

          <button
            onClick={runScreener}
            disabled={loading}
            className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1.5"
          >
            {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            실행
          </button>
        </div>

        {/* Filters row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3 pt-3 border-t border-default">
          <FilterInput
            label="ROE 최소"
            value={filters.min_roe_pct}
            unit="%"
            onChange={(v) => setFilters({ ...filters, min_roe_pct: v })}
          />
          <FilterInput
            label="괴리율 최대"
            value={filters.max_gap_pct}
            unit="%"
            onChange={(v) => setFilters({ ...filters, max_gap_pct: v })}
          />
          <FilterInput
            label="PER 최대"
            value={filters.max_per}
            unit="배"
            onChange={(v) => setFilters({ ...filters, max_per: v })}
          />
          <FilterInput
            label="PBR 최대"
            value={filters.max_pbr}
            unit="배"
            onChange={(v) => setFilters({ ...filters, max_pbr: v })}
          />
          <FilterInput
            label="배당수익률 최소"
            value={filters.min_dividend_yield}
            unit="%"
            onChange={(v) => setFilters({ ...filters, min_dividend_yield: v })}
          />
          <FilterInput
            label="부채비율 최대"
            value={filters.max_debt_ratio}
            unit="%"
            onChange={(v) => setFilters({ ...filters, max_debt_ratio: v })}
          />
          <label className="flex items-center gap-1.5 text-[11px] mt-3">
            <input
              type="checkbox"
              checked={filters.require_positive_fcf ?? false}
              onChange={(e) =>
                setFilters({ ...filters, require_positive_fcf: e.target.checked })
              }
              className="rounded"
            />
            <span>FCF &gt; 0만</span>
          </label>
        </div>
      </div>

      {/* Status bar */}
      {response && !loading && (
        <div className="flex items-center justify-between text-[10px] font-mono text-secondary px-1">
          <div>
            평가 {response.total_evaluated} · 통과 {response.total_passed} ·
            <span className="ml-1">캐시 {response.cache_hits}/{response.cache_hits + response.cache_misses}</span> ·
            <span className="ml-1">{response.elapsed_seconds}s</span>
            {response.failures > 0 && (
              <span className="ml-2 text-amber-600">⚠ {response.failures} 실패</span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <Search size={11} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="종목명 또는 코드..."
              className="input text-[11px] py-1 px-2"
              style={{ width: 140 }}
            />
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="card-md p-3 text-xs" style={{ color: "#dc2626" }}>
          ⚠ {error}
        </div>
      )}

      {/* Leaderboard */}
      {loading ? (
        <div className="card-md p-12 text-center">
          <Loader2 size={24} className="animate-spin mx-auto mb-2 text-secondary" />
          <div className="text-xs text-secondary">
            전 종목 RIM · DCF · DDM 계산 중...
          </div>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="card-md p-12 text-center">
          <div className="text-xs text-secondary">조건에 맞는 종목 없음</div>
        </div>
      ) : (
        <div className="space-y-2 max-h-[calc(100vh-340px)] overflow-y-auto pr-1">
          {filteredItems.map((it, idx) => (
            <StockCard
              key={it.stock_code}
              item={it}
              rank={idx + 1}
              selected={selectedTicker === it.stock_code}
              onClick={() => onSelect(it)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// StockCard — 단일 종목 카드 (리더보드 항목)
// ═══════════════════════════════════════════════════════════════════════════════

function StockCard({
  item, rank, selected, onClick,
}: {
  item: ScreenerItem; rank: number; selected: boolean; onClick: () => void;
}) {
  const colors = verdictColor(item.verdict);
  const TrendIcon = item.gap_pct < 0 ? TrendingDown : item.gap_pct > 0 ? TrendingUp : Minus;

  return (
    <div
      onClick={onClick}
      className={`
        rounded-md p-3 cursor-pointer transition-all border
        ${selected
          ? "border-primary bg-subtle shadow-sm"
          : "border-default bg-white hover:border-primary/50 hover:shadow-sm"}
      `}
    >
      <div className="flex items-center gap-3">
        {/* Rank badge */}
        <div className="flex-shrink-0">
          <div
            className={`w-8 h-8 rounded flex items-center justify-center text-xs font-bold ${
              rank === 1 ? "bg-amber-100 text-amber-700" :
              rank === 2 ? "bg-gray-200 text-gray-700" :
              rank === 3 ? "bg-orange-100 text-orange-700" :
              "bg-gray-50 text-gray-500"
            }`}
          >
            {rank <= 3 ? <Award size={14} /> : rank}
          </div>
        </div>

        {/* Name + sector */}
        <div className="flex-grow min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-primary truncate">
              {item.corp_name}
            </span>
            <span className="text-[10px] font-mono text-secondary">{item.stock_code}</span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            {item.sector && (
              <span className="text-[10px] text-secondary">{item.sector}</span>
            )}
            <span
              className="text-[9px] px-1.5 py-0.5 rounded font-medium"
              style={{ color: colors.fg, background: colors.bg }}
            >
              {item.verdict}
            </span>
          </div>
        </div>

        {/* Composite score */}
        <div className="flex-shrink-0 text-right">
          <div className="text-lg font-bold font-mono" style={{ color: colors.fg }}>
            {item.composite_score.toFixed(1)}
          </div>
          <div className="text-[9px] text-secondary uppercase tracking-wider">점수</div>
        </div>

        {/* Gap */}
        <div className="flex-shrink-0 text-right min-w-[80px]">
          <div className="flex items-center justify-end gap-1">
            <TrendIcon size={11} color={colors.fg} />
            <span className="text-sm font-bold font-mono" style={{ color: colors.fg }}>
              {formatPct(item.gap_pct, 1)}
            </span>
          </div>
          <div className="text-[9px] text-secondary font-mono">
            {item.current_price.toLocaleString()} → {item.intrinsic_value.toLocaleString()}
          </div>
        </div>

        {/* Quick metrics */}
        <div className="hidden md:flex flex-shrink-0 gap-3 text-[10px] font-mono border-l border-default pl-3 ml-1">
          <Metric label="ROE"  value={item.roe_pct != null ? `${item.roe_pct.toFixed(1)}%` : "—"} />
          <Metric label="PER"  value={item.per != null ? `${item.per.toFixed(1)}` : "—"} />
          <Metric label="PBR"  value={item.pbr != null ? `${item.pbr.toFixed(2)}` : "—"} />
        </div>

        <ChevronRight size={14} className="text-secondary flex-shrink-0" />
      </div>

      {/* Score breakdown bar (composite breakdown) */}
      <div className="mt-2 flex h-1 rounded overflow-hidden bg-gray-100">
        <div className="bg-emerald-500" style={{ width: `${item.gap_score * 0.6}%` }} />
        <div className="bg-emerald-400" style={{ width: `${item.roe_score * 0.2}%` }} />
        <div className="bg-emerald-300" style={{ width: `${item.stability_score * 0.2}%` }} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-secondary uppercase text-[8px] tracking-wider">{label}</div>
      <div className="text-primary font-medium">{value}</div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// FilterInput
// ═══════════════════════════════════════════════════════════════════════════════

function FilterInput({
  label, value, unit, onChange,
}: {
  label: string;
  value: number | null | undefined;
  unit: string;
  onChange: (v: number | null) => void;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] text-secondary">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          value={value ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            onChange(v === "" ? null : Number(v));
          }}
          className="input text-[11px] py-1 px-1.5 flex-grow"
          style={{ minWidth: 0 }}
          placeholder="—"
        />
        <span className="text-[10px] text-secondary">{unit}</span>
      </div>
    </label>
  );
}
