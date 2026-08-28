# 데이터 추출 API 전수 감사 — 제공자 능력 vs 실제 적재

> 대상: KRX · KIS · FRED · ECOS · DART. **실제 소스코드 기준**(문서·주석 아님).
> ★구현하지 않았다 — 감사와 우선순위·최소 계획까지.★
> 관련: [`노출 분류 계약`](2026-08-26-exposure-taxonomy-contract.md) ·
> [`아키텍처 메모 §15`](2026-08-25-macro-layer-architecture.md)

---

## 0. 왜 지금인가

정준 분류(`b0dffdf`)가 게이트 조건 5의 병목을 **분류가 아니라 가격 데이터**로
좁혔다. 그래서 "제공자가 줄 수 있는 것" 과 "우리가 실제로 가져오는 것" 의 차이를
전수로 쟀다.

---

## 1. 제공자별 실제 수집 범위

### 1.1 KRX — ★엔드포인트 절반이 호출되지 않는다★

| 파일 | 엔드포인트 | 적재 여부 |
|---|---|---|
| `krx_client.py` | `/sto/stk_bydd_trd` · `/sto/ksq_bydd_trd` (전종목 일별) | ✔ `krx_ingest.backfill` |
| 〃 | `/idx/kospi_dd_trd` · `/idx/kosdaq_dd_trd` (지수 일별) | ✔ `backfill_index` |
| 〃 | ★`/idx/drvprod_dd_trd`(VKOSPI)★ | ★호출부 **0**★ |
| 〃 | ★`/sto/mgn_bydd_trd`(신용잔고)★ | ★호출부 **0**★ |
| 〃 | ★`/sto/shrt_bydd_trd`(공매도)★ | ★호출부 **0**★ |
| 〃 | ★`/sto/lend_bydd_trd`(대차)★ | ★호출부 **0**★ |
| `krx_mdc.py` | `MDCSTAT02303` 투자자별 상세 (비공식 웹 JSON) | 조건부 — ISIN 필요(→ §3.3) |

`EXTRA_ENDPOINTS` 4종을 읽는 `get_extra()` 는 **정의만 있고 아무도 부르지 않는다**
(`grep -rn get_extra src/ scripts/ tests/` → 정의·내부참조뿐).

★그리고 그 사실이 화면에서 구분되지 않는다★ `source_registry` 에 KRX 4계열이
등록돼 있어 `available:false` 로 정직하게 나오지만, 원인이 **"키 미설정"** 인지
**"수집 코드 없음"** 인지 말하지 않는다. 전자는 사용자가 고칠 수 있고 후자는
우리가 고쳐야 하는데, 같은 표시를 쓴다.

### 1.2 KIS — 시세 6 · 주문 4, 마스터는 별도 경로

TR ID 실측:

```
시세  FHKST01010100 현재가 · FHKST01010400 일별 · FHKST01010900 투자자
      FHKST03010100 일봉차트 · FHKST03010200/03010230 분봉
주문  TTTC0801U/0802U/0803U · TTTC8434R   (모의: VTT*)
```

**마스터** `kis_master_parser` 는 다운로드 파일에서 ISIN · 그룹코드(ST/EF/EN/RT) ·
KOSPI200/KOSDAQ150 편입 · 시총규모 · 업종 3단(대/중/소) · 관리/경고/거래정지/
정리매매/투자주의 · 시가총액을 뽑는다. ★내용은 충실하다.★

문제는 **산출물이 파일 캐시 하나**라는 것 — `master_flags_cache.json`.
이 환경에는 그 파일이 **없다**(실측 0건).

### 1.3 FRED — ★같은 제공자에 경로가 둘이고, 하나만 빈티지를 쓴다★

| 경로 | 호출 | 빈티지 | 소비자 |
|---|---|---|---|
| `macro_collector.FredClient.fetch_series` | `/fred/series/observations` + `observation_start/end` + ★`frequency="m"`★ | ★없음★ | 매크로 대시보드 · **국면 축**(→ 배분) |
| `pit_macro.fetch_observations` | 같은 URL + ★`realtime_start=realtime_end=as_of`★ | ✔ | `timing_rules_v2` (curve_slope · indicator · FCI) **만** |

★핵심 발견★ **빈티지 능력은 이미 구현돼 있고 살아서 쓰이고 있다.** 다만 쓰는 쪽이
타이밍 규칙 하나뿐이고, **배분 결정에 쓰이는 국면 축은 빈티지 없는 경로**를 읽는다.

