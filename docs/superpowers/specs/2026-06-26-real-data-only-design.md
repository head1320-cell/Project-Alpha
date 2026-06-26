# 실데이터 전용 (운영서 합성 mock 금지) + 시가총액 "—" 해결

> 운영(실키)에서 사용자에게 **합성(mock) 숫자를 절대 보여주지 않는다.** 실 호출 실패/빈값이면
> 정직한 `null`("—"). 또한 일부 기업이 시가총액·지표를 "—"로 표시하는 문제를 KIS master로 해결.
> mock 생성기는 **명시적 개발/테스트(KIS_USE_MOCK=1)** 전용으로만 격리 — 586 테스트·샌드박스 무영향.

날짜: 2026-06-26 · 브랜치: `claude/keen-thompson-bdk3e8`

---

## 1. 배경 / 진단

**문제 1 — 운영서 합성 mock 노출:** 실키가 있어도(KIS_USE_MOCK=0) 실 호출이 실패/빈값이면 **조용히 합성 mock으로
대체**하는 곳이 다수. 사용자가 가짜 숫자를 봄. 확인된 지점:
- `market_data.py`: OHLCV 실패 → `_mock_ohlcv`(line 278), **수급(`_mock_supply`)은 항상 합성**(line 196·268-273).
- `fundamentals_store.py:180`: DART 실패 → `_mock_raw_financials`.
- `price_factors_store.py:114`: OHLCV 실패 → `_mock_factors`.
- `extended_factors_store.py`: 동일 패턴.
- `ohlcv_loader.py:148-164`: DB→KIS→**mock** 캐스케이드.
- `kis_client.py:819`: 키 없으면 `MockKISClient`.
- `kis_flows.py`: 예외 → mock 경로.

**문제 2 — 시가총액/지표 "—":** `screener.py:_to_item`(line 761)이 `market_cap = None`을 **항상** 둠
(주석 "발행주식수 추정 생략"). 시총은 오직 `_enrich_kis_quotes`(KIS 가격 API)가 채우는데 ① mock 모드선 스킵,
② 실모드서도 그 종목에 KIS가 값을 줄 때만. → ETF·신규·우선주 등 "—".
★그러나 **KIS master 파일이 이미 `시가총액`을 전종목 파싱**(`kis_master_parser.py:165` → `save_master_flags`
→ `load_master_flags()` `{code:{market_cap_억}}`). 이걸 읽으면 무료·전종목 해결.★

## 2. 설계

### Part A — 실데이터 전용 게이트 (합성 mock 격리)
신규 `src/data/mock_gate.py`:
```python
def mock_allowed() -> bool:
    """합성 데이터 서빙 허용? 명시적 개발/테스트(KIS_USE_MOCK=1)에서만 True.
    운영(KIS_USE_MOCK=0)에선 False → 실데이터 또는 정직한 None/빈값."""
    return os.getenv("KIS_USE_MOCK", "1") == "1"
```
각 "조용한 mock 폴백" 지점을 `mock_allowed()`로 게이트 → 운영서 실패 시 mock 대신 None/빈값:
- `market_data.py`: 실 OHLCV 실패 시 `if mock_allowed(): _mock_ohlcv else: None`(지표 None). 수급도
  `_mock_supply` 대신 실모드선 None(실 수급 미연동 시 정직 None).
- `fundamentals_store.py`: DART 실패 시 mock 대신 None(빈 스냅샷).
- `price_factors_store.py`·`extended_factors_store.py`: OHLCV 실패 시 mock 대신 None.
- `ohlcv_loader.py`: 실모드선 DB→KIS→(빈 df). mock은 mock 모드서만.
- `kis_client.py`: 실모드 + 키 없음 = 설정오류 → MockKISClient 대신 실패(mock 모드서만 Mock).
- `kis_flows.py`: 실모드선 None.
핵심 불변: **KIS_USE_MOCK=1(개발/테스트/샌드박스)에선 동작 100% 동일** → 586 테스트 무영향.

### Part B — 시가총액 "—" 해결 (KIS master)
`screener.py:_to_item`: `market_cap = load_master_flags().get(code,{}).get("market_cap_억")`로 채움.
- 전종목(~3,992) 무료, 키·per-ticker 호출 불요. `_enrich_kis_quotes`가 라이브 값으로 덮어쓸 수 있음(우선).
- 운영(GCP, master 적재)서 시총 채워짐 → "—" 소멸. 진짜 없는 소수(일부 ETF)만 정직 "—".
- 샌드박스(master 없음)선 None(개발 — 사용자 노출 아님).
- PER/PBR/ROE 등 다른 지표는 DART/fundamentals_store가 이미 채움 — 실키서 정상화(Part A로 실패 시 정직 None).

## 3. 검증 (TDD)
### 신규 `tests/test_mock_gate.py` + `tests/test_realdata_only.py`
- `mock_allowed()`: KIS_USE_MOCK="1"→True, "0"→False, 미설정→True(기본).
- 실모드 정직 None(monkeypatch KIS_USE_MOCK="0" + 실호출 실패 시뮬):
  · `market_data.get_kis_indicators` 실패 → 합성 아님(None/빈), `_source` != mock.
  · `fundamentals_store` 실패 → 빈/None(합성 financials 아님).
  · `price_factors_store` 실패 → None.
- mock 모드(KIS_USE_MOCK="1") 회귀: 각 함수 기존대로 mock 산출(586 불변).
- 시가총액: `_to_item`이 master flags에서 market_cap_억 채움(master mock 주입 시), 없으면 None.
### 게이트
- ruff · `KIS_USE_MOCK=1 pytest`(586 + 신규) · tsc 0 · next build.
- 회귀: 기존 586 전부 통과(mock 모드 동작 불변).

## 4. 정직한 한계
- 샌드박스/CI는 실키·네트워크 없음 → **실모드 동작은 시뮬레이션(monkeypatch 실패)으로만 검증**, 실 GCP에서 최종 확인.
- "실데이터 전용"의 대가: 실데이터에 빈 곳이 있으면 더 많은 "—"가 보임(합성으로 가리지 않음 — 의도된 정직성).
  시가총액 등 채울 수 있는 건 master/DART로 최대 채우고, 진짜 없는 것만 "—".
- 수급(외국인·기관 실매매)은 실 연동 전까진 실모드서 None(합성 금지). 후속으로 KIS/KRX 투자자동향 실연결.

## 5. 구현 순서 (안전 커밋)
1. Part B(시가총액 master) + 테스트. (커밋①, 저위험·고가시성)
2. Part A(mock_gate + 게이트 적용) + 테스트. (커밋②)
3. 검증·푸시. 트레일러 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` +
   `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`. 모델ID 금지.
