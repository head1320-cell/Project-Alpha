"""CF3 · 수익률 불러오기가 날짜를 맞추며 잃은 것을 말한다 (관측만 — 계산 불변)
==============================================================================
`_load_clean_returns` 는 종목들의 날짜 교집합만 남긴다(`dropna`). 늦게 상장한 종목 하나가 창 전체를 묶어도, 중간 빈 날이
여러 날을 지워도, 벤치마크가 며칠 비어도 지금은 `n_obs` 하나만 남는다. CF3 는 `coverage.alignment` 에 그것을 적는다 —
값을 바꾸지 않고 `notna()` 만 읽는다(골든 `test_cf3_golden` 이 수를 지킨다).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api.allocation_routes import _load_clean_returns  # noqa: E402
from tests.test_cf3_golden import AS_OF, HOLEY, LATE, T5, _frame  # noqa: E402


def _load(monkeypatch, df, lookback, tickers=T5, bench="KOSPI"):
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns", lambda tickers, start, end: df)
    return _load_clean_returns(list(tickers), bench, lookback, as_of=AS_OF)


def test_a_late_listing_that_binds_the_window_is_named(monkeypatch):
    returns, _, _, cov = _load(monkeypatch, _frame(), 900)
    a = cov["alignment"]
    assert a["requested_days"] == 900
    assert a["shortfall_days"] == 900 - len(returns) == 104
    assert a["latest_start"] == {"ticker": LATE, "first": str(returns.index.min().date())}
    assert a["binding"] is True


def test_a_late_listing_outside_the_window_does_not_bind(monkeypatch):
    """짝 — 756일 창은 늦은 상장 뒤에서 시작한다: 늦은 종목은 이름이 남지만 창을 묶지 않는다."""
    returns, _, _, cov = _load(monkeypatch, _frame(), 756)
    a = cov["alignment"]
    assert a["shortfall_days"] == 0
    assert a["latest_start"]["ticker"] == LATE
    assert a["binding"] is False


def test_holes_inside_the_window_are_counted(monkeypatch):
    df = _frame()
    returns, _, _, cov = _load(monkeypatch, df, 756)
    a = cov["alignment"]
    span = df[T5].loc[returns.index.min():returns.index.max()]
    assert a["holes_in_window"] == int(span.isna().any(axis=1).sum()) == 4
    assert int(df[HOLEY].isna().sum()) == 4


def test_benchmark_gap_days_are_counted(monkeypatch):
    returns, bench, _, cov = _load(monkeypatch, _frame(), 756)
    assert cov["alignment"]["bench_gap_days"] == len(returns) - len(bench) == 6


def test_clean_data_reports_nothing_lost(monkeypatch):
    """짝 — 빈 날이 없고 모두 같은 날 시작하면 잃은 것이 0 이고 늦은 종목도 없다."""
    idx = pd.bdate_range(end=AS_OF, periods=900)
    rng = np.random.default_rng(1)
    df = pd.DataFrame({t: np.round(rng.normal(0, 0.01, 900), 6) for t in [*T5, "KOSPI"]}, index=idx)
    _, _, _, cov = _load(monkeypatch, df, 756)
    a = cov["alignment"]
    assert a == {"requested_days": 756, "shortfall_days": 0, "holes_in_window": 0,
                 "latest_start": None, "binding": False, "bench_gap_days": 0}


def test_no_benchmark_means_no_gap_count(monkeypatch):
    """벤치마크를 요청하지 않으면 빈 날은 '없음'이 아니라 잴 대상이 없다 — None."""
    _, bench, _, cov = _load(monkeypatch, _frame(), 756, bench=None)
    assert bench is None
    assert cov["alignment"]["bench_gap_days"] is None


@pytest.mark.parametrize("lookback", [756, 900])
def test_alignment_does_not_change_the_returns(monkeypatch, lookback):
    """관측은 값을 바꾸지 않는다 — 같은 입력으로 alignment 키를 빼고 보면 예전 계산과 같다."""
    df = _frame()
    before = df.copy()
    returns, bench, _, _ = _load(monkeypatch, df, lookback)
    pd.testing.assert_frame_equal(df, before)                     # 입력을 건드리지 않는다
    expect = df[T5].dropna()
    expect = expect.iloc[-lookback:] if len(expect) > lookback else expect
    pd.testing.assert_frame_equal(returns, expect)