> [아키텍처 메모 §15](2026-08-25-macro-layer-architecture.md)의 "수집 경로가 빈티지를
> 가져오지 않는다" 는 **국면 축 기준으로는 정확**하다. 저장소 전체로 보면
> **"경로가 둘인데 소비자별로 갈라져 있다"** 가 더 정확한 서술이다.

그리고 `frequency="m"` 은 `pit_macro` 독스트링이 스스로 지적한 결함이다 —
*"서버측 집계가 월중 공표 타이밍을 뭉갠다."* 대시보드 경로가 그것을 그대로 쓴다.

`derive_usage(has_vintage, depth_ok, lag_known)` 라는 판정 장치가 있고
`timing_rules_v2` 는 **관측치에서 파생**해 태운다(손으로 등급을 지정하지 않는다 —
좋은 설계). ★국면 축은 그 장치를 통과하지 않는다.★

### 1.4 ECOS — 엔드포인트 1종

`StatisticSearch` 만 쓴다(40계열). `StatisticTableList`·`StatisticItemList`·
`KeyStatisticList` 참조 **0건** — 통계표/항목 좌표를 코드에 선언해 두고
`source_registry` 가 그 단일 출처 역할을 한다(P4-D1 의 구조).

★ECOS 에 빈티지 엔드포인트가 없다는 것은 영구 제약이고 이미 정확히 기록돼 있다★
(`PROVIDER_HAS_VINTAGE[ECOS] = False`).

### 1.5 DART — 5 엔드포인트 + corpCode, 전부 사용 중

`company.json` · `fnlttSinglAcnt.json` · `fnlttSinglAcntAll.json` ·
`alotMatter.json`(배당) · `elestock.json`(임원·주요주주) · `corpCode.xml`.
호출부·캐시·쿼터 카운터·mock 폴백이 모두 있다. ★5개 제공자 중 가장 성숙하다.★

**미사용 능력**: 공시검색(`list.json`) · 사업보고서 원문(`document.xml`) ·
지분공시(`majorstock.json`) · 증자/감자/주식분할 공시 — ★코드에 없다★.
즉 **corporate action 을 공시에서 읽는 경로가 없다**.

---

## 2. 8개 도메인 판정

| # | 도메인 | 현재 상태 | 판정 |
|---|---|---|---|
| 1 | **Instrument Master** | 파싱 충실(ISIN·지수편입·업종3단·상태) | ★파일 캐시 1개에만 존재★ · DB 미적재 |
| 2 | **Historical prices** | `daily_prices` 한 테이블에 **writer 둘** | ★불일치★ → §3.1 |
| 3 | **Corporate actions** | 공시 경로 없음. KRX 등락률 체인으로 `adj_close` **역산** | 부분 — KRX 적재분만 유효 |
| 4 | **ETF metadata** | 보수·AUM·NAV·추적오차 **0건** | ★없음★ (`instrument_selector` 가 이미 `unavailable` 로 선언) |
| 5 | **Macro vintages** | ALFRED 구현·사용 중 | ★소비자별 경로 분기★ → §3.2 |
| 6 | **Publication lag** | `lag_known` 을 관측치에서 파생(좋음) | 부분 — 국면 축은 `"unspecified"` |
| 7 | **Financial statements** | DART 5종 + 연/분기 이력 + 캐시 + 쿼터 | ✔ 가장 성숙 |
| 8 | **Company identifiers** | ticker↔corp_code(DART) · ticker↔ISIN(KIS) | ★ISIN 이 휘발성 캐시에만★ → §3.3 |

---

## 3. 교차 결함

### ★3.1 `daily_prices` 에 writer 가 둘이고 수정주가 체인이 한쪽에만 있다★

```
krx_ingest.bulk_upsert        → ticker,date,OHLCV,trading_value,return_1d,mktcap,list_shares
ohlcv_loader.ingest_df_to_db  → ticker,date,OHLCV                        ← return_1d 없음
```

`rebuild_adj_close()` 는 **`return_1d` 체인**으로 `adj_close` 를 역산한다:

```
adj[t-1] = adj[t] / (1 + r[t]/100)
```

KRX 등락률은 분할·증자가 조정된 기준가 대비라 **corporate action 점프가 제거된다**.
그런데 KIS 경로로 들어온 행에는 `return_1d` 가 NULL 이고, 그때 함수는 스스로 적은 대로
*"등락률 결측 봉은 원주가 비율로 폴백"* 한다 —
★그 폴백이 제거하려던 점프를 **다시 집어넣는다**.★

