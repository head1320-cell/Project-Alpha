"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// PortfolioContext — 배분의 **기반 상태** (Phase 11b).
//
// 왜 이것이 기반인가
// ─────────────────────────────────────────────────────────────────────────────
// `runAnalyze` · `recordRun` · 타이밍 쿼리가 전부 여기를 읽는다(실측: holdings·views·
// model·delta·tau·constraints). 그래서 타이밍/시나리오/런을 **형제**로 나누는 설계는 성립하지
// 않는다 — 이 슬라이스가 바깥에 있고 나머지가 그 안에 중첩된다.
//
// ★슬라이스는 **날것의 상태**만 갖는다★
// `setHoldingsReset` 은 보유를 바꾸면서 `result` 를 비우고 타임라인에 기록한다 — 즉 다른
// 슬라이스를 건드린다. 그런 합성 동작은 조립 계층(`AllocationProvider`)이 만든다. 슬라이스가
// 서로를 알기 시작하면 나눈 의미가 없다.
//
// ★하이드레이트는 각자, 저장은 한 곳★
// 각 슬라이스가 같은 `alpha_alloc_wip` 블롭에서 **자기 필드만** 읽는다(읽기는 서로 간섭하지
// 않는다). 쓰기는 정반대다 — 슬라이스마다 같은 키에 쓰면 서로를 덮어쓴다. 그래서 저장은
// 모든 컨텍스트를 볼 수 있는 곳에서 **한 번에** 한다(`WipPersistence`). 키 형식을 쪼개면
// 기존 세션과 E2E 시드가 깨지므로 형식은 한 글자도 바꾸지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

import type { AllocationModel, AllocationViewInput, ConstraintsInput } from "@/entities/allocation/api";
import type { Holding } from "../PortfolioBuilder";

/** 작업셋 키 — 슬라이스가 나뉘어도 **저장 형식은 불변**이다. */
export const SS_WIP = "alpha_alloc_wip";

export interface PortfolioSlice {
  holdings: Holding[];
  setHoldings: React.Dispatch<React.SetStateAction<Holding[]>>;
  holdingsMap: Record<string, number>;
  holdingsKey: string;
  views: AllocationViewInput[];
  setViews: React.Dispatch<React.SetStateAction<AllocationViewInput[]>>;
  model: AllocationModel;
  setModel: (m: AllocationModel) => void;
  delta: number;
  setDelta: (v: number) => void;
  tau: number;
  setTau: (v: number) => void;
  constraints: ConstraintsInput | null;
  setConstraints: (c: ConstraintsInput | null) => void;
  /** 하이드레이트 완료 — 저장은 이 뒤에만(빈 상태로 덮어쓰기 방지). */
  hydrated: boolean;
}

const Ctx = createContext<PortfolioSlice | null>(null);

export function usePortfolio(): PortfolioSlice {
  const v = useContext(Ctx);
  if (!v) throw new Error("usePortfolio must be used within PortfolioProvider");
  return v;
}

export function PortfolioProvider({ children }: { children: React.ReactNode }) {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [views, setViews] = useState<AllocationViewInput[]>([]);
  const [model, setModel] = useState<AllocationModel>("bl");
  const [delta, setDelta] = useState(2.5);
  const [tau, setTau] = useState(0.05);
  const [constraints, setConstraints] = useState<ConstraintsInput | null>(null);
  const [hydrated, setHydrated] = useState(false);

  const holdingsMap = useMemo(() => {
    const m: Record<string, number> = {};
    holdings.forEach((h) => { m[h.code] = h.weight; });
    return m;
  }, [holdings]);
  const holdingsKey = useMemo(() => JSON.stringify(holdingsMap), [holdingsMap]);

  // 자기 필드만 복원한다 — 같은 블롭을 다른 슬라이스도 읽지만 서로 간섭하지 않는다.
  useEffect(() => {
    if (typeof window === "undefined") { setHydrated(true); return; }
    try {
      const w = sessionStorage.getItem(SS_WIP);
      if (w) {
        const wip = JSON.parse(w);
        if (Array.isArray(wip.holdings) && wip.holdings.length) setHoldings(wip.holdings);
        if (Array.isArray(wip.views)) setViews(wip.views);
        if (wip.model) setModel(wip.model);
        if (typeof wip.delta === "number") setDelta(wip.delta);
        if (typeof wip.tau === "number") setTau(wip.tau);
        if (wip.constraints && typeof wip.constraints === "object") setConstraints(wip.constraints);
      }
    } catch { /* 파싱 실패는 무시 — 빈 상태로 시작 */ }
    setHydrated(true);
  }, []);

  const value = useMemo<PortfolioSlice>(() => ({
    holdings, setHoldings, holdingsMap, holdingsKey,
    views, setViews, model, setModel, delta, setDelta, tau, setTau,
    constraints, setConstraints, hydrated,
  }), [holdings, holdingsMap, holdingsKey, views, model, delta, tau, constraints, hydrated]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
