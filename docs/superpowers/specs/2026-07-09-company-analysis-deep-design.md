# 기업분석 탭 심화 — 실무(FAS/DD) 관점 대개편 설계

날짜: 2026-07-09
상태: 승인됨 (사용자, 실무 교정판 기준)
근거: 사용자 제공 Gemini 컨설팅 추천(7라운드) + AX 파트너 실무 검증으로 우선순위 교정

---

## 1. 배경 / 목표

현재 `/insights`(CompanyCockpit 7탭)는 요약 조회에는 성공적이나, 전문가가 "이 숫자가 왜
나왔지?"라고 파고들 드릴다운이 없음(단일 내재가치, 블랙박스 점수, 표 나열).

목표: 회계법인 재무자문(FAS)·실사(DD) 현업이 매일 쓰는 산출물을 3개 탭에 내재화한다.
- Valuation: 단일 값 → **설득 가능한 밴드**(Football Field)와 **방어 가능한 가정**(샌드박스+민감도)
- Financials: 표 나열 → **QoE(이익의 질)·운전자본·자본배치** 중심의 회계학적 스토리
- Risk: 블랙박스 점수 → **Altman/Beneish 분해·커버리지 추이·금리 스트레스** 드릴다운

## 2. 범위

### 포함 (이번 패스)
| 탭 | 산출물 | 실무 용도 |
|---|---|---|
| Valuation | Football Field 차트 | 밸류에이션 보고서 표준 1페이지 |
| Valuation | 가정 샌드박스 (Rf/β/ERP/g/연수 슬라이더 + 출처 배지) | QC에서 가정 출처 없는 밸류에이션은 반려 |
| Valuation | Ke×g 민감도 매트릭스 5×5 | DCF 보고서 필수 부록 |
| Valuation | Comps 테이블 (피어 상대가치 매트릭스 + 중간값 + 암시가) | 실무 최다 사용 표 |
| Financials | QoE: NI vs OCF 10년 + 발생액 추세 + Red Flag 배지 | 재무실사(FDD)의 본체 |
| Financials | 운전자본(NWC) 추이: NWC·NWC/매출 | DD 표준 챕터, 가격조정 핵심 |
| Financials | 자본배치 워터폴 (OCF→CapEx/배당/부채상환/잔여) | 자본 규율·거버넌스 분석 |
| Financials | 듀폰 3단 분해 10년 (보조 섹션) | ROE 드라이버 설명 |
| Risk | Altman Z X1~X5 기여 분해 | "왜 이 점수인가" |
| Risk | Beneish 실측 8지수 (재계산 + 지수별 라벨) | 포렌식 스크리닝 드릴다운 |
| Risk | 커버리지 추이: 이자보상배율·순부채/EBITDA 10년 | 차입 실사·한계기업 판별 |
| Risk | 금리충격 스트레스 (+100/200/300bp → 커버리지·DCF) | 금리 민감 리스크 |

### 제외 (정직한 사유 명시)
- **컨센서스/12M Fwd/어닝리비전/애널리스트 TP**: FnGuide 등 유료 벤더 필요.
- **글로벌 피어**(마이크론 등): 해외 시세·재무 미연동. Comps는 국내 피어만.
- **Normalized EBITDA(일회성 조정)**: DART 주석 데이터 없이는 날조. UI에 "주석 연동 전
  미제공" 표기. (주석 파싱·RAG는 별도 대형 과제)
- **국면 반영 팩터 하이라이트**: 퀀트 운용 관점 — 딜·실사 도구 아님. 매크로 탭과 중복.
- **밸류체인 노드맵 / M&A·LBO 시뮬레이터 / One-Click 보고서 / 주석 NLP**: 별도 과제.

## 3. 아키텍처

### 3.1 백엔드 — `src/engine/company_analytics.py` (신규, 순수 함수 모듈)
데이터 원천: `financials_history`(10년 연간, 원 단위), `fundamentals_store`/`price_factors_store`
팩터, `ohlcv_loader`(주가), `valuation_models.ValuationParams/unified`(기존 재사용),
macro의 국고채 10년(Rf). DB 접근은 기존 헬퍼(`load_history` 등) 재사용 — 신규 SQL 최소화.

함수 (전부 순수 — 입력을 인자로 받거나 얇은 로더 분리, dict 반환):

