// ═══════════════════════════════════════════════════════════════════════════════
// insights-lab/sampleData — Company Analysis 후보 목업용 대표 데이터
//   실API(companyLookup 116필드 + /valuation/evaluate + /valuation/financial + peer-groups)
//   형태를 그대로 baked. 선택된 후보를 프로덕션화할 때 이 구조를 실연결로 교체한다.
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

export interface CompanyData {
  code: string; name: string; sector: string;
  price: number; changePct: number; mktcap: number; // 억
  verdict: string; tone: Tone;
  intrinsic: number; gapPct: number;
  models: ModelResult[];
  summary: { per: number; pbr: number; roe: number; roa: number; debt: number; divYield: number; payout: number; eps: number; bps: number; dps: number; revenue: number; op: number; ni: number; fcf: number; equity: number };
  years: YearFin[];
  quarters: QuarterFin[];
  price1y: PricePt[];
  fundamentals: FactorGroup[];
  priceFactors: FactorGroup[];
  strengths: FactorVal[];
  weaknesses: FactorVal[];
  shareholder: { divYield: number; payout: number; dps: number; shYield: number };
  consensus: { fwdPer: number; fwdEpsChg: number; revision: number; targetPrice: number; targetUpside: number };
  events: { earningsDays: number; exDivDays: number };
  peers: Peer[];
  scenarios: Scenario[];
  score: { composite: number; gap: number; roe: number; stability: number };
}

// 결정적 주가 시계열 생성 (월별 ~14M, 현재가로 종료)
function genPrice(seed: number, start: number, end: number, points = 60): PricePt[] {
  let p = start, s = seed;
  const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  const drift = (end - start) / points;
  const out: PricePt[] = [];
  for (let i = 0; i < points; i++) {
    p += drift + (rnd() - 0.5) * start * 0.05;
    const mo = ((i % 12) + 1);
    const yr = 25 + Math.floor(i / 12);
    out.push({ t: `${yr}.${String(mo).padStart(2, "0")}`, p: Math.max(1, Math.round(p)) });
  }
  out[out.length - 1].p = end;
  return out;
}

const fg = (id: string, label: string, factors: FactorVal[]): FactorGroup => ({ id, label, factors });
const f = (id: string, label: string, value: number, unit: string, pct: number, higherBetter = true): FactorVal => ({ id, label, value, unit, pct, higherBetter });

