"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  screenerApiAdvanced, verdictColor, emptyFilterGroup,
  type FieldsCatalog, type FilterGroupNode, type FilterConditionNode,
  type ScreenerResponse, type ScreenerItem,
} from "@/lib/screenerApi";
import { setScreenerHandoff } from "@/lib/screenerHandoff";
import { listPresets, savePreset, deletePreset, type ScreenerPreset } from "@/lib/screenerPresets";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalScreener — Variant "Institutional Terminal" 스타일 스크리너
//   실제 screenerApiAdvanced 데이터 + 3-pane 워크스페이스 + 결과 테이블
// ═══════════════════════════════════════════════════════════════════════════════

const OPERATORS: Record<string, string> = {
  gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=", neq: "≠",
  between: "between", in: "in", not_in: "not in",
};

export default function TerminalScreener({
  universe, onSelect, selectedTicker,
}: {
  universe: string;
  onSelect?: (item: ScreenerItem) => void;
  selectedTicker?: string;
}) {
  const router = useRouter();
  const [catalog, setCatalog] = useState<FieldsCatalog | null>(null);
  // 저장된 프리셋
  const [presets, setPresets] = useState<ScreenerPreset[]>([]);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [activeCat, setActiveCat] = useState<string>("");
  const [group, setGroup] = useState<FilterGroupNode>(emptyFilterGroup());
  const [count, setCount] = useState<number | null>(null);
  const [results, setResults] = useState<ScreenerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  // 결과 테이블 컬럼 선택 + 정렬
  const [selectedCols, setSelectedCols] = useState<string[]>(["per", "pbr", "roe_pct", "composite_score"]);
  const [showColPicker, setShowColPicker] = useState(false);
  const [sortCol, setSortCol] = useState<string>("composite_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  // 자연어 검색
  const [nlQuery, setNlQuery] = useState("");
  const [nlLoading, setNlLoading] = useState(false);
  const [nlResult, setNlResult] = useState<{ explanation: string; confidence: number; source: string } | null>(null);
  const [nlExamples, setNlExamples] = useState<string[]>([]);
  // 지표 종류 토글 (펀더멘털 / 기술적) + 기술적 지표 카탈로그
  const [indicatorMode, setIndicatorMode] = useState<"fundamental" | "technical">("fundamental");
  const [techCatalog, setTechCatalog] = useState<import("@/lib/screenerApi").TechnicalIndicatorCatalog | null>(null);
  const [activeTechCat, setActiveTechCat] = useState<string>("");
  const [fieldSearch, setFieldSearch] = useState("");

  // 필드 카탈로그 로드
  useEffect(() => {
    screenerApiAdvanced.fields().then((c) => {
      setCatalog(c);
      if (c.categories[0]) setActiveCat(c.categories[0].id);
    }).catch(() => {});
    screenerApiAdvanced.nl2astExamples().then((d) => setNlExamples(d.examples || [])).catch(() => {});
    screenerApiAdvanced.indicators().then((c) => {
      setTechCatalog(c);
      if (c.categories[0]) setActiveTechCat(c.categories[0].label);
    }).catch(() => {});
    setPresets(listPresets());
  }, []);

  // 기술적 지표 조건 추가 (kind=technical)
  const addTechnicalCondition = useCallback((indicatorId: string) => {
    const cond = {
      kind: "technical", field: indicatorId, indicator: indicatorId,
      op: "lt", value: 30,
    } as unknown as FilterConditionNode;
    setGroup((g) => ({ ...g, conditions: [...g.conditions, cond] }));
  }, []);

  // 자연어 → 필터 변환
  const runNlSearch = useCallback(async (q: string) => {
    const query = q.trim();
    if (!query) return;
    setNlLoading(true); setNlResult(null);
    try {
      const r = await screenerApiAdvanced.nl2ast(query);
      // AST를 필터 그룹으로 적용
      setGroup(r.ast);
      setNlResult({ explanation: r.explanation, confidence: r.confidence, source: r.source });
    } catch { /* noop */ }
    finally { setNlLoading(false); }
  }, []);

  // 디바운스 카운트
  useEffect(() => {
    if (!group.conditions.length) { setCount(null); return; }
    const t = setTimeout(async () => {
      try {
        const r = await screenerApiAdvanced.count({ universe, filter_ast: group, limit: 1 });
        setCount(r.total_passed);
      } catch { /* noop */ }
    }, 400);
    return () => clearTimeout(t);
  }, [group, universe]);

  const addCondition = useCallback((field: string, label: string) => {
    const cond: FilterConditionNode = {
      kind: "field", field, op: "gt", value: 0,
    } as FilterConditionNode;
    setGroup((g) => ({ ...g, conditions: [...g.conditions, cond] }));
  }, []);

  const removeCondition = useCallback((idx: number) => {
    setGroup((g) => ({ ...g, conditions: g.conditions.filter((_, i) => i !== idx) }));
  }, []);

  // 조건의 연산자/값 편집
  const updateCondition = useCallback((idx: number, patch: Record<string, unknown>) => {
    setGroup((g) => ({
      ...g,
      conditions: g.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    }));
  }, []);

  const fieldLabel = useCallback((fieldId: string): string => {
    if (catalog) {
      for (const cat of catalog.categories) {
        const f = cat.fields.find((x) => x.id === fieldId);
        if (f) return f.label;
      }
    }
    if (techCatalog) {
      for (const cat of techCatalog.categories) {
        const f = cat.indicators.find((x) => x.id === fieldId);
        if (f) return f.label;
      }
    }
    return fieldId;
  }, [catalog, techCatalog]);

  const execute = async () => {
    if (!group.conditions.length) return;
    setLoading(true);
    try {
      const r = await screenerApiAdvanced.runAdvanced({
        universe, filter_ast: group, sort_by: "composite_score",
        ascending: false, limit: 50, liquidity_floor: "standard",
      });
      setResults(r);
    } catch { /* noop */ }
    finally { setLoading(false); }
  };

  const activeCategory = catalog?.categories.find((c) => c.id === activeCat);
  const activeTechCategory = techCatalog?.categories.find((c) => c.label === activeTechCat);

  // 검색 필터된 필드/지표
  const filteredFundFields = activeCategory?.fields.filter((f) =>
    !fieldSearch || f.label.toLowerCase().includes(fieldSearch.toLowerCase()) || f.id.includes(fieldSearch.toLowerCase())
  ) ?? [];
  const filteredTechInds = activeTechCategory?.indicators.filter((f) =>
    !fieldSearch || f.label.toLowerCase().includes(fieldSearch.toLowerCase()) || f.id.includes(fieldSearch.toLowerCase())
  ) ?? [];

  // ── 결과 테이블 컬럼 (펀더멘털 + 기술적 전체) ──
  const allColumns = (() => {
    const cols: { id: string; label: string; cat: string }[] = [];
    catalog?.categories.forEach((c) => c.fields.forEach((f) => cols.push({ id: f.id, label: f.label, cat: c.label })));
    techCatalog?.categories.forEach((c) => c.indicators.forEach((f) => cols.push({ id: f.id, label: f.label, cat: c.label })));
    return cols;
  })();
  const colLabel = (id: string) => allColumns.find((c) => c.id === id)?.label ?? id;
  const fmtVal = (v: unknown): string => {
    if (v == null) return "—";
    if (typeof v === "number") return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
    return String(v);
  };
  const toggleCol = (id: string) => setSelectedCols((cols) =>
    cols.includes(id) ? cols.filter((c) => c !== id) : [...cols, id]);
  const setSort = (col: string) => {
    if (sortCol === col) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortCol(col); setSortDir("desc"); }
  };
  // 정렬된 결과
  const sortedItems = (() => {
    if (!results) return [];
    const items = [...results.items];
    items.sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortCol], bv = (b as Record<string, unknown>)[sortCol];
      const an = typeof av === "number" ? av : -Infinity, bn = typeof bv === "number" ? bv : -Infinity;
      return sortDir === "desc" ? bn - an : an - bn;
    });
    return items;
  })();
  // 컬럼 값의 min/max (히트맵 바 정규화용)
  const colRange = (col: string): [number, number] => {
    const vals = sortedItems.map((it) => (it as Record<string, unknown>)[col]).filter((v): v is number => typeof v === "number");
    if (!vals.length) return [0, 1];
    return [Math.min(...vals), Math.max(...vals)];
  };

  // 조건식을 사람이 읽는 요약으로
  const conditionSummary = (): string[] => {
    const opMap: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=" };
    return group.conditions.map((c) => {
      const cc = c as { field: string; op?: string; value?: unknown; rank_mode?: string; rank_value?: number };
      if (cc.rank_mode) return `${fieldLabel(cc.field)} ${cc.rank_mode === "top_pct" ? "상위" : "하위"} ${cc.rank_value ?? 30}%`;
      return `${fieldLabel(cc.field)} ${opMap[cc.op || "gt"] || ">"} ${cc.value ?? 0}`;
    });
  };

  // 스크리너 조건식(전략)을 백테스터로 전송
  const sendToBacktester = () => {
    if (!group.conditions.length) return;
    setScreenerHandoff({
      filterAst: group,
      universe,
      conditionSummary: conditionSummary(),
      resultCount: results?.items.length ?? 0,
      createdAt: Date.now(),
    });
    router.push("/backtest");
  };

  // 프리셋 저장/불러오기/삭제
  const handleSavePreset = () => {
    if (!group.conditions.length) return;
    savePreset(presetName, group, universe);
    setPresets(listPresets());
    setPresetName("");
    setShowSaveDialog(false);
  };
  const handleLoadPreset = (p: ScreenerPreset) => {
    setGroup(JSON.parse(JSON.stringify(p.group)));
    setResults(null);
    setCount(null);
  };
  const handleDeletePreset = (id: string) => {
    deletePreset(id);
    setPresets(listPresets());
  };

  return (
    <div>
      {/* 자연어 검색 */}
      <div className="tnl-search">
        <div className="tnl-search-bar">
          <span className="tnl-search-icon">⌕</span>
          <input
            className="tnl-search-input"
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runNlSearch(nlQuery)}
            placeholder="자연어로 검색  ·  예: 부채 적고 배당 높은 방어주"
          />
          <button className="tnl-search-btn" onClick={() => runNlSearch(nlQuery)} disabled={nlLoading || !nlQuery.trim()}>
            {nlLoading ? "변환 중..." : "AI 검색"}
          </button>
        </div>
        {nlExamples.length > 0 && !nlResult && (
          <div className="tnl-examples">
            {nlExamples.slice(0, 5).map((ex) => (
              <button key={ex} className="tnl-example-chip" onClick={() => { setNlQuery(ex); runNlSearch(ex); }}>
                {ex}
              </button>
            ))}
          </div>
        )}
        {nlResult && (
          <div className="tnl-result">
            <span className="tnl-result-badge" style={{ background: nlResult.source === "claude" ? "#dcfce7" : "#fef3c7", color: nlResult.source === "claude" ? "#15803d" : "#a16207" }}>
              {nlResult.source === "claude" ? "AI 해석" : "규칙 해석"} · 신뢰도 {(nlResult.confidence * 100).toFixed(0)}%
            </span>
            <span className="tnl-result-text">{nlResult.explanation}</span>
          </div>
        )}
      </div>

      {/* 3-pane 워크스페이스 */}
      <div className="tscreener-workspace">
        {/* 카테고리 */}
        <div className="tscreener-cat">
          {/* 펀더멘털 / 기술적 토글 */}
          <div className="tind-mode-toggle">
            <button
              className={`tind-mode${indicatorMode === "fundamental" ? " active" : ""}`}
              onClick={() => setIndicatorMode("fundamental")}
            >펀더멘털</button>
            <button
              className={`tind-mode${indicatorMode === "technical" ? " active" : ""}`}
              onClick={() => setIndicatorMode("technical")}
            >기술적</button>
          </div>

          {indicatorMode === "fundamental"
            ? catalog?.categories.map((cat) => (
                <button
                  key={cat.id}
                  className={`tscreener-cat-item${activeCat === cat.id ? " active" : ""}`}
                  onClick={() => setActiveCat(cat.id)}
                >
                  {cat.label}
                  <span className="cat-count">{cat.fields.length}</span>
                </button>
              ))
            : techCatalog?.categories.map((cat) => (
                <button
                  key={cat.label}
                  className={`tscreener-cat-item${activeTechCat === cat.label ? " active" : ""}`}
                  onClick={() => setActiveTechCat(cat.label)}
                >
                  {cat.label}
                  <span className="cat-count">{cat.indicators.length}</span>
                </button>
              ))
          }
        </div>

        {/* 빌더 */}
        <div className="tscreener-builder">
          {group.conditions.length === 0 && (
            <div style={{ color: "var(--t-muted)", fontSize: 13, fontFamily: "var(--t-mono)" }}>
              [ NO_CONDITIONS ] — 우측 필드를 클릭해 조건을 추가하세요
            </div>
          )}
          {group.conditions.map((cond, idx) => {
            const c = cond as { field: string; op?: string; value?: unknown; kind?: string; rank_mode?: string; rank_value?: number };
            const isTech = c.kind === "technical";
            const isRank = !!c.rank_mode;
            return (
              <div key={idx} className={`tchip${isTech ? " tchip-tech" : ""}`}>
                <span className="tchip-field">{fieldLabel(c.field)}</span>
                {isRank ? (
                  <>
                    <span className="tchip-op">{c.rank_mode === "top_pct" ? "상위" : c.rank_mode === "bottom_pct" ? "하위" : "상위"}</span>
                    <input
                      className="tchip-input"
                      type="number"
                      value={String(c.rank_value ?? 30)}
                      onChange={(e) => updateCondition(idx, { rank_value: Number(e.target.value) || 0 })}
                    />
                    <span className="tchip-unit">%</span>
                  </>
                ) : (
                  <>
                    <select
                      className="tchip-op-select"
                      value={c.op || "gt"}
                      onChange={(e) => updateCondition(idx, { op: e.target.value })}
                    >
                      <option value="gt">&gt;</option>
                      <option value="gte">≥</option>
                      <option value="lt">&lt;</option>
                      <option value="lte">≤</option>
                      <option value="eq">=</option>
                    </select>
                    <input
                      className="tchip-input"
                      type="number"
                      step="any"
                      value={String(c.value ?? 0)}
                      onChange={(e) => updateCondition(idx, { value: e.target.value === "" ? 0 : Number(e.target.value) })}
                    />
                  </>
                )}
                <span className="tchip-remove" onClick={() => removeCondition(idx)}>✕</span>
              </div>
            );
          })}

          {/* 현재 카테고리의 필드/지표 (클릭하여 추가) */}
          <div style={{ marginTop: 8, borderTop: "1px solid var(--t-border)", paddingTop: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, gap: 12 }}>
              <span style={{ fontFamily: "var(--t-mono)", fontSize: 10, color: "var(--t-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {indicatorMode === "fundamental" ? activeCategory?.label : activeTechCategory?.label}
                <span style={{ marginLeft: 6, opacity: 0.6 }}>
                  {indicatorMode === "technical" ? "· 기술적 지표" : "· 펀더멘털"}
                </span>
              </span>
              <input
                className="tfield-search"
                value={fieldSearch}
                onChange={(e) => setFieldSearch(e.target.value)}
                placeholder="지표 검색..."
              />
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {indicatorMode === "fundamental"
                ? filteredFundFields.map((f) => (
                    <button key={f.id} className="tadd-condition" onClick={() => addCondition(f.id, f.label)}>
                      + {f.label}
                    </button>
                  ))
                : filteredTechInds.map((f) => (
                    <button key={f.id} className="tadd-condition tadd-technical" onClick={() => addTechnicalCondition(f.id)}>
                      + {f.label}
                    </button>
                  ))
              }
              {((indicatorMode === "fundamental" && filteredFundFields.length === 0) ||
                (indicatorMode === "technical" && filteredTechInds.length === 0)) && (
                <span style={{ color: "var(--t-muted)", fontSize: 12, fontFamily: "var(--t-mono)" }}>
                  검색 결과 없음
                </span>
              )}
            </div>
          </div>
        </div>

        {/* 스택 */}
        <div className="tscreener-stack">
          <div className="tstack-title">
            Active Filters
            <span className="tstack-count">{count !== null ? `${count} MATCHES` : "—"}</span>
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            {group.conditions.length === 0 ? (
              <div style={{ color: "var(--t-muted)", fontSize: 12 }}>조건 없음</div>
            ) : (
              group.conditions.map((cond, idx) => (
                <div key={idx} className="tapplied">
                  <span>{fieldLabel((cond as { field: string }).field)} {OPERATORS[(cond as { op?: string }).op || "gt"]} {String((cond as { value?: unknown }).value ?? "")}</span>
                  <span style={{ opacity: 0.3, cursor: "pointer" }} onClick={() => removeCondition(idx)}>✕</span>
                </div>
              ))
            )}
          </div>

          {/* 저장된 전략 (프리셋) */}
          <div className="tpreset-section">
            <div className="tpreset-head">
              <span>저장된 전략</span>
              <button
                className="tpreset-save-btn"
                onClick={() => setShowSaveDialog((v) => !v)}
                disabled={!group.conditions.length}
                title={group.conditions.length ? "현재 조건을 저장" : "조건을 먼저 추가하세요"}
              >
                + 저장
              </button>
            </div>
            {showSaveDialog && (
              <div className="tpreset-dialog">
                <input
                  className="tpreset-input"
                  placeholder="전략 이름 (예: 저PER 고배당)"
                  value={presetName}
                  onChange={(e) => setPresetName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleSavePreset(); }}
                  autoFocus
                />
                <button className="tpreset-confirm" onClick={handleSavePreset}>저장</button>
              </div>
            )}
            {presets.length === 0 ? (
              <div className="tpreset-empty">저장된 전략 없음</div>
            ) : (
              <div className="tpreset-list">
                {presets.map((p) => (
                  <div key={p.id} className="tpreset-chip">
                    <span className="tpreset-chip-name" onClick={() => handleLoadPreset(p)} title={`${p.group.conditions.length}개 조건 불러오기`}>
                      {p.name}
                      <span className="tpreset-chip-count">{p.group.conditions.length}</span>
                    </span>
                    <span className="tpreset-chip-del" onClick={() => handleDeletePreset(p.id)} title="삭제">✕</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <button className="texecute-btn" onClick={execute} disabled={loading || !group.conditions.length}>
            {loading ? "SCANNING..." : "EXECUTE SCAN [ENTER]"}
          </button>
        </div>
      </div>

      {/* 스캔 로딩 스켈레톤 */}
      {loading && (
        <div className="tresults animate-fade-in">
          <div className="tscan-loading">
            <span className="tscan-spinner" />
            <span className="tscan-text">SCANNING UNIVERSE · 종목별 지표 계산 중...</span>
          </div>
          <div className="tskeleton-table">
            {[...Array(8)].map((_, i) => (
              <div className="tskeleton-row" key={i}>
                {[...Array(6)].map((_, j) => (
                  <div className="tskeleton-cell" key={j} style={{ animationDelay: `${(i * 6 + j) * 0.04}s` }} />
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 결과 테이블 */}
      {results && !loading && (
        <div className="tresults animate-fade-in">
          <div className="tresults-toolbar">
            <span className="tresults-count">{sortedItems.length} RESULTS</span>
            <div className="tresults-actions">
              <button className="tcol-btn" onClick={() => setShowColPicker((v) => !v)}>
                ⚙ 컬럼 ({selectedCols.length})
              </button>
              <button className="tsend-bt-btn" onClick={sendToBacktester} title="이 조건식을 백테스터로 가져가 백테스팅">
                이 전략으로 백테스트 →
              </button>
            </div>
          </div>
          {showColPicker && (
            <div className="tcol-picker">
              <div className="tcol-picker-head">표시할 지표 선택 ({selectedCols.length})</div>
              <div className="tcol-picker-grid">
                {allColumns.map((c) => (
                  <label key={c.id} className={`tcol-chip${selectedCols.includes(c.id) ? " on" : ""}`}>
                    <input type="checkbox" checked={selectedCols.includes(c.id)} onChange={() => toggleCol(c.id)} />
                    {c.label}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className="tresults-scroll">
            <table className="tresults-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Company</th>
                  {selectedCols.map((col) => (
                    <th key={col} className="num sortable" onClick={() => setSort(col)}>
                      {colLabel(col)}{sortCol === col && (sortDir === "desc" ? " ▼" : " ▲")}
                    </th>
                  ))}
                  <th className="num sortable" onClick={() => setSort("composite_score")}>
                    Score{sortCol === "composite_score" && (sortDir === "desc" ? " ▼" : " ▲")}
                  </th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((it) => {
                  const vc = verdictColor(it.verdict);
                  return (
                    <tr
                      key={it.stock_code}
                      className={selectedTicker === it.stock_code ? "selected" : ""}
                      onClick={() => onSelect?.(it)}
                    >
                      <td className="tticker">{it.stock_code}</td>
                      <td>{it.corp_name}{it.sector && <span style={{ color: "var(--t-muted)", fontSize: 11, marginLeft: 8 }}>{it.sector}</span>}</td>
                      {selectedCols.map((col) => {
                        const v = (it as Record<string, unknown>)[col];
                        const [lo, hi] = colRange(col);
                        const pct = (typeof v === "number" && hi > lo) ? (v - lo) / (hi - lo) : 0;
                        return (
                          <td key={col} className="num tcell-bar">
                            <span className="tcell-fill" style={{ width: `${pct * 100}%` }} />
                            <span className="tcell-val">{fmtVal(v)}</span>
                          </td>
                        );
                      })}
                      <td className="num talpha-score">{it.composite_score.toFixed(1)}</td>
                      <td><span className="tverdict" style={{ background: vc.bg, color: vc.fg }}>{it.verdict}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {sortedItems.length === 0 && (
            <div style={{ padding: 48, textAlign: "center", color: "var(--t-muted)", fontSize: 13, fontFamily: "var(--t-mono)" }}>
              [ NO_MATCHES ] — 조건에 맞는 종목이 없습니다
            </div>
          )}
        </div>
      )}
    </div>
  );
}
