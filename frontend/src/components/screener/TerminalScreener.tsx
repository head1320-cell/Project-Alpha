"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// TerminalScreener — 버틀러 벤치마크 퀀트 스크리너
//   · '팩터 추가' → 백테스터와 동일한 FactorPickerModal(똑같은 창)을 그대로 사용.
//   · 좌측 '내 필터' rail(AND/OR · 시총 · 저장된 전략) + 라이브 종목 리스트(SSE 진행).
//   · 표시 컬럼 ≠ 필터 컬럼(보기전용 컬럼 분리) · 임계값 분포 히스토그램 · 셀 퍼센타일
//     히트맵 · 전종목(전체) 유니버스 가상 스크롤 + 0개 진단 · 종목 클릭→기업 분석 이동.
// ═══════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback, useMemo, useRef, type MouseEvent as ReactMouseEvent } from "react";
import { useRouter } from "next/navigation";
import {
  screenerApiAdvanced, screenerApi, verdictColor,
  type FieldsCatalog, type TechnicalIndicatorCatalog,
  type FilterGroupNode, type FilterConditionNode, type ScreenerResponse, type ScreenerItem,
} from "@/lib/screenerApi";
import { setScreenerHandoff } from "@/lib/screenerHandoff";
import { listPresets, savePreset, deletePreset, type ScreenerPreset } from "@/lib/screenerPresets";
import { parseExpr, materialize, type ExprNode } from "@/lib/exprParser";
import FactorPickerModal, { type FactorPick } from "@/components/backtest/FactorPickerModal";

const OP_LABEL: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=" };
// 조건식 기본값 — 추가된 팩터 전부 AND ("팩터1 and 팩터2 and ...")
const autoExpr = (n: number) => (n < 1 ? "" : Array.from({ length: n }, (_, i) => `팩터${i + 1}`).join(" and "));
const MCAP_PRESETS: Array<{ id: string; label: string; min: number | null; max: number | null }> = [
  { id: "large", label: "대형 1조+", min: 10000, max: null },
  { id: "mid", label: "중형 2천억~1조", min: 2000, max: 10000 },
  { id: "small", label: "소형 ~2천억", min: null, max: 2000 },
];
// 시총 슬라이더(0~100) ↔ 억 변환 — 로그 스케일 (10^2=100억 ~ 10^7=1000조)
const MCAP_LO = 2, MCAP_HI = 7;
const sliderToMcap = (s: number) => Math.round(Math.pow(10, MCAP_LO + (MCAP_HI - MCAP_LO) * (s / 100)));
const mcapToSlider = (eok: number) => Math.round(Math.max(0, Math.min(100, ((Math.log10(eok) - MCAP_LO) / (MCAP_HI - MCAP_LO)) * 100)));
const fmtMcapKo = (eok: number) => eok >= 10000 ? `${(eok / 10000).toFixed(eok >= 100000 ? 0 : 1)}조` : `${Math.round(eok).toLocaleString()}억`;
const ROW_H = 41;        // 가상 스크롤 행 높이(고정)
const WINDOW_MIN = 60;   // 결과가 이보다 많으면 윈도잉 활성

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
function passes(v: number, op: string | undefined, t: number): boolean {
  switch (op) { case "gt": return v > t; case "lte": return v <= t; case "lt": return v < t; case "eq": return v === t; default: return v >= t; }
}

