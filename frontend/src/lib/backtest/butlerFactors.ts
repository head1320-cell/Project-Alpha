// 대상 경로: frontend/src/lib/backtest/butlerFactors.ts
//
// Butler(버틀러) 퀀트 플랫폼 팩터 택소노미 이식 — 9개 대분류 → 중분류 → 팩터(2단).
// 각 팩터 expr = {토큰}. 토큰이 백엔드 support-map(/condition-tokens)의 supported면
// 픽커에서 사용 가능, 아니면 회색 비활성(+사유·대체칩 — factor_tokens.py).
//   · 지원 토큰: token_support() 의 정확한 표기(예: {ROE} {신고가갱신(52주)} {외국인순매수금액})
//   · 미지원 토큰: factor_tokens.py UNSUPPORTED_REASONS 에 사유 등록(컨센서스/사업보고서/공매도 등)
// 끝에 우리 고유 팩터(기술지표·점수·학술·매크로)를 추가 대분류로 보존 — 기능 손실 0.

import type { GpFactor } from "./factorCatalog";

export interface ButlerGroup { label: string; factors: GpFactor[]; }
export interface ButlerCategory { id: string; label: string; groups: ButlerGroup[]; }

/** name=Butler 표기(표시), token=백엔드 토큰(평가·지원판정). 같으면 한 번만. */
const f = (name: string, token?: string): GpFactor => ({ name, expr: `{${token ?? name}}` });

