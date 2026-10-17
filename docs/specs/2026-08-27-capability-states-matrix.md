# 능력 6상태 행렬 — `implemented → ingested → persisted → consumed → PIT → provenance`

> 선행: [`데이터 추출 감사`](2026-08-26-data-extraction-audit.md) ·
> [`능력 활용 행렬`](2026-08-26-capability-utilization-matrix.md) · 기준 커밋 `1e3226a`
> ★읽기 전용 감사다 — 이 문서를 쓰면서 코드를 고치지 않았다.★

---

## 0. 이 감사가 **직전 두 문서를 정정한다**

### ★정정 ① FRED 빈티지는 "수집되나 미영속" 이 아니다 — **영속된다**★

계획 단계에서 ALFRED 빈티지를 *"조회 시점에만 존재한다"* 고 적었다. **틀렸다.**

`src/data/regime_snapshots.py` 에 `regime_snapshots` 테이블이 있고 컬럼에
**`observations TEXT`** 와 `research_usage` 가 있다. `MacroObservation` 은
`vintage_id`·`release_timestamp` 를 들고 있으므로 **빈티지가 그대로 저장된다.**

게다가 그 경로에는 **저장 전 룩어헤드 가드**가 있다:

```python
late = [o for o in observations if o.release_timestamp and o.release_timestamp > as_of]
if late:
    raise LookAheadError(f"as_of={as_of} 이후에 공표된 관측치가 …")
```

그리고 `_derive_usage` 가 *"가장 약한 고리를 따른다 — 빈티지 없는 시리즈가 하나라도
있으면 forward_only"* 로 등급을 매긴다.

★즉 이 저장소에는 **완전한 PIT 파이프라인이 이미 하나 있다**★ —
ALFRED 조회 → 룩어헤드 거부 → 빈티지 포함 영속 → 등급 파생.
문제는 그것이 **없다는 것이 아니라, 국면 축이 그 경로를 타지 않는다**는 것이다.

### 정정 ② "수집되나 미영속" 의 실제 사례는 다른 것이다

| 후보 | 판정 |
|---|---|
| FRED ALFRED 빈티지 | ✗ 정정 — **영속됨**(`regime_snapshots.observations`) |
| ★DART `elestock`(임원·주요주주)★ | ✔ **온디맨드 집계** — `insider_flows.py` 에 `CREATE TABLE`·`INSERT` **0건** |
| DART `alotMatter`(배당) | ✔ `fundamentals_store` 도 영속 0건 — 호출 시점 계산 |

---

## 1. 6상태 행렬

`impl` 구현 · `ingest` 수집 파이프라인 · `persist` 영속 · `consume` 소비자 ·
`PIT` 시점 적격 · `prov` 출처 기록 · `성격` research / production

### KRX

| 능력 | impl | ingest | persist | consume | PIT | prov | 성격 |
|---|---|---|---|---|---|---|---|
| 전종목 일별 (`stk`·`ksq`) | ✔ | ✔ | ✔ `daily_prices` | ✔ 26개 파일 | ✗ 빈티지 없음 | ★✔ `source`★ | production |
| 지수 일별 | ✔ | ✔ | ✔ | ✔ | ✗ | ✔ | production |
| VKOSPI·신용잔고·공매도·대차 | ✔ | ★✗★ | ✗ | ✗ | ✗ 영구 | — | — |
| 투자자별 상세 (MDC) | ✔ | ◐ ISIN 필요 | ✔ `investor_flows` | ✔ | ✗ | ✔ | production |

### KIS

| 능력 | impl | ingest | persist | consume | PIT | prov | 성격 |
|---|---|---|---|---|---|---|---|
| 시세 6종 | ✔ | ✔ | ◐ 일봉만 | ✔ | ✗ | ★✔ `source='kis'`★ | production |
| 주문 4종 | ✔ | ✔ | ✔ | ✔ | — | ✔ | production |
| 마스터 (ISIN·지수편입·업종·상태) | ✔ | ✔ | ★✔ `instrument_master`★ | ✔ | ✗ `as_of` 만 | ✔ | production |

### FRED — ★경로가 둘★

| 능력 | impl | ingest | persist | consume | PIT | prov | 성격 |
|---|---|---|---|---|---|---|---|
| `series/observations` (`frequency=m`) | ✔ | ✔ | ✔ | ✔ 대시보드 · **국면 축(→배분)** | ★✗★ | ◐ | production |
| ALFRED 빈티지 (`realtime_*`) | ✔ | ✔ | ★✔ `regime_snapshots.observations`★ | ◐ `timing_rules_v2` · 국면 스냅샷 | ★✔ + `LookAheadError`★ | ✔ | research |