그리고 두 writer 가 같은 PK `(ticker, trade_date)` 를 공유하는데
**어느 경로로 들어온 행인지 기록이 없다**(provenance 컬럼 없음).

★백테스트에 직접 영향을 준다★ 분할일 하나가 조정되지 않으면 그날 수익률이 수십 %로
잡히고, 그 이상치 하나가 공분산·팩터 추정을 흔든다 — 이 저장소가 `VIXCLS` 한 달 변화
**6730%** 로 Ledoit-Wolf 를 λ=1.0 까지 밀어 상관구조를 통째로 지웠던 것과 같은 계열이다.

### ★3.2 빈티지 경로가 소비자별로 갈라져 있다★

같은 FRED 계열이 타이밍 규칙에서는 **빈티지 기준**, 국면 축에서는 **최신 개정본**으로
읽힌다. 두 화면의 숫자가 다르고, 그 차이는 "어느 화면을 보느냐" 에 달렸다.

### ★3.3 식별자 브리지가 휘발성 캐시에만 있다★

`ISIN` 은 KIS 마스터 파싱에서만 나오고 `master_flags_cache.json` 에만 저장된다.

```
master_flags_cache.json 없음
  → krx_mdc 투자자 플로우 백필 불가        (ISIN 이 조회 키)
  → sector_groups_for() 가 {}             (기존 결함, 이미 기록됨)
  → exposure_taxonomy 규칙 배정 불가       (no_master_flags)
```

★파일 하나가 없어서 세 기능이 멈춘다.★

### 3.4 mock 폴백 — ★설계는 옳다, 고칠 것이 없다★

`load_ohlcv_unified` 는 DB→KIS→mock 순이고 **mock 결과를 DB 에 적재하지 않는다**
(적재는 KIS 성공 경로에서만). `mock_allowed()` 게이트도 정확히 걸려 있다.
17개 파일이 mock 경로를 갖지만 전부 게이트를 통과한다.

### 3.5 중복 수집 — 가격 외에는 없다

`snapshot_db` 는 캐시 테이블이고 `daily_prices` 와 역할이 다르다.
`etf_prices` 는 `load_ohlcv_unified` 를 재사용한다(중복 아님).
★중복은 §3.1 하나다.★

---

## 4. 개선 우선순위

| 순위 | 항목 | 왜 이 순서인가 | 규모 |
|---|---|---|---|
| **P0** | ★가격 출처 일원화 + 수정주가 정직화★ (§3.1) | 잘못된 수익률은 **모든 하위 계산을 오염**시킨다 | 小 |
| **P1** | ★마스터·식별자를 DB 로★ (§3.3) | 파일 하나가 3개 기능의 단일 장애점 | 中 |
| **P2** | 국면 축을 빈티지 경로로 (§3.2) | 게이트 조건 2의 잔여분. ★배분 결정 경로 — 별도 승인★ | 中 |
| **P3** | KRX `get_extra` 4종 배선 | 코드가 이미 있고 호출만 없다. 신용잔고·공매도는 알파 후보 | 小 |
| **P4** | ETF 메타데이터 | 없는 것을 새로 만들어야 한다 — 벤더 필요 | 大 |
| **P5** | DART 공시 기반 corporate action | P0 가 KRX 체인으로 대부분 덮으면 우선순위가 내려간다 | 大 |

★P4 가 낮은 이유★ ETF 메타데이터는 게이트 조건 어디에도 필요하지 않다.
`instrument_selector` 가 이미 그 부재를 `unavailable` 로 **정직하게** 내고 있어
조용한 결함이 아니다.

---

## 5. 최소 구현 계획 (P0 + P1)

### 5.1 `daily_prices` 에 출처를 기록한다

```sql
ALTER TABLE daily_prices ADD COLUMN source VARCHAR(8);   -- 'krx' | 'kis'
```

- 두 writer 가 각자 `source` 를 쓴다.
- ★기존 행은 `NULL` = "미상" 으로 남긴다★ — 소급 추정하지 않는다
  (`exposure_taxonomy` 의 미배정 규율과 같다).
- ★`rebuild_adj_close` 가 `return_1d` 결측 행을 **조용히 폴백하지 않고 건너뛰고
  보고한다**★ — 지금의 원주가 비율 폴백이 점프를 되살린다.

