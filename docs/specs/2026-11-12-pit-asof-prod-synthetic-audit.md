# 운영의 시점(as_of) 평가가 합성값을 만든다 — 읽기 전용 감사 (2026-11-12)

> 사용자 요청("운영 as_of 가격 감사"). ★이 문서는 관측·기록만 한다 — `src` 는 0줄 바뀌었다.★
> 고침은 운영 동작과 스크리너 경로를 건드리므로 **별도 승인** 사항이다(§7 에 선택지).
>
> **상태 (2026-11-13)** — 사용자가 §7 의 A안을 고르셨고 고쳤다(§10). ★고침: F1 · F2 · F2b · F4 · F5★ / ★남음: F3 · F6 · F7★(§9 에 F4~F7 관측).
> §0~§8 은 고치기 전의 기록이라 그대로 둔다 — 파일:줄 번호는 2026-11-12 시점의 것이다.
>
> **CLAUDE.md §6** — *"`mock_allowed()` 가 유일한 판정 기준이며 `KIS_USE_MOCK` 이 정확히 `"1"` 일 때만 mock.
> ★운영에서는 합성값을 만들지 않습니다★ — 실패하면 `None`/빈값 + 사유."*
> **§4** — *"폴백은 ⑴ 의미가 알려져 있고 ⑵ 라벨이 붙고 ⑶ 동등 품질로 위장할 수 없고 ⑷ 관측·테스트 가능할 때만."*

## 0. 판정

시점 고정 스크리닝(`as_of_date` 가 있는 평가)은 운영(`KIS_USE_MOCK≠1`)에서 **가격은 항상, 재무는 공시를 못 읽은 종목마다** 합성값으로 계산한다.
그 값으로 괴리율·판정·종합 점수·순위가 나오고, 라벨은 화면까지 가지 않는다. §6 의 불변식과 §4 의 폴백 네 조건 가운데 ⑵⑶ 을 어긴다.

| # | 무엇 | 어디 | 운영에서 | 라벨 |
|---|---|---|---|---|
| F1 | 시점 가격 | `src/engine/pit_store.py:339` `get_price_asof` | `현재가 × (1 − 0.02×분기 수) × U(0.85, 1.15)` — ★과거 종가가 아니다★ | 없음 |
| F2 | 시점 재무 | `src/engine/pit_store.py:147` `get_financials_asof` | 그 시점 공시(DART)를 못 읽으면 `현재 재무 × 추세 × U(0.92, 1.08)` | `_source:"pit_mock"` — 스냅샷 안에만 |
| F2b | 재무 라벨 | `src/engine/screener.py:649` `_apply_pit_financials` | 위 합성 스냅샷을 항목에 덮어 쓰고도 `fundamentals_is_mock` 은 그대로(실 재무면 `False`) | ★값은 합성 · 라벨은 실데이터★ |
| F3 | 바탕 가격 | `src/engine/screener.py:986` `_mock_price` → `ohlcv_loader.mock_price_level` | 기본 `price_provider`. 표에 없는 코드는 `10,000 + (해시×137) % 200,000` | `price_is_mock=True`(기본값) |

## 1. 범위 · 방법 · 증거 등급

- 범위: `PITStore` 의 두 함수와 그것을 부르는 스크리너 경로. 백테스트 엔진의 체결 가격(일봉 적재분)은 범위 밖이다 — 거기는 보지 않았다.
- 방법: 코드 경로를 읽고, **운영 게이트 값(`KIS_USE_MOCK=0`)으로 함수를 로컬에서 직접 불러** 출력을 봤다(네트워크·키 없음).
- 증거 등급: ★관측(로컬 실행 · 코드 경로) — 운영 시스템 실측이 아니다★. 실제 운영에서 이 경로가 얼마나 자주 도는지, 사용자가 본 결과에
  얼마나 섞였는지는 **미상**이다(운영 로그·DB 를 보지 않았다).

로컬 관측(2026-11-12 · `KIS_USE_MOCK=0`):

```
get_price_asof("005930", "2024-06-28", 현재가=71,000) → 53,293.33
get_price_asof("005930", "2024-06-28", 현재가=50,000) → 37,530.52     ← 같은 날의 "종가"가 넘겨받은 현재가를 따라 바뀐다
_mock_price("005930") → 71,000 (고정 표)   ·   _mock_price("ZZZZZZ") → 83,980 (없는 종목에도 가격이 생긴다)
get_financials_asof(…, DART 스냅샷 없음, 현재 ROE 10 · PER 12 · PBR 1.2) → ROE 8.783 · PER 10.468 · PBR 1.048 · _source "pit_mock"
```

