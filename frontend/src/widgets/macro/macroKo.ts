/**
 * 매크로 분석 탭 안 카드의 번역표·색 단계 (BU5b — 계획 "BU5b 상세")
 * ==========================================================================
 * ★번역만 한다(ADR-003 §2.6)★ 서버 키를 한국어로 옮길 뿐 새 판단을 만들지 않는다. 모르는 키는 서버 글자 그대로.
 * 색은 뜻이 넷이다 — 섞지 않는다:
 *  · 등락(변화·수익률) = `--tx-up(-ink)` 빨강 / `--tx-down(-ink)` 파랑 + 부호 (한국식)
 *  · 수준(z·백분위) = `--mc-lv-*` 주황(평균보다 높음) / 청록(낮음) + 회색 가운데 — 등락색과 다른 양쪽 색(사용자 결정)
 *  · 판단(공격/방어·틸트·스트레스·적합도) = 색으로 말하지 않는다(중립) — 글자가 말한다
 *  · 국면 = `--mc-q-*` (BU5a+ 도넛과 같은 네 색) · 범주 계열 = `--mc-c-1..7` + 기타
 * (IND_KR·STRESS_KO 는 원래 visualParts·RegimeVisual 에 있었다 — cockpitParts 가 쓰려면 순환 import 가 생겨 여기로 옮겼다.)
 */

/** 지표 키 → 짧은 한국어 이름. */
export const IND_KR: Record<string, string> = {
  KR_LEADING_CYCLE: "경기선행", KR_IP: "산업생산", KOSPI: "KOSPI", KR_CPI: "CPI",
  KR_10Y: "국고10년", USD_KRW: "환율", CPIAUCSL: "CPI", INDPRO: "산업생산",
  PAYEMS: "고용", UNRATE: "실업률", GDPC1: "GDP", T10YIE: "기대인플레",
  DGS10: "미국10년", VIXCLS: "VIX", BAMLH0A0HYM2: "하이일드 스프레드",
  // BU5c — 스튜디오 입력 계열·장기관계 변수
  KR_3Y: "국고3년", KR_BASE_RATE: "기준금리", KR_TERM_SPREAD: "장단기 금리차", KR_CREDIT_SPREAD: "신용 스프레드",
  DGS3MO: "미국3개월", DGS2: "미국2년", DGS30: "미국30년", T10Y2Y: "미국 10년−2년", DFII10: "미국 실질금리10년", M2SL: "미국 M2",
};

/** 스트레스 구성 항목 이름 — 서버 `_compute_stress` 의 키. */
export const STRESS_KO: Record<string, string> = {
  vix: "변동성 지수(VIX)", credit_spread: "신용 스프레드", fx_volatility: "환율 변동성",
  rate_volatility: "금리 변동성", dxy_strength: "달러 강세", yield_curve: "수익률 곡선(10년−2년)", real_rate: "실질 금리",
};

/** 국면 기반 자산군 틸트 키 — 서버 `asset_tilts`. */
export const TILT_KO: Record<string, string> = {
  growth_stocks: "성장주", value_stocks: "가치주", bonds: "채권", commodities: "원자재", cash: "현금",
  gold: "금", reits: "리츠", em: "신흥국", stocks: "주식",
};

/** 틸트 기호 → 단계·말. 모르는 기호는 서버 글자 그대로(중립 자리). */
export const TILT_STEP: Record<string, { v: number; lbl: string }> = {
  "++": { v: 2, lbl: "강한 비중확대" }, "+": { v: 1, lbl: "비중확대" }, "0": { v: 0, lbl: "중립" },
  "-": { v: -1, lbl: "비중축소" }, "--": { v: -2, lbl: "강한 비중축소" },
};

/** "202505" · "2025-05" → "2025.05". 모르는 모양은 그대로. */
export function ym(s: string | undefined | null): string {
  if (!s) return "";
  const m = /^(\d{4})-?(\d{2})/.exec(s);
  return m ? `${m[1]}.${m[2]}` : s;
}

