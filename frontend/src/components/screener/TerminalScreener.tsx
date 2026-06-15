"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// TerminalScreener — 버틀러 벤치마크 퀀트 스크리너
//   · '팩터 추가' → 백테스터와 동일한 FactorPickerModal(똑같은 창)을 그대로 사용.
//     고른 팩터는 factor-field-map 으로 스크리너 필드 id 로 해석 → 즉시 라이브 필터링.
//   · 좌측 '내 필터' rail(AND/OR · 저장된 전략) + 라이브 종목 리스트 + 진행 표시 + CSV.
//   · 종목 클릭 → '기업 분석 탭으로 가기' → /insights 핸드오프.
// ═══════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback, useMemo, Fragment, type MouseEvent as ReactMouseEvent } from "react";
import { useRouter } from "next/navigation";
import {
  screenerApiAdvanced, screenerApi, verdictColor,
  type FieldsCatalog, type TechnicalIndicatorCatalog,
  type FilterGroupNode, type FilterConditionNode, type ScreenerResponse,
} from "@/lib/screenerApi";
import { setScreenerHandoff } from "@/lib/screenerHandoff";
import { listPresets, savePreset, deletePreset, type ScreenerPreset } from "@/lib/screenerPresets";
import FactorPickerModal, { type FactorPick } from "@/components/backtest/FactorPickerModal";

const OP_LABEL: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=" };
// 시가총액 빠른 필터 프리셋 (억 단위). 실데이터(KIS) 연결 시 market_cap_억 채워져 동작.
const MCAP_PRESETS: Array<{ id: string; label: string; min: number | null; max: number | null }> = [
  { id: "large", label: "대형 1조+", min: 10000, max: null },
  { id: "mid", label: "중형 2천억~1조", min: 2000, max: 10000 },
  { id: "small", label: "소형 ~2천억", min: null, max: 2000 },
];

