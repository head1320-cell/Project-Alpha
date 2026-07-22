"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AllocationProvider — Multi-Stage Wizard 전역 상태 (전략 수립 파이프라인 공유)
//   app/allocation/layout.tsx가 마운트 — App Router에서 layout은 자식 라우트
//   전환에도 유지되므로 게이트 ↔ 각 스테이지 이동 시 유니버스·뷰·가중치·결과가
//   증발하지 않는다 (스크린샷의 "Session이나 상태 관리 툴(Context API)" 채택 —
//   워크스페이스 다중화 시 zustand 승격은 R3 문서화).
//   + 위저드 확장: goal(진입 목표)·stageComplete[]·isResultStale·ensureFreshRun·
//     sessionStorage(goal/pos/wip) 하이드레이트·persist → 중간 새로고침 비파괴.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  allocationApi, type AllocationModel, type AllocationViewInput, type AnalyzeResult,
  type CanaryInput, type StressResult, type StressScenarioMeta, type TimingResult,
  type XrayResult,
} from "@/lib/allocationApi";
import { saveStudy, type AllocationStudy } from "@/lib/allocationStorage";
import { researchApi } from "@/lib/researchApi";
import type { TacticalStrategy } from "@/lib/screenerApi";
import type { Holding } from "./PortfolioBuilder";
import type { TimelineEvent } from "./ResearchTimeline";

export const MODELS: { id: AllocationModel; label: string }[] = [
  { id: "mvo", label: "MVO" },
  { id: "bl", label: "Black-Litterman" },
  { id: "risk_parity", label: "Risk Parity" },
  { id: "hrp", label: "HRP" },
  { id: "min_var", label: "Min Var" },
];

export const COV_ONLY: AllocationModel[] = ["risk_parity", "hrp", "min_var"];

// ── 7단계 순차 리서치 파이프라인 (레퍼런스: Portfolio Visualizer 위저드 / Aladdin / Venn) ──
// 00 Overview·06 Journal은 북엔드, 01~05는 3 매크로 페이즈(SETUP/LOGIC/VALIDATION).
export type PhaseKey = "setup" | "logic" | "validation";
export interface StageMeta {
  n: string; href: string; label: string; title: string; desc: string;
  intent: string;            // "이 단계에서 할 일" — StageChrome이 렌더
  phase?: PhaseKey;          // 북엔드(overview/journal)는 undefined
}
export const STAGES: StageMeta[] = [
  { n: "00", href: "/allocation/overview", label: "OVERVIEW", title: "Overview", desc: "전체 워크플로우 요약 — 각 단계로 드릴다운", intent: "현재 포트폴리오를 한눈에 점검하고 필요한 단계로 이동하세요." },
  { n: "01", href: "/allocation/construct", label: "CONSTRUCT", title: "Construct", desc: "자산 구성 — 직접 구성 · 팩터 빌더 · 매크로 전략", intent: "자산을 2개 이상 담거나(직접) 팩터로 자동 구성하고 비중을 맞추세요.", phase: "setup" },
  { n: "02", href: "/allocation/alphalab", label: "ALPHA LAB", title: "Alpha Lab", desc: "알파 표현식 · lint · IC/ICIR 검증 · 레지스트리", intent: "독립 알파를 정의·검증하고 레지스트리로 관리하세요 (선택).", phase: "logic" },
  { n: "03", href: "/allocation/thesis", label: "THESIS", title: "Thesis", desc: "거시 테제 → Black-Litterman 뷰 + 신뢰도", intent: "거시 테제를 자산·방향·신뢰도로 변환하세요 (선택).", phase: "logic" },
  { n: "04", href: "/allocation/timing", label: "TIMING", title: "Timing", desc: "카나리 신호 + 마켓타이밍 — 위험 국면 게이트", intent: "카나리 자산·지표와 추세 필터로 위험-온/오프를 판단하세요 (선택).", phase: "logic" },
  { n: "05", href: "/allocation/optimize", label: "OPTIMIZE", title: "Optimize", desc: "모델·λ·τ + 효율적 프론티어 + 배분 흐름", intent: "엔진과 위험회피(λ)를 조정해 최적 배분을 산출하세요.", phase: "logic" },
  { n: "06", href: "/allocation/stress", label: "STRESS", title: "Stress", desc: "민감도 + 시나리오 severity + 상관-국면 스트레스", intent: "시나리오·충격·상관국면으로 배분의 견고성을 검증하세요.", phase: "validation" },
  { n: "07", href: "/allocation/explain", label: "EXPLAIN", title: "Explain", desc: "단계별 비중 분해 + 리스크·상관 구조", intent: "왜 이 비중인지 단계별로 분해해 확인하세요.", phase: "validation" },
  { n: "08", href: "/allocation/journal", label: "JOURNAL", title: "Journal", desc: "의사결정 기록 + ResearchRun — Macro View→Changed→Reason→Result→Review", intent: "이번 의사결정을 기록하고 사후 검증을 예약하세요." },
];

