// ═══════════════════════════════════════════════════════════════════════════════
// entities/company/insightsModel — Company Analysis 프로덕션 데이터 모델 + 포맷 헬퍼
//   CompanyCockpit + entities/company/data.ts 공용. 실API 조립 결과가 이 형태.
//
// 원래 shared/lib/insights/types.ts 였다. 이름만 shared 였고 내용은 company 도메인
// 모델이라(소비자도 entities/company · widgets/company 뿐) 소속을 바로잡았다.
//
// `Tone` → `VerdictTone` 개명: shared/ui/kit.tsx 의 `Tone`("buy"|"sell"|"neutral")
// 과 이름이 겹쳐 grep 이 두 곳을 물어 왔다. 이쪽은 밸류에이션 판정 색조이므로
// 이름으로 구분되게 했다(타입 전용 개명 — 런타임 영향 0).
// ═══════════════════════════════════════════════════════════════════════════════

export type VerdictTone = "bull" | "bear" | "caution" | "neutral";

export interface FactorVal { id: string; label: string; value: number; unit: string; pct: number; higherBetter: boolean }
export interface FactorGroup { id: string; label: string; factors: FactorVal[] }
export interface YearFin { year: string; revenue: number; op: number; ni: number; equity: number; fcf: number; roe: number; debt: number; eps: number; bps: number; dps: number }
export interface QuarterFin { q: string; revenue: number; op: number; ni: number; equity: number; roe: number; debt: number; eps: number; bps: number; dps: number; opMargin: number }
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
  price: number; mktcap: number | null; // 억 — 모르면 null(0 으로 그리지 않는다)
  /** 전일 대비 — ★일별 시세의 마지막 두 종가에서만★(둘 미만이면 null — 0% 를 지어내지 않는다). 옛 `changePct: 0` 상수를 대신한다(BU6a+). */
  dayChange: { pct: number; date: string } | null;
  /** 머리 문장(evaluate)이 연습용 재무로 계산됐는지 — 서버 `is_mock`. */
  isMock: boolean;
  verdict: string; tone: VerdictTone;
  intrinsic: number; gapPct: number;
  models: ModelResult[];
  /** ★null = 몰라요(0 과 다르다 — BU6)★ */
  summary: { per: number | null; pbr: number | null; roe: number | null; roa: number | null; debt: number | null; divYield: number | null; payout: number | null; eps: number | null; bps: number | null; dps: number | null; revenue: number | null; op: number | null; ni: number | null; fcf: number | null; equity: number | null };
  years: YearFin[];
  quarters: QuarterFin[];
  price1y: PricePt[];
  /** 코어 하위 요청 중 서버에 닿지 못한 것 — 화면이 "없음" 대신 실패 + 다시 시도를 말한다(BU6). 시세가 비면(실패 아님) price1y 가 빈 배열. */
  failed: ("valuation" | "financials" | "prices")[];
  fundamentals: FactorGroup[];
  priceFactors: FactorGroup[];
  strengths: FactorVal[];
  weaknesses: FactorVal[];
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
export const won = (n: number) => `${Math.round(n).toLocaleString()}원`;
export const eok = (n: number) => {
  const a = Math.abs(n);
  if (a >= 10000) return `${(n / 10000).toFixed(a >= 100000 ? 0 : 1)}조`;
  return `${Math.round(n).toLocaleString()}억`;
};
export const pct = (n: number, d = 1) => `${n > 0 ? "+" : ""}${n.toFixed(d)}%`;
export const toneColor = (t: VerdictTone) => t === "bull" ? "var(--color-bull)" : t === "bear" ? "var(--color-bear)" : t === "caution" ? "var(--color-caution)" : "var(--t-muted)";
export const verdictTone = (v: string): VerdictTone => v.includes("저평가") ? "bull" : v.includes("고평가") ? "bear" : "neutral";
export const pctColor = (p: number) => p >= 66 ? "var(--color-bull)" : p <= 33 ? "var(--color-bear)" : "var(--color-caution)";
