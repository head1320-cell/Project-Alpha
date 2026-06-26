# 내부자/개인 수급 팩터 실데이터 연결 — 설계 스펙

- 날짜: 2026-06-26
- 브랜치: `claude/keen-thompson-bdk3e8`
- 상태: 승인됨 (브레인스토밍 → 구현 대기)

## 1. 배경 / 문제

`market_data`의 behavioral 수급 패밀리(`foreign_net_5d`, `institution_net_5d`,
`insider_net_20d`, `retail_net_5d`)와 이를 쓰는 behavioral 시그널 4종
(`insider_buy_retail_sell`, `smart_divergence`, `institutional_accumulation`,
`capitulation_reversal`)이 **mock 전용**이다. 직전 실데이터 전용 게이트(`mock_gate`) 적용으로
운영(`KIS_USE_MOCK=0`)에선 이 필드들이 전부 `None`("—") → behavioral 시그널이 운영서 평가 불가.

핵심 발견(코드 확인): KIS가 적재하는 `investor_flows` 테이블에 이미 **개인(`prsn_*`)·외국인
(`frgn_*`)·기관(`orgn_*`)** 일별 순매수가 들어 있다. 즉 개인/기관/외국인은 **소스가 없어서가
아니라 behavioral 경로가 `investor_flows`에 배선 안 됐을 뿐**이다(`price_factors_store`는 이미 배선됨).
오직 **내부자(insider)** 만 KIS에 없고 DART 지분공시가 필요하다.

## 2. 목표 / 비목표

**목표**
- behavioral 수급 패밀리를 운영에서 **실데이터**로 평가(개인/기관/외국인은 `investor_flows`, 내부자는 DART).
- 실데이터 전용 원칙 유지: 운영선 실데이터 또는 정직한 `None`("—"), mock 모드선 합성(회귀 불변).
- behavioral 시그널 4종이 운영서 실제로 작동.

**비목표 (Out of scope)**
- KRX MDC 깊은 과거 백필 — 이미 opt-in(`krx_mdc.py`)으로 존재, 변경 없음.
- 내부자 일배치/크론 — Approach A는 **온디맨드**(배치 없음).
- 컨센서스/배당 등 다른 미연결 팩터 — 별도 작업.

## 3. 아키텍처 — 작고 독립적인 3개 단위

market_data.py 비대화를 막기 위해 책임을 분리한다.

### 3.1 `dart_client.get_insider_disclosures(corp_code)` (신규, 저수준)
- DART `elestock.json`(임원·주요주주 특정증권등 소유상황보고서) 호출 → 행 파싱.
- 반환: `[{"rcept_date": "YYYYMMDD", "irds_cnt": int(±), "repror": str, ...}, ...]`
  - `sp_stock_lmp_irds_cnt`(특정증권등 소유주식 증감 수)를 부호 있는 정수로 파싱(쉼표/공백/빈값/`-` 안전).
  - 날짜는 `rcept_no` 접수번호 접두 8자리(YYYYMMDD)로 해석.
- 기존 `dart_cache/` 디스크 캐시 재사용(1일 TTL). 순수 fetch+parse(집계·게이트 없음).
- 실패/미설정/빈 응답 → `[]` 또는 `None`(상위에서 정직 처리). 크래시 금지.

### 3.2 `src/data/insider_flows.py` (신규 모듈, `kis_flows.py`와 대칭)
- `insider_net(stock_code, days=20) -> float | None`:
  - `get_corp_code(stock_code)`(기존) → `get_insider_disclosures(corp_code)`.
  - 윈도우: 공시는 이벤트성이라 **최근 `days` 캘린더일** 내 접수(`rcept_date`) 필링의
    `irds_cnt` **부호합** = 순취득 주식수(매수 양수).
  - 억 단위 변환: 순주식수 × 최근가 → 억. **최근가 없으면 `None`(정직)** — 단위 혼용 금지.
  - **`mock_allowed()` 게이트**: 운영선 실데이터/`None`, mock 모드선 결정론적 합성(`DeterministicMockStore` 또는 기존 `_mock_supply("insider")` 재사용).
- 집계·게이트·캐시를 이 모듈이 소유 → 단위 테스트 용이.

