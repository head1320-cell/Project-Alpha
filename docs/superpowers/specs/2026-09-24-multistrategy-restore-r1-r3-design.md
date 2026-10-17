# BG · 멀티전략 복원 R1~R3 — 등록된 실행 · 기존 배분 코드 · ★실제로 잰 네팅★

작성 2026-09-24 · 앞 프로그램 BF(`src/engine/multistrategy_availability.py`) ·
기록 `docs/HISTORY.md` 의 BG 항목(구현 후)

## 1. 왜

BF 가 멀티전략·리얼리즘 백테스트를 정직하게 비활성화했다 — 모듈 다섯
(allocator · strategy_registry · order_netting · macro_feed · regime_model)과
등록 전략의 수익률 테이블이 없어서다. 2026-06-10 스냅샷 이식 때부터 한 번도
존재한 적이 없다. 사용자가 복원을 설계부터 요청했다.

## 2. 사용자가 정한 것

| 결정 | 답 |
|---|---|
| 범위 | **R1 데이터·레지스트리 + R2 배분기 + R3 네팅**. R4(매크로·국면)는 다음 프로그램 |
| 전략·수익률 원천 | **저장된 백테스트 실행(`backtest_runs`)을 등록** |
| 네팅 | **실제로 잰다** |
| 보유 복원 | **등록 때 재실행 + 재현 검증** |

R4 를 미루는 이유: 엔진이 기대하는 `systemic_risk_score` 는 킬스위치 `auto_risk` 의
재료다(`lifecycle._monitor_regime_state` 가 *"지어낼 수 없어 비워 둔다"* 고 적었다).
그것을 만드는 순간 실거래 안전장치 하나가 무장된다 — CLAUDE.md §6 최우선 구역이다.

## 3. 감사가 찾은 것 (실측)

- **원래 설계는 캔버스 그래프 전략이었다** — `liquidity_capacity` 가 없는
  `strategies(graph_json)` 테이블을 읽는다. 그런데 그래프 전략을 저장하는 경로가 없고,
  프런트가 부르는 `/api/v1/strategies?active_only=true` 도 백엔드에 없다.
- **사분면 어휘가 갈린다** — 저장소 공용 명칭은 `Goldilocks·Reflation·Stagflation·
  Disinflation`(`regime_axes.quadrant`, *"Deflation 아님"*)인데 엔진은 `DEFLATION` 을
  기대한다. R4 몫이다.
- **`regime_change` 는 국면이 없으면 매일 리밸런싱한다** —
  `multi_strategy_backtest.py:259` 의 `or (policy == "regime_change" and current_regime
  is None)`. 국면 모델이 없는 지금은 조용히 일별 리밸런싱이 된다.
- **배분기가 실패하면 엔진은 말없이 직전 가중을 쓴다** — `if alloc_result.get(
  "available")` 가 거짓이면 초기 동일가중이 그대로 남는다.
- **네팅은 지어낸 수다** — 엔진이 `OrderNettingEngine` 을 만들고 **한 번도 부르지
  않는다**. 절감액은 `(회전율 × 1.5 − 회전율) × 요율` 이고 귀인 `netting_effect` 와 화면에
  실린다(수익률에는 안 더해진다).
- **저장된 거래는 앞 500건뿐이다** — 메인 엔진이 `trade_dicts[:500]` 를 **표시 없이**
  저장한다. 완전한 보유를 저장본에서 복원할 수 없다(이 설계는 재실행으로 우회하고,
  잘림 자체는 별건으로 기록만 한다).
- **스크리너 실행은 현재 데이터로 스크리닝한다** — 저장된 요청을 그대로 재실행하면
  유니버스가 달라질 수 있다.

## 4. 설계

### 4.1 R1 · 전략 레지스트리 — `src/engine/strategy_registry.py`

**테이블** (등록 시점 스냅샷 — 원천 실행은 불변)

- `strategy_registry` — `id INTEGER PRIMARY KEY AUTOINCREMENT`(`multibacktest_runs`
  관용구) · `name` · `source_run_id` UNIQUE · `is_active` · `is_mock_data` ·
  `is_pit_verified` · `symbols`(JSON) · `registered_at` · `repro`(JSON)
- `strategy_daily` — `strategy_id` · `trade_date` · `daily_return` · `holdings`
  (JSON `{ticker: weight}`) — PK `(strategy_id, trade_date)`

**등록 `register(run_id, name)`**

1. `backtest_runs` 의 **completed** 실행만 받는다. 아니면 사유와 함께 거절.
2. **같은 경로로 재실행** — 저장 결과의 `symbol_results` 종목과 `input_snapshot` 의
   파라미터로 `screener_routes` 코어가 쓰는 `run_backtest` 인자를 그대로 구성한다.
   ★다시 스크리닝하지 않는다★(유니버스가 바뀔 수 있다). 인자 구성은
   `screener_routes` 에서 함수로 뽑아 **등록과 원래 경로가 같은 함수**를 쓴다.
