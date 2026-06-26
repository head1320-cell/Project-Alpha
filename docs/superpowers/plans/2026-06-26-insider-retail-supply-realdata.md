# 내부자/개인 수급 팩터 실데이터 연결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** behavioral 수급 패밀리(개인/기관/외국인)를 기존 `investor_flows`에 재배선하고 내부자(insider)를 DART `elestock` 온디맨드로 신규 연결해, 운영에서 실데이터로 평가(없으면 정직 "—").

**Architecture:** 책임 분리 3단위 — `dart_client.get_insider_disclosures`(저수준 fetch+parse) → `insider_flows.insider_net`(집계+게이트+캐시) → `market_data._real_supply`(재배선). 단위 정합(qty→금액 amt)을 양 스토어에 적용하고 `insider_net_20d`/`retail_net_*`를 정식 필드화.

**Tech Stack:** Python 3.11, pytest, SQLAlchemy(investor_flows), 기존 DART 디스크 캐시, `mock_gate.mock_allowed()`.

스펙: `docs/superpowers/specs/2026-06-26-insider-retail-supply-realdata-design.md`

---

## File Structure

- `src/data/dart_client.py` (수정) — `_parse_insider_rows()`(순수 파서) + `get_insider_disclosures(corp_code)`(fetch). `elestock.json` 사용.
- `src/data/insider_flows.py` (신규) — `insider_net(stock_code, days, price, as_of)` 집계 + `mock_allowed()` 게이트.
- `src/data/market_data.py` (수정) — `_real_supply(stock_code, price)` + `_compute_all_indicators` 분기.
- `src/data/price_factors_store.py` (수정) — `_supply_factors` qty→amt + 신규 필드(retail/insider) + 메타 + mock 값.
- `tests/test_insider_parsing.py` (신규), `tests/test_realdata_only.py` (확장).

---

## Task 1: DART insider 공시 파서 (순수 함수)

**Files:**
- Modify: `src/data/dart_client.py` (DARTClient에 staticmethod 추가, `_parse_amount` 부근)
- Test: `tests/test_insider_parsing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_insider_parsing.py
"""DART elestock(임원·주요주주 소유보고) 파싱 + insider_net 집계 — 키 없이 픽스처로 검증."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.dart_client import DARTClient  # noqa: E402

# 실제 elestock.json 응답 구조 축약 픽스처
_ELESTOCK_OK = {
    "status": "000", "message": "정상",
    "list": [
        {"rcept_no": "20260610000123", "repror": "홍길동",
         "sp_stock_lmp_cnt": "100,000", "sp_stock_lmp_irds_cnt": "10,000"},
        {"rcept_no": "20260605000045", "repror": "김임원",
         "sp_stock_lmp_cnt": "5,000", "sp_stock_lmp_irds_cnt": "-2,000"},
        {"rcept_no": "20260102000077", "repror": "옛날보고",
         "sp_stock_lmp_cnt": "1,000", "sp_stock_lmp_irds_cnt": "500"},
        {"rcept_no": "20260608000099", "repror": "변동없음",
         "sp_stock_lmp_cnt": "3,000", "sp_stock_lmp_irds_cnt": "-"},
    ],
}


def test_parse_insider_rows_signed():
    rows = DARTClient._parse_insider_rows(_ELESTOCK_OK)
    # 4행 모두 파싱, 날짜 8자리 + 증감 부호 정수("-"는 0)
    by_date = {r["rcept_date"]: r["irds_cnt"] for r in rows}
    assert by_date["20260610"] == 10000
    assert by_date["20260605"] == -2000
    assert by_date["20260102"] == 500
    assert by_date["20260608"] == 0   # "-" → 0


def test_parse_insider_rows_empty_or_bad():
    assert DARTClient._parse_insider_rows({"status": "013", "message": "no data"}) == []
    assert DARTClient._parse_insider_rows({}) == []
    assert DARTClient._parse_insider_rows({"list": []}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_insider_parsing.py -q`
Expected: FAIL — `AttributeError: type object 'DARTClient' has no attribute '_parse_insider_rows'`

- [ ] **Step 3: Write minimal implementation**

