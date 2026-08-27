# 능력-계보 감사 — Data → Research → Model (읽기 전용)

> 기준 커밋 `5fbf817` · 선행: [`데이터 추출 감사`](2026-08-26-data-extraction-audit.md) ·
> [`능력 활용 행렬`](2026-08-26-capability-utilization-matrix.md) ·
> [`능력 6상태 행렬`](2026-08-27-capability-states-matrix.md)
>
> ★이 감사는 코드를 고치지 않았다★ 아래 수치는 전부 실제 소스코드·DB 에서 **실측**했다.
> 목표는 API 활용률 극대화가 **아니다** — 기존 실데이터 능력이 **어디에서 신뢰 가능한
> 재사용 연구 입력이 되지 못하고 멈추는지**를 찾는 것이다.

---

## 0. 어휘 충돌을 먼저 해소한다 — ★증거등급은 `E0~E5`★

증거 사다리를 `L0~L5` 로 쓰면 저장소와 **정면 충돌**한다:

| | 기존 `src/engine/capability.py` | 증거 사다리 |
|---|---|---|
| 정의 | `LEVEL_ORDER = ("L0","L1","L2","L3")` | synthetic → economically validated |
| **L0 의 뜻** | ★최상★ "Full Frontier" (torch·cvxpylayers 가용) | ★최하★ synthetic |

게다가 `regime_snapshots.capability_level` 에 **실제 값이 들어 있다**
(실측: `L1` 67행 · `L3` 126행). 같은 문자열이 한 저장소에서 정반대를 뜻하게 된다.

★그래서 증거 사다리는 `E0~E5` 로 쓴다.★ 두 축은 직교하므로 한 스냅샷이
**"모델역량 L3 · 증거등급 E0"** 처럼 동시에 서술된다.

| 등급 | 뜻 |
|---|---|
| **E0** | 합성 — mock/결정론적 생성 |
| **E1** | 저장소 픽스처 — 체크인된 소량 표본 |
| **E2** | 제공자 파생 — 실 응답에서 유도했으나 원본 미보존 |
| **E3** | 실 과거 데이터 — 원본 보존 |
| **E4** | 시점 고정 실 과거 데이터 — 빈티지로 재현 가능 |
| **E5** | 경제적으로 검증됨 — 표본외에서 의미가 확인됨 |

---

## A. 능력-계보 행렬

범례: ✔ 있음 · ✗ 없음 · ◐ 부분 · **호출부 0** = 구현됐으나 파이프라인 없음

### A.1 KRX

| 능력 | 구현 | 호출 | 적재경로 | 영속 | 출처 | PIT | 품질검사 | 피처 | 백테스트 | 블로커 | 계층 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 전종목 일별시세 `get_daily_all` | ✔ | ✔ | `krx_ingest.backfill` | `daily_prices` | ✔ `source='krx'` | ✗ | ✔ `price_quality` | ◐ | ✔ | ★이 환경에 테이블 자체가 없음★ | 데이터 |
| 지수 일별 `get_index_daily` | ✔ | ✔ `krx_ingest:196,253` | `backfill_index` | `daily_prices` | ✔ | ✗ | ◐ | ✗ | ◐ | 소비자 얕음 | 데이터 |
| **VKOSPI** `/idx/drvprod_dd_trd` | ✔ | ★**0**★ | 없음 | ✗ | — | ✗ 영구 | `not_ingested` 선언됨 | ✗ | ✗ | 배선 없음 | 데이터 |
| **신용잔고** `mgn_bydd_trd` | ✔ | ★**0**★ | 없음 | ✗ | — | ✗ 영구 | 선언됨 | ✗ | ✗ | 배선 없음 | 데이터 |
| **공매도** `shrt_bydd_trd` | ✔ | ★**0**★ | 없음 | ✗ | — | ✗ 영구 | 선언됨 | ✗ | ✗ | 배선 없음 | 데이터 |
| **대차** `lend_bydd_trd` | ✔ | ★**0**★ | 없음 | ✗ | — | ✗ 영구 | 선언됨 | ✗ | ✗ | 배선 없음 | 데이터 |

★실측★ `get_extra` 의 유일한 호출부는 `verify_connection.py:480`(진단 스크립트).
`src/` 안에는 **0건**.

### A.2 KIS

