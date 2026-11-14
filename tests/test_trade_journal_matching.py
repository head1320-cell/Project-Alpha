"""매매일지 — 줄 검사와 왕복 매칭 (설계 `docs/superpowers/specs/2026-11-14-trade-journal-design.md` §4.2 · §5.1)

계약
① 통과 못 한 줄은 ★사유와 줄 번호와 함께★ 돌려준다 — 조용히 버리지 않는다.
② 손익은 선입선출로 맞춘 묶음에서 나온다(먼저 산 것부터 판 것으로 본다).
③ 거래(왕복)는 보유 수량이 0 에서 시작해 다시 0 이 될 때까지다 — 나눠 사고 나눠 팔아도 한 번이다.
④ 파일이 끝났는데 0 으로 돌아오지 않은 거래는 미청산이다 — 남은 수량을 평가하지 않는다.
⑤ 매수 기록 없는 매도는 손익을 계산하지 않고 따로 센다.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.engine.trade_journal.fills import REJECT_REASONS, normalize
from src.engine.trade_journal.matching import match


def row(at, symbol, side, qty, price, **extra) -> dict:
    return {"executed_at": at, "symbol": symbol, "side": side, "quantity": qty, "price": price, **extra}


def fills_of(*rows):
    fills, rejects = normalize(list(rows))
    assert rejects == [], rejects
    return fills


# ══ 줄 검사 ═══════════════════════════════════════════════════════════════════

def test_a_clean_row_becomes_a_fill():
    fills, rejects = normalize([row("2026-03-04 09:01:02", "005930", "buy", 10, 70_000, fee=105, name="삼성전자")])
    assert rejects == []
    f = fills[0]
    assert (f.at, f.symbol, f.side, f.quantity, f.price) == (datetime(2026, 3, 4, 9, 1, 2), "005930", "buy", 10.0, 70_000.0)
    assert f.fee == 105.0 and f.tax is None and f.name == "삼성전자" and f.has_time is True
    assert f.notional == 700_000.0 and f.row == 0


@pytest.mark.parametrize("text,expected,has_time", [
    ("2026-03-04 09:01:02", datetime(2026, 3, 4, 9, 1, 2), True),
    ("2026-03-04 09:01", datetime(2026, 3, 4, 9, 1), True),
    ("2026-03-04T09:01:02", datetime(2026, 3, 4, 9, 1, 2), True),
    ("2026/03/04 09:01:02", datetime(2026, 3, 4, 9, 1, 2), True),
    ("2026.03.04 09:01:02", datetime(2026, 3, 4, 9, 1, 2), True),
    ("20260304 090102", datetime(2026, 3, 4, 9, 1, 2), True),
    ("20260304090102", datetime(2026, 3, 4, 9, 1, 2), True),
    ("2026-03-04", datetime(2026, 3, 4), False),
    ("20260304", datetime(2026, 3, 4), False),
])
def test_the_usual_datetime_forms_are_read(text, expected, has_time):
    fills, rejects = normalize([row(text, "A", "buy", 1, 100)])
    assert rejects == [] and fills[0].at == expected and fills[0].has_time is has_time


@pytest.mark.parametrize("bad,reason", [
    (row("어제", "A", "buy", 1, 100), "bad_datetime"),
    (row("2026-13-40 09:00", "A", "buy", 1, 100), "bad_datetime"),
    (row(None, "A", "buy", 1, 100), "bad_datetime"),
    (row("2026-03-04 09:00", "", "buy", 1, 100), "no_symbol"),
    (row("2026-03-04 09:00", "A", "매수", 1, 100), "bad_side"),
    (row("2026-03-04 09:00", "A", "buy", 0, 100), "bad_quantity"),
    (row("2026-03-04 09:00", "A", "buy", -3, 100), "bad_quantity"),
    (row("2026-03-04 09:00", "A", "buy", "많이", 100), "bad_quantity"),
    (row("2026-03-04 09:00", "A", "buy", True, 100), "bad_quantity"),
    (row("2026-03-04 09:00", "A", "buy", 1, 0), "bad_price"),
    (row("2026-03-04 09:00", "A", "buy", 1, None), "bad_price"),
    (row("2026-03-04 09:00", "A", "buy", 1, 100, fee=-5), "bad_fee"),
    (row("2026-03-04 09:00", "A", "buy", 1, 100, tax="x"), "bad_tax"),
])
def test_a_row_that_cannot_be_used_is_returned_with_its_reason(bad, reason):
    fills, rejects = normalize([row("2026-03-04 09:00", "A", "buy", 1, 100), bad])
    assert len(fills) == 1, "나쁜 줄 하나가 좋은 줄까지 버리게 하면 안 된다"
    assert rejects == [{"row": 1, "reason": reason, "message": REJECT_REASONS[reason]}]


def test_every_reject_reason_has_a_sentence():
    assert all(v.strip() for v in REJECT_REASONS.values()) and len(REJECT_REASONS) >= 7


def test_fills_come_out_in_time_order_and_ties_keep_the_file_order():
    fills = fills_of(row("2026-03-04 10:00", "A", "sell", 1, 110), row("2026-03-04 09:00", "A", "buy", 1, 100),
                     row("2026-03-04 09:00", "B", "buy", 2, 50))
    assert [(f.symbol, f.side, f.row) for f in fills] == [("A", "buy", 1), ("B", "buy", 2), ("A", "sell", 0)]


def test_numeric_strings_are_accepted_but_grouped_digits_are_not_guessed():
    fills, rejects = normalize([row("2026-03-04 09:00", "A", "buy", "3", "100.5"), row("2026-03-04 09:00", "A", "buy", 1, "1,000")])
    assert fills[0].quantity == 3.0 and fills[0].price == 100.5
    assert [r["reason"] for r in rejects] == ["bad_price"], "쉼표를 걷는 일은 파일을 읽는 쪽(브라우저)이 한다"


def test_market_and_instrument_are_normalised_and_unknown_values_become_none():
    fills = fills_of(row("2026-03-04 09:00", "A", "buy", 1, 100, market=" kospi ", instrument="ETF"),
                     row("2026-03-04 09:00", "B", "buy", 1, 100, market="NYSE", instrument="warrant"))
    assert (fills[0].market, fills[0].instrument) == ("KOSPI", "etf")
    assert (fills[1].market, fills[1].instrument) == (None, None), "모르는 시장·상품은 지어내지 않고 미상으로 둔다"


# ══ 왕복 매칭 ═════════════════════════════════════════════════════════════════

def test_one_buy_one_sell_is_one_closed_trade():
    out = match(fills_of(row("2026-03-04 09:00:00", "A", "buy", 10, 100), row("2026-03-04 09:10:00", "A", "sell", 10, 110)))
    assert len(out.trades) == 1 and out.unmatched_sells == []
    t = out.trades[0]
    assert t.closed is True and t.symbol == "A" and t.gross == 100.0
    assert t.opened_at == datetime(2026, 3, 4, 9, 0) and t.closed_at == datetime(2026, 3, 4, 9, 10)
    assert t.holding_seconds == 600 and t.same_day is True
    assert (t.buy_quantity, t.sell_quantity, t.buy_amount, t.sell_amount) == (10, 10, 1_000.0, 1_100.0)


def test_scaling_in_and_out_is_still_one_trade():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 10, 100), row("2026-03-04 09:05", "A", "buy", 10, 104),
                         row("2026-03-04 09:20", "A", "sell", 5, 110), row("2026-03-04 09:30", "A", "sell", 15, 108)))
    assert len(out.trades) == 1
    t = out.trades[0]
    assert t.closed is True and len(t.matches) == 3
    # 선입선출: 5주(100→110) + 5주(100→108) + 10주(104→108) = 50 + 40 + 40
    assert [m.gross for m in t.matches] == [50.0, 40.0, 40.0] and t.gross == 130.0
    assert t.closed_at == datetime(2026, 3, 4, 9, 30)


def test_first_in_first_out_decides_which_cost_is_matched():
    """후입선출이면 105 원가가 먼저 맞아 손익이 달라진다 — 어느 규칙인지가 결과를 바꾼다."""
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 10, 100), row("2026-03-04 09:05", "A", "buy", 10, 105),
                         row("2026-03-04 09:20", "A", "sell", 10, 103)))
    t = out.trades[0]
    assert t.matches[0].buy.price == 100.0 and t.realized_gross == 30.0
    assert t.closed is False and t.open_quantity == 10.0


def test_returning_to_zero_ends_the_trade_and_the_next_buy_starts_another():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 10, 100), row("2026-03-04 09:10", "A", "sell", 10, 99),
                         row("2026-03-04 10:00", "A", "buy", 5, 98), row("2026-03-04 10:30", "A", "sell", 5, 101)))
    assert [(t.gross, t.closed) for t in out.trades] == [(-10.0, True), (15.0, True)]


def test_a_position_left_at_the_end_is_open_and_is_not_valued():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 10, 100), row("2026-03-04 09:10", "A", "sell", 4, 110)))
    t = out.trades[0]
    assert t.closed is False and t.closed_at is None and t.open_quantity == 6.0
    assert t.realized_gross == 40.0, "이미 판 몫의 손익은 실현분이다"
    assert t.gross is None, "미청산 거래의 손익은 정해지지 않았다 — 남은 수량을 평가하지 않는다"


def test_a_file_with_only_buys_has_no_trades_to_score():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 10, 100), row("2026-03-04 09:30", "B", "buy", 3, 50)))
    assert [t.closed for t in out.trades] == [False, False] and all(t.realized_gross == 0.0 for t in out.trades)


def test_a_sell_with_nothing_to_match_is_counted_apart():
    out = match(fills_of(row("2026-03-04 09:00", "A", "sell", 10, 100)))
    assert out.trades == []
    assert out.unmatched_sells == [{"row": 0, "symbol": "A", "quantity": 10.0, "reason": "no_position"}]


def test_selling_more_than_held_matches_what_is_held_and_sets_the_rest_apart():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 10, 100), row("2026-03-04 09:10", "A", "sell", 15, 110)))
    t = out.trades[0]
    assert t.closed is True and t.gross == 100.0 and t.sell_quantity == 10.0
    assert out.unmatched_sells == [{"row": 1, "symbol": "A", "quantity": 5.0, "reason": "no_position"}]


def test_symbols_are_matched_separately():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 10, 100), row("2026-03-04 09:01", "B", "buy", 10, 200),
                         row("2026-03-04 09:02", "A", "sell", 10, 101), row("2026-03-04 09:03", "B", "sell", 10, 198)))
    assert {t.symbol: t.gross for t in out.trades} == {"A": 10.0, "B": -20.0}


def test_trades_are_listed_in_the_order_they_closed_then_open_ones():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 1, 100), row("2026-03-04 09:01", "B", "buy", 1, 100),
                         row("2026-03-04 09:02", "C", "buy", 1, 100),
                         row("2026-03-04 09:05", "B", "sell", 1, 101), row("2026-03-04 09:09", "A", "sell", 1, 101)))
    assert [(t.symbol, t.closed) for t in out.trades] == [("B", True), ("A", True), ("C", False)]


def test_a_trade_held_overnight_is_not_same_day():
    out = match(fills_of(row("2026-03-04 15:00", "A", "buy", 1, 100), row("2026-03-05 09:05", "A", "sell", 1, 101)))
    assert out.trades[0].same_day is False and out.trades[0].holding_seconds == 18 * 3600 + 300


def test_holding_time_is_unknown_when_a_fill_has_no_time_of_day():
    """날짜만 있는 체결로 '보유 0초'를 만들면 초단타로 잘못 읽힌다."""
    out = match(fills_of(row("2026-03-04", "A", "buy", 1, 100), row("2026-03-04", "A", "sell", 1, 101)))
    t = out.trades[0]
    assert t.has_time is False and t.holding_seconds is None and t.same_day is True and t.gross == 1.0


def test_the_holding_time_of_a_scaled_trade_runs_from_first_entry_to_last_exit():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 1, 100), row("2026-03-04 09:10", "A", "buy", 1, 100),
                         row("2026-03-04 09:40", "A", "sell", 2, 101)))
    assert out.trades[0].holding_seconds == 40 * 60


def test_fractional_quantities_close_cleanly():
    out = match(fills_of(row("2026-03-04 09:00", "A", "buy", 0.1, 100), row("2026-03-04 09:01", "A", "buy", 0.2, 100),
                         row("2026-03-04 09:02", "A", "sell", 0.3, 110)))
    assert out.trades[0].closed is True and out.trades[0].gross == pytest.approx(3.0)
