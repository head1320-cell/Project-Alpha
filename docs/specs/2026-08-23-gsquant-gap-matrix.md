# GS Quant 아키텍처 벤치마크 — 갭 매트릭스 (§39 Phase 0 산출물)

> 출처: `Project_Alpha_GSQuant_Architectural_Benchmark.md`
> §34 Phase 0 · §39 가 요구한 **프로덕션 코드 수정 전 감사**.
> 원칙: GS Quant 를 **복제하지 않는다**(§3·§35). 설계 원칙만 차용한다.

## 0. 한 문장

> 기능은 거의 다 있다. **없는 것은 그 기능들이 공유해야 할 도메인 객체**다 —
> 특히 팩터 리스크 모델의 **조립**(Σ_asset = BΣ_fB' + D)이 비어 있었다.

## 1. 갭 매트릭스

| 도메인 원시객체(§39) | 상태 | 근거 (파일·실측) |
|---|---|---|
| **ResearchContext**(S1) | ⚠️ 분산·중복 | `as_of` 인자·`pit_store`·`pit_macro.derive_usage` 는 있으나 `code_version()`/`MODEL_VERSION`/`ENGINE_VERSION` 이 **저장소마다 따로 정의**(`regime_snapshots.py:63,144` · `company_snapshots.py:97,165`) |
| **Dataset**(S2) | ⚠️ 부분 | `ohlcv_loader` · `fundamentals_store` · `dart_history` · `regime_analyzer.collector`(61계열) · `universe_select` — 도메인별 인터페이스는 있으나 **공통 context/provenance 규약이 없다** |
| **Instrument**(S3) | ❌ 없음 | ticker 가 곧 정체성. `stock_master`·`ticker_universe` 는 이름·그룹만 갖는다. `instrument_id`·`valid_from/valid_to`·`listing_status`·`corporate_action_state` 없음 |
| **Position/PositionSet**(S4) | ❌ 없음 | `holdings: dict[str, float]` 가 라우트마다 반복 |
| **Portfolio**(S5) | ❌ 없음 | weights 배열. `PortfolioDecisionState` 는 설계 문서상 개념으로만 존재 |
| **Factor**(S6) | ✅ 있음 | `factor_exposure.FACTOR_PROXIES` 9팩터(각 59개월) · `allocation_studio.effective_number_of_bets` |
| **RiskModel**(§13) | ❌ **조립 없음** | `factor_risk` 는 **분해**만 한다. Σ_asset 은 여전히 `_cov(R)*252` 표본 공분산(`allocation_studio.py:262`) |
| **ConstraintSet**(S7) | ⚠️ 부분 | `constrained_opt.Constraints` 11종(가중·그룹·회전율·베타·현금·gross/net). per-constraint `unit`·`scope`·`source`·`reason` 없음 |
| **BacktestEngine**(§17) | ✅ 있음 | P0 에서 프로세스 격리·텔레메트리 12항목·취소·재시도·고아 복구 |
| **BacktestResult**(§22) | ⚠️ 부분 | `equity_curve`·`statistics`·`trades`·`monthly_returns` 는 있고 `factor_exposures`·`regime_exposure` 는 P3-2 가 라우트로 낸다 |
| **AnalyticsProcessor**(§30) | ⚠️ 부분 | 라우트가 엔진 결과를 가공한다 — 별도 계층은 없음 |
| **InvestmentThesis**(§29) | ✅ 있음 | `company_thesis`(주장·근거·촉매·kill 조건 + 3단 분류) |
| **CompanySnapshot**(§24) | ✅ 있음 | `company_snapshots` — 12섹션 불변 스냅샷 |
| **Mimicking portfolio**(§14) | ❌ 없음 | `instrument_selector.EXPOSURES` 가 재료로 있다 |

## 2. 이 감사가 반증한 것

- "Company 언더라이팅이 없다" — **있다**(§24·§25·§26·§27·§28·§29 전부 P2 에서 닫힘).
- "PIT 개념이 없다" — **있다**(`pit_store`·`pit_macro.ResearchUsage`·`derive_usage`).
- "팩터가 없다" — **있다**(9팩터, 이름 있는 경제 팩터).

문제는 조각이 없는 것이 아니라 **조각들이 공유 객체로 묶이지 않은 것**이다.
이것은 벤치마크 문서 §1 의 진단과 정확히 같다.

## 3. 첫 수직 슬라이스 — §13 팩터 리스크 모델

★재료도 주입점도 이미 있다★

| 필요한 것 | 어디에 |
|---|---|
| B (자산×팩터 노출) | 자산별 결합 OLS — `factor_exposure` 의 팩터 계열 사용 |
| Σ_f (팩터 공분산) | `reverse_stress.factor_covariance` (단위 정규화 완료) |
| D (고유분산) | 회귀 잔차, 자유도 보정 |
| 주입점 | `allocation_studio.optimize(s_override=…)` — **P2.5 가 만들어 둠** |

### 실측 (4자산 · 9팩터 · 59개월 · 자산별 dof 49)

| 자산 | 모델 월변동성 | 표본 월변동성 | 팩터 설명 |
|---|---|---|---|
| 005930 | 8.45% | 7.89% | 19.8% |
| 000660 | 8.41% | 7.82% | 13.9% |
| 035420 | 10.26% | 9.58% | 20.3% |
| 005380 | 8.54% | 7.95% | 16.8% |

**최소 고유값 6.68e-03 > 0 — 양정부호.** `BΣ_fB'` 는 항상 PSD 이고 D 는 양의
대각이므로 합은 **항상 PD** 다. 표본 공분산은 자산수 > 관측수 에서 특이행렬이
되지만 이 모델은 그렇지 않다 — §13 이 "more scalable" 이라 한 근거다.

★결합 베타를 쓴다★ 단변량이면 상관된 팩터의 공통 변동을 중복 흡수한다
(P3-4 에서 그 결과가 설명분산 **103,809%** 였다).

## 4. 다음 후보 (승인 필요)

| 순위 | 항목 | 비고 |
|---|---|---|
| 1 | **S1 ResearchContext** | 문서의 Priority S. 모든 엔진을 가로지르는 리팩터라 별도 승인 필요. 좁은 버전(중복된 `code_version` 통합)부터 가능 |
| 2 | **Position/PositionSet/Portfolio** | Phase 6. `holdings` dict 를 대체 |
| 3 | **§14 팩터 복제 바스켓** | mock 에서 ETF 상관이 0(SPY-VTI 0.037)이라 품질 검증 불가 — 구조만 가능 |
| 4 | **§15 ConstraintSet 구조화** | 현 `Constraints` 로 동작 중이라 급하지 않음 |
| 5 | **S3 Instrument** | 생존편향 정합성에 필요하나 `tickers_asof` 가 부분 대체 중 |
