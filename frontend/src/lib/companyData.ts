// ═══════════════════════════════════════════════════════════════════════════════
// companyData — 실API 조립 → CompanyData (Company Analysis 페이지 데이터 로더)
//   코어: 병렬 로드(byTicker + evaluate×3 + financial + prices + 표본 + 피어 + fields)
//   lazy: network / signal / risk / narrative / macro
// ═══════════════════════════════════════════════════════════════════════════════
import {
  companyApi, analysisApi, screenerApiAdvanced,
  type ScreenerItem, type ValuationDetail, type FieldsCatalog, type FinancialHistory,
} from "@/lib/screenerApi";
import type {
  CompanyData, FactorGroup, FactorVal, ModelResult, Scenario, YearFin, PricePt, Peer,
  SignalInfo, RiskInfo, NetworkInfo, NarrativeInfo, MacroInfo,
} from "@/components/insights/types";
import { verdictTone } from "@/components/insights/types";

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
  else s = `₩${Math.round(v).toLocaleString()}`;
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

// 일봉 → 차트용 다운샘플 / 합성 폴백
function mapPrices(bars: { date: string; close: number }[]): PricePt[] {
  if (!bars.length) return [];
  const step = Math.max(1, Math.floor(bars.length / 60));
  const out: PricePt[] = [];
  for (let i = 0; i < bars.length; i += step) {
    const d = bars[i].date.slice(2).replace(/-/g, ".").slice(0, 5); // YY.MM
    out.push({ t: d, p: Math.round(bars[i].close) });
  }
  if (out.length && bars.length) out[out.length - 1] = { t: out[out.length - 1].t, p: Math.round(bars[bars.length - 1].close) };
  return out;
}
function synthPrices(code: string, end: number): PricePt[] {
  let s = Number(code) || 7, p = end * 0.8;
  const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  const pts: PricePt[] = []; const n = 60, drift = (end - p) / n;
  for (let i = 0; i < n; i++) { p += drift + (rnd() - 0.5) * end * 0.045; const mo = (i % 12) + 1, yr = 25 + Math.floor(i / 12); pts.push({ t: `${yr}.${String(mo).padStart(2, "0")}`, p: Math.max(1, Math.round(p)) }); }
  pts[pts.length - 1].p = end;
  return pts;
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
    companyApi.universeSample("kospi200").catch(() => [] as ScreenerItem[]),
    screenerApiAdvanced.fields().catch(() => ({ categories: [], operators: [], rank_modes: [] } as FieldsCatalog)),
  ]);
  if (!item) throw new Error("NOT_FOUND");
  const price = item.current_price;
  // wave 2
  const [base, bull, bear, hist, bars, peerItems] = await Promise.all([
    companyApi.evaluate(code, price).catch(() => null),
    companyApi.evaluate(code, price, { terminal_growth: 0.03, market_premium: 0.05 }).catch(() => null),
    companyApi.evaluate(code, price, { terminal_growth: 0.01, market_premium: 0.07 }).catch(() => null),
    companyApi.financial(code, 8).catch(() => null),
    companyApi.prices(code, 400).catch(() => []),
    item.sector ? companyApi.peersBySector(item.sector).catch(() => [] as ScreenerItem[]) : Promise.resolve([] as ScreenerItem[]),
  ]);

  const fs = (base?.financial_summary ?? {}) as Record<string, number | null>;
  const pick = (k: string, alt?: number | null): number => fin(fs[k]) ?? fin(alt) ?? 0;
  const intrinsic = base?.intrinsic_value ?? item.intrinsic_value;
  const tone = verdictTone(item.verdict);

  const models: ModelResult[] = (base?.models ?? []).filter((m) => m.available && m.intrinsic_value > 0).map(mapModel);

  const scen = (key: Scenario["key"], label: string, d: ValuationDetail | null, note: string): Scenario | null =>
    d && d.intrinsic_value > 0 ? { key, label, value: Math.round(d.intrinsic_value), gap: Math.round((d.intrinsic_value / price - 1) * 1000) / 10, note } : null;
  const scenarios = [
    scen("bull", "Bull", bull, "영구성장 3% · 시장프리미엄 5% (낙관)"),
    scen("base", "Base", base, "영구성장 2% · 시장프리미엄 6% (기준)"),
    scen("bear", "Bear", bear, "영구성장 1% · 시장프리미엄 7% (보수)"),
  ].filter(Boolean) as Scenario[];

  const fundamentals = buildFactorGroups(item, catalog, sample, FUND_CATS);
  const priceFactors = buildFactorGroups(item, catalog, sample, PRICE_CATS);
  const allFactors = [...fundamentals, ...priceFactors].flatMap((g) => g.factors);
  const ranked = [...allFactors].sort((a, b) => b.pct - a.pct);
  const strengths = ranked.slice(0, 5);
  const weaknesses = ranked.slice(-4).reverse();

  const peers = mapPeers([item, ...peerItems.filter((p) => p.stock_code !== code)], code);

  const years = mapYears(hist);
  const price1y = bars.length ? mapPrices(bars) : synthPrices(code, price);

  const upside = Math.round((intrinsic / price - 1) * 1000) / 10;
  const divYield = pick("dividend_yield_pct", item.dividend_yield_pct);

  return {
    code: item.stock_code, name: item.corp_name, sector: item.sector ?? "—",
    price, changePct: 0, mktcap: fin(item.market_cap_억) ?? 0,
    verdict: item.verdict, tone, intrinsic, gapPct: item.gap_pct,
    models,
    summary: {
      per: pick("per", item.per), pbr: pick("pbr", item.pbr), roe: pick("roe_pct", item.roe_pct), roa: pick("roa_pct", item.roa_pct),
      debt: pick("debt_ratio_pct", item.debt_ratio_pct), divYield, payout: pick("payout_ratio_pct"),
      eps: pick("eps"), bps: pick("bps"), dps: pick("dps"),
      revenue: pick("revenue_억"), op: pick("operating_profit_억"), ni: pick("net_income_억"), fcf: pick("fcf_억", item.fcf_억), equity: pick("total_equity_억"),
    },
    years, quarters: [], price1y, priceIsSynthetic: !bars.length,
    fundamentals, priceFactors, strengths, weaknesses,
    shareholder: { divYield, payout: pick("payout_ratio_pct"), dps: pick("dps"), shYield: fin(item["shareholder_yield"]) ?? divYield },
    consensus: { fwdPer: pick("per", item.per), fwdEpsChg: 0, revision: 0, targetPrice: Math.round(intrinsic), targetUpside: upside },
    consensusReal: false,
    events: { earningsDays: 0, exDivDays: 0 }, eventsReal: false,
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

export async function loadMacro(): Promise<MacroInfo | null> {
  const m = await analysisApi.macroRegime().catch(() => null);
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
  return { groups, note: groups.length ? undefined : "등록된 밸류체인 관계가 없습니다." };
}

export async function loadRisk(code: string): Promise<RiskInfo> {
  const v = await companyApi.riskVar(code).catch(() => null);
  if (!v) return { varPct: null, esAmount: null, vol: null, sharpe: null, mdd: null, note: "리스크 지표는 일별 시세(DB) 적재가 필요합니다." };
  const g = v as Record<string, unknown>;
  return {
    varPct: fin(g.var_pct), esAmount: fin(g.es_amount), vol: fin(g.volatility) ?? fin(g.annual_vol),
    sharpe: null, mdd: null,
  };
}

export async function loadNarrative(item: object, valuationDetail: object): Promise<NarrativeInfo> {
  try {
    const r = await companyApi.narrative(item, valuationDetail);
    return { content: r.content, tokens: r.total_tokens, costKrw: r.cost_krw, cached: r.cached, error: r.error };
  } catch (e) {
    return { content: "", tokens: 0, costKrw: 0, cached: false, error: e instanceof Error ? e.message : "생성 실패" };
  }
}
