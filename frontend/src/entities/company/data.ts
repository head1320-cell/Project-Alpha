// ═══════════════════════════════════════════════════════════════════════════════
// companyData — 실API 조립 → CompanyData (Company Analysis 페이지 데이터 로더)
//   코어: 병렬 로드(byTicker + evaluate×3 + financial + prices + 표본 + 피어 + fields)
//   lazy: network / signal / risk / narrative / macro
// ═══════════════════════════════════════════════════════════════════════════════
import { companyApi } from "./api";
import { type FinancialHistory, type PriceBar } from "./model";
import type { FieldsCatalog, ScreenerItem, ValuationDetail } from "@/shared/model/domain";
// 타입만 참조 — 런타임 결합 없음(regimeToMacroInfo 의 입력 타입).
// eslint-disable-next-line import/no-restricted-paths
import type { RegimeState } from "@/entities/macro/api";
import type {
  CompanyData, FactorGroup, FactorVal, ModelResult, Scenario, YearFin, QuarterFin, PricePt, Peer,
  SignalInfo, RiskInfo, NetworkInfo, NarrativeInfo, MacroInfo,
} from "./insightsModel";
import { verdictTone } from "./insightsModel";

const fin = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

const MODEL_LABEL: Record<string, string> = { RIM: "잔여이익모형", DCF: "현금흐름할인", DDM: "배당할인모형" };
const MODEL_WEIGHT: Record<string, number> = { RIM: 0.4, DCF: 0.4, DDM: 0.2 };
const FUND_CATS = new Set(["quality", "valuation", "growth", "safety", "composite", "profitability", "dividend", "stability"]);
const PRICE_CATS = new Set(["momentum", "volatility", "technical", "volume", "supply"]);

// valuation assumptions/components 키 → 라벨
const KV_LABEL: Record<string, string> = {
  ke_pct: "Kₑ", wacc_pct: "WACC", kd_pct: "Kd", current_roe_pct: "현재 ROE", terminal_roe_pct: "잔존 ROE",
  terminal_growth_pct: "영구성장", initial_fcf_growth_pct: "초기 FCF성장", initial_div_growth_pct: "초기 배당성장",
  projection_years: "예측기간", total_years: "총 기간", high_growth_years: "고성장 기간", payout_ratio_pct: "배당성향",
  current_bps: "현재 BPS", pv_residual: "PV 잔여이익", pv_terminal: "PV 잔존가치", intrinsic: "내재가치",
  base_fcf_억: "기준 FCF", pv_fcf_억: "PV FCF", pv_terminal_억: "PV 잔존", enterprise_value_억: "EV",
  net_debt_억: "순부채", equity_value_억: "지분가치", per_share: "주당가치",
  current_dps: "현재 DPS", pv_dividends: "PV 배당", pv_terminal_price: "PV 잔존주가",
};
function fmtKV(key: string, v: number): { k: string; v: string } {
  const label = KV_LABEL[key] ?? key;
  let s: string;
  if (key.endsWith("_pct")) s = `${v}%`;
  else if (key.endsWith("_억")) s = `${Math.round(v).toLocaleString()}억`;
  else if (key.endsWith("_years")) s = `${v}년`;
  else s = `${Math.round(v).toLocaleString()}원`;
  return { k: label, v: s };
}
function mapModel(m: ValuationDetail["models"][number]): ModelResult {
  return {
    key: m.model, label: MODEL_LABEL[m.model] ?? m.model, value: m.intrinsic_value, weight: MODEL_WEIGHT[m.model] ?? 0,
    assumptions: Object.entries(m.assumptions ?? {}).map(([k, v]) => fmtKV(k, v as number)),
    components: Object.entries(m.components ?? {}).map(([k, v]) => fmtKV(k, v as number)),
  };
}

// 유니버스 표본 기반 퍼센타일 (higher_better 반영)
function makePercentile(sample: ScreenerItem[]) {
  return (fieldId: string, value: number, higherBetter: boolean): number => {
    const vals: number[] = [];
    for (const it of sample) { const x = it[fieldId]; if (typeof x === "number" && Number.isFinite(x)) vals.push(x); }
    if (vals.length < 5) return 50;
    const below = vals.filter((x) => x <= value).length;
    let p = Math.round((below / vals.length) * 100);
    if (!higherBetter) p = 100 - p;
    return Math.max(1, Math.min(99, p));
  };
}
const UNIT = (u: string) => (u === "×" || u === "x" || u === "배" ? "배" : u || "");

