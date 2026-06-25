"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import PageHeader from "@/components/layout/PageHeader";
import { LoadingState, ErrorState } from "@/components/layout/States";
import MacroCockpit, { type TransplantPayload } from "@/components/macro/MacroCockpit";
import { loadMacroCore, type MacroCore } from "@/lib/macroData";
import { setMacroHandoff } from "@/lib/macroHandoff";

export default function MacroPage() {
  const router = useRouter();
  const [core, setCore] = useState<MacroCore | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    loadMacroCore()
      .then(setCore)
      .catch((e) => setErr(e instanceof Error ? e.message : "로드 실패"))
      .finally(() => setLoading(false));
  }, []);

  // 추천 배분 → 백테스터 이식 (asset_alloc 바스켓 프리필 + 라우팅)
  const onTransplant = (p: TransplantPayload) => {
    const total = p.holdings.reduce((s, h) => s + h.weight, 0) || 1;
    setMacroHandoff({
      strategyName: p.strategyName,
      market: p.market,
      basket: p.holdings.map((h) => ({
        ticker: h.ticker,
        name: p.market === "kr" ? h.label : h.us_label,
        weightPct: Math.round((h.weight / total) * 1000) / 10,
      })),
      rebalanceMonths: 3,
      createdAt: Date.now(),
    });
    router.push("/backtest");
  };

  return (
    <div className="tpage-fade">
      <PageHeader
        eyebrow="MACRO / ALLOCATION COCKPIT"
        index="03 / 05"
        title="Macro Allocation Cockpit"
        intro="자산배분·마켓타이밍에 직결되는 매크로 지표를 5개 무료 API(BOK·FRED·KIS·DART·KRX)로 수집·정규화하고, 현 국면에 유리한 택티컬 자산배분 전략을 규칙+성과+AI로 추천합니다."
        status={core?.regime ? `REGIME · ${core.regime.regime}` : "SOURCE: BOK·FRED·KIS"}
      />
      {loading && <LoadingState label="매크로 데이터 수집 중" />}
      {err && !loading && <ErrorState sub={err} />}
      {core && !loading && <MacroCockpit core={core} onTransplant={onTransplant} />}
    </div>
  );
}
