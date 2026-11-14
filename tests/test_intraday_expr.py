"""표현식 나무 — 지표와 상수를 비교·돌파·논리로 엮어 봉마다 참/거짓(또는 수)을 낸다 (분봉 백테스트 설계 §7.1 · W4b b2).

규칙 틀 일곱은 이 나무를 만드는 함수일 뿐이고 시뮬레이터는 나무만 본다. 여기서 거는 것:
- 연산마다 참/거짓의 짝 · ★모르는 값(NaN)이 낀 판단은 참이 되지 않는다★ — `아님`을 씌워도 참이 되지 않는다.
- 검증은 어긋난 나무를 사유와 함께 거절한다(조용히 거짓으로 평가하지 않는다).
- 앞보기 0 — 뒤의 봉을 지우거나 바꿔도 앞의 판단이 같다.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.engine.intraday import expr
from src.engine.intraday.types import PrevDay, Session


def session(close, *, volume=None, time=None, prev=None) -> Session:
    close = np.array(close, float)
    n = len(close)
    time = np.array(time or [f"09{m:02d}00" for m in range(n)])
    return Session("005930", "2026-03-04", time, close.copy(), close + 1, close - 1, close,
                   np.array(volume if volume is not None else [10] * n, float), "kis", prev)


def C(x):
    return {"const": x}


def I(name, **params):                     # noqa: E743 — 지표 잎
    return {"ind": name, **params}


def op(name, *args, **extra):
    return {"op": name, "args": list(args), **extra}


S = session([100, 101, 103, 102, 99, 104])


def bools(tree, s=S):
    return [bool(x) for x in expr.evaluate(tree, s)]


# ── 비교 ─────────────────────────────────────────────────────────────────────────────
def test_comparisons_have_both_outcomes():
    assert bools(op("gt", I("close"), C(101))) == [False, False, True, True, False, True]
    assert bools(op("ge", I("close"), C(101))) == [False, True, True, True, False, True]
    assert bools(op("lt", I("close"), C(101))) == [True, False, False, False, True, False]
    assert bools(op("le", I("close"), C(101))) == [True, True, False, False, True, False]


def test_a_comparison_with_an_unknown_value_is_not_true():
    tree = op("gt", I("close"), I("sma", n=3))             # 처음 두 봉은 평균이 없다
    assert bools(tree)[:2] == [False, False]
    assert bools(op("lt", I("close"), I("sma", n=3)))[:2] == [False, False]


def test_negating_an_unknown_does_not_make_it_true():
    """★`아님`으로 미상을 참으로 뒤집을 수 없다★ — 덥혀지지 않은 지표가 진입 신호를 내는 길을 막는다."""
    known = op("not", op("gt", I("close"), C(101)))
    unknown = op("not", op("gt", I("close"), I("sma", n=3)))
    assert bools(known) == [True, True, False, False, True, False]
    assert bools(unknown)[:2] == [False, False]
    assert bools(unknown)[2:] == [not x for x in bools(op("gt", I("close"), I("sma", n=3)))[2:]]


# ── 돌파 ─────────────────────────────────────────────────────────────────────────────
def test_cross_up_needs_the_bar_before_at_or_below_and_this_bar_above():
    #  종가 100 101 103 102  99 104  ·  기준 101
    assert bools(op("cross_up", I("close"), C(101))) == [False, False, True, False, False, True]
    assert bools(op("cross_down", I("close"), C(101))) == [False, False, False, False, True, False]


def test_touching_the_line_is_not_a_cross():
    s = session([100, 101, 101, 102])
    assert bools(op("cross_up", I("close"), C(101)), s) == [False, False, False, True]


def test_the_first_bar_never_crosses():
    assert bools(op("cross_up", I("close"), C(1)))[0] is False


# ── 논리 ─────────────────────────────────────────────────────────────────────────────
def test_and_or_combine_bar_by_bar():
    a, b = op("gt", I("close"), C(100)), op("lt", I("close"), C(103))
    assert bools(op("and", a, b)) == [False, True, False, True, False, False]
    assert bools(op("or", a, b)) == [True, True, True, True, True, True]


def test_an_unknown_side_decides_nothing_but_a_known_side_can_decide_alone():
    """세 값 논리 — 모름은 참도 거짓도 아니다. 그러나 ★아는 쪽만으로 답이 정해지면★ 모름이 그 답을 흐리지 않는다:
    '또는'은 한쪽이 참이면 참이고, '그리고'는 한쪽이 거짓이면 거짓이다."""
    unknown = op("gt", I("close"), I("sma", n=3))          # 처음 두 봉은 모름
    true, false = op("gt", I("close"), C(0)), op("lt", I("close"), C(0))
    assert bools(op("and", true, unknown))[:2] == [False, False]            # 참 그리고 모름 → 모름 → 참이 아니다
    assert bools(op("or", false, unknown))[:2] == [False, False]            # 거짓 또는 모름 → 모름 → 참이 아니다
    assert bools(op("or", true, unknown))[:2] == [True, True]               # 참 또는 모름 → 참
    assert bools(op("not", op("and", false, unknown)))[:2] == [True, True]  # 거짓 그리고 모름 → 거짓 → 아님 → 참
    assert bools(op("not", op("and", true, unknown)))[:2] == [False, False]  # 모름의 아님은 모름
    assert bools(op("not", op("or", false, unknown)))[:2] == [False, False]


def test_held_before_looks_at_the_bars_before_and_not_at_this_one():
    below = op("lt", I("close"), C(103))                   # 참 참 거짓 참 참 거짓
    assert bools(op("held_before", below, bars=2)) == [False, False, True, False, False, True]
    assert bools(op("held_before", below, bars=1)) == [False, True, True, False, True, True]


def test_time_between_is_inclusive_on_the_bar_label():
    s = session([1, 2, 3, 4], time=["085900", "090000", "093000", "093100"])
    assert bools({"op": "time_between", "from": "0900", "to": "0930"}, s) == [False, True, True, False]


# ── 수 ───────────────────────────────────────────────────────────────────────────────
def test_arithmetic_builds_a_price_level():
    s = session([100, 101, 102], prev=PrevDay(close=98.0, high=104.0, low=96.0, basis="daily"))
    level = op("add", I("day_open"), op("mul", C(0.5), op("sub", I("prev_high"), I("prev_low"))))
    assert list(expr.evaluate(level, s)) == [104.0, 104.0, 104.0]            # 100 + 0.5 × (104 − 96)


def test_arithmetic_with_an_unknown_stays_unknown():
    level = op("add", I("day_open"), I("prev_high"))
    assert all(math.isnan(x) for x in expr.evaluate(level, S))


def test_where_gives_the_value_only_while_the_condition_holds():
    tree = op("where", {"op": "time_between", "from": "0901", "to": "0903"}, I("close"))
    got = expr.evaluate(tree, S)
    assert math.isnan(got[0]) and list(got[1:4]) == [101.0, 103.0, 102.0] and math.isnan(got[4])


# ── 검증 ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tree, code", [
    ("close", "not_a_node"),
    ({"op": "xor", "args": [C(1), C(2)]}, "unknown_op"),
    ({"ind": "macd"}, "unknown_indicator"),
    ({"ind": "sma", "n": 0}, "param_out_of_range"),
    (op("gt", I("close")), "wrong_arity"),
    (op("and", op("gt", I("close"), C(1))), "wrong_arity"),
    (op("gt", op("gt", I("close"), C(1)), C(1)), "wrong_kind"),          # 참/거짓을 수와 견줌
    (op("and", I("close"), C(1)), "wrong_kind"),                         # 수를 논리로 엮음
    (op("where", I("close"), I("close")), "wrong_kind"),
    (C(float("nan")), "bad_const"),
    (C("100"), "bad_const"),
    (C(True), "bad_const"),
    ({"op": "time_between", "from": "9시", "to": "0930"}, "bad_time"),
    ({"op": "time_between", "from": "0930", "to": "0900"}, "bad_time"),
    (op("held_before", op("gt", I("close"), C(1)), bars=0), "bad_bars"),
    ({"ind": "close", "const": 1}, "not_a_node"),
])
def test_a_malformed_tree_is_refused_with_a_reason(tree, code):
    with pytest.raises(expr.ExprError) as err:
        expr.validate(tree)
    assert err.value.code == code


def test_validate_says_what_kind_of_value_the_tree_gives():
    assert expr.validate(op("gt", I("close"), C(1))) == "bool"
    assert expr.validate(op("add", I("close"), C(1))) == "number"
    assert expr.validate({"op": "time_between", "from": "0900", "to": "0930"}) == "bool"


def test_a_tree_that_is_too_deep_or_too_large_is_refused():
    deep = op("gt", I("close"), C(1))
    for _ in range(expr.MAX_DEPTH):
        deep = op("not", deep)
    with pytest.raises(expr.ExprError) as err:
        expr.validate(deep)
    assert err.value.code == "too_deep"
    wide = op("and", *[op("gt", I("close"), C(i)) for i in range(expr.MAX_NODES)])
    with pytest.raises(expr.ExprError) as err:
        expr.validate(wide)
    assert err.value.code == "too_many_nodes"


def test_evaluate_refuses_what_validate_refuses():
    with pytest.raises(expr.ExprError):
        expr.evaluate(op("and", I("close"), C(1)), S)


def test_uses_prev_finds_previous_day_indicators_anywhere_in_the_tree():
    assert expr.uses_prev(op("gt", I("close"), op("mul", I("prev_close"), C(1.02)))) is True
    assert expr.uses_prev(op("gt", I("close"), I("vwap"))) is False


def test_canonical_text_does_not_depend_on_key_order():
    a = {"op": "gt", "args": [{"ind": "sma", "n": 5}, {"const": 1}]}
    b = {"args": [{"n": 5, "ind": "sma"}, {"const": 1}], "op": "gt"}
    assert expr.canonical(a) == expr.canonical(b)
    assert expr.canonical(a) != expr.canonical(op("gt", I("sma", n=6), C(1)))


# ── 성질: 앞보기 0 ─────────────────────────────────────────────────────────────────────
TREES = [
    op("cross_up", I("close"), I("vwap")),
    op("and", op("cross_up", I("close"), I("vwap")), op("held_before", op("lt", I("close"), I("vwap")), bars=3)),
    op("and", op("gt", I("close"), I("or_high", minutes=5)), op("gt", I("volume"), op("mul", C(2), I("vol_avg", bars=5)))),
    op("or", op("cross_down", I("rsi", n=5), C(70)), op("not", op("ge", I("close"), I("bb_lower", n=5, k=2.0)))),
    op("where", {"op": "time_between", "from": "0905", "to": "0950"}, op("add", I("day_open"), op("mul", C(0.5), op("sub", I("prev_high"), I("prev_low"))))),
    op("cross_up", I("close"), I("highest_close", bars=4)),
]


def _random_session(seed: int, n: int = 50) -> Session:
    rng = np.random.default_rng(seed)
    close = 10_000 + np.cumsum(rng.integers(-30, 31, n)) * 10.0
    volume = rng.integers(0, 500, n).astype(float)
    s = session(list(close), volume=list(volume), prev=PrevDay(9_990.0, 10_100.0, 9_900.0, "minute"))
    return s


def _cut(s: Session, k: int) -> Session:
    return Session(s.ticker, s.date, s.time[:k], s.open[:k], s.high[:k], s.low[:k], s.close[:k], s.volume[:k], s.source, s.prev)


def _poison(s: Session, k: int) -> Session:
    def bad(a, v):
        out = a.copy()
        out[k:] = v
        return out
    return Session(s.ticker, s.date, s.time, bad(s.open, 1.0), bad(s.high, 9e9), bad(s.low, 1e-9), bad(s.close, 5e8),
                   bad(s.volume, 7e12), s.source, s.prev)


@pytest.mark.parametrize("tree", TREES, ids=range(len(TREES)))
def test_no_tree_looks_ahead(tree):
    for seed in range(4):
        full_session = _random_session(seed)
        full = expr.evaluate(tree, full_session)
        for k in (1, 2, 9, 21, 37, 49):
            assert np.array_equal(expr.evaluate(tree, _cut(full_session, k)), full[:k], equal_nan=True), (seed, k, "지움")
            assert np.array_equal(expr.evaluate(tree, _poison(full_session, k))[:k], full[:k], equal_nan=True), (seed, k, "바꿈")


def test_the_trees_in_the_property_test_do_fire_somewhere():
    """공허한 성질 시험이 아님을 보인다 — 나무마다 참(또는 값)이 실제로 나오는 봉이 있다."""
    for i, tree in enumerate(TREES):
        hits = 0
        for seed in range(4):
            out = expr.evaluate(tree, _random_session(seed))
            hits += int(np.count_nonzero(out if out.dtype == bool else ~np.isnan(out)))
        assert hits > 0, i


def test_a_cross_is_unknown_when_the_bar_before_it_is_unknown():
    """돌파는 앞 봉과 이 봉을 함께 본다 — 앞 봉의 값을 모르면 '돌파하지 않았다'가 아니라 ★모른다★. 그래야 '아님'이 참이 되지 않는다."""
    s = session([10, 11, 12, 30, 5, 40])
    cross = op("cross_up", I("close"), I("sma", n=3))               # 이동평균은 셋째 봉부터 있다 → 셋째 봉의 앞 봉은 모름
    assert bools(cross, s)[:3] == [False, False, False]
    assert bools(op("not", cross), s)[:4] == [False, False, False, True]     # 셋째 봉: 모름의 아님은 모름 · 넷째 봉부터 안다
    down = op("cross_down", I("close"), I("sma", n=3))
    assert bools(op("not", down), s)[:3] == [False, False, False]
