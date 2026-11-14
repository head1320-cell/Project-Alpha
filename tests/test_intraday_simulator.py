"""분봉 시뮬레이터 — 손으로 계산한 하루들과 체결·손익이 일치한다 (분봉 백테스트 설계 §6 · W4b b4).

모든 시험의 봉은 손으로 만들었고, 기대값은 아래 계산에서 나온다(호가 단위 10원 · 슬리피지 1틱 · 진입 금액 1,000,000원):

    기본 하루(R0~R3) — 진입 규칙 "종가가 10,050 을 상향 돌파"
      09:00  시 10,000  고 10,020  저  9,990  종 10,000
      09:01  시 10,000  고 10,060  저 10,000  종 10,060   ← 종가가 10,050 을 넘었다(앞 봉 10,000) → 신호
      09:02  시 10,070  고 10,100  저 10,060  종 10,090   ← ★다음 봉 시가★ 10,070 + 1틱 = 10,080 에 매수 · 99주(997,920원)
      09:03  시 10,090  고 10,120  저 10,080  종 10,110   ← 마지막 봉 → 종가 10,110 − 1틱 = 10,100 에 강제 청산
      손익 = (10,100 − 10,080) × 99 = +1,980원

    손절 1% → 손절가 10,080 × 0.99 = 9,979.2 → 내림 9,970 · 익절 0.5% → 10,080 × 1.005 = 10,130.4 → 올림 10,140

지키는 것: ★신호 봉에서 체결하지 않는다 · 뒤의 봉을 바꿔도 앞의 체결이 같다 · 한 봉에 손절과 익절이 함께 걸리면 손절 먼저 ·
갭은 시가에 · 거래 없는 봉에는 체결이 없다 · 하루 한도는 종목을 가로지른다 · 모르는 것은 세어 둔다.★
"""
from __future__ import annotations

import numpy as np
import pytest

from src.engine import intraday
from src.engine.intraday import simulator as sim
from src.engine.intraday.simulator import CostAssumptions, Day, PositionRules, RuleSpec
from src.engine.intraday.types import PrevDay, Session

DATE = "2026-03-04"
RULES = {"available": True, "open": "0900", "closing_auction_from": "1520", "close": "1530"}


def C(x):
    return {"const": x}


def I(name, **params):                      # noqa: E743
    return {"ind": name, **params}


def op(name, *args, **extra):
    return {"op": name, "args": list(args), **extra}


ENTRY = op("cross_up", I("close"), C(10_050))
EXIT = op("cross_down", I("close"), C(10_060))
RULE = RuleSpec(entry=ENTRY)
POS = PositionRules(amount=1_000_000)
COST = CostAssumptions(commission_bp=None, slippage_ticks=1, participation_cap=None)

R0 = ("090000", 10_000, 10_020, 9_990, 10_000, 1_000)
R1 = ("090100", 10_000, 10_060, 10_000, 10_060, 1_000)
R2 = ("090200", 10_070, 10_100, 10_060, 10_090, 1_000)
R3 = ("090300", 10_090, 10_120, 10_080, 10_110, 1_000)
QUIET = [("090400", 10_100, 10_110, 10_090, 10_100, 1_000)]


def sess(rows, ticker="005930", date=DATE, prev=None, source="kis", market="KOSPI", instrument="stock") -> Session:
    t, o, h, low, c, v = zip(*rows)
    return Session(ticker, date, np.array(t), np.array(o, float), np.array(h, float), np.array(low, float),
                   np.array(c, float), np.array(v, float), source, prev, market, instrument, None)


def one_day(*sessions, **kw) -> list[Day]:
    return [Day(date=sessions[0].date if sessions else DATE, sessions={s.ticker: s for s in sessions}, **kw)]


def go(days, rule=RULE, position=POS, costs=COST, rules=RULES):
    return sim.simulate(days, rule, position, costs, rules=rules)


def trades(out):
    """(시각, 종목, 매수/매도, 수량, 단가) — 손 계산과 견주기 좋게."""
    return [(f["executed_at"][11:], f["symbol"], f["side"], f["quantity"], f["price"]) for f in out["fills"]]


def kinds(out):
    return [e["kind"] for e in out["events"]]


# ── 진입은 다음 봉 시가 · 장 끝 강제 청산 ───────────────────────────────────────────────
def test_the_signal_bar_does_not_fill_and_the_next_bar_opens_the_trade():
    out = go(one_day(sess([R0, R1, R2, R3])))
    assert trades(out) == [("09:02:00", "005930", "buy", 99, 10_080.0), ("09:03:00", "005930", "sell", 99, 10_100.0)]
    assert kinds(out) == ["entry_signal", "session_end"]
    assert out["counts"] == {"days": 1, "sessions": 1, "bars": 4, "entries": 1, "exits": 1}