// ── 삼성전자 ──
const samsung: CompanyData = {
  code: "005930", name: "삼성전자", sector: "반도체",
  price: 78400, changePct: 1.24, mktcap: 4680000,
  verdict: "저평가", tone: "bull", intrinsic: 91200, gapPct: -14.04,
  models: [
    { key: "RIM", label: "잔여이익모형", value: 94500, weight: 0.4,
      assumptions: [{ k: "ROE", v: "11.8%" }, { k: "Kₑ", v: "8.4%" }, { k: "영구성장", v: "1.5%" }, { k: "예측", v: "10년" }],
      components: [{ k: "현재 BPS", v: "59,400원" }, { k: "PV 잔여이익", v: "23,800원" }, { k: "PV 잔존가치", v: "11,300원" }] },
    { key: "DCF", label: "현금흐름할인", value: 89300, weight: 0.35,
      assumptions: [{ k: "WACC", v: "8.9%" }, { k: "영구성장", v: "2.0%" }, { k: "예측", v: "10년" }, { k: "초기 FCF성장", v: "6.0%" }],
      components: [{ k: "기준 FCF", v: "180,000억" }, { k: "PV FCF", v: "1,210,000억" }, { k: "PV 잔존", v: "4,030,000억" }, { k: "주당", v: "89,300원" }] },
    { key: "DDM", label: "배당할인모형", value: 84100, weight: 0.25,
      assumptions: [{ k: "Kₑ", v: "8.4%" }, { k: "초기 배당성장", v: "7.0%" }, { k: "영구성장", v: "2.5%" }, { k: "배당성향", v: "25%" }],
      components: [{ k: "현재 DPS", v: "1,650원" }, { k: "PV 배당", v: "12,400원" }, { k: "PV 잔존주가", v: "71,700원" }] },
  ],
  summary: { per: 13.2, pbr: 1.32, roe: 11.8, roa: 8.1, debt: 28.4, divYield: 2.1, payout: 25, eps: 5940, bps: 59400, dps: 1650, revenue: 3020000, op: 350000, ni: 420000, fcf: 180000, equity: 3600000 },
  years: [
    { year: "2021", revenue: 2796000, op: 516000, ni: 399000, equity: 3040000, fcf: 156000, roe: 13.9, debt: 26.1, eps: 5777, bps: 50800, dps: 1444 },
    { year: "2022", revenue: 3022000, op: 433000, ni: 547000, equity: 3260000, fcf: 91000, roe: 17.1, debt: 25.4, eps: 8057, bps: 53900, dps: 1444 },
    { year: "2023", revenue: 2589000, op: 65000, ni: 154000, equity: 3360000, fcf: 28000, roe: 4.6, debt: 27.9, eps: 2131, bps: 56300, dps: 1444 },
    { year: "2024", revenue: 2790000, op: 215000, ni: 280000, equity: 3480000, fcf: 132000, roe: 8.2, debt: 28.0, eps: 4120, bps: 57600, dps: 1500 },
    { year: "2025", revenue: 3020000, op: 350000, ni: 420000, equity: 3600000, fcf: 180000, roe: 11.8, debt: 28.4, eps: 5940, bps: 59400, dps: 1650 },
  ],
  quarters: [
    { q: "24.1Q", revenue: 719000, op: 66000, ni: 67000, opMargin: 9.2 },
    { q: "24.2Q", revenue: 740000, op: 104000, ni: 98000, opMargin: 14.1 },
    { q: "24.3Q", revenue: 790000, op: 91000, ni: 101000, opMargin: 11.5 },
    { q: "24.4Q", revenue: 757000, op: 65000, ni: 76000, opMargin: 8.6 },
    { q: "25.1Q", revenue: 742000, op: 66000, ni: 81000, opMargin: 8.9 },
    { q: "25.2Q", revenue: 745000, op: 81000, ni: 95000, opMargin: 10.9 },
    { q: "25.3Q", revenue: 763000, op: 96000, ni: 118000, opMargin: 12.6 },
    { q: "25.4Q", revenue: 770000, op: 107000, ni: 126000, opMargin: 13.9 },
  ],
  price1y: genPrice(7, 53000, 78400),
  fundamentals: [
    fg("quality", "수익성·퀄리티", [
      f("roe", "ROE", 11.8, "%", 64), f("roic", "ROIC", 9.2, "%", 58), f("gp_to_assets", "GP/A", 0.28, "배", 71),
      f("op_margin", "영업이익률", 11.6, "%", 62), f("net_margin", "순이익률", 13.9, "%", 74), f("ocf_to_ni", "이익의 질", 1.34, "배", 80),
    ]),
    fg("value", "밸류에이션", [
      f("per", "PER", 13.2, "배", 55, false), f("pbr", "PBR", 1.32, "배", 60, false), f("ev_ebitda", "EV/EBITDA", 4.1, "배", 78, false),
      f("fcf_yield", "FCF 수익률", 5.3, "%", 68), f("earnings_yield", "이익수익률", 7.6, "%", 66), f("psr", "PSR", 1.55, "배", 52, false),
    ]),
    fg("growth", "성장성", [
      f("rev_yoy", "매출성장 YoY", 8.2, "%", 57), f("eps_yoy", "EPS성장 YoY", 44.2, "%", 88), f("rev_cagr3", "매출 CAGR 3y", 2.6, "%", 41),
      f("op_yoy", "영업익성장 YoY", 62.8, "%", 90), f("sustainable_g", "지속가능성장", 8.9, "%", 60),
    ]),
    fg("safety", "안전성", [
      f("altman_z", "Altman Z", 3.81, "점", 72), f("piotroski_f", "Piotroski F", 7, "점", 78), f("debt_to_eq", "부채자본비율", 0.28, "배", 84, false),
      f("current_ratio", "유동비율", 248, "%", 80), f("interest_cov", "이자보상배율", 31.4, "배", 86), f("net_debt_ebitda", "순부채/EBITDA", -0.4, "배", 90, false),
    ]),
    fg("composite", "종합", [
      f("qmj_score", "QMJ 점수", 72, "점", 75), f("magic_rank", "Magic Formula", 18, "위", 82, false), f("graham_number", "그레이엄넘버", 88200, "원", 70),
      f("value_composite", "가치 종합", 68, "점", 67), f("greenblatt", "Greenblatt", 64, "점", 71),
    ]),
  ],
  priceFactors: [
    fg("momentum", "모멘텀", [
      f("ret_1m", "1개월 수익률", 4.8, "%", 62), f("ret_3m", "3개월 수익률", 12.4, "%", 70), f("ret_12m", "12개월 수익률", 18.3, "%", 66), f("mom_12_1", "12-1 모멘텀", 15.1, "%", 68),
    ]),
    fg("volatility", "변동성", [
      f("vol_20d", "20일 변동성", 22.4, "%", 44, false), f("beta_1y", "베타", 0.95, "배", 56, false), f("mdd_1y", "최대낙폭", -19.2, "%", 60, false), f("downside_vol", "하방변동성", 16.1, "%", 52, false),
    ]),
    fg("technical", "기술 위치", [
      f("rsi_14", "RSI(14)", 58.4, "점", 58), f("dist_ma20", "20일선 이격", 2.1, "%", 60), f("p52w_high", "52주고가대비", 92.5, "%", 74), f("ma_align", "이평 정배열", 3, "점", 100),
    ]),
    fg("supply", "수급", [
      f("foreign_5d", "외국인 5일", 1250, "억", 82), f("foreign_20d", "외국인 20일", 4320, "억", 86), f("inst_5d", "기관 5일", 430, "억", 64), f("inst_20d", "기관 20일", 980, "억", 68),
    ]),
  ],
  strengths: [
    f("op_yoy", "영업이익성장 YoY", 62.8, "%", 90), f("net_debt_ebitda", "순부채/EBITDA", -0.4, "배", 90), f("eps_yoy", "EPS성장 YoY", 44.2, "%", 88),
    f("interest_cov", "이자보상배율", 31.4, "배", 86), f("foreign_20d", "외국인 순매수 20일", 4320, "억", 86),
  ],
  weaknesses: [
    f("rev_cagr3", "매출 CAGR 3년", 2.6, "%", 41), f("vol_20d", "20일 변동성", 22.4, "%", 44), f("psr", "PSR", 1.55, "배", 52),
  ],
  shareholder: { divYield: 2.1, payout: 25, dps: 1650, shYield: 3.4 },
  consensus: { fwdPer: 11.4, fwdEpsChg: 3.2, revision: 28, targetPrice: 96000, targetUpside: 22.4 },
  events: { earningsDays: 18, exDivDays: 74 },
  peers: [
    { code: "005930", name: "삼성전자", price: 78400, per: 13.2, pbr: 1.32, roe: 11.8, gap: -14.0, mktcap: 4680000, self: true },
    { code: "000660", name: "SK하이닉스", price: 198500, per: 9.1, pbr: 1.95, roe: 22.4, gap: -3.1, mktcap: 1445000 },
    { code: "042700", name: "한미반도체", price: 121000, per: 28.4, pbr: 8.1, roe: 31.2, gap: 18.5, mktcap: 117000 },
    { code: "009150", name: "삼성전기", price: 142000, per: 14.8, pbr: 1.41, roe: 9.8, gap: -6.2, mktcap: 106000 },
  ],
  scenarios: [
    { key: "bull", label: "Bull", value: 108400, gap: 38.3, note: "ROE 14% · 영구성장 2.5% 가정" },
    { key: "base", label: "Base", value: 91200, gap: 16.3, note: "ROE 11.8% · 영구성장 1.5% (기준)" },
    { key: "bear", label: "Bear", value: 71600, gap: -8.7, note: "ROE 9% · 영구성장 0.5% 가정" },
  ],
  score: { composite: 78, gap: 86, roe: 64, stability: 80 },
};

