# Project Alpha vNext 감사 — 아키텍처 · 역량 · 근거 · 권고

> 마스터 프롬프트 1차 산출물 ①. **이 문서를 쓰는 동안 프로덕션 코드는 한 줄도 바뀌지 않았다.**
> 실측 원본은 [`2026-08-22-backtest-benchmark-results.md`](./2026-08-22-backtest-benchmark-results.md).

## 0. 한 문단 요약

Project Alpha 는 이미 도구 모음이 아니다 — PIT 매크로 빈티지, 불변 스냅샷, 재현
엔드포인트, 목표 버전(TPV) 실행 게이트, 능력 사다리까지 **연구 OS 의 뼈대가 서 있다**.
가장 큰 위험은 없는 기능이 아니라 **있는 계약이 동시 실행에서 깨진다**는 것이다.
백테스트 신호 생성기가 모듈 전역을 몽키패치하고, 실행마다 상한 없는 스레드를 띄운다.
실측 결과 두 실행이 끝난 뒤에도 전역이 **영구히 오염**됐고(§3.1), 같은 함수가 실행
시간의 **75.7%** 를 쓰며(§3.2), 스레드 4개는 순차 실행보다 **63% 느리다**(§3.3).
따라서 첫 수는 성능 튜닝이 아니라 **정합성 회복 + 프로세스 격리**다.

---

## 1. 아키텍처 맵 (실측)

| 층 | 규모 |
|---|---|
| 백엔드 라우터 모듈 (`ROUTER_MODULES`) | **34** |
| HTTP 경로 데코레이터 | **312** |
| `src/**/*.py` | **264** |
| pytest 파일 | **167** (총 **1,953 passed / 10 skipped / 0 failed**, 오늘 실측) |
| 프론트 라우트 (`page.tsx`) | **34** |
| Playwright 스펙 | **48** (422 passed) |

`main_api.py`(23줄) → `src/app_factory.create_app()` → `ROUTER_MODULES` 등록.
프론트는 FSD, 브라우저는 백엔드 주소를 모르고 전부 동일출처 런타임 프록시
(`/api/backend/[...path]`)를 거친다. `uvicorn --workers 1` 고정 — 캐시·DART 쿼터·
적재 상태가 프로세스 로컬이기 때문이다(CLAUDE.md 불변식).

### 파이프라인 실현도

`DATA → SCREENER → COMPANY/MACRO → THESIS/SIGNAL → BACKTEST → RISK → ALLOCATION →
EXECUTION → ATTRIBUTION/JOURNAL`

이 사슬은 **이미 식별자로 이어져 있다**: `rc_*`(ResearchCase) → `rgs_*`(MES) →
`tpv_*`(TargetPortfolioVersion) → `rr_*`(ResearchRun) → `bt_*`(BacktestRun).
끊긴 곳은 **THESIS/SIGNAL** 한 칸이다 — Company 의 논지가 형식 신호가 되어 백테스트로
들어가는 다리가 없다.

---

## 2. 7개 도구 역량 매트릭스

| 도구 | 있는 것 | 없는 것 (실측) |
|---|---|---|
| **01 Screener** | 3-레이어(유동성 게이트 → 필터 kind → 후처리), `FIELD_BY_ID` 단일 레지스트리, PIT 평가 경로(`as_of_date`), 시점 유니버스(`all_asof`·`top200_asof`, 상폐 포함) | — (구조는 리팩터 대상 아님) |
| **02 Backtester** | 영속 `backtest_runs`, 폴링, 취소, 재시도(이력 불변), 진행률, **하트비트 + `sweep_orphaned()` 고아 복구**, 체결·비용·슬리피지·래더·마켓타이밍 | **프로세스 격리 없음**, 동시성 상한 없음, **성능 계측 0건**, 신호 경로 정합성 결함(§3.1) |
| **03 Macro** | ECOS 40계열 + FRED 21계열, ALFRED 빈티지 PIT, 능력 사다리 L0~L3(위조 불가 프로브), 국면 3도구 + Dirichlet 전이 + 정확 Shapley, VECM/차분 VAR 분기, conformal 실측 커버리지 | 프론티어 모델(torch·cvxpylayers 미설치), ECOS 32계열 **라이브 미검증** |
| **04 Company** | Overview·Valuation·Financials·Factors·Peers·Risk·AI, **RIM/DCF/DDM**(`valuation_models.py`), 민감도, football field, comps, `risk_deep`, 그리고 **`financial_deep` 이 이미 하는 것** — 발생액·OCF-NI 갭·red flag R1~R3(이익의 질) · 듀폰 · **ROIC vs WACC 스프레드**(`:299-309`) · Sloan 발생액 | **역DCF 0건** · **확률적 밸류에이션(P10~P90) 0건** · **CompanySnapshot 0건** · **논지/kill 조건 0건** · **Company 매크로 민감도 0건** |
| **05 Risk** | VaR·GARCH·CVA·파생, 스트레스 시나리오 팩(`pack_id@hash`), 상관-국면, 민감도 히트맵 | 국면조건부 공분산, 꼬리 의존, 역스트레스 |
| **06 Allocation** | BL·MVO·EP(Entropy Pooling)·HRP·리스크패리티, 제약 최적화, TPV 실행 게이트, 롱숏(연구 전용), 오버레이 컴파일 단일 출처 | 동적 리밸런스 밴드, 거래비용 인지 매매 |
| **07 Data Infra** | `source_registry`(`verified_live` 일급), `mock_gate` 단일 판정, `pit_macro` 빈티지, `pit_store`, 스냅샷 DB, KRX/DART/KIS 클라이언트 | `daily_prices`·`investor_flows` 미적재(이 환경), 통합 provenance/품질 대시보드 |

