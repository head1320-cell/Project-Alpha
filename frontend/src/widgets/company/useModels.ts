"use client";
// 여러 모형(BU6a+) — 모형 여덟 + 매크로 민감도를 종목·현재가마다 한 번씩 부른다(react-query 캐시 — 모형 한눈에·레일·카드가 같은 응답을 쓴다).
// `enabled` 는 핵심(가치 샌드박스)이 끝난 뒤 — 단일 워커 서버에 무거운 요청이 첫 화면과 겹치지 않게.
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { modelsApi, type DriverMc, type Eva, type MacroSensitivity, type Multiples, type ReverseDcf, type Scenarios,
  type ValuationDistribution, type ValueLayers } from "@/entities/company/modelsApi";

export interface CompanyModels {
  rdcf: UseQueryResult<ReverseDcf>;
  dist: UseQueryResult<ValuationDistribution>;
  driver: UseQueryResult<DriverMc>;
  layers: UseQueryResult<ValueLayers>;
  eva: UseQueryResult<Eva>;
  multiples: UseQueryResult<Multiples>;
  scenarios: UseQueryResult<Scenarios>;
  macro: UseQueryResult<MacroSensitivity>;
}

export function useCompanyModels(code: string, price: number, marketCapEok: number | null, enabled: boolean): CompanyModels {
  const on = enabled && price > 0;
  const k = (m: string) => ["company", "model", m, code, price] as const;
  // 실패는 자동으로 거듭 묻지 않는다 — 카드의 [다시 시도] 가 묻는다(실패를 조용히 덮지 않게).
  const opt = { enabled: on, retry: false, staleTime: 5 * 60_000 } as const;
  return {
    rdcf: useQuery({ queryKey: k("rdcf"), queryFn: () => modelsApi.reverseDcf(code, price, marketCapEok), ...opt }),
    dist: useQuery({ queryKey: k("dist"), queryFn: () => modelsApi.distribution(code, price), ...opt }),
    driver: useQuery({ queryKey: k("driver"), queryFn: () => modelsApi.driverMc(code, price), ...opt }),
    layers: useQuery({ queryKey: k("layers"), queryFn: () => modelsApi.valueLayers(code, price), ...opt }),
    eva: useQuery({ queryKey: k("eva"), queryFn: () => modelsApi.eva(code, price), ...opt }),
    multiples: useQuery({ queryKey: k("multiples"), queryFn: () => modelsApi.multiples(code, price), ...opt }),
    scenarios: useQuery({ queryKey: k("scenarios"), queryFn: () => modelsApi.scenarios(code, price), ...opt }),
    macro: useQuery({ queryKey: k("macro"), queryFn: () => modelsApi.macroSensitivity(code, price), ...opt }),
  };
}