| 능력 | 구현 | 호출 | 적재경로 | 영속 | 출처 | PIT | 피처 | 백테스트 | 블로커 |
|---|---|---|---|---|---|---|---|---|---|
| 일봉 `get_daily_ohlcv` | ✔ | ✔ 3곳 | `ohlcv_loader.ingest_df_to_db` | `daily_prices` | ✔ `source`·`price_basis` | ✗ | ✔ | ✔ | ★`close` 정의 혼합★ |
| 현재가 `get_current_price` | ✔ | ✔ 3곳 | 온디맨드 | ✗ | — | ✗ | ✗ | ✗ | 실시간 전용 |
| 투자자별 `get_investor_daily` | ✔ | ✔ 1곳 | `kis_flows` | `investor_flows` | ◐ | ✗ | ◐ | ✗ | 소비 얕음 |
| 분봉 `get_minute_bars_*` | ✔ | ✔ | `minute_bars` | ★✗ 온디맨드★ | — | ✗ | ✗ | ◐ `kis_backtest_engine:1144` | 미영속 |
| 마스터(ISIN·업종) | ✔ | ✔ | `kis_master_parser` | 파일+`instrument_master` | ✔ `as_of` | ✗ | ✔ | ✗ | 이 환경 비어 있음 |
| 주문 4종 | ✔ | ✔ | `TradingEngine` | `live_*` 5테이블 | ✔ | — | — | — | — |

### A.3 FRED

| 능력 | 구현 | 호출 | **영속** | 출처 | PIT | 개정 | 소비자 | 블로커 |
|---|---|---|---|---|---|---|---|---|
| `series/observations` | ✔ `macro_collector.FREDClient` | ✔ | ★**✗ 프로세스 dict 캐시**★ | ◐ | ✗ | 최신개정본 | 대시보드·**국면 축** | ★영속 없음★ |
| **ALFRED 빈티지** `fetch_observations` | ✔ `pit_macro` | ✔ | ✗ 온디맨드 | ✔ `vintage_id` | ✔ | ✔ | ★**1곳**★ `timing_rules_v2` | 저장할 곳이 없다 |

★실측★ `macro_collector` 의 캐시는 `self._cache: dict[str, tuple[float, MacroSeries]]`
— **프로세스 메모리**다. FRED/ECOS 시계열 전용 테이블은 저장소에 **존재하지 않는다**.

### A.4 ECOS

| 능력 | 구현 | 호출 | 영속 | PIT | 블로커 |
|---|---|---|---|---|---|
| `StatisticSearch` (`macro_collector.BOKClient`) | ✔ | ✔ | ★✗ 프로세스 캐시★ | ✗ (개정 없음·영구) | 영속 없음 |
| `StatisticSearch` ★두 번째 클라이언트★ | ✔ `kis_strategies/factor_tokens.py:636,690` | ✔ | ✗ 모듈 `_ecos_cache` | ✗ | ★중복 수집 경로★ |
| `StatisticTableList`·`ItemList` | ✔ (`BokClient._fetch_meta`) | 스크립트에서만 | — | — | ★응답 필드명 미검증★ |
| `KeyStatisticList` | ★✗ 미구현★ | — | — | — | 소비자 없음 |

★해소됨★ ECOS 클라이언트가 **둘**이었다(`macro_collector.BOKClient` 와
`factor_tokens._ecos_series` 가 각자 URL·캐시). `1fa4fbd` 에서 일원화했다 —
지금 `BokClient` 하나뿐이다.

★새 발견 (부록 10)★ 비파생 **37계열 전부가 월별(`period="M"`)로 조회된다.**
`ecos_collection_targets()` 가 주기를 돌려주지 않고 수집기가 `period` 를 넘기지
않기 때문이다. 그 안에 일별(기준금리·국고채·환율·KOSPI)과 분기로 보이는 것
(GDP·경상수지)이 섞여 있다.

### A.5 DART

| 능력 | 구현 | 호출 | 영속 | PIT | 블로커 |
|---|---|---|---|---|---|
| `company.json` | ✔ | ✔ 4곳 | `company_snapshots` | ✗ | — |
| `fnlttSinglAcnt(All)` | ✔ | ✔ 4·5곳 | `financials_history` | ★✗ `has_vintage=False` 명시★ | 개정 미관리 |
| **`alotMatter`(배당)** | ✔ | ✔ 2곳 | ★**✗ CREATE TABLE·INSERT 0건**★ | ✗ | 미영속 |
| **`elestock`(지분)** | ✔ | ✔ 1곳 | ★**✗ 0건**★ | ✗ | 미영속 |
| 공시검색·원문·분할공시 | ★✗ 미구현★ | — | — | — | 구현 없음 |

### A.6 파생 인프라

| 능력 | 상태 | 소비자 | 블로커 | 계층 |
|---|---|---|---|---|
| `adj_close` | ✔ 계산·영속 | ★**프로덕션 소비자 0**★ (`kis_models.py:76` 스키마 선언뿐) | 전환은 배분 경로 | ★정책★ |
| `price_basis`/`source` | ✔ (Phase 2) | `price_quality` 만 | 보고 전용 | 데이터 |
| `mktcap`·`list_shares` | ✔ **KRX 만 씀** | `universe_select.py:297` | ★KIS 전용 티커는 유니버스에서 조용히 빠진다★ | 데이터 |
| `regime_snapshots` PIT 파이프라인 | ✔ 완비 | 국면 축이 **안 탄다** | 배선 | ★정책★ |
| 피처 스토어 6종 | `DeterministicMockStore` 상속 | 광범위 | 키 없으면 mock | 데이터 |