### ECOS

| 능력 | impl | ingest | persist | consume | PIT | prov | 성격 |
|---|---|---|---|---|---|---|---|
| `StatisticSearch` (40계열) | ✔ | ✔ | ✔ | ✔ | ✗ **영구**(빈티지 엔드포인트 없음) | ✔ | production |
| `StatisticTableList`·`ItemList`·`KeyStatisticList` | ★✗★ | ✗ | ✗ | ✗ | — | — | — |

### DART

| 능력 | impl | ingest | persist | consume | PIT | prov | 성격 |
|---|---|---|---|---|---|---|---|
| `company`·`fnlttSinglAcnt(All)` | ✔ | ✔ | ✔ `company_snapshots` | ✔ | ★✗ `has_vintage=False` 명시★ | ✔ | production |
| `alotMatter` (배당) | ✔ | ✔ | ★✗ 온디맨드★ | ✔ | ✗ | ◐ | production |
| `elestock` (임원·주요주주) | ✔ | ✔ | ★✗ 온디맨드★ | ✔ | ✗ | ◐ | production |
| 공시검색·원문·지분·분할 | ★✗★ | ✗ | ✗ | ✗ | — | — | — |

### 파생 — 가격 품질

| 능력 | impl | ingest | persist | consume | PIT | prov | 성격 |
|---|---|---|---|---|---|---|---|
| `daily_prices.source` | ✔ | ✔ | ✔ | ★✗★ | — | ✔ | — |
| ★`adj_close`★ | ✔ | ✔ | ✔ | ★**✗ 소비자 0**★ | ✗ | ✔ | — |
| `adj_close_coverage()` | ✔ | — | — | ★**✗ 소비자 0**★ | — | — | — |

---

## 2. 다섯 구분 — 실례

| 구분 | 실례 | 왜 그 칸인가 |
|---|---|---|
| 능력 있으나 **미구현** | ECOS 메타 3종 · DART 공시/원문/지분/분할 | 클라이언트 함수가 아예 없다 |
| 구현됐으나 **미수집** | KRX `get_extra` 4종 | `get_extra()` 호출부 **0** (`not_ingested` 로 선언됨) |
| 수집되나 **미영속** | DART `elestock` · `alotMatter` | `insider_flows`·`fundamentals_store` 에 `CREATE TABLE`/`INSERT` **0건** |
| 영속되나 **미사용** | ★`adj_close`★ · `daily_prices.source` | 정본 로더가 `close` 만 SELECT 한다 |
| 소비되나 **PIT 부적격** | ★국면 축의 FRED 계열★ · DART 재무 | 값이 계산에 들어가지만 과거 시뮬레이션 불가 |

### ★"소비되나 PIT 부적격" 이 가장 위험하다★

나머지 넷은 **없는 것**이고 이것은 **틀린 것**이다. 값이 화면에 나오고 배분 계산에
들어가는데 그 값으로 과거를 채점할 수 없다.

그리고 FRED 는 **같은 제공자 안에서 두 경로가 갈려** 있어 특히 나쁘다 —
빈티지 파이프라인이 **이미 완성돼 있는데**(룩어헤드 가드 포함) 배분에 쓰이는
국면 축만 그것을 타지 않는다. 능력이 없어서가 아니라 **배선이 안 돼서**다.

---

## 3. 우선순위

| 후보 | 정확성 | 재사용 | PIT 안전 | 비용 | 정책 독립 |
|---|---|---|---|---|---|
| ★가격 품질 강제 (Phase 1)★ | **높음** | 높음 | 중 | **작음** | ✔ |
| FRED 빈티지 → 국면 축 | **높음** | 높음 | **높음** | ★중→작음★ | ✗ 배분 경로 |
| DART 공시 CA | 중 | 중 | 중 | 큼 | ✔ |
| DART 배당·임원 영속화 | 낮음 | 중 | 낮음 | 작음 | ✔ |
| KRX `get_extra` | 낮음 | 중 | ✗ 영구 forward-only | 작음 | ✔ |
| ECOS 메타 | 낮음 | 낮음 | — | 중 | ✔ |
| ETF 메타데이터 | 낮음 | 낮음 | — | 큼 | ✔ |

★FRED 빈티지의 비용 평가를 **내렸다**★ 정정 ① 때문이다 — 파이프라인을 새로
만드는 것이 아니라 **국면 축을 기존 경로로 옮기는 배선**이다. 그러나 그것이 곧
배분 결정 경로이므로 **여전히 별도 승인 사항**이다.