export const BUTLER_CATEGORIES: ButlerCategory[] = [
  {
    id: "basic", label: "기본정보",
    groups: [
      { label: "시장 정보", factors: [f("시가총액"), f("버틀러 랭킹", "종합점수")] },
    ],
  },
  {
    id: "business", label: "사업정보",
    groups: [
      { label: "수주·수출", factors: [f("수주잔고"), f("수주잔고증가율"), f("수출품목")] },
      { label: "직원수", factors: [f("직원수"), f("남자직원수"), f("여자직원수"), f("여자직원비율"), f("직원수증가율")] },
      { label: "직원급여", factors: [f("직원급여총액"), f("평균급여"), f("평균급여증가율")] },
      { label: "직원생산성", factors: [f("1인당매출액"), f("1인당영업이익")] },
      { label: "임원정보", factors: [f("임원수"), f("임원평균급여"), f("임원급여총액증가율")] },
    ],
  },
  {
    id: "financials", label: "재무정보",
    groups: [
      { label: "손익계산서", factors: [f("매출액"), f("영업이익"), f("순이익")] },
      { label: "재무상태표", factors: [f("자산총계", "분기자산"), f("자본총계", "분기자본"), f("부채총계", "분기부채"), f("유형자산비중"), f("무형자산비중"), f("시총대비순금융자산비율")] },
      { label: "현금흐름표", factors: [f("영업현금흐름", "분기영업현금흐름"), f("자본지출(CAPEX)")] },
    ],
  },
  {
    id: "fundamental", label: "펀더멘탈",
    groups: [
      { label: "수익성", factors: [f("ROE"), f("지배주주ROE", "ROE"), f("ROA"), f("ROIC"), f("GP/A"), f("매출총이익률"), f("영업이익률"), f("순이익률"), f("매출원가율"), f("판매관리비율", "판관비율")] },
      { label: "성장성", factors: [f("매출액성장율", "매출성장률(YoY)"), f("매출총이익성장율"), f("영업이익성장율", "영업이익성장률(YoY)"), f("순이익성장율", "분기순이익성장률(YOY)"), f("자본성장율", "분기자본성장률(YOY)"), f("재고자산증가율"), f("매출채권증가율"), f("매입채무증가율")] },
      { label: "안정성", factors: [f("부채비율"), f("유동비율")] },
      { label: "효율성", factors: [f("매출채권회전율"), f("재고자산회전율"), f("현금회전일수"), f("현금전환비율(CCR)", "현금전환율")] },
    ],
  },
  {
    id: "valuation", label: "밸류에이션",
    groups: [
      { label: "밸류지표", factors: [f("PBR"), f("PSR"), f("PER"), f("POR"), f("PFCFR", "EV/FCF"), f("PEG")] },
      { label: "주당지표", factors: [f("주당순자산증가율"), f("주당순이익증가율", "EPS성장률(YoY)")] },
    ],
  },
  {
    id: "shareholder", label: "주주환원",
    groups: [
      { label: "배당현황", factors: [f("주당배당금"), f("배당횟수"), f("배당시점배당수익률"), f("시가배당수익률", "배당수익률"), f("EPS배당성향", "배당성향"), f("FCF배당성향"), f("배당금총액증가율"), f("주당배당금증가율", "배당성장률")] },
      { label: "자사주현황", factors: [f("자사주보유비율"), f("자사주소각횟수"), f("자사주소각비율")] },
      { label: "투자자수익률", factors: [f("주가수익률", "투자자주가수익률"), f("총수익률")] },
    ],
  },
  {
    id: "stock", label: "주식정보",
    groups: [
      { label: "주가", factors: [f("주가변동률(1일)", "일별주가상승률"), f("주가변동률(1주일)", "주간주가상승률1주전"), f("주가변동률(1개월)", "월간주가상승률1개월전"), f("주가변동률(1년)", "주가변동률1년"), f("52주 신고가", "신고가갱신(52주)"), f("52주 신저가", "신저가갱신(52주)")] },
      { label: "거래량", factors: [f("거래량증가율", "20일평균거래량대비거래량"), f("거래대금증가율")] },
      { label: "투자자별", factors: [f("외국인 연속순매수", "외국인순매수금액"), f("기관 연속순매수", "기관순매수금액")] },
      { label: "내부자거래", factors: [f("장내매수"), f("장내매도")] },
      { label: "공매도정보", factors: [f("공매도잔고비율"), f("대차잔고비율")] },
      { label: "주주정보", factors: [f("외국인지분율"), f("대주주지분율"), f("소액주주수"), f("소액주주지분율")] },
      { label: "발행정보", factors: [f("우선주발행")] },
    ],
  },
  {
    id: "consensus", label: "컨센서스",
    groups: [
      { label: "목표주가", factors: [f("목표주가수익률"), f("분석보고서수"), f("커버증권사수")] },
      { label: "예상실적", factors: [f("예상매출액증가율"), f("예상영업이익증가율"), f("매출액Surprise"), f("영업이익Surprise")] },
    ],
  },
  {
    id: "ir", label: "IR정보",
    groups: [
      { label: "실적발표", factors: [f("실적발표일")] },
      { label: "기업설명회", factors: [f("기업설명회횟수")] },
    ],
  },
  // ───── 우리 고유 팩터 보존 (Butler 외) ─────
  {
    id: "x_technical", label: "기술지표",
    groups: [
      { label: "추세·오실레이터", factors: [f("RSI"), f("MACD"), f("MACD시그널"), f("MACD오실레이터"), f("CCI"), f("스토캐스틱(K)"), f("스토캐스틱(D)"), f("TRIX"), f("DMI(ADX)"), f("심리선")] },
      { label: "밴드·채널", factors: [f("볼린저밴드_상단값"), f("볼린저밴드_하단값"), f("볼린저밴드_밴드폭"), f("켈트너_위치"), f("돈치안_위치")] },
      { label: "거래량 지표", factors: [f("OBV"), f("MFI"), f("AD_LINE"), f("FORCE_INDEX(단기)"), f("20일평균거래량대비거래량")] },
      { label: "가격 위치·캔들", factors: [f("이격도"), f("주가이동평균변화율"), f("골든크로스(20일/60일)"), f("윗꼬리비율"), f("아래꼬리비율"), f("종가시초가대비율")] },
      { label: "피벗·일목", factors: [f("피벗_기준선"), f("피벗_1차저항"), f("피벗_1차지지"), f("일목균형표기준선"), f("일목균형표전환선")] },
    ],
  },
  {
    id: "x_score", label: "종합점수",
    groups: [
      { label: "뉴지랭크 근사", factors: [f("종합점수"), f("펀더멘탈점수"), f("모멘텀점수"), f("가격점수"), f("수급점수"), f("성장점수"), f("가치점수")] },
    ],
  },
  {
    id: "x_academic", label: "학술 팩터",
    groups: [
      { label: "퀄리티·복합", factors: [f("Altman Z-Score"), f("Beneish M-Score"), f("F-Score"), f("QMJ 점수"), f("Magic Formula 순위"), f("Greenblatt 점수"), f("ROE(듀폰)"), f("이익의 질"), f("발생액 비율"), f("이자보상배율")] },
      { label: "밸류 심화", factors: [f("그레이엄 넘버"), f("NCAV/시총"), f("Acquirer's Multiple"), f("이익수익률"), f("FCF 수익률"), f("주주환원수익률"), f("EV/EBITDA"), f("EV/Sales"), f("BPS"), f("장부/시장")] },
      { label: "수익성·효율 심화", factors: [f("EBITDA 마진"), f("FCF 마진"), f("자산회전율"), f("재무레버리지"), f("순부채/EBITDA"), f("자기자본비율"), f("당좌비율"), f("현금비율"), f("설비투자 집약도"), f("R&D 집약도")] },
      { label: "성장·모멘텀 심화", factors: [f("12-1 모멘텀"), f("매출 CAGR(3년)"), f("EPS CAGR(3년)"), f("지속가능성장률"), f("성장 가속도"), f("FCF 성장률")] },
    ],
  },
  {
    id: "x_macro", label: "매크로·시장·수급",
    groups: [
      { label: "금리·환율", factors: [f("국고채(3년)"), f("국고채(10년)"), f("US국채(10년)"), f("US달러환율"), f("엔환율")] },
      { label: "지수", factors: [f("KOSPI지수_종가"), f("KOSDAQ지수_종가"), f("VIX_종가"), f("베타")] },
      { label: "투자자별 순매수", factors: [f("외국인순매수금액"), f("기관순매수금액"), f("개인순매수금액"), f("연기금순매수금액"), f("투신순매수금액")] },
    ],
  },
];

/** 검색·호환용 평탄화 — (대분류, 중분류, 팩터) */
export function butlerFlat(): { category: ButlerCategory; group: ButlerGroup; factor: GpFactor }[] {
  const out: { category: ButlerCategory; group: ButlerGroup; factor: GpFactor }[] = [];
  for (const c of BUTLER_CATEGORIES) for (const g of c.groups) for (const fac of g.factors) out.push({ category: c, group: g, factor: fac });
  return out;
}

/** 팩터 expr/이름 → 백엔드 토큰(중괄호 제거). support-map 판정·평가에 사용. */
export function butlerToken(fac: GpFactor): string {
  const m = /^\{([^{}]+)\}$/.exec(fac.expr);
  return m ? m[1] : fac.name;
}