// ── 수준 색 단계 (z) ── 0.5·1·2 σ 를 경계로 쪽마다 3 단. 그리기 위한 구간일 뿐 판단이 아니다(값은 늘 글자로 함께 보인다).
export type LvStep = "neg-3" | "neg-2" | "neg-1" | "mid" | "pos-1" | "pos-2" | "pos-3";
export function zStep(z: number): LvStep {
  const a = Math.abs(z);
  if (a < 0.5) return "mid";
  const k = a < 1 ? 1 : a < 2 ? 2 : 3;
  return `${z > 0 ? "pos" : "neg"}-${k}` as LvStep;
}
/** z → 칸 바탕색. 모르면(null) 빈 칸 색 — 0 으로 칠하지 않는다. */
export function zFill(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return "var(--mc-lv-none)";
  return `var(--mc-lv-${zStep(z)})`;
}
/** 백분위(0..100) → 칸 바탕색. 50 이 가운데 — 위치를 z 처럼 같은 양쪽 색으로. */
export function pctFill(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "var(--mc-lv-none)";
  const t = (p - 50) / 50, a = Math.abs(t);
  if (a < 0.2) return "var(--mc-lv-mid)";
  const k = a < 0.5 ? 1 : a < 0.8 ? 2 : 3;
  return `var(--mc-lv-${t > 0 ? "pos" : "neg"}-${k})`;
}

/** 범주 계열 색(빨강·파랑 없음) — 7 개를 넘으면 "기타" 회색으로 접는다. dataviz 검증기 인접 쌍 통과(라이트·다크). */
export const CAT_N = 7;
export const catColor = (idx: number): string => (idx < CAT_N ? `var(--mc-c-${idx + 1})` : "var(--mc-c-etc)");

/** 부호 있는 수(진짜 마이너스 기호). 모르면 "몰라요". */
export function signed(v: number | null | undefined, d = 2): string {
  if (v == null || !Number.isFinite(v)) return "몰라요";
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(d)}`;
}

// ── BU5c 스튜디오 · 매크로 지능 패널 번역표 ─────────────────────────────────────────

/** 스튜디오 산출 키 → 한국어. 모르는 키는 서버 이름 그대로(`data-mono`). */
export const STUDIO_OUT_KO: Record<string, string> = {
  series: "쓴 계열", factors: "요인 값", loadings: "적재(요인과 함께 움직이는 정도)", latest: "지금 값",
  k_factors: "요인 수", explained_var: "설명한 분산 비율",
  lambda: "곡률 위치(λ)", tenors: "만기(년)", series_used: "쓴 계열", level: "수준", slope: "기울기", curvature: "곡률",
  inverted: "역전 여부", rmse_pp: "적합 오차(%p)", term_premium_proxy: "기간프리미엄 대용(bp)", term_premium_reason: "기간프리미엄을 못 잰 이유",
  nodes: "지표", edges: "앞서 움직이는 관계", n_series: "검사한 계열 수",
  assets: "자산", n_views: "뷰 수", A: "제약 행렬(A)", b: "제약 한계(b)", human: "제약(사람 말)", feasible: "모순 검사 결과",
};

/** 사다리·고급 엔진 요건 코드 → 사람 말. 모르는 코드는 서버 사유 그대로. */
export const MISSING_KO: Record<string, string> = {
  torch: "딥러닝 도구가 이 서버에 설치되어 있지 않아요",
  cvxpylayers: "미분 가능한 최적화 도구가 설치되어 있지 않아요",
  trends_api: "검색 트렌드 키(네이버·구글)가 설정되지 않았어요",
  llm: "AI 설명 키가 설정되지 않았어요",
  frontier_sample: "이 엔진은 더 긴 기간의 자료가 필요해요",
  statsmodels: "통계 도구가 설치되어 있지 않아요",
  causal_sample: "검정에 쓸 표본이 짧아요",
};

/** 서버 사유 "code: 글 / code: 글" 을 조각으로. 코드가 없는 조각은 code=null. */
export function splitReason(raw: string | null | undefined): { code: string | null; text: string }[] {
  if (!raw) return [];
  return raw.split(" / ").map((part) => {
    const m = /^([a-z_]+):\s*(.*)$/.exec(part.trim());
    return m ? { code: m[1], text: m[2] } : { code: null, text: part.trim() };
  });
}

/** 조각 하나의 사람 말 — 아는 코드면 번역(+서버 글의 관측 수), 모르면 null(서버 글을 그대로 보인다). */
export function reasonKo(p: { code: string | null; text: string }): string | null {
  if (!p.code || !MISSING_KO[p.code]) return null;
  const n = /관측 (\d+)개, 최소 (\d+)개/.exec(p.text);
  return n ? `${MISSING_KO[p.code]}(지금 관측 ${n[1]}개, 최소 ${n[2]}개)` : MISSING_KO[p.code];
}

/** 국면 도구 이름 — 서버 `per_tool` 키. */
export const TOOL_KO: Record<string, string> = { axis: "축 모형", markov: "마르코프 전환", cluster: "군집" };