---

## 3. 실제로 깨진 것 — **측정 근거**

전 항목의 원 수치는 벤치마크 문서에 있다. 여기서는 판정만 적는다.

### 3.1 ★정합성 — 최우선★

`src/kis_backtest_engine.py:675` `_generate_signal_as_of()` 가 모듈 전역
`fetcher.get_daily_prices` / `get_current_price` 를 패치하고, `finally` 에서
**진입 시점의 전역**(`:677`)으로 되돌린다. `src/api/backtest_run_routes.py:139,196`
은 실행마다 **상한 없는** daemon 스레드를 띄운다.

동시 실행 2개(겹치지 않는 종목 집합) 실측:

- 전역이 패치된 상태로 관측된 비율 **95.9%** (3,978 / 4,149 샘플)
- 두 실행의 데이터가 **모두** 같은 전역에 관측됨 (**2/2**, 42개 티커)
- **두 실행이 정상 종료한 뒤에도 전역이 오염된 채 남음** (`true`)
- **엔진 오류 0건** — 조용히 잘못된다

`uvicorn --workers 1` 이라 프로세스는 하나다. 즉 한 번 오염되면 **이후 모든**
백테스트와 현재가 조회가 완료된 실행의 얼어붙은 DataFrame 을 받는다.
노출 범위도 넓다 — 벡터화 경로 `signal_at` 을 가진 전략은 `condition_strategy`
하나뿐이고, `strategies.py` 10종 + `DslStrategy` 는 전부 이 경로다.

### 3.2 성능 — 병목이 정합성 결함과 같은 함수다

small(20종목×260일): 벽시계 17.15s 중 **simulating 이 91.6%**,
그중 `_generate_signal_as_of` 가 **12.97s = 전체의 75.7%**.
내부적으로 `calc_ma` **7,280회**(봉마다 rolling mean 재계산), `DataFrame.__init__`
**3,642회**(봉마다 6열 프레임 생성).

→ 이 함수 하나를 고치면 정합성과 성능이 **함께** 닫힌다.

### 3.3 확장성 — 스레드가 처리량을 못 산다

4코어에서 동시 실행 1/2/4 의 CPU 사용률이 **107%/103%/105%** 로 고정.
스레드가 확장된다면 4개에서 ~400% 여야 한다. 그리고 4개 동시(27.06s)가
**순차 4회(16.6s)보다 63% 느리다.** 현재 모델은 순차 큐보다 **엄격히 나쁘다.**

### 3.4 데이터 접근

OHLCV 를 **종목당 1쿼리**로 받는다(`load_ohlcv_unified(ticker, ...)`), `eval_cap`
상한 4000. 쿼리 수는 규모에 정확히 비례한다 — small 20종목 **239회** ·
medium 100종목 **1,191회** · large 263종목 **3,265회** (일관되게 종목당 ~12).
실행 내부 로더 스레드 10개(최대 32) × 상한 없는 동시 실행 = 스레드 폭증(c=4 에서 24개).