def test_a_signal_on_the_last_bar_has_no_next_bar_to_fill_on():
    out = go(one_day(sess([R0, R1])))
    assert out["fills"] == [] and out["counts"]["entries"] == 0


def test_the_fill_rows_are_the_trade_journal_rows():
    row = go(one_day(sess([R0, R1, R2, R3])))["fills"][0]
    assert row == {"executed_at": "2026-03-04 09:02:00", "symbol": "005930", "side": "buy", "quantity": 99,
                   "price": 10_080.0, "market": "KOSPI", "instrument": "stock", "name": None}
    assert "fee" not in row and "tax" not in row            # 비용 금액을 싣지 않는다 — 실으면 일지가 '관측'으로 읽는다


# ── 손절 ─────────────────────────────────────────────────────────────────────────────
STOP = PositionRules(amount=1_000_000, stop_pct=1.0)


def test_a_stop_fills_at_the_stop_less_a_tick_when_the_bar_trades_down_to_it():
    rows = [R0, R1, ("090200", 10_070, 10_080, 10_040, 10_050, 1_000), ("090300", 10_050, 10_060, 9_960, 9_980, 1_000),
            ("090400", 9_980, 10_000, 9_970, 9_990, 1_000)]
    out = go(one_day(sess(rows)), position=STOP)
    assert trades(out)[1] == ("09:03:00", "005930", "sell", 99, 9_960.0)          # 9,970 − 1틱
    assert kinds(out) == ["entry_signal", "stop"]


def test_a_gap_below_the_stop_fills_at_the_open():
    rows = [R0, R1, ("090200", 10_070, 10_080, 10_040, 10_050, 1_000), ("090300", 9_900, 9_920, 9_880, 9_900, 1_000), *QUIET]
    out = go(one_day(sess(rows)), position=STOP)
    assert trades(out)[1] == ("09:03:00", "005930", "sell", 99, 9_890.0)          # 시가 9,900 − 1틱 (손절가 9,970 이 아니다)


def test_a_bar_that_stays_above_the_stop_does_not_stop_out():
    rows = [R0, R1, ("090200", 10_070, 10_080, 10_040, 10_050, 1_000), ("090300", 10_050, 10_060, 9_980, 9_990, 1_000)]
    out = go(one_day(sess(rows)), position=STOP)
    assert kinds(out) == ["entry_signal", "session_end"]


def test_the_entry_bar_itself_can_stop_out_because_the_entry_was_at_its_open():
    rows = [R0, R1, ("090200", 10_070, 10_080, 9_950, 9_960, 1_000), *QUIET]
    out = go(one_day(sess(rows)), position=STOP)
    assert trades(out) == [("09:02:00", "005930", "buy", 99, 10_080.0), ("09:02:00", "005930", "sell", 99, 9_960.0)]


# ── 익절 ─────────────────────────────────────────────────────────────────────────────
TARGET = PositionRules(amount=1_000_000, target_pct=0.5)


def test_a_target_needs_the_bar_to_trade_through_it():
    touch = ("090300", 10_090, 10_140, 10_080, 10_130, 1_000)                      # 닿기만 했다
    through = ("090400", 10_130, 10_150, 10_120, 10_140, 1_000)                    # 한 틱 넘었다
    out = go(one_day(sess([R0, R1, R2, touch, through, ("090500", 10_140, 10_150, 10_130, 10_140, 1_000)])), position=TARGET)
    assert trades(out)[1] == ("09:04:00", "005930", "sell", 99, 10_140.0)         # 지정가 — 슬리피지 없음
    assert kinds(out) == ["entry_signal", "target"]


def test_when_stop_and_target_are_both_hit_in_one_bar_the_stop_is_taken_and_counted():
    both = ("090300", 10_090, 10_160, 9_960, 10_000, 1_000)
    out = go(one_day(sess([R0, R1, R2, both, *QUIET])), position=PositionRules(amount=1_000_000, stop_pct=1.0, target_pct=0.5))
    assert trades(out)[1] == ("09:03:00", "005930", "sell", 99, 9_960.0) and kinds(out)[1] == "stop"
    assert out["assumptions"]["stop_and_target_same_bar"] == 1


# ── 규칙 청산 · 시간 청산 · 추적 손절 ───────────────────────────────────────────────────
def test_a_rule_exit_fills_at_the_next_open():
    rows = [R0, R1, R2, ("090300", 10_090, 10_095, 10_040, 10_050, 1_000), ("090400", 10_040, 10_050, 10_030, 10_045, 1_000),
            ("090500", 10_045, 10_050, 10_040, 10_045, 1_000)]
    out = go(one_day(sess(rows)), rule=RuleSpec(entry=ENTRY, exit=EXIT))
    assert trades(out)[1] == ("09:04:00", "005930", "sell", 99, 10_030.0)         # 시가 10,040 − 1틱
    assert kinds(out) == ["entry_signal", "rule_exit"]


