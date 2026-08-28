# 피처 계층 mock 게이트 감사 — ★네 모듈이 불변식 밖에 있다★

> 감사 §B3(*"피처 계층이 mock 기본값이다"*)를 실측한 결과. 선행 `4d38f89`.
>
> **CLAUDE.md 하드 불변식**
> > `mock_allowed()` 가 유일한 판정 기준이며 `KIS_USE_MOCK` 이 정확히 `"1"` 일 때만
> > mock. 운영에서 조회가 실패하면 합성값으로 가리지 말고 정직하게 `None`/빈값을
> > 반환할 것.

## 1. 실측 — 누가 게이트를 지나는가

| 모듈 | `mock_allowed()` | 판정 |
|---|---|---|
| `price_factors_store` | 4회 | ✔ |
| `fundamentals_store` · `consensus_store` · `extended_factors_store` | 2회 | ✔ |
| ★`liquidity_gate`★ | **0회** | ✗ ← 이번에 고침 |
| `graph_store` | **0회** | ✗ |
| `vector_store` | **0회** | ✗ |
| `sentiment_worker` | **0회** | ✗ |

## 2. `liquidity_gate` 가 가장 위험했던 이유

나머지 셋은 **옵트인 필터 kind** 다 — 사용자가 그 필터를 써야 돈다.
유동성 게이트는 다르다:

```python
# screener.py:539 — 모든 필터보다 먼저, 기본으로 켜진 채
floor = resolve_floor(liquidity_floor if liquidity_floor is not None else "standard")
items, self._liquidity_stats = apply_liquidity_gate(items, floor)
```

`standard` = ADV≥10억 · 시총≥1000억 · 스프레드≤0.5%. 즉 **날조된 ADV·스프레드가
그 뒤 모든 분석의 모집단을 정했다.**

```python
tradable = self._uniform(stock_code, "halt") > 0.1   # 소형주 10% 무작위 비거래
```

★실측★ — 시총 300억 종목 200개 중 **13개**가 종목코드 MD5 해시로 "거래정지"
판정을 받아 운영 유니버스에서 조용히 사라졌다. 수정 후 **0개**.

## 3. 고칠 재료가 이미 있었다 (고아 능력)

| 필드 | 실데이터 원천 | 처리 |
|---|---|---|
| `market_cap_억` | 호출부가 `item.market_cap_억` 로 이미 넘긴다 | 사용 · 없으면 `None`(합성 폴백 제거) |
| `adv_value_억` | `price_factors_store.amount_20d_avg` — ★이미 게이트를 지킨다★ | 재사용 |
| `is_tradable` | `stock_master.load_master_flags()`·`MANAGED_CODES` | 재사용 · 없으면 `None` |
| `spread_pct` | ★없다★ — 저장소의 모든 `spread` 가 `rng.uniform` | **항상 `None`** + 사유 |

`amount_20d_avg` 는 이미 올바르게 동작했다(`KIS_USE_MOCK=1` → 908.9, `=0` → `None`).
게이트는 한 모듈 옆에서 정직하게 유도되는 숫자를 무시하고 스스로 날조했다.

## 4. ★잠복 결함 — 이 변경이 드러냈다★

```python
if floor.require_tradable and not liq_data.get("is_tradable", True):   # 예전
```

`.get(key, default)` 는 키가 **없을 때만** 기본값을 쓴다. 키가 있고 값이 `None`
이면 `None` 을 돌려주고 `not None` 은 `True` 라 **전량 배제**된다. 나머지 세 조건은
전부 `is not None` 으로 미상을 건너뛰는데 여기만 달랐고, 합성 경로에서는 항상
bool 이라 **드러날 수 없었다**. 운영 경로가 정직하게 `None` 을 내자마자 터졌다.

`tradable is False` 로 고쳤다 — `False`(거래정지 확인)와 `None`(모름)은 다른 사실이다.