**단, 이 환경(SQLite/mock)에서 로딩 비중은 1.8% → 2.3% → 2.2% 였고, 규모가 커질수록
`simulating` 비중이 오히려 91.6% → 96.5% → 97.4% 로 커진다.** 즉 large 에서 로딩을
**0초로 만들어도 2.2% 절약**이다 — 벌크 로딩의 상한이 그만큼 낮다.
Postgres 풀(15) 경합은 여기서 재현 불가이며 **가설로 남는다**(리스크 R4).

### 3.6 규모 — 선형이지만 절대값이 크다

| 규모 | 종목×거래일 | 벽시계 | 종목·일당 | RSS |
|---|---|---|---|---|
| small | 5,200 | 17.2s | 3.30 ms | 90 MB |
| medium | 78,100 | 182s | 2.33 ms | 121 MB |
| **large** | **479,975** | **1,152s (19.2분)** | **2.40 ms** | **247 MB** |

숨은 2차 항은 없다 — 비용은 **종목·일 단위 파이썬 작업**에 그대로 비례한다.
`eval_cap` 상한 4,000 × 10년(~2,470일)에 이 단가를 외삽하면 **단일 스레드로 ~6.6시간**
이고, GIL 때문에 동시 실행은 그것을 **더 느리게** 만든다. (외삽이며 실측이 아니다.)
메모리도 실행당 247 MB 라 상한 없는 동시성과 곱해진다 — 8개면 ~1.9 GB.

### 3.5b 기준선에 대한 정직한 메모

P4-V 는 pytest 를 **1,952 passed / 1 failed** 로 기록했고, 그 1건
(`test_alpha_portfolio_gate::test_a_past_as_of_changes_the_portfolio`)을
`daily_prices` 부재로 인한 사전 환경 실패로 적었다. **오늘 재 보니 1,953 passed /
0 failed 다.**

★고쳤다고 주장하지 않는다★ 이 감사는 프로덕션 코드를 한 줄도 바꾸지 않았고,
`daily_prices` 는 **여전히 없다**(직접 확인). 그 테스트는 mock 시세로 서로 다른
`as_of` 가 다른 포트폴리오를 내는지 보는데, 날짜·환경에 따라 결과가 갈릴 수 있다.
즉 **그 실패는 환경/날짜 의존이었고 오늘은 재현되지 않았다** — 그 이상은 모른다.
(하네스가 `daily_prices` 에 write-back 했을 가능성을 먼저 의심했으나, 테이블이
여전히 없는 것을 확인해 기각했다.)

### 3.5 관측성

`perf_counter`·RSS·쿼리 카운터가 **어디에도 없다**. `time.time()` 은 id·하트비트용뿐.
프롬프트가 요구한 큐 대기·CPU 시간·피크 RSS·워커 ID·쿼리 수/시간·캐시 적중률·
결과 크기 중 **하나도 기록되지 않는다.**

---

## 4. 없는 것 (기능 공백)

1. **Company 언더라이팅** — 역DCF · 확률적 밸류에이션(P10~P90) · **CompanySnapshot** ·
   구조화된 논지/kill 조건 · Company 매크로 민감도. 다섯 항목 전부 **0건**(전수 grep).
   ★프롬프트가 든 7개 업그레이드 중 **2개(이익의 질 · ROIC vs WACC)는 이미 구현돼 있다**★
   — `financial_deep` 이 발생액·OCF-NI 갭·red flag·듀폰·ROIC-WACC 스프레드를 계산한다.
   (이 문서 초안은 그 둘을 "없음" 으로 적었다. `head` 로 잘린 grep 결과를 결론으로 쓴
   측정 실수였고, 전수 확인으로 정정했다.)
2. **THESIS → SIGNAL → BACKTEST 다리** — 파이프라인에서 유일하게 끊긴 칸.
3. **백테스트 관측성** — §3.5.
4. **프로세스 격리** — §3.1·§3.3 의 공통 해법.

---

## 5. ★바꾸면 안 되는 것★ (CLAUDE.md 불변식 + 이번 감사가 확인한 강점)