def test_a_time_exit_sells_at_the_open_of_the_first_bar_at_or_after_that_time():
    out = go(one_day(sess([R0, R1, R2, R3, *QUIET])), position=PositionRules(amount=1_000_000, time_exit="0903"))
    assert trades(out)[1] == ("09:03:00", "005930", "sell", 99, 10_080.0)         # 시가 10,090 − 1틱
    assert kinds(out) == ["entry_signal", "time_exit"]


def test_a_trailing_stop_moves_only_with_bars_that_have_finished():
    """09:03 봉의 고가 10,200 으로 그 봉의 저가 10,135 를 자르면 안 된다 — 그 봉의 손절가는 앞 봉까지의 고가(10,100)로 정한 10,040 이다."""
    rows = [R0, R1, R2, ("090300", 10_090, 10_200, 10_135, 10_190, 1_000), ("090400", 10_190, 10_195, 10_130, 10_150, 1_000),
            ("090500", 10_150, 10_160, 10_140, 10_150, 1_000)]
    out = go(one_day(sess(rows)), position=PositionRules(amount=1_000_000, trail_pct=0.5))
    assert trades(out)[1] == ("09:04:00", "005930", "sell", 99, 10_130.0)         # 10,200 × 0.995 = 10,149 → 10,140 − 1틱
    assert kinds(out) == ["entry_signal", "trail"]


# ── 거래 없는 봉 · 참여율 상한 ──────────────────────────────────────────────────────────
def test_an_entry_does_not_fill_on_a_bar_without_trades_and_is_not_carried_over():
    out = go(one_day(sess([R0, R1, ("090200", 10_070, 10_070, 10_070, 10_070, 0), R3])))
    assert out["fills"] == [] and out["assumptions"]["entry_skipped_no_trades"] == 1


def test_an_exit_waits_for_the_next_bar_that_trades():
    rows = [R0, R1, R2, ("090300", 10_090, 10_095, 10_040, 10_050, 1_000), ("090400", 10_040, 10_040, 10_040, 10_040, 0),
            ("090500", 10_020, 10_030, 10_010, 10_020, 1_000), ("090600", 10_020, 10_030, 10_010, 10_020, 1_000)]
    out = go(one_day(sess(rows)), rule=RuleSpec(entry=ENTRY, exit=EXIT))
    assert trades(out)[1] == ("09:05:00", "005930", "sell", 99, 10_010.0)
    assert out["assumptions"]["exit_deferred_no_trades"] == 1 and kinds(out)[1] == "rule_exit"


def test_the_participation_cap_cuts_the_entry_and_spreads_the_exit_over_bars():
    rows = [R0, R1, ("090200", 10_070, 10_100, 10_060, 10_090, 500), ("090300", 10_090, 10_095, 10_040, 10_050, 1_000),
            ("090400", 10_040, 10_050, 10_030, 10_045, 300), ("090500", 10_020, 10_030, 10_010, 10_020, 1_000),
            ("090600", 10_020, 10_030, 10_010, 10_020, 1_000)]
    out = go(one_day(sess(rows)), rule=RuleSpec(entry=ENTRY, exit=EXIT), costs=CostAssumptions(None, 1, 0.1))
    assert trades(out) == [("09:02:00", "005930", "buy", 50, 10_080.0),            # 거래량 500 의 10% = 50주
                           ("09:04:00", "005930", "sell", 30, 10_030.0),           # 거래량 300 의 10% = 30주
                           ("09:05:00", "005930", "sell", 20, 10_010.0)]           # 나머지 20주는 다음 봉 시가 − 1틱
    assert kinds(out) == ["entry_signal", "rule_exit", "exit_remainder"]
    assert out["assumptions"]["entry_cut_by_participation"] == 1


def test_an_amount_too_small_for_one_share_is_skipped_and_counted():
    out = go(one_day(sess([R0, R1, R2, R3])), position=PositionRules(amount=5_000))
    assert out["fills"] == [] and out["assumptions"]["entry_skipped_amount_too_small"] == 1


# ── 미리 건 매수(변동성 돌파 꼴) ───────────────────────────────────────────────────────
LEVEL = op("add", I("day_open"), op("mul", C(0.5), op("sub", I("prev_high"), I("prev_low"))))
PREV = PrevDay(close=10_000.0, high=10_100.0, low=9_900.0, basis="minute")        # 범위 200 → 시가 + 100
B0 = ("090000", 10_000, 10_150, 9_990, 10_100, 1_000)
B1 = ("090100", 10_100, 10_120, 10_080, 10_090, 1_000)
B2 = ("090200", 10_090, 10_095, 10_070, 10_075, 1_000)
B3 = ("090300", 10_075, 10_080, 10_070, 10_075, 1_000)


