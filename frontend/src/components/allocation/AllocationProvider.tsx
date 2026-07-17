"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AllocationProvider — Research OS 전역 상태 (마이크로 워크스페이스 공유)
//   app/allocation/layout.tsx가 마운트 — App Router에서 layout은 자식 라우트
//   전환에도 유지되므로 /allocation ↔ /allocation/robustness 이동 시 유니버스·
//   뷰·가중치·결과가 증발하지 않는다 (지시서의 useContext 채택 — 워크스페이스
//   다중화 시 zustand 승격은 R3 문서화).
//   로직은 구 AllocationStudio.tsx에서 그대로 리프트 (동작 불변).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { createContext, useContext, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  allocationApi, type AllocationModel, type AllocationViewInput, type AnalyzeResult,
  type StressResult, type StressScenarioMeta, type XrayResult,
} from "@/lib/allocationApi";
import { saveStudy, type AllocationStudy } from "@/lib/allocationStorage";
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
  pickScenario: (id: string) => void;
  scenarios: StressScenarioMeta[];
  timeline: TimelineEvent[];
  logEvent: (msg: string) => void;
  canRun: boolean;
  pending: boolean;
  analyzeError: string | null;
  runAnalyze: (over?: { model?: AllocationModel; tau?: number; views?: AllocationViewInput[] }) => void;
  xrayQ: UseQueryResult<XrayResult | null>;
  stressQ: UseQueryResult<StressResult | null>;
  saveStudyFull: (name: string, fields: Partial<Pick<AllocationStudy,
    "note" | "macro_view" | "changed" | "reason">>) => void;
  loadStudy: (s: AllocationStudy) => void;
  studiesVersion: number;
  bumpStudies: () => void;
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
  const [studiesVersion, setStudiesVersion] = useState(0);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const lastReqRef = useRef<string>("");

  const logEvent = (msg: string) =>
    setTimeline((l) => [{ t: new Date().toTimeString().slice(0, 5), msg }, ...l].slice(0, 40));

  const holdingsMap = useMemo(() => {
    const m: Record<string, number> = {};
    holdings.forEach((h) => { m[h.code] = h.weight; });
    return m;
  }, [holdings]);
  const holdingsKey = useMemo(() => JSON.stringify(holdingsMap), [holdingsMap]);

  const analyzeMut = useMutation({
    mutationFn: allocationApi.analyze,
    onSuccess: (data) => { if (!data.error) setResult(data); },
  });

  const canRun = holdings.length >= 2;

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
    queryKey: ["allocation", "stress", holdingsKey, scenario],
    queryFn: () => allocationApi.stress(holdingsMap, scenario).catch(() => null),
    enabled: holdings.length >= 1 && !!scenario,
  });

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

  const value: AllocationCtx = {
    holdings, setHoldingsReset, holdingsMap, holdingsKey,
    views, setViewsLogged,
    model, setModel, delta, setDelta, tau, setTau,
    result, scenario, pickScenario, scenarios,
    timeline, logEvent,
    canRun, pending: analyzeMut.isPending,
    analyzeError: analyzeMut.data?.error ? (analyzeMut.data.message ?? "분석 실패") : null,
    runAnalyze, xrayQ, stressQ,
    saveStudyFull, loadStudy, studiesVersion,
    bumpStudies: () => setStudiesVersion((v) => v + 1),
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
