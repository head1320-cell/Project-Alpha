# 데이터 플랫폼 스펙 — 저장 계층 전체 지도

> 실측 2026-09-06. ★개수를 적지 않는다★ — `CLAUDE.md` 규율대로 세지 말고
> 소유 모듈을 읽으세요. 테이블 목록은 `grep -rn "CREATE TABLE" src/ scripts/` 가
> 언제나 진실입니다.
>
> 재무 축의 이중 시간은 이 문서의 주제가 아닙니다 —
> [`INGESTION_ARCHITECTURE_V2.md`](INGESTION_ARCHITECTURE_V2.md) 를 보세요.
> 계층 구조·스택은 [`architecture.md`](architecture.md).

## 0. 이 문서가 답하는 질문

*"우리 DB 에 무엇이 있고, 무엇이 없고, 없는 것은 왜 없는가."*

이 질문이 문서 없이 코드에 흩어져 있었다. 그래서 외부에서 *"TSDB 로 바꾸자"* ·
*"틱 데이터를 넣자"* 같은 제안이 올 때 **측정된 근거로 답할 자리가 없었다.**

---

## 1. ★저장 계층은 하나가 아니라 셋이다★

이것이 이 시스템 스펙에서 가장 자주 오해되는 지점이다. "DB" 라고 하면 RDB 만
떠올리지만 실제로는 셋이고, **셋으로 나뉜 것은 결정이지 누락이 아니다.**

| 계층 | 무엇을 담나 | 어디 |
|---|---|---|
| **RDB** (PostgreSQL → SQLite 폴백) | 일봉·재무·수급·매크로·리서치·실거래 | `src/database.py` |
| **날짜별 Parquet** | 분봉 (`data/minute_bars/{YYYY-MM-DD}.parquet`, zstd) | `src/data/minute_bars.py` |
| **디스크 JSON 캐시** | DART 원본 응답 (TTL, 재시작에도 유지) | `dart_client._DART_CACHE_DIR` |

**분봉을 RDB 에 넣지 않은 이유** — `minute_bars.py` 헤더가 적어 뒀다: 일자당 1파일로
**종목×일자 파일 폭발을 막고**, 엔진이 날짜 순서로 도는 접근 패턴에 LRU 캐시가
맞는다. 그리고 신호는 일봉, **체결만 분봉**이라는 결정이 이미 있어 분봉은 조회
패턴이 좁다. ⇒ 사실상 **날짜 파티션 + 컬럼 저장**이고, 흔히 "파티셔닝을 도입하자"
고 말하는 그것이 이 축에는 이미 있다.

**DART 캐시** — 파싱 결과가 아니라 **응답 원본**을 남기므로 데이터 레이크에
가까운 성격이다. 다만 **DART 만** 그렇다(KRX·KIS·ECOS·FRED 응답은 파싱 후 버린다).

**엔진 설정** — `postgresql+psycopg2`, `pool_pre_ping` · `pool_size=5` ·
`max_overflow=10` · `pool_recycle=3600`. 접속 실패 시 **SQLite 자동 폴백**
(`src/database.py`). ★CI 백엔드 잡은 SQLite 로만 돈다★ — Postgres 전용 DDL 은
테스트에서 한 번도 안 돌고 프로덕션에서 처음 실행된다는 뜻이다.

---

## 2. 테이블 지도 — 도메인과 DDL 소유 모듈

| 도메인 | 테이블 | DDL 소유 |
|---|---|---|
| 시세 | `daily_prices` | `data/krx_ingest.py` (+ `kis_models.py` — §7-4) |
| | `instrument_master` | `data/instrument_master_store.py` |
| | `stocks` | `kis_models.py` (마스터 메타) |
| 재무 | `financials_history` · `financials_vintages` | `data/dart_history.py` |
| | `factor_snapshot` | `data/snapshot_db.py` |
| 수급 | `investor_flows` | `data/kis_flows.py` |
| 매크로 | `macro_observations` | `data/macro_observation_store.py` |
| 리서치·의사결정 | `company_snapshots` · `regime_snapshots` · `research_runs` · `research_cases` · `journal_entries` · `investment_decisions`(+`_legs`) · `alpha_registry` · `backtest_runs` · `target_portfolio_versions` · `execution_plans` · `timing_rule_sets`(+`_versions`) · `scenario_packs`(+`_versions`) | `data/` 동명 모듈 |
| 멀티백테스트 | `multibacktest_runs` · `_daily` · `_strategy_daily` | `engine/multibacktest_schema.py` |
| 실거래 | `live_orders` · `live_fills` · `live_audit_trail` · `live_daily_pnl` · `live_kill_events` | `execution/live_schemas.py` |
| | `reconciliation_history` · `local_portfolio_state` · `local_account_state` | `engine/reconciler.py` |