### 3.3 `market_data` 재배선 (개인/기관/외국인 → investor_flows)
- 신규 `_real_supply(stock_code) -> dict`:
  - `kis_flows.load_flows_series(ticker, field)`로 외국인/기관/개인 순매수 **금액**(`*_amt`)을
    **마지막 N개 거래일 행**(5일/20일) 합산(시계열 일별 데이터이므로 행 기준).
  - 내부자는 `insider_flows.insider_net(stock_code, 20)`.
  - 데이터 없음(미적재/실패) → 해당 필드 `None`.
- `_compute_all_indicators`: `allow=mock_allowed()`면 기존 `_mock_supply`(회귀 불변),
  아니면 `_real_supply`(실데이터/None). 직전 게이트 구조와 동일 패턴.

## 4. 데이터 흐름 + 단위 정합 수정 (완성도)

`investor_flows`는 qty와 amt를 모두 저장한다. 순매수 필드는 "억" 라벨이지만
`price_factors_store._supply_factors`는 현재 **qty**(`frgn_qty`)를 합산하는 **잠재적 단위 불일치**가 있다.

- 순매수를 **금액(`*_amt` → 억)** 으로 통일하고, **`price_factors_store`의 같은 불일치도 수정**해
  두 스토어가 하나의 정의를 공유한다.
- behavioral 패밀리 매핑:
  - `foreign_net_5d` ← `frgn_amt` 최근 5일 합(억)
  - `institution_net_5d` ← `orgn_amt` 5일 합(억)
  - `retail_net_5d` ← `prsn_amt` 5일 합(억)
  - `insider_net_20d` ← DART `insider_net(20)`(억)
- behavioral 시그널은 **부호**만 보므로(>0 / <0) 단위 변경이 시그널 의미를 바꾸지 않음(정합 강화).

## 5. 완성도 확장

- `price_factors_store`에 **`insider_net_20d`·`retail_net_20d`** 를 정식 수치 **필드**로 추가
  (외국인/기관 옆) → 스크리너 컬럼·필터로 노출. 수급 팩터군이 스크리너+behavioral에서 일관.
- behavioral 시그널 4종이 운영서 실데이터 경로로 평가.

## 6. mock 정책 & 에러 처리

직전 게이트 원칙과 동일:
- 운영(`KIS_USE_MOCK=0`): 실데이터 또는 정직 `None`("—"). **합성 금지**.
- mock(`=1`): 합성(회귀 불변).
- DART 실패 / corp_code 없음 / 빈 공시 / `investor_flows` 미적재 → 운영선 `None`,
  debug 로깅, 지표 계산 크래시 금지.

## 7. 테스트 (키 불필요 — 픽스처 + mock DB)

- `tests/test_insider_parsing.py`(신규, `test_realdata_parsing.py` 패턴):
  - `elestock` 픽스처 JSON → 순증감 계산, 증가/감소/혼합, 결측 필드, 빈/에러 → `None`.
  - mock 게이트 양방향(운영 무합성 / mock 합성).
  - 금액 파싱 엣지(쉼표/음수/공백/가비지).
- `tests/test_realdata_only.py` 확장:
  - 재배선 수급 — `investor_flows` 있으면 실값 / 비면 `None`(운영) / mock 모드 합성.
- behavioral 시그널 E2E: stub된 flows/insider로 `insider_buy_retail_sell` 등이 실경로 평가.
- 전체 백엔드 스위트 green 유지, ruff clean.

## 8. 정직한 검증 한계

샌드박스는 DART/KIS 키·네트워크가 없어 **실 fetch 미수행** — 파싱·배선·게이트만 픽스처/mock DB로
검증. 실 종단(실데이터로 채워짐)은 사용자 GCP 실키 환경에서. 운영 적재 후 behavioral 시그널이
실수급으로 작동.

## 9. 파일별 변경 요약

- `src/data/dart_client.py` — `get_insider_disclosures(corp_code)` + `elestock` 파싱/캐시.
- `src/data/insider_flows.py` (신규) — `insider_net()` 집계 + 게이트 + 캐시.
- `src/data/market_data.py` — `_real_supply()` + `_compute_all_indicators` 분기, insider 폴백 사용.
- `src/data/price_factors_store.py` — qty→amt 정합 수정 + `insider_net_20d`/`retail_net_20d` 필드 추가.
- `tests/test_insider_parsing.py` (신규), `tests/test_realdata_only.py` (확장).
