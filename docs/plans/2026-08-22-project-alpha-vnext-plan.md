# Project Alpha vNext 실행 계획 — P0~P5

> 마스터 프롬프트 1차 산출물 ④. 근거: [감사](../specs/2026-08-22-project-alpha-vnext-audit.md) ·
> [벤치마크](../specs/2026-08-22-backtest-benchmark-results.md) ·
> [백테스트 신뢰성](../specs/2026-08-22-backtest-reliability-design.md) ·
> [Company 언더라이팅](../specs/2026-08-22-company-underwriting-design.md).
>
> **이 계획은 승인 전까지 실행되지 않는다.** 브랜치
> `claude/backtest-modern-ui-refactor-akxvbc`. PR 은 만들지 않는다.

## 순서의 근거

프롬프트의 성능 순서(1 프로파일 → 2 벌크 → 3 오버헤드 → 4 프로세스 → 5 수치 → 6 컴파일)를
따르되, **실측이 그 앞에 한 칸을 더 넣었다** — 정합성. 성능을 고치기 전에 결과가 옳아야 한다.

```
P0 정합성·격리·계측  →  P1 성능(측정 후)  →  P2 Company 언더라이팅
                                          →  P3 통합(논지→신호, 매크로→조건부)
                                          →  P4 포트폴리오 결정  →  P5 고급 컴퓨트(증거 있을 때만)
```

---

## P0 — 신뢰성 (첫 수직 슬라이스 포함)

### P0-1 ★전역 몽키패치 제거★ — 가장 먼저

- **목표**: 전략이 데이터를 **인자로** 받는다. 모듈 전역을 통신 채널로 쓰지 않는다.
- **파일**: `src/kis_backtest_engine.py`(`_generate_signal_as_of`),
  `src/kis_strategies/strategies.py`(`BaseStrategy` 에 명시 입력 경로 1개 — 12종이
  **한 곳에서** 얻게 한다), `src/kis_strategies/dsl_strategy.py`.
- **바꾸면 안 되는 것**: 기존 `generate_signal(code, name)` 시그니처(라이브 경로 소비자),
  `signal_lag` 규칙, `df_slice = ohlcv_map[tk].loc[:sim_date]` 의 look-ahead 차단,
  결과 스키마.
- **수용 기준**:
  1. 동시 실행 후 `fetcher.get_daily_prices` 가 **원본이다**.
  2. **단일 실행 결과가 변경 전과 바이트 동일**.
  3. 동시 실행에서 결과가 달라지면 **그 차이가 곧 결함의 크기** — 회귀가 아니라 수정의
     증거이므로 커밋 메시지에 수치로 적는다.
- **기존 테스트**: `test_backtest_run_routes` · `test_backtest_runs` ·
  `test_backtest_progress_emit` · `test_screen_to_backtest_progress` ·
  `test_backtest_run_recovery` · `test_backtest_universe_cap` · `test_strategy_backtest_map`.
- **신규**: ★전역 무오염★ 가드(동시 실행 후 전역 동일성) — **지금 코드에서 반드시 red**.
  ★결정론★ 가드(같은 입력 2회 = 바이트 동일, 동시 실행 중에도).
- **롤백**: 단독 revert. `BaseStrategy` 추가는 가산이라 기존 경로 무영향.

### P0-2 워커 프로세스 1개 + 텔레메트리

- **목표**: CPU 작업을 API 프로세스 밖으로. 동시성은 **아직 1** — 회귀 귀속을 위해.
- **파일**: `src/api/backtest_run_routes.py`(스레드 → 프로세스 풀),
  `src/data/backtest_runs.py`(텔레메트리 컬럼 ADD COLUMN).
- **바꾸면 안 되는 것**: `uvicorn --workers 1`(API 워커는 그대로 — **CPU 를 빼는 것**이지
  워커를 늘리는 게 아니다), 하트비트·`sweep_orphaned()`·취소(`_Cancelled`)·재시도
  (이력 불변)·`touch_progress` 커넥션 절약 — **전부 재사용**.
- **수용 기준**: 취소·재시도·고아 복구 테스트가 프로세스 워커에서 그대로 통과 ·
  텔레메트리 12항목(감사 §3.5 목록)이 DB 에 기록 · 결과가 P0-1 과 바이트 동일.
- **신규**: 프로세스 경계 취소 테스트 · 텔레메트리 기록 가드(항목 수를 먼저 단언).
- **롤백**: 단독 revert. 컬럼은 append-only.

### P0-3 동시성 상한 N + 처리량 가드

- **목표**: `N = min(cpu_count-1, 4)` 기본, `BACKTEST_WORKERS` 로 덮기
  (`BACKTEST_OHLCV_WORKERS` 전례와 동일 관례).