**스키마 관리 방식** — 마이그레이션 프레임워크(alembic 등)가 **없다.**
`CREATE TABLE IF NOT EXISTS` 를 런타임에 부르고, 컬럼 추가는 `ALTER` 헬퍼가
맡는다. `data/schema_add_columns.py` 가 그 규율을 적어 뒀다 — ★한 번만 시도하고
검증하지 않으면 못 붙은 컬럼을 붙었다고 믿는다★.

**인덱스 — ★이 문서가 한 번 틀리게 적었던 자리다★**

처음엔 "핵심 데이터 테이블 전부에 PK 외 인덱스가 없다" 라고 단정했다. **거짓이었다.**
`grep "CREATE INDEX"` 가 **raw SQL 만** 보고 **SQLAlchemy `Index()` 선언을 통째로
놓쳤다.** 표기가 둘인데 한쪽만 센 것이다 — 인벤토리를 만들 때 되풀이하기 쉬운
실수라 지우지 않고 남긴다.

실제로는:

| 표기 | 어디 |
|---|---|
| raw SQL `CREATE INDEX` | 리서치·의사결정·실거래·멀티백테스트 모듈 |
| ORM `Index()` | `kis_models.py`(`stocks` · `daily_prices`) · `screener_models.py` |

그리고 ORM 선언은 **`create_all` 이 그 테이블을 실제로 만들 때만** 반영된다 —
`checkfirst=True` 가 이미 있는 테이블을 통째로 건너뛰므로, **DB 의 생성 이력에
따라 같은 제품의 인덱스가 달랐다**(§7-4). `52c3415` 가 `daily_prices` 를 순서와
무관하게 일치시켰다. 나머지 데이터 테이블(`financials_*` · `investor_flows` ·
`macro_observations` · `factor_snapshot` · `instrument_master`)은 **어느 표기로도
보조 인덱스가 없다** — 그건 다시 확인했다.

★자기 DB 가 어느 쪽인지는 물어봐야 안다★ — `python -m scripts.explain_hot_queries`
가 실제 인덱스를 조회해 찍는다.

---

## 3. 시간축 — ★이중 시간인 곳과 아닌 곳★

대부분의 테이블은 **단일 시간**이다(그 행이 언제의 사실인지만 안다). 두 곳만
이중 시간이다:

| 테이블 | valid time | transaction time |
|---|---|---|
| `macro_observations` | `observation_period` | `release_timestamp` + `vintage_id` |
| `financials_vintages` | `(bsns_year, reprt_code)` | `rcept_dt` + `rcept_no` |

★transaction time 이 없는 행은 as-of 질문에 답할 수 없다★ — 그래서 `pit_macro` 는
`vintage_id` 가 빈 행을, `dart_history.load_vintages` 는 `rcept_dt` 불량 행을
버린다. 같은 규칙이다.

**가격 축에는 이중 시간이 없다.** `daily_prices` 는 "지금 아는 그날의 값" 이고,
수정주가가 나중에 바뀌면 과거 행이 덮인다. 이것이 남은 가장 큰 PIT 공백이다.

**나머지 단일 시간 테이블은 그래도 된다** — 리서치 산출물(`backtest_runs` 등)은
실행 시점이 곧 사실이고 개정되지 않는다.

---

## 4. 행 단위 출처(provenance) — ★정규화와 다르다★

정규화는 포맷을 **통일**한다. provenance 는 정의가 다르다는 **사실을 보존**한다.
통일해 버리면 그 사실이 사라진다.

| 컬럼 | 무엇을 보존하나 |
|---|---|
| `daily_prices.source` | `krx`(전종목 백필) / `kis`(온디맨드) — writer 가 둘이다 |
| `daily_prices.price_basis` | `raw`(KRX 원주가) / `adjusted`(KIS 수정주가) — ★`close` 에 두 정의가 섞인다★ |
| `financials_vintages.rcept_no` | 어느 공시본의 값인가 |
| `macro_observations.vintage_id` | 어느 개정본인가 |

★기존 행은 `NULL` 로 남긴다 — 소급 추정하지 않는다★ (`krx_ingest` 가 적어 둔 규칙).
`NULL` = "모른다" 는 **사실**이고, 그럴듯한 값으로 채우면 그 사실이 사라진다.

`price_quality` 가 이 컬럼들을 읽어 티커별 상태를 4-상태로 보고한다 —
`uniform_raw` / `uniform_adjusted` / **`mixed`** / `unknown`.