### 5.2 수정주가 품질을 관측 가능하게 — `src/data/price_quality.py`

```python
def adj_close_coverage(tickers=None) -> dict:
    """{universe, adjusted, missing_return_1d, by_source, unadjusted_tickers[]}"""
```

`source_coverage`·`exposure_taxonomy.coverage()` 와 같은 모양.
★몇 %가 조정되지 않았는지가 화면에 남지 않으면 아무도 모른다.★

### 5.3 마스터를 DB 로 — `src/data/instrument_master_store.py`

```sql
CREATE TABLE instrument_master (
  ticker PK, isin, name, market, group_code, is_etf,
  is_kospi200, is_kosdaq150, cap_size,
  sector_code, sector_mid, sector_sub,
  is_managed, alert_code, is_halted, market_cap, as_of, source
)
```

`save_master_flags()` 가 파일 **과** DB 에 쓰고, `load_master_flags()` 는
**파일 → DB** 순으로 읽는다. ★파일이 있으면 지금과 동작이 완전히 같다.★

### 5.4 미사용 엔드포인트를 값으로 선언

`source_registry` 가 KRX 4계열에 대해 *"엔드포인트는 있으나 수집 코드가 없음"*
(`not_ingested`)을 **키 미설정과 구분해서** 낸다. 배선(P3)은 그 다음이다.

### 파일

| 파일 | 변경 |
|---|---|
| `src/data/krx_ingest.py` | `source` 컬럼·마이그레이션 · `rebuild_adj_close` 폴백 제거 + 보고 |
| `src/data/ohlcv_loader.py` | `ingest_df_to_db` 에 `source='kis'` |
| `src/data/price_quality.py` | **신규** |
| `src/data/instrument_master_store.py` | **신규** |
| `src/data/stock_master.py` | `save/load_master_flags` 가 DB 도 경유(파일 우선) |
| `src/data/source_registry.py` | `not_ingested` 사유 구분 |

### 테스트

`tests/test_price_provenance.py` · `tests/test_instrument_master_store.py`

| # | 못 박는 것 |
|---|---|
| P1 | 두 writer 가 각자 `source` 를 남긴다 (짝: 값이 서로 다르다) |
| P2 | ★`return_1d` 결측 행은 `adj_close` 를 **추정하지 않는다**★ (현행 폴백이 red) |
| P3 | ★짝★ `return_1d` 가 있으면 체인이 정확히 재구성된다 — **분할 픽스처로 점프 제거 확인** |
| P4 | `adj_close_coverage` 가 미조정 티커를 **이름으로** 낸다 |
| P5 | 마스터 DB 왕복 — 파일 없이도 ISIN 조회 성공 |
| P6 | ★파일이 있으면 DB 를 읽지 않는다★ (기존 동작 불변) |
| P7 | `source_registry` 가 "키 없음" 과 "수집 코드 없음" 을 다른 사유로 낸다 |

**변이**: ① `source` 를 상수로 ② 결측 행을 다시 폴백 ③ coverage 가 미조정을 0 으로
④ DB 가 파일을 덮음 ⑤ 두 사유를 같은 문자열로.

---

## 6. 하지 않는 것

- ★P2 국면 축 빈티지 배선★ — **배분 결정 경로**라 별도 승인이 필요하다.
- KRX `get_extra` 실제 배선(P3) · ETF 메타데이터(P4) · DART 공시 CA(P5).
- `sector_groups_for` 교체 · 정준 분류 소비 지점 배선 — 여전히 Macro→Allocation 정책.
- DFM · TSFM · FCI · Neural SDE · Growth-at-Risk.
- 기존 `daily_prices` 행의 `source` 소급 추정.

## 재현

```bash
cd /home/user/Project-Alpha
grep -rn "get_extra\|EXTRA_ENDPOINTS" src/ scripts/ tests/ --include=*.py   # 호출부 0
grep -n "realtime_start" src/data/pit_macro.py src/services/macro_collector.py
grep -n "INSERT INTO daily_prices" -A3 src/data/krx_ingest.py src/data/ohlcv_loader.py
KIS_USE_MOCK=1 python3 -c "from src.data.stock_master import load_master_flags; print(len(load_master_flags()))"
```

---

## 부록 A — P1·P3 해소 (2026-08-28)

### A.1 §3.3 식별자 브리지 — ★고아는 스토어가 아니라 **판정**이었다★