| 불변식 | 근거 |
|---|---|
| 스크리너 3-레이어 · `ValuationScreener` · 백테스트 엔진 동작 방식 | CLAUDE.md 명시 — 리팩터 대상 아님 |
| `mock_gate.mock_allowed()` 단일 판정, `KIS_USE_MOCK == "1"` 일 때만 mock | 운영 결측은 `None`/빈값. 합성값 금지 |
| 실거래 6중 안전장치 · `dry_run=True` · `OrderExecutor` 우회 금지 | `tests/test_no_order_executor_bypass.py` 가 CI 정적 강제 |
| `fastapi==0.111.0` · `uvicorn --workers 1` | 워커 증설은 프로세스 로컬 상태 이전이 **먼저** |
| CSS 클래스명 = E2E 계약 (`data-testid` 미사용) | 48 스펙 422건 |
| **하트비트 + `sweep_orphaned()` 고아 복구** | 이미 동작. 재작성 금지, **재사용** |
| **취소(협조적 `_Cancelled`) · 재시도(이력 불변) · 진행률 throttle** | 이미 동작 |
| **`touch_progress` 커넥션 절약** | 이벤트당 3회 → 1회 체크아웃. 이미 적용된 최적화 |
| PIT: 관측일 ≠ 공표일, ALFRED 빈티지, `derive_usage()` 게이트 | P4-MACRO 가 세운 계약 |
| TPV 실행 게이트 (`status != executable` → 거부) | R0 가 세운 안전선 |

---

## 6. 아키텍처 안 비교

| | **A 프로세스 워커풀** | **B Postgres SKIP LOCKED 큐** | C Redis/Celery | D 전용 시뮬 서비스 |
|---|---|---|---|---|
| 정합성(§3.1) 해결 | **✔ 근본** — 전역이 프로세스마다 별개 | ✘ 자체로는 안 됨(워커가 스레드면 그대로) | ✘ 동일 | ✔ |
| GIL 우회 | **✔ 4코어=4배** | 워커가 프로세스면 ✔ | ✔ | ✔ |
| 메모리 격리 | **✔ 프로세스 경계** | 워커 형태에 종속 | ✔ | ✔ |
| 취소 | 현행 `_Cancelled` 신호를 프로세스 경계로 옮김 (중간) | DB 플래그 폴링(현행과 동일) | 브로커 취소 | RPC |
| 재시작 복구 | **기존 `sweep_orphaned` 그대로 재사용** | 큐가 원자적으로 보장(더 강함) | 브로커 의존 | 서비스 재기동 |
| 다중 API 인스턴스 | ✘ (프로세스 로컬 풀) | **✔** | ✔ | ✔ |
| 새 인프라 | **0** | **0** (Postgres 이미 있음) | Redis + 워커 (신규) | 서비스 + 배포 |
| 로컬 개발 | **변화 없음** | 변화 없음 | 브로커 필요 | 오케스트레이션 필요 |
| 복잡도 | **낮음** | 중간 | 높음 | 높음 |

### 권고 — **A 를 먼저, B 를 다음 층으로**

**A** 가 §3.1(정합성) · §3.3(GIL) · 메모리 격리를 **한 번에** 닫으면서
새 인프라를 0개 추가하고, 이미 검증된 `backtest_runs` 영속 · 하트비트 ·
`sweep_orphaned` · 취소 · 재시도를 **그대로 재사용**한다.

**B** 는 API 인스턴스가 여럿이 될 때 필요해지는 다음 층이다. 지금은 `--workers 1`
이라 큐의 원자성이 사 줄 것이 적다. A 를 먼저 넣으면 B 로 가는 길이 막히지 않는다 —
워커가 이미 프로세스이므로 디스패치만 DB 큐로 바꾸면 된다.

**C 는 채택하지 않는다.** 프롬프트가 금지한 "유행이라서" 에 해당하고, 이 감사가
찾은 문제 중 Redis 가 푸는 것은 하나도 없다. **D 는 시기상조** — 배포 표면을 늘리기
전에 A 의 실측을 봐야 한다.

★`uvicorn --workers 1` 불변식과 충돌하지 않는다★ 이 안은 **API 워커를 늘리는 것이
아니라 CPU 작업을 API 프로세스 밖으로 빼는 것**이다. 프로세스 로컬 캐시·DART 쿼터
카운터는 API 프로세스에 그대로 남는다.

---

## 7. 마이그레이션 전략

1. **정합성 먼저, 격리 다음.** `_generate_signal_as_of` 의 전역 몽키패치를 제거해
   전략이 데이터를 **인자로** 받게 한다. 이것만으로 §3.1 이 닫히고 §3.2 의 75.7% 가
   줄어든다. 프로세스 풀이 없어도 유효한 수정이다.
