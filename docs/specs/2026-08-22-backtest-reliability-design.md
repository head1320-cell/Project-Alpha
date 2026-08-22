# 백테스트 신뢰성 설계 — 정합성 회복과 프로세스 격리

> 마스터 프롬프트 1차 산출물 ②. 실측 근거는
> [`2026-08-22-backtest-benchmark-results.md`](./2026-08-22-backtest-benchmark-results.md),
> 맥락은 [`2026-08-22-project-alpha-vnext-audit.md`](./2026-08-22-project-alpha-vnext-audit.md).
> **이 문서는 설계다. 구현은 승인 후.**

## 0. 이 설계가 푸는 문제 — 순서가 곧 논지다

프롬프트는 성능을 물었고, 실측은 **성능보다 먼저 다뤄야 할 것**을 내놓았다.

| 순위 | 문제 | 실측 |
|---|---|---|
| **1** | 동시 실행이 서로의 데이터를 읽고, 끝난 뒤에도 프로세스가 오염된 채 남는다 | 오염 `true`, 정상 종료, 오류 0 |
| 2 | 실행 시간의 75.7% 가 그 **같은 함수** 에 있다 | `_generate_signal_as_of` 12.97/17.15s |
| 3 | 스레드 4개가 순차 4회보다 63% 느리다 | 27.06s vs 16.6s, CPU 105% 고정 |
| 4 | 성능 계측이 0건이라 이후 최적화를 판정할 수 없다 | 전수 grep |

1 과 2 가 같은 함수라는 것이 이 설계의 축이다 — **한 수로 둘을 닫는다.**

---

## 1. ★1순위 — 전역 몽키패치 제거★

### 지금

```python
# src/kis_backtest_engine.py:675  _generate_signal_as_of()
original_fn = fetcher.get_daily_prices        # :677  ← 이미 패치돼 있으면 그걸 저장한다
...
fetcher.get_daily_prices  = lambda *a, **kw: df_copy    # :713  모듈 전역
fetcher.get_current_price = lambda *a, **kw: price_info # :714
try:
    return strategy.generate_signal(ticker, ticker)     # 데이터를 **전역으로** 넘긴다
finally:
    fetcher.get_daily_prices = original_fn              # :719  남의 람다를 복원할 수 있다
```

전략은 `generate_signal(ticker, ticker)` 로 **티커만** 받고, 데이터는 전역에서 당긴다.
그래서 전역이 통신 채널이 됐고, 스레드가 여럿이면 채널이 하나뿐이라 섞인다.

### 설계

**전략이 데이터를 인자로 받는다.** 전역은 통신에 쓰지 않는다.

- `BaseStrategy` 에 `generate_signal_with(ticker, bars, price_info)` 형태의 **명시적
  입력 경로**를 추가한다(이름은 구현 시 확정). 기존 `generate_signal(code, name)` 은
  **유지** — 라이브 경로와 외부 소비자가 쓰기 때문이다.
- `BaseStrategy` 에 기본 구현을 두어 12종 전략이 **한 곳에서** 새 경로를 얻게 한다.
  전략마다 고치면 12번 틀릴 기회가 생긴다.
- `_generate_signal_as_of` 는 몽키패치 대신 새 경로를 호출한다. 전역은 건드리지 않는다.

### ★이 변경의 정당성은 "결과가 같다" 가 아니다★

R1 리스크(감사 §8): 몽키패치를 없애면 결과가 달라질 수 있다. **단일 실행에서는 같아야
한다** — 게이트로 강제한다. **동시 실행에서 달라진다면 그 차이가 곧 §3.1 결함의
크기**이고, 그것은 수정이 옳다는 증거이지 회귀가 아니다. 이 구분을 커밋 메시지에 적는다.

### 부수 효과 (성능)

같은 함수 안에서 봉마다 6열 `DataFrame` 을 새로 만들고(3,642회) `calc_ma` 로 rolling
mean 을 처음부터 다시 계산한다(7,280회). 인자 전달로 바뀌면 **사전계산된 지표 시계열을
그대로 넘길 수 있다** — 75.7% 의 상당 부분이 구조적으로 사라진다. 다만 이 문서는
그 크기를 **주장하지 않는다**. 텔레메트리(§4)를 먼저 심고 재서 적는다.

