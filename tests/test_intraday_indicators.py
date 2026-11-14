"""분봉 지표 등록부 — ★봉 i 의 값은 봉 i 까지만으로 정해진다★ (분봉 백테스트 설계 §7.1 · W4b b1).

두 가지를 건다.
1. 값 — 봉 열 개짜리 하루를 손으로 계산한 값과 견준다(계산은 시험 옆에 적는다).
2. 성질 — 등록부의 ★모든★ 지표에 대해, 임의의 자리 k 뒤의 봉을 지우거나 터무니없는 값으로 바꿔도 앞 k 개의 값이 한 자리도
   달라지지 않는다. 새 지표를 등록부에 더하면 이 시험이 자동으로 건다(지표마다 따로 쓰지 않는다).
덥혀지지 않은 자리는 0 이 아니라 NaN 이다 — 미상 ≠ 0.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.engine.intraday import indicators as ind
from src.engine.intraday.types import PrevDay, Session


def session(rows, prev=None, ticker="005930", date="2026-03-04") -> Session:
    """rows: (HHMMSS, open, high, low, close, volume)"""
    t, o, h, low, c, v = zip(*rows)
    return Session(ticker=ticker, date=date, time=np.array(t), open=np.array(o, float), high=np.array(h, float),
                   low=np.array(low, float), close=np.array(c, float), volume=np.array(v, float),
                   source="kis", prev=prev)


#        시각      시가  고가  저가  종가  거래량
ROWS = [("090000", 100, 102, 99, 101, 10),
        ("090100", 101, 103, 100, 102, 20),
        ("090200", 102, 104, 101, 103, 30),
        ("090300", 103, 103, 100, 100, 40),
        ("090400", 100, 101, 98, 99, 50),
        ("090500", 99, 105, 99, 104, 60),
        ("090600", 104, 106, 103, 105, 0),
        ("090700", 105, 105, 102, 102, 70),
        ("090800", 102, 103, 101, 103, 80),
        ("090900", 103, 107, 103, 106, 90)]
S = session(ROWS, prev=PrevDay(close=98.0, high=101.0, low=95.0, basis="minute"))
NAN = float("nan")


def same(a, b) -> bool:
    return np.allclose(np.asarray(a, float), np.asarray(b, float), rtol=1e-9, atol=1e-9, equal_nan=True)


# ── 값 ───────────────────────────────────────────────────────────────────────────────
def test_raw_columns_are_passed_through():
    assert same(ind.compute(S, "close"), [r[4] for r in ROWS])
    assert same(ind.compute(S, "volume"), [r[5] for r in ROWS])


def test_vwap_is_the_running_volume_weighted_typical_price():
    # 대표가 = (고+저+종)/3 → 100.667, 101.667, 102.667 …  ·  누적(대표가×거래량) ÷ 누적 거래량
    tp = [(r[2] + r[3] + r[4]) / 3 for r in ROWS]
    cum_pv, cum_v, want = 0.0, 0.0, []
    for price, row in zip(tp, ROWS):
        cum_pv += price * row[5]
        cum_v += row[5]
        want.append(cum_pv / cum_v)
    got = ind.compute(S, "vwap")
    assert same(got, want)
    assert math.isclose(got[1], (100.6666666667 * 10 + 101.6666666667 * 20) / 30, rel_tol=1e-9)
    assert got[6] == got[5]                                  # 거래 없는 봉은 VWAP 를 움직이지 않는다


def test_vwap_is_unknown_until_the_first_trade():
    quiet = session([("090000", 100, 100, 100, 100, 0), ("090100", 100, 101, 100, 101, 5)])
    got = ind.compute(quiet, "vwap")
    assert math.isnan(got[0]) and math.isclose(got[1], (101 + 100 + 101) / 3)


def test_opening_range_is_unknown_inside_the_window_and_fixed_after_it():
    # 첫 봉 09:00 부터 3분 → 창은 09:00·09:01·09:02 의 세 봉. 고가 max(102,103,104)=104 · 저가 min(99,100,101)=99
    hi, lo, done = (ind.compute(S, name, {"minutes": 3}) for name in ("or_high", "or_low", "or_done"))
    assert all(math.isnan(x) for x in hi[:3]) and all(math.isnan(x) for x in lo[:3])
    assert same(hi[3:], [104] * 7) and same(lo[3:], [99] * 7)
    assert same(done, [0, 0, 0, 1, 1, 1, 1, 1, 1, 1])


def test_opening_range_counts_minutes_from_the_first_bar_not_bars():
    # 09:01 봉이 없다(거래 없음) → 3분 창에는 09:00·09:02 의 두 봉만 든다
    rows = [ROWS[0], ROWS[2], ROWS[3], ROWS[4]]
    hi = ind.compute(session(rows), "or_high", {"minutes": 3})
    assert math.isnan(hi[0]) and math.isnan(hi[1]) and same(hi[2:], [104, 104])


def test_sma_needs_its_full_window():
    got = ind.compute(S, "sma", {"n": 3})
    assert math.isnan(got[0]) and math.isnan(got[1])
    assert same(got[2:5], [(101 + 102 + 103) / 3, (102 + 103 + 100) / 3, (103 + 100 + 99) / 3])


def test_bollinger_bands_use_the_population_deviation_of_the_window():
    # 봉 2: 종가 101·102·103 → 평균 102 · 모표준편차 sqrt(2/3)=0.81650 → 상단 102+2×0.8165 · 하단 102−2×0.8165
    mid, up, lo = (ind.compute(S, name, {"n": 3, "k": 2.0}) for name in ("bb_mid", "bb_upper", "bb_lower"))
    sd = math.sqrt(2 / 3)
    assert math.isclose(mid[2], 102) and math.isclose(up[2], 102 + 2 * sd) and math.isclose(lo[2], 102 - 2 * sd)
    assert math.isnan(up[1]) and math.isnan(lo[1])


def test_rsi_is_wilders_and_starts_after_n_changes():
    # 종가 101,102,103,100,99,104 … 변화 +1,+1,−3,−1,+5 …  n=3:
    #   봉 3(변화 셋: +1,+1,−3): 평균 상승 2/3 · 평균 하락 3/3=1 → RS=0.6667 → RSI=100−100/1.6667=40
    #   봉 4(변화 −1): 평균 상승 (2/3×2+0)/3=0.4444 · 평균 하락 (1×2+1)/3=1 → RSI=100−100/1.4444=30.769
    #   봉 5(변화 +5): 평균 상승 (0.4444×2+5)/3=1.9630 · 평균 하락 (1×2+0)/3=0.6667 → RSI=74.648
    got = ind.compute(S, "rsi", {"n": 3})
    assert all(math.isnan(x) for x in got[:3])
    assert math.isclose(got[3], 40.0, abs_tol=1e-9)
    assert math.isclose(got[4], 100 - 100 / (1 + 0.4444444444 / 1.0), abs_tol=1e-6)
    assert math.isclose(got[5], 100 - 100 / (1 + 1.962962963 / 0.6666666667), abs_tol=1e-6)


def test_rsi_guards_the_division_when_nothing_fell_or_nothing_moved():
    up_only = session([(f"09{m:02d}00", 100 + m, 101 + m, 100 + m, 101 + m, 1) for m in range(6)])
    flat = session([(f"09{m:02d}00", 100, 100, 100, 100, 1) for m in range(6)])
    assert ind.compute(up_only, "rsi", {"n": 3})[5] == 100.0        # 하락이 0 — 100 이라는 값
    assert math.isnan(ind.compute(flat, "rsi", {"n": 3})[5])        # 움직임이 0 — 정의되지 않는다(50 으로 지어내지 않는다)


def test_volume_average_and_highest_close_look_only_at_the_bars_before():
    vol = ind.compute(S, "vol_avg", {"bars": 3})
    top = ind.compute(S, "highest_close", {"bars": 3})
    assert all(math.isnan(x) for x in vol[:3]) and all(math.isnan(x) for x in top[:3])
    assert math.isclose(vol[3], (10 + 20 + 30) / 3) and math.isclose(vol[4], (20 + 30 + 40) / 3)      # 자기 봉은 빼고
    assert top[3] == 103 and top[5] == 103 and top[6] == 104


def test_day_open_and_previous_day_values_are_constants():
    assert same(ind.compute(S, "day_open"), [100] * 10)
    assert same(ind.compute(S, "prev_close"), [98] * 10)
    assert same(ind.compute(S, "prev_high"), [101] * 10) and same(ind.compute(S, "prev_low"), [95] * 10)


def test_without_a_previous_day_those_values_are_unknown_not_zero():
    alone = session(ROWS)
    for name in ("prev_close", "prev_high", "prev_low"):
        assert all(math.isnan(x) for x in ind.compute(alone, name)), name


def test_minute_is_the_clock_of_the_bar_label():
    assert same(ind.compute(S, "minute")[:3], [540, 541, 542])


# ── 등록부와 매개변수 ──────────────────────────────────────────────────────────────────
def test_an_unknown_indicator_or_parameter_is_refused_with_a_reason():
    for name, params, code in (("macd", {}, "unknown_indicator"), ("sma", {"window": 3}, "unknown_param"),
                               ("sma", {"n": 0}, "param_out_of_range"), ("sma", {"n": 2.5}, "param_not_integer"),
                               ("bb_upper", {"n": 3, "k": 99}, "param_out_of_range"), ("sma", {"n": True}, "param_not_integer")):
        with pytest.raises(ind.IndicatorError) as err:
            ind.compute(S, name, params)
        assert err.value.code == code, (name, params)


def test_missing_parameters_take_the_registered_default():
    assert same(ind.compute(S, "sma", {}), ind.compute(S, "sma", {"n": ind.INDICATORS["sma"].params["n"].default}))


def test_the_registry_says_which_indicators_need_the_previous_day():
    assert {n for n, spec in ind.INDICATORS.items() if spec.needs_prev} == {"prev_close", "prev_high", "prev_low"}


# ── 성질: 앞보기 0 ─────────────────────────────────────────────────────────────────────
def _random_session(seed: int, n: int = 60) -> Session:
    rng = np.random.default_rng(seed)
    close = 10_000 + np.cumsum(rng.integers(-30, 31, n)) * 10.0
    open_ = close + rng.integers(-2, 3, n) * 10.0
    high = np.maximum(open_, close) + rng.integers(0, 4, n) * 10.0
    low = np.minimum(open_, close) - rng.integers(0, 4, n) * 10.0
    volume = rng.integers(0, 500, n).astype(float)
    volume[rng.integers(0, n, 5)] = 0.0
    minutes = np.cumsum(rng.integers(1, 3, n)) + 9 * 60       # 군데군데 빈 분이 있다
    time = np.array([f"{m // 60:02d}{m % 60:02d}00" for m in minutes])
    return Session(ticker="000001", date="2026-03-04", time=time, open=open_, high=high, low=low, close=close,
                   volume=volume, source="kis", prev=PrevDay(close=9_990.0, high=10_100.0, low=9_900.0, basis="minute"))


def _cut(s: Session, k: int) -> Session:
    return Session(s.ticker, s.date, s.time[:k], s.open[:k], s.high[:k], s.low[:k], s.close[:k], s.volume[:k], s.source, s.prev)


def _poison(s: Session, k: int) -> Session:
    """k 뒤의 봉을 터무니없는 값으로 — 시각과 봉 수는 그대로."""
    def bad(a, value):
        out = a.copy()
        out[k:] = value
        return out
    return Session(s.ticker, s.date, s.time, bad(s.open, 1.0), bad(s.high, 9e9), bad(s.low, 1e-9), bad(s.close, 5e8),
                   bad(s.volume, 7e12), s.source, s.prev)


@pytest.mark.parametrize("name", sorted(ind.INDICATORS))
def test_no_indicator_looks_ahead(name):
    spec = ind.INDICATORS[name]
    for seed in range(4):
        full_session = _random_session(seed)
        for params in ({}, {p: r.low for p, r in spec.params.items()}, {p: min(r.high, 15) for p, r in spec.params.items()}):
            full = ind.compute(full_session, name, params)
            assert len(full) == len(full_session.time)
            for k in (1, 2, 7, 23, 41, 59):
                assert same(ind.compute(_cut(full_session, k), name, params), full[:k]), (name, params, seed, k, "지움")
                assert same(ind.compute(_poison(full_session, k), name, params)[:k], full[:k]), (name, params, seed, k, "바꿈")


def test_the_property_test_would_catch_a_looking_ahead_indicator(monkeypatch):
    """짝 — 성질 시험이 늘 통과하는 시험이 아님을 보인다: 앞을 보는 지표를 심으면 걸린다."""
    cheat = ind.Indicator(lambda s: np.full(len(s.close), s.close.max()), {}, False)
    monkeypatch.setitem(ind.INDICATORS, "cheat", cheat)
    with pytest.raises(AssertionError):
        test_no_indicator_looks_ahead("cheat")
