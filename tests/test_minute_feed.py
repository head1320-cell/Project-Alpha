"""분봉 파일 → 분봉 백테스트의 하루(`Day`) — `src/data/minute_feed.py` (분봉 백테스트 설계 §6.1 · W4c).

엔진은 파일을 모른다. 이 층이 파일을 읽어 엔진이 쓸 모양으로 옮기면서 ★쓰지 않는 것을 사유와 함께 건너뛴다★:
분봉이 없는 종목 · 결함이 있는 봉 · 운영 게이트가 막은 합성 하루 · 정규장 밖의 봉. 전일 값은 앞선 적재일의 분봉에서 얻고,
너무 멀면(닷새 넘게) 모른다고 둔다.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import src.data.minute_bars as mb
from src.data import minute_feed as feed
from src.data.market_rules import session_rules
from src.engine.trade_journal.costs import market_and_instrument

RULES = {"available": True, "open": "0900", "closing_auction_from": "1520", "close": "1530"}
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]


@pytest.fixture
def bars_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path))
    monkeypatch.setenv("KIS_USE_MOCK", "0")              # 손으로 쓴 `kis` 행을 운영 게이트로 읽는다
    mb.clear_cache()
    yield tmp_path
    mb.clear_cache()


def write_day(day: str, rows: list[tuple]) -> None:
    """rows: (종목, HHMMSS, 시, 고, 저, 종, 거래량, 출처)"""
    mb._write_day_file(pd.DataFrame(rows, columns=COLS), day)
    mb.clear_cache()


def bar(ticker, time, close, *, source="kis", volume=100):
    return (ticker, time, close, close + 10, close - 10, close, volume, source)


D1 = [bar("005930", "090000", 10_000), bar("005930", "090100", 10_020), bar("005930", "090200", 10_050),
      bar("000660", "090000", 20_000), bar("000660", "090100", 20_100)]


def days(tickers, start, end, **kw):
    return feed.build_days(tickers, date.fromisoformat(start), date.fromisoformat(end), rules=RULES, **kw)


# ── 하루를 짓는다 ─────────────────────────────────────────────────────────────────────
def test_only_the_asked_tickers_become_sessions_with_sorted_float_arrays(bars_dir):
    write_day("2026-03-04", list(reversed(D1)))               # 파일의 줄 순서가 뒤집혀 있어도
    [day] = days(["005930"], "2026-03-04", "2026-03-04")
    assert day.date == "2026-03-04" and set(day.sessions) == {"005930"} and day.skipped == () and day.shifted is False
    s = day.sessions["005930"]
    assert list(s.time) == ["090000", "090100", "090200"] and list(s.close) == [10_000.0, 10_020.0, 10_050.0]
    assert list(s.high) == [10_010.0, 10_030.0, 10_060.0] and s.close.dtype == "float64" and s.volume.dtype == "float64"
    assert (s.ticker, s.date, s.source, s.prev) == ("005930", "2026-03-04", "kis", None)


def test_days_without_a_file_are_simply_absent_and_a_ticker_without_bars_is_skipped_with_a_reason(bars_dir):
    write_day("2026-03-04", D1)
    out = days(["005930", "035720"], "2026-03-01", "2026-03-10")
    assert [d.date for d in out] == ["2026-03-04"]
    assert out[0].skipped == (("035720", "no_bars"),) and set(out[0].sessions) == {"005930"}


def test_in_production_a_synthetic_day_gives_no_sessions_and_says_why(bars_dir, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    mb.collect_day(["005930"], "2026-03-04")
    mb.clear_cache()
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    [day] = days(["005930"], "2026-03-04", "2026-03-04")
    assert day.sessions == {} and day.skipped == (("005930", "synthetic_rows_blocked"),)
    monkeypatch.setenv("KIS_USE_MOCK", "1")                    # 짝: 모의 게이트는 그 하루를 쓴다 — 출처는 합성으로 적힌다
    [mock_day] = days(["005930"], "2026-03-04", "2026-03-04")
    assert mock_day.sessions["005930"].source == "synthetic" and len(mock_day.sessions["005930"].time) > 300


def test_a_session_with_defects_is_not_used_and_not_repaired(bars_dir):
    bad = [*D1, ("005930", "090300", 10_000, 9_000, 9_500, 10_000, 100, "kis")]       # 고가가 시가보다 낮다
    write_day("2026-03-04", bad)
    [day] = days(["005930", "000660"], "2026-03-04", "2026-03-04")
    assert day.skipped == (("005930", "defects"),) and set(day.sessions) == {"000660"}


def test_bars_outside_the_regular_session_are_left_out(bars_dir):
    write_day("2026-03-04", [bar("005930", "083500", 9_900), *D1, bar("005930", "153000", 10_060), bar("005930", "161000", 10_070)])
    [day] = days(["005930"], "2026-03-04", "2026-03-04")
    assert list(day.sessions["005930"].time) == ["090000", "090100", "090200", "153000"]


def test_without_session_rules_every_bar_is_kept_because_inside_cannot_be_told(bars_dir):
    write_day("2026-03-04", [bar("005930", "083500", 9_900), *D1])
    [day] = feed.build_days(["005930"], date(2026, 3, 4), date(2026, 3, 4), rules={"available": False})
    assert list(day.sessions["005930"].time)[0] == "083500" and day.shifted is False


def test_a_ticker_whose_rows_have_mixed_sources_is_labelled_unknown(bars_dir):
    write_day("2026-03-04", [bar("005930", "090000", 10_000), bar("005930", "090100", 10_020, source="unknown")])
    [day] = days(["005930"], "2026-03-04", "2026-03-04")
    assert day.sessions["005930"].source == "unknown"


# ── 운영 시간이 다른 날 ───────────────────────────────────────────────────────────────
def test_a_day_is_shifted_when_the_whole_market_started_late_not_just_the_asked_ticker(bars_dir):
    late = [bar("005930", "100000", 10_000), bar("005930", "100100", 10_020)]
    write_day("2026-03-04", [*late, bar("000660", "100000", 20_000)])
    write_day("2026-03-05", [*late, bar("000660", "090000", 20_000)])                   # 다른 종목은 제때 시작했다
    out = days(["005930"], "2026-03-04", "2026-03-05")
    assert [d.shifted for d in out] == [True, False]


# ── 전일 값 ───────────────────────────────────────────────────────────────────────────
def test_the_previous_day_comes_from_the_nearest_earlier_loaded_day(bars_dir):
    write_day("2026-03-04", D1)
    write_day("2026-03-05", [bar("005930", "090000", 10_100)])
    out = days(["005930"], "2026-03-04", "2026-03-05", need_prev=True)
    assert out[0].sessions["005930"].prev is None                                       # 그 앞날의 분봉이 없다
    prev = out[1].sessions["005930"].prev
    assert (prev.close, prev.high, prev.low, prev.basis, prev.date) == (10_050.0, 10_060.0, 9_990.0, "minute", "2026-03-04")


def test_the_previous_day_is_looked_up_before_the_asked_range(bars_dir):
    write_day("2026-02-27", D1)                                                          # 금요일
    write_day("2026-03-02", [bar("005930", "090000", 10_100)])                           # 월요일
    [day] = days(["005930"], "2026-03-02", "2026-03-02", need_prev=True)
    assert day.sessions["005930"].prev.date == "2026-02-27" and day.sessions["005930"].prev.close == 10_050.0


def test_a_previous_day_more_than_five_days_back_is_unknown(bars_dir):
    write_day("2026-02-24", D1)
    write_day("2026-03-02", [bar("005930", "090000", 10_100)])
    [day] = days(["005930"], "2026-03-02", "2026-03-02", need_prev=True)
    assert day.sessions["005930"].prev is None


def test_a_previous_day_with_defects_is_not_used_as_the_previous_day(bars_dir):
    write_day("2026-03-04", [*D1, ("005930", "090300", 10_000, 9_000, 9_500, 10_000, 100, "kis")])
    write_day("2026-03-05", [bar("005930", "090000", 10_100)])
    out = days(["005930"], "2026-03-04", "2026-03-05", need_prev=True)
    assert out[1].sessions["005930"].prev is None


def test_without_need_prev_nothing_before_the_range_is_read(bars_dir, monkeypatch):
    write_day("2026-02-27", D1)
    write_day("2026-03-02", [bar("005930", "090000", 10_100)])
    read = []
    real = mb.load_day_frame
    monkeypatch.setattr(mb, "load_day_frame", lambda d: read.append(str(d)) or real(d))
    days(["005930"], "2026-03-02", "2026-03-02")
    assert read == ["2026-03-02"]


# ── 종목 마스터 ───────────────────────────────────────────────────────────────────────
def test_market_and_instrument_come_from_the_master_only_when_it_knows():
    master = {"005930": {"market": "KOSPI", "group_code": "ST", "name": "삼성전자"},
              "069500": {"market": "KOSPI", "is_etf": True}, "999999": {"market": "NYSE", "group_code": "XX"}}.get
    assert market_and_instrument("005930", master) == ("KOSPI", "stock")
    assert market_and_instrument("069500", master) == ("KOSPI", "etf")
    assert market_and_instrument("999999", master) == (None, None)        # 모르는 시장 · 'ETF 아님'은 주식이라는 뜻이 아니다
    assert market_and_instrument("000000", master) == (None, None) and market_and_instrument("005930", None) == (None, None)


def test_sessions_carry_what_the_master_knows(bars_dir):
    write_day("2026-03-04", D1)
    master = {"005930": {"market": "KOSPI", "group_code": "ST", "name": "삼성전자"}}.get
    [day] = days(["005930", "000660"], "2026-03-04", "2026-03-04", master=master)
    a, b = day.sessions["005930"], day.sessions["000660"]
    assert (a.market, a.instrument, a.name) == ("KOSPI", "stock", "삼성전자")
    assert (b.market, b.instrument, b.name) == (None, None, None)


# ── 읽기 전에 재는 것 ─────────────────────────────────────────────────────────────────
def test_the_plan_lists_loaded_days_and_their_size_without_reading_them(bars_dir, monkeypatch):
    write_day("2026-03-04", D1)
    write_day("2026-03-06", D1)
    monkeypatch.setattr(mb, "load_day_frame", lambda d: (_ for _ in ()).throw(AssertionError("읽었다")))
    plan = feed.plan(date(2026, 3, 1), date(2026, 3, 10))
    assert plan.dates == ["2026-03-04", "2026-03-06"]
    assert plan.bytes == sum(mb._existing_day_path(d).stat().st_size for d in plan.dates) > 0


def test_the_real_session_rules_work_with_the_feed(bars_dir):
    write_day("2026-03-04", D1)
    [day] = feed.build_days(["005930"], date(2026, 3, 4), date(2026, 3, 4), rules=session_rules())
    assert len(day.sessions["005930"].time) == 3