function buildFactorGroups(item: ScreenerItem, catalog: FieldsCatalog, sample: ScreenerItem[], cats: Set<string>): FactorGroup[] {
  const pctOf = makePercentile(sample);
  const groups: FactorGroup[] = [];
  for (const cat of catalog.categories) {
    if (!cats.has(cat.id)) continue;
    const factors: FactorVal[] = [];
    for (const f of cat.fields) {
      const raw = item[f.id];
      if (typeof raw !== "number" || !Number.isFinite(raw)) continue;
      factors.push({ id: f.id, label: f.label, value: Math.round(raw * 100) / 100, unit: UNIT(f.unit), higherBetter: f.higher_better, pct: pctOf(f.id, raw, f.higher_better) });
    }
    if (factors.length) groups.push({ id: cat.id, label: cat.label, factors });
  }
  return groups;
}

// 일봉 → 차트용 다운샘플. ★시세가 없으면 빈 배열 — 합성 경로를 지어 그리지 않는다(BU6, CLAUDE.md §6 mock 게이트)★
function mapPrices(bars: { date: string; close: number }[], current: number): PricePt[] {
  if (!bars.length) return [];
  const lastClose = bars[bars.length - 1].close;
  const scale = current > 0 && lastClose > 0 ? current / lastClose : 1; // 헤더 현재가에 정렬(실 KIS면 ≈1)
  const step = Math.max(1, Math.floor(bars.length / 60));
  const out: PricePt[] = [];
  for (let i = 0; i < bars.length; i += step) {
    const d = bars[i].date.slice(2).replace(/-/g, ".").slice(0, 5); // YY.MM
    out.push({ t: d, p: Math.round(bars[i].close * scale) });
  }
  out[out.length - 1] = { t: out[out.length - 1].t, p: Math.round(current) };
  return out;
}
function mapYears(hist: FinancialHistory | null): YearFin[] {
  if (!hist?.financials?.length) return [];
  const rows = hist.financials.map((f) => ({
    year: f.year, revenue: f.revenue_억 ?? 0, op: f.operating_profit_억 ?? 0, ni: f.net_income_억 ?? 0,
    equity: f.total_equity_억 ?? 0, fcf: f.fcf_억 ?? 0, roe: f.roe_pct ?? 0, debt: f.debt_ratio_pct ?? 0,
    eps: f.eps ?? 0, bps: f.bps ?? 0, dps: f.dps ?? 0,
  }));
  // 시계열 차트/표는 과거→최근(오름차순)으로 — API는 내림차순으로 반환
  rows.sort((a, b) => Number(a.year) - Number(b.year));
  return rows;
}

function mapQuarters(hist: FinancialHistory | null): QuarterFin[] {
  if (!hist?.financials?.length) return [];
  const rows = hist.financials.map((f) => {
    const rev = f.revenue_억 ?? 0;
    const op = f.operating_profit_억 ?? 0;
    return {
      q: f.year, revenue: rev, op, ni: f.net_income_억 ?? 0,
      equity: f.total_equity_억 ?? 0, roe: f.roe_pct ?? 0, debt: f.debt_ratio_pct ?? 0,
      eps: f.eps ?? 0, bps: f.bps ?? 0, dps: f.dps ?? 0,
      opMargin: rev ? Math.round((op / rev) * 1000) / 10 : 0,
    };
  });
  // "2025Q3" 형식 → 과거→최근 오름차순
  rows.sort((a, b) => a.q.localeCompare(b.q));
  return rows;
}

function mapPeers(items: ScreenerItem[], selfCode: string): Peer[] {
  const peers = items.map((it) => ({
    code: it.stock_code, name: it.corp_name, price: it.current_price, per: Math.round((fin(it.per) ?? 0) * 100) / 100,
    pbr: Math.round((fin(it.pbr) ?? 0) * 100) / 100, roe: Math.round((fin(it.roe_pct) ?? 0) * 10) / 10,
    gap: Math.round((it.gap_pct ?? 0) * 10) / 10, mktcap: fin(it.market_cap_억) ?? 0, self: it.stock_code === selfCode,
  }));
  return peers.sort((a, b) => a.gap - b.gap).slice(0, 12);
}

