# 매크로 콕핏 — 상관관계 추이 · 마켓타이밍 · 국면 궤적 (07/08 탭 + Regime 강화)

> 매크로 탭의 두 핵심 목적("자산배분 마켓타이밍 시점 분석", "자산별 상관관계 추이")을
> 현 5개 API(BOK·FRED·KIS·DART·KRX) 데이터만으로 구현. 새 외부 데이터 불필요 —
> `daily_closes`(etf_prices) + 기존 매크로 시계열(MacroCollector)이 이미 손안에 있음.

날짜: 2026-06-25 · 브랜치: `claude/keen-thompson-bdk3e8`

---

## 1. 배경 / 문제

콕핏(6탭)은 "현재 국면 → 전략 추천"까지는 하지만 자산배분 의사결정의 두 축이 비어 있다:
- **마켓타이밍**: 전략들이 내부적으로 200일선·12개월 모멘텀·카나리아·수익률곡선을 쓰지만,
  "지금 위험자산에 들어갈 때인가?"를 한 화면에 종합한 곳이 없다.
- **상관관계**: 자산 간 상관이 콕핏 어디에도 없다. 그러나 `risk_allocations.py`가 이미 공분산을 계산하고
  (`_cov_to_corr` 보유), `daily_closes`로 일간 수익률이 다 있다 — 데이터는 있는데 안 보여주고 있다.

13개 매크로 엔드포인트·6개 콕핏 탭에 상관/타이밍은 전무(확인). 둘 다 신규이고 명시된 목적에 직접 대응.

## 2. 확장 유니버스 (13자산)
주식·채권·신용·실물·물가를 포괄 — 상관 분석에 이상적. 전부 `US_UNIVERSE`·`US_TO_KR` 존재(US⇄KR 토글).

`SPY`(미 대형) `QQQ`(나스닥) `IWM`(소형) · `EFA`(선진) `EEM`(신흥) · `TLT`(장기국채) `IEF`(중기국채) ·
`LQD`(IG회사채) `HYG`(하이일드) · `GLD`(금) `PDBC`(원자재) · `VNQ`(리츠) · `TIP`(물가채)

## 3. 기능 명세

### 3.1 07 Correlations — `/macro/correlations`
일간 수익률(`daily_closes`, 룩백 ~252)에서 산출. 반환:
- `matrix`: `{tickers, labels, values: number[][]}` — 13×13 상관행렬(대칭·대각1·[-1,1]).
- `pairs`: 롤링 60일 상관 시계열 5쌍 — `[{key,label, series:[{t,corr}]}]`:
  ★`SPY-TLT`(주식-장기채 = 헤지 여부, 2022 음→양 전환의 핵심)★, `SPY-GLD`, `SPY-PDBC`, `SPY-EEM`, `SPY-HYG`.
- `avg_corr`: 평균 페어상관 시계열 `[{t,corr}]` — **분산 국면**(1 근접=상관붕괴/위기, 낮음=건강한 분산).
- `stock_bond_now`: `{corr, verdict}` — 현재 SPY-TLT 상관 + "헤지 작동/동조화" 판정.
- `sources`: `{prices: bool}`.

### 3.2 08 Timing — `/macro/timing`
위험 온/오프 종합 + 자산별 추세. 반환:
- `composite`: `{score: 0~100, label}` — risk-on(≥60)/neutral/risk-off(≤40).
- `components`: 5종 서브점수(가중) `[{key,label,value,score,weight}]` — 합 weight=100:
  · `breadth` **위험자산**(SPY·QQQ·IWM·EFA·EEM·VNQ·HYG) 200일선 상회 비율(25) · `mom_breadth` 같은 위험자산 12개월 양(+) 모멘텀 비율(20)
  · `yield_curve` T10Y2Y(정상=온, 역전=오프)(20) · `credit` HY 스프레드(타이트=온)(20) · `vix` VIX 수준(저=온)(15).
- `history`: 월별 종합점수 `[{t,score}]` — 5 구성요소 전부 월간 시계열 보유(FRED 시리즈 + 일간 워킹) → 추이.
- `assets`: 자산별 추세표 `[{ticker,label, vs_ma200_pct, mom_12m, dist_52w_high, rsi, trend}]`
  (trend: 200일선 상회 & 12M>0 → 상승, 둘 다 반대 → 하락, 혼합 → 중립).
- `sources`: `{prices, fred}`.

### 3.3 C1 국면 궤적 — `/macro/regime-trajectory`
Regime 탭은 *현재 점*만 보여줌 → 경로 추가. regime_analyzer 내부공식 대신 **테마-z 프록시**(투명·결합도↓):
- `path`: 최근 18개월 `[{t, growth, inflation, quadrant}]`:
  · growth(t) = 평균 z(INDPRO, GDPC1, PAYEMS, **−**UNRATE) at month t  (z = (value[t]−mean_5y)/std_5y)
  · inflation(t) = 평균 z(CPIAUCSL, T10YIE, DCOILWTICO, KR_CPI) at month t
  · [-1,1] 클램프(스캐터 도메인 일치). 분면 매핑은 부호로(성장≥0&물가≥0=과열 등).
