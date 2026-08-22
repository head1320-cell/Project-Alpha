"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// TimingContext — 타이밍 슬라이스 (Phase 11b).
//
// `PortfolioProvider` **안에** 중첩된다. 타이밍 쿼리가 보유 종목을 읽기 때문이다 —
// 형제로 두면 보유를 prop 으로 흘려보내야 하고, 그건 컨텍스트를 쓰는 이유를 지운다.
//
// ★두 종류의 저장을 구분한다★
//  · `alpha_alloc_wip` — **여러 슬라이스가 공유하는** 블롭. 읽기는 각자, 쓰기는 조립 계층이
//    한 번에(슬라이스마다 같은 키에 쓰면 서로를 덮어쓴다).
//  · `alpha_alloc_ruleset` — 이 슬라이스 **전용** 키. 공유가 없으니 읽기·쓰기 모두 여기서 한다.
//
// 로그(`logEvent`)는 여기 없다. 타임라인은 다른 슬라이스의 상태이고, 슬라이스가 서로를
// 알기 시작하면 나눈 의미가 없다 — 로그를 붙이는 것은 조립 계층의 일이다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { allocationApi, type CanaryInput, type TimingResult } from "@/entities/allocation/api";
import { SS_WIP, usePortfolio } from "./PortfolioContext";

/** 룰셋 신원 전용 키 — WIP 블롭과 달리 이 슬라이스만 쓴다. */
export const SS_RULESET = "alpha_alloc_ruleset";

// ── 타이밍(카나리·마켓타이밍) 설정 — 위저드 공유 상태 ──
export interface TimingConfig {
  market: "kr" | "us";
  canaries: CanaryInput[];
  minBreadth: number;                 // 0 = 전부 통과, k = k-of-N
  riskOnAssets: string[];             // 비면 현재 포트폴리오 유지
  riskOffAssets: string[];
  overlay: { type: "ma_day" | "abs_mom" | "none"; n: number; lookback: number };
  regimeBlend: boolean;               // 국면확률 가중 연속 노출(휩쏘 억제)
  targetVolPct: number | null;        // 목표 변동성(연 %) — 위험자산 노출 스케일
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
  regimeBlend: false,
  targetVolPct: null,
};

export type TimingOverlay = { exposure: number; source: "canary" } | null;
export type RuleSetRef = { id: string; version: number | null } | null;

export interface TimingSlice {
  timingCfg: TimingConfig;
  setTimingCfg: (next: TimingConfig) => void;
  timingQ: UseQueryResult<TimingResult | null>;
  timingOverlay: TimingOverlay;
  setTimingOverlay: (o: TimingOverlay) => void;
  activeRuleSet: RuleSetRef;
  /** 상태 + 전용 키 저장까지. 타임라인 기록은 조립 계층이 덧붙인다. */
  persistActiveRuleSet: (r: RuleSetRef) => void;
}

const Ctx = createContext<TimingSlice | null>(null);

export function useTiming(): TimingSlice {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTiming must be used within TimingProvider");
  return v;
}

export function TimingProvider({ children }: { children: React.ReactNode }) {
  const { holdings, holdingsMap, holdingsKey } = usePortfolio();
  const [timingCfg, setTimingCfg] = useState<TimingConfig>(DEFAULT_TIMING);
  const [timingOverlay, setTimingOverlay] = useState<TimingOverlay>(null);
  const [activeRuleSet, setActiveRuleSet] = useState<RuleSetRef>(null);

  // 자기 필드만 복원한다 — WIP 블롭에서 둘, 전용 키에서 하나.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      // 룰셋은 ID+버전만 복원한다 — 본문은 서버의 timing_rule_set_versions 가 진실이다.
      const rs = sessionStorage.getItem(SS_RULESET);
      if (rs) { try { setActiveRuleSet(JSON.parse(rs)); } catch { /* 손상된 값은 버린다 */ } }
      const w = sessionStorage.getItem(SS_WIP);
      if (!w) return;
      const wip = JSON.parse(w);
      if (wip.timingCfg && typeof wip.timingCfg === "object") setTimingCfg(wip.timingCfg);
      // 오버레이도 새로고침을 견뎌야 한다 — 제약과 같은 성격의 **결정 입력**이고, 사라지면
      // 사용자는 노출을 줄여 둔 줄 알고 있는데 실제로는 전액 노출로 돌아가 있다.
      if (wip.timingOverlay && typeof wip.timingOverlay === "object") {
        const ex = Number((wip.timingOverlay as { exposure?: unknown }).exposure);
        if (Number.isFinite(ex)) setTimingOverlay({ exposure: Math.max(0, Math.min(1, ex)), source: "canary" });
      }
    } catch { /* 파싱 실패는 무시 — 빈 상태로 시작 */ }
  }, []);

  const persistActiveRuleSet = (r: RuleSetRef) => {
    setActiveRuleSet(r);
    try {
      if (typeof window === "undefined") return;
      if (r) sessionStorage.setItem(SS_RULESET, JSON.stringify(r));
      else sessionStorage.removeItem(SS_RULESET);
    } catch { /* ignore */ }
  };

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
      regime_blend: timingCfg.regimeBlend,
      target_vol_pct: timingCfg.targetVolPct,
    }).catch(() => null),
    enabled: timingCfg.canaries.length >= 1,
  });

  const value = useMemo<TimingSlice>(() => ({
    timingCfg, setTimingCfg, timingQ, timingOverlay, setTimingOverlay,
    activeRuleSet, persistActiveRuleSet,
  }), [timingCfg, timingQ, timingOverlay, activeRuleSet]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
