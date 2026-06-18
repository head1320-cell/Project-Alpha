// ═══════════════════════════════════════════════════════════════════════════════
// insights/types — Company Analysis 프로덕션 데이터 모델 + 포맷 헬퍼
//   CompanyCockpit + companyData(lib) 공용. 실API 조립 결과가 이 형태.
// ═══════════════════════════════════════════════════════════════════════════════

export type Tone = "bull" | "bear" | "caution" | "neutral";

export interface FactorVal { id: string; label: string; value: number; unit: string; pct: number; higherBetter: boolean }
export interface FactorGroup { id: string; label: string; factors: FactorVal[] }
export interface YearFin { year: string; revenue: number; op: number; ni: number; equity: number; fcf: number; roe: number; debt: number; eps: number; bps: number; dps: number }
export interface QuarterFin { q: string; revenue: number; op: number; ni: number; opMargin: number }
export interface ModelResult { key: "RIM" | "DCF" | "DDM"; label: string; value: number; weight: number; assumptions: { k: string; v: string }[]; components: { k: string; v: string }[] }
export interface Peer { code: string; name: string; price: number; per: number; pbr: number; roe: number; gap: number; mktcap: number; self?: boolean }
export interface Scenario { key: "bull" | "base" | "bear"; label: string; value: number; gap: number; note: string }
export interface PricePt { t: string; p: number }

// 지연 로드(lazy) — 탭 진입 시 채워짐
export interface SignalInfo { action: string; strength: number; reason: string; strategy: string }
export interface RiskInfo { varPct: number | null; esAmount: number | null; vol: number | null; sharpe: number | null; mdd: number | null; note?: string }
export interface NetworkNode { code: string; name: string; relation: string }
export interface NetworkInfo { groups: { relation: string; label: string; nodes: NetworkNode[] }[]; note?: string }
export interface NarrativeInfo { content: string; tokens: number; costKrw: number; cached: boolean; error?: string | null }
export interface MacroInfo { regime: string; riskFree: number | null; recommendedMode?: string }

export interface CompanyData {
  code: string; name: string; sector: string;
  market?: string; listingDate?: string;
  price: number; changePct: number; mktcap: number; // 억
  verdict: string; tone: Tone;
  intrinsic: number; gapPct: number;
  models: ModelResult[];
  summary: { per: number; pbr: number; roe: number; roa: number; debt: number; divYield: number; payout: number; eps: number; bps: number; dps: number; revenue: number; op: number; ni: number; fcf: number; equity: number };
  years: YearFin[];
  quarters: QuarterFin[];
  price1y: PricePt[];
  priceIsSynthetic?: boolean;          // /prices DB 비어 합성 폴백 사용
  fundamentals: FactorGroup[];
  priceFactors: FactorGroup[];
  strengths: FactorVal[];
  weaknesses: FactorVal[];
  shareholder: { divYield: number; payout: number; dps: number; shYield: number };
  consensus: { fwdPer: number; fwdEpsChg: number; revision: number; targetPrice: number; targetUpside: number };
  consensusReal?: boolean;             // 컨센서스 실데이터 여부(현재 mock)
  events: { earningsDays: number; exDivDays: number };
  eventsReal?: boolean;
  peers: Peer[];
  scenarios: Scenario[];
  score: { composite: number; gap: number; roe: number; stability: number };
  // lazy
  signal?: SignalInfo | null;
  risk?: RiskInfo | null;
  network?: NetworkInfo | null;
  narrative?: NarrativeInfo | null;
  macro?: MacroInfo | null;
}

// ── 포맷 헬퍼 ──
export const won = (n: number) => `₩${Math.round(n).toLocaleString()}`;
export const eok = (n: number) => {
  const a = Math.abs(n);
  if (a >= 10000) return `${(n / 10000).toFixed(a >= 100000 ? 0 : 1)}조`;
  return `${Math.round(n).toLocaleString()}억`;
};
export const pct = (n: number, d = 1) => `${n > 0 ? "+" : ""}${n.toFixed(d)}%`;
export const toneColor = (t: Tone) => t === "bull" ? "var(--color-bull)" : t === "bear" ? "var(--color-bear)" : t === "caution" ? "var(--color-caution)" : "var(--t-muted)";
export const verdictTone = (v: string): Tone => v.includes("저평가") ? "bull" : v.includes("고평가") ? "bear" : "neutral";
export const pctColor = (p: number) => p >= 66 ? "var(--color-bull)" : p <= 33 ? "var(--color-bear)" : "var(--color-caution)";