def test_a_resting_buy_is_live_from_the_second_bar_and_fills_inside_the_bar():
    out = go(one_day(sess([B0, B1, B2, B3], prev=PREV)), rule=RuleSpec(entry_stop=LEVEL))
    # 첫 봉의 고가 10,150 이 10,100 을 넘지만 그 봉에서는 주문이 아직 없다(시가를 봐야 값이 정해진다)
    assert trades(out)[0] == ("09:01:00", "005930", "buy", 98, 10_110.0)          # max(10,100, 시가 10,100) + 1틱 · 990,780원
    assert kinds(out)[0] == "entry_stop"


def test_the_bar_a_resting_buy_filled_in_is_not_used_to_stop_it_out():
    """그 봉의 저가가 진입 앞인지 뒤인지 모른다 — 지어내지 않고 세어 둔다. 손절은 다음 봉부터 본다."""
    out = go(one_day(sess([B0, B1, B2, B3], prev=PREV)), rule=RuleSpec(entry_stop=LEVEL),
             position=PositionRules(amount=1_000_000, stop_pct=0.2))               # 손절가 10,110 × 0.998 → 10,080
    assert trades(out) == [("09:01:00", "005930", "buy", 98, 10_110.0), ("09:02:00", "005930", "sell", 98, 10_070.0)]
    assert out["assumptions"]["entry_bar_range_unknown"] == 1


def test_a_resting_buy_uses_the_level_known_before_the_bar_not_the_bar_s_own():
    """값이 봉마다 달라지는 주문 — "앞 봉 종가 + 30원". 09:01 봉의 주문가는 09:00 종가로 정한 10,030 이다(09:01 종가로 정한 10,065 가 아니다)."""
    rows = [("090000", 10_000, 10_010, 9_990, 10_000, 1_000), ("090100", 10_000, 10_040, 10_000, 10_035, 1_000),
            ("090200", 10_035, 10_040, 10_030, 10_035, 1_000)]
    out = go(one_day(sess(rows)), rule=RuleSpec(entry_stop=op("add", I("close"), C(30))))
    assert trades(out)[0] == ("09:01:00", "005930", "buy", 99, 10_040.0)          # max(10,030, 시가 10,000) + 1틱


def test_a_rule_that_needs_the_previous_day_skips_sessions_without_it():
    out = go(one_day(sess([B0, B1, B2, B3])), rule=RuleSpec(entry_stop=LEVEL))
    assert out["fills"] == [] and out["skipped"] == [{"date": DATE, "ticker": "005930", "reason": "no_previous_day"}]
    assert out["counts"]["sessions"] == 0


# ── 종목을 가로지르는 하루 한도 ────────────────────────────────────────────────────────
LOSER = [R0, R1, ("090200", 10_070, 10_080, 10_040, 10_050, 1_000), ("090300", 10_050, 10_060, 9_960, 9_980, 1_000),
         ("090400", 9_980, 10_000, 9_970, 9_990, 1_000)]                           # 09:03 에 −11,880원으로 손절
FLAT = [("090000", 10_000, 10_020, 9_990, 10_000, 1_000), ("090100", 10_000, 10_010, 9_990, 10_000, 1_000),
        ("090200", 10_000, 10_010, 9_990, 10_000, 1_000), ("090300", 10_000, 10_010, 9_990, 10_000, 1_000)]
LATER = [*FLAT, ("090400", 10_000, 10_060, 10_000, 10_060, 1_000), ("090500", 10_070, 10_100, 10_060, 10_090, 1_000),
         ("090600", 10_090, 10_120, 10_080, 10_110, 1_000)]                        # 09:04 신호 → 09:05 진입


def two(position):
    return go(one_day(sess(LOSER, ticker="000660"), sess(LATER, ticker="005930")), position=position)


def test_the_daily_loss_limit_stops_new_entries_in_every_ticker():
    out = two(PositionRules(amount=1_000_000, stop_pct=1.0, daily_loss_limit=10_000))
    assert [t[1] for t in trades(out)] == ["000660", "000660"]                     # 다른 종목의 손실이 이 종목의 진입을 막았다
    assert out["assumptions"]["entry_blocked_daily_loss"] == 1


def test_a_loss_exactly_at_the_limit_already_stops_entries():
    out = two(PositionRules(amount=1_000_000, stop_pct=1.0, daily_loss_limit=11_880))
    assert len(out["fills"]) == 2 and out["assumptions"]["entry_blocked_daily_loss"] == 1


def test_a_larger_limit_lets_the_other_ticker_enter():
    out = two(PositionRules(amount=1_000_000, stop_pct=1.0, daily_loss_limit=20_000))
    assert [t[1] for t in trades(out)] == ["000660", "000660", "005930", "005930"]
    assert "entry_blocked_daily_loss" not in out["assumptions"]