2. **워커 프로세스 1개**로 먼저 전환(동시성 1). 취소·하트비트·복구가 프로세스
   경계에서 그대로 동작하는지 확인.
3. **동시성 상한 N** 으로 확장. N 기본값은 `min(cpu_count-1, 4)` 를 실측으로 확정.
4. **텔레메트리**를 워커에 심는다(§3.5 목록). 이후 최적화는 전부 이 숫자 위에서 한다.
5. 그 다음에야 `calc_ma` 사전계산 · 벌크 로딩 · NumPy. **프롬프트의 성능 순서를 지킨다.**

각 단계는 단독 revert 가능하고, 백테스트 pytest 9개 파일이 회귀를 잡는다.

---

## 8. 리스크 레지스터

| # | 리스크 | 심각도 | 완화 |
|---|---|---|---|
| R1 | 몽키패치 제거가 12종 전략의 신호를 바꾼다 | **높음** | 제거 전후 **동일 입력 결과 바이트 비교**를 게이트로. 다르면 그 차이가 곧 §3.1 의 크기 |
| R2 | 프로세스 경계에서 취소가 안 걸린다 | 높음 | 현행 협조적 취소는 DB 상태 폴링 기반 — 프로세스에서도 같은 신호를 쓴다. 취소 테스트 선행 |
| R3 | 프로세스 간 DB 커넥션이 N배 | 중간 | 워커당 풀 크기를 명시적으로 작게. Postgres 환경에서 재측정 |
| R4 | mock 형상에서만 검증됨 | **중간** | 모든 표에 라벨. 하네스를 Postgres 환경에서 재실행하는 것을 P0 완료 조건에 넣음 |
| R5 | 직렬화 비용(프로세스 간 결과 전달) | 중간 | 결과는 이미 DB 경유(`set_result`) — 프로세스가 직접 쓰면 IPC 불필요 |
| R6 | Company 확장이 DART 쿼터(20,000/일)를 태운다 | 중간 | CompanySnapshot 캐시가 곧 쿼터 방어. 미가용 카운트를 관측성에 포함 |

---

## 9. 테스트 전략

- **회귀 보호막(이미 있음)**: 백테스트 pytest 9개 파일, Playwright 48 스펙 422건.
- **신규 게이트 셋**:
  1. ★전역 무오염★ — 동시 실행 후 `fetcher.get_daily_prices` 가 원본이다.
     지금 코드에서는 **반드시 red** 여야 한다(그것이 결함의 증명이다).
  2. ★결정론★ — 같은 입력 2회 실행이 **바이트 동일** 결과. 동시 실행 중에도 성립.
  3. ★동시 처리량★ — 동시 N 의 실행당 시간이 순차보다 **나쁘지 않다**.
- **변이 프로브**: 각 가드마다 보호 대상을 되돌려 red 를 확인한다.
  이 저장소가 반복해 값을 치른 원칙 — 프로브를 돌리지 않은 가드는 가드가 아니다.

## 10. 성공 지표

| 지표 | 현재 (실측) | 목표 |
|---|---|---|
| 동시 실행 후 전역 오염 | **발생 (`true`)** | 0 |
| 동시 4 실행 vs 순차 4 | **63% 느림** | 순차보다 빠름 (4코어에서 ≥2배) |
| CPU 사용률 (동시 4) | **105%** | ≥ 300% |
| `_generate_signal_as_of` 비중 | **75.7%** | ≤ 30% |
| 백테스트 텔레메트리 항목 | **0** | 12 (프롬프트 목록 전부) |
| pytest / Playwright | 1,953 / 422 | 감소 없음 |

---

# 부록 A — `.md` 마스터 프롬프트 요구사항 보강 (2차 감사)

1차 감사는 짧은 `.txt` 판을 따랐다. 상세 `.md` 판이 추가로 요구한 절을 여기 채운다.

## A.1 (§3.B) 역량 매트릭스 — 7열

`Duplicate` 열이 이 표의 핵심이다. **없는 것을 짓기 전에 있는 것을 먼저 본다.**