`src/data/dart_client.py` — `_parse_amount` staticmethod 바로 아래에 추가:

```python
    @staticmethod
    def _parse_insider_rows(data: dict | None) -> list[dict]:
        """elestock 응답 → [{"rcept_date":"YYYYMMDD","irds_cnt":int(±),"repror":str}].
        '-'/빈값/가비지 증감은 0. status!=000 또는 list 없음 → []."""
        if not data or data.get("status") != "000":
            return []
        rows = []
        for it in data.get("list", []) or []:
            rcept = str(it.get("rcept_no", ""))[:8]
            if len(rcept) != 8 or not rcept.isdigit():
                continue
            irds = DARTClient._parse_amount(it.get("sp_stock_lmp_irds_cnt"))
            rows.append({"rcept_date": rcept,
                         "irds_cnt": int(irds) if irds is not None else 0,
                         "repror": it.get("repror", "")})
        return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_insider_parsing.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_insider_parsing.py src/data/dart_client.py
git commit -m "feat(dart): elestock 내부자 공시 파서(_parse_insider_rows)"
```

---

## Task 2: DART insider fetch 메서드 (`get_insider_disclosures`)

**Files:**
- Modify: `src/data/dart_client.py`
- Test: `tests/test_insider_parsing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_insider_parsing.py 에 추가
def test_get_insider_disclosures_uses_get(monkeypatch):
    c = DARTClient(api_key="x" * 20)
    monkeypatch.setattr(c, "_get", lambda endpoint, params: _ELESTOCK_OK
                        if endpoint == "elestock.json" else None)
    rows = c.get_insider_disclosures("00126380")
    assert len(rows) == 4
    assert rows[0]["rcept_date"] == "20260610"


def test_get_insider_disclosures_no_data(monkeypatch):
    c = DARTClient(api_key="x" * 20)
    monkeypatch.setattr(c, "_get", lambda endpoint, params: None)
    assert c.get_insider_disclosures("00126380") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_insider_parsing.py -q`
Expected: FAIL — `AttributeError: 'DARTClient' object has no attribute 'get_insider_disclosures'`

- [ ] **Step 3: Write minimal implementation**

`src/data/dart_client.py` — `get_corp_info` 부근(공개 메서드 영역)에 추가:

```python
    def get_insider_disclosures(self, corp_code: str) -> list[dict]:
        """임원·주요주주 특정증권등 소유상황보고(elestock) → 파싱 행 리스트.
        성공 응답은 _get가 디스크 캐시. 미설정/실패/빈 → []."""
        data = self._get("elestock.json", {"corp_code": corp_code})
        return self._parse_insider_rows(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_insider_parsing.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_insider_parsing.py src/data/dart_client.py
git commit -m "feat(dart): get_insider_disclosures — elestock fetch+parse"
```

---

## Task 3: `insider_flows.insider_net` — 윈도우 집계 + 실데이터 게이트