---

## 2. 2순위 — 프로세스 격리 (안 A)

### 왜 A 인가

감사 §6 의 표가 근거다. 요약: **A 만이 새 인프라 0개로 정합성·GIL·메모리 격리를
동시에 닫으면서, 이미 검증된 영속·복구 계층을 그대로 재사용한다.**

★`uvicorn --workers 1` 을 어기지 않는다★ API 워커를 늘리는 것이 아니라 **CPU 작업을
API 프로세스 밖으로 빼는** 것이다. 프로세스 로컬 캐시·DART 쿼터 카운터·적재 상태는
API 프로세스에 그대로 남는다 — CLAUDE.md 가 워커 증설을 막은 이유가 그 상태이고,
이 설계는 그 상태를 건드리지 않는다.

### 형태

- `concurrent.futures.ProcessPoolExecutor` 상한 N. **새 의존성 0.**
- N 기본값은 `min(cpu_count - 1, 4)`. 하드코딩하지 않고 실측으로 확정하며
  `BACKTEST_WORKERS` 로 덮을 수 있게 한다(`BACKTEST_OHLCV_WORKERS` 전례와 동일 관례).
- **큐 대기를 상태로 만든다.** 지금은 `queued` 가 사실상 즉시 `running` 이 된다.
  풀이 차면 진짜로 대기하므로, `queued` 시간이 관측 가능한 값이 된다(§4).
- 워커는 **결과를 직접 DB 에 쓴다**(`br.set_result`). 프로세스 간 결과 직렬화(IPC)를
  피한다 — 결과 페이로드가 medium 에서 359 KB 다.

### 취소 — 프로세스 경계를 넘기는 법

현행 취소는 **협조적**이다: 진행 콜백이 `touch_progress` 가 `blocked` 를 반환할 때
DB 상태를 확인하고 `_Cancelled` 를 던진다(`backtest_run_routes.py:60~90`).
이 신호는 **DB 를 경유하므로 프로세스에서도 그대로 동작한다.** 새 IPC 채널이 필요 없다.

- 워커가 응답하지 않으면? **강제 종료는 하지 않는다.** 하트비트가 끊기면 기존
  `sweep_orphaned()` 가 `failed` 로 확정한다 — 이미 있는 안전망이다.
- 취소 지연 상한은 진행 이벤트 간격(최대 100개 throttle)에 종속된다. 이 값을
  텔레메트리에 넣어 실측한 뒤에 조정한다.

### 재시작 복구

**변경 없음.** 하트비트 + `sweep_orphaned()` 가 이미 "워커가 사라진 비종료 행" 을
처리한다. 워커가 스레드에서 프로세스로 바뀌어도 판정 기준(하트비트 침묵)은 동일하다.
★이 계층을 재작성하지 않는다★ — 이미 동작하고 테스트가 있다.

### 재현성

프로세스 격리는 재현성을 **강화**한다. 전역이 프로세스마다 별개이므로 §1 의 오염이
구조적으로 불가능해진다. 입력 스냅샷(`input_snapshot`)·엔진 버전 기록은 그대로.

---

## 3. 3순위 — 데이터 접근 (측정 후에만)

실측에서 로딩은 small 1.8% · medium 2.3% 였다. **이 환경에서는 병목이 아니다.**
그러나 SQLite/mock 이므로 Postgres 형상은 다를 수 있고, 종목당 1쿼리 구조는 사실이다
(small 239회 / medium 1,191회, 종목당 ~12).

따라서 **벌크 로딩은 설계만 해 두고 착수 조건을 건다**: Postgres 환경에서 하네스를
재실행해 로딩 비중이 **15% 를 넘을 때** 착수한다. 넘지 않으면 하지 않는다 —
프롬프트의 "measure before optimize" 를 문자 그대로 지킨다.

설계 형태: `load_ohlcv_unified(ticker, ...)` 옆에 `load_ohlcv_bulk(tickers, ...)` 를
두어 `WHERE ticker IN (...)` 한 번으로 받고 티커별로 쪼갠다. 기존 단건 함수는
**유지**(라이브 경로 소비자가 있다).