**종목 식별**은 `data/stock_master.py` 가 단일 진실 공급원이다
(`get_stock_name()` / `resolve_name()`). ★`"Unknown Corp"`·가짜 종목코드 재도입
금지★ 는 `CLAUDE.md` 불변식이다.

---

## 5. 적재 — 언제, 어떻게

- **기동 시 백그라운드 데몬** — `startup/lifecycle.py` 가 KRX 백필 · 매크로 빈티지
  백필 · OHLCV/ETF 예열 · DART 재무 백필 · 수급 동기화를 각각 데몬 스레드로
  띄운다. **재개 가능**하고 비차단이다.
- **일 1회 스케줄러** — `data_sync.daily_sync_scheduler` 가 02:00 KST 에 KIS
  메타데이터를 동기화한다(인프로세스 asyncio 루프).
- **수동 CLI** — `python -m src.data.dart_history …` · `python -m src.data.minute_bars …`
- **재적재 안전성** — CDC 는 없다. 대신 **upsert(`ON CONFLICT DO UPDATE`) + resume
  키**다. 예: `dart_history.existing_keys` 가 적재된 `(종목, 연도, 보고서)` 를
  돌려주고 백필이 그것을 건너뛴다.

**보존/삭제 정책이 없다.** 데이터 테이블에 `DELETE`·`TRUNCATE`·retention 이 없다.
지금 규모에서는 문제가 아니지만 **그것이 결정된 적은 없다** — 기본값일 뿐이다.

---

## 6. ★없는 것★ — 그리고 그 판단

| 없는 것 | 판단 |
|---|---|
| **틱 데이터** | 소비자가 없다. *신호는 일봉, 체결만 분봉* 이라는 결정이 이미 있다. 넣으면 적재·쿼터·스키마·테스트가 늘고 답하는 질문은 없다. |
| **호가창(Market Depth)** | 주문/체결 경로가 호가 필드를 **참조**하지만 저장 테이블은 없다. 위와 같은 이유. |
| **기업행위 이벤트 테이블** | ★있어야 한다★ — §7-3. 지금은 `adj_close` 를 등락률 체인으로 **역산**하므로 체인이 끊긴 구간은 복원 불가다. |
| **실데이터 대안데이터** | 없다. 감성·관계망은 운영에서 **차단**된다(합성값 금지) — §7-2. |
| **RDB 파티셔닝** | 분봉은 이미 날짜 파티션이다. 일봉은 종목×영업일 규모라 근거가 없다 — §8. |
| **마이그레이션 프레임워크** | `CREATE IF NOT EXISTS` + `ALTER` 헬퍼로 돈다. 도입은 전 테이블을 건드리는 별도 승인 사항. |
| **DW 분리 · CDC** | 분석과 적재가 같은 DB 다. 분리를 요구한 워크로드가 관측된 적 없다. |
| **보존 정책** | 결정된 적 없다(§5). |

---

## 7. ★문서화되지 않았던 사실 넷★

조사하다 나온 것들이다. **여기 적는 것이 이 문서의 존재 이유다.**

| | 상태 |
|---|---|
| 7-1 인덱스 | ★내가 **틀리게 적었다**★ — 있었고, DB 이력에 달려 있었다. **고쳤다** (`52c3415`) |
| 7-2 합성값 누수 | ★불변식 위반이었고 **고쳤다**★ (`c93f33c`) |
| 7-3 기업행위 이벤트 없음 | 기록만. 수집 설계가 필요 — **로드맵 2단계** |
| 7-4 `daily_prices` 두 선언 | 컬럼·인덱스·`updated_at` 셋 다 갈렸다. **고쳤다** (`52c3415`) |

### 7-1. `daily_prices` 인덱스가 ★DB 생성 이력에 달려 있었다★ — 고쳤다 (`52c3415`)

처음 이 절은 "인덱스가 없다 → 만들 근거가 약하다" 로 끝났다. **둘 다 손봐야 했다.**
"없다" 는 위 §2 의 이유로 거짓이었고, 그래서 결론도 다시 써야 했다.

★쿼리 형태 분류는 그대로 유효하다★ — 그건 재서 얻은 사실이고 인덱스 유무와
무관하다. 바뀐 것은 **그 위에 내린 판단**이다.

### 쿼리 형태 — 재서 얻은 것 (변함없음)

`daily_prices` 를 읽는 SQL 을 **전수 분류**했다(`grep -rn "FROM daily_prices"`).