**Files:**
- Create: `src/data/insider_flows.py`
- Test: `tests/test_insider_parsing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_insider_parsing.py 에 추가
def test_insider_net_window_and_price(monkeypatch):
    import src.data.insider_flows as inf
    monkeypatch.setenv("KIS_USE_MOCK", "0")  # 운영 — 실데이터 경로
    monkeypatch.setattr(inf, "get_corp_code", lambda code: "00126380")
    monkeypatch.setattr(inf, "_disclosures", lambda corp: [
        {"rcept_date": "20260610", "irds_cnt": 10000},
        {"rcept_date": "20260605", "irds_cnt": -2000},
        {"rcept_date": "20260102", "irds_cnt": 500},   # 윈도우 밖
    ])
    # as_of=2026-06-12, days=20 → 6/10·6/5 포함(8000주), 1/2 제외. price=50,000원
    net = inf.insider_net("005930", days=20, price=50000.0, as_of="20260612")
    assert net == round(8000 * 50000 / 1e8, 1)   # 4.0 억


def test_insider_net_real_mode_no_price_or_data(monkeypatch):
    import src.data.insider_flows as inf
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(inf, "get_corp_code", lambda code: "00126380")
    monkeypatch.setattr(inf, "_disclosures", lambda corp: [{"rcept_date": "20260610", "irds_cnt": 10000}])
    assert inf.insider_net("005930", days=20, price=None, as_of="20260612") is None   # 가격없음→None
    monkeypatch.setattr(inf, "_disclosures", lambda corp: [])
    assert inf.insider_net("005930", days=20, price=50000.0, as_of="20260612") is None  # 데이터없음→None


def test_insider_net_mock_mode_synthetic(monkeypatch):
    import src.data.insider_flows as inf
    monkeypatch.setenv("KIS_USE_MOCK", "1")  # mock — 합성(가격·공시 무관)
    v = inf.insider_net("005930", days=20, price=None, as_of="20260612")
    assert isinstance(v, float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_insider_parsing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.insider_flows'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/insider_flows.py
"""내부자(임원·주요주주) 순매수 — DART elestock 온디맨드 집계.
KIS에 없는 유일한 수급 주체. 운영선 실데이터/None(합성 금지), mock 모드선 결정론적 합성.
가격 필요(순주식수 × 최근가 → 억). 가격/공시 없으면 None."""
from __future__ import annotations

import logging

from src.data.dart_client import get_corp_code, get_dart_client

logger = logging.getLogger(__name__)


def _disclosures(corp_code: str) -> list[dict]:
    """공유 DARTClient로 내부자 공시 조회 (테스트에서 monkeypatch 지점)."""
    return get_dart_client().get_insider_disclosures(corp_code)


def _cutoff(as_of: str | None, days: int) -> str:
    """YYYYMMDD 컷오프 = as_of - days (캘린더). as_of None이면 오늘."""
    from datetime import datetime, timedelta
    base = datetime.strptime(as_of, "%Y%m%d") if as_of else datetime.now()
    return (base - timedelta(days=days)).strftime("%Y%m%d")


def insider_net(stock_code: str, days: int = 20, price: float | None = None,
                as_of: str | None = None) -> float | None:
    """내부자 순취득(억, 매수 양수). 운영: 실 공시 윈도우 합 × 가격. mock: 합성."""
    from src.data.mock_gate import mock_allowed
    if not mock_allowed():
        if price is None or price <= 0:
            return None
        corp = get_corp_code(stock_code)
        if not corp:
            return None
        cutoff = _cutoff(as_of, days)
        rows = [r for r in _disclosures(corp) if r.get("rcept_date", "") >= cutoff]
        if not rows:
            return None
        net_shares = sum(int(r.get("irds_cnt", 0)) for r in rows)
        return round(net_shares * price / 1e8, 1)
    # mock 모드 — 결정론적 합성 (기존 _mock_supply 재사용, 종목 일관)
    from src.data.market_data import _mock_supply
    return round(_mock_supply(stock_code, "insider_net") * 0.3, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_insider_parsing.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_insider_parsing.py src/data/insider_flows.py
git commit -m "feat(data): insider_flows.insider_net — DART 내부자 순매수 집계 + 실데이터 게이트"
```

---

## Task 4: `market_data` 수급 재배선 (금액 amt) + 내부자 연결