- `transitions`: 분면 전환 `[{t, from, to}]` — 언제 국면이 바뀌었나(타임라인).
- 데이터: `MacroCollector.collect_all().series`의 월간 values + mean_5y/std_5y (이미 존재).

## 4. 아키텍처 (격리 · 기존 패턴 보존)

### 4.1 신규 백엔드 `src/engine/macro_analytics.py`
전략 엔진과 분리된 분석 모듈. numpy 사용, `daily_closes`/`monthly_closes`/`MacroCollector` 재사용.
- `_aligned_returns(tickers, mk, lookback) -> (names, np.ndarray)` — 정렬 일간수익률(risk_allocations와 동형, 재사용 가능하면 import).
- `correlation_panel(mk) -> dict` — matrix + pairs(롤링) + avg_corr + stock_bond_now + clusters.
- `_rolling_corr(a, b, window=60) -> list` — 두 수익률 시계열의 롤링 상관.
- `timing_panel(mk) -> dict` — composite + components + history + assets.
- `_asset_trend(t, mk) -> dict` — 200일선/12M/52주고점/RSI/판정.
- `regime_trajectory() -> dict` — path + transitions (테마-z 프록시).
- 견고성: 데이터 부족 시 빈 시계열/`null` + sources=false (합성 금지, 정직 라벨).

### 4.2 엔드포인트 `src/api/macro_routes.py`
`GET /macro/correlations?market=`, `GET /macro/timing?market=`, `GET /macro/regime-trajectory`.
각 try/except + logger.exception + 안전 메시지(기존 패턴).

### 4.3 프론트
- `screenerApi.ts` analysisApi: `macroCorrelations(market)`·`macroTiming(market)`·`macroTrajectory()` + 타입
  (CorrMatrix/CorrPair/TimingPanel/TrendRow/TrajectoryPoint).
- `lib/macroData.ts`: `loadCorrelations(mk)`·`loadTiming(mk)`·`loadTrajectory()` lazy(탭 진입 시 — 계산 무거워 코어 분리).
- 신규 `components/macro/analyticsParts.tsx`(cockpitParts가 이미 커서 분리):
  · `CorrMatrix`(발산색 히트맵 그리드) · `RollingCorrChart`(recharts 멀티라인, 주식-채권 강조 + 0선) ·
    `AvgCorrChart`(영역 + 고상관 위험구간 음영) · `ComponentBars`(타이밍 신호별 기여) ·
    `TimingHistory`(종합점수 라인 + 온/오프 임계선) · `TrendTable`(자산별, 상승=녹·하락=적) ·
    `RegimeTrajectory`(RegimeScatter에 path 폴리라인 + 화살표 오버레이).
- `MacroCockpit.tsx`: 탭 2개 추가(07 Correlations·08 Timing) + RegimeTab에 궤적/전환 타임라인.
  ArcGauge는 타이밍 게이지로 재사용.

## 5. 검증 (TDD)

### 5.1 단위 (`tests/test_macro_analytics.py` 신규, TDD red→green)
- `correlation_panel`: matrix 대칭·대각=1·전부[-1,1], pairs 5쌍 존재, avg_corr 길이>0, stock_bond_now.verdict ∈ {헤지/동조}.
- `_rolling_corr`: 길이 = obs−window+1, 값 [-1,1].
- `timing_panel`: composite.score ∈ [0,100], components 5개 가중합=score, assets 13행 필드 완비, history 길이>0.
- `_asset_trend`: trend ∈ {상승,하락,중립}, rsi ∈ [0,100].
- `regime_trajectory`: path 분면 ∈ 4국면, growth/inflation ∈ [-1,1], transitions from≠to.
- 결정론(mock 동일입력 동일출력), 데이터부족 폴백(빈 시계열·sources=false).

### 5.2 통합·게이트
- 엔드포인트 3개 200 응답(mock), 콕핏 8탭 렌더.
- `ruff` · `KIS_USE_MOCK=1 pytest`(기준 555 + 신규) · `tsc 0` · `next build`(16/16, /macro).
- 회귀 불변: 기존 6탭·22전략·555 테스트.