3. **재현 검증** — 재실행 `equity_curve`(같은 반올림)와 `equity_dates` 가 저장본과
   **전부 같아야** 등록한다. 다르면 거절하고 첫 불일치 날짜와 두 값을 낸다 —
   *"같은 전략이라고 말할 수 없다"*. 비교 결과는 `repro` 에 남는다.
4. **보유 스냅샷** — 재실행의 완전한 `engine.trades` 로 날짜별 수량을 누적하고
   `engine.ohlcv_all` 종가 × 수량 / 그날 자산으로 종목 비중을 낸다. ETF 슬리브
   거래도 `trades` 에 있으므로 포함된다.
5. 원천 실행의 `is_mock_data`·`is_pit_verified` 를 그대로 싣는다.

**엔진이 쓰는 인터페이스 그대로** — `get(sid)`(dict, `name` 포함) ·
`load_returns_matrix(strategy_ids, start_date, end_date, drop_na_rows=True)`(열이 정수
id 인 DataFrame) — 그리고 새 `load_holdings(strategy_ids, start_date, end_date)`.

**메인 엔진에 필요한 단 하나** — `run_backtest` 는 결과 dict 만 돌려줘 완전한 거래를
얻을 수 없다. `kis_backtest_engine.run_backtest(..., on_engine=None)` 선택 인자를 더해
실행이 끝난 엔진 객체를 콜백으로 넘긴다. 기본 `None` 이면 **바이트 동일**하고 기존
골든이 그것을 지킨다. CLAUDE.md §6 보호 구역에 대한 **유일한 변경**이며 로직은
건드리지 않는다.

### 4.2 R2 · 배분기 — `src/engine/allocator.py`

- `MultiStrategyAllocator.compute(returns_matrix, method, strategies, as_of_date,
  lookback_days, max_weight, min_weight)` — 엔진과 `RegimeAdaptiveAllocator` 가 이미
  쓰는 시그니처 그대로.
- **새로 짜지 않는다** — `hrp` 는 `risk_allocations._hrp_weights`, 역변동성은 같은
  모듈의 식을 쓴다. 상·하한 클립 후 초과분 재분배는
  `regime_adaptive_allocator._cap_and_redistribute` 를 쓴다.
- 반환 — `available` · `weights` · `base_weights`(= weights) · `macro_adjustments`
  (`{}` — ★매크로가 없는 방법이라 구조적으로 0★) · `regime: None` · `method` · `n_obs`.
- `hrp_macro` → `available: False` + 사유(R4 전). 표본 부족(관측 < 20, 공분산 특이)도
  `available: False` + 사유. ★엔진은 이것을 조용히 삼키므로 문(4.5)이 먼저 거절한다.★

### 4.3 R3 · 네팅 — `src/execution/order_netting.py`

**정의** — 날짜 t 에 전략 s 의 슬리브가 종목 i 에 갖는 노출을
`x(s,i,t) = W(s,t) · h(s,i,t)` 로 둔다(W = 포트폴리오 안 전략 비중, h = 전략 자신의 종목
보유 비중).

    총거래  G(t) = Σ_s Σ_i | x(s,i,t) − x(s,i,t−1) |
    순거래  N(t) = Σ_i | Σ_s x(s,i,t) − Σ_s x(s,i,t−1) |
    절감    S(t) = (G(t) − N(t)) × (수수료 + 슬리피지) × equity(t−1)

**라벨** — `netting_basis: "measured_holdings"` 와 가정 둘을 함께 싣는다:
*"t−1→t 가격 변동에 따른 비중 drift 를 무시한다"* · *"전략 내부 거래 비용은 포트폴리오
요율로 평가한다"*. 보유가 없는 날·전략은 **`None` + 사유**다 — 0 이 아니다.

**배선** — 엔진 두 곳(`multi_strategy_backtest.py` 의 네팅 계산,
`realism_engine.py` 의 같은 자리)의 `×1.5` 를 `OrderNettingEngine.savings(...)` 호출로
바꾸고, `_load_data` 가 `holdings` 를 함께 싣는다. ★네팅은 지금처럼 **보고 전용**이다★
— 수익률에 더하지 않는다. 더하는 것은 값을 바꾸는 결정이라 이 설계의 범위가 아니다.

### 4.4 가용성 — `src/engine/multistrategy_availability.py`

- `MISSING` 에서 셋(allocator · strategy_registry · order_netting)을 뺀다.
  `test_no_dangling_imports` 가 그것을 **요구**한다(복원되면 레지스트리에서 빼라).