def test_the_cooldown_after_a_loss_blocks_entries_until_that_many_minutes_have_passed():
    blocked = two(PositionRules(amount=1_000_000, stop_pct=1.0, cooldown_after_loss_min=3))    # 09:03 손실 → 09:06 부터
    allowed = two(PositionRules(amount=1_000_000, stop_pct=1.0, cooldown_after_loss_min=2))    # 09:05 는 꼭 2분 뒤
    assert len(blocked["fills"]) == 2 and blocked["assumptions"]["entry_blocked_cooldown"] == 1
    assert len(allowed["fills"]) == 4


def test_the_open_position_limit_counts_across_tickers_in_ticker_order():
    same = [R0, R1, R2, R3]
    out = go(one_day(sess(same, ticker="005930"), sess(same, ticker="000660")),
             position=PositionRules(amount=1_000_000, max_open_positions=1))
    assert {t[1] for t in trades(out)} == {"000660"} and out["assumptions"]["entry_blocked_max_open"] == 1
    free = go(one_day(sess(same, ticker="005930"), sess(same, ticker="000660")))
    assert {t[1] for t in trades(free)} == {"000660", "005930"}


TWICE = [R0, R1, R2, ("090300", 10_090, 10_095, 10_040, 10_040, 1_000), ("090400", 10_040, 10_050, 10_030, 10_040, 1_000),
         ("090500", 10_040, 10_080, 10_040, 10_070, 1_000), ("090600", 10_080, 10_100, 10_070, 10_090, 1_000),
         ("090700", 10_090, 10_100, 10_080, 10_100, 1_000)]


def test_one_entry_per_ticker_per_day_unless_more_are_allowed():
    rule = RuleSpec(entry=ENTRY, exit=EXIT)
    once = go(one_day(sess(TWICE)), rule=rule)
    assert len(once["fills"]) == 2 and once["assumptions"]["entry_blocked_max_entries"] == 1
    twice = go(one_day(sess(TWICE)), rule=rule, position=PositionRules(amount=1_000_000, max_entries_per_ticker=2))
    assert trades(twice) == [("09:02:00", "005930", "buy", 99, 10_080.0), ("09:04:00", "005930", "sell", 99, 10_030.0),
                             ("09:06:00", "005930", "buy", 99, 10_090.0), ("09:07:00", "005930", "sell", 99, 10_090.0)]


# ── 진입 시각 ─────────────────────────────────────────────────────────────────────────
LATE = [("151800", 10_000, 10_020, 9_990, 10_000, 1_000), ("151900", 10_000, 10_060, 10_000, 10_060, 1_000),
        ("152000", 10_070, 10_100, 10_060, 10_090, 1_000), ("152100", 10_090, 10_120, 10_080, 10_110, 1_000)]


def test_no_new_entry_from_the_closing_auction_onward():
    out = go(one_day(sess(LATE)))
    assert out["fills"] == [] and out["assumptions"]["entry_blocked_time"] == 1


def test_without_session_rules_the_cutoff_is_not_applied_and_that_is_counted():
    out = go(one_day(sess(LATE)), rules=None)
    assert len(out["fills"]) == 2 and out["assumptions"]["no_closing_auction_cutoff"] == 1


def test_an_explicit_entry_window_is_respected():
    assert go(one_day(sess([R0, R1, R2, R3])), position=PositionRules(amount=1_000_000, entry_from="0905"))["fills"] == []
    assert go(one_day(sess([R0, R1, R2, R3])), position=PositionRules(amount=1_000_000, entry_until="0902"))["fills"] == []
    assert len(go(one_day(sess([R0, R1, R2, R3])), position=PositionRules(amount=1_000_000, entry_until="0903"))["fills"]) == 2


# ── 건너뜀 · 출처 ─────────────────────────────────────────────────────────────────────
def test_a_day_with_shifted_hours_is_skipped_with_a_reason():
    out = go([Day(DATE, {"005930": sess([R0, R1, R2, R3])}, shifted=True)])
    assert out["fills"] == [] and out["skipped"] == [{"date": DATE, "ticker": "005930", "reason": "session_shifted"}]


def test_what_the_feed_skipped_is_passed_on_and_sessions_are_counted_by_source():
    days = [Day(DATE, {"005930": sess([R0, R1, R2, R3], source="synthetic"), "000660": sess([R0, R1, R2, R3], ticker="000660")},
                skipped=(("035720", "no_bars"),))]
    out = go(days)
    assert {"date": DATE, "ticker": "035720", "reason": "no_bars"} in out["skipped"]
    assert out["sources"] == {"kis": 1, "synthetic": 1, "unknown": 0}


def test_days_are_independent_and_nothing_is_held_overnight():
    d1 = Day("2026-03-04", {"005930": sess([R0, R1, R2, R3], date="2026-03-04")})
    d2 = Day("2026-03-05", {"005930": sess([R0, R1, R2, R3], date="2026-03-05")})
    out = go([d1, d2])
    assert [f["executed_at"][:10] for f in out["fills"]] == ["2026-03-04", "2026-03-04", "2026-03-05", "2026-03-05"]
    assert [f["side"] for f in out["fills"]] == ["buy", "sell", "buy", "sell"]