★`get_extra` 를 1순위로 두지 않는 이유★ 싸고 독립적이지만 **정확성을 고치지
않는다**. KRX 는 빈티지가 없어 그 4계열은 영원히 forward-only 이고, 미사용이
이미 `not_ingested` 로 **선언돼** 있어 조용한 결함도 아니다.

---

## 4. 권고 — ★가격 품질 강제 (Phase 1)★

**근거**

1. 저장소의 **모든 수익률이 미조정 가격 위에서** 돈다 — `kis_backtest_engine.load_ohlcv`
   가 `SELECT … close …` 이고 `adj_close` 를 읽는 코드가 **하나도 없다**.
2. `close → adj_close` 전환은 배분 경로를 건드리므로 **지금 할 수 없다.**
   Phase 1 은 그 전환의 **선행 조건**을 정책 밖에서 만든다.
3. 임계값을 지어내지 않는다 — 기존 계약(`derive_usage`·`all(vintage_id)`)이
   **전부-아니면-전무**이므로 그대로 확장한다.

### 계약

| 상태 | 판정 | 고치는 방법 |
|---|---|---|
| `adjusted` | `adj_close` 값 있음 | — |
| `chain_broken` | NULL **이고** 그 티커에 조정된 행이 있음 | 해당 구간 KRX 재적재 |
| `raw` | 그 티커가 **전부** NULL (하위: `not_rebuilt` / `no_return_data`) | 재구성 실행 / KRX 적재 |
| `missing` | 요청 티커에 **행이 없음** | 적재 |

```python
def price_usage(tickers, start=None, end=None, engine=None) -> dict:
    """★`pit_macro.derive_usage` 를 **호출**한다★ 등급 규칙을 복제하지 않는다.
    has_vintage ↔ 모든 행이 adjusted · depth_ok ↔ 구간을 덮는다 · lag_known ↔ True
    """
```
`assert_prices_backtest_eligible(...)` → 기존 `ForwardOnlyError`.

### 파일

| 파일 | 변경 |
|---|---|
| `src/data/price_quality.py` | 4상태 · `missing` · `price_usage` · `assert_prices_backtest_eligible` |
| `src/data/ohlcv_loader.py` | `df.attrs["adj_status"]` (기존 `attrs["source"]` 관례) |
| `src/api/data_routes.py` | `GET /api/v1/data/price-quality` (`ingest-doctor`·`source-honesty` 계열) |

★`src/engine/` · `allocation_routes.py` 무변경★ · 백테스트 엔진에 게이트 **미배선**.

### 테스트 12 + 변이 6

4상태 배타성 · `missing` 이 100% 로 안 보이기 · `raw` 하위 사유 분리 ·
`NULL` 출처를 `unknown` 유지 · **한 행만 깨져도 `FORWARD_ONLY`**(짝: 전부면
`BACKTEST_ELIGIBLE`) · 행 없으면 `UNAVAILABLE` · `ForwardOnlyError` ·
★`derive_usage` 를 실제로 통과★(몽키패치) · 라우트 200/`available:false` ·
`attrs` 비보장 명시 · ★백분율 상수 없음★.

**변이**: `missing` 미집계 · 한 행 깨져도 적격 · `raw` 하위 사유 병합 ·
`NULL` → `krx` 추정 · `derive_usage` 우회 · 백분율 임계값 도입.

### 불변 증명 (3중)

1. `git diff -- src/engine/ src/api/allocation_routes.py` 비어 있음
2. ★골든 스냅샷 3종(`t3_bl_ep`·`t3_d`·`geom`) 바이트 동일★ — 구현 **전에** 재취득
3. 전체 스위트 3,014 + 신규

---

## 5. 하지 않는 것

`close → adj_close` 소비자 전환(배분 경로) · `constrained_solve` · 배분 결정 경로 ·
Macro→Allocation 배선 · 최적화기 의미 · 국면→배분 정책 · 분류→배분 매핑 ·
Phase 2/3 후보 구현 · 백분율 임계값.

## 재현

```bash
cd /home/user/Project-Alpha
grep -rn "adj_close" src/ --include=*.py | grep -viE "krx_ingest|kis_models|price_quality"
grep -n "def load_ohlcv" -A18 src/kis_backtest_engine.py | grep SELECT
grep -n "observations TEXT" src/data/regime_snapshots.py
grep -cE "CREATE TABLE|INSERT INTO" src/data/insider_flows.py src/data/fundamentals_store.py
grep -rn "\.get_extra(" src/ scripts/ --include=*.py | grep -v krx_client.py | wc -l
```