export async function loadCompanyCore(code: string): Promise<CompanyData> {
  // wave 1
  const [item, sample, catalog] = await Promise.all([
    companyApi.byTicker(code),
    // 퍼센타일 분포: DB 적재 표본(factor_snapshot) 우선 → 비면(미적재) 라이브 kospi200 폴백.
    (async () => {
      const db = await companyApi.factorSample(600).catch(() => [] as ScreenerItem[]);
      if (db.length >= 20) return db;
      return companyApi.universeSample("kospi200").catch(() => [] as ScreenerItem[]);
    })(),
    companyApi.fieldsCatalog().catch(() => ({ categories: [], operators: [], rank_modes: [] } as FieldsCatalog)),
  ]);
  if (!item) throw new Error("NOT_FOUND");
  const price = item.current_price;
  const mcapInput = fin(item.market_cap_억) ?? undefined;  // 발행주식수 도출용(BPS·EPS) → valuation 활성
  // wave 2
  // ★실패를 "없음"과 가른다(BU6)★ 실패는 settle 로 받아 `failed` 에 적는다 — 화면이 "재무 데이터 부족" 대신 실패 + 다시 시도를 말한다.
  const settle = <T,>(pr: Promise<T>): Promise<{ ok: true; v: T } | { ok: false }> =>
    pr.then((v) => ({ ok: true as const, v }), () => ({ ok: false as const }));
  const [baseR, bull, bear, histR, quarterHist, barsR, peerItems] = await Promise.all([
    settle(companyApi.evaluate(code, price, { market_cap: mcapInput })),
    companyApi.evaluate(code, price, { market_cap: mcapInput, terminal_growth: 0.03, market_premium: 0.05 }).catch(() => null),
    companyApi.evaluate(code, price, { market_cap: mcapInput, terminal_growth: 0.01, market_premium: 0.07 }).catch(() => null),
    settle(companyApi.financial(code, 8, "annual", price, mcapInput)),
    companyApi.financial(code, 8, "quarter", price, mcapInput).catch(() => null),
    companyApi.prices(code, 400).catch(() => null),
    item.sector ? companyApi.peersBySector(item.sector).catch(() => [] as ScreenerItem[]) : Promise.resolve([] as ScreenerItem[]),
  ]);

  const failed: CompanyData["failed"] = [];
  if (!baseR.ok) failed.push("valuation");
  if (!histR.ok) failed.push("financials");
  if (barsR === null) failed.push("prices");
  const base = baseR.ok ? baseR.v : null;
  const hist = histR.ok ? histR.v : null;
  const bars = barsR ?? [];
  const fs = (base?.financial_summary ?? {}) as Record<string, number | null>;
  const pick0 = (k: string, alt?: number | null): number => fin(fs[k]) ?? fin(alt) ?? 0;
  // ★0 과 미상을 섞지 않는다(BU6)★ 화면에 숫자로 나가는 요약은 null(몰라요)을 그대로 나른다.
  const pickN = (k: string, alt?: number | null): number | null => fin(alt) ?? fin(fs[k]);
  // 답 문장의 근거 — evaluate(기본 가정)의 내재가치·괴리·판정을 우선, 없으면 스크리너 항목(같은 엔진 `compute_gap_pct`).
  const intrinsic = base?.intrinsic_value ?? item.intrinsic_value;
  const verdict = base?.verdict ?? item.verdict;
  const gapPct = base ? base.gap_pct : item.gap_pct;
  const tone = verdictTone(verdict);

  const models: ModelResult[] = (base?.models ?? []).filter((m) => m.available && m.intrinsic_value > 0).map(mapModel);

  const scen = (key: Scenario["key"], label: string, d: ValuationDetail | null, note: string): Scenario | null =>
    d && d.intrinsic_value > 0 ? { key, label, value: Math.round(d.intrinsic_value), gap: Math.round((d.intrinsic_value / price - 1) * 1000) / 10, note } : null;
  const scenarios = [
    scen("bull", "낙관", bull, "영구성장 3%, 시장프리미엄 5%"),
    scen("base", "기준", base, "영구성장 2%, 시장프리미엄 6%"),
    scen("bear", "보수", bear, "영구성장 1%, 시장프리미엄 7%"),
  ].filter(Boolean) as Scenario[];

  const fundamentals = buildFactorGroups(item, catalog, sample, FUND_CATS);
  const priceFactors = buildFactorGroups(item, catalog, sample, PRICE_CATS);
  const allFactors = [...fundamentals, ...priceFactors].flatMap((g) => g.factors);
  const ranked = [...allFactors].sort((a, b) => b.pct - a.pct);
  const strengths = ranked.slice(0, 5);
  const weaknesses = ranked.slice(-4).reverse();

  const peers = mapPeers([item, ...peerItems.filter((p) => p.stock_code !== code)], code);

  const years = mapYears(hist);
  const quarters = mapQuarters(quarterHist);
  const price1y = mapPrices(bars, price);

  // 전일 대비 — 시세 원본의 마지막 두 종가(배율 조정 전). 둘 미만이면 모른다(null).
  const closes = bars.filter((b) => b.close > 0);
  const dayChange = closes.length >= 2
    ? { pct: Math.round((closes[closes.length - 1].close / closes[closes.length - 2].close - 1) * 10000) / 100, date: closes[closes.length - 1].date }
    : null;
  const divYield = pickN("dividend_yield_pct", item.dividend_yield_pct);
  // 시총: 실값 우선, 없으면 가격×(자기자본/BPS)=가격×발행주식수 로 도출 (mock에서 market_cap_억=null 대응)
  const eqV = pick0("total_equity_억"), bpsV = pick0("bps");
  const mktcap = fin(item.market_cap_억) ?? (eqV > 0 && bpsV > 0 ? Math.round((price * eqV) / bpsV) : null);

  return {
    code: item.stock_code, name: item.corp_name, sector: item.sector ?? "—",
    price, mktcap, dayChange, isMock: !!base?.is_mock,
    verdict, tone, intrinsic, gapPct,
    models,
    summary: {
      // 단일 소스: item 팩터(ffl — 실측 시총 기반) 우선, evaluate 요약은 폴백 —
      // 헤더 PER 36.99 vs 팩터 15.05 불일치(CIO 실사) 제거
      per: pickN("per", item.per), pbr: pickN("pbr", item.pbr),
      roe: pickN("roe_pct", item.roe_pct), roa: pickN("roa_pct", item.roa_pct),
      debt: pickN("debt_ratio_pct", item.debt_ratio_pct), divYield, payout: pickN("payout_ratio_pct"),
      eps: pickN("eps"), bps: pickN("bps"), dps: pickN("dps"),
      revenue: pickN("revenue_억"), op: pickN("operating_profit_억"), ni: pickN("net_income_억"), fcf: pickN("fcf_억", item.fcf_억), equity: pickN("total_equity_억"),
    },
    years, quarters, price1y, failed,
    fundamentals, priceFactors, strengths, weaknesses,
    peers, scenarios,
    score: { composite: Math.round(item.composite_score ?? 0), gap: Math.round(item.gap_score ?? 0), roe: Math.round(item.roe_score ?? 0), stability: Math.round(item.stability_score ?? 0) },
    signal: undefined, risk: undefined, network: undefined, narrative: undefined, macro: undefined,
  };
}