## 2. F1 — 시점 가격

`get_price_asof` 는 mock 일 때만 그 날의 mock 종가를 읽고(2026-11-11 고침), 운영에서는 예전 식 그대로다(`pit_store.py:355-361`):
종목코드와 분기 번호로 난수 씨앗을 만들고 `current_price × trend × rng.uniform(0.85, 1.15)` 를 돌려준다. 실제 과거 종가를 읽는 코드는 없다.

입력인 `current_price` 도 실제 현재가가 아니다. 스크리너의 기본 `price_provider` 는 `_mock_price`(F3)이고, 실시세로 덮어 쓰는 유일한 자리인
`_enrich_kis_quotes`(`screener.py:746`)는 시점 평가 중이면 ★일부러 건너뛴다★(`:763` — 오늘 시세로 되돌리면 룩어헤드가 되므로).
그래서 운영의 시점 가격은 **고정 표(또는 해시) × 추세 × 난수**다.

## 3. F2 · F2b — 시점 재무

`get_financials_asof` 는 `_dart_snapshot` 을 먼저 시도하고(DART 키 + 그 시점 공시), `None` 이면 ★운영에서도★ 현재 재무를 흔든 값을 낸다.
`_dart_snapshot` 이 `None` 인 경우: 키 없음 · corp_code 없음 · 그 분기 공시 없음 · 자본총계 결측 · 예외(로그는 `debug`).
함수 주석은 이것을 *"실패 시 mock 폴백"* 이라 부른다 — mock 게이트를 지나지 않는 mock 이다.

라벨은 스냅샷의 `_source` 에만 있다. `_apply_pit_financials` 는 여덟 칸(ROE·ROA·PER·PBR·부채비율·배당수익률·FCF·시총)을 항목에 덮어 쓰면서
`_source` 를 버리고 `fundamentals_is_mock` 을 고치지 않는다. 현재 재무가 실데이터인 종목이면 **합성으로 흔든 값 + "실데이터" 라벨**이 된다(F2b).
같은 함수의 `except Exception: pass` 는 실패도 삼킨다.

## 4. 도달 경로 — 누가 `as_of_date` 를 넘기나

| 경로 | 자리 | 화면 |
|---|---|---|
| `POST /api/v1/screener/run-pit` | `src/api/screener_routes.py:1160` | API 래퍼만 있다(`entities/screener/api/v2.ts`) — 부르는 위젯은 못 찾았다 |
| 스크리너 → 백테스트 실행 | `screener_routes.py:1679-1699` — 유니버스 `all_asof` · `top200_asof` 일 때 `as_of_date = 시작일` | 백테스트 편집기의 생존편향 보정(`widgets/backtester/strategyModel.ts:118`) |
| 캔버스 스크리닝 노드 `as_of`("과거 시점") | `src/api/allocation_graph_nodes_signal.py:91` → 위 `run-pit` 함수 | 캔버스 노드의 전문가 설정 |

## 5. 하류 영향

- 합성 가격으로 `gap_pct` · `verdict` · `composite_score` 가 계산되고 그 순서로 후보가 잘린다(`limit` · `top_n`).
- ★백테스트★: 생존편향 보정 유니버스를 고르면 **후보 풀이 합성 가격·(일부) 합성 재무로 거른 결과**다. 그 뒤의 체결·성과가 실데이터여도
  "어느 종목이 들어갔는가"는 합성 판정을 지났다. 응답의 `universe` 메타는 유니버스 폴백만 말하고 이 사실은 말하지 않는다.
- 캔버스: 과거 시점 스크리닝 노드의 종목 목록이 하류(비중 산출·백테스트)로 간다.
- 라벨이 화면에 닿는가: `price_is_mock` · `fundamentals_is_mock` 을 읽는 코드를 `frontend/src` · `src/api` 에서 찾지 못했다(검색 0건). 닿지 않는다고 본다.

## 6. 이 동작을 못 박아 둔 시험 (고칠 때 함께 바뀐다)

- `tests/test_mock_price_single_source.py::test_in_real_mode_the_as_of_price_is_unchanged` · `…the_base_price_is_unchanged` — 운영 식의 값을 골든으로 얼렸다
  (2026-11-11 · mock 쪽만 고치고 "운영 동작은 범위가 아니다"를 지키려고 둔 것).
