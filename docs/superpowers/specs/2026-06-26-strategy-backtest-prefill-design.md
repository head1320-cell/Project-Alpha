# 전략 백테스트 원클릭 셋업 — 매크로 전략 → 백테스터 조건식 자동 구성

> 매크로 콕핏 05 Strategies(및 전략 상세 모달)의 "백테스트" 버튼을 누르면, 해당 전략에 맞게
> 백테스터의 모든 조건/설정이 자동으로 채워져 바로 RUN 할 수 있게 한다. 전략 유형별로
> 가장 충실한 표현을 선택하는 **하이브리드**. 유니버스는 국내 ETF 코드(시세 가용).

날짜: 2026-06-26 · 브랜치: `claude/keen-thompson-bdk3e8`

---

## 1. 배경 / 문제
현재 "백테스트" 버튼은 `asset_alloc`(현재 비중 고정 ETF 바스켓, 월 리밸런스)만 셋업한다.
동적 전략(모멘텀/타이밍/최적화)에는 부정확(buy&hold). 전략별로 백테스터를 **충실하게** 구성해야 함.

백테스터 표현력(탐색 결과):
- **조건식 경로**(`buy_conditions` + `expr`, `strategy_name="__custom__"`→"Condition"): 자유 산술식 지원 —
  `변화율_기간({종가},{252일})`(12개월 수익), `순위(...)<=N`(상위 N), 이동평균 타이밍, 월 리밸런스, custom_tickers.
- **asset_alloc**: 정적 바스켓 N개월 리밸런스(정적 전략에 정확).
- **최적화**(공분산): 조건식·정적바스켓으로 표현 불가 → 실제 엔진 필요.

## 2. 전략 유형 → 백테스터 표현 (하이브리드)

| 유형 | 전략 | 표현 | 편집성 |
|---|---|---|---|
| 모멘텀 13 | classic_dm·composite_dm·accel_dm·raa·gtaa·paa·vaa·faa·aaa·daa·bond_dynamic·managed_futures | **편집가능 조건식**(custom ETF + buy_conditions + 정렬 상위N + 월 리밸런스) | ✅ 보고 수정·RUN |
| 정적 2 | permanent·equal_weight | **asset_alloc** 바스켓(균등/고정) | ✅ 가중 편집 |
| 최적화 7 | risk_parity·hrp·min_var·max_div·max_sharpe·black_litterman·kelly | **충실 동적 엔진**(backtest_strategy를 백엔드 백테스트로 실행) | ❌ 조건 편집불가(배지 명시) |

유니버스: 전략의 US 티커를 **US_TO_KR로 국내 ETF 코드 매핑**(예 SPY→379800). 백테스터가 KR `daily_prices`에서
시세를 읽으므로 GCP 실데이터로 백테스트 가능(샌드박스는 mock).

## 3. 백엔드

### 3.1 신규 `src/engine/strategy_backtest_map.py`
전략 id → 백테스터 구성(mode + 파라미터)을 산출하는 단일 소스.
- `_MOMENTUM_SPEC: dict[sid, {conditions:[expr...], logic, sort_expr, sort_desc, max_tickers, universe:[US tickers]}]`
  — 13 모멘텀 전략의 조건식을 큐레이션(전략 핵심을 조건 언어로 충실히 표현, 근사는 명시).
  예) gtaa: universe=[SPY,EFA,IEF,PDBC,VNQ], conditions=[`{종가} >= 이동평균({종가},{200일})`], max_tickers=5(균등),
      classic_dm: universe=[SPY,EFA,AGG], sort=`변화율_기간({종가},{252일})` desc, cond=[`변화율_기간({종가},{252일}) >= 0`], max_tickers=1.