---

## B. 가장 큰 아키텍처 병목 셋

### B1. ★매크로 시계열에 영속 계층이 없다★ (가장 깊다)

FRED·ECOS 시계열은 **프로세스 dict 캐시**에만 산다. 영구 아티팩트는
`regime_snapshots.observations` JSON 블롭 하나뿐이고, 그것은 **파생 스냅샷**이지
원천 시계열이 아니다. 결과:

- 재시작하면 사라진다 → **과거 매크로 실험을 재현할 수 없다.**
- `uvicorn --workers 1` 고정이 강제되는 이유와 **같은 뿌리**다(CLAUDE.md).
- ALFRED 빈티지 경로가 있는데도 **저장할 곳이 없어** 소비자가 하나뿐이다.

### B2. ★가격 의미 계약이 갈라져 있다★

`close` 가 KRX 원주가와 KIS 수정주가를 함께 담고(Phase 2), `mktcap` 은 KRX 만 쓰고,
`adj_close` 는 소비자가 0이며, **배당은 어디에도 없다**. 그리고 이 환경에는
`daily_prices` 테이블 **자체가 없다**(실측 — `risk_system.db` 19테이블 중 부재).

### B3. ★피처 계층이 mock 기본값이다★

`price_factors_store`·`fundamentals_store`·`graph_store`·`liquidity_gate`·
`vector_store`·`sentiment_worker` 가 전부 `DeterministicMockStore` 를 상속한다.
즉 **영속된 실데이터에서 유도된 피처가 아니라** 키가 없으면 결정론적 합성값이다.
계보가 "데이터 → 피처" 에서 끊긴다.

---

## C. 미사용 능력 — ★"어떤 연구 질문을 여는가" 로만 판정★

| 순위 | 능력 | 여는 연구 질문 | 판정 |
|---|---|---|---|
| **1** | **FRED ALFRED 빈티지 영속화** | *"오늘의 국면 판정이 **그때도** 같았는가?"* — 지금은 답할 수 없다. `regime_snapshots` 관측치 5,790개의 `vintage_id` 가 **전부 빈 문자열**(실측). 개정 편향의 크기를 **한 번도 잰 적이 없다.** | ★최고★ |
| **2** | **DART `alotMatter`(배당)** | *"우리 수익률은 총수익률인가?"* — 아니다. 가격 사슬 어디에도 배당이 없고 `return_1d`(KRX `FLUC_RT`)는 기준가 대비라 **분할·증자만** 제거한다. 한국 주식 배당수익률은 무시할 수 없어 장기 성과가 **체계적으로 저평가**된다. | 높음 |
| **3** | **ECOS 메타 3종** | *"이 계열의 단위·주기·공표지연이 무엇인가?"* — 지금은 `timing_factor_meta` 에 **손으로** 적혀 있다. 메타를 받아오면 그 손 표를 검증할 수 있다. | 중 |
| — | **KRX `get_extra` 4종** | ★구체적 연구 질문을 찾지 못했다★ KRX 는 빈티지가 없어 이 4계열은 **영구 forward-only**. 배선해도 백테스트 적격 데이터가 **한 줄도 늘지 않는다**. | ★낮음★ |
| — | ETF 메타데이터 | 어느 게이트도 요구하지 않는다. `exposure_taxonomy` 가 이미 체크인된 증거로 55종을 분류한다. | 낮음 |
| — | `adj_close` 소비 전환 | 질문은 크지만 **정책 계층**(배분 경로). | 보류 |

★쉽다는 이유로 순위를 올리지 않았다.★

---

## D. 단일 최고가치 다음 구현 — ★매크로 관측 스토어★

`src/data/macro_observation_store.py` — **빈티지를 갖는 매크로 관측치의 영속 계층**.

| 기준 | 평가 |
|---|---|
| 정확성 영향 | ★높음★ 매크로 이력이 재현 불가능한 상태를 끝낸다 |
| 기존 연구 재사용 | ★높음★ 모든 매크로 실험이 같은 원천을 읽게 된다 |
| PIT 안전 | ★최고★ 이것이 PIT 의 **기반**이다 — `vintage_id` 가 저장될 곳이 생긴다 |
| 불가능했던 질문 | ★"개정 편향이 얼마인가" 를 처음으로 **잴 수 있게** 한다★ |
| 비용 | 중 — `pit_macro.MacroObservation`·`instrument_master_store` 패턴 재사용 |
| 정책 독립성 | ★✔ 스토어는 순수 데이터 인프라★ |

### ★3개 단계 동안 미뤄진 항목이 왜 이제 가능한가★