§3.3 이 지적한 "파일 하나가 세 기능의 단일 장애점" 은 `1e3226a` 에서 이미 해소됐다
(파일 → DB 이중화). 이번에 재 보니 남은 구멍은 다른 것이었다:

★`isin_of()` 는 소비자가 0★ 이고, 유일한 실소비자 `krx_mdc.backfill_flows_krx` 는
같은 조회를 **인라인으로 다시** 썼다. 그래서 "이 ISIN 이 쓸 수 있는 값인가" 를
세 곳이 **두 가지 규칙**으로 판정했다:

| 위치 | 규칙 |
|---|---|
| `kis_master_parser:147` (쓰기) | `len == 12` 이면 저장, 아니면 `""` |
| `instrument_master_store.isin_of` | ★비어 있지 않으면 유효★ — 혼자 다르다 |
| `krx_mdc:164` (유일한 소비자) | `len == 12` |

**해소**: `isin_status()` 하나가 판정하고 `isin_of()` 는 그 래퍼다. 동작 변경은
"덜 받아들인다" 하나(11자 → `None`). 건너뛴 사유는 `no_master`/`no_isin`/
`malformed` 셋으로 갈라졌다 — ★셋째가 둘째로 뭉개지면 파서 버그가 영원히 안
보인다★. `master_flags_origin()` 이 파일/DB/없음을 관측하고(순서는 불변),
`isin_coverage()` 가 기존 상태 응답에 실린다.

### A.2 §5.4 미사용 엔드포인트 — ★배선했고, 모르는 집계는 거부한다★

배선하면서 계획에 없던 사실 둘을 만났다.

**⑴ 접기 규칙이 필요하다.** `get_extra` 는 `basDd` **하루치**이고
`parse_extra_rows` 결과에 **종목 식별자가 없다**. `/sto/*_bydd_trd` 셋은 전종목
일별 규약이라 하루에 여러 행이 온다 — 시장 한 값으로 접는 정의가 필요한데
★엔드포인트가 미검증★ 이라 그 정의를 지어내는 것이 된다. 그래서
`COLLAPSE_SINGLE`(이름으로 한 행) / `COLLAPSE_UNKNOWN`(여러 행이면 거부)을
`krx_client.EXTRA_SERIES` 에 선언했다. 거부 사유는 **두 갈래**다 — 이름이 유일하지
않은 것과 집계 정의가 없는 것은 고치는 사람이 다르다.

**⑵ 선언이 손 목록이었다.** `NOT_INGESTED_KEYS` 는 비우기만 하면 가드가 풀리는
모양이었다. `not_ingested_keys()` 로 바꿔 **수집 경로에서 유도**한다 —
`EXTRA_SERIES` 에서 계열을 지우면 선언이 스스로 돌아온다.

**★늘어나지 않는 것★** `PROVIDER_HAS_VINTAGE[KRX] = False` 다. 이 계열들은 영구
forward-only 이고 **백테스트 적격 데이터를 한 줄도 늘리지 않는다**. 증거등급은
**E1(픽스처)** — `KRX_API_KEY` 가 없고 호스트가 프록시 403 이라 실호출로 확인한
것이 하나도 없다. 바뀐 것은 "아니오" 의 정확도다:

    이전: "수집 코드가 없습니다 — 키를 설정해도 값이 오지 않습니다"
    이후: "API 키가 설정되지 않았습니다" (수집 경로) ·
          "엔드포인트 미검증 — 호스트 프록시 차단" (레지스트리) ·
          "집계 정의가 미확정입니다" (다중 행)

`MARGIN`·`SHORT`·`LENDING` 의 시장 집계 정의는 ★실응답 1건이면 확정된다★.

### A.3 재현 (갱신)

```bash
cd /home/user/Project-Alpha
KIS_USE_MOCK=1 python3 -c "
from src.data.source_registry import not_ingested_keys, status
print(sorted(not_ingested_keys()))                      # []
print(status('VKOSPI')['reason'][:40])"
KIS_USE_MOCK=1 python3 -c "
from src.data.krx_extras import collect_all_extras
for k, s in collect_all_extras('2026-08-01','2026-08-07').items():
    print(k, s.source, (s.reason or '')[:40])"
KIS_USE_MOCK=1 python3 -c "
from src.data.instrument_master_store import isin_status, isin_coverage
print(isin_status('005930')); print(isin_coverage())"
```

---