// ── SK하이닉스 ──
const skhynix: CompanyData = {
  code: "000660", name: "SK하이닉스", sector: "반도체",
  price: 198500, changePct: 2.41, mktcap: 1445000,
  verdict: "적정", tone: "neutral", intrinsic: 204800, gapPct: -3.07,
  models: [
    { key: "RIM", label: "잔여이익모형", value: 212000, weight: 0.4,
      assumptions: [{ k: "ROE", v: "22.4%" }, { k: "Kₑ", v: "10.1%" }, { k: "영구성장", v: "2.0%" }, { k: "예측", v: "10년" }],
      components: [{ k: "현재 BPS", v: "101,800원" }, { k: "PV 잔여이익", v: "82,400원" }, { k: "PV 잔존가치", v: "27,800원" }] },
    { key: "DCF", label: "현금흐름할인", value: 201500, weight: 0.35,
      assumptions: [{ k: "WACC", v: "10.6%" }, { k: "영구성장", v: "2.5%" }, { k: "예측", v: "10년" }, { k: "초기 FCF성장", v: "9.0%" }],
      components: [{ k: "기준 FCF", v: "92,000억" }, { k: "PV FCF", v: "640,000억" }, { k: "PV 잔존", v: "820,000억" }, { k: "주당", v: "201,500원" }] },
    { key: "DDM", label: "배당할인모형", value: 188400, weight: 0.25,
      assumptions: [{ k: "Kₑ", v: "10.1%" }, { k: "초기 배당성장", v: "10.0%" }, { k: "영구성장", v: "3.0%" }, { k: "배당성향", v: "10%" }],
      components: [{ k: "현재 DPS", v: "1,500원" }, { k: "PV 배당", v: "9,800원" }, { k: "PV 잔존주가", v: "178,600원" }] },
  ],
  summary: { per: 9.1, pbr: 1.95, roe: 22.4, roa: 13.8, debt: 41.2, divYield: 0.8, payout: 10, eps: 21800, bps: 101800, dps: 1500, revenue: 720000, op: 235000, ni: 158000, fcf: 92000, equity: 740000 },
  years: [
    { year: "2021", revenue: 429000, op: 124000, ni: 96000, equity: 540000, fcf: 38000, roe: 19.4, debt: 38.1, eps: 13190, bps: 74200, dps: 1240 },
    { year: "2022", revenue: 447000, op: 70000, ni: 22000, equity: 580000, fcf: -110000, roe: 3.9, debt: 44.2, eps: 3063, bps: 79700, dps: 1200 },
    { year: "2023", revenue: 327000, op: -77000, ni: -91000, equity: 510000, fcf: -90000, roe: -16.8, debt: 62.1, eps: -12500, bps: 70100, dps: 1000 },
    { year: "2024", revenue: 622000, op: 175000, ni: 118000, equity: 660000, fcf: 64000, roe: 18.9, debt: 48.0, eps: 16210, bps: 90700, dps: 1300 },
    { year: "2025", revenue: 720000, op: 235000, ni: 158000, equity: 740000, fcf: 92000, roe: 22.4, debt: 41.2, eps: 21800, bps: 101800, dps: 1500 },
  ],
  quarters: [
    { q: "24.1Q", revenue: 124000, op: 28000, ni: 19000, opMargin: 22.6 },
    { q: "24.2Q", revenue: 165000, op: 54000, ni: 41000, opMargin: 32.7 },
    { q: "24.3Q", revenue: 175000, op: 70000, ni: 58000, opMargin: 40.0 },
    { q: "24.4Q", revenue: 197000, op: 80000, ni: 80000, opMargin: 40.6 },
    { q: "25.1Q", revenue: 174000, op: 53000, ni: 50000, opMargin: 30.5 },
    { q: "25.2Q", revenue: 178000, op: 58000, ni: 38000, opMargin: 32.6 },
    { q: "25.3Q", revenue: 182000, op: 61000, ni: 34000, opMargin: 33.5 },
    { q: "25.4Q", revenue: 186000, op: 63000, ni: 36000, opMargin: 33.9 },
  ],
  price1y: genPrice(19, 142000, 198500),
  fundamentals: [
    fg("quality", "수익성·퀄리티", [
      f("roe", "ROE", 22.4, "%", 90), f("roic", "ROIC", 18.7, "%", 88), f("gp_to_assets", "GP/A", 0.41, "배", 86),
      f("op_margin", "영업이익률", 32.6, "%", 94), f("net_margin", "순이익률", 21.9, "%", 88), f("ocf_to_ni", "이익의 질", 1.52, "배", 84),
    ]),
    fg("value", "밸류에이션", [
      f("per", "PER", 9.1, "배", 78, false), f("pbr", "PBR", 1.95, "배", 40, false), f("ev_ebitda", "EV/EBITDA", 3.4, "배", 84, false),
      f("fcf_yield", "FCF 수익률", 6.4, "%", 72), f("earnings_yield", "이익수익률", 11.0, "%", 82), f("psr", "PSR", 2.0, "배", 38, false),
    ]),
    fg("growth", "성장성", [
      f("rev_yoy", "매출성장 YoY", 15.8, "%", 80), f("eps_yoy", "EPS성장 YoY", 34.5, "%", 84), f("rev_cagr3", "매출 CAGR 3y", 18.2, "%", 86),
      f("op_yoy", "영업익성장 YoY", 34.3, "%", 82), f("sustainable_g", "지속가능성장", 20.2, "%", 88),
    ]),
    fg("safety", "안전성", [
      f("altman_z", "Altman Z", 2.94, "점", 54), f("piotroski_f", "Piotroski F", 8, "점", 88), f("debt_to_eq", "부채자본비율", 0.41, "배", 62, false),
      f("current_ratio", "유동비율", 162, "%", 58), f("interest_cov", "이자보상배율", 14.2, "배", 70), f("net_debt_ebitda", "순부채/EBITDA", 0.6, "배", 64, false),
    ]),
    fg("composite", "종합", [
      f("qmj_score", "QMJ 점수", 84, "점", 90), f("magic_rank", "Magic Formula", 8, "위", 92, false), f("graham_number", "그레이엄넘버", 215000, "원", 80),
      f("value_composite", "가치 종합", 76, "점", 82), f("greenblatt", "Greenblatt", 80, "점", 88),
    ]),
  ],
  priceFactors: [
    fg("momentum", "모멘텀", [
      f("ret_1m", "1개월 수익률", 9.2, "%", 80), f("ret_3m", "3개월 수익률", 21.4, "%", 86), f("ret_12m", "12개월 수익률", 39.8, "%", 90), f("mom_12_1", "12-1 모멘텀", 33.2, "%", 88),
    ]),
    fg("volatility", "변동성", [
      f("vol_20d", "20일 변동성", 34.1, "%", 28, false), f("beta_1y", "베타", 1.42, "배", 32, false), f("mdd_1y", "최대낙폭", -28.4, "%", 40, false), f("downside_vol", "하방변동성", 25.2, "%", 36, false),
    ]),
    fg("technical", "기술 위치", [
      f("rsi_14", "RSI(14)", 66.8, "점", 72), f("dist_ma20", "20일선 이격", 5.4, "%", 78), f("p52w_high", "52주고가대비", 97.1, "%", 88), f("ma_align", "이평 정배열", 3, "점", 100),
    ]),
    fg("supply", "수급", [
      f("foreign_5d", "외국인 5일", 2840, "억", 92), f("foreign_20d", "외국인 20일", 9120, "억", 94), f("inst_5d", "기관 5일", 1180, "억", 84), f("inst_20d", "기관 20일", 3240, "억", 86),
    ]),
  ],
  strengths: [
    f("op_margin", "영업이익률", 32.6, "%", 94), f("foreign_20d", "외국인 순매수 20일", 9120, "억", 94), f("magic_rank", "Magic Formula", 8, "위", 92),
    f("ret_12m", "12개월 수익률", 39.8, "%", 90), f("roe", "ROE", 22.4, "%", 90),
  ],
  weaknesses: [
    f("vol_20d", "20일 변동성", 34.1, "%", 28), f("beta_1y", "베타", 1.42, "배", 32), f("pbr", "PBR", 1.95, "배", 40),
  ],
  shareholder: { divYield: 0.8, payout: 10, dps: 1500, shYield: 1.1 },
  consensus: { fwdPer: 7.2, fwdEpsChg: 8.6, revision: 52, targetPrice: 248000, targetUpside: 24.9 },
  events: { earningsDays: 9, exDivDays: 74 },
  peers: [
    { code: "000660", name: "SK하이닉스", price: 198500, per: 9.1, pbr: 1.95, roe: 22.4, gap: -3.1, mktcap: 1445000, self: true },
    { code: "005930", name: "삼성전자", price: 78400, per: 13.2, pbr: 1.32, roe: 11.8, gap: -14.0, mktcap: 4680000 },
    { code: "042700", name: "한미반도체", price: 121000, per: 28.4, pbr: 8.1, roe: 31.2, gap: 18.5, mktcap: 117000 },
    { code: "240810", name: "원익IPS", price: 38600, per: 22.1, pbr: 2.2, roe: 10.4, gap: 6.8, mktcap: 19000 },
  ],
  scenarios: [
    { key: "bull", label: "Bull", value: 252000, gap: 26.9, note: "ROE 26% · 영구성장 3% 가정" },
    { key: "base", label: "Base", value: 204800, gap: 3.2, note: "ROE 22.4% · 영구성장 2% (기준)" },
    { key: "bear", label: "Bear", value: 158000, gap: -20.4, note: "ROE 16% · 영구성장 1% 가정" },
  ],
  score: { composite: 84, gap: 62, roe: 96, stability: 70 },
};