"FRED 빈티지 → 국면 축" 은 계속 *"배분 경로라 별도 승인"* 으로 미뤄졌다. 그것은
**두 개의 일**이 하나로 묶여 있었기 때문이다:

    ① 빈티지를 저장한다        ← 데이터 인프라 · ★지금 해도 된다★
    ② 국면 축이 그것을 읽는다   ← 정책 배선 · 별도 승인

①만 떼면 하드 경계를 전혀 건드리지 않는다. 그리고 ① 없이는 ②를 해도 저장할 곳이
없다 — ★①이 빠진 전제였다.★

---

## E. 파일·모듈 (구현 승인 시)

| 파일 | 성격 | 내용 |
|---|---|---|
| `src/data/macro_observation_store.py` | ★신규★ | `macro_observations` 테이블 · `save()`/`load()`/`vintages_of()` |
| `src/data/pit_macro.py` | 재사용 | `MacroObservation`(이미 있음) · `derive_usage` |
| `src/data/instrument_master_store.py` | ★패턴 원본★ | 저장 원시함수 규약 — 절대 raise 안 함 · DB 없으면 0 · 부작용 없음 |
| `src/services/macro_collector.py` | 독스트링만 | 프로세스 캐시라는 사실을 명시 |
| `src/api/data_routes.py` | 관측 | `GET /api/v1/data/macro-vintages` |

★건드리지 않는 것★ `regime_axes.py` · `allocation_routes.py` · `constrained_solve` ·
`timing_rules_v2` 판정 로직 · `src/engine/` 전체.

---

## F. 테스트 · 변이 테스트

| # | 못 박는 것 |
|---|---|
| M1 | 왕복 — `vintage_id`·`release_timestamp`·`retrieved_at` 전부 보존 |
| M2 | ★같은 기간의 **여러 빈티지**가 공존★ — 개정본이 이전본을 덮지 않는다 |
| M3 | ★짝★ 같은 `(series, period, vintage_id)` 재저장은 멱등 |
| M4 | 빈 `vintage_id` 는 **빈 채로** 저장 — 추정하지 않는다 |
| M5 | `as_of` 조회가 그 시점 **이후** 공표본을 제외 |
| M6 | DB 없으면 `save()` 가 0 반환, raise 안 함 |
| M7 | `load()` 가 없으면 `{}` (0 아님) |
| M8 | 등급은 `pit_macro.derive_usage()` 를 **호출** — 두 번째 체계 금지 |

| 변이 | 죽이는 테스트 |
|---|---|
| V1 최신 빈티지가 이전 것을 UPSERT 로 덮음 | M2 |
| V2 빈 `vintage_id` 를 `"latest"` 로 채움 | M4 |
| V3 `as_of` 필터 무조건 통과 | M5 |
| V4 DB 없을 때 예외를 던짐 | M6 |
| V5 `load()` 실패를 0행으로 보고 | M7 |
| V6 `derive_usage` 우회 | M8 |
| V7 멱등성 제거 | M3 |

★M2/M3 가 짝이다★ — 한쪽만 있으면 "무조건 덮기" 나 "무조건 쌓기" 로도 통과한다.

---

## G. 불변 검사

| # | 방법 | 무엇을 말하는가 |
|---|---|---|
| 1 | `git diff --stat HEAD -- src/engine/ src/api/allocation_routes.py` 비어 있음 | 정책 파일 무편집 |
| 2 | 골든 스냅샷 3종 바이트 동일 | 하네스 동작 불변 |
| 3 | 전체 스위트 3,063 + 신규 · ruff 0 | 회귀 없음 |
| 4 | ★`regime_axes` 가 새 스토어를 import 하지 않음★ | ①과 ②의 분리를 코드가 강제 |

★2번의 한계★ — 골든 하네스는 합성 데이터로 돌고 새 테이블을 읽지 않으므로,
바이트 동일은 무해함의 **증명이 아니다**. 실제 근거는 4번이며 테스트가 지킨다.

---

## H. 실제 제공자 데이터가 필요한가

| 대상 | 필요? |
|---|---|
| 스토어 **기계 검증**(M1~M8·V1~V7) | ★불필요★ — 합성 `MacroObservation` 으로 전부 검증된다 |
| **개정 편향을 실제로 재는 것** | ★필요★ — `FRED_API_KEY` 가 있어야 ALFRED 가 서로 다른 빈티지를 준다 |
| 증거등급 | 스토어만으로는 **E0**. 실키 적재로 **E3**, `as_of` 재현까지 **E4** |

★이 환경은 키가 하나도 없다★ — 실측: KRX·KIS·FRED·BOK·DART 전부 미설정, `.env` 없음.

---

## 부록 1. 실데이터 가용성 — ★E0~E5 실측★

