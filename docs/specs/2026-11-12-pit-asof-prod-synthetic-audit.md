# 운영의 시점(as_of) 평가가 합성값을 만든다 — 읽기 전용 감사 (2026-11-12)

> 사용자 요청("운영 as_of 가격 감사"). ★이 문서는 관측·기록만 한다 — `src` 는 0줄 바뀌었다.★
> 고침은 운영 동작과 스크리너 경로를 건드리므로 **별도 승인** 사항이다(§7 에 선택지).
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
