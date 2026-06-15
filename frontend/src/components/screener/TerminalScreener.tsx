"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// TerminalScreener — 버틀러 벤치마크 퀀트 스크리너
//   좌측 "내 필터" rail + 라이브 종목 리스트 + 팩터 추가 모달.
//   팩터(백테스터와 동일 라이브러리)를 추가하면 즉시 종목 리스트가 갱신되고,
//   종목을 누르면 "기업 분석 탭으로 가기" 액션이 떠 /insights 로 이동한다.
// ═══════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback, useMemo, Fragment, type MouseEvent as ReactMouseEvent } from "react";
import { useRouter } from "next/navigation";
import {
  screenerApiAdvanced, verdictColor,
  type FieldsCatalog, type TechnicalIndicatorCatalog,
  type FilterGroupNode, type FilterConditionNode,
  type ScreenerResponse,
} from "@/lib/screenerApi";
import { setScreenerHandoff } from "@/lib/screenerHandoff";

const OP_LABEL: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=" };
// 영문 카테고리 라벨 → 한글
const CAT_KO: Record<string, string> = { quality: "품질", safety: "안전성", composite: "종합", score: "종합 스코어" };

type PickKind = "field" | "technical";
interface PickItem {
  id: string; label: string; kind: PickKind; catLabel: string;
  unit?: string; higher_better?: boolean; typical_min?: number; typical_max?: number;
}
interface PickCat { id: string; label: string; items: PickItem[] }

function condText(c: FilterConditionNode, label: (id: string) => string): string {
  if (c.rank_mode) return `${label(c.field)} ${c.rank_mode === "top_pct" ? "상위" : "하위"} ${c.rank_value ?? 0}%`;
  return `${label(c.field)} ${OP_LABEL[c.op || "gt"] || ">"} ${c.value ?? 0}`;
}
function fmtVal(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    if (Math.abs(v) >= 10000) return Math.round(v).toLocaleString();
    if (Math.abs(v) >= 100) return v.toFixed(0);
    return v.toFixed(2);
  }
  return String(v);
}