| 경로 | 형태 | PK 가 덮나 | 빈도 |
|---|---|---|---|
| 종목 시계열 (`ohlcv_loader`) | `WHERE ticker=… AND trade_date BETWEEN …` | ✅ prefix seek | 종목당 |
| `universe_select.mktcap_asof` | `WHERE ticker=… AND trade_date <= …` | ✅ prefix seek | 종목당 |
| `universe_select.tickers_asof` ①② | `WHERE trade_date <= …` / `= …` | ❌ **ticker 술어 없음** | **요청당 1회** |
| `universe_select.top_mktcap_asof` ①② | 위 + `mktcap IS NOT NULL ORDER BY mktcap` | ❌ | **요청당 1회** |

★핵심은 빈도다★ — ticker 술어가 없는 넷은 **봉당도 종목당도 아니고 요청당 1회**다.
종목마다 불리는 `mktcap_asof` 는 PK 로 덮인다.

### 그런데 그 넷을 덮는 인덱스가 ★있기도 하고 없기도 했다★

`kis_models.DailyPrice` 가 `Index("ix_daily_date", "trade_date")` 를 선언한다 —
정확히 그 축이다. 하지만 `create_all(checkfirst=True)` 는 이미 있는 테이블을
건너뛰므로, `ensure_table`(raw DDL)이 먼저 돌았던 DB 에는 **그 인덱스가 없다.**
메모리 SQLite 로 두 순서를 재서 확인했다(§7-4의 표).

`52c3415` 가 `ensure_table` 도 `ix_daily_date` 를 멱등 생성하게 해 **순서와
무관하게** 일치시켰다. 하네스가 그 효과를 실행계획으로 보여 준다 — 넷 전부
`SCAN`(풀스캔) → `SEARCH … USING INDEX ix_daily_date`(탐색)로 바뀐다.

★그래도 실 DB 의 행 수와 지연은 못 쟀다★(개발 컨테이너에 DB 없음). 그리고
**기존 DB 는 여전히 어느 쪽인지 모른다** — `ensure_table` 이 한 번 돌면 생긴다.
확인은 한 명령이다:

```bash
python -m scripts.explain_hot_queries      # 실제 인덱스 + 실행계획 + 1회 실측
```

### 7-2. 합성값이 운영 경로로 새고 있었다 — ★고쳤다★ (`c93f33c`)

처음엔 "감성이 mock 이다" 로만 적었는데, 재보니 **훨씬 넓었다.**

`mock_base` 는 **캐시·영속만** 게이트한다(모드별 네임스페이스 · 합성값 미영속).
**빌더는 각 스토어의 몫**인데 `DeterministicMockStore` 서브클래스 여덟 중
다섯만 하고 있었다. 셋(`SentimentWorker` · `GraphStore` · `VectorStore`)이
`KIS_USE_MOCK=0` 에서도 합성값을 만들었고, 그 값이 스크리너 필터에 노출됐다.
`CLAUDE.md` 절대 불변식 위반이다.

★셋의 성격이 달라 처방이 달랐다★

- `GraphStore` — `_KNOWN_STOCKS` 를 셔플해 **공급망 관계를 지어낸다** → 차단.
  빌더가 아니라 **읽기 경로**에 걸었다(빌더는 싱글톤 생성 시 1회만 돌아 모드
  변경을 놓친다). 운영에서는 **만들지도 않는다**.
- `SentimentWorker` — 순수 합성 → 차단, `_source: "unavailable"` + 사유.
- `VectorStore` — ★혼종★. 후보 임베딩은 **실 재무**로 만든다. 통째로 막으면
  동작하는 실기능이 사라진다 ⇒ **합성 성분만** 제거했다(노이즈 · `item=None`
  폴백 · `_scoped()` 를 우회하던 캐시 키).

★그리고 불변식을 강제하는 장치를 만들었다★ — `tests/test_mock_store_gate.py` 가
`src/` 의 모든 서브클래스를 열거해 프로브가 없으면 실패하고, 합성 생성기를
폭발시켜 운영 조회가 거기 닿는지 **동작으로** 본다. 그 트립와이어는 만들자마자
전체 스위트에서 스스로 발화했다(다른 테스트 파일의 픽스처를 잡았다 — 범위를
`src.` 로 좁혔다).

★남은 것★ — 뉴스·콜 NLP 소스와 공급망 데이터 제공자는 **여전히 없다.**
바뀐 것은 "없는데 있는 척하지 않는다" 이지 "생겼다" 가 아니다.

### 7-3. 수정주가에 기업행위 이벤트가 없다

`adj_close` 는 저장된 이벤트로 계산한 값이 **아니다**. `krx_ingest.rebuild_adj_close()`
가 `return_1d`(등락률) 체인을 역산해 만든다. 그래서:

