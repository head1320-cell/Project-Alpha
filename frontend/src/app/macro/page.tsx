"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { LoadingState, ErrorState } from "@/shared/ui/States";
import MacroCockpit, { type TransplantPayload } from "@/widgets/macro/MacroCockpit";
import { loadStrategyBacktestConfig, type MacroCore } from "@/entities/macro/data";
import { setMacroHandoff } from "@/entities/macro/handoff";
import { analysisApi } from "@/entities/macro/analysisApi";
import { macroApi } from "@/entities/macro/api";

export default function MacroPage() {
  const router = useRouter();
  // 5개를 개별 쿼리로 분리 — regime은 Company 탭(CompanyCockpit)의 매크로 로더와 동일한
  // queryKey(["macro","regime"])를 써서 두 탭 간 중복 호출을 캐시 레벨에서 공유한다.
  // 전부 각자 catch(() => null)로 감싸 절대 reject하지 않음(기존 loadMacroCore와 동일 정책).
  const regimeQ = useQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime().catch(() => null) });
  const dashboardQ = useQuery({ queryKey: ["macro", "dashboard"], queryFn: () => analysisApi.macroDashboard().catch(() => null) });
  const valuationQ = useQuery({ queryKey: ["macro", "valuation"], queryFn: () => analysisApi.macroValuation().catch(() => null) });
  const strategiesQ = useQuery({ queryKey: ["macro", "strategies", "kr"], queryFn: () => analysisApi.macroStrategies("kr").catch(() => null) });
  const recommendQ = useQuery({ queryKey: ["macro", "recommend", "kr"], queryFn: () => analysisApi.macroRecommend("kr").catch(() => null) });
  const loading = regimeQ.isLoading || dashboardQ.isLoading || valuationQ.isLoading || strategiesQ.isLoading || recommendQ.isLoading;
  const core: MacroCore | null = loading ? null : {
    regime: regimeQ.data ?? null, dashboard: dashboardQ.data ?? null, valuation: valuationQ.data ?? null,
    strategies: strategiesQ.data ?? null, recommend: recommendQ.data ?? null,
  };
  const err: string | null = null;  // 개별 쿼리가 전부 자체 catch로 null 폴백 — 기존과 동일하게 도달 안 함

  // 전략 백테스트 → 백테스터 셋업 이식 (전략별 mode 구성 fetch + 라우팅)
  const [bridging, setBridging] = useState(false);
  const onTransplant = async (p: TransplantPayload) => {
    setBridging(true);
    try {
      const cfg = await loadStrategyBacktestConfig(p.sid, p.market);
      if (cfg) {
        setMacroHandoff({ config: cfg, createdAt: Date.now() });
        router.push("/backtest");
      }
    } finally {
      setBridging(false);
    }
  };

  return (
    <div className="tpage-fade">
      {loading && <LoadingState label="매크로 데이터 수집 중" />}
      {bridging && <LoadingState label="전략을 백테스터로 구성하는 중" />}
      {err && !loading && <ErrorState sub={err} />}
      {core && !loading && <MacroCockpit core={core} onTransplant={onTransplant} />}
    </div>
  );
}