| 역량 | Exists | Partial | Missing | Duplicate | Risk | 재사용 후보 |
|---|:--:|:--:|:--:|---|---|---|
| 백테스트 잡 영속·폴링·취소·재시도 | ✔ | | | | 낮음 | `backtest_runs.py` 그대로 |
| 고아 복구(하트비트+sweep) | ✔ | | | | 낮음 | `sweep_orphaned()` |
| **프로세스 격리** | | | **✘** | | **높음** | — (P0-2) |
| **백테스트 텔레메트리** | | **5/10** | | | 중간 | 하네스 계측을 워커로 이식 |
| PIT 빈티지(매크로) | ✔ | | | | 낮음 | `pit_macro.derive_usage()` |
| PIT 스토어(재무) | ✔ | | | | 낮음 | `pit_store.py` |
| 생존편향 안전 유니버스 | ✔ | | | | 낮음 | `tickers_asof` · `top_mktcap_asof` |
| **경제노출 ↔ 상품 분리** | | | **✘** | | **높음** | — (A.4) |
| 국면 추정(축·Markov·GMM) | ✔ | | | | 낮음 | `regime_ensemble.py` |
| 포워드 국면분포·전이 | ✔ | | | | 낮음 | `regime_transitions.k_step_forecast` |
| 모델 불일치 | | ✔ 매크로 탭만 | | | 중간 | `ensemble.disagreement()` |
| **조건부 μ/Σ/tail** | | | **✘** | | **높음** | `regime_adaptive_allocator` 의 EWMA Σ |
| 자산배분 옵티마이저 | ✔ | | | **AAS ↔ 다전략 2계통** | **중간** | `allocation_studio.py` |
| Entropy Pooling / BL | ✔ | | | | 낮음 | `entropy_views.ep_posterior_mu()` |
| **Target range** | | | **✘** | | 중간 | `disagreement()` 로 유도 |
| **리밸런싱 정책** | | | **✘** | | **높음** | `build_plan` 앞단에 얹기 |
| 실행 게이트(TPV) | ✔ | | | | 낮음 | `_resolve_target` |
| 반사실 귀인 | ✔ | | | | 낮음 | `counterfactual_analyzer.py` |
| 밸류에이션 RIM/DCF/DDM | ✔ | | | | 낮음 | `valuation_models.py` |
| 이익의 질 · ROIC−WACC | ✔ | | | | 낮음 | `financial_deep` |
| **역DCF · 확률적 밸류에이션** | | | **✘** | | 중간 | `compute_dcf` 역산/감싸기 |
| **CompanySnapshot** | | | **✘** | | **높음** | `regime_snapshots.py` 관례 |

### ★Duplicate — 배분 계통이 둘이다★

| 계통 | 구성 | 소비자 |
|---|---|---|
| **AAS** | `allocation_studio.py` — MVO/BL/EP/HRP/RP/MinVar/MaxDiv/MinCVaR | Allocation Studio 11스테이지 |
| **다전략** | `MultiStrategyAllocator` + `regime_adaptive_allocator.py` — **EWMA 공분산 · 상관붕괴 감지 · 3모드** | `realism_engine` · `stage12_routes` |

★후자에 이미 조건부 공분산이 있다★ 브리프가 원하는 regime-conditional Σ 의 절반이
**다른 계통에 구현돼 있다.** 통합·재사용 판단을 새 설계 문서에서 다룬다.

## A.2 (§3.D) Company 실행맵

```
/insights (frontend/src/app/insights/page.tsx)
  └─ loadCompanyCore(code)                      entities/company/data.ts:152
       wave1 (병렬 3)  byTicker → POST /screener/run-advanced (custom_tickers=[code])
                      factorSample(600) → GET /screener/factor-sample
                      fieldsCatalog
       wave2 (병렬 7)  evaluate ×3 (base/bull/bear) → POST /valuation/evaluate
                      financial(annual) · financial(quarter) → GET /valuation/financial/{code}
                      prices(400) · peersBySector
  └─ 별도 탭          financialDeep · riskDeep · valuationSandbox → /company/{code}/*

POST /valuation/evaluate → ValuationEngine.evaluate()      valuation_models.py:421
   → get_corp_code() → dart.get_financial_statement_full() → RIM + DCF + DDM
   → DART 디스크 캐시 7일 TTL                              dart_client.py:75
/company/{code}/financial-deep → company_analytics.financial_deep()
   → _annual_rows() → dart_history.load_history()          company_analytics.py:228
```

**실측**(`scripts/bench_company.py`, 벤치 문서 §6.5):