- 등락률이 없는 행(KIS 경로)은 **앵커를 세울 근거 자체가 없다**
- 분할·배당 이벤트 자체는 어디에도 저장되지 않는다 ⇒ 사후 검증 불가

`price_quality` 가 이 상태를 `not_rebuilt` / `no_return_data` 등으로 **보고는
한다.** 없는 것은 **왜 그런지** 였고, 지금 여기 적혔다.

### 7-4. `daily_prices` 를 선언하는 곳이 둘이다 — ★셋이 갈렸다★ (고침 `52c3415`)

- `data/krx_ingest.py` 의 raw DDL — `mktcap`·`list_shares`·`source`·`price_basis`
  **포함**, 인덱스·`updated_at` **없음**
- `kis_models.py::DailyPrice` — 그 넷 **없음**, 인덱스 둘·`updated_at` **있음**

기동은 `init_async_db()`(→`create_all`)를 먼저 부르지만(`lifecycle:287` → `:326`),
CLI 백필로 DB 를 먼저 만드는 것도 문서가 안내하는 정상 경로다.
그리고 ★`create_all(checkfirst=True)` 는 이미 있는 테이블을 **통째로** 건너뛴다★ —
그 테이블의 인덱스도 만들지 않는다.

메모리 SQLite 로 두 순서를 재봤다:

| 생성 순서 | 컬럼 넷 | 인덱스 | `updated_at` |
|---|---|---|---|
| `create_all` 먼저 (기동 경로) | ✅ (ALTER 가 채움) | ✅ 둘 | ✅ |
| `ensure_table` 먼저 (CLI 경로) | ✅ (ALTER 가 채움) | ❌ **없음** | ❌ **없음** |

⇒ **컬럼만 `ALTER` 가 치유하고 있었다.** 인덱스와 `updated_at` 은 아니었고,
그래서 **같은 제품의 두 DB 가 성능 특성이 달랐다.**

★고친 방향이 셋 다 다르다★ — 무엇이 옳은지가 항목마다 달랐기 때문이다:

- `ix_daily_date`(trade_date) → **위로**. `ensure_table` 도 멱등 생성한다.
  이 축이 PK 로 답할 수 없는 유일한 축이다(§7-1).
- `ix_daily_ticker_date` → **아래로**. PK 와 완전히 중복이라 최대 테이블의
  쓰기 비용만 냈다.
- `updated_at` → **아래로**. 읽는 곳이 없고, 지배적 writer 가 ORM 이 아니라
  `bulk_upsert`(raw SQL)라 갱신되지 않는다 ⇒ 두면 ★"갱신되지 않는 `updated_at`"
  이라는 그럴듯한 거짓 필드★가 된다.

★기존 DB 의 것을 DROP 하지 않는다★ — 저장소에 삭제 마이그레이션 선례가 없다.
새 DB 에 더 만들지 않을 뿐이다.

★처음 측정에서 `updated_at` 을 놓쳤다★ — 넷만 확인했고, **순서 무관 테스트를
쓰고 나서야** 드러났다. 목록을 손으로 정해 비교하면 목록 밖은 안 보인다.

---

## 8. 흔한 제안에 대한 판단

> *"TSDB(InfluxDB · TimescaleDB · kdb+)로 바꾸자"* · *"파티셔닝을 도입하자"*

★먼저 물을 것은 "지금 무엇이 느리거나 틀렸는가" 다.★ 이 저장소에는 이미 계측이
있고(`signal_path` 카운터 · 콜드 로딩 계측), 그것이 지목한 비용은 **네트워크 I/O
와 프레임 메모리**였지 DB 엔진이 아니었다. 일봉은 종목×영업일 규모이고, 분봉은
이미 날짜 파티션 Parquet 이다.

⇒ 이관은 전 테이블·전 테스트를 건드리면서 **측정된 이득이 없다.**
`CLAUDE.md`: *"정교함을 위한 정교함 금지 — 측정 가능한 투자 가치 없이 복잡도를
올리지 말 것."*

**다시 볼 조건** — §7-1 을 재서 횡단면 조회가 실제로 병목일 때. 그때도 첫 수는
TSDB 이관이 아니라 **인덱스 하나**다.

> *"틱·호가·대안데이터를 넣자"*

소비자가 먼저다. 이 저장소에는 선례가 있다 — 개정되지 않는 FRED 일별 계열을
토큰으로 등록했다가 *"개정되지 않아 빈티지 연구에도 보탬이 안 된다"* 는 이유로
되돌렸다. **그 데이터를 필요로 하는 팩터·전략·화면이 먼저 생길 때** 다시 본다.