// ── lazy 로더 ──
export async function loadSignal(code: string, name: string): Promise<SignalInfo | null> {
  const s = await companyApi.signal(code, name).catch(() => null);
  if (!s) return null;
  return { action: s.action, strength: s.strength, reason: s.reason, strategy: s.strategy };
}

// 순수 변환(fetch 아님) — CompanyCockpit이 매크로 탭과 동일한 react-query 캐시 키
// (["macro","regime"])로 macroApi.regime()을 직접 호출하고, 그 원시 결과를 이 함수로
// MacroInfo로 변환한다(두 탭 간 중복 호출을 캐시 레벨에서 공유하기 위해 fetch/변환을 분리).
export function regimeToMacroInfo(m: RegimeState | null | undefined): MacroInfo | null {
  if (!m) return null;
  const mm = m as unknown as Record<string, unknown>;
  return { regime: String(mm.regime ?? mm.description ?? "—"), riskFree: fin(mm.dynamic_risk_free_rate), recommendedMode: mm.recommended_mode as string | undefined };
}

export async function loadNetwork(code: string): Promise<NetworkInfo> {
  const g = await companyApi.graphRelations(code).catch(() => ({ supplier: [], customer: [], competitor: [] }));
  const mk = (rel: string, label: string, arr: { code: string; name: string }[]) =>
    ({ relation: rel, label, nodes: (arr ?? []).map((a) => ({ code: a.code, name: a.name, relation: rel })) });
  const groups = [
    mk("supplier", "공급사·협력사", g.supplier),
    mk("customer", "고객사", g.customer),
    mk("competitor", "경쟁사", g.competitor),
  ].filter((grp) => grp.nodes.length);
  return { groups, note: groups.length ? undefined : "등록된 밸류체인 관계가 없어요." };
}

