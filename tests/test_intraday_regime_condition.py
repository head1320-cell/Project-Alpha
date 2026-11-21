"""지표 '시장 국면 확률' — 직접 구성의 진입 조건이 시장 국면(일)을 쓴다 (구현 계획 2026-11-16 §7.4 · K3).

지표 `regime_prob(index, k, state)` 는 ★그날 시가 전에 알던★ 소속 확률(전 거래일 종가까지 · K1)을 규칙 맥락(`Session.context.regimes`)에서
읽어 그날의 모든 봉에 같은 값으로 낸다. 그날 값이 없으면 하루 내내 미상(NaN)이고, 맥락에 그 국면이 없으면 ★명시적으로 실패★한다
(T2 와 같은 장치 — 미상으로 두면 그 조건을 쓴 규칙이 조용히 거래 0 이 된다).

국면 조건의 꼴 — 국면을 뺀 판(짝 비교)이 하나로 정해지게: 국면 조건 = 초과 · 이상 · 미만 · 이하 비교이고 양변이 국면 확률 · 상수 · 그 둘의
더하기 · 빼기 · 곱하기로만 된 것. 진입 조건에만 · 뿌리이거나 '모두 충족'만 거쳐 닿는 자리에만 둔다.

★증거의 등급★: 손으로 만든 날과 무작위 날로 장치의 성질(그날 값 · 미상 · 실패 · 짝 판)을 본다(`structural`). 국면 조건이 돈이 된다는 말이 아니다.
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from src.engine.intraday import Day, Session, expr, rules, stepper
from src.engine.intraday import indicators as ind
from src.engine.intraday.simulator import CostAssumptions, PositionRules, RuleSpec, simulate
from src.engine.intraday.types import RegimeRef, RuleContext

NAN = float("nan")
POS = PositionRules(amount=1_000_000)
COSTS = CostAssumptions(commission_bp=1.5)


def R(state: int = 1, k: int = 2, index: str = "KOSPI") -> dict:
    return {"ind": "regime_prob", "index": index, "k": k, "state": state}


def C(value: float) -> dict:
    return {"const": value}


def ind_node(name: str, **params) -> dict:
    return {"ind": name, **params}


def op(name: str, *args: dict, **extra) -> dict:
    return {"op": name, "args": list(args), **extra}


def regime(probs: dict, index: str = "KOSPI", k: int = 2) -> RegimeRef:
    return RegimeRef(index=index, k=k, probs=probs)


def context(*refs: RegimeRef) -> RuleContext:
    return RuleContext(regimes={(r.index, r.k): r for r in refs})


def clock(n: int) -> list[str]:
    return [f"{(540 + i) // 60:02d}{(540 + i) % 60:02d}00" for i in range(n)]


def session(date: str, ctx: RuleContext | None, closes=(10_010.0, 10_020.0, 10_030.0, 10_040.0), ticker: str = "005930") -> Session:
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[10_000.0], c[:-1]])
    return Session(ticker, date, np.asarray(clock(len(c))), o, np.maximum(o, c) + 5, np.minimum(o, c) - 5, c,
                   np.full(len(c), 1_000.0), "kis", market="KOSPI", instrument="stock", context=ctx)


def same(a, b) -> bool:
    return np.array_equal(np.asarray(a, float), np.asarray(b, float), equal_nan=True)


# ── 값 — 그날의 확률 · 하루 내내 · 미상 · 실패 ─────────────────────────────────────────────────
def test_the_value_is_that_days_probability_on_every_bar():
    s = session("2026-07-01", context(regime({"2026-07-01": (0.8, 0.2)})))
    assert same(ind.compute(s, "regime_prob", {"index": "KOSPI", "k": 2, "state": 1}), [0.8] * 4)
    assert same(ind.compute(s, "regime_prob", {"index": "KOSPI", "k": 2, "state": 2}), [0.2] * 4)   # 짝 — 번호를 따라간다


def test_the_first_bar_already_has_the_value_because_it_was_known_before_the_open():
    s = session("2026-07-01", context(regime({"2026-07-01": (0.7, 0.3)})), closes=(10_010.0,))
    assert same(ind.compute(s, "regime_prob", {"index": "KOSPI", "k": 2, "state": 1}), [0.7])


def test_a_day_without_a_probability_is_unknown_all_day_not_zero_nor_even():
    ctx = context(regime({"2026-07-01": (0.3, 0.7), "2026-07-02": None}))
    for date in ("2026-07-02", "2026-07-03"):                      # 값이 없는 날 · 지수에 없는 날
        s = session(date, ctx)
        assert same(ind.compute(s, "regime_prob", {"index": "KOSPI", "k": 2, "state": 1}), [NAN] * 4)
        below = op("lt", R(1), C(0.9))                             # 0 이나 0.5 로 채우면 '미만'이 선다 — 서지 않아야 한다
        assert not expr.evaluate(below, s).any()
    known = session("2026-07-01", ctx)
    assert expr.evaluate(op("lt", R(1), C(0.9)), known).all()      # 짝 — 아는 날은 선다


def test_without_a_context_or_without_that_regime_the_indicator_fails():
    params = {"index": "KOSPI", "k": 2, "state": 1}
    for ctx in (None, RuleContext(), context(regime({"2026-07-01": (0.5, 0.3, 0.2)}, k=3)),
                context(regime({"2026-07-01": (0.5, 0.5)}, index="KOSDAQ"))):
        with pytest.raises(ind.IndicatorError) as err:
            ind.compute(session("2026-07-01", ctx), "regime_prob", params)
        assert err.value.code == "rule_context_missing"
    ok = context(regime({"2026-07-01": (0.5, 0.5)}))
    assert same(ind.compute(session("2026-07-01", ok), "regime_prob", params), [0.5] * 4)   # 짝


def test_other_indicators_still_need_no_context():
    assert same(ind.compute(session("2026-07-01", None), "close"), [10_010.0, 10_020.0, 10_030.0, 10_040.0])


# ── 매개변수 — 고르기(지수) · 기본값 없는 수(국면 수 · 번호) ─────────────────────────────────────
def test_resolve_keeps_the_index_and_makes_the_numbers_integers():
    assert ind.resolve("regime_prob", {"index": "KOSDAQ", "k": 4.0, "state": 3}) == {"index": "KOSDAQ", "k": 4, "state": 3}


@pytest.mark.parametrize("missing", ["index", "k", "state"])
def test_index_number_of_states_and_state_have_no_default(missing):
    given = {"index": "KOSPI", "k": 3, "state": 2}
    for params in ({k: v for k, v in given.items() if k != missing}, {**given, missing: None}):
        with pytest.raises(ind.IndicatorError) as err:
            ind.resolve("regime_prob", params)
        assert err.value.code == "param_missing"


def test_a_null_for_a_parameter_that_has_a_default_is_still_not_an_integer():
    """짝 — 기본값이 있는 지표의 `null` 은 지금처럼 거절한다(기본값으로 메우지도, 사유를 바꾸지도 않는다)."""
    with pytest.raises(ind.IndicatorError) as err:
        ind.resolve("sma", {"n": None})
    assert err.value.code == "param_not_integer"
    assert ind.resolve("sma", {}) == {"n": 20}


@pytest.mark.parametrize("bad", ["KOSPI200", "kospi", "", 1, "코스피"])
def test_the_index_is_one_of_the_two(bad):
    with pytest.raises(ind.IndicatorError) as err:
        ind.resolve("regime_prob", {"index": bad, "k": 2, "state": 1})
    assert err.value.code == "bad_choice"


@pytest.mark.parametrize(("k", "state", "code"), [(1, 1, "param_out_of_range"), (5, 1, "param_out_of_range"),
                                                   (2, 0, "param_out_of_range"), (2.5, 1, "param_not_integer"),
                                                   (2, 3, "regime_state_out_of_range"), (3, 4, "regime_state_out_of_range")])
def test_the_number_of_states_is_2_to_4_and_the_state_cannot_exceed_it(k, state, code):
    with pytest.raises(ind.IndicatorError) as err:
        ind.resolve("regime_prob", {"index": "KOSPI", "k": k, "state": state})
    assert err.value.code == code


def test_the_last_state_of_each_count_is_accepted():
    for k in (2, 3, 4):
        assert ind.resolve("regime_prob", {"index": "KOSPI", "k": k, "state": k})["state"] == k    # 짝 — 번호 = 국면 수는 된다


def test_the_ranges_are_the_market_regime_ones_and_the_indexes_the_doors_ones():
    from src.api.intraday_market_regime_routes import INDEXES
    from src.engine import market_regime as mr
    spec = ind.INDICATORS["regime_prob"]
    assert (spec.params["k"].low, spec.params["k"].high) == mr.K_RANGE
    assert (spec.params["state"].low, spec.params["state"].high) == (1, mr.K_RANGE[1])
    assert dict(spec.params["index"].choices) == INDEXES


# ── 글 · 주석 · 문법 표 ─────────────────────────────────────────────────────────────────────
def test_the_rule_text_names_the_index_the_state_and_the_number_of_states():
    spec = RuleSpec(entry=op("and", op("gt", R(2, 3), C(0.6)), op("gt", ind_node("close"), ind_node("vwap"))))
    assert rules.text_of(spec) == "진입 조건: 코스피 국면 2 확률(국면 3개) > 0.6 그리고 종가 > VWAP"
    kosdaq = RuleSpec(entry=op("le", R(1, 4, "KOSDAQ"), C(0.25)))
    assert rules.text_of(kosdaq) == "진입 조건: 코스닥 국면 1 확률(국면 4개) ≤ 0.25"


def test_the_notes_speak_of_the_regime_only_when_used_and_of_the_stop_only_with_one():
    used = RuleSpec(entry=op("gt", R(), C(0.6)))
    plain = RuleSpec(entry=op("gt", ind_node("close"), ind_node("vwap")))
    stopped = RuleSpec(entry=op("gt", R(), C(0.6)), entry_stop=ind_node("or_high", minutes=5))
    assert rules.REGIME_NOTE in rules.notes_of(used) and rules.REGIME_NOTE not in rules.notes_of(plain)
    assert rules.REGIME_STOP_NOTE in rules.notes_of(stopped) and rules.REGIME_STOP_NOTE not in rules.notes_of(used)
    assert all("—" not in n and "–" not in n for n in (rules.REGIME_NOTE, rules.REGIME_STOP_NOTE))


def test_the_grammar_offers_a_pick_and_two_numbers_without_defaults_in_the_entry_slot_only():
    g = rules.grammar()
    found = next(i for i in g["indicators"] if i["name"] == "regime_prob")
    assert (found["label"], found["unit"], found["context"], found["slots"]) == ("시장 국면 확률", "prob", "regimes", ["entry"])
    assert found["params"] == [
        {"key": "index", "label": "지수", "type": "pick", "default": None,
         "choices": [{"value": "KOSPI", "label": "코스피"}, {"value": "KOSDAQ", "label": "코스닥"}]},
        {"key": "k", "label": "국면 수", "type": "int", "min": 2, "max": 4, "default": None, "unit": "개"},
        {"key": "state", "label": "국면 번호", "type": "int", "min": 1, "max": 4, "default": None, "unit": "번"},
    ]
    assert g["units"]["prob"] == "확률(0~1)"
    assert all(i["slots"] is None for i in g["indicators"] if i["name"] != "regime_prob")       # 짝 — 다른 지표는 어느 자리에나


# ── 국면 조건의 꼴 ────────────────────────────────────────────────────────────────────────────
ABOVE = op("gt", ind_node("close"), ind_node("vwap"))
BELOW = op("lt", ind_node("close"), ind_node("sma", n=5))


def refused(params: dict) -> rules.RuleError:
    with pytest.raises(rules.RuleError) as err:
        rules.resolve("custom", params)
    return err.value


@pytest.mark.parametrize(("slot", "tree"), [
    ("exit", op("gt", R(), C(0.6))),
    ("exit", op("and", ABOVE, op("lt", R(), C(0.3)))),
    ("entry_stop", op("where", op("gt", R(), C(0.6)), ind_node("or_high", minutes=5))),
    ("entry_stop", op("mul", R(), ind_node("close"))),
])
def test_the_regime_is_for_the_entry_condition_only(slot, tree):
    params = {slot: tree} if slot == "entry_stop" else {"entry": ABOVE, slot: tree}
    err = refused(params)
    assert (err.code, err.slot) == ("regime_outside_entry", slot)


@pytest.mark.parametrize("entry", [
    op("or", op("gt", R(), C(0.6)), ABOVE),
    op("not", op("gt", R(), C(0.6))),
    op("held_before", op("gt", R(), C(0.6)), bars=2),
    op("and", op("or", op("gt", R(), C(0.6)), ABOVE), BELOW),
    op("and", ABOVE, op("not", op("lt", R(), C(0.3)))),
])
def test_a_regime_condition_must_hang_from_the_entry_root_through_and_only(entry):
    err = refused({"entry": entry})
    assert (err.code, err.slot) == ("regime_not_in_and", "entry")


@pytest.mark.parametrize("entry", [
    op("cross_up", R(), C(0.6)),
    op("cross_down", C(0.6), R()),
    op("gt", R(), ind_node("close")),
    op("gt", op("add", R(), ind_node("rsi")), C(0.6)),
    op("gt", {"op": "ago", "bars": 1, "args": [R()]}, C(0.6)),
    op("gt", op("where", ABOVE, R()), C(0.6)),
    op("and", ABOVE, op("cross_up", R(1), R(2))),
])
def test_a_regime_condition_compares_only_regime_probabilities_and_constants(entry):
    err = refused({"entry": entry})
    assert (err.code, err.slot) == ("regime_not_plain", "entry")


@pytest.mark.parametrize("entry", [
    op("gt", R(), C(0.6)),
    op("lt", C(0.3), R(2)),
    op("ge", op("add", R(1, 3), R(2, 3)), C(0.7)),
    op("gt", R(1), R(2)),
    op("le", op("mul", R(), C(2.0)), op("sub", C(1.0), R(2))),
    op("and", ABOVE, op("gt", R(), C(0.6))),
    op("and", op("and", op("gt", R(), C(0.6)), ABOVE), op("or", ABOVE, BELOW)),
    op("and", op("gt", R(1, 2), C(0.6)), op("lt", R(2, 3, "KOSDAQ"), C(0.4)), BELOW),
])
def test_the_accepted_shapes(entry):
    """짝 — 위 거절들의 이웃은 받아들인다(늘 거절하는 검사가 아니다)."""
    out = rules.resolve("custom", {"entry": entry, "exit": BELOW})
    assert out["entry"] == rules.resolve("custom", {"entry": entry})["entry"]


def test_a_rule_without_a_regime_is_untouched_by_the_shape_checks():
    tree = op("or", op("not", ABOVE), op("held_before", BELOW, bars=3))
    assert rules.resolve("custom", {"entry": tree, "exit": op("cross_up", ind_node("close"), ind_node("sma", n=5))})


# ── 국면 조건을 뺀 판 ─────────────────────────────────────────────────────────────────────────
G1 = op("gt", R(), C(0.6))
G2 = op("lt", R(2, 3, "KOSDAQ"), C(0.4))


def built(**trees) -> RuleSpec:
    return rules.build("custom", trees)


@pytest.mark.parametrize(("entry", "left"), [
    (op("and", G1, ABOVE), ABOVE),
    (op("and", ABOVE, G1, BELOW), op("and", ABOVE, BELOW)),
    (op("and", op("and", G1, ABOVE), BELOW), op("and", ABOVE, BELOW)),
    (op("and", op("and", G1, G2), op("or", ABOVE, BELOW)), op("or", ABOVE, BELOW)),
    (op("and", G1, G2, ABOVE), ABOVE),
])
def test_without_the_regime_the_and_chain_keeps_the_rest(entry, left):
    spec = built(entry=entry, exit=BELOW)
    bare = rules.without_regime(spec)
    assert bare is not None and bare.entry == rules.build("custom", {"entry": left}).entry
    assert bare.exit == spec.exit and bare.entry_stop is None
    assert not rules.uses_regime(bare) and rules.uses_regime(spec)


def test_without_the_regime_a_rule_made_only_of_it_is_none_unless_a_stop_is_left():
    assert rules.without_regime(built(entry=G1)) is None
    assert rules.without_regime(built(entry=op("and", G1, G2), exit=ABOVE)) is None
    stop = ind_node("or_high", minutes=5)
    bare = rules.without_regime(built(entry=G1, entry_stop=stop))
    assert bare is not None and bare.entry is None and bare.entry_stop == built(entry=G1, entry_stop=stop).entry_stop


def test_without_the_regime_twice_is_the_same_and_the_regimes_used_are_listed():
    spec = built(entry=op("and", op("and", G1, ABOVE), G2, BELOW))
    once = rules.without_regime(spec)
    assert once is not None and rules.without_regime(once) == once          # 국면 조건이 없는 판은 그대로다
    assert rules.regime_uses(spec) == {("KOSPI", 2): {1}, ("KOSDAQ", 3): {2}}
    assert rules.regime_uses(built(entry=ABOVE)) == {}


# ── 손 계산 — 확률이 문턱을 넘는 날에만 진입한다 ─────────────────────────────────────────────────
DAYS = ("2026-07-01", "2026-07-02", "2026-07-03")


def three_days(probs: dict) -> list[Day]:
    ctx = context(regime(probs))
    return [Day(d, {"005930": session(d, ctx)}) for d in DAYS]


def buys(out: dict) -> list[str]:
    return [f["executed_at"] for f in out["fills"] if f["side"] == "buy"]


def test_the_rule_enters_only_on_the_day_whose_probability_is_above_the_threshold():
    """사흘(국면 1 확률 0.8 · 0.3 · 모름)에 '국면 1 > 0.6 그리고 종가 > 0' → 첫날만 첫 봉 종가에 서고 다음 봉(09:01) 시가에 산다.
    국면 조건을 뺀 판은 사흘 모두 산다(모르는 날도 국면 조건이 없으니 선다)."""
    days = three_days({"2026-07-01": (0.8, 0.2), "2026-07-02": (0.3, 0.7), "2026-07-03": None})
    spec = built(entry=op("and", G1, op("gt", ind_node("close"), C(0))))
    assert buys(simulate(days, spec, POS, COSTS)) == ["2026-07-01 09:01:00"]
    bare = rules.without_regime(spec)
    assert bare is not None
    assert buys(simulate(days, bare, POS, COSTS)) == [f"{d} 09:01:00" for d in DAYS]


def test_a_probability_equal_to_the_threshold_is_not_above_it_but_is_at_least_it():
    days = three_days({"2026-07-01": (0.6, 0.4), "2026-07-02": (0.59, 0.41), "2026-07-03": (0.61, 0.39)})
    up = op("gt", ind_node("close"), C(0))
    over = built(entry=op("and", op("gt", R(), C(0.6)), up))
    at_least = built(entry=op("and", op("ge", R(), C(0.6)), up))
    assert buys(simulate(days, over, POS, COSTS)) == ["2026-07-03 09:01:00"]
    assert buys(simulate(days, at_least, POS, COSTS)) == ["2026-07-01 09:01:00", "2026-07-03 09:01:00"]


def _random_session(rng: np.random.Generator, date: str, ticker: str, ctx: RuleContext) -> Session:
    n = 40
    close = 10_000 + np.cumsum(rng.integers(-3, 4, n)) * 10.0
    open_ = np.concatenate([[10_000.0], close[:-1]])
    high = np.maximum(open_, close) + rng.integers(0, 3, n) * 10.0
    low = np.minimum(open_, close) - rng.integers(0, 3, n) * 10.0
    return Session(ticker, date, np.asarray(clock(n)), open_, high, low, close, rng.integers(1, 500, n).astype(float), "kis",
                   market="KOSPI", instrument="stock", context=ctx)


def test_with_the_regime_the_fills_are_the_bare_rules_fills_on_the_days_the_condition_held():
    """성질 — 하루 상태는 날마다 새로 짓고 국면은 하루 내내 같다 → 넣은 판의 체결 = 뺀 판의 체결 가운데 조건이 선 날의 것.
    (미리 건 매수 가격이 없을 때 — 미리 건 매수는 진입 조건과 따로 체결된다)."""
    orb = rules.build("opening_range_breakout", {"minutes": 2}).entry
    checked, extra = 0, 0
    for seed in range(6):
        rng = np.random.default_rng(seed)
        dates = [f"2026-07-{d:02d}" for d in range(1, 13)]
        probs = {d: (None if rng.random() < 0.2 else (lambda p: (p, 1.0 - p))(float(rng.random()))) for d in dates}
        ctx = context(regime(probs))
        days = [Day(d, {t: _random_session(rng, d, t, ctx) for t in ("005930", "000660")}) for d in dates]
        spec = built(entry=op("and", orb, op("gt", R(), C(0.5))))
        with_it = simulate(days, spec, POS, COSTS)["fills"]
        bare = simulate(days, rules.without_regime(spec), POS, COSTS)["fills"]
        held = {d for d, p in probs.items() if p is not None and p[0] > 0.5}
        assert with_it == [f for f in bare if f["executed_at"][:10] in held], seed
        checked += len(with_it)
        extra += len(bare) - len(with_it)
    assert checked > 0 and extra > 0                                         # 공허하지 않다 — 넣은 판도 샀고 뺀 판은 더 샀다


def test_the_stepper_carries_the_regime_and_matches_the_whole_day():
    ctx = context(regime({"2026-07-01": (0.9, 0.1)}))
    s = session("2026-07-01", ctx, closes=(10_010.0, 10_020.0, 10_030.0, 10_020.0, 10_040.0))
    day = Day("2026-07-01", {"005930": s})
    spec = built(entry=op("and", G1, op("gt", ind_node("close"), C(0))))
    whole = simulate([day], spec, POS, COSTS)["fills"]
    walker = stepper.Stepper(day, spec, POS, COSTS)
    got = []
    for label in s.time:
        got.extend(walker.step(str(label)))
    got.extend(walker.finish())
    assert got == whole and any(f["side"] == "buy" for f in whole)
    assert stepper._upto(s, "090200").context is s.context


def test_random_regime_trees_resolve_or_are_refused_with_one_of_the_three_codes():
    """꼴 검사는 지어낸 나무에서도 셋 가운데 하나의 사유로만 거절한다(다른 예외로 새지 않는다)."""
    rng = random.Random(20261117)
    leaves = [R(1), R(2), C(0.5), ind_node("close"), ind_node("vwap")]
    seen = set()
    for _ in range(400):
        a, b = rng.choice(leaves), rng.choice(leaves)
        cmp_ = op(rng.choice(["gt", "lt", "cross_up"]), a, b)
        tree = rng.choice([cmp_, op("and", cmp_, ABOVE), op("or", cmp_, ABOVE), op("not", cmp_)])
        try:
            rules.resolve("custom", {"entry": tree})
            seen.add("ok")
        except rules.RuleError as err:
            assert err.code in ("regime_outside_entry", "regime_not_in_and", "regime_not_plain"), err.code
            seen.add(err.code)
    assert seen == {"ok", "regime_not_in_and", "regime_not_plain"}
