"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 종목 찾기 (BU2 · ADR-003) — 조건 → 답 한 문장 + 근거 칩 → 결과 표 → 시트
//   · ★요청은 한 바이트도 바꾸지 않는다★(CLAUDE.md §6 스크리너 3-레이어) — `e2e/screener-requests.spec.ts` 골든이 건다.
//     실행·표본·단독 통과 수 요청을 만드는 로직은 옛 화면 그대로이고, 바뀐 것은 그리는 방식뿐이다.
//   · 답 문장·칩은 서버 값으로만: `total_passed` · `capped` · `ingested_count/universe_size` · `liquidity_gate` ·
//     연습용 표시는 `GET /macro/connection-status` 의 `mock_allowed`(= mock_gate). 화면이 새 판단을 만들지 않는다.
//   · ★실패는 실패로★ 스트림이 실패하면(중단 제외) 옛 결과를 지우고 alert + 다시 시도 — 낡은 결과를 새 결과처럼 두지 않는다.
//   · 한 화면 한 일: 조건식·유동성 게이트·저장한 조건·계산 통계는 "전문가 설정"에 접는다(기능은 그대로, 게이트 기본 꺼짐 그대로).
//   · "설계에 넣기" → `/allocation?tickers=`(캔버스가 stock_master 로 확인한 코드만 싣는다 — `tickerBridge.ts`).
// ═══════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback, useMemo, useRef, type MouseEvent as ReactMouseEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { macroApi } from "@/entities/macro/api";
import { screenerApiAdvanced } from "@/entities/screener/api/ast";
import { screenerApi } from "@/entities/screener/api/core";
import { type ScreenerResponse, type TechnicalIndicatorCatalog } from "@/entities/screener/model";
import type { FieldsCatalog, FilterConditionNode, FilterGroupNode, ScreenerItem } from "@/shared/model/domain";
import { num, priceWon } from "@/shared/lib/krFormat";
import { LoadingState } from "@/shared/ui/States";
import { Answer, Chips, Notice, PageHead, Sheet, type Chip, type Figure } from "@/shared/ui/tx";
import { setScreenerHandoff } from "@/shared/lib/screenerHandoff";
import { listPresets, savePreset, deletePreset, type ScreenerPreset } from "@/shared/lib/screenerPresets";
import { parseExpr, materialize, type ExprNode } from "@/shared/lib/exprParser";
import dynamic from "next/dynamic";
import { type FactorPick } from "@/features/factor-picker/FactorPickerModal";
// ★기본이 '닫힘' 인 창은 첫 로드에 있을 이유가 없다★ 팩터 창이 CatalogueShell 로 옮겨가며
// shadcn/Radix ToggleGroup 을 끌고 오는데, 정적 import 로 두면 그 무게가 이 라우트의 첫
// 로드에 그대로 실린다(실측: +17 kB). ADR 001 은 설명되지 않는 4 kB 증가를 되돌리라고 한다 —
// 되돌리는 대신 **필요할 때 가져온다**. 타입은 값이 아니므로 위 import 는 런타임에 남지 않는다.
const FactorPickerModal = dynamic(
  () => import("@/features/factor-picker/FactorPickerModal"), { ssr: false });

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
const PAGE_SIZE = 100;   // 결과 테이블 페이지당 행 수
const TOP_BRIDGE = 10;   // "상위 n종목 설계에 넣기" — 표의 지금 정렬 그대로 위 n개(캔버스 종목 고르기 노드 상한 30 안)
/** 고를 수 있는 유니버스 — id 는 서버 프리셋 id 그대로(요청 골든이 건다). */
const UNIVERSES = [
  { id: "kospi200", label: "코스피 200" },
  { id: "kosdaq150", label: "코스닥 150" },
  { id: "kospi", label: "코스피 전체" },
  { id: "kosdaq", label: "코스닥 전체" },
  { id: "etf", label: "ETF 전체" },
  { id: "all_listed", label: "모든 상장 종목" },
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
function passes(v: number, op: string | undefined, t: number): boolean {
  switch (op) { case "gt": return v > t; case "lte": return v <= t; case "lt": return v < t; case "eq": return v === t; default: return v >= t; }
}

// 임계값 설정 보조 — 팩터 분포 미니 히스토그램 (통과=파랑, 미통과=선 색, 잉크선=임계값 — 판단을 빨강/초록으로 말하지 않는다)
function MiniHistogram({ values, op, threshold }: { values: number[]; op?: string; threshold: number }) {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length < 4) return <span className="bsc-hist-empty">분포를 그릴 표본이 모자라요</span>;
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
          return <rect key={i} x={(i / BINS) * 100} y={29 - h} width={100 / BINS - 0.5} height={h} fill={passes(mid, op, threshold) ? "var(--tx-blue)" : "var(--tx-line)"} />;
        })}
        <line x1={tx * 100} y1={0} x2={tx * 100} y2={30} stroke="var(--tx-ink)" strokeWidth="0.8" />
      </svg>
      <span className="bsc-hist-meta">표본 {num(finite.length)}개 중 {num(passCount)}개 통과 · 범위 {fmtVal(min)}~{fmtVal(max)}</span>
    </>
  );
}