export async function loadRisk(code: string): Promise<RiskInfo> {
  // 1차: 일별 시세로 직접 계산 (VaR·ES·변동성·MDD·Sharpe) — 시세만 있으면 동작, 엔진 제약 회피
  const bars = await companyApi.prices(code, 400).catch(() => [] as PriceBar[]);
  const closes = bars.map((b) => b.close).filter((c) => c > 0);
  if (closes.length >= 30) {
    const rets: number[] = [];
    for (let i = 1; i < closes.length; i++) rets.push(closes[i] / closes[i - 1] - 1);
    const sorted = [...rets].sort((a, b) => a - b);
    const idx1 = Math.max(0, Math.floor(0.01 * sorted.length));
    const var99 = -sorted[idx1];                                   // 1일 99% VaR (손실, 양수)
    const tail = sorted.slice(0, idx1 + 1);
    const es = tail.length ? -(tail.reduce((s, r) => s + r, 0) / tail.length) : var99;
    const mean = rets.reduce((s, r) => s + r, 0) / rets.length;
    const sd = Math.sqrt(rets.reduce((s, r) => s + (r - mean) ** 2, 0) / Math.max(1, rets.length - 1));
    let peak = closes[0], mdd = 0;
    for (const c of closes) { if (c > peak) peak = c; const dd = (c - peak) / peak; if (dd < mdd) mdd = dd; }
    return {
      varPct: Math.round(var99 * 1000) / 10,                       // %
      esAmount: Math.round(es * 1e8),                              // 1억 포트 기준 손실(원)
      vol: Math.round(sd * Math.sqrt(252) * 1000) / 10,            // 연율 변동성 %
      sharpe: sd > 0 ? Math.round((mean / sd) * Math.sqrt(252) * 100) / 100 : null,
      mdd: Math.round(mdd * 1000) / 10,                            // 최대낙폭 % (음수)
    };
  }
  // 2차: 백엔드 VaR 엔진 (DB 일봉 있으면)
  const v = await companyApi.riskVar(code).catch(() => null);
  if (v) {
    const g = v as Record<string, unknown>;
    return { varPct: fin(g.var_pct), esAmount: fin(g.es_amount), vol: fin(g.volatility) ?? fin(g.annual_vol), sharpe: null, mdd: null };
  }
  return { varPct: null, esAmount: null, vol: null, sharpe: null, mdd: null, note: "리스크 지표를 계산할 수 없어요 — 해당 종목 일별 시세가 아직 적재되지 않았어요(시세 수집 후 활성)." };
}

export async function loadNarrative(item: object, valuationDetail: object): Promise<NarrativeInfo> {
  try {
    const r = await companyApi.narrative(item, valuationDetail);
    return { content: r.content, tokens: r.total_tokens, costKrw: r.cost_krw, cached: r.cached, error: r.error };
  } catch (e) {
    return { content: "", tokens: 0, costKrw: 0, cached: false, error: e instanceof Error ? e.message : "생성 실패" };
  }
}