| 데이터셋 | 실측 | 등급 |
|---|---|---|
| `daily_prices` | ★테이블 자체가 없음★ (`risk_system.db` 19테이블 중 부재) | **없음** |
| `regime_snapshots` | 193행 · `data_status='mock'` **전부** · `research_usage='forward_only'` 전부 · 관측치 5,790개 중 `vintage_id` 있는 것 ★0개★ | **E0** |
| `market_snapshot_ficc` | 267행 | **E0~E1** |
| `market_snapshot_equity` | 28행 | **E0~E1** |
| `backtest_runs`·`research_runs` | 18 · 6행 — 위 입력 위에서 돈 결과 | **E0** |
| `instrument_master` | 테이블 없음(경로만 생김) | **없음** |
| T3-A~D 매크로 실험 | 앞선 실측 `real_share = 0.0`(61계열 중 실데이터 0) | **E0** |

★결론★ 이 저장소의 모든 정량 결과는 현재 **E0(합성) — 기계 검증**이다. 경제적
주장으로 쓸 수 있는 것은 하나도 없다. 그것이 결함이 아니라 **현재 사실**이며,
이 감사가 바꾸려는 것은 그 사실을 **가릴 수 없게** 만드는 것이다.

---

## 부록 2. 가격 데이터 의미 계약 (★제안만★ — 배선하지 않음)

| 필드 | 오늘의 의미(실측) |
|---|---|
| `close` | ★두 값★ — `source='krx'` 원주가 · `source='kis'` 수정주가(`FID_ORG_ADJ_PRC="0"` 요청) · NULL 은 모름 |
| `return_1d` | KRX `FLUC_RT` — **기준가 대비** 등락률. 분할·증자 제거됨. ★배당 미포함★ |
| `adj_close` | `return_1d` 체인 역산. 앵커는 등락률을 쓸 수 있는 가장 최신 행(Phase 3). **분할조정 가격**이지 총수익 계열이 아님 |
| 배당 | ★가격 사슬 어디에도 없음★ (실측: `krx_ingest`·`ohlcv_loader`·`price_quality` 에 0건) |
| 기업행위 | 분할·증자만, `return_1d` 안에 **암묵적으로** 표현. 이벤트 테이블 없음 |
| KRX vs KIS | ★다르다★ — 위 `close` 행 |
| DART 기업행위 필요? | 배당은 **필요**(`alotMatter` 가 유일한 원천) · 분할은 `return_1d` 로 충분 |
| 이중조정 위험 | KRX 행: 없음. ★KIS 행에 `adj_close = close` 를 넣으면 위험★ — 이미 조정된 값에 체인을 다시 걸 수 있다. Phase 2·3 이 막아 뒀다 |

### 제안 계약

> **연구 수익률의 권위 있는 필드는 `adj_close` 이며, 그것은 "분할·증자 조정 가격
> 계열" 이다 — 총수익 계열이 아니다.** 총수익이 필요한 연구는 `alotMatter` 배당을
> 별도 계열로 결합해야 하며, `close` 는 **표시·체결가** 용도로만 쓴다.

★문서로만 제안한다★ — 소비자 전환은 배분 경로이므로 별도 승인이다.

---

## 부록 3. 다음 다섯 개 우선순위

| 순위 | 항목 | 정확성 | 재사용 | PIT | 불가능→가능 | 비용 | 정책독립 |
|---|---|---|---|---|---|---|---|
| **1** | ★매크로 관측 스토어★ | 높 | 높 | ★최고★ | ★개정 편향 측정★ | 중 | ✔ |
| **2** | ~~DART 배당 영속 + 총수익 계열~~ → ★배당기준일★ | 중 | 중 | 중 | 일별 총수익 계열 | 큼 | ✔ (부록 6 정정) |
| **3** | ECOS 클라이언트 **일원화** | 중 | 높 | 중 | (정합성) | 작 | ✔ |
| ~~4~~ | ~~`mktcap` 을 KIS 경로에도 기록~~ | — | — | — | — | — | ★회수(아래 §부록 4)★ |
| ~~5~~ | ~~ECOS 메타 3종~~ → ★주기 축★ | 중 | 높 | — | ★"왜 비었나" 에 답한다★ | 중 | ✔ (부록 10 정정) |
| — | KRX `get_extra` | ★낮★ | 낮 | ✗ 영구 | ★연구 질문 없음★ | 작 | ✔ |


---

## 부록 4. ★회수된 항목★ — `mktcap` 을 KIS 경로에 기록 (구 4순위)

**회수 사유: 올바르게 구현할 수 없다.** (`1fa4fbd` 이후 실측)

KIS 가 주는 시가총액 필드는 **하나뿐**이고 그것은 과거값이 아니다:

    kis_client.py:547  "market_cap_억": float(output.get("hts_avls") or 0)
                       ← get_current_price() — ★현재 스냅샷★

