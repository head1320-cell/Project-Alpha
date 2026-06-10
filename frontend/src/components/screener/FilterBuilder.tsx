"use client";

/**
 * Visual Filter Builder — Milestone 2
 * ==========================================================================
 * 좌(카테고리) → 중(조건 편집) → 우(필터 스택 + 실시간 통과 수) 3단 빌더.
 *
 * 구성:
 *   CategorySidebar — 지표 카테고리/필드 목록
 *   ConditionEditor — 절대값/랭킹 조건 편집 + 스택 추가
 *   FilterStack     — 적용 조건 칩 + AND/OR + 통과 수(디바운스 count) + 실행
 *
 * 재사용: M1 screenerApiAdvanced(fields/count/runAdvanced), Phase 5 TickValue/Skeleton
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { AnalyzerPanel } from "./AnalyzerPanel";
import { BacktestPanel } from "./BacktestPanel";
import { LiveTradingPanel } from "./LiveTradingPanel";
import { DataQualityPanel } from "./DataQualityPanel";
import {
  Search, Plus, X, Trash2, Play, Loader2, BarChart3, Sparkles,
  Hash, Percent, ChevronRight, AlertCircle, SlidersHorizontal,
  Globe, Wand2, Zap, Scale, FunctionSquare, MessageSquare, Send, Check,
  Activity, CalendarClock, TrendingUp as TrendUp, Clock, History, Sparkles as SparkIcon, LineChart, Droplets, ShieldCheck, Brain, Network, MessageCircle, Users,
} from "lucide-react";
import { TickValue, Skeleton } from "@/components/common";
import {
  screenerApiAdvanced, emptyFilterGroup, conditionLabel,
  fetchMacroGuidance, guidanceFilterToNode,
  screenerV2Api, conditionLabelV2, copilotApi, screenerV2DataApi, screenerPITApi, screenerV3Api, liquidityApi,
  behavioralApi, graphApi, sentimentApi, vectorApi, fundamentalsApi,
  type FieldsCatalog, type FieldMeta, type FilterGroupNode,
  type FilterConditionNode, type ScreenerResponse, type ScreenerItem,
  type MacroGuidance, type PeerGroups, type NL2ASTResult,
  type IndicatorCatalog, type EventCatalog, type PITDates, type EstimateCatalog,
  type LiquidityProfiles, type BehaviorSignals, type GraphMeta,
  type SentimentCatalog, type VectorMeta,
} from "@/lib/screenerApi";

const CATEGORY_ICONS: Record<string, typeof Hash> = {
  valuation: BarChart3, profitability: Percent, growth: ChevronRight,
  dividend: Hash, stability: SlidersHorizontal, score: Sparkles,
};

interface FilterBuilderProps {
  universe: string;
  onResults: (resp: ScreenerResponse) => void;
  onSelect?: (item: ScreenerItem) => void;
}

export default function FilterBuilder({ universe, onResults, onSelect }: FilterBuilderProps) {
  const [catalog, setCatalog] = useState<FieldsCatalog | null>(null);
  const [activeField, setActiveField] = useState<FieldMeta | null>(null);
  const [group, setGroup] = useState<FilterGroupNode>(emptyFilterGroup());
  const [count, setCount] = useState<number | null>(null);
  const [countLoading, setCountLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guidance, setGuidance] = useState<MacroGuidance | null>(null);
  const [useMacro, setUseMacro] = useState(true);
  const [asOfDate, setAsOfDate] = useState<string | null>(null);
  const [liquidityFloor, setLiquidityFloor] = useState<string>("standard");
  const [hasRun, setHasRun] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 카탈로그 로드 (fields + indicators + events + estimates 통합)
  useEffect(() => {
    Promise.all([
      screenerApiAdvanced.fields(),
      screenerV2DataApi.indicators().catch(() => null),
      screenerV2DataApi.eventsCatalog().catch(() => null),
      screenerV3Api.estimatesCatalog().catch(() => null),
      behavioralApi.signals().catch(() => null),
      graphApi.meta().catch(() => null),
      sentimentApi.catalog().catch(() => null),
      vectorApi.meta().catch(() => null),
      fundamentalsApi.catalog().catch(() => null),
    ]).then(([fieldsCat, indCat, evCat, estCat, behavCat, graphCat, sentCat, vecMeta, fundCat]) => {
      const merged: FieldsCatalog = { ...fieldsCat, categories: [...fieldsCat.categories] };
      // FFL: 학술 펀더멘털 팩터 병합 (field kind — 기본 에디터 사용)
      if (fundCat) {
        for (const cat of fundCat.categories) {
          merged.categories.push({
            id: `ffl_${cat.id}`,
            label: cat.label,
            fields: cat.factors.map(f => ({
              id: f.id, label: f.label, category: `ffl_${cat.id}`,
              unit: f.unit, higher_better: f.higher_better,
              typical_min: f.typical_min, typical_max: f.typical_max,
              _desc: `${f.description}${f.source !== "기본" ? ` · ${f.source}` : ""}`,
            })) as unknown as FieldMeta[],
          });
        }
      }
      // 기술지표/수급 카테고리 병합 (_kind=technical 마커)
      if (indCat) {
        for (const cat of indCat.categories) {
          merged.categories.push({
            id: `tech_${cat.id}`,
            label: cat.label,
            fields: cat.indicators.map(ind => ({
              id: ind.id, label: ind.label, category: `tech_${cat.id}`,
              unit: ind.unit, higher_better: true,
              typical_min: ind.typical_min, typical_max: ind.typical_max,
              _kind: "technical", _desc: ind.description,
            })) as unknown as FieldMeta[],
          });
        }
      }
      // 이벤트 카테고리 병합 (_kind=event 마커)
      if (evCat) {
        merged.categories.push({
          id: "events",
          label: "이벤트",
          fields: evCat.events.map(ev => ({
            id: ev.id, label: ev.label, category: "events",
            unit: "일", higher_better: false, typical_min: 0, typical_max: 90,
            _kind: "event", _desc: ev.description,
          })) as unknown as FieldMeta[],
        });
      }
      // V3-M1: 추정치 카테고리 병합 (_kind=estimate 마커)
      if (estCat) {
        merged.categories.push({
          id: "estimate",
          label: estCat.category.label,
          fields: estCat.category.fields.map(f => ({
            id: f.id, label: f.label, category: "estimate",
            unit: f.unit, higher_better: f.higher_better,
            typical_min: f.typical_min, typical_max: f.typical_max,
            _kind: "estimate", _desc: f.description,
          })) as unknown as FieldMeta[],
        });
      }
      // V3-M3: 행동재무 카테고리 병합 (_kind=behavioral 마커)
      if (behavCat) {
        merged.categories.push({
          id: "behavioral",
          label: "행동재무",
          fields: behavCat.signals.map(s => ({
            id: s.id, label: s.label, category: "behavioral",
            unit: "", higher_better: true, typical_min: 0, typical_max: 0,
            _kind: "behavioral", _desc: s.description,
          })) as unknown as FieldMeta[],
        });
      }
      // V3-M4: 공급망 그래프 (단일 항목, _kind=graph 마커)
      if (graphCat) {
        merged.categories.push({
          id: "graph",
          label: "공급망",
          fields: [{
            id: "__graph__", label: "밸류체인 관계", category: "graph",
            unit: "", higher_better: true, typical_min: 0, typical_max: 0,
            _kind: "graph", _desc: "특정 종목의 공급사·고객사·경쟁사 관계망 필터",
          }] as unknown as FieldMeta[],
        });
      }
      // V3-M5: AI 센티먼트 카테고리 (_kind=sentiment 마커)
      if (sentCat) {
        merged.categories.push({
          id: "sentiment",
          label: "AI 센티먼트",
          fields: sentCat.sources.map(s => ({
            id: s.id, label: s.label, category: "sentiment",
            unit: s.unit, higher_better: true,
            typical_min: s.typical_min, typical_max: s.typical_max,
            _kind: "sentiment", _desc: s.description,
          })) as unknown as FieldMeta[],
        });
      }
      // V3-M6: 유사 종목 (단일 항목, _kind=vector_sim 마커)
      if (vecMeta) {
        merged.categories.push({
          id: "vector",
          label: "유사 종목",
          fields: [{
            id: "__vector__", label: "벡터 유사도 (Twin)", category: "vector",
            unit: "", higher_better: true, typical_min: 0, typical_max: 1,
            _kind: "vector_sim", _desc: "재무/가격 임베딩 기반 유사 종목 탐색",
          }] as unknown as FieldMeta[],
        });
      }
      setCatalog(merged);
      if (merged.categories[0]?.fields[0]) setActiveField(merged.categories[0].fields[0]);
    }).catch(e => setError(e.message));
  }, []);

  // M3: 매크로 가이던스 로드
  useEffect(() => {
    fetchMacroGuidance().then(setGuidance).catch(() => {});
  }, []);

  // 추천 필터 일괄 적용
  const applyRecommended = () => {
    if (!guidance) return;
    const nodes = guidance.recommended_filters.map(guidanceFilterToNode);
    setGroup(g => ({ ...g, conditions: [...g.conditions, ...nodes] }));
  };

  // 디바운스 count (조건 변경 시 통과 수 자동 갱신)
  useEffect(() => {
    if (group.conditions.length === 0 && group.groups.length === 0) {
      setCount(null);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setCountLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await screenerApiAdvanced.count({ universe, filter_ast: group, limit: 1 });
        setCount(r.total_passed);
      } catch {
        setCount(null);
      } finally {
        setCountLoading(false);
      }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [group, universe]);

  const addCondition = (cond: FilterConditionNode) => {
    setGroup(g => ({ ...g, conditions: [...g.conditions, cond] }));
  };
  const removeCondition = (idx: number) => {
    setGroup(g => ({ ...g, conditions: g.conditions.filter((_, i) => i !== idx) }));
  };
  const toggleLogic = () => {
    setGroup(g => ({ ...g, logic: g.logic === "AND" ? "OR" : "AND" }));
  };
  const clearAll = () => setGroup(emptyFilterGroup());

  const runScreener = async () => {
    setRunning(true);
    setError(null);
    try {
      let r: ScreenerResponse;
      if (asOfDate) {
        // V2-M4: 타임머신 모드
        r = await screenerPITApi.runPit({
          universe, filter_ast: group, as_of_date: asOfDate,
          sort_by: "composite_score", limit: 50,
        });
      } else {
        r = await screenerApiAdvanced.runAdvanced({
          universe, filter_ast: group, sort_by: "composite_score", limit: 50,
          use_macro: useMacro, liquidity_floor: liquidityFloor,
        });
      }
      onResults(r);
      setHasRun(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  if (error && !catalog) {
    return <div className="card-md p-6 text-center text-sm" style={{ color: "#dc2626" }}><AlertCircle size={20} className="mx-auto mb-2" />{error}</div>;
  }

  return (
    <div className="space-y-3">
      <CopilotBar onApplyAst={(ast) => setGroup(ast)} />
      <LiquidityGateBar value={liquidityFloor} onChange={setLiquidityFloor} />
      <TimeMachineBar asOfDate={asOfDate} onChange={setAsOfDate} />
      {guidance && (
        <MacroGuidanceBanner
          guidance={guidance}
          useMacro={useMacro}
          onToggleMacro={() => setUseMacro(v => !v)}
          onApply={applyRecommended}
        />
      )}
    <div className="card-md overflow-hidden">
      {/* 3-Panel Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr_320px]" style={{ minHeight: 420 }}>
        <CategorySidebar catalog={catalog} activeField={activeField} onSelect={setActiveField} />
        <ConditionEditor field={activeField} catalog={catalog} onAdd={addCondition} />
        <FilterStack
          group={group} catalog={catalog} count={count} countLoading={countLoading}
          running={running} onRemove={removeCondition} onToggleLogic={toggleLogic}
          onClear={clearAll} onRun={runScreener}
        />
      </div>
      {error && <div className="px-4 py-2 text-xs border-t border-default" style={{ color: "#dc2626" }}>⚠ {error}</div>}
    </div>
    {/* V3-M7+M8: 후처리 메타분석 (스크리닝 실행 후) */}
    {hasRun && (
      <AnalyzerPanel group={group} universe={universe} liquidityFloor={liquidityFloor} />
    )}
    {/* V3 4순위: 데이터 품질 검증 (스크리닝 실행 후) */}
    {hasRun && (
      <DataQualityPanel group={group} universe={universe} liquidityFloor={liquidityFloor} />
    )}
    {/* V3 2순위: 통과 종목 원클릭 백테스트 (스크리닝 실행 후) */}
    {hasRun && (
      <BacktestPanel group={group} universe={universe} liquidityFloor={liquidityFloor} />
    )}
    {/* V3 3순위: 자동매매 실거래 (스크리닝 실행 후) */}
    {hasRun && (
      <LiveTradingPanel group={group} universe={universe} liquidityFloor={liquidityFloor} />
    )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MacroGuidanceBanner (M3) — 현재 국면 기반 추천
// ═══════════════════════════════════════════════════════════════════════════════

function MacroGuidanceBanner({
  guidance, useMacro, onToggleMacro, onApply,
}: {
  guidance: MacroGuidance;
  useMacro: boolean;
  onToggleMacro: () => void;
  onApply: () => void;
}) {
  const modeColor =
    guidance.recommended_mode === "DEFENSIVE" ? { border: "#dc2626", bg: "#fef2f2", fg: "#b91c1c" } :
    guidance.recommended_mode === "CAUTIOUS"  ? { border: "#f59e0b", bg: "#fffbeb", fg: "#a16207" } :
                                                  { border: "#22c55e", bg: "#f0fdf4", fg: "#15803d" };

  return (
    <div
      className="card-md p-4 animate-fade-in"
      style={{ borderLeft: `3px solid ${modeColor.border}`, background: `linear-gradient(135deg, ${modeColor.bg} 0%, #fff 60%)` }}
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-grow min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <Globe size={15} style={{ color: modeColor.fg }} />
            <span className="text-sm font-bold text-primary">매크로 적응형 가이드</span>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold" style={{ background: modeColor.bg, color: modeColor.fg }}>
              {guidance.regime}
            </span>
            <span className="text-[10px] font-mono text-secondary">Stress {guidance.stress_score.toFixed(0)} · {guidance.recommended_mode}</span>
          </div>
          <p className="text-[12px] text-primary leading-relaxed">💡 {guidance.guidance_text}</p>

          {/* 동적 가중치 시각화 */}
          <div className="flex items-center gap-3 mt-2 text-[10px] font-mono text-secondary">
            <span>동적 Composite 가중:</span>
            <span style={{ color: "#16a34a" }}>저평가 {(guidance.recommended_weights.gap * 100).toFixed(0)}%</span>
            <span style={{ color: "#10b981" }}>수익성 {(guidance.recommended_weights.roe * 100).toFixed(0)}%</span>
            <span style={{ color: "#22c55e" }}>안정성 {(guidance.recommended_weights.stability * 100).toFixed(0)}%</span>
          </div>
        </div>

        <div className="flex flex-col gap-2 flex-shrink-0">
          <button
            onClick={onApply}
            className="text-xs font-medium px-3 py-2 rounded-md flex items-center gap-1.5 transition hover:scale-105"
            style={{ background: modeColor.fg, color: "#fff" }}
          >
            <Wand2 size={13} /> 추천 필터 적용
          </button>
          <label className="flex items-center gap-1.5 text-[10px] text-secondary cursor-pointer justify-center">
            <input type="checkbox" checked={useMacro} onChange={onToggleMacro} className="rounded" />
            <Zap size={10} /> 국면 가중 점수
          </label>
        </div>
      </div>

      {/* 추천 필터 미리보기 */}
      {guidance.recommended_filters.length > 0 && (
        <div className="flex items-center gap-1.5 mt-3 pt-3 border-t border-default flex-wrap">
          <span className="text-[10px] text-secondary">추천:</span>
          {guidance.recommended_filters.map((f, i) => (
            <span key={i} className="text-[10px] font-mono px-2 py-0.5 rounded" style={{ background: modeColor.bg, color: modeColor.fg }}>
              {f.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// CategorySidebar (좌)
// ═══════════════════════════════════════════════════════════════════════════════

function CategorySidebar({
  catalog, activeField, onSelect,
}: {
  catalog: FieldsCatalog | null;
  activeField: FieldMeta | null;
  onSelect: (f: FieldMeta) => void;
}) {
  const [query, setQuery] = useState("");

  if (!catalog) {
    return (
      <div className="border-r border-default p-3 space-y-2 bg-light">
        {[0,1,2,3,4].map(i => <Skeleton key={i} className="h-7" />)}
      </div>
    );
  }

  const q = query.trim().toLowerCase();

  return (
    <div className="border-r border-default bg-light flex flex-col">
      <div className="p-2 border-b border-default">
        <div className="flex items-center gap-1.5 px-2 py-1 bg-white rounded border border-default">
          <Search size={12} className="text-secondary" />
          <input
            value={query} onChange={e => setQuery(e.target.value)}
            placeholder="지표 검색"
            className="text-[11px] outline-none bg-transparent flex-grow"
          />
        </div>
      </div>
      <div className="flex-grow overflow-y-auto p-1.5 space-y-2" style={{ maxHeight: 420 }}>
        {catalog.categories.map(cat => {
          const Icon = CATEGORY_ICONS[cat.id] || Hash;
          const fields = q
            ? cat.fields.filter(f => f.label.toLowerCase().includes(q) || f.id.includes(q))
            : cat.fields;
          if (fields.length === 0) return null;
          return (
            <div key={cat.id}>
              <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] uppercase tracking-wider font-bold text-secondary">
                <Icon size={11} /> {cat.label}
              </div>
              {fields.map(f => {
                const isActive = activeField?.id === f.id;
                return (
                  <button
                    key={f.id} onClick={() => onSelect(f)}
                    className={`w-full text-left px-2 py-1.5 rounded text-[12px] transition flex items-center justify-between ${
                      isActive ? "bg-primary text-white" : "hover:bg-white text-primary"
                    }`}
                  >
                    <span>{f.label}</span>
                    <span className={`text-[9px] font-mono ${isActive ? "text-white/70" : "text-secondary"}`}>{f.unit}</span>
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ConditionEditor (중)
// ═══════════════════════════════════════════════════════════════════════════════

function ConditionEditor({
  field, catalog, onAdd,
}: {
  field: FieldMeta | null;
  catalog: FieldsCatalog | null;
  onAdd: (cond: FilterConditionNode) => void;
}) {
  const [mode, setMode] = useState<"absolute" | "rank" | "peer" | "formula" | "zscore">("absolute");
  const [op, setOp] = useState<string>("lt");
  const [value, setValue] = useState<string>("");
  const [value2, setValue2] = useState<string>("");
  const [rankMode, setRankMode] = useState<string>("top_pct");
  const [rankValue, setRankValue] = useState<string>("10");
  const [zWindow, setZWindow] = useState<number>(20);
  // V3-M4 Graph
  const [graphTarget, setGraphTarget] = useState<string>("");
  const [graphTargetName, setGraphTargetName] = useState<string>("");
  const [graphRelation, setGraphRelation] = useState<string>("supplier");
  const [graphDepth, setGraphDepth] = useState<number>(1);
  const [graphQuery, setGraphQuery] = useState<string>("");
  const [graphResults, setGraphResults] = useState<Array<{ code: string; name: string }>>([]);
  // V3-M6 Vector
  const [vectorTicker, setVectorTicker] = useState<string>("");
  const [vectorTickerName, setVectorTickerName] = useState<string>("");
  const [vectorThreshold, setVectorThreshold] = useState<number>(0.8);
  const [vectorQuery, setVectorQuery] = useState<string>("");
  const [vectorResults, setVectorResults] = useState<Array<{ code: string; name: string }>>([]);
  // Peer
  const [peerScope, setPeerScope] = useState<"sector" | "market">("sector");
  const [peerStat, setPeerStat] = useState<"mean" | "median" | "rank_pct">("mean");
  // Formula
  const [formula, setFormula] = useState<string>("");
  const [formulaValid, setFormulaValid] = useState<{ valid: boolean; error: string | null } | null>(null);
  const fvDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (field) {
      setOp(field.higher_better ? "gte" : "lte");
      setValue("");
      if (mode !== "formula") setRankMode(field.higher_better ? "top_pct" : "bottom_pct");
    }
  }, [field]);

  // 수식 실시간 검증 (디바운스)
  useEffect(() => {
    if (mode !== "formula" || !formula.trim()) { setFormulaValid(null); return; }
    if (fvDebounce.current) clearTimeout(fvDebounce.current);
    fvDebounce.current = setTimeout(async () => {
      try {
        const v = await screenerV2Api.validateFormula(formula);
        setFormulaValid({ valid: v.valid, error: v.error });
      } catch { setFormulaValid(null); }
    }, 400);
    return () => { if (fvDebounce.current) clearTimeout(fvDebounce.current); };
  }, [formula, mode]);

  if (!catalog) {
    return (
      <div className="p-6 flex items-center justify-center text-center">
        <div className="text-secondary"><SlidersHorizontal size={28} className="mx-auto mb-2 opacity-40" /><div className="text-sm">로딩 중...</div></div>
      </div>
    );
  }
  // formula 모드는 field 불필요, 나머지는 필요
  if (!field && mode !== "formula") {
    return (
      <div className="p-6 flex items-center justify-center text-center">
        <div className="text-secondary"><SlidersHorizontal size={28} className="mx-auto mb-2 opacity-40" /><div className="text-sm">좌측에서 지표를 선택하세요</div></div>
      </div>
    );
  }

  const handleAdd = () => {
    if (mode === "formula") {
      const v = parseFloat(value);
      if (!formula.trim() || isNaN(v) || !formulaValid?.valid) return;
      onAdd({ field: "__formula__", kind: "formula", formula, op: op as FilterConditionNode["op"], value: v });
      setFormula(""); setValue(""); setFormulaValid(null);
      return;
    }
    if (!field) return;
    // V2-M3: technical/event 필드 감지
    const fieldKind = (field as unknown as { _kind?: string })._kind;
    if (fieldKind === "technical") {
      const v = parseFloat(value);
      if (isNaN(v)) return;
      onAdd({ field: "__tech__", kind: "technical", indicator: field.id, op: op as FilterConditionNode["op"], value: v });
      setValue("");
      return;
    }
    if (fieldKind === "event") {
      const d = parseFloat(value);
      if (isNaN(d)) return;
      onAdd({ field: "__event__", kind: "event", event_type: field.id, within_days: d });
      setValue("");
      return;
    }
    if (fieldKind === "estimate") {
      const v = parseFloat(value);
      if (isNaN(v)) return;
      onAdd({ field: "__est__", kind: "estimate", estimate_field: field.id, op: op as FilterConditionNode["op"], value: v });
      setValue("");
      return;
    }
    if (fieldKind === "behavioral") {
      onAdd({ field: "__b__", kind: "behavioral", behavior_signal: field.id });
      return;
    }
    if (fieldKind === "graph") {
      if (!graphTarget) return;
      onAdd({ field: "__g__", kind: "graph", graph_target: graphTarget, graph_relation: graphRelation, graph_depth: graphDepth });
      return;
    }
    if (fieldKind === "sentiment") {
      const v = parseFloat(value);
      if (isNaN(v)) return;
      onAdd({ field: "__s__", kind: "sentiment", sentiment_source: field.id, op: op as FilterConditionNode["op"], value: v });
      setValue("");
      return;
    }
    if (fieldKind === "vector_sim") {
      if (!vectorTicker) return;
      onAdd({ field: "__v__", kind: "vector_sim", vector_ticker: vectorTicker, vector_threshold: vectorThreshold });
      return;
    }
    if (mode === "zscore") {
      const v = parseFloat(value);
      if (isNaN(v)) return;
      onAdd({ field: "__z__", kind: "z_score", z_field: field.id, z_window: zWindow, op: op as FilterConditionNode["op"], value: v });
      setValue("");
      return;
    }
    if (mode === "absolute") {
      const v = parseFloat(value);
      if (isNaN(v)) return;
      onAdd({ field: field.id, kind: "field", op: op as FilterConditionNode["op"], value: v, value2: op === "between" ? parseFloat(value2) : null });
    } else if (mode === "rank") {
      const rv = parseFloat(rankValue);
      if (isNaN(rv)) return;
      onAdd({ field: field.id, kind: "field", rank_mode: rankMode as FilterConditionNode["rank_mode"], rank_value: rv });
    } else if (mode === "peer") {
      if (peerStat === "rank_pct") {
        const rv = parseFloat(rankValue);
        if (isNaN(rv)) return;
        onAdd({ field: field.id, kind: "peer", peer_scope: peerScope, peer_stat: "rank_pct", rank_value: rv });
      } else {
        onAdd({ field: field.id, kind: "peer", peer_scope: peerScope, peer_stat: peerStat, op: op as FilterConditionNode["op"] });
      }
    }
    setValue(""); setValue2("");
  };

  const MODES = [
    { id: "absolute", label: "절대값" },
    { id: "rank", label: "랭킹" },
    { id: "peer", label: "Peer", icon: Scale },
    { id: "zscore", label: "Z-Score", icon: LineChart },
    { id: "formula", label: "수식", icon: FunctionSquare },
  ] as const;

  // V2-M3: technical/event 필드는 전용 에디터
  const fieldKind = field ? (field as unknown as { _kind?: string })._kind : undefined;
  const fieldDesc = field ? (field as unknown as { _desc?: string })._desc : undefined;

  // V3-M3/M4: behavioral/graph 전용 에디터
  if (fieldKind === "behavioral") {
    return (
      <div className="p-4 flex flex-col">
        <div className="mb-3">
          <div className="flex items-center gap-2">
            <Brain size={15} style={{ color: "#7c3aed" }} />
            <h3 className="text-base font-bold text-primary">{field?.label}</h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: "#f3e8ff", color: "#7c3aed" }}>행동재무</span>
          </div>
          {fieldDesc && <div className="text-[10px] text-secondary mt-1 leading-relaxed">{fieldDesc}</div>}
        </div>
        <div className="text-[11px] text-secondary bg-light p-2.5 rounded leading-relaxed mb-3">
          🧠 사전 정의된 복합 수급 신호입니다. 내부자·기관·외국인·개인의 매매 방향 교차를 포착합니다.
        </div>
        <button onClick={handleAdd} className="btn-primary text-sm py-2 flex items-center justify-center gap-1.5">
          <Plus size={14} /> 이 신호를 필터에 추가
        </button>
      </div>
    );
  }

  if (fieldKind === "graph") {
    return (
      <div className="p-4 flex flex-col">
        <div className="mb-3">
          <div className="flex items-center gap-2">
            <Network size={15} style={{ color: "#0891b2" }} />
            <h3 className="text-base font-bold text-primary">밸류체인 관계</h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: "#cffafe", color: "#0891b2" }}>공급망</span>
          </div>
          <div className="text-[10px] text-secondary mt-1">특정 종목의 공급망 관계망에 속한 종목만 필터링</div>
        </div>

        <div className="space-y-3">
          {/* 타겟 종목 검색 */}
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">기준 종목</label>
            {graphTarget ? (
              <div className="flex items-center gap-2 mt-1 px-2.5 py-2 bg-light rounded border border-default">
                <span className="text-sm font-bold text-primary flex-grow">{graphTargetName} <span className="text-[10px] font-mono text-secondary">{graphTarget}</span></span>
                <button onClick={() => { setGraphTarget(""); setGraphTargetName(""); setGraphQuery(""); }} className="text-secondary hover:text-primary">
                  <X size={12} />
                </button>
              </div>
            ) : (
              <div className="relative mt-1">
                <input
                  value={graphQuery}
                  onChange={async e => {
                    setGraphQuery(e.target.value);
                    if (e.target.value.length >= 1) {
                      try { const r = await graphApi.search(e.target.value); setGraphResults(r.results); } catch {}
                    } else setGraphResults([]);
                  }}
                  placeholder="종목명 검색 (예: 삼성전자)"
                  className="input w-full text-sm py-2"
                />
                {graphResults.length > 0 && (
                  <div className="absolute z-10 left-0 right-0 mt-1 bg-white border border-default rounded-md shadow-lg max-h-40 overflow-y-auto">
                    {graphResults.map(r => (
                      <button key={r.code}
                        onClick={() => { setGraphTarget(r.code); setGraphTargetName(r.name); setGraphResults([]); setGraphQuery(""); }}
                        className="w-full text-left px-3 py-2 hover:bg-light transition flex items-center justify-between">
                        <span className="text-sm text-primary">{r.name}</span>
                        <span className="text-[10px] font-mono text-secondary">{r.code}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 관계 유형 */}
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">관계</label>
            <div className="flex gap-1 mt-1">
              {[["supplier","공급사"],["customer","고객사"],["competitor","경쟁사"]].map(([id, lbl]) => (
                <button key={id} onClick={() => setGraphRelation(id)}
                  className={`flex-1 py-1.5 text-[11px] font-medium rounded border transition ${graphRelation === id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {lbl}
                </button>
              ))}
            </div>
          </div>

          {/* Depth */}
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">탐색 깊이 (hop)</label>
            <div className="flex gap-1 mt-1">
              {[1, 2, 3].map(d => (
                <button key={d} onClick={() => setGraphDepth(d)}
                  className={`flex-1 py-1.5 text-[11px] font-medium rounded border transition ${graphDepth === d ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {d}-hop
                </button>
              ))}
            </div>
            <div className="text-[10px] text-secondary mt-1.5 bg-light p-2 rounded">
              1-hop = 직접 관계, 2-hop = 관계의 관계까지. 깊을수록 넓은 밸류체인.
            </div>
          </div>
        </div>

        <button onClick={handleAdd} disabled={!graphTarget} className="btn-primary text-sm py-2 mt-4 flex items-center justify-center gap-1.5">
          <Plus size={14} /> 필터 스택에 추가
        </button>
      </div>
    );
  }

  if (fieldKind === "vector_sim") {
    return (
      <div className="p-4 flex flex-col">
        <div className="mb-3">
          <div className="flex items-center gap-2">
            <Users size={15} style={{ color: "#db2777" }} />
            <h3 className="text-base font-bold text-primary">유사 종목 (Twin)</h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: "#fce7f3", color: "#db2777" }}>벡터</span>
          </div>
          <div className="text-[10px] text-secondary mt-1">재무/가격 임베딩 기반 코사인 유사도로 닮은 종목 탐색</div>
        </div>

        <div className="space-y-3">
          {/* 기준 종목 검색 */}
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">기준 종목</label>
            {vectorTicker ? (
              <div className="flex items-center gap-2 mt-1 px-2.5 py-2 bg-light rounded border border-default">
                <span className="text-sm font-bold text-primary flex-grow">{vectorTickerName} <span className="text-[10px] font-mono text-secondary">{vectorTicker}</span></span>
                <button onClick={() => { setVectorTicker(""); setVectorTickerName(""); setVectorQuery(""); }} className="text-secondary hover:text-primary">
                  <X size={12} />
                </button>
              </div>
            ) : (
              <div className="relative mt-1">
                <input
                  value={vectorQuery}
                  onChange={async e => {
                    setVectorQuery(e.target.value);
                    if (e.target.value.length >= 1) {
                      try { const r = await graphApi.search(e.target.value); setVectorResults(r.results); } catch {}
                    } else setVectorResults([]);
                  }}
                  placeholder="종목명 검색 (예: 삼성전자)"
                  className="input w-full text-sm py-2"
                />
                {vectorResults.length > 0 && (
                  <div className="absolute z-10 left-0 right-0 mt-1 bg-white border border-default rounded-md shadow-lg max-h-40 overflow-y-auto">
                    {vectorResults.map(r => (
                      <button key={r.code}
                        onClick={() => { setVectorTicker(r.code); setVectorTickerName(r.name); setVectorResults([]); setVectorQuery(""); }}
                        className="w-full text-left px-3 py-2 hover:bg-light transition flex items-center justify-between">
                        <span className="text-sm text-primary">{r.name}</span>
                        <span className="text-[10px] font-mono text-secondary">{r.code}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 유사도 임계 슬라이더 */}
          <div>
            <div className="flex items-center justify-between">
              <label className="text-[10px] uppercase tracking-wider text-secondary">최소 유사도</label>
              <span className="text-sm font-mono font-bold" style={{ color: "#db2777" }}>{vectorThreshold.toFixed(2)}</span>
            </div>
            <input type="range" min="0.5" max="0.99" step="0.01" value={vectorThreshold}
              onChange={e => setVectorThreshold(parseFloat(e.target.value))}
              className="w-full mt-2" style={{ accentColor: "#db2777" }} />
            <div className="flex justify-between text-[9px] text-secondary mt-0.5">
              <span>0.5 (느슨)</span><span>0.8 (권장)</span><span>0.99 (쌍둥이)</span>
            </div>
          </div>
          <div className="text-[10px] text-secondary bg-light p-2 rounded">
            코사인 유사도가 임계 이상인 종목만 통과. 값이 높을수록 더 닮은 종목.
          </div>
        </div>

        <button onClick={handleAdd} disabled={!vectorTicker} className="btn-primary text-sm py-2 mt-4 flex items-center justify-center gap-1.5">
          <Plus size={14} /> 필터 스택에 추가
        </button>
      </div>
    );
  }

  if (mode !== "formula" && (fieldKind === "technical" || fieldKind === "event" || fieldKind === "estimate" || fieldKind === "sentiment")) {
    return (
      <div className="p-4 flex flex-col">
        <div className="mb-3">
          <div className="flex items-center gap-2">
            {fieldKind === "technical" ? <Activity size={15} style={{ color: "#0891b2" }} /> : fieldKind === "event" ? <CalendarClock size={15} style={{ color: "#d97706" }} /> : fieldKind === "sentiment" ? <MessageCircle size={15} style={{ color: "#db2777" }} /> : <SparkIcon size={15} style={{ color: "#8b5cf6" }} />}
            <h3 className="text-base font-bold text-primary">{field?.label}</h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: fieldKind === "technical" ? "#cffafe" : fieldKind === "event" ? "#fef3c7" : fieldKind === "sentiment" ? "#fce7f3" : "#f3e8ff", color: fieldKind === "technical" ? "#0891b2" : fieldKind === "event" ? "#a16207" : fieldKind === "sentiment" ? "#db2777" : "#8b5cf6" }}>
              {fieldKind === "technical" ? "기술지표" : fieldKind === "event" ? "이벤트" : fieldKind === "sentiment" ? "AI 센티먼트" : "추정치"}
            </span>
          </div>
          {fieldDesc && <div className="text-[10px] text-secondary mt-1 leading-relaxed">{fieldDesc}</div>}
        </div>

        {fieldKind === "event" ? (
          <div className="space-y-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-secondary">임박 일수 (이내)</label>
              <div className="flex items-center gap-2 mt-1">
                <input type="number" value={value} onChange={e => setValue(e.target.value)} placeholder="7" autoFocus className="input flex-grow text-sm py-2" />
                <span className="text-sm text-secondary font-mono">일 이내</span>
              </div>
            </div>
            <div className="flex gap-1.5">
              {[3, 7, 14, 30].map(d => (
                <button key={d} onClick={() => setValue(String(d))}
                  className="flex-1 text-[11px] py-1 rounded border border-default hover:border-primary/50 transition text-secondary">
                  {d}일
                </button>
              ))}
            </div>
            <div className="text-[10px] text-secondary bg-light p-2 rounded">
              {field?.label} 예정일까지 설정 일수 이내인 종목을 필터링합니다.
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-secondary">연산자</label>
              <div className="flex gap-1 mt-1">
                {catalog.operators.filter(o => o.id !== "between").map(o => (
                  <button key={o.id} onClick={() => setOp(o.id)} title={o.name}
                    className={`flex-1 py-1.5 text-sm font-mono rounded border transition ${op === o.id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                    {o.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input type="number" value={value} onChange={e => setValue(e.target.value)} placeholder="값" autoFocus className="input flex-grow text-sm py-2" />
              <span className="text-sm text-secondary font-mono">{field?.unit}</span>
            </div>
            <div className="text-[10px] text-secondary bg-light p-2 rounded">
              범위 {field?.typical_min} ~ {field?.typical_max}
              {fieldKind === "technical" && " · 예: RSI < 30 (과매도), MACD 히스토그램 > 0 (골든크로스)"}
              {fieldKind === "estimate" && " · 예: 선행 EPS 변화 > 10% (추정 상향), 리비전 > 30"}
              {fieldKind === "sentiment" && " · 예: 뉴스 > 0.3 (긍정), 콜 톤 ≥ 0 (부정 제외). 정성적 맥락 필터."}
            </div>
          </div>
        )}

        <button onClick={handleAdd} className="btn-primary text-sm py-2 mt-4 flex items-center justify-center gap-1.5">
          <Plus size={14} /> 필터 스택에 추가
        </button>
      </div>
    );
  }

  return (
    <div className="p-4 flex flex-col">
      {/* Field header */}
      <div className="mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-bold text-primary">
            {mode === "formula" ? "사용자 수식" : field?.label}
          </h3>
          {field && mode !== "formula" && <span className="text-[10px] px-1.5 py-0.5 bg-light rounded text-secondary font-mono">{field.unit}</span>}
        </div>
        <div className="text-[10px] text-secondary mt-0.5 font-mono">
          {mode === "formula"
            ? "필드명과 사칙연산으로 커스텀 지표 생성"
            : field && `일반 범위 ${field.typical_min} ~ ${field.typical_max} · ${field.higher_better ? "높을수록 유리 ↑" : "낮을수록 유리 ↓"}`}
        </div>
      </div>

      {/* Mode toggle (4) */}
      <div className="flex gap-1 p-0.5 bg-light rounded mb-3">
        {MODES.map(m => {
          const Icon = "icon" in m ? m.icon : null;
          return (
            <button
              key={m.id} onClick={() => setMode(m.id)}
              className={`flex-1 py-1.5 text-[11px] font-medium rounded transition flex items-center justify-center gap-1 ${mode === m.id ? "bg-white shadow-sm text-primary" : "text-secondary"}`}
            >
              {Icon && <Icon size={11} />}{m.label}
            </button>
          );
        })}
      </div>

      {/* ── ABSOLUTE ── */}
      {mode === "absolute" && (
        <div className="space-y-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">연산자</label>
            <div className="flex gap-1 mt-1">
              {catalog.operators.map(o => (
                <button key={o.id} onClick={() => setOp(o.id)} title={o.name}
                  className={`flex-1 py-1.5 text-sm font-mono rounded border transition ${op === o.id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input type="number" value={value} onChange={e => setValue(e.target.value)} placeholder="값" autoFocus className="input flex-grow text-sm py-2" />
            {op === "between" && (<><span className="text-secondary">~</span><input type="number" value={value2} onChange={e => setValue2(e.target.value)} placeholder="상한" className="input flex-grow text-sm py-2" /></>)}
            <span className="text-sm text-secondary font-mono">{field?.unit}</span>
          </div>
        </div>
      )}

      {/* ── RANK ── */}
      {mode === "rank" && (
        <div className="space-y-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">랭킹 방식</label>
            <div className="flex gap-1 mt-1">
              {catalog.rank_modes.map(rm => (
                <button key={rm.id} onClick={() => setRankMode(rm.id)}
                  className={`flex-1 py-1.5 text-[11px] font-medium rounded border transition ${rankMode === rm.id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {rm.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input type="number" value={rankValue} onChange={e => setRankValue(e.target.value)} className="input flex-grow text-sm py-2" />
            <span className="text-sm text-secondary font-mono">{rankMode === "top_n" ? "종목" : "%"}</span>
          </div>
        </div>
      )}

      {/* ── PEER ── */}
      {mode === "peer" && (
        <div className="space-y-3">
          <div className="text-[10px] text-secondary bg-light p-2 rounded leading-relaxed">
            ⚖ <strong>{field?.label}</strong>를 동종 그룹의 통계와 비교합니다 (크로스섹셔널).
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">비교 그룹</label>
            <div className="flex gap-1 mt-1">
              {[["sector","동일 섹터"],["market","전체 시장"]].map(([id, lbl]) => (
                <button key={id} onClick={() => setPeerScope(id as "sector"|"market")}
                  className={`flex-1 py-1.5 text-[11px] font-medium rounded border transition ${peerScope === id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {lbl}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">비교 기준</label>
            <div className="flex gap-1 mt-1">
              {[["mean","평균"],["median","중앙값"],["rank_pct","상위 %"]].map(([id, lbl]) => (
                <button key={id} onClick={() => setPeerStat(id as "mean"|"median"|"rank_pct")}
                  className={`flex-1 py-1.5 text-[11px] font-medium rounded border transition ${peerStat === id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {lbl}
                </button>
              ))}
            </div>
          </div>
          {peerStat === "rank_pct" ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-secondary">그룹 내 상위</span>
              <input type="number" value={rankValue} onChange={e => setRankValue(e.target.value)} className="input flex-grow text-sm py-2" />
              <span className="text-sm text-secondary font-mono">%</span>
            </div>
          ) : (
            <div>
              <label className="text-[10px] uppercase tracking-wider text-secondary">연산자 (그룹 {peerStat === "median" ? "중앙값" : "평균"} 대비)</label>
              <div className="flex gap-1 mt-1">
                {catalog.operators.filter(o => o.id !== "between").map(o => (
                  <button key={o.id} onClick={() => setOp(o.id)} title={o.name}
                    className={`flex-1 py-1.5 text-sm font-mono rounded border transition ${op === o.id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                    {o.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Z-SCORE ── */}
      {mode === "zscore" && (
        <div className="space-y-3">
          <div className="text-[10px] text-secondary bg-light p-2 rounded leading-relaxed">
            📉 <strong>{field?.label}</strong>를 자기 자신의 과거 평균과 비교 (Mean Reversion). Z &lt; 0 = 과거보다 낮음, Z &gt; 0 = 과거보다 높음.
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">과거 기간</label>
            <div className="flex gap-1 mt-1">
              {[[12,"3년"],[20,"5년"],[40,"10년"]].map(([w, lbl]) => (
                <button key={w} onClick={() => setZWindow(w as number)}
                  className={`flex-1 py-1.5 text-[11px] font-medium rounded border transition ${zWindow === w ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {lbl}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">시그마(σ) 임계</label>
            <div className="flex gap-1 mt-1">
              {catalog.operators.filter(o => o.id !== "between").map(o => (
                <button key={o.id} onClick={() => setOp(o.id)} title={o.name}
                  className={`flex-1 py-1.5 text-sm font-mono rounded border transition ${op === o.id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input type="number" step="0.5" value={value} onChange={e => setValue(e.target.value)} placeholder="-2" className="input flex-grow text-sm py-2" />
            <span className="text-sm text-secondary font-mono">σ</span>
          </div>
          <div className="flex gap-1.5">
            {[["-2","역사적 저평가"],["-1","약세"],["1","강세"],["2","역사적 고평가"]].map(([v, lbl]) => (
              <button key={v} onClick={() => setValue(v)}
                className="flex-1 text-[9px] py-1 rounded border border-default hover:border-primary/50 transition text-secondary">
                {v}σ<br/>{lbl}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── FORMULA ── */}
      {mode === "formula" && (
        <div className="space-y-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-secondary">수식 (필드명 + 사칙연산)</label>
            <textarea
              value={formula} onChange={e => setFormula(e.target.value)}
              placeholder="(per * 0.4) + (pbr * 0.6)" rows={2}
              className="input w-full text-sm py-2 font-mono mt-1" style={{ resize: "none" }}
            />
            {formulaValid && (
              <div className="text-[10px] mt-1 flex items-center gap-1" style={{ color: formulaValid.valid ? "#16a34a" : "#dc2626" }}>
                {formulaValid.valid ? <><CheckIcon /> 유효한 수식</> : <><AlertCircle size={10} /> {formulaValid.error}</>}
              </div>
            )}
          </div>
          {/* 사용 가능 필드 칩 */}
          <div className="flex flex-wrap gap-1">
            {catalog.categories.flatMap(c => c.fields).slice(0, 14).map(f => (
              <button key={f.id} onClick={() => setFormula(prev => prev + f.id)}
                className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-light hover:bg-primary hover:text-white transition text-secondary">
                {f.id}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-secondary">결과</span>
            <div className="flex gap-1 flex-grow">
              {catalog.operators.filter(o => o.id !== "between").map(o => (
                <button key={o.id} onClick={() => setOp(o.id)}
                  className={`flex-1 py-1.5 text-sm font-mono rounded border transition ${op === o.id ? "bg-primary text-white border-primary" : "border-default hover:border-primary/50"}`}>
                  {o.label}
                </button>
              ))}
            </div>
            <input type="number" value={value} onChange={e => setValue(e.target.value)} placeholder="값" className="input text-sm py-2" style={{ width: 80 }} />
          </div>
        </div>
      )}

      <button
        onClick={handleAdd}
        disabled={mode === "formula" && !formulaValid?.valid}
        className="btn-primary text-sm py-2 mt-4 flex items-center justify-center gap-1.5"
      >
        <Plus size={14} /> 필터 스택에 추가
      </button>
    </div>
  );
}

function CheckIcon() {
  return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12" /></svg>;
}

// ═══════════════════════════════════════════════════════════════════════════════
// FilterStack (우)
// ═══════════════════════════════════════════════════════════════════════════════

function FilterStack({
  group, catalog, count, countLoading, running,
  onRemove, onToggleLogic, onClear, onRun,
}: {
  group: FilterGroupNode;
  catalog: FieldsCatalog | null;
  count: number | null;
  countLoading: boolean;
  running: boolean;
  onRemove: (idx: number) => void;
  onToggleLogic: () => void;
  onClear: () => void;
  onRun: () => void;
}) {
  const fieldLabel = (id: string): string => {
    if (!catalog) return id;
    for (const cat of catalog.categories) {
      const f = cat.fields.find(x => x.id === id);
      if (f) return f.label;
    }
    return id;
  };

  const total = group.conditions.length;

  return (
    <div className="border-l border-default bg-light flex flex-col">
      {/* Header + Logic toggle */}
      <div className="p-3 border-b border-default flex items-center justify-between">
        <span className="text-xs font-bold text-primary">적용된 필터</span>
        {total >= 2 && (
          <button
            onClick={onToggleLogic}
            className="text-[10px] font-mono font-bold px-2 py-0.5 rounded transition"
            style={{
              background: group.logic === "AND" ? "#dbeafe" : "#fef3c7",
              color: group.logic === "AND" ? "#1e40af" : "#a16207",
            }}
            title="AND/OR 전환"
          >
            {group.logic}
          </button>
        )}
      </div>

      {/* Condition chips */}
      <div className="flex-grow overflow-y-auto p-2 space-y-1.5" style={{ maxHeight: 300 }}>
        {total === 0 ? (
          <div className="text-center py-8 text-secondary">
            <div className="text-xs">조건을 추가하세요</div>
            <div className="text-[10px] mt-1 opacity-70">중앙에서 지표 조건 설정 후 추가</div>
          </div>
        ) : (
          group.conditions.map((cond, idx) => (
            <div
              key={idx}
              className="animate-fade-in flex items-center gap-2 px-2.5 py-2 bg-white rounded border border-default group"
            >
              <div className="flex-grow min-w-0">
                <div className="text-[12px] font-medium text-primary truncate">
                  {conditionLabelV2(cond, fieldLabel)}
                </div>
              </div>
              <button
                onClick={() => onRemove(idx)}
                className="opacity-0 group-hover:opacity-100 transition p-0.5 hover:bg-light rounded flex-shrink-0"
              >
                <X size={12} className="text-secondary" />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Pass count + Actions */}
      <div className="border-t border-default p-3 space-y-3">
        <div className="text-center">
          <div className="text-[10px] uppercase tracking-wider text-secondary">실시간 통과 종목</div>
          <div className="text-3xl font-bold text-primary mt-0.5 flex items-center justify-center gap-1">
            {countLoading ? (
              <Loader2 size={20} className="animate-spin text-secondary" />
            ) : count !== null ? (
              <TickValue value={count} format="number" digits={0} />
            ) : (
              <span className="text-secondary">—</span>
            )}
            {count !== null && !countLoading && <span className="text-sm text-secondary">종목</span>}
          </div>
        </div>

        <button
          onClick={onRun}
          disabled={running || total === 0}
          className="btn-primary w-full text-sm py-2 flex items-center justify-center gap-1.5"
        >
          {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          스크리닝 실행
        </button>

        {total > 0 && (
          <button onClick={onClear} className="w-full text-[11px] text-secondary hover:text-primary flex items-center justify-center gap-1 py-1">
            <Trash2 size={11} /> 전체 초기화
          </button>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// CopilotBar (V2-M2) — 자연어 → AST (human-in-the-loop)
// ═══════════════════════════════════════════════════════════════════════════════

function CopilotBar({ onApplyAst }: { onApplyAst: (ast: FilterGroupNode) => void }) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<NL2ASTResult | null>(null);
  const [examples, setExamples] = useState<string[]>([]);
  const [catalog, setCatalog] = useState<FieldsCatalog | null>(null);

  useEffect(() => {
    copilotApi.examples().then(r => setExamples(r.examples)).catch(() => {});
    screenerApiAdvanced.fields().then(setCatalog).catch(() => {});
  }, []);

  const fieldLabel = (id: string): string => {
    if (!catalog) return id;
    for (const cat of catalog.categories) {
      const f = cat.fields.find(x => x.id === id);
      if (f) return f.label;
    }
    return id;
  };

  const submit = async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setResult(null);
    try {
      const r = await copilotApi.nl2ast(query);
      setResult(r);
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const apply = () => {
    if (result?.ast) {
      onApplyAst(result.ast);
      setResult(null);
      setQuery("");
    }
  };

  const confColor = (c: number) => c >= 0.7 ? "#16a34a" : c >= 0.5 ? "#d97706" : "#dc2626";

  return (
    <div className="card-md p-4" style={{ background: "linear-gradient(135deg, #faf5ff 0%, #fff 60%)" }}>
      <div className="flex items-center gap-2 mb-2">
        <MessageSquare size={15} style={{ color: "#8b5cf6" }} />
        <span className="text-sm font-bold text-primary">AI 자연어 스크리닝</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded-full font-bold" style={{ background: "#f3e8ff", color: "#8b5cf6" }}>
          NL2AST
        </span>
      </div>

      {/* 입력 */}
      <div className="flex items-center gap-2">
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") submit(); }}
          placeholder="원하는 종목을 말로 설명하세요 — 예: 부채 적고 배당 높은 방어주"
          className="input flex-grow text-sm py-2"
        />
        <button
          onClick={submit}
          disabled={loading || !query.trim()}
          className="btn-primary text-sm py-2 px-4 flex items-center gap-1.5"
          style={{ background: "#8b5cf6" }}
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          변환
        </button>
      </div>

      {/* 예시 칩 */}
      {!result && examples.length > 0 && (
        <div className="flex items-center gap-1.5 mt-2 flex-wrap">
          <span className="text-[10px] text-secondary">예시:</span>
          {examples.slice(0, 4).map((ex, i) => (
            <button
              key={i} onClick={() => setQuery(ex)}
              className="text-[10px] px-2 py-0.5 rounded-full border border-default hover:border-primary/50 transition text-secondary"
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* 결과 미리보기 (human-in-the-loop) */}
      {result && result.ast && (
        <div className="mt-3 p-3 rounded-lg border border-default bg-white animate-fade-in">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-bold text-primary">AI 해석 미리보기</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded font-mono" style={{ background: result.source === "claude" ? "#f3e8ff" : "#f3f4f6", color: result.source === "claude" ? "#8b5cf6" : "#737373" }}>
                {result.source === "claude" ? "Claude" : "규칙기반"}
              </span>
              <span className="text-[10px] font-mono" style={{ color: confColor(result.confidence) }}>
                신뢰도 {(result.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>

          <p className="text-[11px] text-secondary mb-2">💡 {result.explanation}</p>

          {/* 조건 칩 미리보기 */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {result.ast.conditions.map((cond, i) => (
              <span key={i} className="text-[10px] font-mono px-2 py-1 rounded" style={{ background: "#f3e8ff", color: "#7c3aed" }}>
                {conditionLabelV2(cond, fieldLabel)}
              </span>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={apply}
              className="text-xs font-medium px-3 py-1.5 rounded-md flex items-center gap-1.5 transition hover:scale-105"
              style={{ background: "#8b5cf6", color: "#fff" }}
            >
              <Check size={13} /> 필터에 적용
            </button>
            <button
              onClick={() => setResult(null)}
              className="text-xs px-3 py-1.5 rounded-md border border-default hover:bg-light transition text-secondary"
            >
              취소
            </button>
            <span className="text-[10px] text-secondary ml-auto">적용 후 좌측에서 수정 가능</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TimeMachineBar (V2-M4) — 과거 시점 스크리닝
// ═══════════════════════════════════════════════════════════════════════════════

function TimeMachineBar({ asOfDate, onChange }: { asOfDate: string | null; onChange: (d: string | null) => void }) {
  const [dates, setDates] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    screenerPITApi.dates().then(d => { setDates(d.dates); setNote(d.note); }).catch(() => {});
  }, []);

  const active = asOfDate !== null;

  return (
    <div
      className="card-md p-3"
      style={active ? { borderLeft: "3px solid #d97706", background: "linear-gradient(135deg, #fffbeb 0%, #fff 60%)" } : {}}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <History size={15} style={{ color: active ? "#d97706" : "#737373" }} />
          <span className="text-sm font-bold text-primary">타임머신</span>
          {active ? (
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono" style={{ background: "#fef3c7", color: "#a16207" }}>
              {asOfDate} 기준
            </span>
          ) : (
            <span className="text-[11px] text-secondary">현재 시점</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {active && (
            <button
              onClick={() => onChange(null)}
              className="text-[11px] px-2 py-1 rounded border border-default hover:bg-light transition text-secondary flex items-center gap-1"
            >
              <Clock size={11} /> 현재로
            </button>
          )}
          <button
            onClick={() => setExpanded(v => !v)}
            className="text-[11px] px-3 py-1.5 rounded-md transition flex items-center gap-1.5"
            style={{ background: active ? "#d97706" : "#f5f5f5", color: active ? "#fff" : "#525252" }}
          >
            <History size={12} /> {expanded ? "닫기" : "과거 시점 선택"}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-default animate-fade-in">
          <div className="text-[10px] text-secondary mb-2">{note}</div>
          <div className="flex flex-wrap gap-1.5">
            {dates.map(d => (
              <button
                key={d}
                onClick={() => { onChange(d); setExpanded(false); }}
                className={`text-[11px] font-mono px-2 py-1 rounded border transition ${
                  asOfDate === d ? "bg-amber-500 text-white border-amber-500" : "border-default hover:border-amber-400 text-secondary"
                }`}
              >
                {d}
              </button>
            ))}
          </div>
          <div className="text-[10px] text-secondary mt-2 flex items-center gap-1">
            <Clock size={10} /> 선택 시점에 공시 완료된 재무만 사용 (look-ahead bias 차단). 결과는 결정적으로 재현됩니다.
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// LiquidityGateBar (V3-P1.5) — 유동성 게이트 (모든 필터보다 먼저)
// ═══════════════════════════════════════════════════════════════════════════════

function LiquidityGateBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [profiles, setProfiles] = useState<LiquidityProfiles | null>(null);

  useEffect(() => {
    liquidityApi.profiles().then(setProfiles).catch(() => {});
  }, []);

  if (!profiles) return null;

  const isOff = value === "off";
  const current = profiles.profiles.find(p => p.id === value);

  return (
    <div
      className="card-md p-3"
      style={{ borderLeft: `3px solid ${isOff ? "#dc2626" : "#0891b2"}`, background: isOff ? "#fef2f2" : "linear-gradient(135deg, #ecfeff 0%, #fff 60%)" }}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Droplets size={15} style={{ color: isOff ? "#dc2626" : "#0891b2" }} />
          <span className="text-sm font-bold text-primary">유동성 게이트</span>
          <span className="text-[10px] text-secondary">모든 필터보다 먼저 적용</span>
          {isOff && (
            <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: "#fee2e2", color: "#b91c1c" }}>
              ⚠ 슬리피지 위험
            </span>
          )}
        </div>
        <div className="flex gap-1">
          {profiles.profiles.map(p => (
            <button
              key={p.id}
              onClick={() => onChange(p.id)}
              title={p.description}
              className={`text-[11px] px-2.5 py-1 rounded-md transition ${
                value === p.id
                  ? p.id === "off" ? "bg-red-500 text-white" : "bg-cyan-600 text-white"
                  : "border border-default hover:border-primary/50 text-secondary"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {current && (
        <div className="text-[10px] text-secondary mt-2 flex items-center gap-1">
          <ShieldCheck size={10} /> {current.description}
        </div>
      )}
    </div>
  );
}