- `tests/test_pit_dart.py::test_mock_fallback_without_key` · `test_mock_fallback_on_dart_error` — `_source == "pit_mock"` 폴백을 "기존 동작 불변"으로 단언.
- 이번에 더한 트립와이어 `tests/test_pit_asof_prod_tripwire.py` — 되어야 하는 동작을 `xfail(strict=True)` 로 적었다. 고치면 strict 가 표식을 떼라고 알린다.

## 7. 고침 선택지 (★구현하지 않았다 — 승인 사항★)

| 안 | 내용 | 얻는 것 | 잃는 것·위험 |
|---|---|---|---|
| A (권고) | 운영: 시점 가격은 적재된 실제 일봉(`ohlcv_loader._db_ohlcv_df` 계열)의 as_of 이하 마지막 종가. 없으면 `None` + 사유로 ★그 종목을 평가에서 뺀다★. 재무는 `_dart_snapshot` 실패 시 여덟 칸 `None` + 사유. 응답에 "뺀 종목 수·사유"를 싣는다 | 불변식 회복 · 결과가 실데이터 | 일봉·공시가 없는 종목이 빠져 결과 수가 준다(지금은 합성으로 채워져 있다) · 스크리너 경로 수정 · 위 골든 시험 갱신 |
| B | 운영에서는 시점 평가를 막는다(400 + 사유) — 데이터가 준비될 때까지 | 가장 작다 · 거짓 결과 0 | 생존편향 보정 백테스트와 과거 시점 노드를 운영에서 못 쓴다 |
| C | 동작은 두고 라벨만 화면까지(응답 `price_basis:"synthetic"` · 화면 칩) | 변경이 작다 | ★불변식은 그대로 어긴다★ — 권하지 않는다 |

F3(바탕 가격)는 A 를 해도 시점 밖 경로에 남는다 — 실시세 보강이 실패한 종목은 `price_is_mock=True` 인 채 표·해시 가격으로 판정된다. 따로 볼 일이다.

## 8. 하지 않은 것 · 미검증

- `src` 수정 0줄. 운영 로그·DB 실측 없음(빈도·영향 규모 미상). 백테스트 엔진의 체결 가격 경로는 보지 않았다.
- `get_financials_asof` 의 DART 경로가 실제로 얼마나 자주 `None` 이 되는지 재지 않았다.
- 화면이 라벨을 쓰지 않는다는 판단은 문자열 검색에 근거한다(동적 키 접근이 있으면 놓친다).

## 9. 고치려고 읽다가 더 찾은 것 (2026-11-13 · ★로컬 실행으로 재현★ — mock + `SNAPSHOT_DB=1` · 임시 sqlite)

§0~§8 의 감사는 `PITStore` 의 두 함수만 봤고 ★그 값을 감싸는 스크리너의 `item:` 캐시★를 보지 않았다. `ValuationScreener.run` 은 과거 시점 평가에서도
그 캐시를 읽고 썼다 — 운영에서는 `snapshot_db.enabled()` 가 켜진다(DART 키가 있거나 mock 이 아니면).

| # | 무엇 | 관측(as_of = 2024-06-28 · 005930) | 고침 |
|---|---|---|---|
| F4 | as_of 평가가 `item:` 캐시를 ★읽는다★ | 현재 항목이 캐시에 있으면 평가 0건으로 ★오늘 값★(76,856)을 돌려줬다 — 그 날 종가는 69,224. 적재된 종목은 PIT 를 통째로 건너뛴다 | ✔ 읽지 않는다 |
| F5 | as_of 평가가 `item:` 캐시에 ★쓴다★ | 빈 캐시에서 as_of 로 평가한 뒤 `item:005930` 에 69,224 가 남고, 뒤의 ★현재★ 스크리닝이 평가 0건으로 그 값을 돌려줬다(TTL 3일) | ✔ 쓰지 않는다 |
| F6 | as_of 평가 항목에 ★현재★ 펀더멘털·팩터를 붙인다 | `attach_fundamentals`(+ 가격 팩터 · 확장 팩터)가 as_of 로 새로 평가한 3종목에 불렸다. 그 필드로 거르면 현재 값으로 거른다. 읽은 공시에 없는 칸(배당수익률 · FCF · 시총 시계열 없는 PER/PBR)도 현재 값이 남는다('부분 적용') | ✘ 남음 |
| F7 | 재무가 없는 항목의 종합 점수 | 운영 게이트 · DART 키 없음: 판정 "데이터 없음" · 적정가 0 인 항목이 ★종합 점수 38.0★ 을 받고 목록에 남는다(`fundamentals_is_mock=True` 라벨은 붙는다). as_of 에 한정된 것이 아니라 현재 스크리닝도 같다 | ✘ 남음(범위 밖 — 기록만) |