일봉(`get_daily_ohlcv`)에는 시총이 없다. 즉 KIS 경로로 `daily_prices.mktcap` 을
채우려면 **오늘의 시총을 과거 행에 적어야** 하고, 그것은 룩어헤드 날조다.

★그 컬럼의 소비자가 정확히 그것을 못 견딘다★:

    universe_select.mktcap_asof(ticker, date)
        "SELECT mktcap ... WHERE trade_date <= :d ORDER BY trade_date DESC LIMIT 1"
      → engine/pit_store.py:214      역사 PER/PBR 구성
      → universe_select.top_mktcap_asof → api/screener_routes.py:1513
                                          백테스트 시점 유니버스

시점 조회로 설계된 필드에 현재값을 넣으면 역사 밸류에이션과 백테스트 유니버스가
**동시에** 오염된다.

**남는 사실** — KIS 전용 티커는 `mktcap` 이 `NULL` 이라 시점 유니버스에서 조용히
빠진다. 그것은 여전히 참이지만, ★고치는 방법은 KRX 백필뿐이다★
(`krx_ingest.bulk_upsert` 가 `mktcap`·`list_shares` 를 쓰는 유일한 writer).

## 부록 5. FRED 레지스트리 미등록 (감사 항목 — 조치하지 않음)

`factor_tokens.FRED_TOKENS` 8종 중 `DGS1·3·5·7·20` 이 레지스트리에 없다.
★그러나 등록하지 않기로 했다★ — 셋 다 실측이다:

1. **등록은 무해하지 않다.** `fred_collection_targets()` 가 `macro_collector` 의
   수집 목록(`FRED_INDICATORS`)이라 5종을 넣으면 `collect_all()` 이 61→66계열이
   되고, `capability.py:132` 의 `total = len(series)` 가 바뀌며, 그 값이 골든
   스냅샷 `frontier_sample.total_series` 에 들어 있다.
2. **소비자가 없다.** 조밀한 커브를 요구하는 곳을 찾지 못했다 — L1 요건
   `term_structure` 는 `scipy.optimize.least_squares` **라이브러리 프로브**이지
   데이터 밀도가 아니다.
3. **빈티지 연구에도 보탬이 안 된다.** `DGS` 는 일별 **시장 관측치**라 GDP·고용
   처럼 개정되지 않는다.

★ECOS 처럼 미지원 선언도 하지 않는다★ — FRED 에는 매핑 결함이 없다. `DGS{n}` 은
자기서술적·자기일관적이고 레지스트리의 `DGS2`·`DGS10`·`DGS30`·`DGS3MO` 와 같은
패턴이다. 같은 처방을 기계적으로 적용하면 **정상 작동하는 계열을 지우게 된다.**


---

## 부록 6. ★#2 정정★ — 배당은 이미 상당히 배선돼 있었다

이 감사는 §C 에서 *"우리 수익률은 총수익률인가? — 아니다"* 라고 적고 #2 를 "DART 배당
영속 + 총수익 계열" 로 올렸다. 착수하며 실측하니 **전제가 상당 부분 틀렸다.**

### 실제 상태

```
alotMatter → {dps, payout_pct, yield_pct}
  dps        → dart_client.py:470  fs.dps 주입            ✔ 배선됨
  payout_pct → fundamentals_store._real_dividend          ✔ 배선됨
  yield_pct  → ★아무도 읽지 않았다★                        → 이번에 연결
```

그리고 **총수익 팩터도 이미 있었다** — `extended_factors_store.py:242`
`d["total_return"] = round(r12 + (dy or 0.0), 2)` (주가수익률 + 배당수익률).

★따라서 "총수익 계열이 없다" 는 틀렸다.★ 참인 것은 좁다 — **`daily_prices` 의
일별 수익률 사슬에 배당이 없다**. 그것은 §부록 2(가격 의미 계약)에 이미 정확히
적혀 있었고, §C 가 그것을 과잉 일반화했다.

### 남은 진짜 공백은 **배당기준일** 하나다

일별 총수익 계열에는 배당락일이 필요한데 `alotMatter` 는 **사업연도 집계**
(`bsns_year` + `reprt_code`)라 기준일을 주지 않는다(`_parse_dividend_rows` 실측).
★#4(`mktcap`)와 같은 구조다★ — 원천이 그 필드를 주지 않으므로 정직하게는 만들 수
없고, 지어내면 룩어헤드다. 배당 결정 공시(미구현 엔드포인트)가 있어야 한다.

### 이번에 한 것

`yield_pct`(공시 현금배당수익률, **배당 시점 기준**)를
`FinancialStatement.disclosed_dividend_yield` 로 잇고 토큰 "배당시점배당수익률" 을
열었다. `dividend_yield`(= `dps / 오늘 주가`)를 **덮지 않는다** — 과거 분석에
현재가 기준을 쓰면 오늘 가격이 과거로 샌다.

