// 기업분석 심화 API (샌드박스·재무·리스크).
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE, postJson } from "@/shared/api/apiBase";
import type { FieldsCatalog, GraphRelations, ScreenerItem, ValuationDetail } from "@/shared/model/domain";
import type {
  EvaluateOverrides,
  FinancialDeep,
  FinancialHistory,
  NarrativeResp,
  PriceBar,
  RiskDeep,
  SignalResp,
  SymbolItem,
  ValuationSandbox,
} from "./model";

export const companyApi = {
  /** 필드 카탈로그(퍼센타일 라벨용). screener가 소유한 엔드포인트지만 entity→entity 런타임
   *  의존을 만들지 않으려고 여기서 직접 읽는다 — 같은 경로·같은 응답. */
  fieldsCatalog: async (): Promise<FieldsCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/fields`);
    if (!r.ok) throw new Error(`Fields fetch failed: ${r.status}`);
    return r.json();
  },

  // 단일 종목 — 116팩터 + 점수 + valuation 요약 (custom_tickers로 임의 종목 대응)
  byTicker: async (code: string): Promise<ScreenerItem | null> => {
    const r = await postJson(`/api/v1/screener/run-advanced`, {
      universe: "all_listed", custom_tickers: [code],
      filter_ast: { logic: "AND", conditions: [], groups: [] }, limit: 1, liquidity_floor: "off",
    });
    if (!r.ok) throw new Error(`company byTicker failed: ${r.status}`);
    const d = await r.json();
    return d.items?.[0] ?? null;
  },
  // 퍼센타일 계산용 유니버스 표본
  universeSample: async (universe = "kospi200"): Promise<ScreenerItem[]> => {
    const r = await postJson(`/api/v1/screener/run-advanced`, {
      universe, filter_ast: { logic: "AND", conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }], groups: [] },
      limit: 300, liquidity_floor: "relaxed",
    });
    if (!r.ok) return [];
    return (await r.json()).items ?? [];
  },
  // 퍼센타일 분포 — factor_snapshot(DB)에서 즉시 (라이브 130종목 재계산 회피). 비면 [].
  factorSample: async (limit = 600): Promise<ScreenerItem[]> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/factor-sample?limit=${limit}`);
    if (!r.ok) return [];
    return (await r.json()).items ?? [];
  },
  // 섹터 피어
  peersBySector: async (sector: string): Promise<ScreenerItem[]> => {
    const r = await postJson(`/api/v1/screener/run-advanced`, {
      universe: `sector:${sector}`, filter_ast: { logic: "AND", conditions: [], groups: [] }, limit: 24, liquidity_floor: "off",
    });
    if (!r.ok) return [];
    return (await r.json()).items ?? [];
  },
  // 기업분석 심화: 샌드박스+민감도+풋볼필드+Comps (1콜)
  valuationSandbox: async (code: string, price: number,
    o: { rf?: number; beta?: number; erp?: number; g?: number; years?: number } = {},
  ): Promise<ValuationSandbox> => {
    const qs = new URLSearchParams({ price: String(price) });
    for (const [k, v] of Object.entries(o)) if (v != null) qs.set(k, String(v));
    const r = await fetch(`${API_BASE}/api/v1/company/${code}/valuation-sandbox?${qs.toString()}`);
    if (!r.ok) throw new Error(`valuation-sandbox failed: ${r.status}`);
    return r.json();
  },
  // 기업분석 심화: QoE·NWC·워터폴·듀폰 (1콜)
  financialDeep: async (code: string): Promise<FinancialDeep> => {
    const r = await fetch(`${API_BASE}/api/v1/company/${code}/financial-deep`);
    if (!r.ok) throw new Error(`financial-deep failed: ${r.status}`);
    return r.json();
  },
  // 기업분석 심화: Altman 분해·Beneish 8지수·커버리지·금리 스트레스 (1콜)
  riskDeep: async (code: string, price: number): Promise<RiskDeep> => {
    const r = await fetch(`${API_BASE}/api/v1/company/${code}/risk-deep?price=${price}`);
    if (!r.ok) throw new Error(`risk-deep failed: ${r.status}`);
    return r.json();
  },
  // 3모형 상세 + 시나리오용 가정 오버라이드
  evaluate: async (code: string, price: number, o: EvaluateOverrides = {}): Promise<ValuationDetail> => {
    const r = await postJson(`/api/v1/valuation/evaluate`, {
      stock_code: code, current_price: price, market_cap: o.market_cap ?? null,
      beta: o.beta ?? 1.0, risk_free_rate: o.risk_free_rate ?? 0.035, market_premium: o.market_premium ?? 0.06,
      terminal_growth: o.terminal_growth ?? 0.02, projection_years: o.projection_years ?? 10,
      weight_rim: 0.4, weight_dcf: 0.4, weight_ddm: 0.2,
    });
    if (!r.ok) throw new Error(`evaluate failed: ${r.status}`);
    return r.json();
  },
  // 재무 시계열 (period=annual: N년 / quarter: 분기). price·marketCap 주면 EPS/BPS 도출.
  financial: async (code: string, years = 8, period: "annual" | "quarter" = "annual", price?: number, marketCap?: number): Promise<FinancialHistory | null> => {
    const qs = new URLSearchParams({ years: String(years), period });
    if (price && price > 0) qs.set("price", String(price));
    if (marketCap && marketCap > 0) qs.set("market_cap", String(marketCap));
    const r = await fetch(`${API_BASE}/api/v1/valuation/financial/${code}?${qs.toString()}`);
    if (r.status === 404) return null;
    if (!r.ok) return null;
    return r.json();
  },
  // 일봉 (DB 캐시 — 비어있으면 [] → 호출측 합성 폴백)
  prices: async (code: string, days = 400): Promise<PriceBar[]> => {
    const r = await fetch(`${API_BASE}/api/v1/prices/${code}?days=${days}`);
    if (!r.ok) return [];
    return (await r.json()).prices ?? [];
  },
  // 밸류체인 관계 (M4)
  graphRelations: async (code: string): Promise<GraphRelations> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/graph-relations/${code}`);
    if (!r.ok) return { supplier: [], customer: [], competitor: [] };
    return r.json();
  },
  // 기술 시그널
  signal: async (code: string, name: string, strategy = "골든크로스"): Promise<SignalResp | null> => {
    const r = await postJson(`/api/v1/strategies/signal`, { stock_code: code, stock_name: name, strategy, params: {} });
    if (!r.ok) return null;
    return r.json();
  },
  // AI 내러티브 (Claude)
  narrative: async (stockItem: object, valuationDetail: object): Promise<NarrativeResp> => {
    const r = await postJson(`/api/v1/narrative/stock`, { stock_item: stockItem, valuation_detail: valuationDetail, max_tokens: 1600 });
    if (!r.ok) throw new Error(`narrative failed: ${r.status}`);
    return r.json();
  },
  // 리스크 — VaR (DB 일봉 필요; 없으면 에러 → 호출측 graceful)
  riskVar: async (code: string): Promise<Record<string, unknown> | null> => {
    const r = await postJson(`/calculate-var`, { ticker: code, portfolio_value: 1e8, confidence_level: 0.99, holding_period: 1, use_ewma: true });
    if (!r.ok) return null;
    return r.json();
  },
  symbolsSearch: async (q: string): Promise<SymbolItem[]> => {
    const r = await fetch(`${API_BASE}/api/v1/symbols/search?q=${encodeURIComponent(q)}&limit=12`);
    if (!r.ok) return [];
    return (await r.json()).items ?? [];
  },
  // 종목명/코드 자동완성 (전체 상장사) — "삼" → 삼성전자·삼성SDI…
  stockSearch: async (q: string, limit = 12): Promise<{ code: string; name: string }[]> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/stock-search?q=${encodeURIComponent(q)}&limit=${limit}`);
    if (!r.ok) return [];
    return (await r.json()).items ?? [];
  },
};