## 6. 구현 순서 (안전 커밋 단위)
1. `macro_analytics.py` + `test_macro_analytics.py`(TDD) + 엔드포인트 3개. 백엔드 검증. (커밋①)
2. 프론트 `analyticsParts.tsx` + `screenerApi.ts`/`macroData.ts` + 콕핏 07/08 탭 + Regime 궤적. tsc/build. (커밋②)
3. 검증·푸시(`claude/keen-thompson-bdk3e8`). 커밋 트레일러:
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`. 모델ID 커밋 금지.

## 7. 정직한 한계
- 일간 ~400봉(`_daily_df` 600일)이라 롤링 상관·타이밍 추이는 **~18개월** — 장기 추이는 GCP 실데이터/KRX 백필에서.
- mock 가격은 합성 → 상관·타이밍 절대수치 비현실적(구조·부호·로직은 검증). **실 상관/타이밍은 실시세에서.**
- 국면 궤적은 테마-z 프록시(전체 regime_analyzer 공식 근사) — 투명성·결합도↓ 위한 의도된 단순화.
- VIX/HY/수익률곡선은 FRED 월간(키 없으면 결정론적 mock). 일중·실시간 아님(자산배분 타이밍엔 충분).

## 8. 비범위 (YAGNI)
- 상관 클러스터 시각화(HRP 재사용) — 가치 있으나 별도 viz 필요, 후속 후보.
- 수급(외국인·기관) 기반 타이밍 — price_factors_store에 있으나 별도 데이터정합 필요, 후속.
- 인트라데이/실시간 상관, lead-lag 인과분석, 상관 예측 — 범위 외.

---

## 9. 장기 데이터 DB 준비도 검토 + 한계 개선 (★이번 구현에 포함★)

### 현황 (검토 결과)
적재 substrate는 완비:
- `daily_prices`(UPSERT write-back `ingest_df_to_db`) + `load_ohlcv_unified`(DB→KIS→mock 자가워밍) +
  `prewarm_ohlcv(tickers, days=3650, 병렬·재개가능)` + 시작 데몬 `_prewarm_ohlcv_bg`.

갭 2가지:
- **갭1**: `_prewarm_ohlcv_bg`가 KR 주식(kospi200/kosdaq150/all_listed)만 적재 — 크로스에셋 ETF 13종 미적재.
- **갭2**: `etf_prices._daily_df`가 600일 고정 요청 — DB 깊이를 안 씀(롤링 ~18개월 한계의 원인).

### 개선 (구현 포함)
- **etf_prices 윈도우 확장**: `_daily_df`를 `_HISTORY_DAYS = env("ETF_HISTORY_DAYS", 1825)`(~5년) 요청으로.
  `daily_closes`/`monthly_closes`는 전체 시계열을 캐시하고 tail 반환 → 호출자가 깊은 history 사용 가능.
  · 안전: 기존 22전략은 tail(`_ret`는 끝에서 인덱스, monthly_closes 기본 n=14)만 쓰므로 불변. risk_allocations는
    `_COV_LOOKBACK=252`로 캡 → 불변. mock 생성도 5년치(결정론) → **샌드박스 롤링차트도 길어져 검증 강화**.
- **ETF 유니버스 prewarm**: `prewarm_etf_universe()`(US_TO_KR의 KR 코드 13종 → `prewarm_ohlcv`) 추가 +
  `_prewarm_ohlcv_bg`에 gated 추가(env `OHLCV_PREWARM_ETF`). KR ETF는 도메스틱 경로로 적재 → DB 누적.
- 결과: DB가 쌓일수록(prewarm·write-back) 롤링 상관·타이밍 추이가 **자동 장기화**. 한계가 시간이 지나며 해소.

### 검증 추가
- etf_prices 윈도우 확장 후 기존 22전략 산출 불변(회귀), 분석 시계열 길이↑ 확인.
- `prewarm_etf_universe` mock no-op·키 있을 때 KR 코드 대상 확인(스레드 안전·재개).

---

## 10. 구현 완료 (Implementation — ★기록★)
브랜치 `claude/keen-thompson-bdk3e8`. 2 커밋 단위 + 푸시 완료.
- `1db3b1d` 백엔드: `src/engine/macro_analytics.py`(correlation_panel/timing_panel/regime_trajectory + 헬퍼) +
  엔드포인트 3개 + `tests/test_macro_analytics.py`(11, TDD red→green). 장기 DB: etf_prices 윈도우 ~5년 확장 +
  `prewarm_etf_universe()` + main_api gated 데몬.
- `2430c11` 프론트: `analyticsParts.tsx`(CorrMatrix·RollingCorrChart·AvgCorrChart·ComponentBars·TimingHistory·
  TrendTable·RegimeTrajectory) + 콕핏 07/08 탭 + Regime 궤적 + screenerApi/macroData lazy 로더 + globals.css mca-*.

검증(완료): `KIS_USE_MOCK=1 pytest` **566 passed/10 skipped**(555+11), ruff 통과, tsc 0, next build 16/16(/macro 24kB).
E2E: /correlations 13자산·롤링 SPY-TLT 178점·평균상관, /timing 종합+5신호+18M추이+13자산추세, /regime-trajectory 18M 경로.
장기 DB 개선 확인: daily_closes 400→1304(~5년) → 롤링 추이 자동 장기화, DB 누적 시 추가 장기화.

정직성 유지: mock 상관/타이밍 절대수치는 합성(구조·부호·로직 검증) — 실값은 GCP 실시세. 출처 배지 표기.
