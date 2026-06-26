"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import PageHeader from "@/components/layout/PageHeader";
import { LoadingState, ErrorState } from "@/components/layout/States";
import MacroCockpit, { type TransplantPayload } from "@/components/macro/MacroCockpit";
import { loadMacroCore, loadStrategyBacktestConfig, type MacroCore } from "@/lib/macroData";
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
      <PageHeader
        eyebrow="MACRO / ALLOCATION COCKPIT"
        index="03 / 05"
        title="Macro Allocation Cockpit"
        intro="자산배분·마켓타이밍에 직결되는 매크로 지표를 5개 무료 API(BOK·FRED·KIS·DART·KRX)로 수집·정규화하고, 현 국면에 유리한 택티컬 자산배분 전략을 규칙+성과+AI로 추천합니다."
        status={core?.regime ? `REGIME · ${core.regime.regime}` : "SOURCE: BOK·FRED·KIS"}
      />
      {loading && <LoadingState label="매크로 데이터 수집 중" />}
      {bridging && <LoadingState label="전략을 백테스터로 구성하는 중" />}
      {err && !loading && <ErrorState sub={err} />}
      {core && !loading && <MacroCockpit core={core} onTransplant={onTransplant} />}
    </div>
  );
}
