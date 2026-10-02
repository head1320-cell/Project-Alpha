"use client";
/**
 * /macro — 경제 흐름 (BU5a)
 * ★실패를 실패로★ 예전엔 다섯 쿼리가 모두 `.catch(() => null)` 로 실패를 삼켜, 국면이 실패하면 "백엔드 연결을 확인하세요" 한 줄,
 * 다른 데이터가 실패하면 빈 카드("데이터 없음")가 됐다. 이제 react-query 의 실패 상태를 그대로 쓴다 —
 * 국면 실패는 화면 전체 alert + [다시 시도], 나머지는 그 데이터를 쓰는 탭 안에서 alert + [다시 시도].
 * `["macro","regime"]` 는 홈·기업 분석·셸 prefetch 와 같은 키다 — 성공 값 `null` 도 실패로 그린다(누가 다시 삼켜도 침묵하지 않는다).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { LoadingState } from "@/shared/ui/States";
import { Notice } from "@/shared/ui/tx";
import MacroCockpit, { type CoreKey, type TransplantPayload } from "@/widgets/macro/MacroCockpit";
import MacroIntelPanel from "@/widgets/macro/MacroIntelPanel";
import { loadStrategyBacktestConfig } from "@/entities/macro/data";
import { setMacroHandoff } from "@/entities/macro/handoff";
import { analysisApi } from "@/entities/macro/analysisApi";
import { macroApi } from "@/entities/macro/api";
import { regimeSnapshotApi } from "@/entities/regime-snapshot/api";

export default function MacroPage() {
  const router = useRouter();
  // 5개를 개별 쿼리로 — regime 은 홈·기업 분석과 같은 queryKey(["macro","regime"])라 캐시를 공유한다.
  const regimeQ = useQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime() });
  const dashboardQ = useQuery({ queryKey: ["macro", "dashboard"], queryFn: () => analysisApi.macroDashboard() });
  const valuationQ = useQuery({ queryKey: ["macro", "valuation"], queryFn: () => analysisApi.macroValuation() });
  const strategiesQ = useQuery({ queryKey: ["macro", "strategies", "kr"], queryFn: () => analysisApi.macroStrategies("kr") });
  const recommendQ = useQuery({ queryKey: ["macro", "recommend", "kr"], queryFn: () => analysisApi.macroRecommend("kr") });
  const loading = regimeQ.isLoading || dashboardQ.isLoading || valuationQ.isLoading || strategiesQ.isLoading || recommendQ.isLoading;
  const regime = regimeQ.data ?? null;
  // 실패한 코어 데이터 → 다시 묻는 함수(탭이 alert 옆 [다시 시도]로 쓴다)
  const coreFail: Partial<Record<CoreKey, () => void>> = {};
  const queries = { dashboard: dashboardQ, valuation: valuationQ, strategies: strategiesQ, recommend: recommendQ };
  for (const [k, q] of Object.entries(queries) as [CoreKey, typeof dashboardQ | typeof valuationQ | typeof strategiesQ | typeof recommendQ][]) {
    if (q.isError || (!q.isLoading && q.data == null)) coreFail[k] = () => { void q.refetch(); };
  }

  // 전략 백테스트 → 백테스터 셋업 이식 (전략별 mode 구성 fetch + 라우팅)
  const [bridging, setBridging] = useState(false);
  const [bridgeErr, setBridgeErr] = useState<string | null>(null);
  const onTransplant = async (p: TransplantPayload) => {
    setBridging(true);
    setBridgeErr(null);
    try {
      const cfg = await loadStrategyBacktestConfig(p.sid, p.market);
      if (cfg) {
        setMacroHandoff({ config: cfg, createdAt: Date.now() });
        router.push("/backtest");
      } else {
        // 예전엔 설정을 못 받으면 아무 일도 없었다(누른 단추가 조용히 죽음) — 이동하지 않고 이유를 말한다.
        setBridgeErr(`‘${p.name}’ 전략의 백테스트 설정을 받지 못해 넘기지 못했어요. 잠시 뒤 다시 눌러 주세요.`);
      }
    } finally {
      setBridging(false);
    }
  };

  // 현재 국면 → 불변 스냅샷 → Allocation Studio.
  // 백테스터 이식(setMacroHandoff/sessionStorage)과 달리 **URL 로 ID 를 넘긴다** —
  // 스펙상 브라우저 저장소는 스냅샷의 진실 소스가 될 수 없고, URL 은 새로고침·공유에 견딘다.
  const [aasBusy, setAasBusy] = useState(false);
  const [aasError, setAasError] = useState<string | null>(null);
  const onOpenInAAS = async () => {
    setAasBusy(true);
    setAasError(null);
    try {
      const res = await regimeSnapshotApi.createFromCurrent("kr");
      if (!res.recorded || !res.snapshot_id) {
        // 저장 실패를 성공으로 위장하지 않는다 — 이동하지 않고 사유를 보여 준다.
        setAasError(res.message || "스냅샷이 저장되지 않아 이동하지 않았어요.");
        return;
      }
      router.push(`/allocation?snapshot=${encodeURIComponent(res.snapshot_id)}`);
    } catch (e) {
      setAasError(e instanceof Error ? e.message : "스냅샷 생성에 실패했어요.");
    } finally {
      setAasBusy(false);
    }
  };

  return (
    <div className="tpage-fade">
      {loading && <LoadingState label="경제 흐름을 불러오는 중이에요" />}
      {bridging && <LoadingState label="전략을 백테스트 설정으로 옮기는 중이에요" />}
      {bridgeErr && <Notice tone="danger" title="백테스트로 넘기지 못했어요">{bridgeErr}</Notice>}
      {!loading && !regime && (
        <div className="mc-err tx-page tx-page--wide">
          <Notice tone="danger" title="경제 흐름을 불러오지 못했어요">
            국면 계산 서버에 닿지 못했거나 계산이 실패했어요. 잠시 뒤 다시 시도해 주세요.
            <div className="mc-act">
              <button type="button" className="tx-btn tx-btn--sub" onClick={() => { void regimeQ.refetch(); }}
                      disabled={regimeQ.isFetching}>
                {regimeQ.isFetching ? "다시 묻는 중이에요…" : "다시 시도"}
              </button>
            </div>
          </Notice>
        </div>
      )}
      {!loading && regime && (
        <MacroCockpit
          core={{ regime, dashboard: dashboardQ.data ?? null, valuation: valuationQ.data ?? null,
                  strategies: strategiesQ.data ?? null, recommend: recommendQ.data ?? null }}
          coreFail={coreFail} onTransplant={onTransplant}
          onOpenInAAS={onOpenInAAS} aasBusy={aasBusy} aasError={aasError} />
      )}
      {/* P4 지능 패널 — 칵핏 아래. `.mc-*` 는 한 글자도 건드리지 않는다(15개 스펙 계약). */}
      {!loading && <MacroIntelPanel />}
    </div>
  );
}