**Files:**
- Modify: `src/data/market_data.py:265-276` (`_compute_all_indicators` 수급 dict) + 신규 `_real_supply`
- Test: `tests/test_realdata_only.py` (확장)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_realdata_only.py 에 추가 (파일 끝)
# ── 수급 재배선 (investor_flows 금액 + DART 내부자) ──
def test_market_supply_real_mode_from_flows(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import pandas as pd
    import src.data.market_data as md
    # investor_flows 금액 시리즈 stub (last-5 합)
    def fake_series(ticker, field, engine=None):
        base = {"frgn_amt": [10, 20, 30, 40, 50], "orgn_amt": [1, 2, 3, 4, 5],
                "prsn_amt": [-5, -5, -5, -5, -5]}.get(field)
        return pd.Series(base) if base else None
    monkeypatch.setattr("src.data.kis_flows.load_flows_series", fake_series)
    # 실 OHLCV 존재 → close 확보 → 내부자 가격주입 경로 작동
    df = pd.DataFrame({"open": [50000] * 150, "high": [51000] * 150, "low": [49000] * 150,
                       "close": [50000] * 150, "volume": [1000] * 150})
    monkeypatch.setattr(md, "_real_kis_ohlcv", lambda code, days=150: df)
    monkeypatch.setattr("src.data.insider_flows.insider_net",
                        lambda code, days=20, price=None, as_of=None: 7.0)
    data = md.MarketDataProvider.get_default()._compute_all_indicators("005930")
    assert data["foreign_net_5d"] == 150       # 10+20+30+40+50 (금액)
    assert data["institution_net_5d"] == 15
    assert data["retail_net_5d"] == -25
    assert data["insider_net_20d"] == 7.0      # close 주입 후 set
    assert data["_source"] == "kis_real"


def test_market_supply_real_mode_empty_flows(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.data.market_data as md
    monkeypatch.setattr("src.data.kis_flows.load_flows_series", lambda *a, **k: None)
    monkeypatch.setattr(md, "_real_kis_ohlcv", lambda code, days=150: None)  # OHLCV 없음
    data = md.MarketDataProvider.get_default()._compute_all_indicators("005930")
    assert data["foreign_net_5d"] is None       # 미적재 → 정직 None
    assert data["insider_net_20d"] is None      # 가격 없음(OHLCV None) → 주입 안 됨
    assert data["_source"] == "unavailable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_realdata_only.py -q -k supply`
Expected: FAIL — `assert None == 150` (현재 운영선 전부 None, 재배선 전)

- [ ] **Step 3: Write minimal implementation**

(a) `src/data/market_data.py` — `_compute_all_indicators`의 수급 dict(현 270-276)를 교체:

```python
        # 수급: mock 모드선 합성, 운영선 investor_flows(금액). 내부자는 close 확보 후 주입.
        if allow:
            data = {
                "foreign_net_5d":     _mock_supply(stock_code, "foreign_net"),
                "institution_net_5d": _mock_supply(stock_code, "institution_net"),
                "insider_net_20d":    _mock_supply(stock_code, "insider_net") * 0.3,
                "retail_net_5d":      _mock_supply(stock_code, "retail_net"),
                "_source": "mock_kis_indicators",
            }
        else:
            data = self._real_supply(stock_code)
            data["_source"] = "unavailable"
```

(b) 같은 함수에서 `close = df["close"].iloc[-1]`(현 289) **바로 다음 줄**에 내부자 가격주입 추가:

```python
            close = df["close"].iloc[-1]
            if not allow:   # 운영 — close 확보됨 → DART 내부자 순매수(억) 주입
                from src.data.insider_flows import insider_net
                data["insider_net_20d"] = insider_net(stock_code, days=20, price=float(close))
```

(c) `_compute_all_indicators` 메서드 아래(같은 클래스)에 `_real_supply` 추가:

```python
    def _real_supply(self, stock_code: str) -> dict:
        """운영 수급 — investor_flows 금액(외국인/기관/개인 last-5). 미적재면 None.
        내부자는 가격 필요 → 호출부서 close 확보 후 주입(placeholder None)."""
        out = {"foreign_net_5d": None, "institution_net_5d": None,
               "insider_net_20d": None, "retail_net_5d": None}
        try:
            from src.data.kis_flows import load_flows_series

            def _sum5(field: str):
                s = load_flows_series(stock_code, field)
                if s is None or len(s) == 0:
                    return None
                tail = s.dropna().tail(5)
                return round(float(tail.sum()), 0) if len(tail) else None
            out["foreign_net_5d"] = _sum5("frgn_amt")
            out["institution_net_5d"] = _sum5("orgn_amt")
            out["retail_net_5d"] = _sum5("prsn_amt")
        except Exception as e:
            logger.debug(f"실 수급 조회 실패 ({stock_code}): {e}")
        return out
```

참고: 외국인/기관/개인은 금액(amt)이라 가격 불필요. 내부자만 순주식수×close → 억이므로 close
확보(실 OHLCV 존재) 시에만 주입 — OHLCV 없으면(실데이터 부재) insider도 정직 None. close 직후에
set하므로 이후 지표 계산이 실패(except)해도 내부자 값은 유지됨.

- [ ] **Step 4: Run test to verify it passes**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_realdata_only.py -q -k supply`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_realdata_only.py src/data/market_data.py
git commit -m "feat(data): market_data 수급 재배선 — investor_flows 금액 + DART 내부자(운영)"
```

---

## Task 5: `price_factors_store` 단위 정합(qty→amt) + 내부자/개인 필드화

**Files:**
- Modify: `src/data/price_factors_store.py` (메타 76-79, `_supply_factors` 239-258, `_mock_factors` 389-392)
- Test: `tests/test_realdata_only.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_realdata_only.py 에 추가
def test_price_supply_uses_amt_and_new_fields(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import pandas as pd
    from src.data.price_factors_store import PRICE_FACTOR_BY_ID, PriceFactorsStore
    # 신규 필드 메타 등록 확인
    assert "retail_net_5d" in PRICE_FACTOR_BY_ID
    assert "retail_net_20d" in PRICE_FACTOR_BY_ID
    assert "insider_net_20d" in PRICE_FACTOR_BY_ID
    seen = {}
    def fake_series(ticker, field, engine=None):
        seen[field] = True
        return pd.Series([1, 2, 3, 4, 5]) if field.endswith("_amt") else None
    monkeypatch.setattr("src.data.kis_flows.load_flows_series", fake_series)
    s = PriceFactorsStore.get_default()
    out = s._supply_factors("005930")
    assert out["foreign_net_5d"] == 15        # amt 합 (qty 아님)
    assert out["retail_net_5d"] == 15
    assert "frgn_amt" in seen and "prsn_amt" in seen   # 금액 컬럼 사용
    assert "frgn_qty" not in seen                       # qty 미사용
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_realdata_only.py -q -k price_supply`
Expected: FAIL — `KeyError: 'retail_net_5d'` (메타 미등록) 또는 `'frgn_qty' in seen`

- [ ] **Step 3: Write minimal implementation**

(a) 메타 — `src/data/price_factors_store.py:79` `inst_net_20d` 줄 다음에 추가:

```python
    PriceFactorMeta("retail_net_5d", "개인 5일 순매수", "supply", "억", False, -500, 500, "KIS 투자자동향", "최근 5일 개인 순매수 금액(역추세 참고)"),
    PriceFactorMeta("retail_net_20d", "개인 20일 순매수", "supply", "억", False, -2000, 2000, "KIS 투자자동향", "최근 20일 개인 순매수"),
    PriceFactorMeta("insider_net_20d", "내부자 20일 순매수", "supply", "억", True, -300, 300, "DART 지분공시", "최근 20일 임원·주요주주 순취득(억)"),
```

(b) `_supply_factors` (239-258) 전체 교체 — qty→amt + retail + insider:

```python
    def _supply_factors(self, stock_code: str, price: float | None = None) -> dict:
        """investor_flows 금액(외국인/기관/개인 N일 합) + DART 내부자(20d). 미적재면 None."""
        out = {"foreign_net_5d": None, "foreign_net_20d": None,
               "inst_net_5d": None, "inst_net_20d": None,
               "retail_net_5d": None, "retail_net_20d": None, "insider_net_20d": None}
        try:
            from src.data.kis_flows import load_flows_series

            def _sum_last(field: str, days: int):
                s = load_flows_series(stock_code, field)
                if s is None or len(s) == 0:
                    return None
                tail = s.dropna().tail(days)
                return round(float(tail.sum()), 0) if len(tail) else None
            out["foreign_net_5d"] = _sum_last("frgn_amt", 5)
            out["foreign_net_20d"] = _sum_last("frgn_amt", 20)
            out["inst_net_5d"] = _sum_last("orgn_amt", 5)
            out["inst_net_20d"] = _sum_last("orgn_amt", 20)
            out["retail_net_5d"] = _sum_last("prsn_amt", 5)
            out["retail_net_20d"] = _sum_last("prsn_amt", 20)
        except Exception:
            pass
        try:
            from src.data.insider_flows import insider_net
            out["insider_net_20d"] = insider_net(stock_code, days=20, price=price)
        except Exception:
            pass
        return out
```

참고: `_derive_from_ohlcv`의 호출부(현 234 `**self._supply_factors(stock_code)`)는 그대로 두되,
가격을 넘기도록 `**self._supply_factors(stock_code, cur)`로 수정(같은 스코프에 `cur` 존재).

(c) `_mock_factors` (389-392) 수급 줄을 retail/insider 포함으로 확장:

```python
            "foreign_net_5d": round(nm(stock_code, "f5", mu=0, sigma=120), 1),
            "foreign_net_20d": round(nm(stock_code, "f20", mu=0, sigma=400), 1),
            "inst_net_5d": round(nm(stock_code, "i5", mu=0, sigma=100), 1),
            "inst_net_20d": round(nm(stock_code, "i20", mu=0, sigma=350), 1),
            "retail_net_5d": round(nm(stock_code, "r5", mu=0, sigma=110), 1),
            "retail_net_20d": round(nm(stock_code, "r20", mu=0, sigma=380), 1),
            "insider_net_20d": round(nm(stock_code, "ins20", mu=0, sigma=40), 1),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_realdata_only.py -q -k price_supply`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_realdata_only.py src/data/price_factors_store.py
git commit -m "feat(data): 수급 단위 정합(qty→amt) + 개인·내부자 필드화 (price_factors)"
```

---

## Task 6: behavioral 시그널 E2E (실경로) + 전체 검증

**Files:**
- Test: `tests/test_realdata_only.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_realdata_only.py 에 추가
def test_behavioral_signal_real_path(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    from src.data.market_data import eval_behavioral_signal
    # 내부자 매수 + 개인 매도 → insider_buy_retail_sell 참
    ind = {"insider_net_20d": 5.0, "retail_net_5d": -10.0,
           "foreign_net_5d": 0, "institution_net_5d": 0}
    assert eval_behavioral_signal(ind, "insider_buy_retail_sell") is True
    # 데이터 없음(None) → 시그널 거짓 (정직, 합성 안 함)
    empty = {"insider_net_20d": None, "retail_net_5d": None,
             "foreign_net_5d": None, "institution_net_5d": None}
    assert eval_behavioral_signal(empty, "insider_buy_retail_sell") is False
```

- [ ] **Step 2: Run test to verify it fails (or passes trivially — confirm)**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_realdata_only.py -q -k behavioral_signal_real`
Expected: PASS (eval_behavioral_signal은 기존 함수 — 이 테스트는 실경로 계약을 고정/회귀 방지). 만약 `None or 0` 처리 누락으로 FAIL 시 Step3.

- [ ] **Step 3: (필요 시) None 안전 확인**

`eval_behavioral_signal`은 이미 `indicators.get(...) or 0`로 None→0 처리(현 393-396). 변경 불필요.

- [ ] **Step 4: 전체 스위트 + ruff**

Run:
```bash
python -m ruff check src/data/dart_client.py src/data/insider_flows.py src/data/market_data.py src/data/price_factors_store.py tests/test_insider_parsing.py tests/test_realdata_only.py
KIS_USE_MOCK=1 python -m pytest tests/ -q
```
Expected: ruff `All checks passed!` · 전체 `~615 passed, 10 skipped` (604 + 내부자 7 + 수급/behavioral 4). 0 failed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_realdata_only.py
git commit -m "test(data): behavioral 시그널 실경로 E2E + 수급 실데이터 검증"
```

---

## Task 7: 푸시

- [ ] **Step 1: 브랜치 푸시**

```bash
git push -u origin claude/keen-thompson-bdk3e8
```
Expected: 정상 푸시(네트워크 실패 시 2/4/8/16초 백오프 재시도).

---

## 검증 요약 (정직한 한계)
- 키 없는 샌드박스: DART/KIS 실 fetch 미수행. 파서·집계·게이트·재배선은 픽스처/stub로 검증.
- 실 종단(실데이터 채움)은 GCP 실키 + `investor_flows` 적재 + DART 키 후. 그 전엔 운영서 정직 "—".
- 단위 정합(qty→amt): 회귀 영향 — mock 값은 sigma만 동일 스케일 유지, 운영 의미는 "금액(억)"으로 정정.