def test_a_day_s_limits_do_not_leak_into_the_next_day():
    # 판정(표본외 · 워크포워드)은 체결 줄을 날짜로 잘라 쓴다 — 하루씩 따로 돌린 것과 같아야 그 자르기가 옳다.
    pos = PositionRules(amount=1_000_000, stop_pct=1.0, daily_loss_limit=10_000, cooldown_after_loss_min=30)

    def day(date):
        return Day(date, {"000660": sess(LOSER, ticker="000660", date=date), "005930": sess(LATER, date=date)})
    both = go([day("2026-03-04"), day("2026-03-05")], position=pos)
    alone = go([day("2026-03-04")], position=pos)["fills"] + go([day("2026-03-05")], position=pos)["fills"]
    assert both["fills"] == alone and len(alone) == 4               # 이튿날에도 첫 종목은 다시 들어간다


def test_the_days_that_actually_ran_are_listed():
    ran = Day("2026-03-04", {"005930": sess([R0, R1, R2, R3], date="2026-03-04")})
    shifted = Day("2026-03-05", {"005930": sess([R0, R1, R2, R3], date="2026-03-05")}, shifted=True)
    nothing = Day("2026-03-06", {}, skipped=(("005930", "no_bars"),))
    quiet = Day("2026-03-09", {"005930": sess(FLAT, date="2026-03-09")})        # 돌았지만 거래가 없다 — 그래도 하루다
    out = go([ran, shifted, nothing, quiet])
    assert out["dates"] == ["2026-03-04", "2026-03-09"] and out["counts"]["days"] == 2
    assert intraday.run([ran, shifted, nothing, quiet], RULE, POS, COST, rules=RULES)["dates"] == out["dates"]


def test_the_order_of_the_ticker_dict_does_not_change_the_result():
    a, b = sess([R0, R1, R2, R3], ticker="000660"), sess([R0, R1, R2, R3], ticker="005930")
    pos = PositionRules(amount=1_000_000, max_open_positions=1)
    one = go([Day(DATE, {"000660": a, "005930": b})], position=pos)
    other = go([Day(DATE, {"005930": b, "000660": a})], position=pos)
    assert one["fills"] == other["fills"]


# ── 검증 ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kwargs, code", [
    ({"rule": RuleSpec()}, "no_entry"),
    ({"rule": RuleSpec(entry=I("close"))}, "entry_not_a_condition"),
    ({"rule": RuleSpec(entry_stop=ENTRY)}, "entry_stop_not_a_price"),
    ({"rule": RuleSpec(entry=ENTRY, exit=I("close"))}, "exit_not_a_condition"),
    ({"rule": RuleSpec(entry=op("gt", I("macd"), C(1)))}, "unknown_indicator"),
    ({"position": PositionRules(amount=0)}, "bad_amount"),
    ({"position": PositionRules(amount=1_000_000, stop_pct=0)}, "bad_percent"),
    ({"position": PositionRules(amount=1_000_000, trail_pct=100)}, "bad_percent"),
    ({"position": PositionRules(amount=1_000_000, time_exit="9시")}, "bad_time"),
    ({"position": PositionRules(amount=1_000_000, max_entries_per_ticker=0)}, "bad_count"),
    ({"position": PositionRules(amount=1_000_000, daily_loss_limit=-1)}, "bad_amount"),
    ({"position": PositionRules(amount=1_000_000, cooldown_after_loss_min=0)}, "bad_count"),
    ({"costs": CostAssumptions(None, -1, None)}, "bad_slippage"),
    ({"costs": CostAssumptions(None, 1, 0.0)}, "bad_participation"),
    ({"costs": CostAssumptions(None, 1, 1.5)}, "bad_participation"),
])
def test_a_malformed_setting_is_refused_with_a_reason(kwargs, code):
    with pytest.raises(sim.SimError) as err:
        go(one_day(sess([R0, R1, R2, R3])), **kwargs)
    assert err.value.code == code


def test_every_counter_and_reason_has_a_sentence():
    for table in (sim.ASSUMPTIONS, sim.SKIP_REASONS):
        assert all(text.endswith("니다.") and "—" not in text and "–" not in text for text in table.values())
    out = go(one_day(sess(LATE)), rules=None)
    assert set(out["assumptions"]) <= set(sim.ASSUMPTIONS)
    assert {"no_previous_day", "session_shifted"} <= set(sim.SKIP_REASONS)