---

## 4. 관측성 — 프롬프트가 요구한 12항목

현재 0건. 워커에 심고 `backtest_runs` 에 남긴다(컬럼 추가는 `regime_snapshots.py:89`
의 ADD COLUMN 관례 — SQLite `IF NOT EXISTS` 미지원을 예외로 흡수).

| 항목 | 출처 |
|---|---|
| 큐 대기 시간 | 풀 제출 → 워커 시작 |
| 총 소요 | 기존 `created_at`/완료 시각 |
| **CPU 시간** | `time.process_time()` (워커 프로세스) |
| **피크 RSS** | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| **워커 ID** | `os.getpid()` |
| **DB 쿼리 수 / 시간** | SQLAlchemy `before_cursor_execute` 이벤트 |
| 캐시 적중률 | OHLCV 로더 |
| 적재 행수 | `ohlcv_map` 합계 |
| 시뮬레이션 스텝 | `len(sim_dates) × len(symbols)` |
| 결과 크기 | 직렬화 바이트 |
| 실패 · 취소 | 기존 상태 전이 |

★하네스가 이미 이 값들을 재고 있다★ (`scripts/bench_backtest.py`). 워커 안으로
옮기는 것이지 새로 발명하는 것이 아니다.

---

## 5. 반드시 보존하는 계약

프롬프트의 "BACKTESTER MUST PRESERVE" 전 항목 + 이 저장소의 불변식.

| 계약 | 현재 위치 | 이 설계의 영향 |
|---|---|---|
| PIT · look-ahead 차단 | `df_slice = ohlcv_map[tk].loc[:sim_date]`, `signal_lag` | 없음 — 슬라이스 규칙 그대로 |
| 공표일 | `pit_store` · `pit_macro` · `_asof_date_for_screener` | 없음 |
| 생존편향 안전 유니버스 | `tickers_asof` · `top_mktcap_asof` (상폐 포함) | 없음 |
| 기업행위 | 적재 계층 | 없음 |
| 현실적 체결 | `fill_price` · 래더 · 돌파매수 · 슬리피지 | 없음 |
| 비용 | `commission_rate` · `slippage_rate` | 없음 |
| 유동성 | `liquidity_floor` 게이트 | 없음 |
| 회전율 | 결과 지표 | 없음 |
| 결정론 엔진 버전 | `input_snapshot` + 코드 버전 | **강화**(§2 재현성) |
| 불변 입력 스냅샷 | `backtest_runs.input_snapshot` | 없음 |
| 취소 · 재시도 · 복구 | `_Cancelled` · retry · `sweep_orphaned` | **재사용**(§2) |

---

## 6. 첫 수직 슬라이스 (권고)

**"몽키패치 제거 + 워커 프로세스 1개 + 텔레메트리"** — 동시성 확장은 다음 커밋.

이 조각을 고른 이유: 가장 작으면서 **정합성·격리·측정 세 가지를 동시에 연다.**
동시성 N 을 같이 넣으면 회귀가 났을 때 셋 중 무엇 때문인지 가릴 수 없다.

수용 기준:
1. 동시 실행 후 `fetcher.get_daily_prices` 가 **원본이다** (지금은 아니다).
2. 단일 실행 결과가 변경 전과 **바이트 동일**.
3. 취소·재시도·고아 복구 테스트가 프로세스 워커에서 그대로 통과.
4. 텔레메트리 12항목이 `backtest_runs` 에 기록된다.
5. pytest 1,953 · Playwright 422 감소 없음.

## 7. 하지 않는 것

프롬프트의 금지 목록 그대로 — C++ 전면 재작성 · 유행에 따른 Redis/Celery ·
무분별한 Numba · 타임아웃 증설 · 폴링 주기 증설 · **프로세스 로컬 상태 이전 전
uvicorn 워커 증설**. 그리고 이 단계에서 **NumPy/Numba 는 착수하지 않는다** —
프롬프트의 성능 순서(1 프로파일 → 2 벌크 → 3 오버헤드 → 4 프로세스 → 5 수치)에서
아직 4번이다.
