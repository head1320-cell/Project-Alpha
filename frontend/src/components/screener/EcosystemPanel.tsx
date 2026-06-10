"use client";

/**
 * Preset Gallery + Ecosystem Actions — Milestone 4
 * ==========================================================================
 *  · PresetGallery     — 거장/국면/테마 프리셋 카드 (Valley AI 전략 리스트 흡수)
 *  · EcosystemActions  — 백테스터 연동 + AI 매크로 브리핑 (Phase 3 재사용)
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Loader2, Play, BarChart3, Sparkles, ChevronRight, X,
} from "lucide-react";
import { Skeleton, SkeletonText } from "@/components/common";
import { NarrativeDisplay } from "@/components/narrative";
import {
  presetApi,
  type PresetCatalog, type PresetItem, type ScreenerResponse, type ScreenerItem,
} from "@/lib/screenerApi";
import { narrativeApi, type NarrativeResponse } from "@/lib/narrativeApi";
import { macroApi } from "@/lib/macroApi";

const CATEGORY_ACCENT: Record<string, string> = {
  master: "#8b5cf6", regime: "#0891b2", theme: "#16a34a",
};

// ═══════════════════════════════════════════════════════════════════════════════
// PresetGallery
// ═══════════════════════════════════════════════════════════════════════════════

export function PresetGallery({
  universe, onResults, onLoadToBuilder,
}: {
  universe: string;
  onResults: (resp: ScreenerResponse & { preset_name?: string }) => void;
  onLoadToBuilder?: (presetId: string) => void;
}) {
  const [catalog, setCatalog] = useState<PresetCatalog | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    presetApi.list().then(setCatalog).catch(e => setError(e.message));
  }, []);

  const runPreset = async (id: string) => {
    setRunning(id);
    setError(null);
    try {
      const r = await presetApi.run(id, universe, 50);
      onResults(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(null);
    }
  };

  if (error && !catalog) {
    return <div className="card-md p-4 text-xs text-center" style={{ color: "#dc2626" }}>{error}</div>;
  }

  if (!catalog) {
    return (
      <div className="card-md p-4">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {[0,1,2,3,4,5].map(i => <Skeleton key={i} className="h-24" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="card-md p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-primary">거장 & 국면 프리셋</h3>
        <span className="text-[10px] font-mono text-secondary">{catalog.total}개 전략 · 원클릭 실행</span>
      </div>

      {catalog.categories.map(cat => (
        <div key={cat.id} className="mb-4 last:mb-0">
          <div className="text-[10px] uppercase tracking-wider font-bold mb-2" style={{ color: CATEGORY_ACCENT[cat.id] || "#737373" }}>
            {cat.label}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5">
            {cat.presets.map(p => (
              <PresetCard
                key={p.id} preset={p}
                accent={CATEGORY_ACCENT[cat.id] || "#737373"}
                running={running === p.id}
                onRun={() => runPreset(p.id)}
                onLoad={onLoadToBuilder ? () => onLoadToBuilder(p.id) : undefined}
              />
            ))}
          </div>
        </div>
      ))}
      {error && <div className="text-[11px] mt-2" style={{ color: "#dc2626" }}>⚠ {error}</div>}
    </div>
  );
}

function PresetCard({
  preset, accent, running, onRun, onLoad,
}: {
  preset: PresetItem;
  accent: string;
  running: boolean;
  onRun: () => void;
  onLoad?: () => void;
}) {
  return (
    <div
      className="rounded-lg border border-default p-3 hover:shadow-sm transition group"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="flex items-start gap-2 mb-1.5">
        <span className="text-xl leading-none">{preset.icon}</span>
        <div className="flex-grow min-w-0">
          <div className="text-sm font-bold text-primary truncate">{preset.name}</div>
          <div className="text-[10px] text-secondary">{preset.master}</div>
        </div>
        {preset.use_macro && (
          <span className="text-[8px] px-1 py-0.5 rounded font-bold flex-shrink-0" style={{ background: "#cffafe", color: "#0891b2" }}>
            MACRO
          </span>
        )}
      </div>
      <p className="text-[10px] text-secondary leading-relaxed mb-2 line-clamp-2" style={{ minHeight: 28 }}>
        {preset.description}
      </p>
      <div className="flex items-center gap-1.5">
        <button
          onClick={onRun}
          disabled={running}
          className="flex-grow text-[11px] font-medium py-1.5 rounded flex items-center justify-center gap-1 transition"
          style={{ background: accent, color: "#fff" }}
        >
          {running ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
          실행
        </button>
        {onLoad && (
          <button
            onClick={onLoad}
            className="text-[11px] px-2 py-1.5 rounded border border-default hover:border-primary/50 transition text-secondary"
            title="빌더에 불러오기"
          >
            편집
          </button>
        )}
      </div>
      <div className="text-[9px] text-secondary mt-1.5 font-mono">{preset.condition_count}개 조건</div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// EcosystemActions — 백테스터 연동 + AI 브리핑
// ═══════════════════════════════════════════════════════════════════════════════

export function EcosystemActions({ items }: { items: ScreenerItem[] }) {
  const router = useRouter();
  const [briefing, setBriefing] = useState<NarrativeResponse | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);

  const tickers = items.slice(0, 20).map(it => it.stock_code);

  const goToBacktest = () => {
    // 통과 종목을 Stage 11 백테스터로 전달
    const codes = tickers.join(",");
    router.push(`/admin/multi-backtest?tickers=${encodeURIComponent(codes)}`);
  };

  const generateBriefing = async () => {
    setBriefingLoading(true);
    try {
      const regime = await macroApi.regime().catch(() => null);
      const top5 = items.slice(0, 5);
      const regime_state = {
        regime: regime?.regime ?? "Unknown",
        systemic_risk_score: regime?.stress_score ?? 0,
        mode: regime?.recommended_mode ?? "NORMAL",
        vix: 0, t10y2y_bps: regime?.yield_curve?.spread_2y10y_bp ?? 0,
        spx: 0, spx_trend: "—", dxy: 0, gold: 0,
        vix_signal: "—", rate_signal: regime?.yield_inversion ? "inverted" : "normal",
        usd_signal: "—",
        screened_stocks: top5.map(s => ({
          name: s.corp_name, gap_pct: s.gap_pct, verdict: s.verdict,
          composite: s.composite_score, sector: s.sector,
        })),
        screening_note: `스크리너 통과 ${items.length}종목 중 상위 5종목. 현재 국면에서 이들이 유리한 이유를 분석.`,
      };
      const r = await narrativeApi.macro(regime_state);
      setBriefing(r);
    } catch {
      // ignore
    } finally {
      setBriefingLoading(false);
    }
  };

  if (items.length === 0) return null;

  return (
    <div className="space-y-3">
      <div className="card-md p-3 flex items-center justify-between flex-wrap gap-2"
            style={{ background: "linear-gradient(135deg, #f5f3ff 0%, #eff6ff 60%)" }}>
        <div className="text-xs text-secondary">
          통과 <span className="font-bold text-primary tabular-nums">{items.length}</span>종목으로 다음 단계 →
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={generateBriefing}
            disabled={briefingLoading}
            className="text-xs font-medium px-3 py-1.5 rounded-md flex items-center gap-1.5 transition hover:scale-105"
            style={{ background: "#8b5cf6", color: "#fff" }}
          >
            {briefingLoading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
            AI 매크로 브리핑
          </button>
          <button
            onClick={goToBacktest}
            className="text-xs font-medium px-3 py-1.5 rounded-md flex items-center gap-1.5 transition hover:scale-105"
            style={{ background: "#198754", color: "#fff" }}
          >
            <BarChart3 size={12} /> 백테스터로 →
          </button>
        </div>
      </div>

      {briefing && (
        <NarrativeDisplay response={briefing} domain="macro" onClose={() => setBriefing(null)} />
      )}
    </div>
  );
}
