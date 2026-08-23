"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// ScenarioContext — 스트레스 시나리오 슬라이스 (Phase 11b).
//
// ★`scenario` 와 `scenarioPackId` 는 **다른 것**이다★
// 앞엣것은 `/stress` 가 실행할 수 있는 id 로 국내팩을 담지 못한다. 국내팩을 고르면
// `scenario` 는 그대로인데 화면은 국내팩 결과를 보이므로, 컨텍스트 스트립이 `scenario` 를
// 읽으면 **활성 시나리오를 잘못 적는다**. 두 필드를 한 슬라이스에 두되 합치지 않는 이유다.
//
// 이 슬라이스도 `PortfolioProvider` 안에 중첩된다 — 스트레스 쿼리가 보유 비중을 읽는다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { createContext, useContext, useMemo, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  allocationApi, type StressResult, type StressScenarioMeta,
} from "@/entities/allocation/api";
import { usePortfolio } from "./PortfolioContext";

export interface ScenarioSlice {
  scenario: string;
  setScenario: (id: string) => void;
  /** 선택된 **시나리오 팩 신원** (스펙 §4 ⑦, Phase 9) — 위 주석 참고. */
  scenarioPackId: string;
  setScenarioPackId: (id: string) => void;
  /**
   * 되돌린 런이 **기록 당시** 쓴 팩 해시 (Phase 10b). 런을 열지 않았으면 null.
   * 지금 팩의 해시와 다르면 그 사이 충격 정의가 바뀐 것이다.
   */
  runPackHash: string | null;
  setRunPackHash: (h: string | null) => void;
  bump: number;
  setBump: (v: number) => void;
  severity: number;
  setSeverity: (v: number) => void;
  scenarios: StressScenarioMeta[];
  stressQ: UseQueryResult<StressResult | null>;
}

const Ctx = createContext<ScenarioSlice | null>(null);

export function useScenario(): ScenarioSlice {
  const v = useContext(Ctx);
  if (!v) throw new Error("useScenario must be used within ScenarioProvider");
  return v;
}

export function ScenarioProvider({ children }: { children: React.ReactNode }) {
  const { holdings, holdingsMap, holdingsKey } = usePortfolio();
  const [scenario, setScenario] = useState<string>("rate_hike_200bp");
  const [scenarioPackId, setScenarioPackId] = useState<string>("rate_hike_200bp");
  const [runPackHash, setRunPackHash] = useState<string | null>(null);
  const [bump, setBump] = useState(2.0);
  const [severity, setSeverity] = useState(1.0);

  const catalogQ = useQuery({
    queryKey: ["allocation", "stress-catalog"],
    queryFn: () => allocationApi.stressCatalog().catch(() => null),
  });
  const stressQ = useQuery({
    queryKey: ["allocation", "stress", holdingsKey, scenario, severity],
    queryFn: () => allocationApi.stress(holdingsMap, scenario, severity).catch(() => null),
    enabled: holdings.length >= 1 && !!scenario,
  });

  const scenarios = useMemo(() => catalogQ.data?.scenarios || [], [catalogQ.data]);

  const value = useMemo<ScenarioSlice>(() => ({
    scenario, setScenario, scenarioPackId, setScenarioPackId, runPackHash, setRunPackHash,
    bump, setBump, severity, setSeverity, scenarios, stressQ,
  }), [scenario, scenarioPackId, runPackHash, bump, severity, scenarios, stressQ]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