## 5. 남은 셋 — ★새 감사 항목★

| 모듈 | 도달 경로 | 실데이터 원천 | 판단 |
|---|---|---|---|
| `graph_store` | `filter_ast.py:819` (`eval_graph`) | ★없음★ — 밸류체인 원천 미보유 | 운영에서 항상 unavailable 이 될 것 |
| `vector_store` | `filter_ast.py:833` (`eval_vector_sim`) | ★없음★ — 임베딩 원천 미보유 | 동일 |
| `sentiment_worker` | `filter_ast.py:826` (`eval_sentiment`) | ★없음★ — `_source: sentiment_precomputed_mock` | 동일 |

★유동성 게이트와 성격이 다르다★ — 셋 다 옵트인이고, 원천이 아예 없어 게이트를
붙이면 "운영에서 그 필터는 항상 평가 불가" 가 된다. 그것이 **정직한 상태**지만
기능이 사라지는 것과 같으므로 **별도 결정**이 필요하다. 여기 기록만 한다.

## 7. 캐시 키가 mock 모드를 기록하지 않는다 — ★해소됨★

**상태: 해소.** `mock_base.cached()` 의 키에 mock 여부가 없어
`KIS_USE_MOCK=1` 에서 만들어진 값이 `=0` 으로 바뀐 뒤에도 그대로 서빙됐다.

```
mock 모드에서 데움:  PriceFactorsStore.get_factors("005930")["amount_20d_avg"] = 908.9
그 뒤 운영 모드 게이트: adv_value_억 = 908.9      ★None 이어야 한다★
```

### ★이 항목의 위험 평가가 틀렸었다★

당시 이렇게 적었다 — *"운영 위험은 낮다. 프로세스는 한 모드로 시작해 끝난다."*
그리고 *"파급이 커 별도 승인 사항"* 이라고 미뤘다. **둘 다 재실측에서 뒤집혔다.**

**① 누수는 프로세스 수명을 넘었다.** `snapshot_db.enabled()` 를 보면:

```python
return bool(os.getenv("DART_API_KEY")) or not mock_allowed()
```

`KIS_USE_MOCK=1` + `DART_API_KEY` 설정은 **정당한 부분 연동 개발 조합**인데, 이때
`mock_allowed()=True` 이면서 `_persist_on()=True` 다(실측). 즉 합성값이
`factor_snapshot` 에 **기록되고 재시작을 넘어** 운영에서 실값처럼 읽힌다.

**② 파급 우려는 비어 있었다.** *"여러 스토어의 캐시가 한 번에 무효화된다"* 고
걱정했으나 `factor_snapshot` 은 **0행**이었다(실측). 무효화할 것이 없었다.
대상은 `PERSIST=True` 스토어 3개 · `cached()` 호출 4곳뿐이다.

★교훈 — 미룬 항목의 위험 평가는 미룰 때가 아니라 **다시 잴 때** 정해진다.★

### 조치 — 누수가 둘이라 둘 다 고쳤다

| 누수 | 처방 |
|---|---|
| 메모리 | `cached()`·`prime()` 키에 모드를 붙인다(`_scoped()` 가 단일 출처) |
| ★영속★ | `_persist_on()` 이 `mock_allowed()` 이면 **False** — 합성값은 DB 에 안 들어간다 |

★하나만 고치면 다른 쪽이 남는다★ — 서로 다른 누수다.

`tests/test_cache_mode_isolation.py`(11개) 가 이 상태를 지키고, 변이 X1~X8 이 전부
죽는다. `liquidity_gate` 는 `store._scoped(...)` 를 거쳐 읽어 **규칙을 복제하지
않는다** — 그 하드코딩 변이(X8)는 오늘은 의미상 동등하지만(그 함수는 운영에서만
도달한다) 미래 드리프트를 막기 위해
`test_real_adv_reads_the_current_mode_not_a_hardcoded_one` 이 속성을 못 박는다.