- 가드를 **기능 단위**로 나눈다: 코어 셋이 없으면 503. `macro_feed`·`regime_model` 이
  필요한 요청만 422 + 사유 — `allocation_method="hrp_macro"` ·
  `rebalance_policy="regime_change"`.
- 리얼리즘 `enable_regime_adaptive` 는 허용하되 `regime_adaptive` 블록에 *"systemic_risk
  미상(R4 전) — 상관붕괴만으로 모드를 정했다"* 를 싣는다.
- `DATA_GAP` 사유는 레지스트리 테이블이 생기므로 갱신한다.

### 4.5 문 — `stage11_routes` · `stage12_routes`

- `GET /api/v1/multibacktest/strategies`(목록 — 프런트 `Strategy` 타입의 `id`·`name`·
  `is_active`) · `POST`(등록) · `DELETE /api/v1/multibacktest/strategies/{id}`(비활성).
  등록 거절은 409/422 + 사유.
- 결과에 `sources` 블록 — 전략별 `source_run_id`·`is_mock_data`·`is_pit_verified`·재현
  검증 결과. `perf_label` 은 **원천 실행들의 mock 여부**로 정한다(하나라도 mock → mock).
- BB 의 `cost_model` 블록과 네팅 라벨을 함께 낸다.

### 4.6 화면 (CSS 클래스·헤딩 불변 — E2E 계약)

- 멀티전략 페이지 — 전략 목록을 `/api/v1/multibacktest/strategies` 에서 읽는다. 최근
  완료 백테스트 실행을 골라 등록하는 작은 패널과 거절 사유 표시. 기본 알고리즘
  `hrp_macro` → `hrp`. `hrp_macro`·`regime_change` 옵션은 *"R4 전까지 불가"* 로
  비활성하고 사유를 보인다.
- 리얼리즘 대시보드 — 기본 `allocation_method` 를 `hrp` 로, `strategy_ids` 를 등록
  목록에서 가져온다(지금은 존재하지 않는 `[1, 2, 3]` 하드코딩).

## 5. 검증

- **TDD** — 레지스트리(완료 실행만 · 재현 일치 → 등록 / 불일치 → 거절 + 첫 불일치 날짜 ·
  재스크리닝 0회 · 보유 합 ≈ 투자 비중 · 플래그 전달) · 배분기(`risk_allocations` 와 같은
  답 · 클립 경계 · `available: False` 짝) · 네팅(손계산 골든: 반대 방향 → 절감 > 0, 같은
  방향 → 0 · 보유 없음 → `None`) · 가용성(코어 가용 → 503 아님 · hrp_macro·regime_change
  → 422).
- **골든** — 메인 엔진 기존 골든 불변(`on_engine=None`) · 멀티전략 수익률·Sharpe·MDD 가
  네팅 교체 전후 동일.
- **실물 E2E(mock)** — 백테스트 둘 실행 → 등록 → 멀티백테스트 inverse_vol·hrp 완주 →
  `sources`·`netting_basis`·`perf_label(mock)` 확인.
- **변이** — 재현 검증 제거 · 재스크리닝 경로 · 네팅 ×1.5 복귀 · 보유 없음을 0 으로 ·
  hrp_macro/regime_change 가드 제거 · 클립 제거 · `on_engine` 기본값이 동작을 바꿈 ·
  mock 플래그 누락 · 복원된 모듈이 레지스트리에 잔존 → 전부 사망해야 한다.
- **커밋 단위** — R1(레지스트리 + 엔진 훅) · R2 · R3 · 가용성·문·화면. 각각 전체 게이트
  (`ruff` · pytest · `tsc` · `next build`, 곁에 아무것도 안 돌린다).

## 6. ★이 설계가 하지 않는 것★

- **R4 를 하지 않는다** — `macro_feed`·`regime_model`·`hrp_macro`·`systemic_risk_score`·
  사분면 어휘 통일. 킬스위치 경로를 건드리지 않는다.
- **메인 엔진 로직을 바꾸지 않는다** — 선택 인자 하나만 더한다.
- **네팅 절감을 수익률에 더하지 않는다** — 보고 전용 그대로.
- **캔버스 그래프 전략 저장을 만들지 않는다** — 원천은 저장된 백테스트 실행이다.
- **`trades[:500]` 잘림을 고치지 않는다** — 별건으로 기록한다.
- **`liquidity_capacity` 의 `strategies(graph_json)` 조회를 고치지 않는다** — capacity 훅은
  기본 꺼짐이고, 켜면 지금처럼 폴백 사유(`capacity 데이터 부족`)를 낸다. 별건.
