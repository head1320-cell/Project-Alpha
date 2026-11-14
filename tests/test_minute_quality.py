"""분봉 품질 검사 — ★고치지 않고 센다★ (`src/data/minute_quality.py` · 분봉 백테스트 설계 W4a · a3).

검사는 결함을 메우거나 봉을 버리지 않는다. 무엇이 몇 개인지 세어 돌려주고, 쓰는 쪽(적재 범위 보고 · 분봉 백테스트)이 판단한다.
각 결함에 "있는 봉 / 없는 봉" 짝을 둔다 — 늘 0 을 세거나 늘 1 을 세는 구현을 배제한다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.data import minute_quality as mq

RULES = {"available": True, "open": "0900", "closing_auction_from": "1520", "close": "1530"}
NO_RULES = {"available": False, "open": None, "closing_auction_from": None, "close": None, "reason": "no_evidence_file"}


def bars(*rows) -> pd.DataFrame:
    """rows: (HHMMSS, open, high, low, close, volume)"""
    return pd.DataFrame([dict(zip(["time", "open", "high", "low", "close", "volume"], r)) for r in rows])


CLEAN = [("090000", 100, 101, 99, 100, 10), ("090100", 100, 102, 100, 101, 20), ("090200", 101, 101, 100, 100, 5)]


def day(**by_ticker) -> pd.DataFrame:
    frames = []
    for ticker, (rows, source) in by_ticker.items():
        f = bars(*rows)
        f.insert(0, "ticker", ticker.lstrip("t"))
        f["source"] = source
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


# ── 한 종목 · 하루 ─────────────────────────────────────────────────────────────────────
def test_a_clean_session_has_no_defects_and_reports_its_span():
    out = mq.check_session(bars(*CLEAN), RULES)
    assert out["bars"] == 3 and (out["first"], out["last"]) == ("090000", "090200")
    assert out["defect_total"] == 0 and set(out["defects"].values()) == {0}
    assert set(out["defects"]) == set(mq.DEFECTS)
    assert out["zero_volume_bars"] == 0
    assert out["gaps"] == {"count": 0, "longest_minutes": 0}
    assert out["regular"] == {"inside": 3, "outside": 0} and out["regular_reason"] is None


@pytest.mark.parametrize("defect, row", [
    ("bad_time", ("9시", 100, 101, 99, 100, 10)),
    ("bad_time", ("096100", 100, 101, 99, 100, 10)),               # 61분
    ("ohlc_inconsistent", ("090300", 100, 99, 98, 99, 10)),        # 시가가 고가보다 높다
    ("ohlc_inconsistent", ("090300", 100, 101, 100.5, 101, 10)),   # 저가가 시가보다 높다
    ("ohlc_inconsistent", ("090300", 101, 102, 100.5, 100, 10)),   # 저가가 종가보다 높다(시가보다는 낮다)
    ("ohlc_inconsistent", ("090300", 100, 100.5, 99, 101, 10)),    # 고가가 종가보다 낮다(시가보다는 높다)
    ("nonpositive_price", ("090300", 0, 0, 0, 0, 10)),
    ("negative_volume", ("090300", 100, 101, 99, 100, -1)),
    ("missing_value", ("090300", 100, 101, 99, float("nan"), 10)),
])
def test_each_defect_is_counted_once_for_the_bar_that_has_it(defect, row):
    out = mq.check_session(bars(*CLEAN, row), RULES)
    assert out["defects"][defect] == 1
    assert out["defect_total"] >= 1
    assert out["bars"] == 4                                          # 버리지 않는다


def test_a_repeated_time_is_counted_as_a_duplicate_not_silently_dropped():
    out = mq.check_session(bars(*CLEAN, CLEAN[1]), RULES)
    assert out["defects"]["duplicate_time"] == 1 and out["bars"] == 4


def test_bars_without_trades_are_counted_but_are_not_a_defect():
    out = mq.check_session(bars(*CLEAN, ("090300", 100, 100, 100, 100, 0)), RULES)
    assert out["zero_volume_bars"] == 1 and out["defect_total"] == 0


def test_a_gap_longer_than_a_minute_is_counted_with_its_length():
    out = mq.check_session(bars(*CLEAN, ("090700", 100, 100, 100, 100, 3)), RULES)       # 09:02 → 09:07
    assert out["gaps"] == {"count": 1, "longest_minutes": 5}
    assert out["defect_total"] == 0                                 # 정지·거래 없음일 수 있다 — 결함으로 단정하지 않는다


def test_one_missing_minute_is_already_a_gap():
    out = mq.check_session(bars(*CLEAN, ("090400", 100, 100, 100, 100, 3)), RULES)       # 09:02 → 09:04
    assert out["gaps"] == {"count": 1, "longest_minutes": 2}


def test_a_negative_volume_is_a_defect_and_not_a_bar_without_trades():
    out = mq.check_session(bars(*CLEAN, ("090300", 100, 101, 99, 100, -1)), RULES)
    assert out["zero_volume_bars"] == 0 and out["defects"]["negative_volume"] == 1


def test_bars_outside_the_regular_session_are_counted_apart():
    rows = [("083500", 100, 100, 100, 100, 1), *CLEAN, ("153000", 100, 100, 100, 100, 9), ("160100", 100, 100, 100, 100, 2)]
    out = mq.check_session(bars(*rows), RULES)
    assert out["regular"] == {"inside": 4, "outside": 2}


def test_without_session_rules_inside_and_outside_are_unknown_not_guessed():
    out = mq.check_session(bars(*CLEAN), NO_RULES)
    assert out["regular"] is None and out["regular_reason"] == "no_session_rules"
    assert out["bars"] == 3 and out["defect_total"] == 0             # 나머지 검사는 규칙 없이도 한다


def test_an_empty_session_is_reported_as_empty():
    out = mq.check_session(bars(), RULES)
    assert out["bars"] == 0 and out["first"] is None and out["last"] is None and out["defect_total"] == 0


def test_the_input_is_not_modified():
    frame = bars(*CLEAN, ("9시", 0, 0, 0, 0, -1))
    before = frame.copy()
    mq.check_session(frame, RULES)
    pd.testing.assert_frame_equal(frame, before)


# ── 하루 전체 ─────────────────────────────────────────────────────────────────────────
def test_a_day_sums_its_tickers_and_counts_rows_by_source():
    out = mq.check_day(day(t005930=(CLEAN, "kis"), t000660=([*CLEAN, ("090300", 0, 0, 0, 0, 1)], "synthetic")), RULES)
    assert out["tickers"] == 2 and out["bars"] == 7
    assert out["sources"] == {"kis": 3, "synthetic": 4, "unknown": 0}
    assert out["defect_total"] == 1 and out["defects"]["nonpositive_price"] == 1
    assert out["by_ticker"]["000660"]["defect_total"] == 1 and out["by_ticker"]["005930"]["defect_total"] == 0


def test_an_ordinary_day_is_not_marked_as_shifted():
    out = mq.check_day(day(t005930=(CLEAN, "kis")), RULES)
    assert out["session_shifted"] is False
    assert out["session_shift"] == {"earliest_first": "090000", "expected_open": "0900", "minutes_late": 0, "tickers": 1}


def test_a_day_whose_every_ticker_starts_an_hour_late_is_marked_as_shifted():
    late = [("100000", 100, 101, 99, 100, 10), ("100100", 100, 102, 100, 101, 20)]
    out = mq.check_day(day(t005930=(late, "kis"), t000660=(late, "kis")), RULES)
    assert out["session_shifted"] is True
    assert out["session_shift"]["minutes_late"] == 60 and out["session_shift"]["earliest_first"] == "100000"


def test_one_early_ticker_is_enough_to_say_the_market_opened_on_time():
    late = [("100000", 100, 101, 99, 100, 10)]
    out = mq.check_day(day(t005930=(late, "kis"), t000660=(CLEAN, "kis")), RULES)
    assert out["session_shifted"] is False


def test_the_shift_threshold_is_exclusive_at_thirty_minutes():
    at_30 = [("093000", 100, 101, 99, 100, 10)]
    at_31 = [("093100", 100, 101, 99, 100, 10)]
    assert mq.check_day(day(t005930=(at_30, "kis")), RULES)["session_shifted"] is False
    assert mq.check_day(day(t005930=(at_31, "kis")), RULES)["session_shifted"] is True


def test_without_session_rules_the_shift_is_unknown():
    out = mq.check_day(day(t005930=(CLEAN, "kis")), NO_RULES)
    assert out["session_shifted"] is None and out["shift_reason"] == "no_session_rules" and out["session_shift"] is None


def test_an_empty_day_is_unknown_for_shift_and_zero_for_counts():
    empty = pd.DataFrame(columns=["ticker", "time", "open", "high", "low", "close", "volume", "source"])
    out = mq.check_day(empty, RULES)
    assert out["tickers"] == 0 and out["bars"] == 0 and out["session_shifted"] is None and out["shift_reason"] == "no_bars"


def test_every_reason_has_a_sentence():
    assert set(mq.REASONS) == {"no_session_rules", "no_bars"}
    assert all(text.endswith("니다.") for text in mq.REASONS.values())


def test_detail_limits_the_per_ticker_results_but_not_the_totals():
    whole = day(t005930=(CLEAN, "kis"), t000660=([*CLEAN, ("090300", 0, 0, 0, 0, 1)], "kis"))
    out = mq.check_day(whole, RULES, detail=["005930"])
    assert set(out["by_ticker"]) == {"005930"}
    assert out["tickers"] == 2 and out["bars"] == 7 and out["defect_total"] == 1      # 합계는 고른 종목과 무관하다
    assert mq.check_day(whole, RULES, detail=[])["by_ticker"] == {}


def test_the_same_time_in_two_tickers_is_not_a_duplicate():
    out = mq.check_day(day(t005930=(CLEAN, "kis"), t000660=(CLEAN, "kis")), RULES)
    assert out["defects"]["duplicate_time"] == 0
    twice = day(t005930=([*CLEAN, CLEAN[0]], "kis"), t000660=(CLEAN, "kis"))
    assert mq.check_day(twice, RULES)["defects"]["duplicate_time"] == 1


def test_the_per_ticker_results_of_a_day_equal_the_session_check_of_each_ticker():
    """합계와 종목별 값이 다른 길로 계산돼 어긋나는 일이 없게 — 같은 봉을 따로 검사한 것과 같아야 한다."""
    messy = [*CLEAN, CLEAN[1], ("9시", 1, 1, 1, 1, 1), ("090900", 100, 99, 98, 99, 0), ("160100", 5, 5, 5, 5, -2)]
    whole = day(t005930=(CLEAN, "kis"), t000660=(messy, "unknown"), t035720=([("100000", 1, 1, 1, 1, 1)], "kis"))
    out = mq.check_day(whole, RULES)
    for ticker, frame in whole.groupby("ticker"):
        assert out["by_ticker"][ticker] == mq.check_session(frame.drop(columns=["ticker", "source"]), RULES), ticker
    assert out["defect_total"] == sum(s["defect_total"] for s in out["by_ticker"].values())
    assert out["by_ticker"]["000660"]["defects"] == {"bad_time": 1, "duplicate_time": 1, "ohlc_inconsistent": 1,
                                                     "nonpositive_price": 0, "negative_volume": 1, "missing_value": 0}