// ── 카카오 ──
const kakao: CompanyData = {
  code: "035720", name: "카카오", sector: "인터넷",
  price: 38200, changePct: -0.78, mktcap: 170000,
  verdict: "고평가", tone: "bear", intrinsic: 34100, gapPct: 12.02,
  models: [
    { key: "RIM", label: "잔여이익모형", value: 32400, weight: 0.4,
      assumptions: [{ k: "ROE", v: "4.2%" }, { k: "Kₑ", v: "9.8%" }, { k: "영구성장", v: "2.0%" }, { k: "예측", v: "10년" }],
      components: [{ k: "현재 BPS", v: "31,600원" }, { k: "PV 잔여이익", v: "-3,100원" }, { k: "PV 잔존가치", v: "3,900원" }] },
    { key: "DCF", label: "현금흐름할인", value: 35800, weight: 0.35,
      assumptions: [{ k: "WACC", v: "9.4%" }, { k: "영구성장", v: "3.0%" }, { k: "예측", v: "10년" }, { k: "초기 FCF성장", v: "8.0%" }],
      components: [{ k: "기준 FCF", v: "6,200억" }, { k: "PV FCF", v: "52,000억" }, { k: "PV 잔존", v: "108,000억" }, { k: "주당", v: "35,800원" }] },
    { key: "DDM", label: "배당할인모형", value: 33500, weight: 0.25,
      assumptions: [{ k: "Kₑ", v: "9.8%" }, { k: "초기 배당성장", v: "5.0%" }, { k: "영구성장", v: "2.0%" }, { k: "배당성향", v: "15%" }],
      components: [{ k: "현재 DPS", v: "60원" }, { k: "PV 배당", v: "520원" }, { k: "PV 잔존주가", v: "32,980원" }] },
  ],
  summary: { per: 48.6, pbr: 1.21, roe: 4.2, roa: 2.1, debt: 62.4, divYield: 0.2, payout: 12, eps: 786, bps: 31600, dps: 60, revenue: 81000, op: 5200, ni: 3500, fcf: 6200, equity: 140000 },
  years: [
    { year: "2021", revenue: 61000, op: 5900, ni: 16400, equity: 120000, fcf: 4200, roe: 14.8, debt: 51.2, eps: 3680, bps: 27000, dps: 60 },
    { year: "2022", revenue: 71000, op: 5800, ni: 10600, equity: 128000, fcf: 3100, roe: 8.6, debt: 55.4, eps: 2380, bps: 28700, dps: 60 },
    { year: "2023", revenue: 78000, op: 5000, ni: -1700, equity: 132000, fcf: 4800, roe: -1.3, debt: 60.1, eps: -380, bps: 29600, dps: 60 },
    { year: "2024", revenue: 79000, op: 4900, ni: 2300, equity: 137000, fcf: 5600, roe: 1.7, debt: 61.8, eps: 516, bps: 30700, dps: 60 },
    { year: "2025", revenue: 81000, op: 5200, ni: 3500, equity: 140000, fcf: 6200, roe: 4.2, debt: 62.4, eps: 786, bps: 31600, dps: 60 },
  ],
  quarters: [
    { q: "24.1Q", revenue: 19000, op: 1200, ni: 800, opMargin: 6.3 },
    { q: "24.2Q", revenue: 20000, op: 1340, ni: 620, opMargin: 6.7 },
    { q: "24.3Q", revenue: 19800, op: 1230, ni: 480, opMargin: 6.2 },
    { q: "24.4Q", revenue: 20200, op: 1130, ni: 400, opMargin: 5.6 },
    { q: "25.1Q", revenue: 20100, op: 1280, ni: 820, opMargin: 6.4 },
    { q: "25.2Q", revenue: 20400, op: 1310, ni: 910, opMargin: 6.4 },
    { q: "25.3Q", revenue: 20100, op: 1290, ni: 880, opMargin: 6.4 },
    { q: "25.4Q", revenue: 20400, op: 1320, ni: 890, opMargin: 6.5 },
  ],
  price1y: genPrice(31, 44800, 38200),
  fundamentals: [
    fg("quality", "수익성·퀄리티", [
      f("roe", "ROE", 4.2, "%", 24), f("roic", "ROIC", 3.1, "%", 20), f("gp_to_assets", "GP/A", 0.18, "배", 36),
      f("op_margin", "영업이익률", 6.4, "%", 34), f("net_margin", "순이익률", 4.3, "%", 30), f("ocf_to_ni", "이익의 질", 1.78, "배", 88),
    ]),
    fg("value", "밸류에이션", [
      f("per", "PER", 48.6, "배", 12, false), f("pbr", "PBR", 1.21, "배", 64, false), f("ev_ebitda", "EV/EBITDA", 11.4, "배", 30, false),
      f("fcf_yield", "FCF 수익률", 3.6, "%", 48), f("earnings_yield", "이익수익률", 2.1, "%", 18), f("psr", "PSR", 2.1, "배", 36, false),
    ]),
    fg("growth", "성장성", [
      f("rev_yoy", "매출성장 YoY", 2.5, "%", 38), f("eps_yoy", "EPS성장 YoY", 52.3, "%", 70), f("rev_cagr3", "매출 CAGR 3y", 4.5, "%", 46),
      f("op_yoy", "영업익성장 YoY", 6.1, "%", 50), f("sustainable_g", "지속가능성장", 3.7, "%", 34),
    ]),
    fg("safety", "안전성", [
      f("altman_z", "Altman Z", 1.92, "점", 30), f("piotroski_f", "Piotroski F", 5, "점", 50), f("debt_to_eq", "부채자본비율", 0.62, "배", 44, false),
      f("current_ratio", "유동비율", 118, "%", 40), f("interest_cov", "이자보상배율", 4.1, "배", 38), f("net_debt_ebitda", "순부채/EBITDA", 1.8, "배", 42, false),
    ]),
    fg("composite", "종합", [
      f("qmj_score", "QMJ 점수", 41, "점", 32), f("magic_rank", "Magic Formula", 148, "위", 28, false), f("graham_number", "그레이엄넘버", 23600, "원", 30),
      f("value_composite", "가치 종합", 38, "점", 30), f("greenblatt", "Greenblatt", 34, "점", 26),
    ]),
  ],
  priceFactors: [
    fg("momentum", "모멘텀", [
      f("ret_1m", "1개월 수익률", -3.4, "%", 36), f("ret_3m", "3개월 수익률", -8.2, "%", 30), f("ret_12m", "12개월 수익률", -14.7, "%", 22), f("mom_12_1", "12-1 모멘텀", -11.2, "%", 26),
    ]),
    fg("volatility", "변동성", [
      f("vol_20d", "20일 변동성", 29.4, "%", 36, false), f("beta_1y", "베타", 1.18, "배", 44, false), f("mdd_1y", "최대낙폭", -24.1, "%", 46, false), f("downside_vol", "하방변동성", 21.8, "%", 44, false),
    ]),
    fg("technical", "기술 위치", [
      f("rsi_14", "RSI(14)", 42.6, "점", 38), f("dist_ma20", "20일선 이격", -2.8, "%", 38), f("p52w_high", "52주고가대비", 78.4, "%", 34), f("ma_align", "이평 정배열", 0, "점", 10),
    ]),
    fg("supply", "수급", [
      f("foreign_5d", "외국인 5일", -340, "억", 30), f("foreign_20d", "외국인 20일", -1280, "억", 24), f("inst_5d", "기관 5일", -180, "억", 34), f("inst_20d", "기관 20일", -620, "억", 30),
    ]),
  ],
  strengths: [
    f("ocf_to_ni", "이익의 질", 1.78, "배", 88), f("eps_yoy", "EPS성장 YoY", 52.3, "%", 70), f("pbr", "PBR", 1.21, "배", 64),
  ],
  weaknesses: [
    f("per", "PER", 48.6, "배", 12, false), f("earnings_yield", "이익수익률", 2.1, "%", 18), f("roic", "ROIC", 3.1, "%", 20),
    f("ret_12m", "12개월 수익률", -14.7, "%", 22), f("foreign_20d", "외국인 순매수 20일", -1280, "억", 24),
  ],
  shareholder: { divYield: 0.2, payout: 12, dps: 60, shYield: 0.3 },
  consensus: { fwdPer: 32.1, fwdEpsChg: -4.2, revision: -18, targetPrice: 41000, targetUpside: 7.3 },
  events: { earningsDays: 26, exDivDays: 74 },
  peers: [
    { code: "035720", name: "카카오", price: 38200, per: 48.6, pbr: 1.21, roe: 4.2, gap: 12.0, mktcap: 170000, self: true },
    { code: "035420", name: "NAVER", price: 218000, per: 18.4, pbr: 1.32, roe: 9.8, gap: -8.4, mktcap: 348000 },
    { code: "376300", name: "디어유", price: 41500, per: 24.2, pbr: 5.1, roe: 22.8, gap: 9.1, mktcap: 9000 },
    { code: "263750", name: "펄어비스", price: 38900, per: 41.0, pbr: 2.8, roe: 6.4, gap: 15.2, mktcap: 25000 },
  ],
  scenarios: [
    { key: "bull", label: "Bull", value: 46200, gap: 20.9, note: "ROE 8% · 영구성장 3% 가정" },
    { key: "base", label: "Base", value: 34100, gap: -10.7, note: "ROE 4.2% · 영구성장 2% (기준)" },
    { key: "bear", label: "Bear", value: 24800, gap: -35.1, note: "ROE 2% · 영구성장 1% 가정" },
  ],
  score: { composite: 41, gap: 22, roe: 26, stability: 44 },
};