# ── 성질: 앞보기 0 ─────────────────────────────────────────────────────────────────────
def _random_session(seed: int, ticker: str, n: int = 80) -> Session:
    rng = np.random.default_rng(seed)
    close = 10_000 + np.cumsum(rng.integers(-6, 7, n)) * 10.0
    open_ = np.concatenate([[close[0]], close[:-1]]) + rng.integers(-2, 3, n) * 10.0
    high = np.maximum(open_, close) + rng.integers(0, 4, n) * 10.0
    low = np.minimum(open_, close) - rng.integers(0, 4, n) * 10.0
    volume = rng.integers(50, 3_000, n).astype(float)
    volume[rng.integers(0, n, 6)] = 0.0
    time = np.array([f"{(540 + m) // 60:02d}{(540 + m) % 60:02d}00" for m in range(n)])
    return Session(ticker, DATE, time, open_, high, low, close, volume, "kis", PrevDay(10_000.0, 10_150.0, 9_900.0, "minute"),
                   "KOSPI", "stock", None)


def _cut(s: Session, k: int) -> Session:
    return Session(s.ticker, s.date, s.time[:k], s.open[:k], s.high[:k], s.low[:k], s.close[:k], s.volume[:k], s.source,
                   s.prev, s.market, s.instrument, s.name)


def _poison(s: Session, k: int) -> Session:
    def bad(a, v):
        out = a.copy()
        out[k:] = v
        return out
    return Session(s.ticker, s.date, s.time, bad(s.open, 1_000.0), bad(s.high, 99_000.0), bad(s.low, 500.0), bad(s.close, 60_000.0),
                   bad(s.volume, 9e9), s.source, s.prev, s.market, s.instrument, s.name)


SETUPS = [
    (RuleSpec(entry=op("cross_up", I("close"), I("sma", n=5)), exit=op("cross_down", I("close"), I("sma", n=5))),
     PositionRules(amount=1_000_000, stop_pct=0.3, target_pct=0.5, max_entries_per_ticker=5)),
    (RuleSpec(entry=op("and", op("gt", I("close"), I("or_high", minutes=10)), op("gt", I("volume"), I("vol_avg", bars=5)))),
     PositionRules(amount=2_000_000, trail_pct=0.4, max_entries_per_ticker=3, cooldown_after_loss_min=5, daily_loss_limit=30_000)),
    (RuleSpec(entry_stop=op("add", I("day_open"), op("mul", C(0.1), op("sub", I("prev_high"), I("prev_low"))))),
     PositionRules(amount=1_000_000, stop_pct=0.4, time_exit="1000", max_open_positions=1)),
    (RuleSpec(entry=op("cross_up", I("rsi", n=5), C(30)), exit=op("gt", I("rsi", n=5), C(70))),
     PositionRules(amount=500_000, max_entries_per_ticker=4)),
]


@pytest.mark.parametrize("setup", range(len(SETUPS)))
def test_changing_later_bars_never_changes_earlier_fills(setup):
    rule, position = SETUPS[setup]
    costs = CostAssumptions(None, 1, 0.2)
    total = 0
    for seed in range(5):
        a, b = _random_session(seed, "000660"), _random_session(seed + 100, "005930")
        full = go(one_day(a, b), rule=rule, position=position, costs=costs)["fills"]
        total += len(full)
        for k in (5, 17, 33, 52, 71):
            edge = f"{DATE} {a.time[k][:2]}:{a.time[k][2:4]}:00"
            before = [f for f in full if f["executed_at"] < edge]
            last = f"{DATE} {a.time[k - 1][:2]}:{a.time[k - 1][2:4]}:00"
            cut = go(one_day(_cut(a, k), _cut(b, k)), rule=rule, position=position, costs=costs)["fills"]
            # 잘린 하루는 마지막 봉(k−1)에서 강제 청산한다 — 그 봉의 체결은 견주지 않는다
            assert [f for f in cut if f["executed_at"] < last] == [f for f in before if f["executed_at"] < last], (seed, k, "지움")
            poisoned = go(one_day(_poison(a, k), _poison(b, k)), rule=rule, position=position, costs=costs)["fills"]
            assert [f for f in poisoned if f["executed_at"] < edge] == before, (seed, k, "바꿈")
    assert total > 0, "이 설정은 체결을 하나도 내지 않았다 — 공허한 성질 시험이다"