export default function TerminalScreener() {
  const router = useRouter();
  const [universe, setUniverse] = useState("kospi200");
  // 연습용 표시의 근거 — 서버 mock 게이트(홈·셸 prefetch 와 같은 queryKey). 실패면 "출처를 확인하지 못했어요"(침묵 금지).
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  // 카탈로그류(fields/indicators/factorFieldMap/universes) — 탭 재방문 시 재요청 없이 캐시
  // 재사용(staleTime 24h, 전역 QueryClient 기본값). 변수명은 기존 useState와 동일하게 유지해
  // 아래 로직을 건드리지 않음.
  const { data: catalog } = useQuery({ queryKey: ["screener", "fields"], queryFn: () => screenerApiAdvanced.fields() });
  const { data: techCatalog } = useQuery({ queryKey: ["screener", "indicators"], queryFn: () => screenerApiAdvanced.indicators() });
  const { data: aliasMapData } = useQuery({ queryKey: ["screener", "factor-field-map"], queryFn: () => screenerApiAdvanced.factorFieldMap() });
  const aliasMap = aliasMapData?.map ?? {};
  const { data: universesData } = useQuery({ queryKey: ["screener", "universes"], queryFn: () => screenerApi.universes() });
  const universeSizes = useMemo(() => {
    const m: Record<string, number> = {};
    universesData?.presets.forEach((p) => { m[p.id] = p.size; });
    return m;
  }, [universesData]);
  const [group, setGroup] = useState<FilterGroupNode>({ logic: "AND", conditions: [], groups: [] });
  const [labelOverride, setLabelOverride] = useState<Record<string, string>>({});
  const [results, setResults] = useState<ScreenerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);   // 스트림 실패(중단 아님) — 결과 대신 alert
  const [retry, setRetry] = useState(0);                            // [다시 시도] — 같은 요청을 한 번 더
  const [prog, setProg] = useState<{ done: number; total: number; misses: number } | null>(null);
  const [chipCounts, setChipCounts] = useState<(number | null)[]>([]);   // 팩터별 단독 통과 수
  const [focusedChip, setFocusedChip] = useState<number | null>(null);
  const [sortCol, setSortCol] = useState("composite_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<string | null>(null);
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // 유동성 게이트 — 기본 OFF (검색된 기업 == 평가 완료). ON 시 시총300억·거래대금3억·스프레드1% 필터
  const [gateOn, setGateOn] = useState(false);
  // 시총 슬라이더 (0~100 핸들). [0,100] = 제한 없음
  const [mcapRange, setMcapRange] = useState<[number, number]>([0, 100]);
  const mcapInit = useRef(true);
  // 시총 조건은 팩터 토큰과 분리 — 항상 AND 로 적용되는 유니버스 제약
  const [mcapConds, setMcapConds] = useState<FilterConditionNode[]>([]);
  // 표시(보기전용) 컬럼 — 필터와 분리
  const [displayCols, setDisplayCols] = useState<string[]>([]);
  const [showColPicker, setShowColPicker] = useState(false);
  const [colSearch, setColSearch] = useState("");
  // 결과 페이지네이션 (100행/페이지) — 렌더 행수 고정으로 렉 방지
  const tableWrapRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(0);
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
    const r = resolveFactor(pick.factorToken) ?? resolveFactor(pick.factorName);
    if (!r) { setNotice(`‘${pick.factorName}’은(는) 단면 스크리닝에서 지원되지 않아요 (백테스터 전용 시계열·수급 팩터).`); return; }
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
    setLoading(true); setProg(null); setRunError(null);
    const ctrl = new AbortController();
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await screenerApiAdvanced.runAdvancedStream(
          // 유니버스 전체 반환 — 백엔드가 유니버스 크기로 캡(kospi200→200, all_listed→~2,900). 상한 4000.
          { universe, filter_ast: effectiveAst, sort_by: "composite_score", ascending: false, limit: 4000, liquidity_floor: gateOn ? "relaxed" : "off" },
          (done, total, misses) => { if (!cancelled) setProg({ done, total, misses }); }, ctrl.signal,
        );
        if (!cancelled) setResults(r);
      } catch (e) {
        // 중단(조건이 바뀌어 새 실행이 시작됨)만 조용히 넘긴다. 그 밖의 실패는 옛 결과를 지우고 말한다.
        if (!cancelled && !ctrl.signal.aborted) {
          setResults(null);
          setRunError(e instanceof Error ? e.message : String(e));
        }
      }
      finally { if (!cancelled) setLoading(false); }
    }, 350);
    return () => { cancelled = true; ctrl.abort(); clearTimeout(t); };
  }, [effectiveAst, universe, gateOn, retry]);

  // ── 분포용 무필터 표본 (유니버스 변경 시) ── react-query로 캐시(동일 universe/gateOn
  // 재방문 시 재요청 없음)
  const { data: sampleData } = useQuery({
    queryKey: ["screener", "sample", universe, gateOn],
    queryFn: () => screenerApiAdvanced.runAdvanced({ universe, filter_ast: { logic: "AND", conditions: [], groups: [] }, sort_by: "composite_score", ascending: false, limit: 300, liquidity_floor: gateOn ? "relaxed" : "off" }),
  });
  const sampleItems = useMemo(() => sampleData?.items ?? [], [sampleData]);

  // ── 팩터별 단독 통과 수 (선택도 표시) ──
  useEffect(() => {
    if (!group.conditions.length) { setChipCounts([]); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      const cnt = (conds: FilterConditionNode[]) =>
        screenerApiAdvanced.count({ universe, filter_ast: { logic: "AND", conditions: conds, groups: [] }, limit: 1, liquidity_floor: gateOn ? "relaxed" : "off" }).then((r) => r.total_passed).catch(() => null);
      const sc = await Promise.all(group.conditions.map((c) => cnt([c])));
      if (!cancelled) setChipCounts(sc);
    }, 450);
    return () => { cancelled = true; clearTimeout(t); };
  }, [group, universe, gateOn]);

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
  const uniTotal = results?.universe_size || universeSizes[universe] || results?.total_evaluated || 0;
  const selectedItem = selected ? sortedItems.find((it) => it.stock_code === selected) ?? null : null;

  // 페이지네이션 계산 — 정렬/새 결과 시 1페이지로 리셋
  const pageCount = Math.max(1, Math.ceil(sortedItems.length / PAGE_SIZE));
  const curPage = Math.min(page, pageCount - 1);
  const pageItems = sortedItems.slice(curPage * PAGE_SIZE, (curPage + 1) * PAGE_SIZE);
  useEffect(() => { setPage(0); }, [results, sortCol, sortDir]);
  const gotoPage = (p: number) => {
    setPage(Math.max(0, Math.min(pageCount - 1, p)));
    tableWrapRef.current?.scrollTo({ top: 0 });
  };
  const pageNums = useMemo(() => {
    const out: (number | "…")[] = [];
    for (let i = 0; i < pageCount; i++) {
      if (i === 0 || i === pageCount - 1 || Math.abs(i - curPage) <= 2) out.push(i);
      else if (out[out.length - 1] !== "…") out.push("…");
    }
    return out;
  }, [pageCount, curPage]);

  // 0개 진단 — 가장 제한적인(단독 통과 최소) 조건
  const diagnostic = useMemo(() => {
    if (total !== 0 || !group.conditions.length || chipCounts.length !== group.conditions.length) return null;
    let minI = -1, minC = Infinity;
    chipCounts.forEach((c, i) => { if (c != null && c < minC) { minC = c; minI = i; } });
    if (minI < 0) return null;
    return { label: fieldLabel(group.conditions[minI].field), count: minC };
  }, [total, group, chipCounts, fieldLabel]);

  /** 값 칸의 막대 — 판단을 색으로 말하지 않는다(BU2): 한 색, "좋은 쪽"으로 길다(방향을 모르면 값 순서대로). 72px 한 자 안에서.
   *  종합점수는 시트·홈과 같은 소수 한 자리(같은 값을 화면마다 다르게 쓰지 않는다). */
  const heatCell = (id: string, v: unknown) => {
    const range = colRanges[id];
    const pct = range && typeof v === "number" && Number.isFinite(v) && range[1] > range[0] ? (v - range[0]) / (range[1] - range[0]) : 0;
    const hb = id === "composite_score" ? true : metaById.get(id)?.higher_better;
    const width = hb === false ? 1 - pct : pct;
    return (
      <td className="num bsc-cell" key={id}>
        <span className="bsc-cell-fill" style={{ width: `${Math.round(width * 72)}px` }} />
        <span className="bsc-cell-val">{id === "composite_score" && typeof v === "number" ? num(v, 1) : fmtVal(v)}</span>
      </td>
    );
  };

  const renderRow = (it: ScreenerItem, i: number) => {
    const isSel = selected === it.stock_code;
    const fav = favs.has(it.stock_code);
    return (
      <tr key={it.stock_code} className={`bsc-row${isSel ? " selected" : ""}`} data-code={it.stock_code} tabIndex={0}
          onClick={() => setSelected(it.stock_code)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(it.stock_code); } }}>
        <td className="bsc-rank">{i + 1}</td>
        <td className="scr-fav-cell">
          <button type="button" className={`bsc-fav${fav ? " on" : ""}`} aria-pressed={fav}
                  aria-label={fav ? `${it.corp_name} 관심 종목에서 빼기` : `${it.corp_name} 관심 종목에 넣기`}
                  onClick={(e) => toggleFav(it.stock_code, e)}>{fav ? "★" : "☆"}</button>
        </td>
        <td className="scr-name-cell">
          <span className="bsc-name">{it.corp_name}</span>
          <span className="scr-name-sub"><span className="scr-code">{it.stock_code}</span>{it.sector ? <> · {it.sector}</> : null}</span>
        </td>
        <td className="num">{priceWon(typeof it.current_price === "number" ? it.current_price : null)}</td>
        {showMcap && <td className="num">{it.market_cap_억 != null ? `${num(Math.round(it.market_cap_억))}억` : "몰라요"}</td>}
        {shownCols.map((c) => heatCell(c.id, (it as Record<string, unknown>)[c.id]))}
        {heatCell("composite_score", it.composite_score)}
        <td><span className="tx-chip" data-tone="plain">{it.verdict || "판정 없음"}</span></td>
      </tr>
    );
  };

  // ── 답(서버 값만) ──
  const chips: Chip[] = [];
  if (cs.isError) chips.push({ label: "데이터 출처를 확인하지 못했어요", tone: "unknown" });
  else if (cs.data?.mock_allowed) chips.push({ label: "연습용 시세", tone: "practice" });
  if (results) {
    if (typeof results.ingested_count === "number" && typeof results.universe_size === "number" && results.universe_size > 0)
      chips.push({ label: `스냅샷 저장 ${num(results.ingested_count)}/${num(results.universe_size)}`, tone: "plain" });
    if (results.capped) chips.push({ label: "일부만 평가했어요", tone: "assumed" });
    const out = results.liquidity_gate?.filtered_out ?? 0;
    if (gateOn && out > 0) chips.push({ label: `유동성 게이트로 ${num(out)}개 뺐어요`, tone: "plain" });
  }
  const topCodes = sortedItems.slice(0, TOP_BRIDGE).map((it) => it.stock_code);
  const answerFigures: Figure[] = diagnostic ? [{ label: "가장 좁히는 조건", value: `${diagnostic.label} · 단독 ${num(diagnostic.count)}개` }] : [];
  const progressText = prog ? `종목 ${num(prog.done)}/${num(prog.total || uniTotal)}개를 계산하는 중이에요` : "종목을 거르는 중이에요";

  return (
    <div className="tx-page tx-page--wide scr">
      <PageHead title="종목 찾기" lede="조건을 걸어 종목을 골라요." />

      {/* ── 조건 ── */}
      <section className="tx-sec bsc-workspace scr-conds" aria-label="조건">
        <div className="scr-line">
          <label className="scr-line-k" htmlFor="scr-universe">어디서</label>
          <select id="scr-universe" className="scr-select" data-act="universe" value={universe} onChange={(e) => setUniverse(e.target.value)}>
            {UNIVERSES.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
          </select>
        </div>

        <div className="scr-line">
          <span className="scr-line-k" id="scr-mcap-k">시가총액</span>
          <div className="scr-mcap" role="group" aria-labelledby="scr-mcap-k">
            <button type="button" className={`scr-pill${!mcapActive ? " scr-pill--on" : ""}`} aria-pressed={!mcapActive} onClick={() => setMcapRange([0, 100])}>전체</button>
            {MCAP_PRESETS.map((pr) => {
              const r: [number, number] = [pr.min ? mcapToSlider(pr.min) : 0, pr.max ? mcapToSlider(pr.max) : 100];
              const on = mcapRange[0] === r[0] && mcapRange[1] === r[1];
              return <button key={pr.id} type="button" className={`scr-pill${on ? " scr-pill--on" : ""}`} aria-pressed={on} data-act="mcap-preset" onClick={() => setMcapRange(r)}>{pr.label}</button>;
            })}
            <details className="scr-mcap-custom">
              <summary>직접 정하기 <span className="scr-mcap-vals">{mcapRange[0] === 0 ? "최소" : fmtMcapKo(sliderToMcap(mcapRange[0]))} ~ {mcapRange[1] === 100 ? "최대" : fmtMcapKo(sliderToMcap(mcapRange[1]))}</span></summary>
              <div className="bsc-range">
                <div className="bsc-range-fill" style={{ left: `${mcapRange[0]}%`, right: `${100 - mcapRange[1]}%` }} />
                <input type="range" min={0} max={100} value={mcapRange[0]} className="bsc-range-input" aria-label="시가총액 최소"
                  onChange={(e) => { const v = Number(e.target.value); setMcapRange(([, hi]) => [Math.min(v, hi - 1), hi]); }} />
                <input type="range" min={0} max={100} value={mcapRange[1]} className="bsc-range-input" aria-label="시가총액 최대"
                  onChange={(e) => { const v = Number(e.target.value); setMcapRange(([lo]) => [lo, Math.max(v, lo + 1)]); }} />
              </div>
            </details>
          </div>
        </div>
        {mcapActive && results && !showMcap && (
          <p className="scr-note">지금 결과에는 시가총액 값이 없어요 — 시가총액 조건은 그 값이 있는 데이터에서만 걸러져요.</p>
        )}

        <div className="scr-line scr-line--top">
          <span className="scr-line-k">조건</span>
          <div className="scr-cond-list">
            {group.conditions.length === 0 ? (
              <p className="scr-empty">아직 조건이 없어요. 조건을 더하면 그 조건에 맞는 종목만 남아요.</p>
            ) : group.conditions.map((c, i) => {
              const isRank = !!c.rank_mode;
              const name = fieldLabel(c.field);
              return (
                <div key={i} className={`scr-cond${focusedChip === i ? " scr-cond--focus" : ""}`}>
                  <div className="scr-cond-row">
                    <span className="scr-cond-tag" aria-hidden>팩터{i + 1}</span>
                    <span className="scr-cond-name">{name}{c.kind === "technical" && <span className="scr-cond-kind">기술 지표</span>}</span>
                    <span className="scr-cond-edit">
                      {isRank ? (
                        <>
                          <select className="bsc-chip-op" data-act="cond-op" aria-label={`${name} 순위 방향`} value={c.rank_mode!} onChange={(e) => updateCondition(i, { rank_mode: e.target.value as FilterConditionNode["rank_mode"] })}>
                            <option value="top_pct">상위</option><option value="bottom_pct">하위</option>
                          </select>
                          <input className="bsc-chip-val" data-act="cond-val" aria-label={`${name} 순위 %`} type="number" value={String(c.rank_value ?? 30)} onChange={(e) => updateCondition(i, { rank_value: Number(e.target.value) || 0 })} />
                          <span className="scr-cond-unit">%</span>
                        </>
                      ) : (
                        <>
                          <select className="bsc-chip-op" data-act="cond-op" aria-label={`${name} 비교`} value={c.op || "gte"} onChange={(e) => updateCondition(i, { op: e.target.value as FilterConditionNode["op"] })}>
                            <option value="gt">&gt;</option><option value="gte">≥</option><option value="lt">&lt;</option><option value="lte">≤</option><option value="eq">=</option>
                          </select>
                          <input className="bsc-chip-val" data-act="cond-val" aria-label={`${name} 값`} type="number" step="any" value={String(c.value ?? 0)} onFocus={() => setFocusedChip(i)}
                            onChange={(e) => updateCondition(i, { value: e.target.value === "" ? 0 : Number(e.target.value) })} />
                        </>
                      )}
                    </span>
                    <span className="scr-cond-count">{chipCounts[i] != null ? `단독 ${num(chipCounts[i]!)}개` : ""}</span>
                    <button type="button" className="scr-cond-x" data-act="cond-remove" aria-label={`${name} 조건 빼기`} onClick={() => removeCondition(i)}>✕</button>
                  </div>
                  {focusedChip === i && !isRank && (
                    <div className="bsc-hist-panel">
                      <span className="bsc-hist-label">{name} 분포 — 어디서 자를지 정해요</span>
                      <div className="bsc-hist-wrap"><MiniHistogram values={sampleVals(c.field)} op={c.op} threshold={Number(c.value) || 0} /></div>
                    </div>
                  )}
                </div>
              );
            })}
            <div className="scr-cond-act">
              <button type="button" className="bsc-add-btn" data-act="add-factor" onClick={() => setModalOpen(true)}>＋ 조건 더하기</button>
              {group.conditions.length > 0 && <button type="button" className="bsc-rail-clear" data-act="clear" onClick={clearAll}>모두 지우기</button>}
            </div>
          </div>
        </div>

        {/* 전문가 설정 — 기능은 그대로, 기본은 접힘(한 화면 한 일). */}
        <details className="scr-expert" data-act="expert">
          <summary>전문가 설정 <span className="scr-expert-sub">조건식 · 유동성 게이트 · 저장한 조건 · 계산 통계</span></summary>
          <div className="scr-expert-body">
            <div className="bsc-expr">
              <p className="scr-expert-h">조건식</p>
              {group.conditions.length === 0 ? (
                <p className="scr-note">조건을 더하면 ‘팩터1 and (팩터2 or 팩터3)’처럼 묶을 수 있어요.</p>
              ) : (
                <>
                  <div className="bsc-expr-row">
                    <input ref={exprInputRef} className={`bsc-expr-input${exprError ? " err" : ""}`} data-act="expr" aria-label="조건식"
                      value={exprText} placeholder="예: 팩터1 and (팩터2 or 팩터3)" spellCheck={false}
                      onChange={(e) => setExprText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") runSearch(); }} />
                    <button type="button" className="bsc-expr-search" data-act="expr-run" onClick={runSearch}>이 식으로 거르기</button>
                  </div>
                  <div className="bsc-expr-tokens">
                    {group.conditions.map((c, i) => (
                      <button key={i} type="button" className="bsc-expr-token" aria-label={`팩터${i + 1} 넣기 — ${condText(c, fieldLabel)}`} onClick={() => insertAtCursor(`팩터${i + 1}`)}>팩터{i + 1}</button>
                    ))}
                    <span className="bsc-expr-sep" />
                    {["and", "or", "(", ")"].map((op) => (
                      <button key={op} type="button" className="bsc-expr-op" onClick={() => insertAtCursor(op === "and" || op === "or" ? ` ${op} ` : op)}>{op}</button>
                    ))}
                  </div>
                  {exprError
                    ? <p className="bsc-expr-msg err" role="alert">{exprError}</p>
                    : <p className="bsc-expr-msg ok">지금 거르는 식: <b>{committed ? exprText.trim() : "전체 종목(식 없음)"}</b></p>}
                </>
              )}
            </div>

            <label className="scr-gate">
              <input type="checkbox" role="switch" className="scr-switch" data-act="gate" checked={gateOn} onChange={(e) => setGateOn(e.target.checked)} />
              <span>
                <b>유동성 게이트</b>
                <span className="scr-gate-d">시가총액 300억 이상 · 하루 거래대금 3억 이상 · 호가 차이 1% 이하인 종목만 남겨요. 기본은 꺼져 있어요.</span>
              </span>
            </label>

            <div className="bsc-preset">
              <div className="bsc-preset-head">
                <p className="scr-expert-h">저장한 조건</p>
                <button type="button" className="bsc-preset-save" disabled={!group.conditions.length} onClick={() => setShowSave((v) => !v)}>지금 조건 저장</button>
              </div>
              {showSave && (
                <div className="bsc-preset-dialog">
                  <input className="bsc-preset-input" aria-label="저장할 이름" placeholder="이름 (예: 저PER 저PBR)" value={presetName} autoFocus
                    onChange={(e) => setPresetName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }} />
                  <button type="button" className="bsc-preset-confirm" onClick={handleSave}>저장</button>
                </div>
              )}
              {presets.length === 0 ? <p className="scr-note">저장한 조건이 없어요.</p> : (
                <div className="bsc-preset-list">
                  {presets.map((pr) => (
                    <span key={pr.id} className="bsc-preset-chip">
                      <button type="button" className="bsc-preset-chip-name" onClick={() => handleLoad(pr)}>{pr.name} · 조건 {pr.group.conditions.length}개</button>
                      <button type="button" className="bsc-preset-chip-del" aria-label={`${pr.name} 지우기`} onClick={(e) => handleDelete(pr.id, e)}>✕</button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="scr-stats">
              <p className="scr-expert-h">계산 통계</p>
              {results ? (
                <p className="scr-note">
                  유니버스 {num(uniTotal)}종목 · 스냅샷 저장 {num(results.ingested_count ?? 0)} · 평가 {num(results.evaluated_actual ?? results.total_evaluated)}
                  {" "}· 새로 계산 {num(results.cache_misses)} · 캐시 {num(results.cache_hits)} · {results.elapsed_seconds.toFixed(2)}초
                  {results.capped ? " · 저장되지 않은 종목이 많아 이번에는 일부만 평가했어요(데이터 상태에서 전체 적재를 돌리면 풀려요)." : ""}
                </p>
              ) : <p className="scr-note">아직 계산한 결과가 없어요.</p>}
            </div>
          </div>
        </details>
      </section>

      {notice && <div className="scr-notice"><Notice tone="warn" title={notice} /></div>}

      {/* ── 답 ── */}
      <div className="scr-answer-wrap">
        {runError ? (
          <Notice tone="danger" title="종목을 거르지 못했어요">
            스크리너 계산에 닿지 못했어요. 조건은 그대로 두었으니 다시 시도해 주세요.
            <details className="scr-err-detail"><summary>자세히</summary><code>{runError}</code></details>
            <div className="scr-retry"><button type="button" className="tx-btn tx-btn--sub" onClick={() => setRetry((n) => n + 1)}>다시 시도</button></div>
          </Notice>
        ) : !results ? (
          <LoadingState label={progressText} />
        ) : (
          <div className="scr-answer">
            <Answer
              sentence={total ? `조건에 맞는 종목 ${num(total)}개예요` : "조건에 맞는 종목이 없어요"}
              figures={answerFigures} chips={chips}
              action={
                <>
                  {/* 주 행동은 하나 — 조건이 있으면 백테스트, 없으면(보낼 조건이 없다) 설계에 넣기가 주 행동이다. 순서는 그대로. */}
                  <button type="button" className={`tx-btn ${group.conditions.length ? "tx-btn--main" : "tx-btn--sub"}`} data-act="send-backtest" onClick={sendToBacktester} disabled={!group.conditions.length}>이 조건으로 백테스트</button>
                  {topCodes.length > 0 && <Link className={`tx-btn ${group.conditions.length ? "tx-btn--sub" : "tx-btn--main"}`} href={`/allocation?tickers=${topCodes.join(",")}`}>상위 {topCodes.length}종목 설계에 넣기</Link>}
                  {!group.conditions.length && <span className="scr-hint">조건을 하나 이상 더하면 백테스트로 보낼 수 있어요.</span>}
                  {loading && <span className="scr-hint" role="status">{progressText}</span>}
                </>
              } />
          </div>
        )}
      </div>

      {/* ── 결과 ── */}
      {results && !runError && sortedItems.length > 0 && (
        <section className="tx-sec scr-results" aria-label="결과">
          <header className="tx-sec-head">
            <div>
              <h2 className="tx-sec-t">결과</h2>
              <p className="tx-sec-sub">종목을 누르면 자세히 볼 수 있어요.</p>
            </div>
            <div className="scr-tools">
              <button type="button" className="tx-btn tx-btn--sub scr-tool" aria-expanded={showColPicker} onClick={() => setShowColPicker((v) => !v)}>표시 열{displayCols.length ? ` ${displayCols.length}개` : ""}</button>
              <button type="button" className="tx-btn tx-btn--sub scr-tool" onClick={exportCsv}>CSV 내려받기</button>
            </div>
          </header>

          {showColPicker && (
            <div className="bsc-colpicker">
              <div className="bsc-colpicker-head">
                <span>표에 더 볼 열(조건과 따로 — 보기만 해요)</span>
                <input className="bsc-colpicker-search" aria-label="열 찾기" placeholder="열 찾기" value={colSearch} onChange={(e) => setColSearch(e.target.value)} />
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

          <div className="bsc-table-wrap" ref={tableWrapRef}>
            <table className="bsc-table">
              <thead>
                <tr>
                  <th className="bsc-rank">순위</th>
                  <th><span className="tx-sr">관심</span></th>
                  <th>종목</th>
                  <th className="num sortable" aria-sort={sortCol === "current_price" ? (sortDir === "desc" ? "descending" : "ascending") : undefined}>
                    <button type="button" onClick={() => setSort("current_price")}>현재가{sortArrow("current_price")}</button></th>
                  {showMcap && <th className="num sortable"><button type="button" onClick={() => setSort("market_cap_억")}>시가총액{sortArrow("market_cap_억")}</button></th>}
                  {shownCols.map((c) => (
                    <th key={c.id} className={`num sortable${c.filtered ? "" : " viewcol"}`}>
                      <button type="button" onClick={() => setSort(c.id)}>{c.label}{sortArrow(c.id)}</button></th>
                  ))}
                  <th className="num sortable"><button type="button" onClick={() => setSort("composite_score")}>종합점수{sortArrow("composite_score")}</button></th>
                  <th>판정</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((it, vi) => renderRow(it, curPage * PAGE_SIZE + vi))}
              </tbody>
            </table>
          </div>

          {pageCount > 1 && (
            <nav className="bsc-pager" aria-label="결과 쪽">
              <button type="button" onClick={() => gotoPage(curPage - 1)} disabled={curPage === 0}>이전</button>
              {pageNums.map((pn, i) => pn === "…"
                ? <span key={`e${i}`}>…</span>
                : <button type="button" key={pn} className={pn === curPage ? "on" : ""} aria-current={pn === curPage ? "page" : undefined} onClick={() => gotoPage(pn)}>{pn + 1}</button>)}
              <button type="button" onClick={() => gotoPage(curPage + 1)} disabled={curPage >= pageCount - 1}>다음</button>
              <span className="bsc-pager-range">{num(curPage * PAGE_SIZE + 1)}–{num(Math.min(sortedItems.length, (curPage + 1) * PAGE_SIZE))} / {num(sortedItems.length)}</span>
            </nav>
          )}
        </section>
      )}

      {/* ── 자세히(시트) ── */}
      <Sheet open={!!selectedItem} onClose={() => setSelected(null)} title={selectedItem?.corp_name ?? ""} testId="screener-row"
             sub={selectedItem ? <>{selectedItem.stock_code}{selectedItem.sector ? ` · ${selectedItem.sector}` : ""}</> : undefined}>
        {selectedItem && (
          <>
            <dl className="scr-sheet-figs">
              <div className="scr-sheet-fig"><dt>현재가</dt><dd>{priceWon(typeof selectedItem.current_price === "number" ? selectedItem.current_price : null)}</dd></div>
              <div className="scr-sheet-fig"><dt>종합점수</dt><dd>{num(selectedItem.composite_score, 1)}</dd></div>
              <div className="scr-sheet-fig"><dt>판정</dt><dd><span className="tx-chip" data-tone="plain">{selectedItem.verdict || "판정 없음"}</span></dd></div>
              {selectedItem.market_cap_억 != null && <div className="scr-sheet-fig"><dt>시가총액</dt><dd>{num(Math.round(selectedItem.market_cap_억))}억</dd></div>}
              {shownCols.map((c) => (
                <div key={c.id} className="scr-sheet-fig"><dt>{c.label}</dt><dd>{fmtVal((selectedItem as Record<string, unknown>)[c.id])}</dd></div>
              ))}
            </dl>
            <Chips items={cs.data?.mock_allowed ? [{ label: "연습용 시세", tone: "practice" }] : []} label="이 값의 근거" />
            <div className="scr-sheet-act">
              <Link className="tx-btn tx-btn--main" href={`/insights?code=${selectedItem.stock_code}`}>기업 분석 열기</Link>
              <Link className="tx-btn tx-btn--sub" href={`/allocation?tickers=${selectedItem.stock_code}`}>설계에 넣기</Link>
            </div>
          </>
        )}
      </Sheet>

      <FactorPickerModal key={modalOpen ? "open" : "closed"} open={modalOpen} tone="neutral" onClose={() => setModalOpen(false)} onInsert={handlePick} />
    </div>
  );
}