export const COMPANIES: CompanyData[] = [samsung, skhynix, kakao];
export const byCode = (code: string): CompanyData => COMPANIES.find((c) => c.code === code) ?? samsung;

// ── 포맷 헬퍼 ──
export const won = (n: number) => `₩${Math.round(n).toLocaleString()}`;
export const eok = (n: number) => {
  const a = Math.abs(n);
  if (a >= 10000) return `${(n / 10000).toFixed(a >= 100000 ? 0 : 1)}조`;
  return `${Math.round(n).toLocaleString()}억`;
};
export const pct = (n: number, d = 1) => `${n > 0 ? "+" : ""}${n.toFixed(d)}%`;
export const toneColor = (t: Tone) => t === "bull" ? "var(--color-bull)" : t === "bear" ? "var(--color-bear)" : t === "caution" ? "var(--color-caution)" : "var(--t-muted)";
// verdict → tone
export const verdictTone = (v: string): Tone =>
  v.includes("저평가") ? "bull" : v.includes("고평가") ? "bear" : "neutral";
// 퍼센타일 → 색 (higherBetter 반영: 높을수록 좋음=초록)
export const pctColor = (p: number) => p >= 66 ? "var(--color-bull)" : p <= 33 ? "var(--color-bear)" : "var(--color-caution)";