export default function TerminalScreener({ universe }: { universe: string }) {
  const router = useRouter();
  const [catalog, setCatalog] = useState<FieldsCatalog | null>(null);
  const [techCatalog, setTechCatalog] = useState<TechnicalIndicatorCatalog | null>(null);
  const [group, setGroup] = useState<FilterGroupNode>({ logic: "AND", conditions: [], groups: [] });
  const [results, setResults] = useState<ScreenerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [sortCol, setSortCol] = useState("composite_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<string | null>(null);
  const [favs, setFavs] = useState<Set<string>>(new Set());

  // 팩터 추가 모달
  const [modalOpen, setModalOpen] = useState(false);
  const [mCat, setMCat] = useState("");
  const [mSearch, setMSearch] = useState("");
  const [mField, setMField] = useState<PickItem | null>(null);
  const [mMode, setMMode] = useState<"value" | "rank">("value");
  const [mOp, setMOp] = useState("gte");
  const [mValue, setMValue] = useState("0");
  const [mRankMode, setMRankMode] = useState<"top_pct" | "bottom_pct">("top_pct");
  const [mRankValue, setMRankValue] = useState("30");
  const [mPreview, setMPreview] = useState<number | null>(null);

  // 카탈로그 + 즐겨찾기 로드
  useEffect(() => {
    screenerApiAdvanced.fields().then(setCatalog).catch(() => {});
    screenerApiAdvanced.indicators().then(setTechCatalog).catch(() => {});
    try { const f = localStorage.getItem("alpha_screener_favs"); if (f) setFavs(new Set(JSON.parse(f))); } catch { /* noop */ }
  }, []);

  // 팩터 picker 카테고리 (펀더멘털 fields + 기술적 indicators 병합)
  const pickerCats: PickCat[] = useMemo(() => {
    const cats: PickCat[] = [];
    catalog?.categories.forEach((c) => cats.push({
      id: c.id, label: CAT_KO[c.id] ?? CAT_KO[c.label] ?? c.label,
      items: c.fields.map((f) => ({
        id: f.id, label: f.label, kind: "field", catLabel: CAT_KO[c.id] ?? c.label,
        unit: f.unit, higher_better: f.higher_better, typical_min: f.typical_min, typical_max: f.typical_max,
      })),
    }));
    techCatalog?.categories.forEach((c) => cats.push({
      id: "tech_" + c.label, label: `${c.label} · 기술적`,
      items: c.indicators.map((i) => ({
        id: i.id, label: i.label, kind: "technical", catLabel: c.label,
        unit: i.unit, typical_min: i.typical_min, typical_max: i.typical_max,
      })),
    }));
    return cats;
  }, [catalog, techCatalog]);

  useEffect(() => { if (pickerCats.length && !mCat) setMCat(pickerCats[0].id); }, [pickerCats, mCat]);

  const flatItems = useMemo(() => pickerCats.flatMap((c) => c.items), [pickerCats]);
  const fieldLabel = useCallback((id: string) => flatItems.find((f) => f.id === id)?.label ?? id, [flatItems]);

  // ── 라이브 스크리닝 (group 변경 시 디바운스 실행) ──
  useEffect(() => {
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const r = await screenerApiAdvanced.runAdvanced({
          universe, filter_ast: group, sort_by: "composite_score",
          ascending: false, limit: 200, liquidity_floor: "relaxed",
        });
        setResults(r);
      } catch { /* noop */ }
      finally { setLoading(false); }
    }, 350);
    return () => clearTimeout(t);
  }, [group, universe]);

  // 모달 draft 조건
  const draftCondition = useCallback((): FilterConditionNode | null => {
    if (!mField) return null;
    const base = { kind: mField.kind, field: mField.id } as FilterConditionNode;
    if (mField.kind === "technical") base.indicator = mField.id;
    if (mMode === "rank") { base.rank_mode = mRankMode; base.rank_value = Number(mRankValue) || 0; }
    else { base.op = mOp as FilterConditionNode["op"]; base.value = Number(mValue) || 0; }
    return base;
  }, [mField, mMode, mOp, mValue, mRankMode, mRankValue]);

  // ── 모달 실시간 미리보기 카운트 ──
  useEffect(() => {
    if (!modalOpen || !mField) { setMPreview(null); return; }
    const dc = draftCondition();
    if (!dc) return;
    const t = setTimeout(async () => {
      try {
        const r = await screenerApiAdvanced.count({ universe, filter_ast: { ...group, conditions: [...group.conditions, dc] }, limit: 1 });
        setMPreview(r.total_passed);
      } catch { setMPreview(null); }
    }, 300);
    return () => clearTimeout(t);
  }, [modalOpen, mField, draftCondition, group, universe]);

  const selectField = (f: PickItem) => {
    setMField(f); setMMode("value");
    const hb = f.higher_better ?? true;
    setMOp(hb ? "gte" : "lte");
    const dv = hb ? (f.typical_min ?? 0) : (f.typical_max ?? 0);
    setMValue(String(Math.round((dv as number) * 100) / 100));
  };

  const addFactor = () => {
    const dc = draftCondition();
    if (!dc) return;
    setGroup((g) => ({ ...g, conditions: [...g.conditions, dc] }));
    setModalOpen(false); setMField(null); setMSearch("");
  };
  const removeCondition = (idx: number) => setGroup((g) => ({ ...g, conditions: g.conditions.filter((_, i) => i !== idx) }));
  const updateCondition = (idx: number, patch: Partial<FilterConditionNode>) =>
    setGroup((g) => ({ ...g, conditions: g.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c)) }));
  const clearAll = () => { setGroup({ logic: "AND", conditions: [], groups: [] }); setSelected(null); };

  const toggleFav = (code: string, e: ReactMouseEvent) => {
    e.stopPropagation();
    setFavs((s) => {
      const n = new Set(s); if (n.has(code)) n.delete(code); else n.add(code);
      try { localStorage.setItem("alpha_screener_favs", JSON.stringify([...n])); } catch { /* noop */ }
      return n;
    });
  };
  const setSort = (col: string) => {
    if (sortCol === col) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortCol(col); setSortDir("desc"); }
  };
  const sortArrow = (col: string) => (sortCol === col ? (sortDir === "desc" ? " ▼" : " ▲") : "");

  const goToCompany = (code: string, e: ReactMouseEvent) => {
    e.stopPropagation();
    try { sessionStorage.setItem("alpha_company_ticker", code); } catch { /* noop */ }
    router.push("/insights");
  };
  const sendToBacktester = () => {
    if (!group.conditions.length) return;
    setScreenerHandoff({
      filterAst: group, universe,
      conditionSummary: group.conditions.map((c) => condText(c, fieldLabel)),
      resultCount: results?.items.length ?? 0, createdAt: Date.now(),
    });
    router.push("/backtest");
  };

  // 추가된 팩터 → 동적 컬럼 (중복 제거)
  const factorCols = useMemo(() => {
    const seen = new Set<string>(); const cols: { id: string; label: string }[] = [];
    group.conditions.forEach((c) => {
      const f = c.field;
      if (f && !seen.has(f)) { seen.add(f); cols.push({ id: f, label: fieldLabel(f) }); }
    });
    return cols;
  }, [group, fieldLabel]);

  const sortedItems = useMemo(() => {
    if (!results) return [];
    return [...results.items].sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortCol], bv = (b as Record<string, unknown>)[sortCol];
      const an = typeof av === "number" && Number.isFinite(av) ? av : -Infinity;
      const bn = typeof bv === "number" && Number.isFinite(bv) ? bv : -Infinity;
      return sortDir === "desc" ? bn - an : an - bn;
    });
  }, [results, sortCol, sortDir]);

  const total = results?.total_passed ?? null;
  const modalItems = mSearch
    ? flatItems.filter((f) => f.label.toLowerCase().includes(mSearch.toLowerCase()) || f.id.includes(mSearch.toLowerCase()))
    : (pickerCats.find((c) => c.id === mCat)?.items ?? []);
  const colSpan = 6 + factorCols.length;

  return (
    <div>
      <div className="bsc-workspace">
        {/* ── 좌측: 내 필터 ── */}
        <aside className="bsc-rail">
          <div className="bsc-rail-head">
            <span className="bsc-rail-title">내 필터</span>
            {group.conditions.length > 0 && <button className="bsc-rail-clear" onClick={clearAll}>전체 초기화</button>}
          </div>
          <button className="bsc-add-btn" onClick={() => setModalOpen(true)}>＋ 팩터 추가</button>
          {group.conditions.length === 0 ? (
            <div className="bsc-rail-empty">아직 추가된 팩터가 없습니다.<br />「＋ 팩터 추가」로 조건을 더하면 전 종목이 즉시 필터링됩니다.</div>
          ) : (
            <div className="bsc-rail-list">
              {group.conditions.map((c, i) => (
                <div key={i} className="bsc-rail-item">
                  <div className="bsc-rail-item-body">
                    <div className="bsc-rail-item-name">
                      {fieldLabel(c.field)}
                      {c.kind === "technical" && <span className="bsc-field-tech" style={{ marginLeft: 6 }}>기술</span>}
                    </div>
                    <div className="bsc-rail-item-cond">{condText(c, fieldLabel)}</div>
                  </div>
                  <span className="bsc-rail-item-del" onClick={() => removeCondition(i)}>✕</span>
                </div>
              ))}
            </div>
          )}
        </aside>

        {/* ── 우측: 필터 칩 + 카운트 + 종목 리스트 ── */}
        <div className="bsc-main">
          <div className="bsc-toolbar">
            <span className="bsc-toolbar-label">필터 추가하기</span>
            {group.conditions.length === 0 && <span style={{ fontSize: 12, color: "var(--t-muted)" }}>조건 없음 — 전체 종목 표시 중</span>}
            {group.conditions.map((c, idx) => {
              const isRank = !!c.rank_mode;
              return (
                <span key={idx} className={`bsc-chip${c.kind === "technical" ? " bsc-chip-tech" : ""}`}>
                  <span className="bsc-chip-name">{fieldLabel(c.field)}</span>
                  {isRank ? (
                    <>
                      <select className="bsc-chip-op" value={c.rank_mode!} onChange={(e) => updateCondition(idx, { rank_mode: e.target.value as FilterConditionNode["rank_mode"] })}>
                        <option value="top_pct">상위</option><option value="bottom_pct">하위</option>
                      </select>
                      <input className="bsc-chip-val" type="number" value={String(c.rank_value ?? 30)} onChange={(e) => updateCondition(idx, { rank_value: Number(e.target.value) || 0 })} />
                      <span style={{ fontSize: 11, color: "var(--t-muted)" }}>%</span>
                    </>
                  ) : (
                    <>
                      <select className="bsc-chip-op" value={c.op || "gte"} onChange={(e) => updateCondition(idx, { op: e.target.value as FilterConditionNode["op"] })}>
                        <option value="gt">&gt;</option><option value="gte">≥</option><option value="lt">&lt;</option><option value="lte">≤</option><option value="eq">=</option>
                      </select>
                      <input className="bsc-chip-val" type="number" step="any" value={String(c.value ?? 0)} onChange={(e) => updateCondition(idx, { value: e.target.value === "" ? 0 : Number(e.target.value) })} />
                    </>
                  )}
                  <span className="bsc-chip-del" onClick={() => removeCondition(idx)}>✕</span>
                </span>
              );
            })}
            <button className="bsc-chip-add" onClick={() => setModalOpen(true)}>＋ 팩터</button>
          </div>

          <div className="bsc-countbar">
            <span className="bsc-count">검색된 기업 <b>{total != null ? total.toLocaleString() : "—"}</b>개</span>
            {loading && <span className="bsc-spinner" />}
            <span className="bsc-countbar-spacer" />
            <button className="bsc-bt-btn" onClick={sendToBacktester} disabled={!group.conditions.length} title="이 조건식을 백테스터로 전달">
              이 전략 백테스트 →
            </button>
          </div>

          <div className="bsc-table-wrap">
            <table className="bsc-table">
              <thead>
                <tr>
                  <th className="bsc-rank">#</th>
                  <th />
                  <th>종목명</th>
                  <th className="num sortable" onClick={() => setSort("current_price")}>현재가{sortArrow("current_price")}</th>
                  <th className="num sortable" onClick={() => setSort("market_cap_억")}>시총(억){sortArrow("market_cap_억")}</th>
                  {factorCols.map((fc) => (
                    <th key={fc.id} className="num sortable" onClick={() => setSort(fc.id)}>{fc.label}{sortArrow(fc.id)}</th>
                  ))}
                  <th className="num sortable" onClick={() => setSort("composite_score")}>종합점수{sortArrow("composite_score")}</th>
                  <th>판정</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((it, i) => {
                  const vc = verdictColor(it.verdict);
                  const isSel = selected === it.stock_code;
                  return (
                    <Fragment key={it.stock_code}>
                      <tr className={`bsc-row${isSel ? " selected" : ""}`} onClick={() => setSelected(isSel ? null : it.stock_code)}>
                        <td className="bsc-rank">{i + 1}</td>
                        <td>
                          <span className={`bsc-fav${favs.has(it.stock_code) ? " on" : ""}`} onClick={(e) => toggleFav(it.stock_code, e)}>
                            {favs.has(it.stock_code) ? "★" : "☆"}
                          </span>
                        </td>
                        <td><span className="bsc-name">{it.corp_name}</span>{it.sector && <span className="bsc-sector">{it.sector}</span>}</td>
                        <td className="num">{typeof it.current_price === "number" ? `${it.current_price.toLocaleString()}원` : "—"}</td>
                        <td className="num">{it.market_cap_억 != null ? Math.round(it.market_cap_억).toLocaleString() : "—"}</td>
                        {factorCols.map((fc) => (
                          <td key={fc.id} className="num">{fmtVal((it as Record<string, unknown>)[fc.id])}</td>
                        ))}
                        <td className="num bsc-score" style={{ color: vc.fg }}>{it.composite_score.toFixed(1)}</td>
                        <td><span className="tverdict" style={{ background: vc.bg, color: vc.fg }}>{it.verdict}</span></td>
                      </tr>
                      {isSel && (
                        <tr className="bsc-action-row">
                          <td colSpan={colSpan}>
                            <div className="bsc-action-inner">
                              <span className="bsc-action-text">
                                <b>{it.corp_name}</b> ({it.stock_code}) · 현재가 {typeof it.current_price === "number" ? it.current_price.toLocaleString() : "—"}원 · 종합점수 {it.composite_score.toFixed(1)} · {it.verdict}
                              </span>
                              <button className="bsc-go-company" onClick={(e) => goToCompany(it.stock_code, e)}>기업 분석 탭으로 가기 →</button>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {!loading && sortedItems.length === 0 && <div className="bsc-empty">[ NO_MATCHES ] 조건에 맞는 종목이 없습니다</div>}
          </div>
        </div>
      </div>

      {/* ── 팩터 추가 모달 ── */}
      {modalOpen && (
        <div className="bsc-modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="bsc-modal" onClick={(e) => e.stopPropagation()}>
            <div className="bsc-modal-head">
              <div className="bsc-modal-search">
                <span style={{ color: "var(--t-muted)" }}>⌕</span>
                <input value={mSearch} onChange={(e) => setMSearch(e.target.value)} placeholder="팩터를 직접 검색해 보세요  ·  예: ROE, PER, 부채비율, RSI" autoFocus />
              </div>
              <button className="bsc-modal-x" onClick={() => setModalOpen(false)}>✕</button>
            </div>
            <div className="bsc-modal-body">
              {/* 카테고리 */}
              <div className="bsc-modal-col">
                {!mSearch ? pickerCats.map((c) => (
                  <button key={c.id} className={`bsc-cat-item${mCat === c.id ? " active" : ""}`} onClick={() => setMCat(c.id)}>
                    <span>{c.label}</span><span className="bsc-cat-count">{c.items.length}</span>
                  </button>
                )) : (
                  <div style={{ padding: "8px 10px", fontSize: 11, color: "var(--t-muted)", fontFamily: "var(--t-mono)" }}>
                    검색 결과 {modalItems.length}건
                  </div>
                )}
              </div>
              {/* 팩터 목록 */}
              <div className="bsc-modal-col">
                {modalItems.slice(0, 300).map((f) => (
                  <button key={f.kind + f.id} className={`bsc-field-item${mField?.id === f.id && mField?.kind === f.kind ? " active" : ""}`} onClick={() => selectField(f)}>
                    <span>{f.label}</span>
                    {f.kind === "technical" ? <span className="bsc-field-tech">기술</span> : <span className="bsc-cat-count">{f.catLabel}</span>}
                  </button>
                ))}
                {modalItems.length === 0 && <div style={{ padding: "8px 10px", fontSize: 12, color: "var(--t-muted)" }}>검색 결과 없음</div>}
              </div>
              {/* 조건 편집 */}
              <div className="bsc-editor">
                {mField ? (
                  <>
                    <div className="bsc-editor-label">{mField.label}</div>
                    <div className="bsc-editor-meta">
                      {mField.catLabel}{mField.unit ? ` · ${mField.unit}` : ""}{mField.kind === "technical" ? " · 기술적 지표" : ""}
                    </div>
                    <div className="bsc-editor-modetabs">
                      <button className={`bsc-editor-modetab${mMode === "value" ? " active" : ""}`} onClick={() => setMMode("value")}>기준값</button>
                      <button className={`bsc-editor-modetab${mMode === "rank" ? " active" : ""}`} onClick={() => setMMode("rank")}>순위</button>
                    </div>
                    {mMode === "value" ? (
                      <div className="bsc-editor-row">
                        <select className="bsc-editor-op" value={mOp} onChange={(e) => setMOp(e.target.value)}>
                          <option value="gte">이상 (≥)</option><option value="gt">초과 (&gt;)</option>
                          <option value="lte">이하 (≤)</option><option value="lt">미만 (&lt;)</option><option value="eq">같음 (=)</option>
                        </select>
                        <input className="bsc-editor-input" type="number" step="any" value={mValue} onChange={(e) => setMValue(e.target.value)} />
                        {mField.unit && <span style={{ color: "var(--t-muted)", fontSize: 13 }}>{mField.unit}</span>}
                      </div>
                    ) : (
                      <div className="bsc-editor-row">
                        <select className="bsc-editor-op" value={mRankMode} onChange={(e) => setMRankMode(e.target.value as "top_pct" | "bottom_pct")}>
                          <option value="top_pct">상위</option><option value="bottom_pct">하위</option>
                        </select>
                        <input className="bsc-editor-input" type="number" value={mRankValue} onChange={(e) => setMRankValue(e.target.value)} />
                        <span style={{ color: "var(--t-muted)", fontSize: 13 }}>%</span>
                      </div>
                    )}
                    {mField.typical_min != null && mField.typical_max != null && (
                      <div className="bsc-editor-range">일반 범위 {mField.typical_min} ~ {mField.typical_max}</div>
                    )}
                    <div className="bsc-editor-preview">
                      {mPreview != null ? <>이 조건 적용 시 <b>{mPreview.toLocaleString()}</b>개 종목</> : <span style={{ color: "var(--t-muted)" }}>미리보기 계산 중…</span>}
                    </div>
                  </>
                ) : (
                  <div style={{ margin: "auto", color: "var(--t-muted)", fontSize: 13, textAlign: "center" }}>왼쪽에서 팩터를 선택하세요</div>
                )}
              </div>
            </div>
            <div className="bsc-modal-foot">
              <span className="bsc-modal-hint">{flatItems.length}개 스크리닝 팩터 · 백테스터와 동일 라이브러리</span>
              <button className="bsc-modal-add" disabled={!mField} onClick={addFactor}>＋ 이 팩터 추가</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