// 임계값 설정 보조 — 팩터 분포 미니 히스토그램 (통과=액센트, 미통과=회색, 빨강선=임계값)
function MiniHistogram({ values, op, threshold }: { values: number[]; op?: string; threshold: number }) {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length < 4) return <span className="bsc-hist-empty">분포 표본 부족</span>;
  const min = Math.min(...finite), max = Math.max(...finite), span = (max - min) || 1, BINS = 20;
  const counts = new Array(BINS).fill(0);
  finite.forEach((v) => { let b = Math.floor(((v - min) / span) * BINS); if (b >= BINS) b = BINS - 1; if (b < 0) b = 0; counts[b]++; });
  const maxC = Math.max(...counts, 1);
  const tx = Math.max(0, Math.min(1, (threshold - min) / span));
  const passCount = finite.filter((v) => passes(v, op, threshold)).length;
  return (
    <>
      <svg className="bsc-hist" viewBox="0 0 100 30" preserveAspectRatio="none">
        {counts.map((c, i) => {
          const mid = min + ((i + 0.5) / BINS) * span;
          const h = (c / maxC) * 28;
          return <rect key={i} x={(i / BINS) * 100} y={29 - h} width={100 / BINS - 0.5} height={h} fill={passes(mid, op, threshold) ? "var(--t-accent)" : "#d4d4d8"} />;
        })}
        <line x1={tx * 100} y1={0} x2={tx * 100} y2={30} stroke="var(--color-bear)" strokeWidth="0.8" />
      </svg>
      <span className="bsc-hist-meta">통과 {passCount}/{finite.length} · 범위 {fmtVal(min)}~{fmtVal(max)}</span>
    </>
  );
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
  const [sampleItems, setSampleItems] = useState<ScreenerItem[]>([]);   // 분포용 무필터 표본
  const [loading, setLoading] = useState(false);
  const [prog, setProg] = useState<{ done: number; total: number; misses: number } | null>(null);
  const [chipCounts, setChipCounts] = useState<(number | null)[]>([]);   // 팩터별 단독 통과 수
  const [focusedChip, setFocusedChip] = useState<number | null>(null);
  const [sortCol, setSortCol] = useState("composite_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<string | null>(null);
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // 시총 슬라이더 (0~100 핸들). [0,100] = 제한 없음
  const [mcapRange, setMcapRange] = useState<[number, number]>([0, 100]);
  const mcapInit = useRef(true);
  // 시총 조건은 팩터 토큰과 분리 — 항상 AND 로 적용되는 유니버스 제약
  const [mcapConds, setMcapConds] = useState<FilterConditionNode[]>([]);
  // 표시(보기전용) 컬럼 — 필터와 분리
  const [displayCols, setDisplayCols] = useState<string[]>([]);
  const [showColPicker, setShowColPicker] = useState(false);
  const [colSearch, setColSearch] = useState("");
  // 가상 스크롤
  const tableWrapRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(560);
  // 프리셋
  const [presets, setPresets] = useState<ScreenerPreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [showSave, setShowSave] = useState(false);
  // 조건식(불리언 표현식) — 사용자가 "팩터1 and (팩터2 or 팩터3)" 처럼 직접 작성
  const [exprText, setExprText] = useState("");
  const [exprError, setExprError] = useState<string | null>(null);
  const [committed, setCommitted] = useState<ExprNode | null>(null);   // 실제 검색에 쓰이는 구조 (null = 전 종목)
  const exprTextRef = useRef("");          // 핸들러에서 최신 식 즉시 참조 (렌더 전 다중 추가 대응)
  const countRef = useRef(0);              // 현재 팩터 수 (토큰 번호 부여용)
  const exprInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { exprTextRef.current = exprText; }, [exprText]);
  useEffect(() => { countRef.current = group.conditions.length; }, [group.conditions.length]);

  useEffect(() => {
    screenerApiAdvanced.fields().then(setCatalog).catch(() => {});
    screenerApiAdvanced.indicators().then(setTechCatalog).catch(() => {});
    screenerApiAdvanced.factorFieldMap().then((d) => setAliasMap(d.map)).catch(() => {});
    screenerApi.universes().then((d) => { const m: Record<string, number> = {}; d.presets.forEach((p) => { m[p.id] = p.size; }); setUniverseSizes(m); }).catch(() => {});
    try { const f = localStorage.getItem("alpha_screener_favs"); if (f) setFavs(new Set(JSON.parse(f))); } catch { /* noop */ }
    try { const c = localStorage.getItem("alpha_screener_cols"); if (c) setDisplayCols(JSON.parse(c)); } catch { /* noop */ }
    setPresets(listPresets());
  }, []);

  // ── 팩터 해석용 인덱스 ──
  const { labelToId, techIdSet, metaById } = useMemo(() => {
    const labelToId = new Map<string, string>();
    const techIdSet = new Set<string>();
    const metaById = new Map<string, FieldMeta>();
    catalog?.categories.forEach((c) => c.fields.forEach((f) => {
      labelToId.set(f.label, f.id); labelToId.set(f.label.replace(/\s+/g, ""), f.id); labelToId.set(f.label.toLowerCase(), f.id);
      metaById.set(f.id, { higher_better: f.higher_better, typical_min: f.typical_min, typical_max: f.typical_max, label: f.label, unit: f.unit });
    }));
    techCatalog?.categories.forEach((c) => c.indicators.forEach((i) => {
      techIdSet.add(i.id);
      labelToId.set(i.label, i.id); labelToId.set(i.label.replace(/\s+/g, ""), i.id);
      metaById.set(i.id, { typical_min: i.typical_min, typical_max: i.typical_max, label: i.label, unit: i.unit });
    }));
    return { labelToId, techIdSet, metaById };
  }, [catalog, techCatalog]);

  const fieldLabel = useCallback((id: string) => labelOverride[id] ?? metaById.get(id)?.label ?? id, [labelOverride, metaById]);
  const allColOptions = useMemo(() => Array.from(metaById, ([id, m]) => ({ id, label: m.label })), [metaById]);

  const resolveFactor = useCallback((name: string): { id: string; kind: "field" | "technical" } | null => {
    const n = name.trim().replace(/^\{+|\}+$/g, "").trim();
    const id = aliasMap[n] ?? labelToId.get(n) ?? labelToId.get(n.replace(/\s+/g, "")) ?? labelToId.get(n.toLowerCase());
    if (!id) return null;
    return { id, kind: techIdSet.has(id) ? "technical" : "field" };
  }, [aliasMap, labelToId, techIdSet]);

  const handlePick = useCallback((pick: FactorPick) => {
    setModalOpen(false);
    const r = resolveFactor(pick.factorName);
    if (!r) { setNotice(`‘${pick.factorName}’은(는) 단면 스크리닝에서 지원되지 않습니다 (백테스터 전용 시계열·수급 팩터).`); return; }
    setNotice(null);
    const meta = metaById.get(r.id);
    const isRank = pick.functionId === "rank";
    const cond: FilterConditionNode = isRank
      ? { kind: r.kind, field: r.id, ...(r.kind === "technical" ? { indicator: r.id } : {}), rank_mode: "top_pct", rank_value: 30 }
      : { kind: r.kind, field: r.id, ...(r.kind === "technical" ? { indicator: r.id } : {}),
          op: (meta?.higher_better ?? true) ? "gte" : "lte",
          value: meta ? Math.round(((meta.higher_better ?? true ? meta.typical_min : meta.typical_max) ?? 0) * 100) / 100 : 0 };
    setLabelOverride((m) => ({ ...m, [r.id]: meta?.label ?? pick.factorName }));
    setGroup((g) => ({ ...g, conditions: [...g.conditions, cond] }));
    // 조건식에 새 토큰 자동 추가 ("... and 팩터N") + 즉시 미리보기 검색
    const n = countRef.current + 1; countRef.current = n;
    const prev = exprTextRef.current.trim();
    const txt = prev ? `${prev} and 팩터${n}` : `팩터${n}`;
    exprTextRef.current = txt; setExprText(txt);
    const pr = parseExpr(txt, n);
    if (pr.ok) { setCommitted(pr.ast); setExprError(null); }
  }, [resolveFactor, metaById]);

  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(null), 5000); return () => clearTimeout(t); }, [notice]);

  // ── 조건식 → 실제 filter_ast (committed 구조 + 현재 조건 값) + 시총 AND 병합 ──
  const effectiveAst = useMemo<FilterGroupNode>(() => {
    const factorAst = committed ? (materialize(committed, group.conditions) as FilterGroupNode) : null;
    if (factorAst && mcapConds.length) return { logic: "AND", conditions: [...mcapConds], groups: [factorAst] };
    if (factorAst) return factorAst;
    if (mcapConds.length) return { logic: "AND", conditions: [...mcapConds], groups: [] };
    return { logic: "AND", conditions: [], groups: [] };
  }, [committed, group.conditions, mcapConds]);

  // ── 라이브 스크리닝 (SSE 스트리밍) — committed 조건식 또는 값 변경 시 재실행 ──
  useEffect(() => {
    setLoading(true); setProg(null);
    const ctrl = new AbortController();
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await screenerApiAdvanced.runAdvancedStream(
          { universe, filter_ast: effectiveAst, sort_by: "composite_score", ascending: false, limit: 500, liquidity_floor: "relaxed" },
          (done, total, misses) => { if (!cancelled) setProg({ done, total, misses }); }, ctrl.signal,
        );
        if (!cancelled) setResults(r);
      } catch { /* aborted/error */ }
      finally { if (!cancelled) setLoading(false); }
    }, 350);
    return () => { cancelled = true; ctrl.abort(); clearTimeout(t); };
  }, [effectiveAst, universe]);

  // ── 분포용 무필터 표본 (유니버스 변경 시) ──
  useEffect(() => {
    let cancelled = false;
    screenerApiAdvanced.runAdvanced({ universe, filter_ast: { logic: "AND", conditions: [], groups: [] }, sort_by: "composite_score", ascending: false, limit: 300, liquidity_floor: "relaxed" })
      .then((r) => { if (!cancelled) setSampleItems(r.items); }).catch(() => {});
    return () => { cancelled = true; };
  }, [universe]);

  // ── 팩터별 단독 통과 수 (선택도 표시) ──
  useEffect(() => {
    if (!group.conditions.length) { setChipCounts([]); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      const cnt = (conds: FilterConditionNode[]) =>
        screenerApiAdvanced.count({ universe, filter_ast: { logic: "AND", conditions: conds, groups: [] }, limit: 1, liquidity_floor: "relaxed" }).then((r) => r.total_passed).catch(() => null);
      const sc = await Promise.all(group.conditions.map((c) => cnt([c])));
      if (!cancelled) setChipCounts(sc);
    }, 450);
    return () => { cancelled = true; clearTimeout(t); };
  }, [group, universe]);

  // ── 가상 스크롤 컨테이너 높이 측정 ──
  useEffect(() => {
    const el = tableWrapRef.current; if (!el) return;
    const update = () => setViewH(el.clientHeight || 560);
    update();
    const ro = new ResizeObserver(update); ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 팩터 제거 → 인덱스가 밀리므로 조건식을 기본 AND 로 재생성 (예측가능 동작)
  const removeCondition = (idx: number) => {
    setGroup((g) => ({ ...g, conditions: g.conditions.filter((_, i) => i !== idx) }));
    const n = Math.max(0, countRef.current - 1); countRef.current = n;
    const txt = autoExpr(n); exprTextRef.current = txt; setExprText(txt);
    const pr = n >= 1 ? parseExpr(txt, n) : null;
    setCommitted(pr && pr.ok ? pr.ast : null); setExprError(null);
  };
  const updateCondition = (idx: number, patch: Partial<FilterConditionNode>) => setGroup((g) => ({ ...g, conditions: g.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c)) }));
  const clearAll = () => {
    setGroup({ logic: "AND", conditions: [], groups: [] }); setSelected(null);
    countRef.current = 0; exprTextRef.current = ""; setExprText(""); setCommitted(null); setExprError(null);
  };
  // 조건식 SEARCH/Enter — 현재 식을 파싱해 검색 실행 (빈 식 = 전 팩터 AND, 팩터 없으면 전 종목)
  const runSearch = () => {
    const txt = exprText.trim();
    const n = group.conditions.length;
    if (!txt) {
      if (n >= 1) { const d = autoExpr(n); setExprText(d); exprTextRef.current = d; const pr = parseExpr(d, n); setCommitted(pr.ok ? pr.ast : null); }
      else setCommitted(null);
      setExprError(null); return;
    }
    const pr = parseExpr(txt, n);
    if (pr.ok) { setCommitted(pr.ast); setExprError(null); } else setExprError(pr.error);
  };
  // 토큰/연산자를 커서 위치에 삽입
  const insertAtCursor = (s: string) => {
    const el = exprInputRef.current;
    const cur = exprTextRef.current;
    if (!el) { const next = cur + s; exprTextRef.current = next; setExprText(next); return; }
    const start = el.selectionStart ?? cur.length, end = el.selectionEnd ?? cur.length;
    const next = cur.slice(0, start) + s + cur.slice(end);
    exprTextRef.current = next; setExprText(next);
    requestAnimationFrame(() => { el.focus(); const pos = start + s.length; el.setSelectionRange(pos, pos); });
  };
  // 시총 슬라이더 → market_cap_억 조건 (팩터 토큰과 분리, 항상 AND)
  const commitMcapNow = useCallback((r: [number, number]) => {
    const min = r[0] > 0 ? sliderToMcap(r[0]) : null;
    const max = r[1] < 100 ? sliderToMcap(r[1]) : null;
    const conds: FilterConditionNode[] = [];
    if (min != null) conds.push({ kind: "field", field: "market_cap_억", op: "gte", value: min });
    if (max != null) conds.push({ kind: "field", field: "market_cap_억", op: "lte", value: max });
    setMcapConds(conds);
    if (conds.length) setLabelOverride((m) => ({ ...m, market_cap_억: "시가총액" }));
  }, []);
  useEffect(() => {
    if (mcapInit.current) { mcapInit.current = false; return; }
    const t = setTimeout(() => commitMcapNow(mcapRange), 280);
    return () => clearTimeout(t);
  }, [mcapRange, commitMcapNow]);
  const mcapActive = mcapRange[0] !== 0 || mcapRange[1] !== 100;
  const toggleDisplayCol = (id: string) => setDisplayCols((cols) => {
    const next = cols.includes(id) ? cols.filter((c) => c !== id) : [...cols, id];
    try { localStorage.setItem("alpha_screener_cols", JSON.stringify(next)); } catch { /* noop */ }
    return next;
  });

  const toggleFav = (code: string, e: ReactMouseEvent) => {
    e.stopPropagation();
    setFavs((s) => { const n = new Set(s); if (n.has(code)) n.delete(code); else n.add(code);
      try { localStorage.setItem("alpha_screener_favs", JSON.stringify([...n])); } catch { /* noop */ } return n; });
  };
  const setSort = (col: string) => { if (sortCol === col) setSortDir((d) => (d === "desc" ? "asc" : "desc")); else { setSortCol(col); setSortDir("desc"); } };
  const sortArrow = (col: string) => (sortCol === col ? (sortDir === "desc" ? " ▼" : " ▲") : "");
  const goToCompany = (code: string, e: ReactMouseEvent) => { e.stopPropagation(); try { sessionStorage.setItem("alpha_company_ticker", code); } catch { /* noop */ } router.push("/insights"); };
  const sendToBacktester = () => { if (!group.conditions.length) return; setScreenerHandoff({ filterAst: effectiveAst, universe, conditionSummary: group.conditions.map((c) => condText(c, fieldLabel)), resultCount: results?.items.length ?? 0, createdAt: Date.now() }); router.push("/backtest"); };
  const handleSave = () => { if (!group.conditions.length || !presetName.trim()) return; savePreset(presetName.trim(), group, universe); setPresets(listPresets()); setPresetName(""); setShowSave(false); };
  const handleLoad = (p: ScreenerPreset) => {
    const g = JSON.parse(JSON.stringify(p.group)) as FilterGroupNode;
    setGroup(g); setSelected(null);
    const n = g.conditions.length; countRef.current = n;
    const txt = autoExpr(n); exprTextRef.current = txt; setExprText(txt);
    const pr = n >= 1 ? parseExpr(txt, n) : null;
    setCommitted(pr && pr.ok ? pr.ast : null); setExprError(null);
  };
  const handleDelete = (id: string, e: ReactMouseEvent) => { e.stopPropagation(); deletePreset(id); setPresets(listPresets()); };

  // 표시 컬럼 = 필터 팩터 컬럼 + 보기전용 컬럼 (중복/고정컬럼 제거)
  const dataCols = useMemo(() => {
    const seen = new Set<string>(["current_price", "market_cap_억", "composite_score"]);
    const cols: { id: string; label: string; filtered: boolean }[] = [];
    group.conditions.forEach((c) => { if (c.field && !seen.has(c.field)) { seen.add(c.field); cols.push({ id: c.field, label: fieldLabel(c.field), filtered: true }); } });
    displayCols.forEach((id) => { if (!seen.has(id)) { seen.add(id); cols.push({ id, label: fieldLabel(id), filtered: false }); } });
    return cols;
  }, [group, displayCols, fieldLabel]);

  const sortedItems = useMemo(() => {
    if (!results) return [];
    return [...results.items].sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortCol], bv = (b as Record<string, unknown>)[sortCol];
      const an = typeof av === "number" && Number.isFinite(av) ? av : -Infinity;
      const bn = typeof bv === "number" && Number.isFinite(bv) ? bv : -Infinity;
      return sortDir === "desc" ? bn - an : an - bn;
    });
  }, [results, sortCol, sortDir]);

  // 셀 퍼센타일 히트맵용 컬럼 min/max
  const colRanges = useMemo(() => {
    const r: Record<string, [number, number]> = {};
    ["composite_score", ...dataCols.map((c) => c.id)].forEach((id) => {
      const vals = sortedItems.map((it) => (it as Record<string, unknown>)[id]).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
      if (vals.length) r[id] = [Math.min(...vals), Math.max(...vals)];
    });
    return r;
  }, [sortedItems, dataCols]);

  // ── 값이 전부 빈 컬럼 자동 숨김 (mock 시총 등). 필터 컬럼은 유지 ──
  const emptyCols = useMemo(() => {
    const s = new Set<string>();
    if (!sortedItems.length) return s;
    const allNull = (id: string) => sortedItems.every((it) => { const v = (it as Record<string, unknown>)[id]; return v == null || (typeof v === "number" && !Number.isFinite(v)); });
    if (allNull("market_cap_억")) s.add("market_cap_억");
    dataCols.forEach((c) => { if (!c.filtered && allNull(c.id)) s.add(c.id); });
    return s;
  }, [sortedItems, dataCols]);
  const shownCols = useMemo(() => dataCols.filter((c) => c.filtered || !emptyCols.has(c.id)), [dataCols, emptyCols]);
  const showMcap = !emptyCols.has("market_cap_억");

  const sampleVals = useCallback((id: string) => sampleItems.map((it) => (it as Record<string, unknown>)[id]).filter((v): v is number => typeof v === "number" && Number.isFinite(v)), [sampleItems]);

  const exportCsv = () => {
    if (!sortedItems.length) return;
    const header = ["순위", "종목코드", "종목명", "섹터", "현재가", ...(showMcap ? ["시총(억)"] : []), ...shownCols.map((c) => c.label), "종합점수", "판정"];
    const rows = sortedItems.map((it, i) => [i + 1, it.stock_code, it.corp_name, it.sector ?? "",
      typeof it.current_price === "number" ? it.current_price : "", ...(showMcap ? [it.market_cap_억 ?? ""] : []),
      ...shownCols.map((c) => { const v = (it as Record<string, unknown>)[c.id]; return typeof v === "number" ? v : ""; }), it.composite_score, it.verdict]);
    const esc = (v: unknown) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = [header, ...rows].map((r) => r.map(esc).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = `screener_${universe}_${Date.now()}.csv`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };

  const total = results?.total_passed ?? null;
  const uniTotal = universeSizes[universe] ?? results?.total_evaluated ?? 0;
  const colSpan = 6 + (showMcap ? 1 : 0) + shownCols.length;
  const selectedItem = selected ? sortedItems.find((it) => it.stock_code === selected) ?? null : null;
  const focusCond = focusedChip != null ? group.conditions[focusedChip] : null;

  // 가상 스크롤 윈도잉
  const windowing = sortedItems.length > WINDOW_MIN;
  const startIdx = windowing ? Math.max(0, Math.floor(scrollTop / ROW_H) - 8) : 0;
  const visCount = windowing ? Math.ceil(viewH / ROW_H) + 16 : sortedItems.length;
  const endIdx = Math.min(sortedItems.length, startIdx + visCount);
  const visItems = sortedItems.slice(startIdx, endIdx);
  const topPad = startIdx * ROW_H, botPad = (sortedItems.length - endIdx) * ROW_H;

  // 0개 진단 — 가장 제한적인(단독 통과 최소) 조건
  const diagnostic = useMemo(() => {
    if (total !== 0 || !group.conditions.length || chipCounts.length !== group.conditions.length) return null;
    let minI = -1, minC = Infinity;
    chipCounts.forEach((c, i) => { if (c != null && c < minC) { minC = c; minI = i; } });
    if (minI < 0) return null;
    return { label: fieldLabel(group.conditions[minI].field), count: minC };
  }, [total, group, chipCounts, fieldLabel]);

  const heatCell = (id: string, v: unknown) => {
    const range = colRanges[id];
    const pct = range && typeof v === "number" && Number.isFinite(v) && range[1] > range[0] ? (v - range[0]) / (range[1] - range[0]) : 0;
    const hb = id === "composite_score" ? true : metaById.get(id)?.higher_better;
    // 방향성: higher_better 면 큰 값=좋음(녹), 아니면 작은 값=좋음 → 좋을수록 길고 초록, 나쁠수록 짧고 빨강
    let width = pct, fill = "rgba(18,0,255,0.10)";
    if (hb !== undefined && range) {
      const good = hb ? pct : 1 - pct;
      width = good;
      fill = good >= 0.5 ? "rgba(22,163,74,0.15)" : "rgba(220,38,38,0.13)";
    }
    return (
      <td className="num bsc-cell" key={id}>
        <span className="bsc-cell-fill" style={{ width: `${Math.round(width * 100)}%`, background: fill }} />
        <span className="bsc-cell-val">{fmtVal(v)}</span>
      </td>
    );
  };

  const renderRow = (it: ScreenerItem, i: number) => {
    const vc = verdictColor(it.verdict);
    const isSel = selected === it.stock_code;
    return (
      <tr key={it.stock_code} className={`bsc-row${isSel ? " selected" : ""}`} onClick={() => setSelected(isSel ? null : it.stock_code)}>
        <td className="bsc-rank">{i + 1}</td>
        <td><span className={`bsc-fav${favs.has(it.stock_code) ? " on" : ""}`} onClick={(e) => toggleFav(it.stock_code, e)}>{favs.has(it.stock_code) ? "★" : "☆"}</span></td>
        <td><span className="bsc-name">{it.corp_name}</span>{it.sector && <span className="bsc-sector">{it.sector}</span>}</td>
        <td className="num">{typeof it.current_price === "number" ? `${it.current_price.toLocaleString()}원` : "—"}</td>
        {showMcap && <td className="num">{it.market_cap_억 != null ? Math.round(it.market_cap_억).toLocaleString() : "—"}</td>}
        {shownCols.map((c) => heatCell(c.id, (it as Record<string, unknown>)[c.id]))}
        {heatCell("composite_score", it.composite_score)}
        <td><span className="tverdict" style={{ background: vc.bg, color: vc.fg }}>{it.verdict}</span></td>
      </tr>
    );
  };

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

          <div className="bsc-mcap">
            <div className="bsc-mcap-head">시가총액
              <span className="bsc-mcap-vals">{mcapRange[0] === 0 ? "최소" : fmtMcapKo(sliderToMcap(mcapRange[0]))} ~ {mcapRange[1] === 100 ? "최대" : fmtMcapKo(sliderToMcap(mcapRange[1]))}</span>
            </div>
            <div className="bsc-range">
              <div className="bsc-range-fill" style={{ left: `${mcapRange[0]}%`, right: `${100 - mcapRange[1]}%` }} />
              <input type="range" min={0} max={100} value={mcapRange[0]} className="bsc-range-input" aria-label="시총 최소"
                onChange={(e) => { const v = Number(e.target.value); setMcapRange(([, hi]) => [Math.min(v, hi - 1), hi]); }} />
              <input type="range" min={0} max={100} value={mcapRange[1]} className="bsc-range-input" aria-label="시총 최대"
                onChange={(e) => { const v = Number(e.target.value); setMcapRange(([lo]) => [lo, Math.max(v, lo + 1)]); }} />
            </div>
            <div className="bsc-mcap-btns">
              <button className={`bsc-mcap-btn${!mcapActive ? " active" : ""}`} onClick={() => setMcapRange([0, 100])}>전체</button>
              {MCAP_PRESETS.map((p) => (
                <button key={p.id} className="bsc-mcap-btn" onClick={() => setMcapRange([p.min ? mcapToSlider(p.min) : 0, p.max ? mcapToSlider(p.max) : 100])}>{p.label}</button>
              ))}
            </div>
            <div className="bsc-mcap-note">ⓘ 실데이터 연결 시 동작 (mock은 시총 미제공)</div>
          </div>

          {group.conditions.length === 0 ? (
            <div className="bsc-rail-empty">아직 추가된 팩터가 없습니다.<br />「＋ 팩터 추가」로 조건을 더하면 「팩터1, 팩터2 …」로 위에 쌓이고, 조건식에 자동으로 들어갑니다.</div>
          ) : (
            <div className="bsc-rail-list">
              {group.conditions.map((c, i) => {
                const isRank = !!c.rank_mode;
                return (
                  <div key={i} className="bsc-rail-item">
                    <div className="bsc-rail-item-top">
                      <span className="bsc-rail-item-tag">팩터{i + 1}</span>
                      <span className="bsc-rail-item-name">{fieldLabel(c.field)}{c.kind === "technical" && <span className="bsc-field-tech" style={{ marginLeft: 6 }}>기술</span>}</span>
                      {chipCounts[i] != null && <span className="bsc-rail-item-count" title="이 팩터 단독 통과 종목 수">{chipCounts[i]!.toLocaleString()}</span>}
                      <span className="bsc-rail-item-del" onClick={() => removeCondition(i)}>✕</span>
                    </div>
                    <div className="bsc-rail-item-edit">
                      {isRank ? (
                        <>
                          <select className="bsc-chip-op" value={c.rank_mode!} onChange={(e) => updateCondition(i, { rank_mode: e.target.value as FilterConditionNode["rank_mode"] })}>
                            <option value="top_pct">상위</option><option value="bottom_pct">하위</option>
                          </select>
                          <input className="bsc-chip-val" type="number" value={String(c.rank_value ?? 30)} onChange={(e) => updateCondition(i, { rank_value: Number(e.target.value) || 0 })} />
                          <span className="bsc-rail-item-unit">%</span>
                        </>
                      ) : (
                        <>
                          <select className="bsc-chip-op" value={c.op || "gte"} onChange={(e) => updateCondition(i, { op: e.target.value as FilterConditionNode["op"] })}>
                            <option value="gt">&gt;</option><option value="gte">≥</option><option value="lt">&lt;</option><option value="lte">≤</option><option value="eq">=</option>
                          </select>
                          <input className="bsc-chip-val" type="number" step="any" value={String(c.value ?? 0)} onFocus={() => setFocusedChip(i)}
                            onChange={(e) => updateCondition(i, { value: e.target.value === "" ? 0 : Number(e.target.value) })} />
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

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
            {presets.length === 0 ? <div className="bsc-preset-empty">저장된 전략 없음</div> : (
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

        {/* ── 우측 ── */}
        <div className="bsc-main">
          {/* 조건식(불리언 표현식) — 팩터 토큰 + and/or/() 직접 작성 → SEARCH */}
          {group.conditions.length > 0 && (
            <div className="bsc-expr">
              <div className="bsc-expr-row">
                <span className="bsc-expr-label">조건식</span>
                <input
                  ref={exprInputRef}
                  className={`bsc-expr-input${exprError ? " err" : ""}`}
                  value={exprText}
                  placeholder="예: 팩터1 and (팩터2 or 팩터3)"
                  spellCheck={false}
                  onChange={(e) => setExprText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") runSearch(); }}
                />
                <button className="bsc-expr-search" onClick={runSearch} title="조건식으로 검색">SEARCH</button>
              </div>
              <div className="bsc-expr-tokens">
                <span className="bsc-expr-hint">삽입:</span>
                {group.conditions.map((c, i) => (
                  <button key={i} className="bsc-expr-token" title={condText(c, fieldLabel)} onClick={() => insertAtCursor(`팩터${i + 1}`)}>팩터{i + 1}</button>
                ))}
                <span className="bsc-expr-sep" />
                <button className="bsc-expr-op" onClick={() => insertAtCursor(" and ")}>and</button>
                <button className="bsc-expr-op" onClick={() => insertAtCursor(" or ")}>or</button>
                <button className="bsc-expr-op" onClick={() => insertAtCursor("(")}>(</button>
                <button className="bsc-expr-op" onClick={() => insertAtCursor(")")}>)</button>
              </div>
              {exprError
                ? <div className="bsc-expr-msg err">⚠ {exprError}</div>
                : <div className="bsc-expr-msg ok">적용 중: <b>{committed ? exprText.trim() : "전체 종목 (조건식 없음)"}</b></div>}
            </div>
          )}

          {/* 임계값 분포 히스토그램 (편집 중인 조건) */}
          {focusCond && !focusCond.rank_mode && (
            <div className="bsc-hist-panel">
              <span className="bsc-hist-label">{fieldLabel(focusCond.field)} 분포 — 임계값 정하기</span>
              <div className="bsc-hist-wrap"><MiniHistogram values={sampleVals(focusCond.field)} op={focusCond.op} threshold={Number(focusCond.value) || 0} /></div>
            </div>
          )}

          {notice && <div className="bsc-notice">{notice}</div>}

          <div className="bsc-countbar">
            <span className="bsc-count">검색된 기업 <b>{total != null ? total.toLocaleString() : "—"}</b>개</span>
            {loading && <span className="bsc-spinner" />}
            <span className="bsc-countbar-spacer" />
            <button className="bsc-bt-btn" onClick={() => setShowColPicker((v) => !v)} title="표시 컬럼 추가 (필터와 별개)">⊞ 컬럼{displayCols.length ? ` (${displayCols.length})` : ""}</button>
            <button className="bsc-bt-btn" onClick={exportCsv} disabled={!sortedItems.length} title="현재 결과를 CSV로 내보내기">⤓ CSV</button>
            <button className="bsc-bt-btn" onClick={sendToBacktester} disabled={!group.conditions.length} title="이 조건식을 백테스터로 전달">이 전략 백테스트 →</button>
          </div>

          {showColPicker && (
            <div className="bsc-colpicker">
              <div className="bsc-colpicker-head">
                <span>표시 컬럼 (필터와 별개로 보기만)</span>
                <input className="bsc-colpicker-search" placeholder="컬럼 검색…" value={colSearch} onChange={(e) => setColSearch(e.target.value)} />
              </div>
              <div className="bsc-colpicker-list">
                {allColOptions.filter((o) => !colSearch || o.label.toLowerCase().includes(colSearch.toLowerCase()) || o.id.includes(colSearch.toLowerCase())).slice(0, 240).map((o) => (
                  <label key={o.id} className={`bsc-colpicker-item${displayCols.includes(o.id) ? " on" : ""}`}>
                    <input type="checkbox" checked={displayCols.includes(o.id)} onChange={() => toggleDisplayCol(o.id)} />{o.label}
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="bsc-progress">
            {loading
              ? <>데이터 확충 중… <b>{(prog?.done ?? 0).toLocaleString()}</b>/{(prog?.total ?? uniTotal).toLocaleString()} 종목 업데이트{prog && prog.misses > 0 ? ` · 신규 ${prog.misses.toLocaleString()}` : ""}</>
              : results
                ? <>평가 완료 <b>{results.total_evaluated.toLocaleString()}</b>/{uniTotal.toLocaleString()} 종목 · 신규 {results.cache_misses.toLocaleString()} · 캐시 {results.cache_hits.toLocaleString()} · {results.elapsed_seconds.toFixed(2)}s{windowing ? ` · 가상 스크롤 ${sortedItems.length.toLocaleString()}행` : ""}</>
                : <>대기 중…</>}
          </div>

          {/* 0개 진단 */}
          {diagnostic && (
            <div className="bsc-diag">조건에 맞는 종목 <b>0개</b> — 가장 제한적인 조건은 <b>{diagnostic.label}</b>(단독 {diagnostic.count.toLocaleString()}개)입니다. 완화하거나 제거해 보세요.</div>
          )}

          <div className="bsc-table-wrap" ref={tableWrapRef} onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}>
            <table className="bsc-table">
              <thead>
                <tr>
                  <th className="bsc-rank">#</th>
                  <th />
                  <th>종목명</th>
                  <th className="num sortable" onClick={() => setSort("current_price")}>현재가{sortArrow("current_price")}</th>
                  {showMcap && <th className="num sortable" onClick={() => setSort("market_cap_억")}>시총(억){sortArrow("market_cap_억")}</th>}
                  {shownCols.map((c) => (
                    <th key={c.id} className={`num sortable${c.filtered ? "" : " viewcol"}`} onClick={() => setSort(c.id)} title={c.filtered ? "필터 컬럼" : "보기 컬럼"}>{c.label}{c.filtered ? "" : " ·"}{sortArrow(c.id)}</th>
                  ))}
                  <th className="num sortable" onClick={() => setSort("composite_score")}>종합점수{sortArrow("composite_score")}</th>
                  <th>판정</th>
                </tr>
              </thead>
              <tbody>
                {windowing && topPad > 0 && <tr aria-hidden style={{ height: topPad }}><td colSpan={colSpan} style={{ padding: 0, border: 0 }} /></tr>}
                {visItems.map((it, vi) => renderRow(it, startIdx + vi))}
                {windowing && botPad > 0 && <tr aria-hidden style={{ height: botPad }}><td colSpan={colSpan} style={{ padding: 0, border: 0 }} /></tr>}
              </tbody>
            </table>
            {!loading && sortedItems.length === 0 && !diagnostic && <div className="bsc-empty">[ NO_MATCHES ] 조건에 맞는 종목이 없습니다</div>}
          </div>

          {/* 선택 종목 — 하단 고정 액션 바 */}
          {selectedItem && (
            <div className="bsc-action-bar">
              <span className="bsc-action-text"><b>{selectedItem.corp_name}</b> ({selectedItem.stock_code}) · 현재가 {typeof selectedItem.current_price === "number" ? selectedItem.current_price.toLocaleString() : "—"}원 · 종합점수 {selectedItem.composite_score.toFixed(1)} · {selectedItem.verdict}</span>
              <span className="bsc-countbar-spacer" />
              <button className="bsc-go-company" onClick={(e) => goToCompany(selectedItem.stock_code, e)}>기업 분석 탭으로 가기 →</button>
              <span className="bsc-action-close" onClick={() => setSelected(null)}>✕</span>
            </div>
          )}
        </div>
      </div>

      <FactorPickerModal key={modalOpen ? "open" : "closed"} open={modalOpen} tone="neutral" onClose={() => setModalOpen(false)} onInsert={handlePick} />
    </div>
  );
}