interface FieldMeta { higher_better?: boolean; typical_min?: number; typical_max?: number; label: string; unit?: string }

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
  const [aliasMap, setAliasMap] = useState<Record<string, string>>({});
  const [universeSizes, setUniverseSizes] = useState<Record<string, number>>({});
  const [group, setGroup] = useState<FilterGroupNode>({ logic: "AND", conditions: [], groups: [] });
  const [labelOverride, setLabelOverride] = useState<Record<string, string>>({});
  const [results, setResults] = useState<ScreenerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [prog, setProg] = useState<{ done: number; total: number; misses: number } | null>(null);
  const [chipCounts, setChipCounts] = useState<(number | null)[]>([]);
  const [sortCol, setSortCol] = useState("composite_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<string | null>(null);
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // 저장된 전략(프리셋)
  const [presets, setPresets] = useState<ScreenerPreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [showSave, setShowSave] = useState(false);

  // 카탈로그 / 매핑 / 즐겨찾기 / 프리셋 로드
  useEffect(() => {
    screenerApiAdvanced.fields().then(setCatalog).catch(() => {});
    screenerApiAdvanced.indicators().then(setTechCatalog).catch(() => {});
    screenerApiAdvanced.factorFieldMap().then((d) => setAliasMap(d.map)).catch(() => {});
    screenerApi.universes().then((d) => {
      const m: Record<string, number> = {}; d.presets.forEach((p) => { m[p.id] = p.size; }); setUniverseSizes(m);
    }).catch(() => {});
    try { const f = localStorage.getItem("alpha_screener_favs"); if (f) setFavs(new Set(JSON.parse(f))); } catch { /* noop */ }
    setPresets(listPresets());
  }, []);

  // ── 팩터 해석용 인덱스 ──
  const { labelToId, idSet, techIdSet, metaById } = useMemo(() => {
    const labelToId = new Map<string, string>();
    const idSet = new Set<string>();
    const techIdSet = new Set<string>();
    const metaById = new Map<string, FieldMeta>();
    catalog?.categories.forEach((c) => c.fields.forEach((f) => {
      idSet.add(f.id);
      labelToId.set(f.label, f.id); labelToId.set(f.label.replace(/\s+/g, ""), f.id); labelToId.set(f.label.toLowerCase(), f.id);
      metaById.set(f.id, { higher_better: f.higher_better, typical_min: f.typical_min, typical_max: f.typical_max, label: f.label, unit: f.unit });
    }));
    techCatalog?.categories.forEach((c) => c.indicators.forEach((i) => {
      idSet.add(i.id); techIdSet.add(i.id);
      labelToId.set(i.label, i.id); labelToId.set(i.label.replace(/\s+/g, ""), i.id);
      metaById.set(i.id, { typical_min: i.typical_min, typical_max: i.typical_max, label: i.label, unit: i.unit });
    }));
    return { labelToId, idSet, techIdSet, metaById };
  }, [catalog, techCatalog]);

  const fieldLabel = useCallback((id: string) => labelOverride[id] ?? metaById.get(id)?.label ?? id, [labelOverride, metaById]);

  // 젠포트 팩터 이름 → 스크리너 필드 id (별칭맵 → 라벨맵)
  const resolveFactor = useCallback((name: string): { id: string; kind: "field" | "technical" } | null => {
    const n = name.trim().replace(/^\{+|\}+$/g, "").trim();
    const id = aliasMap[n] ?? labelToId.get(n) ?? labelToId.get(n.replace(/\s+/g, "")) ?? labelToId.get(n.toLowerCase());
    if (!id) return null;
    return { id, kind: techIdSet.has(id) ? "technical" : "field" };
  }, [aliasMap, labelToId, techIdSet]);

  // FactorPickerModal 에서 팩터를 고르면 → 조건 추가 (똑같은 창, 스크리너로 연동)
  const handlePick = useCallback((pick: FactorPick) => {
    setModalOpen(false);
    const r = resolveFactor(pick.factorName);
    if (!r) {
      setNotice(`‘${pick.factorName}’은(는) 단면 스크리닝에서 지원되지 않습니다 (백테스터 전용 시계열·수급 팩터).`);
      return;
    }
    setNotice(null);
    const meta = metaById.get(r.id);
    const isRank = pick.functionId === "rank";
    const cond: FilterConditionNode = isRank
      ? { kind: r.kind, field: r.id, ...(r.kind === "technical" ? { indicator: r.id } : {}), rank_mode: "top_pct", rank_value: 30 }
      : {
          kind: r.kind, field: r.id, ...(r.kind === "technical" ? { indicator: r.id } : {}),
          op: (meta?.higher_better ?? true) ? "gte" : "lte",
          value: meta ? Math.round(((meta.higher_better ?? true ? meta.typical_min : meta.typical_max) ?? 0) * 100) / 100 : 0,
        };
    setLabelOverride((m) => ({ ...m, [r.id]: meta?.label ?? pick.factorName }));
    setGroup((g) => ({ ...g, conditions: [...g.conditions, cond] }));
  }, [resolveFactor, metaById]);

  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(null), 5000); return () => clearTimeout(t); }, [notice]);

  // ── 라이브 스크리닝 (SSE 스트리밍 — 종목별 진행 실시간 + 최종 결과) ──
  useEffect(() => {
    setLoading(true); setProg(null);
    const ctrl = new AbortController();
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await screenerApiAdvanced.runAdvancedStream(
          { universe, filter_ast: group, sort_by: "composite_score", ascending: false, limit: 200, liquidity_floor: "relaxed" },
          (done, total, misses) => { if (!cancelled) setProg({ done, total, misses }); },
          ctrl.signal,
        );
        if (!cancelled) setResults(r);
      } catch { /* aborted or error */ }
      finally { if (!cancelled) setLoading(false); }
    }, 350);
    return () => { cancelled = true; ctrl.abort(); clearTimeout(t); };
  }, [group, universe]);

  // ── 칩별 미리보기 카운트 (각 조건 단독 통과 종목 수, 디바운스) ──
  useEffect(() => {
    if (!group.conditions.length) { setChipCounts([]); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      const counts = await Promise.all(group.conditions.map((c) =>
        screenerApiAdvanced.count({ universe, filter_ast: { logic: "AND", conditions: [c], groups: [] }, limit: 1 })
          .then((r) => r.total_passed).catch(() => null),
      ));
      if (!cancelled) setChipCounts(counts);
    }, 450);
    return () => { cancelled = true; clearTimeout(t); };
  }, [group, universe]);

  const removeCondition = (idx: number) => setGroup((g) => ({ ...g, conditions: g.conditions.filter((_, i) => i !== idx) }));
  const updateCondition = (idx: number, patch: Partial<FilterConditionNode>) =>
    setGroup((g) => ({ ...g, conditions: g.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c)) }));
  const clearAll = () => { setGroup({ logic: "AND", conditions: [], groups: [] }); setSelected(null); };
  const toggleLogic = () => setGroup((g) => ({ ...g, logic: g.logic === "AND" ? "OR" : "AND" }));
  // 시가총액 빠른 필터 — market_cap_억 조건 교체
  const applyMcap = (min: number | null, max: number | null) => {
    setGroup((g) => {
      const conds = g.conditions.filter((c) => c.field !== "market_cap_억");
      if (min != null) conds.push({ kind: "field", field: "market_cap_억", op: "gte", value: min });
      if (max != null) conds.push({ kind: "field", field: "market_cap_억", op: "lte", value: max });
      return { ...g, conditions: conds };
    });
    setLabelOverride((m) => ({ ...m, market_cap_억: "시가총액" }));
  };
  const mcapActive = group.conditions.some((c) => c.field === "market_cap_억");

  const toggleFav = (code: string, e: ReactMouseEvent) => {
    e.stopPropagation();
    setFavs((s) => { const n = new Set(s); if (n.has(code)) n.delete(code); else n.add(code);
      try { localStorage.setItem("alpha_screener_favs", JSON.stringify([...n])); } catch { /* noop */ } return n; });
  };
  const setSort = (col: string) => { if (sortCol === col) setSortDir((d) => (d === "desc" ? "asc" : "desc")); else { setSortCol(col); setSortDir("desc"); } };
  const sortArrow = (col: string) => (sortCol === col ? (sortDir === "desc" ? " ▼" : " ▲") : "");

  const goToCompany = (code: string, e: ReactMouseEvent) => {
    e.stopPropagation();
    try { sessionStorage.setItem("alpha_company_ticker", code); } catch { /* noop */ }
    router.push("/insights");
  };
  const sendToBacktester = () => {
    if (!group.conditions.length) return;
    setScreenerHandoff({ filterAst: group, universe, conditionSummary: group.conditions.map((c) => condText(c, fieldLabel)), resultCount: results?.items.length ?? 0, createdAt: Date.now() });
    router.push("/backtest");
  };

  // 프리셋 저장/불러오기/삭제
  const handleSave = () => { if (!group.conditions.length || !presetName.trim()) return; savePreset(presetName.trim(), group, universe); setPresets(listPresets()); setPresetName(""); setShowSave(false); };
  const handleLoad = (p: ScreenerPreset) => { setGroup(JSON.parse(JSON.stringify(p.group))); setSelected(null); };
  const handleDelete = (id: string, e: ReactMouseEvent) => { e.stopPropagation(); deletePreset(id); setPresets(listPresets()); };

  const factorCols = useMemo(() => {
    const seen = new Set<string>(); const cols: { id: string; label: string }[] = [];
    group.conditions.forEach((c) => { if (c.field && !seen.has(c.field)) { seen.add(c.field); cols.push({ id: c.field, label: fieldLabel(c.field) }); } });
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

  const exportCsv = () => {
    if (!sortedItems.length) return;
    const header = ["순위", "종목코드", "종목명", "섹터", "현재가", "시총(억)", ...factorCols.map((c) => c.label), "종합점수", "판정"];
    const rows = sortedItems.map((it, i) => [
      i + 1, it.stock_code, it.corp_name, it.sector ?? "",
      typeof it.current_price === "number" ? it.current_price : "",
      it.market_cap_억 ?? "",
      ...factorCols.map((c) => { const v = (it as Record<string, unknown>)[c.id]; return typeof v === "number" ? v : ""; }),
      it.composite_score, it.verdict,
    ]);
    const esc = (v: unknown) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = [header, ...rows].map((r) => r.map(esc).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = `screener_${universe}_${Date.now()}.csv`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };

  const total = results?.total_passed ?? null;
  const uniTotal = universeSizes[universe] ?? results?.total_evaluated ?? 0;
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

          {/* 시가총액 빠른 필터 (버틀러식) */}
          <div className="bsc-mcap">
            <div className="bsc-mcap-head">시가총액</div>
            <div className="bsc-mcap-btns">
              <button className={`bsc-mcap-btn${!mcapActive ? " active" : ""}`} onClick={() => applyMcap(null, null)}>전체</button>
              {MCAP_PRESETS.map((p) => (
                <button key={p.id} className="bsc-mcap-btn" onClick={() => applyMcap(p.min, p.max)}>{p.label}</button>
              ))}
            </div>
            <div className="bsc-mcap-note">ⓘ 실데이터 연결 시 동작 (mock은 시총 미제공)</div>
          </div>

          {group.conditions.length >= 2 && (
            <div className="bsc-logic">
              <span className="bsc-logic-label">조건 결합</span>
              <button className="bsc-logic-toggle" onClick={toggleLogic}>
                <span className={group.logic === "AND" ? "on" : ""}>모두(AND)</span>
                <span className={group.logic === "OR" ? "on" : ""}>하나(OR)</span>
              </button>
            </div>
          )}

          {group.conditions.length === 0 ? (
            <div className="bsc-rail-empty">아직 추가된 팩터가 없습니다.<br />「＋ 팩터 추가」로 조건을 더하면 전 종목이 즉시 필터링됩니다.</div>
          ) : (
            <div className="bsc-rail-list">
              {group.conditions.map((c, i) => (
                <div key={i} className="bsc-rail-item">
                  <div className="bsc-rail-item-body">
                    <div className="bsc-rail-item-name">{fieldLabel(c.field)}{c.kind === "technical" && <span className="bsc-field-tech" style={{ marginLeft: 6 }}>기술</span>}</div>
                    <div className="bsc-rail-item-cond">{condText(c, fieldLabel)}</div>
                  </div>
                  <span className="bsc-rail-item-del" onClick={() => removeCondition(i)}>✕</span>
                </div>
              ))}
            </div>
          )}

          {/* 저장된 전략 (프리셋) */}
          <div className="bsc-preset">
            <div className="bsc-preset-head">
              <span>저장된 전략</span>
              <button className="bsc-preset-save" disabled={!group.conditions.length} onClick={() => setShowSave((v) => !v)}>＋ 저장</button>
            </div>
            {showSave && (
              <div className="bsc-preset-dialog">
                <input className="bsc-preset-input" placeholder="전략 이름 (예: 저PER 저PBR)" value={presetName} autoFocus
                  onChange={(e) => setPresetName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }} />
                <button className="bsc-preset-confirm" onClick={handleSave}>저장</button>
              </div>
            )}
            {presets.length === 0 ? (
              <div className="bsc-preset-empty">저장된 전략 없음</div>
            ) : (
              <div className="bsc-preset-list">
                {presets.map((p) => (
                  <div key={p.id} className="bsc-preset-chip" onClick={() => handleLoad(p)} title={`${p.group.conditions.length}개 조건 불러오기`}>
                    <span className="bsc-preset-chip-name">{p.name}</span>
                    <span className="bsc-preset-chip-count">{p.group.conditions.length}</span>
                    <span className="bsc-preset-chip-del" onClick={(e) => handleDelete(p.id, e)}>✕</span>
                  </div>
                ))}
              </div>
            )}
          </div>
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
                  {chipCounts[idx] != null && <span className="bsc-chip-count" title="이 조건 단독 통과 종목 수">{chipCounts[idx]!.toLocaleString()}</span>}
                  <span className="bsc-chip-del" onClick={() => removeCondition(idx)}>✕</span>
                </span>
              );
            })}
            <button className="bsc-chip-add" onClick={() => setModalOpen(true)}>＋ 팩터</button>
          </div>

          {notice && <div className="bsc-notice">{notice}</div>}

          <div className="bsc-countbar">
            <span className="bsc-count">검색된 기업 <b>{total != null ? total.toLocaleString() : "—"}</b>개{group.conditions.length >= 2 ? ` · ${group.logic === "AND" ? "모든 조건" : "하나라도"}` : ""}</span>
            {loading && <span className="bsc-spinner" />}
            <span className="bsc-countbar-spacer" />
            <button className="bsc-bt-btn" onClick={exportCsv} disabled={!sortedItems.length} title="현재 결과를 CSV로 내보내기">⤓ CSV</button>
            <button className="bsc-bt-btn" onClick={sendToBacktester} disabled={!group.conditions.length} title="이 조건식을 백테스터로 전달">이 전략 백테스트 →</button>
          </div>
          {/* 데이터 확충 진행 (실시간 SSE — 작은 글씨) */}
          <div className="bsc-progress">
            {loading
              ? <>데이터 확충 중… <b>{(prog?.done ?? 0).toLocaleString()}</b>/{(prog?.total ?? uniTotal).toLocaleString()} 종목 업데이트{prog && prog.misses > 0 ? ` · 신규 ${prog.misses.toLocaleString()}` : ""}</>
              : results
                ? <>평가 완료 <b>{results.total_evaluated.toLocaleString()}</b>/{uniTotal.toLocaleString()} 종목 · 신규 {results.cache_misses.toLocaleString()} · 캐시 {results.cache_hits.toLocaleString()} · {results.elapsed_seconds.toFixed(2)}s</>
                : <>대기 중…</>}
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
                  {factorCols.map((fc) => <th key={fc.id} className="num sortable" onClick={() => setSort(fc.id)}>{fc.label}{sortArrow(fc.id)}</th>)}
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
                        <td><span className={`bsc-fav${favs.has(it.stock_code) ? " on" : ""}`} onClick={(e) => toggleFav(it.stock_code, e)}>{favs.has(it.stock_code) ? "★" : "☆"}</span></td>
                        <td><span className="bsc-name">{it.corp_name}</span>{it.sector && <span className="bsc-sector">{it.sector}</span>}</td>
                        <td className="num">{typeof it.current_price === "number" ? `${it.current_price.toLocaleString()}원` : "—"}</td>
                        <td className="num">{it.market_cap_억 != null ? Math.round(it.market_cap_억).toLocaleString() : "—"}</td>
                        {factorCols.map((fc) => <td key={fc.id} className="num">{fmtVal((it as Record<string, unknown>)[fc.id])}</td>)}
                        <td className="num bsc-score" style={{ color: vc.fg }}>{it.composite_score.toFixed(1)}</td>
                        <td><span className="tverdict" style={{ background: vc.bg, color: vc.fg }}>{it.verdict}</span></td>
                      </tr>
                      {isSel && (
                        <tr className="bsc-action-row">
                          <td colSpan={colSpan}>
                            <div className="bsc-action-inner">
                              <span className="bsc-action-text"><b>{it.corp_name}</b> ({it.stock_code}) · 현재가 {typeof it.current_price === "number" ? it.current_price.toLocaleString() : "—"}원 · 종합점수 {it.composite_score.toFixed(1)} · {it.verdict}</span>
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

      {/* ── 팩터 추가: 백테스터와 동일한 FactorPickerModal (똑같은 창) ── */}
      <FactorPickerModal open={modalOpen} tone="neutral" onClose={() => setModalOpen(false)} onInsert={handlePick} />
    </div>
  );
}
