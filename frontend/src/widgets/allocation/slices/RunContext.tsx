"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RunContext — 최적화 **결과**와 그 신원 슬라이스 (Phase 11b).
//
// 담는 것: 결과(`result`)·마지막 실행 시각·활성 런/스터디 신원·목록 갱신 신호,
// 그리고 결과를 만들어 내는 두 통로(`mutateAnalyze`, `xrayQ`).
//
// ★`lastReqRef` 가 여기 있는 이유★
// stale 판정("지금 입력으로 이 결과가 나왔나")은 결과의 성질이지 입력의 성질이 아니다.
// 입력 슬라이스에 두면 결과를 비울 때마다 남의 상태를 만져야 한다.
//
// 뮤테이션 객체를 통째로 노출하지 않는다 — 조립 계층이 필요한 것은 `mutate`·`isPending`·
// 에러 문구뿐이고, 객체를 넘기면 슬라이스 경계가 react-query 구현 세부로 새어 나간다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { createContext, useContext, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { allocationApi, type AnalyzeResult, type XrayResult } from "@/entities/allocation/api";
import { usePortfolio } from "./PortfolioContext";

export type AnalyzeRequest = Parameters<typeof allocationApi.analyze>[0];

export interface RunSlice {
  result: AnalyzeResult | null;
  setResult: (r: AnalyzeResult | null) => void;
  /** 마지막 실행 시각 "HH:MM:SS" — 아직 없으면 "—:—:—". */
  lastRun: string;
  markRunNow: () => void;
  pending: boolean;
  analyzeError: string | null;
  mutateAnalyze: (req: AnalyzeRequest) => void;
  /** 마지막으로 보낸 요청 서명 — 중복 방지 + stale 판정의 기준점. */
  lastReqRef: React.MutableRefObject<string>;
  xrayQ: UseQueryResult<XrayResult | null>;
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
  runsVersion: number;
  bumpRuns: () => void;
  activeStudy: { id: string; name: string } | null;
  setActiveStudy: (s: { id: string; name: string } | null) => void;
  studiesVersion: number;
  bumpStudies: () => void;
}

const Ctx = createContext<RunSlice | null>(null);

export function useRun(): RunSlice {
  const v = useContext(Ctx);
  if (!v) throw new Error("useRun must be used within RunProvider");
  return v;
}

export function RunProvider({ children }: { children: React.ReactNode }) {
  const { holdings, holdingsMap, holdingsKey } = usePortfolio();
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [lastRun, setLastRun] = useState("—:—:—");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runsVersion, setRunsVersion] = useState(0);
  const [activeStudy, setActiveStudy] = useState<{ id: string; name: string } | null>(null);
  const [studiesVersion, setStudiesVersion] = useState(0);
  const lastReqRef = useRef<string>("");

  const markRunNow = () => setLastRun(new Date().toTimeString().slice(0, 8));

  const analyzeMut = useMutation({
    mutationFn: allocationApi.analyze,
    onSuccess: (data) => { if (!data.error) { setResult(data); markRunNow(); } },
  });

  const xrayQ = useQuery({
    queryKey: ["allocation", "xray", holdingsKey],
    queryFn: () => allocationApi.factorXray(holdingsMap).catch(() => null),
    enabled: holdings.length >= 1,
  });

  const analyzeError = analyzeMut.data?.error
    ? (analyzeMut.data.message ?? "분석 실패") : null;

  const value = useMemo<RunSlice>(() => ({
    result, setResult, lastRun, markRunNow,
    pending: analyzeMut.isPending, analyzeError, mutateAnalyze: analyzeMut.mutate,
    lastReqRef, xrayQ,
    activeRunId, setActiveRunId,
    runsVersion, bumpRuns: () => setRunsVersion((v) => v + 1),
    activeStudy, setActiveStudy,
    studiesVersion, bumpStudies: () => setStudiesVersion((v) => v + 1),
  }), [result, lastRun, analyzeMut.isPending, analyzeError, analyzeMut.mutate,
       xrayQ, activeRunId, runsVersion, activeStudy, studiesVersion]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