# ── 일지 엔진으로 넘어간다 ─────────────────────────────────────────────────────────────
def test_the_journal_of_a_simulated_run_lists_what_the_simulator_does_not_model_not_what_a_file_lacks():
    """일지 엔진의 목록은 '올린 파일'의 이야기다(파일에 없는 체결 …). 모의 체결에는 파일이 없다 — 그 문장이 그대로 나가면 거짓이다."""
    from src.engine.trade_journal import NOT_COVERED, analyze
    out = intraday.run(one_day(sess([R0, R1, R2, R3])), RULE, POS, COST, rules=RULES)
    listed = out["journal"]["not_covered"]
    assert listed == list(intraday.NOT_MODELED) and len(listed) >= 6 and len(set(listed)) == len(listed)
    text = " ".join(listed)
    assert "파일" not in text and "미청산" not in text            # 일지 전용 문장이 섞이지 않는다
    for word in ("호가", "시장 충격", "공매도", "하루를 넘기는", "수익률(%)", "기업행위", "선물", "세후"):
        assert word in text, word
    # 짝: 일지 엔진 자신의 목록은 그대로다(실거래 분석 화면은 달라지지 않는다).
    assert analyze(out["fills"], COST.journal_options())["not_covered"] == list(NOT_COVERED)
    assert any("파일" in s for s in NOT_COVERED)


def test_run_hands_the_fills_to_the_trade_journal_and_reports_the_same_gross():
    out = intraday.run(one_day(sess([R0, R1, R2, R3])), RULE, POS, COST, rules=RULES)
    assert out["journal"]["summary"]["gross"]["total"] == 1_980
    assert out["journal"]["summary"]["net"] is None                              # 수수료율을 모른다 — 0 으로 치지 않는다
    assert out["journal"]["inputs"]["fills"] == 2 and out["journal"]["rejects"]["count"] == 0
    assert set(out) >= {"fills", "events", "journal", "origin", "assumptions", "skipped", "counts"}


def test_with_a_commission_rate_the_same_trade_is_a_loss_after_costs():
    """매수 997,920 · 매도 999,900 · 수수료 10bp 씩 997.92 + 999.90 · 매도세 20bp(2026 코스피 주식) 1,999.80
       → 1,980 − 997.92 − 999.90 − 1,999.80 = −2,017.62원"""
    out = intraday.run(one_day(sess([R0, R1, R2, R3])), RULE, POS, CostAssumptions(10, 1, None), rules=RULES)
    assert out["journal"]["summary"]["net"]["total"] == pytest.approx(-2_017.62, abs=0.01)
    basis = out["journal"]["basis"]
    assert basis["fee"] == {"observed": 0, "assumed": 2, "unknown": 0}            # 요율로 계산한 값이다 — 관측이 아니다
    assert basis["tax"]["inferred"] == 1 and basis["tax"]["observed"] == 0 and basis["tax"]["not_applicable"] == 1


def test_an_unknown_market_keeps_the_net_unknown_even_with_a_commission_rate():
    out = intraday.run(one_day(sess([R0, R1, R2, R3], market=None, instrument=None)), RULE, POS,
                       CostAssumptions(10, 1, None), rules=RULES)
    assert out["journal"]["summary"]["gross"]["total"] == 1_980 and out["journal"]["summary"]["net"] is None


def test_a_declared_market_assumption_gives_a_net_and_is_marked_as_an_assumption():
    days = one_day(sess([R0, R1, R2, R3], market=None, instrument=None))
    blind = intraday.run(days, RULE, POS, CostAssumptions(commission_bp=1.5, participation_cap=None), rules=RULES)
    assumed = intraday.run(days, RULE, POS, CostAssumptions(commission_bp=1.5, participation_cap=None, unknown_market="KOSPI",
                                                           unknown_instrument="stock"), rules=RULES)
    assert blind["journal"]["summary"]["net"] is None
    # 매수 997,920 · 매도 999,900 → 수수료 1.5bp 299.67 · 매도세 20bp 1,999.80 → 1,980 − 2,299.47 = −319.47
    assert assumed["journal"]["summary"]["net"]["total"] == pytest.approx(-319.47, abs=0.01)
    assert assumed["journal"]["basis"]["unknown_market"] == "KOSPI" and assumed["journal"]["basis"]["tax"]["assumed"] == 1
    assert assumed["fills"] == blind["fills"]                                    # 가정은 계산만 바꾼다 — 체결은 같다


@pytest.mark.parametrize("sources, grade", [(("kis", "kis"), "E3"), (("kis", "synthetic"), "E0"), (("kis", "unknown"), None),
                                            (("synthetic", "unknown"), "E0")])
def test_the_origin_grade_is_set_by_the_weakest_source(sources, grade):
    days = one_day(sess([R0, R1, R2, R3], ticker="000660", source=sources[0]), sess([R0, R1, R2, R3], source=sources[1]))
    origin = intraday.run(days, RULE, POS, COST, rules=RULES)["origin"]
    assert origin["kind"] == "simulated" and origin["grade"] == grade
    assert origin["grade_reason"].endswith("니다.")


def test_etf_fills_are_counted_because_the_tick_table_is_the_stock_one():
    out = go(one_day(sess([R0, R1, R2, R3], instrument="etf")))
    assert out["assumptions"]["etf_uses_stock_tick_table"] == 2
    assert "etf_uses_stock_tick_table" not in go(one_day(sess([R0, R1, R2, R3])))["assumptions"]