- **수용 기준**: ★동시 N 의 실행당 시간이 순차보다 나쁘지 않다★
  (현재 4코어에서 **63% 나쁨** — 이 가드가 지금은 red 여야 한다) ·
  CPU 사용률이 동시 4 에서 **≥300%**(현재 105%).
- **신규**: 처리량 가드. **변이 프로브** — 프로세스를 스레드로 되돌려 red 확인.
- **롤백**: N=1 로 되돌리면 P0-2 상태.

### P0-4 Postgres 환경 재측정 ★P0 완료 조건★

- **목표**: 하네스를 **실 DB 형상**에서 재실행. SQLite/mock 에서 잰 것은 Postgres 를
  말해 주지 않는다(벤치마크 문서 §환경).
- **수용 기준**: 커넥션 풀(15) 경합·쿼리 시간·로딩 비중을 **실측치로** 문서에 채운다.
  로딩 비중이 **15% 이하면 P1-2(벌크 로딩)를 착수하지 않는다** — measure before optimize.
- **롤백**: 해당 없음(측정).

---

## P1 — 성능 (P0-4 의 숫자 위에서만)

| # | 작업 | 착수 조건 |
|---|---|---|
| P1-1 | `calc_ma` 사전계산 — 봉마다 rolling mean 재계산(7,280회) 제거 | P0-1 이후 프로파일에서 여전히 상위면 |
| P1-2 | `load_ohlcv_bulk(tickers)` — `WHERE ticker IN (...)`. 단건 함수는 **유지** | **P0-4 에서 로딩 ≥15% 일 때만** |
| P1-3 | 봉당 `DataFrame` 생성(3,642회) 제거 | P0-1 이 대부분 해소할 것으로 보이나 **재서 판단** |
| P1-4 | NumPy 벡터화 | P1-1~3 이후 프로파일이 지목할 때만 |

★프롬프트 금지 사항★ 무분별한 Numba · 타임아웃 증설 · 폴링 주기 증설 · C++ 전면 재작성.
**P1-4 이후에도 컴파일 커널(P5)은 벤치마크 증거가 있을 때만.**

---

## P2 — Company 언더라이팅

| # | 작업 | 비고 |
|---|---|---|
| P2-1 | **CompanySnapshot 저장소** + 기존 값 담기 | ★첫 슬라이스★ — 새 모델 0개. `regime_snapshots.py` 관례 복제 |
| P2-2 | **역DCF** — `compute_dcf` 근 찾기 역산 | 근 없음/불연속은 **사유**, 숫자 금지 |
| P2-3 | **확률적 밸류에이션 P10~P90** | 분포 폭을 좁혀 보이게 하지 않는다 |
| P2-4 | **매크로 민감도** — `regime_drivers`(정확 Shapley) 재사용 | 그레인저 ≠ 인과 라벨 유지 |
| P2-5 | **논지 + kill 조건** — `FIELD_BY_ID` 로 표현 | 새 DSL 금지 |

★이익의 질·ROIC vs WACC 는 짓지 않는다 — 이미 있다★ (`financial_deep`).
스냅샷이 **호출해서 담기만** 한다. 산수를 두 곳에 두지 않는다.

**수치 안전 필수**: 역DCF·확률 표본이 분수승·로그 구간이다. 적자기업 실데이터에서만
터지고 mock 은 항상 흑자다(CLAUDE.md).

---

## P3 — 통합

- P3-1 **논지 → 신호 → 백테스트**: kill 조건이 `buy/sell_conditions` 로 들어간다.
  **새 다리를 놓지 않고 있는 다리에 올린다.**
- P3-2 **백테스트 → 리스크 귀인**: `bt_*` → 팩터 귀인.
- P3-3 **매크로 → 조건부 예측**: 국면별 μ/Σ.
- P3-4 **Company 팩터 → 포트폴리오 팩터 리스크**.

## P4 — 포트폴리오 결정 엔진

조건부 μ/Σ · 로버스트 최적화 · 동적 리밸런스 밴드 · **모델 불일치**(P4-MACRO 의
앙상블 불일치 재사용 — 평균으로 뭉개지 않는다) · 거래비용 인지 매매.

## P5 — 고급 컴퓨트

**벤치마크 증거가 지지할 때만.** 그 전에는 착수하지 않는다.

---

## 전 단계 공통 게이트

```bash
KIS_USE_MOCK=1 python3 -m pytest tests/ -q          # 1,953 passed / 10 skipped / 0 failed
ruff check scripts/ src/ tests/ main_api.py         # 0
cd frontend && npx tsc --noEmit && npm run lint && npx next build
cd frontend && npx playwright test --shard=1/4      # 이후 2/4·3/4·4/4 (422 passed)
KIS_USE_MOCK=1 python3 scripts/bench_backtest.py --suite all --json out.json
```