A안만 고쳤다면 F4 때문에 ★적재된 종목 대부분에서 고침이 우회됐을 것이다★(캐시가 PIT 경로 앞에 있다).

## 10. 고침 (2026-11-13 · A안 + F4·F5)

- **F1 가격** — `universe_select.close_asof(ticker, date)`: as_of 이하 마지막 적재 봉의 `close` 와 그 행의 `trade_date · source · price_basis`. 없으면 `None` + 사유
  (`not_loaded` · `stale`(마지막 봉이 10 달력일보다 오래됨) · `store_error`(DB 를 못 읽음 — 미적재가 아니다) · `bad_date`).
  `PITStore.price_asof_detail`: mock 은 그대로(그 날의 mock 종가), ★운영은 실제 종가 또는 없음★ — `현재가 × 추세 × 난수` 는 운영 경로에서 걷었다(mock 봉이 없는 2000-01-03 이전 날짜의 mock 폴백으로만 남는다).
  스크리너: 종가가 없으면 그 종목을 평가에서 빼고 사유를 모은다. 조회 중 예외도 뺀다(전에는 `except: pass` 로 ★오늘 가격★으로 계속 평가했다). 실제 종가로 평가한 항목은 `price_is_mock=False` + `asof_price`(출처).
- **F2 · F2b 재무** — `get_financials_asof`: 운영에서 그 시점 공시를 못 읽으면 여덟 칸 `None` + `_source:"pit_unavailable"` + `_reason`(`no_dart_key` · `filing_unreadable`). 흔든 값(`pit_mock`)은 mock 모드에서만.
  `_apply_pit_financials`: 미상이면 항목의 여덟 칸을 `None` 으로(오늘 값을 과거 값처럼 남기지 않는다) + `asof_financials`. `pit_mock` 이면 `fundamentals_is_mock=True`. 예외를 삼키지 않는다.
- **F4 · F5 캐시** — as_of 평가는 `item:` 캐시를 읽지도 쓰지도 않는다. 현재 스크리닝의 캐시는 그대로다.
- **응답** — `ScreenerResult.asof = {excluded: {count, by_reason, sample≤20}, financials_unavailable: {count, by_reason}}` → `POST /screener/run-pit` 의 `asof` ·
  백테스트 `universe.asof_screening`(시점 유니버스일 때만) · 캔버스 과거 시점 스크리닝 노드의 view·사실 줄(뺀 것이 있을 때만). 제외는 `failures` 와 섞지 않는다.
- **고친 뒤 관측(로컬 · 운영 게이트 `KIS_USE_MOCK=0` · 임시 sqlite · 외부 연결 차단)** — 005930 은 적재한 종가 81,500 으로 평가되고(`price_is_mock=False` · 출처 `2024-06-28/krx/raw`)
  재무는 미상(`no_dart_key` — ROE·PER `None`), 000660 은 `not_loaded`, 1년 반 전 봉만 있는 035420 은 `stale` 로 빠졌다. `failures` 0 · 외부 시도 0.
- **바뀌는 동작(운영)** — ① 일봉이 적재되지 않은 종목은 과거 시점 스크리닝·생존편향 보정 유니버스의 후보에서 ★빠진다★(전에는 합성 가격으로 채워져 있었다). 일봉 적재가 얕으면 결과가 크게 준다 — 응답의 수·사유로 보인다.
  ② 과거 시점 평가는 전부 새로 계산하므로 `SCREENER_MAX_LIVE_COMPUTE`(기본 400) 상한에 더 자주 걸린다 — 응답 `capped` 로 관측된다. 상한은 바꾸지 않았다.
  ③ 공시를 못 읽은 종목의 재무 여덟 칸이 `None` 이라, 그 칸에 조건을 건 필터는 그 종목을 통과시키지 않는다.
- **증거 등급** — ★관측(로컬 실행 · 코드 경로)★. 운영 DB·운영 로그로 재지 않았다: 실제로 몇 종목이 빠지는지 · 상한에 얼마나 걸리는지는 **미상**이다.
  `close`(적재된 정의 — `price_basis` 로 표시)와 주당 적정가의 주식 수 기준이 액면분할 전후로 맞는지는 **미검증**이다(가격 정의 전환은 하지 않았다).