## 부록 B — 골든 스냅샷의 흔들림 ★원인 규명·항목 종결★ (2026-08-28)

HISTORY 2026-08-28 이 남긴 미해결 항목: *"`t3_geometry` 산출이 소스 변경 없이도
환경에 따라 한 필드가 흔들린다. ★원인 미상★ — 골든 스냅샷을 불변 증거로 쓰려면 이
흔들림의 출처를 먼저 알아야 한다."*

### B.1 측정

| # | 측정 | 결과 |
|---|---|---|
| 1 | 기준선(08-27) 이후 **계산 사슬**을 건드린 커밋 | ★0건★ — 21커밋 전부 무편집 |
| 2 | 기준선 시점 커밋 `da7e191` 을 워크트리에서 오늘 실행 | ★오늘 HEAD 와 바이트 동일★ |
| 3 | 같은 설정 4연속 실행 | md5 동일 — 완전 결정론 |
| 4 | `OPENBLAS_CORETYPE` 만 교체 | ★그 한 필드가 뒤집힌다★ |

```
CORETYPE=NEHALEM·SANDYBRIDGE·SKYLAKEX → 08-27 기준선과 차이 0  (mdd_pct -23.16)
CORETYPE=HASWELL · 이 호스트 기본값    → 오늘 산출과 차이 0    (mdd_pct -23.17)
```

**원인**: numpy 1.26.4 가 싣는 OpenBLAS 는 `DYNAMIC_ARCH=1` 빌드라 **호스트 CPU 를
보고 런타임에 마이크로커널을 고른다**. 컨테이너가 다른 기계에 스케줄되면 부동소수
합산 순서가 바뀌고, 그 차이가 `mdd_pct` 의 넷째 유효숫자까지 올라온다.

★결론: "골든 바이트 동일" 은 **코드의 성질이 아니다**★ — 호스트의 성질이 섞여 있다.

### B.2 두 번째 함정 — ★기준선이 어떤 명령으로 뽑혔는지 기록이 없다★

도구를 만들자마자 걸렸다. 저장된 `t3_bl_ep` 기준선은 `--conf 25` 로 뽑혔는데
재생성은 기본값(분해 Ω, conf≈1.111)이었고 **40개 필드가 전부 크게** 달랐다.
`--conf 25` 로 다시 뽑으니 `identical` 이다. 즉 **회귀가 아니라 다른 실험**이었다.

BLAS 쪽과 달리 이쪽은 차이가 **크게** 나므로 회귀로 오독되기 쉽다.

### B.3 ★골든 사용 규칙★

1. **같은 호스트에서 기준선과 대상을 연달아 생성**해 비교할 때만 바이트 동등을
   주장할 수 있다. (직전 P0·P2·P1·P3 커밋이 그 방식이었으므로 그 결론들은 유효하다.)
2. **저장된 기준선**과의 비교는 `scripts/golden_compare.py` 로 한다. `diff` 는
   "달랐다" 만 말하고 원인을 가르지 못한다.
3. `last_place` 는 ★불변의 증거가 아니라 **지문 대조 요구**★ 다. 종료코드 2 로
   성공(0)과 분리돼 있다.
4. `설정이 다릅니다` 가 먼저 뜨면 **다른 실험을 비교한 것**이다 — 코드를 의심하기 전에
   명령을 맞춘다.

### B.4 기준선 재생성 명령 (★이것을 적어 두지 않아 B.2 가 생겼다★)

```bash
KIS_USE_MOCK=1 python3 scripts/t3_transmission.py --engine both --conf 25 --report t3_bl_ep.json
KIS_USE_MOCK=1 python3 scripts/t3_transmission.py --arch D             --report t3_d.json
KIS_USE_MOCK=1 python3 scripts/t3_geometry.py                          --report geom.json
python3 scripts/golden_compare.py --fingerprint > fingerprint.json
```

### B.5 남는 미상

이 컨테이너 하나로는 **CPU 한 종류**만 봤다. "모든 골든 차이가 BLAS 때문" 이라는
뜻이 아니다 — 그래서 `last_place` 가 "무해" 가 아니라 "지문을 대조하라" 인 것이다.
`OPENBLAS_CORETYPE` 을 저장소에 고정하지 않은 이유: 문제는 **비교 방법**이지
계산이 아니고, 연구 스크립트 하나 때문에 전 프로세스의 BLAS 커널을 묶는 것은
대가가 크다.