## 부록 7. 죽은 미지원 사유 17개 — ★해소됨. 둘은 반대 방향의 결함이었다★

**상태: 해소.** `UNSUPPORTED_REASONS` 에 **이미 supported 인 토큰**의 항목이 남아
있었다. 주주환원 11종을 정리한 뒤에도 **17개**가 더 있었고(실측), 상한 테스트로
증가만 막아 뒀다. 그 17개를 실제로 조사해 보니 ★한 종류가 아니었다★.

| 부류 | 수 | 실체 | 처리 |
|---|---|---|---|
| 죽은 사유 | 15 | `_derive` 가 실파생을 붙여 `REAL_CAPABLE_IDS` 에 들어갔는데 사유 항목만 남음 (`POR`·`매출원가율`·`직원급여총액`·`재고자산회전율` …) | 항목 제거 |
| ★능력 선언 과장★ | 2 | `남자직원수`·`여자직원수` — 사유가 낡은 게 아니라 **선언이 틀렸다** | `REAL_CAPABLE_IDS` 에서 강등 |

### 둘째 부류가 왜 더 심각한가

```python
d["female_emp"] = round(emp * fr / 100)          # fr = female_ratio
d["male_emp"]   = round(emp * (1 - fr / 100))
```

`emp`(직원수)는 `_real_business` 가 DART `empSttus` 에서 받는 **실값**이지만
`fr`(성별 비율)은 `MOCK_ONLY` 다 — 같은 응답에서 성별 행을 파싱하지 않는다.
★실값 × 합성비율 = 합성★인데 픽커는 그 둘을 **실데이터 팩터로 제공**했다.
스크리너 조건 `남자직원수 > 1000` 이 날조된 값으로 종목을 걸렀다는 뜻이다.
저장소가 스스로 적어 둔 원칙과 정면으로 어긋난다 — *"합성값 → 실데이터 원칙상
픽커/조건식에서 비활성"*.

강등 결과 실측: 논지 다리 **93 → 91**, 지원 토큰 **316 → 314**, 델타는 정확히
그 둘뿐(재현 확인). 사유는 `REASON_BIZREPORT`("사업보고서 미연동" — 연동돼 있으므로
**거짓**) 에서 `REASON_SYNTHETIC_INPUT` 으로 바꿨다.

`tests/test_real_capability_claims.py`(E1~E11 · 변이 U1~U8) 가 이 상태를 지킨다.
상한 `<= 17` 은 **`== 0`** 으로 강화됐다.

### 함께 드러낸 것 — 설명 없는 가정 상수

`ccc`·`net_fin_asset` 은 `유동부채×0.35`(매입채무 근사)·`총부채×0.5`(금융부채 근사)
라는 가정을 쓰는데 주석도 설명문도 없었다. ★입력이 실 DART 값이라 위 둘과 성격이
다르다★ — 날조가 아니라 **모델링 근사**다. 그래서 강등하지 않고 상수에 이름을 주고
(`DPO_PAYABLES_RATIO`·`FINANCIAL_DEBT_RATIO`) 사용자 설명문에 가정을 적었다.
값은 바뀌지 않았음을 수치로 고정했다(E9).

---

## 부록 8. ★새 감사 항목★ — `empSttus` 가 성별 행을 주는가

부록 7 의 강등은 **성별 비율에 실데이터 경로가 없다**는 사실에 근거한다. 그런데
`_real_business` 가 이미 부르는 `empSttus.json` 의 응답에 성별 구분 행이 있을
**가능성**이 있다 — DART 직원현황은 통상 성별로 행이 나뉜다.

★그러나 필드명을 오프라인에서 확인할 수 없다.★ ECOS 항목코드를 추측으로 적어
넣었다가 회사채를 국고채라고 부른 전례가 있으므로, 같은 이유로 **지어내지 않고
감사 항목으로 남긴다**.

| 항목 | 내용 |
|---|---|
| 필요한 것 | `DART_API_KEY` — `empSttus.json` 실응답 1건 |
| 확인할 것 | 성별 구분 행의 키와 값 형식 (행 분리인지 컬럼인지) |
| 성공 시 | `female_ratio` → 실데이터 경로 확보 → `female_emp`·`male_emp` 재승격 |
| 증거등급 | 현재 **E0**. 실응답을 보면 E2 |
| 하지 말 것 | 필드명 추측. 응답을 보기 전에는 코드를 쓰지 않는다 |

---

## 부록 9. ★새 감사 항목★ — ECOS 분기 TIME 표기

`BokClient.fetch_series` 는 이제 `D`·`M`·`A` 의 기본 조회 범위를 만든다.
**`Q` 는 거절한다** — ECOS 분기 TIME 표기가 `2024Q1` 인지 `20241` 인지
오프라인에서 확인할 수 없다.