| 관측 | 값 |
|---|---|
| 콜드 페이지 로드 | 83 ms (엔드포인트 8개) · 웜 43 ms |
| 페이지 로드 DB 쿼리 | 18 |
| **`comps_table` 단독** | **DB 48 쿼리** |
| **`risk_deep` 내부 중복** | 한 호출에서 `_annual_rows` **2회** · `load_history` **2회** |
| 딥 탭 합계 | DB 52 쿼리 · 같은 재무이력 **3회** 읽기 |
| DART 호출 | **0 (키 미설정)** → 캐시 적중률 **측정 불가** |

**반복 계산**: `evaluate` 가 3번 도는데 셋은 `terminal_growth`·`market_premium` 만
다르고 재무 데이터는 동일하다. ★이 환경에서는 그 비용이 0.2ms 로 보이지 않는다★ —
DART 키가 없어 mock 재무로 계산하기 때문이다. 실 키에서 재측정해야 한다.

**누락 캐시**: 재무이력을 읽는 층(`_annual_rows`/`load_history`)에 캐시가 없다.
CompanySnapshot 이 그 자리다.

## A.3 (§3.E) 병목 가설표 — 신뢰도 등급

| # | 결론 | 신뢰도 | 근거 |
|---|---|---|---|
| 1 | **GIL/파이썬 CPU 루프가 백테스트의 천장** | **높음** | 4코어에서 동시 1/2/4 의 CPU 사용률 107/103/105% 고정. 동시 4가 순차 4보다 63% 느림 |
| 2 | **동시 실행이 전역을 오염시킨다(정합성)** | **높음** | 샘플 95.9%가 패치 상태 · 두 실행 데이터가 같은 전역에 관측 · 정상 종료 후에도 오염 `true` |
| 3 | 시뮬 루프가 지배적 비용 | **높음** | 단계 비중 88~97%, 3규모 일관 |
| 4 | 직렬화는 병목이 아니다 | **높음** | 12.4 ms = 0.09% |
| 5 | 폴링은 유의한 부하가 아니다 | **높음** | 1회 0.144 ms · 1쿼리 · 분당 60쿼리 |
| 6 | 메모리 압박은 단일 실행에서 경미, **동시성과 곱해지면 문제** | **중간** | 실행당 RSS +90~247 MB. 상한이 없어 8개면 ~1.9 GB(외삽) |
| 7 | **DB 풀 기아** | **낮음 — 미검증** | SQLite 폴백이라 `pool_size=5+overflow=10` 을 재현 못 함. 로딩 비중은 1.8~2.3% |
| 8 | 컨테이너/프로세스 수명 실패 | **중간** | `daemon=True` 라 재시작 시 in-flight 유실. `sweep_orphaned` 가 사후 정리는 함 |
| 9 | API 기아 | **중간** | 워커가 API 와 같은 GIL 점유. 별도 측정 필요 |
| 10 | Company 콜드 지연 | **낮음 — 형상 다름** | mock 재무·DART 키 없음. 실 키에서 재측정 |

## A.4 (§26 · Brief §7) 투자가능 유니버스 계층 감사

| 계층 | 실재 |
|---|---|
| 상품 유형 식별 | ✔ `kis_master_parser.py:152` 가 그룹코드 `ST/EF/EN/RT`(주권·ETF·ETN·리츠) 파싱, `universe_select.py:101` 이 사용 |
| 상장/정지/상폐 상태 | ✔ `_status_codes()` · `tickers_asof()` (상폐 포함 시점 유니버스) |
| **경제노출 ↔ 상품 분리** | **✘ 0건** |
| **상품 선택기**(유동성·스프레드·추적오차·보수) | **✘** |
| 리스크팩터 노출 계층 | 부분 — 팩터는 종목 레벨(`FIELD_BY_ID`)에 있고 자산군 레벨에는 없다 |

★증상★ `etf_prices.py:65` 가 `VNQ`(미국 리츠)와 `REM`(모기지 리츠)을 **같은 종목
182480(TIGER 미국리츠)** 에 매핑한다. 서로 다른 경제노출이 한 상품으로 접힌다 —
분리 계층이 없다는 사실이 데이터에 그대로 드러난 자리다.

매크로 자산군은 미국 티커 프록시(`SPY`·`TIP`·`GLD`·`DBC`·`VNQ`·`BIL`)로 표현되고
(`macro_visuals.py:95` · `risk_allocations.py:31`), 국내 상장 ETF 로의 매핑이
`etf_prices.py` 에 **평면 딕셔너리**로 있다. optimizer 는 경제노출이 아니라 **상품**을
직접 최적화한다.
