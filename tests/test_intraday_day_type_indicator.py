"""지표 '하루 유형' — 직접 구성의 조건이 하루 유형 모형을 쓴다 (구현 계획 2026-11-16 §6 · T2).

지표 `day_type_is(model, type)` 는 ★세션 자신의 첫 N 봉★으로 그날의 유형을 센다(`day_types.window` · `assign` 그대로):
창의 마지막 봉부터 1(그 유형) 또는 0, 그 앞 봉은 미상(NaN), 창이 어긋난 날은 하루 내내 미상이다.
모형의 중심은 규칙 맥락(`Session.context`)으로 온다 — 문 층이 내 모형을 읽어 싣는다. 맥락이 없으면 ★명시적으로 실패★한다
(미상으로 두면 그 조건을 쓴 규칙이 조용히 거래 0 이 된다).

★증거의 등급★: 손으로 만든 하루와 무작위 하루로 장치의 성질(인과 · 미상 · 실패)을 본다(`structural`). 유형이 돈이 된다는 말이 아니다.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from src.engine.intraday import Day, Session, expr, rules, stepper
from src.engine.intraday import day_types as dt
from src.engine.intraday import indicators as ind
from src.engine.intraday.simulator import CostAssumptions, PositionRules, RuleSpec, simulate
from src.engine.intraday.types import DayTypeRef, RuleContext

UP = [10.0, 20.0, 30.0, 40.0, 50.0]
DOWN = [-10.0, -20.0, -30.0, -40.0, -50.0]
VEE = [-10.0, -20.0, -30.0, -20.0, -10.0]
HAT = [10.0, 20.0, 30.0, 20.0, 10.0]
KEY = "1a2b3c4d" + "0" * 56
OTHER = "f" * 64


def clock(start: str, n: int) -> list[str]:
    h, m = int(start[:2]), int(start[2:4])
    return [f"{(h * 60 + m + i) // 60:02d}{(h * 60 + m + i) % 60:02d}00" for i in range(n)]


def model(paths=(UP, DOWN, VEE, HAT)) -> DayTypeRef:
    """심은 네 경로를 중심으로 — 번호는 학습과 같은 법(끝값 오름차순): 1 DOWN · 2 VEE · 3 HAT · 4 UP."""
    centroids = dt.order_centroids(np.asarray(paths, dtype=float))
    return DayTypeRef(centroids=centroids, minutes=centroids.shape[1], k=centroids.shape[0])


def context(**refs: DayTypeRef) -> RuleContext:
    return RuleContext(day_types={KEY: model(), **{k: v for k, v in refs.items()}})


def bp_session(path, *, extra=(), times=None, open0=10_000.0, ctx: RuleContext | None = None, date="2026-07-01") -> Session:
    """bp 경로(창) + 그 뒤의 bp 들 → 첫 봉 시가 10,000 의 1분 봉. 10bp = 10원."""
    closes = np.asarray([open0 + p for p in [*path, *extra]], dtype=float)
    n = len(closes)
    t = np.asarray(times if times is not None else clock("090000", n))
    opens = np.concatenate([[open0], closes[:-1]])
    return Session("005930", date, t, opens, np.maximum(opens, closes) + 5, np.minimum(opens, closes) - 5, closes,
                   np.full(n, 1_000.0), "kis", context=ctx)


def same(a, b) -> bool:
    return np.array_equal(np.asarray(a, float), np.asarray(b, float), equal_nan=True)


NAN = float("nan")


# ── 값 ───────────────────────────────────────────────────────────────────────────────
def test_the_type_is_unknown_inside_the_window_and_known_from_its_last_bar():
    """손 계산: HAT 을 따른 창(5분) 뒤에 봉 다섯 — 창의 마지막 봉(다섯째)부터 유형 3 이고, 앞 네 봉은 미상이다."""
    s = bp_session(HAT, extra=[0, 5, -5, 10, 30], ctx=context())
    assert same(ind.compute(s, "day_type_is", {"model": KEY, "type": 3}), [NAN] * 4 + [1.0] * 6)
    for other in (1, 2, 4):                                                 # 다른 유형 번호는 같은 봉부터 0
        assert same(ind.compute(s, "day_type_is", {"model": KEY, "type": other}), [NAN] * 4 + [0.0] * 6)


def test_every_planted_path_lands_on_its_own_number():
    for path, number in ((DOWN, 1), (VEE, 2), (HAT, 3), (UP, 4)):
        s = bp_session(path, extra=[0], ctx=context())
        assert ind.compute(s, "day_type_is", {"model": KEY, "type": number})[-1] == 1.0, number


def test_the_bars_after_the_window_never_change_the_type():
    """창 뒤의 봉이 어떻게 움직여도 유형은 창의 다섯 봉으로만 정해진다(그날 전체 경로로 다시 세지 않는다)."""
    calm = bp_session(HAT, extra=[0] * 5, ctx=context())
    wild = bp_session(HAT, extra=[400, -400, 900, -900, 2_000], ctx=context())
    assert same(ind.compute(calm, "day_type_is", {"model": KEY, "type": 3}), ind.compute(wild, "day_type_is", {"model": KEY, "type": 3}))


def test_equal_distance_goes_to_the_smaller_number():
    """두 중심(유형 2 · 3)에서 같은 거리 — 학습의 배정과 같은 법으로 작은 번호."""
    a, b = [0.0, 0.0, 0.0, 0.0, 0.0], [10.0, 10.0, 10.0, 10.0, 10.0]
    ref = DayTypeRef(centroids=dt.order_centroids(np.asarray([a, b], dtype=float)), minutes=5, k=2)
    s = bp_session([5.0] * 5, ctx=RuleContext(day_types={KEY: ref}))
    assert ind.compute(s, "day_type_is", {"model": KEY, "type": 1})[-1] == 1.0
    assert ind.compute(s, "day_type_is", {"model": KEY, "type": 2})[-1] == 0.0


def test_a_broken_window_leaves_the_whole_day_unknown_but_a_gap_after_it_does_not():
    gap_inside = clock("090000", 6)
    del gap_inside[2]                                                       # 09:02 가 빠졌다 — 창 안
    s = bp_session(HAT, extra=[0], times=gap_inside, ctx=context())
    assert np.isnan(ind.compute(s, "day_type_is", {"model": KEY, "type": 3})).all()
    gap_after = [*clock("090000", 5), "091000", "091100"]                  # 창 뒤의 빈 분은 상관없다(짝)
    s2 = bp_session(HAT, extra=[0, 0], times=gap_after, ctx=context())
    assert same(ind.compute(s2, "day_type_is", {"model": KEY, "type": 3}), [NAN] * 4 + [1.0] * 3)
    bad_price = bp_session([10.0, 20.0, -10_000.0, 20.0, 10.0], extra=[0], ctx=context())   # 창 안의 종가 0
    assert np.isnan(ind.compute(bad_price, "day_type_is", {"model": KEY, "type": 3})).all()
    short = bp_session(HAT[:3], ctx=context())                              # 봉이 창보다 적다
    assert np.isnan(ind.compute(short, "day_type_is", {"model": KEY, "type": 3})).all()


def test_the_window_starts_at_the_first_bar_not_at_nine():
    s = bp_session(HAT, extra=[0], times=clock("091300", 6), ctx=context())
    assert same(ind.compute(s, "day_type_is", {"model": KEY, "type": 3}), [NAN] * 4 + [1.0] * 2)


def test_a_cut_session_gives_the_first_part_of_the_full_answer():
    """앞보기 0 — 봉 L 개까지 자른 세션의 값은 전체 값의 앞 L 개와 같다(무작위 하루 · 무작위 모형 · 모든 L)."""
    rng = np.random.default_rng(7)
    for trial in range(6):
        minutes = int(rng.integers(5, 12))
        paths = rng.normal(0, 40, size=(int(rng.integers(2, 6)), minutes))
        ref = DayTypeRef(centroids=dt.order_centroids(paths), minutes=minutes, k=len(paths))
        ctx = RuleContext(day_types={KEY: ref})
        walk = np.round(rng.normal(0, 30, size=minutes + 15)).cumsum()
        full_s = bp_session(walk[:minutes], extra=walk[minutes:], ctx=ctx)
        for number in range(1, ref.k + 1):
            full = ind.compute(full_s, "day_type_is", {"model": KEY, "type": number})
            assert not np.isnan(full[minutes - 1:]).any(), (trial, number)      # 공허하지 않다 — 창 뒤에는 값이 있다
            for cut in range(1, len(full) + 1):
                part = dataclasses.replace(full_s, **{f: getattr(full_s, f)[:cut] for f in ("time", "open", "high", "low", "close", "volume")})
                assert same(ind.compute(part, "day_type_is", {"model": KEY, "type": number}), full[:cut]), (trial, number, cut)


def test_exactly_one_number_is_true_on_every_known_bar():
    s = bp_session(VEE, extra=[3, 1, 4], ctx=context())
    flags = np.vstack([ind.compute(s, "day_type_is", {"model": KEY, "type": n}) for n in (1, 2, 3, 4)])
    assert (flags[:, 4:].sum(axis=0) == 1).all() and np.isnan(flags[:, :4]).all()


# ── 맥락 — 없으면 명시적 실패 ─────────────────────────────────────────────────────────────
def test_without_a_context_the_indicator_fails_instead_of_staying_unknown():
    s = bp_session(HAT, extra=[0])
    with pytest.raises(ind.IndicatorError) as err:
        ind.compute(s, "day_type_is", {"model": KEY, "type": 3})
    assert err.value.code == "rule_context_missing"
    other = bp_session(HAT, extra=[0], ctx=RuleContext(day_types={OTHER: model()}))      # 맥락은 있으나 그 모형이 없다
    with pytest.raises(ind.IndicatorError) as err2:
        ind.compute(other, "day_type_is", {"model": KEY, "type": 3})
    assert err2.value.code == "rule_context_missing"


def test_other_indicators_need_no_context():
    """짝 — 맥락은 이 지표만의 일이다. 다른 지표는 맥락 없이 그대로 돈다(기존 경로 불변)."""
    s = bp_session(HAT, extra=[0])
    assert len(ind.compute(s, "close")) == 6 and len(ind.compute(s, "or_high", {"minutes": 3})) == 6


def test_a_number_above_the_models_type_count_is_refused():
    s = bp_session(HAT, extra=[0], ctx=context())
    with pytest.raises(ind.IndicatorError) as err:
        ind.compute(s, "day_type_is", {"model": KEY, "type": 5})                      # 모형의 유형은 넷
    assert err.value.code == "day_type_out_of_range"


# ── 매개변수 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [None, 7, "", "A" * 64, "a" * 63, "g" * 64, KEY + "0"])
def test_the_model_key_must_be_64_lowercase_hex(bad):
    with pytest.raises(ind.IndicatorError) as err:
        ind.resolve("day_type_is", {"model": bad, "type": 1})
    assert err.value.code == "bad_model_key"


def test_a_missing_model_key_is_refused_not_defaulted():
    with pytest.raises(ind.IndicatorError) as err:
        ind.resolve("day_type_is", {"type": 1})
    assert err.value.code == "bad_model_key"


@pytest.mark.parametrize("number, code", [(0, "param_out_of_range"), (17, "param_out_of_range"), (2.5, "param_not_integer"),
                                          ("3", "param_not_integer"), (True, "param_not_integer")])
def test_the_type_number_is_an_integer_from_1_to_16(number, code):
    with pytest.raises(ind.IndicatorError) as err:
        ind.resolve("day_type_is", {"model": KEY, "type": number})
    assert err.value.code == code


def test_resolve_keeps_the_key_as_given_and_the_number_as_an_integer():
    assert ind.resolve("day_type_is", {"model": KEY, "type": 3.0}) == {"model": KEY, "type": 3}
    assert expr.validate({"op": "gt", "args": [{"ind": "day_type_is", "model": KEY, "type": 2}, {"const": 0.5}]}) == "bool"


# ── 나무 · 시뮬레이터 · 걸음 엔진 ──────────────────────────────────────────────────────────
ENTRY = {"op": "gt", "args": [{"ind": "day_type_is", "model": KEY, "type": 3}, {"const": 0.5}]}
POS = PositionRules(amount=1_000_000)
COSTS = CostAssumptions(commission_bp=1.5)


def test_the_rule_enters_only_on_the_day_of_that_type_after_the_window():
    """손 계산: HAT 의 날은 창의 마지막 봉(09:04)에서 조건이 서고 다음 봉(09:05) 시가에 산다 · UP 의 날은 사지 않는다."""
    ctx = context()
    hat = bp_session(HAT, extra=[0, 10, 20], ctx=ctx, date="2026-07-01")
    up = bp_session(UP, extra=[0, 10, 20], ctx=ctx, date="2026-07-02")
    out = simulate([Day("2026-07-01", {"005930": hat}), Day("2026-07-02", {"005930": up})], RuleSpec(entry=ENTRY), POS, COSTS)
    buys = [f for f in out["fills"] if f["side"] == "buy"]
    assert [f["executed_at"] for f in buys] == ["2026-07-01 09:05:00"]


def test_the_stepper_keeps_the_context_and_matches_the_whole_day():
    """걸음마다 낸 체결의 이어 붙임 = 그 하루를 한 번에 돌린 체결(맥락을 잃으면 걸음 엔진이 실패한다)."""
    s = bp_session(HAT, extra=[0, 10, 20, -10], ctx=context())
    day = Day("2026-07-01", {"005930": s})
    whole = simulate([day], RuleSpec(entry=ENTRY), POS, COSTS)["fills"]
    walker = stepper.Stepper(day, RuleSpec(entry=ENTRY), POS, COSTS)
    got = []
    for label in s.time:
        got.extend(walker.step(str(label)))
    got.extend(walker.finish())
    assert got == whole and any(f["side"] == "buy" for f in whole)


def test_the_cut_session_in_the_stepper_carries_the_same_context_object():
    s = bp_session(HAT, extra=[0], ctx=context())
    assert stepper._upto(s, "090200").context is s.context


# ── 글 · 주석 · 문법 표 ────────────────────────────────────────────────────────────────
def test_the_rule_text_names_the_type_and_the_model():
    assert rules.text_of(RuleSpec(entry=ENTRY)) == "진입 조건: 하루 유형 3번(모형 1a2b3c4d) > 0.5"


def test_the_notes_speak_of_the_window_only_when_the_rule_uses_a_day_type():
    with_it = rules.notes_of(RuleSpec(entry=ENTRY))
    without = rules.notes_of(RuleSpec(entry={"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]}))
    note = rules.DAY_TYPE_NOTE
    assert note in with_it and note not in without


def test_the_grammar_offers_a_model_field_and_a_type_number():
    found = next(i for i in rules.grammar()["indicators"] if i["name"] == "day_type_is")
    assert found["label"] == "하루 유형" and found["unit"] == "flag" and found["context"] == "day_types"
    assert found["params"] == [{"key": "model", "label": "모형", "type": "model", "kind": "day_type"},
                               {"key": "type", "label": "유형 번호", "type": "int", "min": 1, "max": dt.MAX_K, "default": 1, "unit": "번"}]
    others = [i for i in rules.grammar()["indicators"] if i["name"] not in ("day_type_is", "regime_prob")]
    assert all(i["context"] is None for i in others)                                  # 짝 — 다른 지표는 맥락이 필요 없다
    assert next(i for i in rules.grammar()["indicators"] if i["name"] == "regime_prob")["context"] == "regimes"   # K3 — 시장 국면은 제 칸