- `_STATIC = {"permanent","equal_weight"}`, `_OPTIMIZER = {"risk_parity","hrp","min_var","max_div","max_sharpe","black_litterman","kelly"}`.
- `backtest_config(sid, market) -> dict`:
  - momentum → `{mode:"conditions", universe_codes:[KR codes], buy_conditions:[{expr}...], buy_logic, sort_expr, sort_desc, max_tickers, rebalance_period:"monthly", note}`
  - static → `{mode:"asset_alloc", basket:[{ticker,name,weight_pct}], rebalance_months:3, note}` (build_detail 보유 재사용)
  - optimizer → `{mode:"engine", engine_strategy:sid, universe_codes:[KR codes], rebalance_months:1, note}`
  - 공통: `id, name, family, market, sources`.

### 3.2 최적화 전략 충실 실행 — `screen_to_backtest` 어댑터
`strategy_name == "tactical:<sid>"` 인식 → KIS 엔진 대신 어댑터 실행:
- `run_tactical_backtest(sid, mk, start, end, capital) -> ScreenToBacktestResult 형태`:
  - 기간(start..end)을 개월수로 환산 → `strategy_profiles.backtest_strategy(sid, mk, months)` 실행(이미 동적·시점평가).
  - 반환 곡선·월수익에서 통계 산출: total_return·CAGR·MDD·연변동성 + **Sharpe·Sortino·Calmar**(월수익→연율), 거래기반 통계(승률·손익비)는 N/A(배분형).
  - `statistics`, `equity_curve`(곡선), `benchmark`(선택: 기존 _compute_benchmark 또는 생략), `trades:[]`, `data_source`.
- `_screen_to_backtest_core`에서 `strategy_name.startswith("tactical:")` 분기 → 어댑터 반환(스트리밍/유너리 동일).
- 결과 셰이프를 기존 result UI가 그대로 렌더 → 단일 렌더러 유지.

### 3.3 엔드포인트 `src/api/macro_routes.py`
`GET /macro/strategy/{sid}/backtest-config?market=us|kr` → `backtest_config`. 알 수 없는 sid → 404.

## 4. 프론트엔드

### 4.1 `screenerApi.ts` + `macroData.ts`
- 타입 `StrategyBacktestConfig`(mode union + 필드). `analysisApi.macroStrategyBacktestConfig(sid, market)`. `loadStrategyBacktestConfig` lazy.
- `ScreenToBacktestBody`/handoff: 이미 buy_conditions·custom_tickers·asset_alloc·strategy_name·rebalance_period 지원(무변경).

### 4.2 `macroHandoff.ts` 확장
기존 basket-only → `MacroBacktestHandoff`(mode + 전체 구성: strategyName, market, mode, universeCodes, buyConditions, buyLogic, sortExpr, sortDesc, maxTickers, rebalance, basket, engineStrategy). 하위호환 유지(기존 필드 optional).

### 4.3 버튼 동작 (StrategyCard·StrategyModal)
"백테스트" 클릭 → `loadStrategyBacktestConfig(sid, market)` → `setMacroHandoff(config)` → `router.push("/backtest")`.
(모달의 백테스트 버튼도 동일.)

### 4.4 `TerminalBacktester.tsx` 적용
`getMacroHandoff()` 마운트 감지 → mode별 상태 셋업:
- **conditions**: `buy.conditions = buyConditions.map(expr→ {direct:true, expr})`, `buy.logicExpr=buyLogic`,
  `buy.primarySort/sortExpr` = sortExpr, `buy.maxStocks=maxTickers`, universe=custom(universeCodes),
  `rebalancePeriod="monthly"`, assetAlloc off. → 사용자가 조건 보고 수정 가능, RUN=Condition 전략.
- **asset_alloc**: 기존 경로(assetAlloc basket, etf100).
- **engine**: `strategy_name="tactical:<sid>"` + custom_tickers(universeCodes) + rebalance. RUN이 어댑터 실행.
  (조건 UI는 "이 전략은 최적화형 — 엔진 실행" 배지로 안내, 조건 비노출.)
- 배너: mode·전략명·유니버스 수 표기 + 해제.