- **전체 게이트는 샤드 4개로 나눈다** — 단일 실행이 `[killed]` 로 2.5시간을 날린 전례.
- 게이트 도는 중 `next build` 금지. 성패는 종료코드가 아니라 로그의 `N passed / N failed`.
- **변이 프로브를 돌리지 않은 가드는 가드가 아니다.** 가드마다 보호 대상을 되돌려
  red 를 확인하고, 같은 가드를 건드릴 수 있는 프로브끼리는 **나눠 돌린다**(귀속).
- 백그라운드 명령은 `cd /home/user/Project-Alpha[/frontend] &&` 로 시작한다.

## 성공 지표 (감사 §10)

| 지표 | 현재 | 목표 |
|---|---|---|
| 동시 실행 후 전역 오염 | **발생** | 0 |
| 동시 4 vs 순차 4 | **63% 느림** | 4코어에서 ≥2배 빠름 |
| CPU 사용률(동시 4) | **105%** | ≥300% |
| `_generate_signal_as_of` 비중 | **75.7%** | ≤30% |
| 백테스트 텔레메트리 | **0항목** | 12항목 |
| pytest / Playwright | 1,953 / 422 | 감소 없음 |

---

# 부록 — Dynamic Portfolio 축 편입 (2차 감사)

`Project_Alpha_Dynamic_Portfolio_Design_Brief.md` 가 새 축을 추가했다. 위 P0~P5 를
버리지 않고 **끼워 넣는다** — 두 문서의 우선순위가 충돌하지 않기 때문이다.

| 이 계획 | Brief 우선순위 | 관계 |
|---|---|---|
| P0 백테스트 신뢰성 | — | Brief 는 다루지 않음. **먼저** 한다(정합성 결함이 열려 있다) |
| — | Brief P0 ①아키텍처 감사 ②유니버스 감사 ③매크로→조건부 μ/Σ **설계** | **이번 세션에 완료** |
| P1 백테스트 성능 | — | 측정 후 조건부 |
| **P2.5 (신설)** | Brief P0③ 구현 · P1 ④~⑧ | **첫 수직 슬라이스** — 조건부 μ/Σ → optimizer → target range |
| P2 Company 언더라이팅 | — | 병행 가능(다른 표면) |
| P3 통합 | Brief P2 ⑨~⑫ | 리밸런싱 정책 · 노출↔상품 · 정책 OOS |
| P4 포트폴리오 결정 | Brief P1 ⑦⑧ · P2 | robust · dispersion · 동적 밴드 |
| P5 고급 컴퓨트 | Brief P3 ⑮ | 증거 있을 때만 |

## P2.5 — 첫 수직 슬라이스 (Brief §20 지정)

`Macro State/Regime → 조건부 μ/Σ → optimizer → target range`

| 항목 | 내용 |
|---|---|
| 목표 | 감사가 찾은 **"파이프는 깔렸는데 안 흐른다"** 를 닫는다 |
| 파일 | `src/engine/conditional_market.py`(신규) · `allocation_studio.py`(주입 지점) · `allocation_routes.py`(`mes_id` 를 스탬프 이상으로) · `PortfolioDecisionState` 저장소 |
| 재사용 | `regime_transitions.k_step_forecast` · `ensemble.disagreement` · `entropy_views.ep_posterior_mu` · `regime_adaptive_allocator` 의 EWMA·상관진단 · `regime_snapshots`/`target_versions` 관례 |
| 바꾸면 안 되는 것 | 기존 8개 모델의 **무조건부 결과 바이트 동일** · TPV 실행 게이트 · `macro_allocation.py` baseline · `build_plan` |
| 수용 기준 | 설계 문서 §6 의 6항목(짝 단언 포함) |
| 신규 테스트 | 국면 바꾸면 μ 가 바뀐다 / 국면 없으면 기존과 동일 / 표본 부족 시 사유 / 조용한 폴백 금지 / 모델 1개면 range 없음 |
| 롤백 | 신규 파일 + 주입 지점 한 줄 — 단독 revert |

★순서 주의★ P0(백테스트 정합성)을 P2.5 보다 **먼저** 한다. 이유는 우선순위가 아니라
**증거**다 — 동시 실행이 전역을 오염시키는 상태에서 정책 백테스트를 돌리면 그 결과를
믿을 수 없다. Brief §14 가 walk-forward 를 "핵심 validation engine" 으로 삼는데,
그 엔진이 지금 동시 실행에서 오염된다.
