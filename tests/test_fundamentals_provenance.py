"""실데이터 경로의 ★가정값에 라벨을 붙인다★ — 값은 그대로 (⑥)

## 무엇이 문제였나

`FundamentalsStore._real_raw_financials` 는 **실데이터 경로**다(mock 게이트 뒤가
아니다). 그런데 DART 값이 없으면 가정값을 만들어 낸다 — 실측 12곳:

```python
        gross_profit = ... else (revenue * 0.3 if revenue else None)
        mcap = total_equity * 1.2            # "PBR≈1.2 가정으로 근사"
        revenue_prev = ... else (revenue * 0.95)
        op_prev      = ... else (operating_profit * 0.93)
        ni_prev      = ... else (net_income * 0.94)
        shares = 10000                       # "최후 근사"
```

조건식이 그 위에서 **'매출액증가율'** 을 스크리닝한다 — `revenue_prev = revenue *
0.95` 면 어떤 종목이든 정확히 **+5.26% 성장**으로 나온다. 스크리닝 결과가
데이터가 아니라 상수에서 나온다.

CLAUDE.md §6 은 *"운영에서는 합성값을 만들지 않습니다 — 실패하면 None + 사유"* 다.

## 이 슬라이스가 하는 것 / 하지 않는 것

**하지 않는다** — 값을 바꾸지 않는다. `None` 으로 돌리면 조건식이 평가 불가로
건너뛰어 **백테스트 결과가 바뀐다**(정책 변경 = 별도 승인). 사용자가 "라벨 부착,
동작 불변" 을 택했다.

**한다** — 어떤 필드가 가정값인지 `_assumed` 로 표시한다. 그래야 "이 백테스트의
성장률은 실측인가 상수인가" 를 물을 수 있다.

★같은 파일이 이미 옳게 하는 곳이 있다★ — `dividend` 는 미상일 때 0 이 아니라
`None` 이고 그 이유가 주석에 적혀 있다. 그 어휘를 따른다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.fundamentals_store import assumed_fields  # noqa: E402


def test_a_field_backed_by_dart_is_not_marked_assumed():
    """실측값이 있으면 가정이 아니다."""
    got = assumed_fields({"revenue": 1000.0, "revenue_prev": 950.0},
                         assumed=set())
    assert got == [], got


def test_a_derived_previous_year_is_marked():
    """★핵심★ `revenue_prev = revenue * 0.95` 는 관측이 아니라 가정이다."""
    got = assumed_fields({"revenue": 1000.0, "revenue_prev": 950.0},
                         assumed={"revenue_prev"})
    assert got == ["revenue_prev"], got


def test_the_label_is_a_sorted_stable_list():
    """골든·비교에 쓰이므로 순서가 안정적이어야 한다."""
    a = assumed_fields({}, assumed={"shares", "mcap", "revenue_prev"})
    b = assumed_fields({}, assumed={"revenue_prev", "mcap", "shares"})
    assert a == b == ["mcap", "revenue_prev", "shares"]


def test_an_empty_assumption_set_is_not_the_same_as_unknown():
    """★미상 ≠ 가정 없음★ 계산해 보지 않았으면 빈 리스트가 아니라 None 이다.

    빈 리스트를 내면 "확인했더니 가정값이 하나도 없다" 는 **하지 않은 진술**이 된다.
    """
    assert assumed_fields({}, assumed=None) is None


def test_the_real_path_reports_which_fields_it_invented(monkeypatch):
    """★계약: 실데이터 경로가 만든 가정값이 응답에 표시된다★

    DART 전년도 값이 없는 상황을 만들고, `revenue_prev` 가 가정으로 표시되는지 본다.
    """
    from src.data.fundamentals_store import FundamentalsStore
    st = FundamentalsStore.__new__(FundamentalsStore)

    class _FS:
        """DART 재무제표 스텁 — 명시하지 않은 필드는 **미상(None)** 이다.
        (필드를 하나씩 세는 대신 `__getattr__` 로 흡수한다 — 이 테스트가 검증하는
         것은 '가정값에 라벨이 붙는가' 이지 필드 목록이 아니다.)"""
        revenue = 1000e8; operating_profit = 100e8; net_income = 80e8
        total_assets = 2000e8; total_equity = 800e8; total_liabilities = 1200e8
        is_mock = False

        def __getattr__(self, name):
            return None

    monkeypatch.setattr(st, "_get_fs", lambda *a, **k: _FS(),
                        raising=False)
    monkeypatch.setattr(st, "_market_snapshot",
                        lambda code: {"mcap_억": None, "price": None}, raising=False)
    out = st._real_raw_financials("005930")
    assert out is not None, "실경로가 값을 못 만들었다 — 이 테스트가 공허해진다"
    # ★`None` 을 허용하면 "라벨을 아예 안 붙인다" 는 변이가 살아남는다 (변이 D27)★
    # 처음에 `is None or isinstance(..., list)` 로 걸었다가 실제로 그 변이를 놓쳤다.
    assert isinstance(out["_assumed"], list), f"라벨이 리스트가 아니다: {out['_assumed']!r}"
    for f in ("gross_profit", "mcap", "shares"):
        assert f in out["_assumed"], (
            f"{f} 는 DART 값이 없어 가정으로 만들어졌는데 표시되지 않았다: {out['_assumed']}")


def test_a_missing_previous_year_is_marked_and_yields_a_constant_growth_rate(monkeypatch):
    """★상수에서 나온 성장률을 드러낸다★

    전년도 재무가 없으면 `revenue_prev = revenue * 0.95` 가 쓰이고, 그러면
    매출액증가율이 **어떤 종목이든 정확히 +5.26%** 가 된다. 조건식이 그 위에서
    스크리닝하면 데이터가 아니라 상수를 거르는 것이다 — 최소한 표시는 돼야 한다.
    """
    from src.data.fundamentals_store import FundamentalsStore
    st = FundamentalsStore.__new__(FundamentalsStore)

    class _FS:
        revenue = 1000e8; operating_profit = 100e8; net_income = 80e8
        total_assets = 2000e8; total_equity = 800e8; total_liabilities = 1200e8
        is_mock = False

        def __getattr__(self, name):
            return None

    seen = {"n": 0}

    def only_current(*a, **k):
        seen["n"] += 1
        return _FS() if seen["n"] == 1 else None      # 전년도·3년 전 없음

    monkeypatch.setattr(st, "_get_fs", only_current, raising=False)
    monkeypatch.setattr(st, "_market_snapshot",
                        lambda code: {"mcap_억": None, "price": None}, raising=False)
    out = st._real_raw_financials("005930")
    assert out is not None
    for f in ("revenue_prev", "op_prev", "ni_prev"):
        assert f in out["_assumed"], f"{f} 가 가정인데 표시되지 않았다: {out['_assumed']}"
    growth = (out["revenue"] / out["revenue_prev"] - 1) * 100
    assert growth == pytest.approx(5.26, abs=0.01), (
        f"이 값은 데이터가 아니라 상수 0.95 에서 나온다: {growth:.2f}%")