```
resolve_default_params(code) -> {rf, rf_source, beta, beta_source, erp, g, years}
    # Rf: ECOS 국고채10년 실시간(macro 캐시), 실패 시 0.035 + source="기본값"
    # β: price_factors beta_1y, 없으면 1.0 + source="기본값"

valuation_sandbox(code, price, overrides) -> {
    unified: {value, gap_pct, verdict, models:[{model, value, available, error}]},
    assumptions: [{key, label, value, source}],
    sensitivity: {ke_axis[5], g_axis[5], grid[5][5], current_price}}
    # grid = 가중(RIM/DCF/DDM) 내재가치.
    # ke_axis = 기준 Ke ± {−1.0, −0.5, 0, +0.5, +1.0}%p, g_axis = 기준 g ± 동일 간격
    # (단 g < ke − 0.5%p 제약 — 영구성장률이 할인율에 근접하면 TV 발산, 해당 칸은 null+사유)

football_field(code, price) -> {bands: [
    {id:"dcf", label, lo, hi, mid, note},      # Bear~Bull (g 1~3%, ERP 7~5%)
    {id:"rim", ...}, {id:"ddm", ...(무배당 → available:false, note:"무배당")},
    {id:"w52", lo=52주최저, hi=52주최고},
    {id:"graham", 점 밴드(lo=hi=그레이엄넘버)},
    {id:"peer_per", lo/hi = 피어 PER 25/75분위 × 자사 EPS},
    {id:"peer_pbr", lo/hi = 피어 PBR 25/75분위 × 자사 BPS}],
    current_price}

comps_table(code) -> {rows: [{code, name, mcap, per, pbr, ev_ebitda, roe, op_margin,
    rev_growth}], median_row, implied: {per_based, pbr_based, ev_ebitda_based}}
    # 피어 = 기존 피어 로직(동일 섹터) 재사용, 팩터는 ffl: 스냅샷에서 벌크.

financial_deep(code) -> {
    qoe: {years[], ni[], ocf[], gap_pct[], accruals[], red_flags:[{rule, msg, severity}]},
    nwc: {years[], nwc[], nwc_to_rev_pct[]},
    waterfall: {years[], ocf[], capex[], dividends[], debt_delta[], residual[],
                note:"자사주 매입 데이터 미보유 — 항목 제외"},
    dupont: {years[], net_margin[], asset_turnover[], leverage[], roe[]},
    roic_wacc: {roic, wacc, spread, verdict}}

risk_deep(code, price) -> {
    altman: {z, zone, components:[{id:"x1".."x5", label, value, weight, contribution}]},
    beneish: {m_score, flag, indices:[{id, label, value, basis:"real"|"approx"|"neutral"}]},
    coverage: {years[], interest_coverage[], net_debt_to_ebitda[]},
    rate_stress: {rows:[{shock_bp, interest_coverage, wacc, dcf_value, dcf_gap_pct}]}}
```

수식·규칙 (핵심만):
- **민감도 grid**: 기존 `unified` 평가를 (ke, g) 25조합으로 재실행. DDM 무배당 시 가중 재정규화
  (기존 evaluate와 동일 규칙).
- **QoE Red Flag 규칙** (rule 기반, 각 severity warn|bad):
  R1 `OCF < NI` 3년 연속 → "보고이익이 현금으로 뒷받침되지 않음"
  R2 발생액(NI−OCF)/자산 3년 상승 추세 → "발생액 누적 상승 — 이익의 질 저하 신호"
  R3 NWC/매출 3년 연속 상승 → "운전자본 잠김 심화 — 현금전환 악화"
- **NWC** = 유동자산 − 유동부채 (연도별). NWC/매출 = NWC/revenue.
- **워터폴**: OCF − CapEx − 배당(dps×주식수) − 부채상환(총부채 감소분, 증가면 조달로 표기)
  = 잔여현금. 자사주 항목 없음(주석 명시).
- **듀폰**: NI/매출 × 매출/자산 × 자산/자본 = ROE. 테스트로 곱=ROE 검증.
- **Altman 분해**: 기존 fundamentals_store 공식과 동일 X1~X5, contribution = 계수×값.
- **Beneish 8지수** (당년/전년 financials_history):
  실측: GMI=(GM₋₁/GM), SGI=(rev/rev₋₁), LVGI=((TL/TA)/(TL/TA)₋₁), TATA=(NI−OCF)/TA
  근사: AQI (비유동자산 질 — PPE 미보유로 (1−CA/TA) 비율 근사, basis:"approx")
  중립(1.0): DSRI(매출채권 無), DEPI(감가상각 無), SGAI(판관비 無) — basis:"neutral"
  M = −4.84 +0.92·DSRI +0.528·GMI +0.404·AQI +0.892·SGI +0.115·DEPI −0.172·SGAI
      +4.679·TATA −0.327·LVGI  (원 논문 계수)
  flag: M > −1.78 → "조작 위험 신호". 전년 데이터 없으면 available:false(정직).
