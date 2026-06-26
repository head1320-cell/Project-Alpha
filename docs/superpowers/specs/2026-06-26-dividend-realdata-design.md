# 배당 팩터 실데이터 연결 (DART alotMatter) — 설계 스펙

- 날짜: 2026-06-26
- 브랜치: `claude/keen-thompson-bdk3e8`
- 상태: 승인됨(배치 ①) — 구현

## 문제 (두 경로)

1. **dart_client 경로** — `FinancialStatement.dps`가 영원히 None. `get_financial_statement_full`이
   배당공시(`alotMatter`)를 호출 안 해서 `compute_ratios`의 `dividend_yield`/`payout_ratio`가 "—"(백테스터 DslStrategy 사용).
2. **fundamentals_store 경로** — `_real_raw_financials`가 `dividend = net_income * 0.25`로 **날조 근사**.
   DART 키가 있어도 실 배당이 아니라 순이익의 25% → 실데이터 전용 원칙 위반 + 부정확.

## 설계

### `dart_client.get_dividend_info(corp_code, year) -> dict` (신규)
- `alotMatter.json`(배당에 관한 사항) 호출 → 행에서 `se`(구분)·`stock_knd`(주식종류)·`thstrm`(당기) 파싱.
- 반환 `{"dps": float|None, "payout_pct": float|None, "yield_pct": float|None}`:
  - `se`에 "주당 현금배당금" + 보통주 → `dps`
  - `se`에 "현금배당성향" → `payout_pct`
  - `se`에 "현금배당수익률" → `yield_pct`
- 순수 파서 `_parse_dividend_rows(data)` + fetch 분리(키 없이 픽스처 테스트). `_get` 디스크 캐시 재사용.
- 미설정/실패/빈 → 전부 None.

### 배선
- `get_financial_statement_full`: `fs.compute_ratios()`(현 412) **직전**에
  `div = self.get_dividend_info(corp_code, bsns_year); if div["dps"] is not None: fs.dps = div["dps"]`.
  → `compute_ratios`가 실 dps로 `payout_ratio`(dps/eps) 산출, 가격 주입 시 `dividend_yield`(dps/price)도.
- `fundamentals_store._real_raw_financials`: `dividend = net_income * 0.25`(현 262) 교체:
  - `div = get_dividend_info(corp, year)`; `payout_pct` 있으면 `dividend = payout_pct/100 × net_income`.
  - 없으면(공시에 배당 항목 없음 = 무배당) `dividend = 0.0` — **날조 0.25 제거**(0은 "공시상 무배당", 정직).
  - 연도/ corp_code는 이미 이 메서드 컨텍스트에 있음(아래 구현서 확인).

## mock 정책
- 운영(`KIS_USE_MOCK=0`): 실 alotMatter 또는 0(무배당)/None. 0.25 날조 제거.
- mock 모드: 기존 `_mock_raw_financials` 합성 dividend 유지(회귀 불변). `_mock_financial_statement`의 dps도 유지.

## 테스트 (키 없이 픽스처)
- `tests/test_dividend_parsing.py`(신규): alotMatter 픽스처 → dps/payout/yield 파싱, 쉼표/"-"/결측, 빈/에러 → None.
- `get_dividend_info`가 `_get` monkeypatch로 파싱 호출 확인.
- fundamentals: alotMatter stub로 `_real_raw_financials`의 dividend가 0.25×NI 아님(payout 기반) 확인.

## 한계
- 샌드박스 키 없음 → 실 fetch 미수행. 파서·배선은 픽스처/stub. 실데이터는 GCP DART 키.

## 파일
- `src/data/dart_client.py` — `_parse_dividend_rows` + `get_dividend_info` + `get_financial_statement_full` 배선.
- `src/data/fundamentals_store.py` — `_real_raw_financials` dividend 실데이터화.
- `tests/test_dividend_parsing.py`(신규).