## 5. 검증 (TDD)
### 5.1 단위 (`tests/test_strategy_backtest_map.py`)
- `backtest_config`: 22 전부 유효 mode 반환(momentum=conditions·static=asset_alloc·optimizer=engine), universe_codes 비어있지 않음(KR 코드), 알수없는 id→None.
- momentum: buy_conditions expr가 `factor_expr.parse_expr`로 파싱 통과(유효식), max_tickers>0.
- static: basket 합≈100.
- optimizer: engine_strategy==sid.
- `run_tactical_backtest`(어댑터): 결과에 statistics(total/cagr/sharpe/mdd/vol)·equity_curve(비어있지않음)·trades(리스트). 알수없는 sid 안전.
- `screen_to_backtest` 라우팅: `strategy_name="tactical:hrp"` → 어댑터 결과(통계 유효).
### 5.2 게이트
- ruff · `KIS_USE_MOCK=1 pytest`(577 + 신규) · tsc 0 · next build 16/16.
- 회귀 불변: 기존 백테스트 52거래 -8.1%(기존 전략 경로 무영향), 기존 macro 8탭·strategy modal.

## 6. 구현 순서 (안전 커밋)
1. `strategy_backtest_map.py`(매핑+모멘텀 조건 큐레이션) + `run_tactical_backtest` 어댑터 + `screen_to_backtest` 라우팅 + 엔드포인트 + 테스트(TDD). (커밋①)
2. 프론트: macroHandoff 확장 + screenerApi/macroData + 버튼 동작 + TerminalBacktester mode 적용 + 배너. tsc/build. (커밋②)
3. 검증·푸시. 트레일러 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` +
   `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`. 모델ID 금지.

## 7. 정직한 한계
- 모멘텀 조건식은 전략 핵심(모멘텀 랭킹·MA 타이밍)을 조건 언어로 옮긴 것 — 일부 정교한 로직(13612W 정확가중·
  카나리아 방어전환)은 근사. 배너/노트에 "조건식 변환(편집 가능)" 명시. 정확 동적실행은 최적화형 엔진 모드와 동일하게
  backtest_strategy로도 확인 가능(상세 모달).
- 최적화 엔진 모드: 거래기반 통계(승률·손익비)는 배분형이라 N/A. 곡선·수익·위험비율은 산출.
- 유니버스=국내 ETF 코드 → GCP 실시세서 실측. 샌드박스 mock은 절대수치 합성(구조·배선 검증).

## 8. 비범위 (YAGNI)
- 최적화 전략을 백테스터 조건 UI에서 편집 — 불가능(공분산 최적화). 엔진 모드로 충실 실행만.
- 벤치마크 자동(엔진 모드)은 선택 — 우선 곡선·통계. 추후 _compute_benchmark 연결 가능.

---

## 9. 구현 완료 (Implementation — ★기록★)
브랜치 `claude/keen-thompson-bdk3e8`. 2 커밋 + 푸시.
- `cb6ffef` 백엔드: `strategy_backtest_map.py`(backtest_config 22→mode + 모멘텀12 조건식 큐레이션 + run_tactical_backtest 어댑터) +
  `screen_to_backtest` "tactical:<sid>" 라우팅 + `GET /macro/strategy/{sid}/backtest-config` + `tests/test_strategy_backtest_map.py`(9, TDD).
  ★factor_expr 산술전용 → cond는 값식 + op=gte/rhs=0. laa는 타자산 MA 참조라 engine 모드(최적화7+laa=8).★
- `6516551` 프론트: macroHandoff(config 이식) + screenerApi/macroData 로더 + MacroCockpit(sid 전달) +
  page onTransplant(config fetch→handoff→/backtest) + TerminalBacktester applyMacroConfig(mode별) + 배너.

검증: pytest 586 passed/10 skipped(577+9), ruff, tsc 0, next build 16/16. E2E: tactical:hrp 라우팅(총47%·sharpe0.9·49pt),
모멘텀 조건식 parse 통과, 엔진/조건/자산배분 3모드 셋업 확인.

정직한 한계(개정): 모멘텀은 조건식 변환(편집가능, 일부 근사) — 정확 동적실행은 상세모달 backtest_strategy·엔진모드와 동일.
엔진모드 거래통계(승률·손익비)는 월기반. 유니버스=국내 ETF 코드 → 실측은 GCP. mock 절대수치는 합성.