export interface PhaseMeta { key: PhaseKey; label: string; ko: string; steps: number[] }
export const PHASES: PhaseMeta[] = [
  { key: "setup", label: "SETUP", ko: "설정", steps: [1] },              // 01 Construct
  { key: "logic", label: "LOGIC", ko: "설계", steps: [2, 3, 4, 5] },     // 02 Alpha Lab · 03 Thesis · 04 Timing · 05 Optimize
  { key: "validation", label: "VALIDATION", ko: "검증", steps: [6, 7] }, // 06 Stress · 07 Explain
];

// ── 타이밍(카나리·마켓타이밍) 설정 — 위저드 공유 상태 ──
export interface TimingConfig {
  market: "kr" | "us";
  canaries: CanaryInput[];
  minBreadth: number;                 // 0 = 전부 통과, k = k-of-N
  riskOnAssets: string[];             // 비면 현재 포트폴리오 유지
  riskOffAssets: string[];
  overlay: { type: "ma_day" | "abs_mom" | "none"; n: number; lookback: number };
}
export const DEFAULT_TIMING: TimingConfig = {
  market: "kr",
  canaries: [
    { kind: "asset", id: "SPY", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" },
    { kind: "asset", id: "EFA", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" },
    { kind: "asset", id: "EEM", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" },
    { kind: "asset", id: "AGG", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" },
  ],
  minBreadth: 0,
  riskOnAssets: [],
  riskOffAssets: ["IEF", "SHY"],
  overlay: { type: "none", n: 200, lookback: 12 },
};

export function stageIndex(pathname: string): number {
  // 가장 긴(정확) 매칭 우선. 게이트(/allocation)는 어떤 스테이지도 매칭 안 됨 → 0 폴백
  // (게이트 라우트는 layout의 isGate 분기에서 stageIndex를 소비하지 않으므로 무해).
  let best = -1; let bestLen = -1;
  STAGES.forEach((s, i) => {
    if (pathname === s.href || pathname.startsWith(s.href + "/")) {
      if (s.href.length > bestLen) { best = i; bestLen = s.href.length; }
    }
  });
  return best >= 0 ? best : 0;
}

export interface AllocationGoal { id: string; label: string }

// 매크로 탭에서 불러온 자산배분 전략의 출처 마커 (원 전략 비중 = 최적화 비교 기준선)
export interface LoadedStrategy {
  id: string; name: string; family: string; market: "kr" | "us";
  signal: string; weights: Record<string, number>;
}

// sessionStorage 키 (localStorage 스터디와 별개 — 세션 한정, 중간 새로고침 재개용)
const SS_GOAL = "alpha_alloc_goal";
const SS_WIP = "alpha_alloc_wip";
const SS_POS = "alpha_alloc_pos";

interface AllocationCtx {
  holdings: Holding[];
  setHoldingsReset: (next: Holding[]) => void;
  holdingsMap: Record<string, number>;
  holdingsKey: string;
  views: AllocationViewInput[];
  setViewsLogged: (next: AllocationViewInput[]) => void;
  model: AllocationModel;
  setModel: (m: AllocationModel) => void;
  delta: number;
  setDelta: (v: number) => void;
  tau: number;
  setTau: (v: number) => void;
  result: AnalyzeResult | null;
  scenario: string;
  bump: number;
  setBump: (v: number) => void;
  severity: number;
  setSeverity: (v: number) => void;
  pickScenario: (id: string) => void;
  scenarios: StressScenarioMeta[];
  // ── 타이밍(카나리·마켓타이밍) ──
  timingCfg: TimingConfig;
  setTimingCfg: (next: TimingConfig) => void;
  timingQ: UseQueryResult<TimingResult | null>;
  applyTiming: () => void;             // 타이밍 결과 배분을 포트폴리오에 적용
  timeline: TimelineEvent[];
  logEvent: (msg: string) => void;
  canRun: boolean;
  pending: boolean;
  lastRun: string;
  analyzeError: string | null;
  runAnalyze: (over?: { model?: AllocationModel; tau?: number; views?: AllocationViewInput[] }) => void;
  xrayQ: UseQueryResult<XrayResult | null>;
  stressQ: UseQueryResult<StressResult | null>;
  saveStudyFull: (name: string, fields: Partial<Pick<AllocationStudy,
    "note" | "macro_view" | "changed" | "reason">>) => void;
  loadStudy: (s: AllocationStudy) => void;
  studiesVersion: number;
  bumpStudies: () => void;
  // ── 매크로 전략 로드 (매크로 탭 자산배분 전략 → AAS) ──
  loadedStrategy: LoadedStrategy | null;
  loadStrategy: (strat: TacticalStrategy, market: "kr" | "us") => void;
  clearLoadedStrategy: () => void;
  // ── ResearchRun (P1 재현성) ──
  activeRunId: string | null;
  recordRun: (name: string) => Promise<string | null>;   // 현재 결과를 런으로 기록
  runsVersion: number;                                    // 목록 갱신 신호
  // ── Alpha Lab (P2) ──
  alphaTouched: boolean;                                  // 검증/저장 1회 이상 → 스테이지 완료
  markAlphaTouched: () => void;
  // ── 위저드 확장 ──
  goal: AllocationGoal | null;
  setGoal: (g: AllocationGoal | null) => void;
  lastPos: string | null;                 // 마지막 방문 스테이지 href (Resume용)
  noteVisit: (href: string) => void;      // layout이 pathname 변경 시 호출
  stageComplete: boolean[];               // STAGES 인덱스별 완료 (단일 소스)
  isResultStale: boolean;                 // 현재 입력 대비 result가 낡았나
  ensureFreshRun: () => void;             // 다음 단계 진입 시 stale이면 재최적화
}

const Ctx = createContext<AllocationCtx | null>(null);

export function useAllocation(): AllocationCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAllocation must be used within AllocationProvider");
  return v;
}

export function AllocationProvider({ children }: { children: React.ReactNode }) {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [views, setViews] = useState<AllocationViewInput[]>([]);
  const [model, setModel] = useState<AllocationModel>("bl");
  const [delta, setDelta] = useState(2.5);
  const [tau, setTau] = useState(0.05);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [scenario, setScenario] = useState<string>("rate_hike_200bp");
  const [bump, setBump] = useState(2.0);
  const [severity, setSeverity] = useState(1.0);
  const [timingCfg, setTimingCfgState] = useState<TimingConfig>(DEFAULT_TIMING);
  const [studiesVersion, setStudiesVersion] = useState(0);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [lastRun, setLastRun] = useState("—:—:—");
  const [goal, setGoalState] = useState<AllocationGoal | null>(null);
  const [loadedStrategy, setLoadedStrategy] = useState<LoadedStrategy | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runsVersion, setRunsVersion] = useState(0);
  const [alphaTouched, setAlphaTouched] = useState(false);
  const [lastPos, setLastPos] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);   // persist는 하이드레이트 후에만
  const lastReqRef = useRef<string>("");

  const logEvent = (msg: string) =>
    setTimeline((l) => [{ t: new Date().toTimeString().slice(0, 5), msg }, ...l].slice(0, 40));

  const holdingsMap = useMemo(() => {
    const m: Record<string, number> = {};
    holdings.forEach((h) => { m[h.code] = h.weight; });
    return m;
  }, [holdings]);
  const holdingsKey = useMemo(() => JSON.stringify(holdingsMap), [holdingsMap]);

  // ── sessionStorage 하이드레이트 (마운트 1회, 클라이언트 전용 — SSR 불일치 회피) ──
  useEffect(() => {
    if (typeof window === "undefined") { setHydrated(true); return; }
    try {
      const g = sessionStorage.getItem(SS_GOAL);
      if (g) setGoalState(JSON.parse(g));
      const p = sessionStorage.getItem(SS_POS);
      if (p) setLastPos(p);
      const w = sessionStorage.getItem(SS_WIP);
      if (w) {
        const wip = JSON.parse(w);
        if (Array.isArray(wip.holdings) && wip.holdings.length) setHoldings(wip.holdings);
        if (Array.isArray(wip.views)) setViews(wip.views);
        if (wip.model) setModel(wip.model);
        if (typeof wip.delta === "number") setDelta(wip.delta);
        if (typeof wip.tau === "number") setTau(wip.tau);
        if (wip.timingCfg && typeof wip.timingCfg === "object") setTimingCfgState(wip.timingCfg);
        if (wip.loadedStrategy && typeof wip.loadedStrategy === "object") setLoadedStrategy(wip.loadedStrategy);
      }
    } catch { /* 파싱 실패는 무시 — 빈 상태로 시작 */ }
    setHydrated(true);
  }, []);

  // ── 작업셋 persist (하이드레이트 이후에만 — 하이드레이트 전 빈 상태로 덮어쓰기 방지) ──
  useEffect(() => {
    if (!hydrated || typeof window === "undefined") return;
    try { sessionStorage.setItem(SS_WIP, JSON.stringify({ holdings, views, model, delta, tau, timingCfg, loadedStrategy })); }
    catch { /* 용량 초과 등 무시 */ }
  }, [hydrated, holdings, views, model, delta, tau, timingCfg, loadedStrategy]);

  // ── 종목명 해소 (초기 구성 시 코드 대신 이름 표시 — 게이트 시드/관심그룹/직접코드 공통) ──
  //   이름이 코드 그대로인 홀딩만 배치 해소 → 이름만 패치(비중·키 불변 → 재분석 없음).
  const resolvedNamesRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const pend = holdings
      .filter((h) => h.name === h.code || /^\d{6}$/.test(h.name))
      .map((h) => h.code)
      .filter((c) => c && !resolvedNamesRef.current.has(c));
    if (!pend.length) return;
    pend.forEach((c) => resolvedNamesRef.current.add(c));
    allocationApi.resolveNames(pend).then((labels) => {
      setHoldings((prev) => {
        let changed = false;
        const next = prev.map((h) => {
          const nm = labels[h.code];
          if (nm && nm !== h.code && nm !== h.name) { changed = true; return { ...h, name: nm }; }
          return h;
        });
        return changed ? next : prev;
      });
    }).catch(() => { /* 해소 실패는 코드 폴백 유지 */ });
  }, [holdings]);

  const analyzeMut = useMutation({
    mutationFn: allocationApi.analyze,
    onSuccess: (data) => { if (!data.error) { setResult(data); setLastRun(new Date().toTimeString().slice(0, 8)); } },
  });

  const canRun = holdings.length >= 2;

  // 현재 입력 서명 — runAnalyze의 req와 동일 키 순서/값이어야 stale 판정이 정확
  const currentSig = useMemo(() => JSON.stringify({
    tickers: holdings.map((h) => h.code),
    weights: holdingsMap,
    views: views.filter((v) => v.assets.length > 0 && v.magnitude_pct > 0),
    model, delta, tau,
  }), [holdings, holdingsMap, views, model, delta, tau]);
  const isResultStale = !result || currentSig !== lastReqRef.current;

  const runAnalyze = (over?: { model?: AllocationModel; tau?: number; views?: AllocationViewInput[] }) => {
    if (!canRun || analyzeMut.isPending) return;
    const req = {
      tickers: holdings.map((h) => h.code),
      weights: holdingsMap,
      views: (over?.views ?? views).filter((v) => v.assets.length > 0 && v.magnitude_pct > 0),
      model: over?.model ?? model,
      delta,
      tau: over?.tau ?? tau,
    };
    const key = JSON.stringify(req);
    if (key === lastReqRef.current) return; // 동일 요청 중복 방지
    lastReqRef.current = key;
    analyzeMut.mutate(req);
    logEvent(`재최적화 — ${req.model.toUpperCase()} · λ ${delta.toFixed(1)} · τ ${req.tau} · 뷰 ${req.views.length}개`);
  };

  // 다음 단계 진입(특히 VALIDATION) 시 결과가 낡았으면 자동 재최적화 (dedupe라 무해)
  const ensureFreshRun = () => { if (canRun && !analyzeMut.isPending && isResultStale) runAnalyze(); };

  const xrayQ = useQuery({
    queryKey: ["allocation", "xray", holdingsKey],
    queryFn: () => allocationApi.factorXray(holdingsMap).catch(() => null),
    enabled: holdings.length >= 1,
  });
  const catalogQ = useQuery({
    queryKey: ["allocation", "stress-catalog"],
    queryFn: () => allocationApi.stressCatalog().catch(() => null),
  });
  const stressQ = useQuery({
    queryKey: ["allocation", "stress", holdingsKey, scenario, severity],
    queryFn: () => allocationApi.stress(holdingsMap, scenario, severity).catch(() => null),
    enabled: holdings.length >= 1 && !!scenario,
  });

  // ── 타이밍(카나리·마켓타이밍) 쿼리 — 설정/보유 변경 시 자동 재계산 ──
  const timingCfgKey = useMemo(() => JSON.stringify(timingCfg), [timingCfg]);
  const timingQ = useQuery({
    queryKey: ["allocation", "timing", timingCfgKey, holdingsKey],
    queryFn: () => allocationApi.timing({
      market: timingCfg.market,
      canaries: timingCfg.canaries,
      min_breadth: timingCfg.minBreadth,
      risk_on_assets: timingCfg.riskOnAssets,
      risk_off_assets: timingCfg.riskOffAssets,
      holdings: holdings.length ? holdingsMap : null,
      overlay: timingCfg.overlay,
    }).catch(() => null),
    enabled: timingCfg.canaries.length >= 1,
  });

  const setTimingCfg = (next: TimingConfig) => setTimingCfgState(next);

  const scenarios = catalogQ.data?.scenarios || [];
  const pickScenario = (id: string) => {
    setScenario(id);
    const label = scenarios.find((x) => x.id === id)?.label || id;
    logEvent(`시나리오 전환 — ${label}`);
  };

  const setHoldingsReset = (next: Holding[]) => {
    setHoldings(next);
    setResult(null);
    lastReqRef.current = "";
    setLoadedStrategy(null);   // 수동 편집·타 소스 로드는 매크로 전략 출처를 해제
  };

  // 매크로 탭 자산배분 전략 → AAS 포트폴리오. 원 전략 비중을 마커에 보존(비교 기준선).
  const loadStrategy = (strat: TacticalStrategy, market: "kr" | "us") => {
    const hold: Holding[] = (strat.holdings || [])
      .filter((h) => h.weight > 0)
      .map((h) => ({ code: h.ticker, name: h.label || h.ticker, weight: h.weight }));
    setHoldingsReset(hold);   // 마커 초기화 후
    setLoadedStrategy({       // 이 전략으로 재설정
      id: strat.id, name: strat.name, family: strat.family ?? "momentum", market,
      signal: strat.signal, weights: Object.fromEntries(hold.map((h) => [h.code, h.weight])),
    });
    logEvent(`매크로 전략 불러오기 — ${strat.name} (${strat.holdings?.length ?? 0}자산)`);
  };
  const clearLoadedStrategy = () => setLoadedStrategy(null);

  // ── ResearchRun 기록 — 서버측 opt-in 경로: analyze를 record_run=true로 재실행해
  //    서버가 계산한 결과를 서버가 스탬프(inputs/outputs 정합 + code_version 보존).
  //    스터디(localStorage 초안)와 별개의, DB 영속 재현성 단위.
  const recordRun = async (name: string): Promise<string | null> => {
    if (!canRun) return null;
    try {
      const data = await allocationApi.analyze({
        tickers: holdings.map((h) => h.code),
        weights: holdingsMap,
        views: views.filter((v) => v.assets.length > 0 && v.magnitude_pct > 0),
        model, delta, tau,
        record_run: true, run_name: name.trim() || undefined,
      });
      if (data.error) return null;
      setResult(data);
      setLastRun(new Date().toTimeString().slice(0, 8));
      const rid = data.run_id ?? null;
      if (rid) {
        setActiveRunId(rid);
        setRunsVersion((v) => v + 1);
        logEvent(`런 기록 — ${name.trim() || rid} (${model.toUpperCase()})`);
      } else {
        logEvent("런 기록 실패 — DB 미가용");
      }
      return rid;
    } catch {
      logEvent("런 기록 실패 — 네트워크 오류");
      return null;
    }
  };

  const applyTiming = () => {
    const data = timingQ.data;
    if (!data || data.error || !data.holdings?.length) return;
    setHoldingsReset(data.holdings
      .filter((h) => h.weight > 0)
      .map((h) => ({ code: h.code, name: h.label || h.code, weight: h.weight })));
    logEvent(`타이밍 배분 적용 — ${data.canary.signal === "risk_on" ? "위험-온" : "위험-오프"}`);
  };

  const setViewsLogged = (next: AllocationViewInput[]) => {
    if (next.length > views.length) logEvent("테제(뷰) 추가");
    else if (next.length < views.length) logEvent("테제(뷰) 삭제");
    setViews(next);
  };

  const loadStudy = (s: AllocationStudy) => {
    setHoldings(Object.entries(s.holdings).map(([code, weight]) => ({
      code, weight, name: s.names?.[code] || result?.labels?.[code] || code,
    })));
    setViews(s.views || []);
    setModel(s.model);
    setDelta(s.delta);
    setTau(s.tau);
    setResult(null);
    lastReqRef.current = "";
    setLoadedStrategy(null);
    logEvent(`스터디 로드 — ${s.name}`);
  };

  const saveStudyFull: AllocationCtx["saveStudyFull"] = (name, fields) => {
    const names: Record<string, string> = {};
    holdings.forEach((h) => { names[h.code] = h.name; });
    const pf = result?.summary?.portfolio;
    const topW = result
      ? Object.entries(result.weights.optimized).sort((a, b) => b[1] - a[1]).slice(0, 3)
          .map(([c, w]) => `${result.labels[c] || c} ${w.toFixed(1)}%`).join(" · ")
      : "";
    const result_summary = pf
      ? `기대수익 ${pf.expected_return_pct}% · 변동성 ${pf.volatility_pct}% · Sharpe ${pf.sharpe}${topW ? ` | ${topW}` : ""}`
      : undefined;
    saveStudy(name, {
      holdings: holdingsMap, names, views, model, delta, tau,
      result_summary, ...fields,
    });
    logEvent(`스터디 저장 — ${name.trim() || "이름 없음"}`);
    setStudiesVersion((v) => v + 1);
  };

  // ── 위저드 상태 ──
  const setGoal = (g: AllocationGoal | null) => {
    setGoalState(g);
    try {
      if (typeof window !== "undefined") {
        if (g) sessionStorage.setItem(SS_GOAL, JSON.stringify(g));
        else sessionStorage.removeItem(SS_GOAL);
      }
    } catch { /* ignore */ }
  };
  const noteVisit = (href: string) => {
    setLastPos(href);
    try { if (typeof window !== "undefined") sessionStorage.setItem(SS_POS, href); } catch { /* ignore */ }
  };

  const stageComplete = useMemo(() => [
    !!result,                                             // 00 overview
    holdings.length >= 2,                                 // 01 construct (SETUP)
    alphaTouched,                                         // 02 alpha lab (LOGIC)
    views.length > 0,                                     // 03 thesis    (LOGIC)
    !!timingQ.data && !timingQ.data.error,                // 04 timing    (LOGIC)
    !!result,                                             // 05 optimize  (LOGIC)
    !!result,                                             // 06 stress    (VALIDATION)
    !!result,                                             // 07 explain   (VALIDATION)
    timeline.some((e) => e.msg.startsWith("스터디 저장") || e.msg.startsWith("런 기록")),  // 08 journal
  ], [result, holdings.length, views.length, timeline, timingQ.data, alphaTouched]);

  const value: AllocationCtx = {
    holdings, setHoldingsReset, holdingsMap, holdingsKey,
    views, setViewsLogged,
    model, setModel, delta, setDelta, tau, setTau,
    result, scenario, bump, setBump, severity, setSeverity, pickScenario, scenarios,
    timingCfg, setTimingCfg, timingQ, applyTiming,
    timeline, logEvent,
    canRun, pending: analyzeMut.isPending, lastRun,
    analyzeError: analyzeMut.data?.error ? (analyzeMut.data.message ?? "분석 실패") : null,
    runAnalyze, xrayQ, stressQ,
    saveStudyFull, loadStudy, studiesVersion,
    bumpStudies: () => setStudiesVersion((v) => v + 1),
    loadedStrategy, loadStrategy, clearLoadedStrategy,
    activeRunId, recordRun, runsVersion,
    alphaTouched, markAlphaTouched: () => setAlphaTouched(true),
    goal, setGoal, lastPos, noteVisit, stageComplete, isResultStale, ensureFreshRun,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