- **커버리지**: 이자보상배율 = 영업이익/이자비용(이자비용 = 총부채×금리 근사, 근사 라벨).
  순부채/EBITDA = (총부채−현금근사)/(영업이익+감가근사) — 기존 팩터 공식 재사용, 연도별.
- **금리 스트레스**: shock ∈ {+100,+200,+300bp} → 이자비용′=총부채×(기준금리+shock),
  커버리지′ 재산출; WACC′=WACC+shock×(부채비중) 근사 → DCF 재평가.

### 3.2 API — `src/api/company_routes.py` (신규, main_api에 등록)
- `GET /api/v1/company/{code}/valuation-sandbox?rf=&beta=&erp=&g=&years=&price=`
  → valuation_sandbox + football_field + comps_table (Valuation 탭 1콜)
- `GET /api/v1/company/{code}/financial-deep` → financial_deep
- `GET /api/v1/company/{code}/risk-deep?price=` → risk_deep
- 에러: logger.exception + 안전 메시지(기존 관례). 종목 미존재 404.

### 3.3 프론트 — Cockpit 탭 컴포넌트 분리
- `components/insights/ValuationTab.tsx` — Football Field(SVG 가로밴드) + 가정 패널
  (슬라이더 5개, 출처 배지, "실측 기본값 복원" 버튼) + 민감도 히트맵(5×5, 현재가 대비
  저평가 칸 강조) + Comps 테이블(중간값 행 + 암시가 3행)
- `components/insights/FinancialsDeepTab.tsx` — QoE 오버레이 차트 + Red Flag 배지 +
  NWC 추이 + 워터폴 + 듀폰(접이식 보조)
- `components/insights/RiskDeepTab.tsx` — Altman 기여 바 + Beneish 8지수 표(basis 라벨)
  + 커버리지 추이 + 스트레스 표
- CompanyCockpit.tsx는 탭 렌더 분기만 유지(기존 lazy 패턴: 탭 진입 시 1콜). 기존
  Valuation/Financials/Risk 탭의 기존 콘텐츠는 새 컴포넌트 하단에 보존(정보 손실 없음).
- 차트: 기존 관례대로 자체 SVG (외부 라이브러리 도입 없음). API 클라이언트는
  `lib/screenerApi.ts`의 companyApi에 3메서드 추가.

## 4. 정직성 규칙 (전 산출물 공통)
- 산출 불가 항목은 숨기지 않고 `available:false + note(사유)` — 예: DDM 무배당,
  Beneish 전년 무데이터, 자사주 미보유, 이자비용 근사.
- mock 모드(KIS_USE_MOCK=1)에서도 결정론 작동(개발/테스트), 실데이터 시 자동 전환.
- 근사값에는 반드시 "근사" 라벨 (이자비용, AQI 등).

## 5. 테스트 전략 (TDD)
- `tests/test_company_analytics.py`: in-memory SQLite에 합성 financials_history 적재 →
  듀폰 곱=ROE, NWC 계산, 워터폴 항등(OCF−지출합=잔여), QoE red flag 규칙 3종 발화/비발화,
  Beneish 지수 수식·중립 라벨·전년無→unavailable, Altman contribution 합=Z,
  민감도 grid 단조성(ke↑→가치↓, g↑→가치↑), football field 밴드 lo≤hi, 커버리지 스트레스
  방향성(shock↑→커버리지↓).
- API smoke: 3 엔드포인트 200 + 스키마 키 존재 (mock).
- 프론트: tsc 0, next build 통과.

## 6. 커밋 단위 (6)
1. company_analytics 코어 A: sandbox+민감도+football field+comps (+TDD)
2. company_routes /valuation-sandbox + ValuationTab UI
3. company_analytics 코어 B: financial_deep (+TDD)
4. FinancialsDeepTab UI
5. company_analytics 코어 C: risk_deep (+TDD) + /risk-deep
6. RiskDeepTab UI + 전체 검증(729+ 테스트·ruff·tsc·build) + CLAUDE.md + 푸시

## 7. 성공 기준
- Valuation 탭에서 가정 조정 → 내재가치·밴드·매트릭스가 즉시 재계산(1콜 왕복).
- 3탭 모두 mock에서 결정론 렌더, GCP 실데이터에서 실측 렌더(재무 10년 실선).
- 모든 불가 항목에 사유 표기(빈칸·가짜값 0).
- 기존 테스트 전부 통과 + 신규 TDD 통과, ruff/tsc/build 통과.
