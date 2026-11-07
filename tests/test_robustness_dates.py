"""BS3 — 견고성 입력: 날짜 축 · 날짜로 맞춘 흐름 · 끝 맞춤과의 어긋남 관측 · 미국 대용.

거는 것:
- 흐름은 ★날짜 교집합★으로 줄을 세운다 — 한 종목에 없는 날은 모두에서 뺀다(끝을 맞춰 짝짓지 않는다).
- 합치기가 쓰는 끝 맞춤 흐름과 다르면 `alignment` 가 그렇다고 말한다 · 같으면 same(짝). 합치기 경로는 고치지 않는다.
- 보고서는 **로더가 준 날짜만** 싣는다 — 날짜를 주지 않으면 날짜 키가 없다(짝). 길이가 다르면 실패 + 사유.
- 시장 대용: 한국 종목뿐이면 KODEX 200 · 미국 기호뿐이면 원화 상장 S&P500 ETF(같은 값 매김 경로) · 섞이면 없음 + 사유.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import robustness_inputs as ri  # noqa: E402
from src.engine.strategy_robustness import robustness_report  # noqa: E402


def _dates(n: int, start: str = "2025-01-01") -> list[str]:
    import pandas as pd
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start=start, periods=n)]


def _keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(map(str, obj)) | set().union(*(_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(_keys(v) for v in obj)) if obj else set()
    return set()


# ── 보고서의 날짜 축 ──────────────────────────────────────────────────────────

def test_a_report_with_dates_carries_them_through_every_block():
    rng = np.random.default_rng(5)
    T = 160
    S = rng.normal(0, 0.01, (T, 3))
    S[40:60] -= 0.004                                         # 모두 함께 잃는 구간
    d = _dates(T)
    rep = robustness_report(["가", "나", "다"], S, None, dates=d, window=20)
    assert rep["available"] and rep["axis"] == "date"
    assert rep["period"] == {"start": d[0], "end": d[-1]}
    roll = rep["rolling"]
    assert roll["end_dates"] == d[20 - 1:] and len(roll["end_dates"]) == len(roll["ago"])
    for row in rep["drawdown"]["strategies"]:
        if row["max_drawdown_pct"] is None:
            continue
        assert row["start_date"] == d[T - 1 - row["start_ago"]] and row["end_date"] == d[T - 1 - row["end_ago"]]
    w = rep["drawdown"]["worst_window"]
    assert w["start_date"] == d[T - 1 - w["start_ago"]] and w["end_date"] == d[T - 1 - w["end_ago"]]


def test_without_dates_there_are_no_date_keys_pair():
    """짝 — 날짜를 주지 않으면 지어내지 않는다(예전 계약 그대로)."""
    S = np.random.default_rng(6).normal(0, 0.01, (120, 2))
    rep = robustness_report(["A", "B"], S, None)
    assert rep["axis"] == "trading_days_ago"
    assert not any("date" in k.lower() for k in _keys(rep))


def test_dates_of_the_wrong_length_are_a_failure_with_a_reason():
    S = np.random.default_rng(7).normal(0, 0.01, (120, 2))
    rep = robustness_report(["A", "B"], S, None, dates=_dates(119))
    assert rep["available"] is False and "날짜" in rep["reason"]


# ── 날짜로 맞춘 흐름 ──────────────────────────────────────────────────────────

def _closes(dates: list[str], seed: int) -> list[tuple[str, float]]:
    rng = np.random.default_rng(seed)
    px = 100 * np.cumprod(1 + rng.normal(0, 0.01, len(dates)))
    return list(zip(dates, px.tolist()))


def _patch_prices(monkeypatch, table: dict[str, list[tuple[str, float]]]):
    """같은 가격표를 두 로더에 — 날짜 있는 쪽(`daily_closes_indexed`)과 합치기가 쓰는 끝 맞춤 쪽(`daily_closes`)."""
    from src.data import etf_prices
    from src.engine import risk_allocations
    closes = lambda t, market="kr", days=300: [c for _, c in table[t]][-days:]  # noqa: E731
    monkeypatch.setattr(etf_prices, "daily_closes_indexed",
                        lambda t, market="kr", days=300: table[t][-days:])
    monkeypatch.setattr(etf_prices, "daily_closes", closes)
    monkeypatch.setattr(risk_allocations, "daily_closes", closes)


def test_series_are_lined_up_by_date_not_by_their_tails(monkeypatch):
    d = _dates(200)
    gap = d[:150] + d[151:]                                  # B 는 하루(150번째)가 없다
    table = {"A": _closes(d, 1), "B": _closes(gap, 2)}
    _patch_prices(monkeypatch, table)
    sleeves = [{"name": "가", "weights": {"A": 100.0}}, {"name": "나", "weights": {"B": 100.0}}]
    got = ri.dated_sleeve_returns(sleeves, lookback=252)
    assert got["available"], got
    assert d[150] not in got["dates"]                        # 한쪽에 없는 날은 모두에서 뺀다
    assert len(got["dates"]) == got["S"].shape[0] == len(gap) - 1
    # 날짜마다 값이 원래 종가에서 나온다 — A 의 151번째 날 수익은 (가격[151]/가격[149]) - 1 (빠진 날을 건너뛴다).
    pa = dict(table["A"])
    k = got["dates"].index(d[151])
    assert got["S"][k, 0] == pytest.approx(pa[d[151]] / pa[d[149]] - 1)


def test_tail_alignment_differences_are_observed_pair(monkeypatch):
    d = _dates(200)
    gap = d[:150] + d[151:]
    _patch_prices(monkeypatch, {"A": _closes(d, 1), "B": _closes(gap, 2)})
    sleeves = [{"name": "가", "weights": {"A": 100.0}}, {"name": "나", "weights": {"B": 100.0}}]
    a = ri.alignment_check(sleeves, lookback=252)
    assert a["same"] is False and a["differing_days"] > 0 and "끝을 맞춰" in a["reason"]
    # 짝 — 빠진 날이 없으면 같다.
    _patch_prices(monkeypatch, {"A": _closes(d, 1), "B": _closes(d, 2)})
    b = ri.alignment_check(sleeves, lookback=252)
    assert b["same"] is True and b["differing_days"] == 0 and b["reason"] is None


def test_a_ticker_without_prices_is_named_not_dropped_silently(monkeypatch):
    d = _dates(120)
    _patch_prices(monkeypatch, {"A": _closes(d, 1), "B": []})
    sleeves = [{"name": "가", "weights": {"A": 100.0}}, {"name": "나", "weights": {"B": 100.0}}]
    got = ri.dated_sleeve_returns(sleeves, lookback=252)
    assert got["available"] is False and "B" in got["reason"]


# ── 시장 대용 ─────────────────────────────────────────────────────────────────

def test_market_proxy_follows_what_the_sleeves_hold():
    kr = ri.market_proxy(["005930", "000660"])
    assert kr["ticker"] == "069500" and "KODEX 200" in kr["label"] and kr["reason"] is None
    us = ri.market_proxy(["SPY", "QQQ", "TLT"])
    assert us["ticker"] == "SPY" and "원화" in us["label"] and us["reason"] is None
    mixed = ri.market_proxy(["005930", "SPY"])
    assert mixed["ticker"] is None and "섞여" in mixed["reason"]


def test_market_returns_are_matched_on_the_same_dates(monkeypatch):
    d = _dates(130)
    _patch_prices(monkeypatch, {"069500": _closes(d, 9)})
    m, why = ri.market_on_dates("069500", d[1:])
    assert why is None and len(m) == len(d) - 1
    # 짝 — 시장 대용에 없는 날이 있으면 맞추지 않고 사유.
    _patch_prices(monkeypatch, {"069500": _closes(d[:-5], 9)})
    m2, why2 = ri.market_on_dates("069500", d[1:])
    assert m2 is None and "날" in why2