★추측한 좌표로 회사채를 국고채라고 불렀던 것(`1fa4fbd`)과 정확히 같은 종류의
오류★ 이므로 포맷을 만드는 대신 빈 결과 + 사유를 돌려준다. `start`/`end` 를
명시로 넘기면 그대로 쓰므로, 표기를 아는 사람은 지금도 쓸 수 있다.

| 항목 | 내용 |
|---|---|
| 필요한 것 | `BOK_API_KEY` — 분기 통계표(예: 200Y002) 실응답 1건 |
| 확인할 것 | 응답 `TIME` 값의 표기 · 요청 start/end 가 받는 표기 |
| 성공 시 | `_FMT` 에 `Q` 를 추가 → 분기 계열의 기본 조회가 열린다 |
| 하지 말 것 | 표기 추측. `test_quarterly_is_refused_rather_than_invented` 가 막는다 |

★후속 (데이터 계약 감사)★ — `scripts/verify_ecos_meta.py` 의 프로브 창
`_PROBE_WINDOWS` 에도 **`Q` 를 넣지 않았다**. 분기 표기가 바로 알아내려는 것이므로
요청에 적으면 순환이 된다. `D`·`M`·`A` 로 걸어 응답 `TIME` 에서 **역으로** 알아낸다.
`test_the_quarterly_request_notation_is_still_not_invented` 가 지킨다.
자세한 것은 [`2026-08-27-ecos-data-contract-audit.md`](2026-08-27-ecos-data-contract-audit.md).

---

## 부록 10. ★#5 정정★ — 메타는 수단이고, 결함은 주기 축의 부재였다

감사 §C·부록 3 은 #5 의 근거를 *"계열의 단위·주기·공표지연이 `timing_factor_meta`
에 **손으로** 적혀 있다"* 고 적었다. ★그 전제는 틀렸다★(실측).

`timing_factor_meta._SOURCE_TIMING` 은 **타이밍 팩터** 5개(`financial_conditions`·
`curve_slope`·`vix_term_structure`·`vix_term_spread`·`indicator`)의 공표지연이고
전부 FRED 계열이다 — ECOS 는 한 줄도 없다. 감사 #2·#4 에 이은 세 번째 정정이다.

### 실제 결함 셋 (실측)

| # | 결함 | 근거 |
|---|---|---|
| 1 | ★주기를 담을 자리가 없다★ | `SourceSpec` 8필드에 `frequency` 부재. `macro_collector.py` 의 `fetch_series(s, i)` 가 `period` 를 안 넘겨 **37계열 전부 월별** |
| 2 | ★네 원인이 한 문자열로 뭉개진다★ | 빈 응답이면 `source="unavailable"` 이 전부. `MacroSeries` 에 `reason` 부재 |
| 3 | 날짜 포맷이 M·A 만 만든다 (★잠재★) | `"%Y%m" if period == "M" else "%Y"` — `D` 로 부르며 start/end 를 생략하면 무효 범위. 유일한 일별 호출자가 명시로 넘겨 살아 있는 버그는 아니었다 |

### 이번에 한 것

- `SourceSpec.frequency` 신설 — ★37계열 전부 `None`(미검증)★. 하나도 채우지 않았다.
- `unavailable_reason_for()` — **키 없음** · **좌표 미검증** · **검증됐는데 빈 응답** ·
  **파생 원계열 부재** 를 가른다. 주기 불일치 의심은 기존 사유를 **덮어쓰지 않고 덧붙는다**.
- `D` 날짜 포맷 · `Q` 거절(부록 9) · `M` 은 ★URL 문자 단위로 동일★.
- `BokClient.fetch_table_list`/`fetch_item_list` + `scripts/verify_ecos_meta.py`.
  ★발견한 주기를 레지스트리에 자동으로 쓰지 않는다★ — `verified_live` 와 같은 규율.

### 하지 않은 것 — ★수집 주기는 그대로다★

주기를 알게 됐다고 수집기가 그것으로 조회하면, 키가 들어오는 순간 사람 확인 없이
`collect_all()` 출력이 달라진다. `frequency` 는 **기록·대조 전용**이고,
`test_the_collector_still_does_not_pass_a_period` 가 트립와이어로 지킨다 —
배선하려면 그 테스트를 의식적으로 고쳐야 한다.

### 부수 발견 — 레지스트리에 읽기 경로가 둘이다

`specs_by_provider()` 는 `_SPECS`(튜플), `get_spec()` 은 `_BY_KEY`(딕트)를 읽는다.
첫 판의 C17 이 `_SPECS` 만 검사해서 `_BY_KEY` 에 쓰는 변이(V10)가 **살아남았다**.
`test_the_two_registry_read_paths_agree` 가 두 경로의 일치를 못 박는다.
