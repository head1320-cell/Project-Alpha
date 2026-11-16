"""직접 구성한 규칙(`custom`) — 틀 일곱 옆의 여덟째 종류 (자유 조건식 설계 §4 · 구현 계획 f1).

`custom` 은 새 엔진이 아니다 — 사용자가 지은 나무 셋을 ★틀이 지나는 길 그대로★(`rules.resolve` · `rules.build`) 지나게 할 뿐이다.
그래서 여기서 거는 것은: ⑴ 틀이 만든 나무를 `custom` 으로 돌리면 체결이 한 줄도 다르지 않다 ⑵ 문법에서 뽑은 어떤 나무도 앞을 보지 않는다
⑶ 같은 설정은 하나의 꼴이 된다(시행을 가르는 것이 이것이다) ⑷ 어긋난 것은 사유 · 자리와 함께 거절된다
⑸ 화면이 쓸 이름표는 전부 등록부에 있다 ⑹ 규칙의 글은 다른 나무에 다른 글을 낸다.
"""
from __future__ import annotations

import hashlib
import json
import random

import numpy as np
import pytest

from src.engine import intraday
from src.engine.intraday import expr, indicators, rules, simulator
from src.engine.intraday.types import PrevDay, Session
from tests.test_intraday_golden import GOLDEN, SETUPS, _days
from tests.test_intraday_golden import RULES as SESSION_RULES


def I(name, **params):                                           # noqa: E743 — 시험의 짧은 손
    return {"ind": name, **params}


def C(value):
    return {"const": value}


def op(name, *args, **extra):
    return {"op": name, "args": list(args), **extra}


ABOVE = op("gt", I("close"), I("sma"))                           # 종가 > 이동평균(기본 20봉)
BELOW = op("lt", I("close"), I("vwap"))


def refused(params) -> rules.RuleError:
    with pytest.raises(rules.RuleError) as err:
        rules.build("custom", params)
    return err.value


# ── ⑴ 틀 일곱 = 같은 나무의 custom ───────────────────────────────────────────────────────
ALL_SETTINGS = [(kind, params) for kind, template in rules.TEMPLATES.items()
                for params in ({}, *[{c.key: v} for c in template.params if isinstance(c, rules.Choice) for v in c.values])]
_KEYS = ("fills", "events", "skipped", "assumptions", "counts", "sources")


@pytest.mark.parametrize("kind, params", ALL_SETTINGS, ids=[f"{k}:{p}" for k, p in ALL_SETTINGS])
@pytest.mark.parametrize("setup", list(SETUPS))
def test_a_template_s_trees_run_as_custom_give_the_same_fills_line_for_line(kind, params, setup):
    position, costs = SETUPS[setup]
    spec = rules.build(kind, params)
    same = rules.build("custom", rules.as_custom(spec))
    by_template = intraday.simulate(_days(), spec, position, costs, rules=SESSION_RULES)
    by_custom = intraday.simulate(_days(), same, position, costs, rules=SESSION_RULES)
    assert {k: by_custom[k] for k in _KEYS} == {k: by_template[k] for k in _KEYS}
    if not params:                                               # 기본값이면 골든이 붙든 그 요약값이다(공허한 일치가 아니다)
        blob = json.dumps({k: by_custom[k] for k in _KEYS}, sort_keys=True)
        assert (hashlib.sha256(blob.encode()).hexdigest()[:20], len(by_custom["fills"])) == GOLDEN[f"{kind}/{setup}"]


def test_as_custom_keeps_every_slot_the_template_filled():
    for kind, params in ALL_SETTINGS:
        spec = rules.build(kind, params)
        filled = {key for key in ("entry", "entry_stop", "exit") if getattr(spec, key) is not None}
        assert set(rules.as_custom(spec)) == filled, (kind, params)
    assert set(rules.as_custom(rules.build("vwap_cross", {}))) == {"entry", "exit"}
    assert set(rules.as_custom(rules.build("volatility_breakout", {}))) == {"entry_stop"}


def test_a_custom_rule_passes_the_simulator_s_own_check():
    spec = rules.build("custom", {"entry": ABOVE, "exit": BELOW})
    assert isinstance(spec, simulator.RuleSpec) and spec.entry_stop is None
    simulator.validate(spec, simulator.PositionRules(amount=1_000_000), simulator.CostAssumptions())


# ── ⑵ 성질: 문법에서 뽑은 어떤 나무도 앞을 보지 않는다 ───────────────────────────────────────
def _session(seed: int, n: int = 70) -> Session:
    rng = np.random.default_rng(seed)
    close = 10_000 + np.cumsum(rng.integers(-8, 9, n)) * 10.0
    open_ = np.concatenate([[close[0] + 150], close[:-1]])
    high = np.maximum(open_, close) + rng.integers(0, 4, n) * 10.0
    low = np.minimum(open_, close) - rng.integers(0, 4, n) * 10.0
    volume = rng.integers(0, 3_000, n).astype(float)
    time = np.array([f"{9 + m // 60:02d}{m % 60:02d}00" for m in range(n)])
    prev = PrevDay(close=float(open_[0] - 300), high=float(open_[0] - 100), low=float(open_[0] - 400), basis="minute")
    return Session("005930", "2026-03-04", time, open_, high, low, close, volume, "kis", prev, "KOSPI", "stock", None)


def _cut(s: Session, k: int) -> Session:
    return Session(s.ticker, s.date, s.time[:k], s.open[:k], s.high[:k], s.low[:k], s.close[:k], s.volume[:k], s.source,
                   s.prev, s.market, s.instrument, s.name)


_CONSTS = (0, 0.5, 1, 30, 50, 70, 1_500, 9_950, 10_000, 10_050)


def _rand_ind(rng: random.Random) -> dict:
    name = rng.choice(list(indicators.INDICATORS))
    node = {"ind": name}
    for key, r in indicators.INDICATORS[name].params.items():
        if rng.random() < 0.8:                                   # 작은 창 — 70봉짜리 하루에서 덥혀지게. 나머지는 기본값에 맡긴다
            node[key] = rng.randint(int(r.low), min(int(r.high), 12)) if r.integer else round(rng.uniform(r.low, r.high), 2)
    return node


def _rand_number(rng: random.Random, depth: int) -> dict:
    roll = rng.random()
    if depth <= 0 or roll < 0.4:
        return _rand_ind(rng) if rng.random() < 0.75 else C(rng.choice(_CONSTS))
    if roll < 0.75:
        return op(rng.choice(["add", "sub", "mul"]), _rand_number(rng, depth - 1), _rand_number(rng, depth - 1))
    if roll < 0.88:
        return op("where", _rand_bool(rng, depth - 1), _rand_number(rng, depth - 1))
    return op("ago", _rand_number(rng, depth - 1), bars=rng.randint(1, 4))


def _rand_bool(rng: random.Random, depth: int) -> dict:
    roll = rng.random()
    if depth <= 0 or roll < 0.35:
        if rng.random() < 0.12:
            start = rng.randint(0, 50)
            return {"op": "time_between", "args": [], "from": f"09{start:02d}", "to": f"09{rng.randint(start, 59):02d}"}
        name = rng.choice(["gt", "ge", "lt", "le", "cross_up", "cross_down"])
        return op(name, _rand_number(rng, max(depth - 1, 0)), _rand_number(rng, max(depth - 1, 0)))
    if roll < 0.7:
        return op(rng.choice(["and", "or"]), *[_rand_bool(rng, depth - 1) for _ in range(rng.randint(2, 3))])
    if roll < 0.85:
        return op("not", _rand_bool(rng, depth - 1))
    return op("held_before", _rand_bool(rng, depth - 1), bars=rng.randint(1, 4))


def _random_trees(count: int = 300, seed: int = 20261115) -> list[dict]:
    """문법에서 뽑은 나무 — 절반은 판단, 절반은 수. 상한을 넘은 것은 버리고 다시 뽑는다(검사기가 가른다)."""
    rng, out, seen = random.Random(seed), [], set()
    while len(out) < count:
        tree = (_rand_bool if len(out) % 2 == 0 else _rand_number)(rng, 3)
        try:
            expr.validate(tree)
        except expr.ExprError as err:
            assert err.code in ("too_many_nodes", "too_deep"), err   # 뽑는 손이 문법을 어긴 것이면 시험이 틀린 것이다
            continue
        if expr.canonical(tree) not in seen:                     # 같은 나무를 두 번 세지 않는다
            seen.add(expr.canonical(tree))
            out.append(tree)
    return out


TREES = _random_trees()


def _names(tree, key: str) -> set[str]:
    found = {tree[key]} if key in tree else set()
    for arg in tree.get("args", []):
        found |= _names(arg, key)
    return found


def test_the_random_trees_cover_the_whole_grammar():
    """뽑힌 나무가 연산과 지표를 전부 덮는다 — 덮지 못한 연산은 아래 성질 시험이 보지 못한 것이다."""
    ops, inds = set(), set()
    for tree in TREES:
        ops |= _names(tree, "op")
        inds |= _names(tree, "ind")
    assert ops == set(expr.OP_LABELS) and len(ops) == 16
    assert inds == set(indicators.INDICATORS) and len(inds) == 28
    assert len({expr.canonical(t) for t in TREES}) == len(TREES) == 300


def test_no_random_tree_looks_ahead():
    sessions = [_session(seed) for seed in (1, 2)]
    for index, tree in enumerate(TREES):
        for s in sessions:
            full = expr.evaluate(tree, s)
            for k in (1, 7, 23, 41, 69):
                assert np.array_equal(expr.evaluate(tree, _cut(s, k)), full[:k], equal_nan=True), (index, k, tree)


def test_the_random_trees_are_not_all_silent():
    """전부 거짓 · 전부 미상인 나무뿐이면 위 성질은 아무것도 보지 못한다."""
    s = _session(1)
    firing = sum(bool(expr.evaluate(t, s).any()) for t in TREES if expr.validate(t) == "bool")
    valued = sum(bool((~np.isnan(expr.evaluate(t, s))).any()) for t in TREES if expr.validate(t) == "number")
    assert firing >= 60 and valued >= 100, (firing, valued)


# ── ⑶ 모름은 참이 아니다 ─────────────────────────────────────────────────────────────────
def test_a_custom_condition_is_silent_until_its_indicators_have_values():
    s = _session(3)
    never_below = op("not", op("lt", I("close"), I("sma", n=20)))            # '평균 아래가 아니다' — 평균이 없는 봉에서는 모름이다
    hits = np.flatnonzero(expr.evaluate(rules.build("custom", {"entry": never_below}).entry, s))
    assert len(hits) > 0 and hits.min() >= 19                                # 20봉이 차기 전(봉 0~18)에는 신호가 없다
    always = op("or", never_below, op("lt", I("close"), I("sma", n=20)))     # 짝: 덥혀진 뒤에는 둘 중 하나가 늘 참이다
    assert list(np.flatnonzero(expr.evaluate(always, s))) == list(range(19, 70))


# ── ⑷ 하나의 꼴 ─────────────────────────────────────────────────────────────────────────
def test_defaults_are_filled_and_the_form_does_not_depend_on_spelling():
    plain = rules.resolve("custom", {"entry": ABOVE})
    assert plain == {"entry": {"op": "gt", "args": [{"ind": "close"}, {"ind": "sma", "n": 20}]}}
    spelled = rules.resolve("custom", {"exit": None, "entry": {"args": [I("close"), I("sma", n=20.0)], "op": "gt"}})
    assert expr.canonical(spelled) == expr.canonical(plain)                   # 열쇠 순서 · 기본값 · 20.0 · 빈 자리
    assert isinstance(spelled["entry"]["args"][1]["n"], int)


def test_a_whole_number_and_its_float_are_one_setting():
    a = rules.resolve("custom", {"entry": op("gt", I("rsi"), C(30))})
    b = rules.resolve("custom", {"entry": op("gt", I("rsi", n=14), C(30.0))})
    assert expr.canonical(a) == expr.canonical(b) and a["entry"]["args"][1] == {"const": 30.0}
    assert expr.canonical(rules.resolve("custom", {"entry": op("gt", I("rsi"), C(31))})) != expr.canonical(a)   # 짝 — 값이 다르면 다르다


def test_the_order_of_conditions_is_kept_so_a_reordered_rule_is_another_setting():
    """순서를 정규화하다 틀리면 시행을 덜 세게 된다 — 묶지 않는다(설계 §4)."""
    ab = rules.resolve("custom", {"entry": op("and", ABOVE, BELOW)})
    ba = rules.resolve("custom", {"entry": op("and", BELOW, ABOVE)})
    assert expr.canonical(ab) != expr.canonical(ba)
    assert [arg["op"] for arg in ab["entry"]["args"]] == ["gt", "lt"]


def test_every_node_has_the_same_shape_and_nothing_extra():
    form = rules.resolve("custom", {"entry": op("and", {"op": "time_between", "from": "0930", "to": "1450"},
                                                op("held_before", BELOW, bars=3))})
    window, held = form["entry"]["args"]
    assert window == {"op": "time_between", "args": [], "from": "0930", "to": "1450"}
    assert set(held) == {"op", "args", "bars"} and held["bars"] == 3


def test_resolving_twice_changes_nothing():
    for tree in TREES[:60]:
        slot = "entry" if expr.validate(tree) == "bool" else "entry_stop"
        once = rules.resolve("custom", {slot: tree})
        assert rules.resolve("custom", once) == once


# ── ⑸ 거절과 사유 ───────────────────────────────────────────────────────────────────────
def _wide(conditions: int) -> dict:
    """비교 `conditions` 개를 '모두 충족'으로 묶은 나무 — 마디 수 1 + 3 × conditions."""
    return op("and", *[op("gt", I("close"), C(float(i))) for i in range(conditions)])


def _deep(levels: int) -> dict:
    tree = ABOVE
    for _ in range(levels):
        tree = op("not", tree)
    return tree


@pytest.mark.parametrize("params, code, slot", [
    ({"entry": ABOVE, "stop": ABOVE}, "unknown_param", None),
    ({}, "no_entry", None),
    ({"exit": BELOW}, "no_entry", None),
    ({"entry": I("close")}, "entry_not_a_condition", "entry"),
    ({"entry_stop": ABOVE}, "entry_stop_not_a_price", "entry_stop"),
    ({"entry": ABOVE, "exit": C(1)}, "exit_not_a_condition", "exit"),
    ({"entry": op("gt", I("stochastic"), C(0))}, "unknown_indicator", "entry"),
    ({"entry": op("gt", I("sma", n=500), C(0))}, "param_out_of_range", "entry"),
    ({"entry": op("gt", I("sma", window=5), C(0))}, "unknown_param", "entry"),
    ({"entry": {**ABOVE, "note": "x"}}, "unknown_key", "entry"),
    ({"entry": ABOVE, "exit": op("held_before", BELOW, bars=3, to="1500")}, "unknown_key", "exit"),
    ({"entry": "close > sma"}, "not_a_node", "entry"),
    ({"entry": op("gt", I("close"), C(10 ** 400))}, "bad_const", "entry"),
    ({"entry": ABOVE, "exit": _deep(12)}, "too_deep", "exit"),
    ({"entry": op("xor", ABOVE, BELOW)}, "unknown_op", "entry"),
    ({"entry": op("held_before", ABOVE, bars=241)}, "bad_bars", "entry"),
])
def test_a_bad_custom_rule_is_refused_with_a_reason_and_the_slot(params, code, slot):
    err = refused(params)
    assert (err.code, err.slot) == (code, slot)


def test_the_node_limit_counts_the_three_trees_together():
    assert expr.size(_wide(21)) == (64, 3)
    rules.build("custom", {"entry": _wide(21)})                              # 한 나무가 64 마디 — 딱 상한
    rules.build("custom", {"entry": _wide(20), "exit": BELOW})               # 61 + 3 = 64 — 합쳐서 딱 상한
    err = refused({"entry": _wide(20), "exit": op("and", BELOW, ABOVE)})     # 61 + 7 = 68
    assert err.code == "too_many_nodes" and err.slot is None
    assert refused({"entry": _wide(21), "entry_stop": I("close")}).code == "too_many_nodes"      # 64 + 1


def test_held_before_takes_240_bars_and_not_241():
    assert expr.validate(op("held_before", ABOVE, bars=240)) == "bool"
    with pytest.raises(expr.ExprError) as err:
        expr.validate(op("held_before", ABOVE, bars=241))
    assert err.value.code == "bad_bars" and expr.HELD_BARS == (1, 240)


def test_size_counts_like_the_validator():
    assert expr.size(I("close")) == (1, 1) and expr.size(ABOVE) == (3, 2)
    assert expr.size(_deep(11)) == (14, 13) and expr.size({"op": "time_between", "from": "0900", "to": "0930"}) == (1, 1)
    for tree in TREES[:40]:
        nodes, depth = expr.size(tree)
        assert 1 <= nodes <= expr.MAX_NODES and 1 <= depth <= expr.MAX_DEPTH


# ── ⑹ 이름표 · 문법 표 ───────────────────────────────────────────────────────────────────
def test_every_indicator_parameter_and_operator_has_a_label_and_the_labels_differ():
    """화면은 이름을 지어내지 않는다 — 등록부에 있는 것은 전부 이름표가 있다(새 지표를 더하면 여기서 걸린다)."""
    labels = [spec.label for spec in indicators.INDICATORS.values()]
    assert all(labels) and len(set(labels)) == len(labels) == 28
    for name, spec in indicators.INDICATORS.items():
        assert spec.unit in indicators.UNITS, name
        assert all(r.label and r.unit for r in spec.params.values()), name
    assert set(expr.OP_LABELS) == set(expr.shapes()) and len(set(expr.OP_LABELS.values())) == 16
    assert set(expr.OP_SYMBOLS) == {"add", "sub", "mul", "gt", "ge", "lt", "le"}
    assert all("—" not in text for text in (*labels, *expr.OP_LABELS.values(), *indicators.UNITS.values()))


def test_the_grammar_is_read_from_the_registries_not_copied():
    g = rules.grammar()
    assert [i["name"] for i in g["indicators"]] == list(indicators.INDICATORS)
    for i in g["indicators"]:
        spec = indicators.INDICATORS[i["name"]]
        assert (i["label"], i["unit"], i["needs_prev"]) == (spec.label, spec.unit, spec.needs_prev)
        assert [p["key"] for p in i["params"]] == list(spec.params)
        for p in i["params"]:
            r = spec.params[p["key"]]
            assert (p["min"], p["max"], p["default"], p["label"], p["unit"]) == (r.low, r.high, r.default, r.label, r.unit)
            assert p["type"] == ("int" if r.integer else "float")
    assert {i["name"] for i in g["indicators"] if i["needs_prev"]} == {"prev_close", "prev_high", "prev_low"}
    by_name = {o["name"]: o for o in g["ops"]}
    assert list(by_name) == list(expr.shapes()) and len(by_name) == 16
    assert by_name["ago"] == {"name": "ago", "label": "N봉 전 값", "symbol": None, "gives": "number", "args": ["number"], "variadic": None,
                              "extra": [{"key": "bars", "label": "봉 수", "type": "int", "min": 1, "max": 240, "unit": "봉"}]}
    macd = next(i for i in g["indicators"] if i["name"] == "macd_signal")
    assert (macd["label"], macd["unit"]) == ("MACD 신호선", "price")
    assert [(p["key"], p["label"], p["default"]) for p in macd["params"]] == [("fast", "단기 기간", 12), ("slow", "장기 기간", 26), ("signal", "신호 기간", 9)]
    assert {i["name"]: i["label"] for i in g["indicators"]}.items() >= {
        "ema": "지수이동평균", "macd": "MACD", "macd_hist": "MACD 오실레이터", "atr": "ATR", "day_high": "당일 고가", "day_low": "당일 저가"}.items()
    assert by_name["gt"] == {"name": "gt", "label": "초과", "symbol": ">", "gives": "bool", "args": ["number", "number"],
                             "variadic": None, "extra": []}
    assert by_name["where"]["args"] == ["bool", "number"] and by_name["where"]["gives"] == "number"
    assert by_name["and"]["args"] == [] and by_name["and"]["variadic"] == {"kind": "bool", "min": 2, "max": expr.MAX_NODES}
    assert by_name["not"]["args"] == ["bool"] and by_name["time_between"]["args"] == []
    assert by_name["held_before"]["extra"] == [{"key": "bars", "label": "직전 봉 수", "type": "int", "min": 1, "max": 240,
                                                "unit": "봉"}]
    assert [f["key"] for f in by_name["time_between"]["extra"]] == ["from", "to"]
    assert g["limits"] == {"nodes": expr.MAX_NODES, "depth": expr.MAX_DEPTH} == {"nodes": 64, "depth": 12}
    assert [(s["key"], s["kind"], s["label"]) for s in g["slots"]] == [
        ("entry", "bool", "진입 조건"), ("entry_stop", "number", "미리 건 매수 가격"), ("exit", "bool", "청산 조건")]
    assert g["entry_rule"].endswith("니다.") and g["units"] == indicators.UNITS


def test_the_listing_has_the_custom_kind_last_and_marks_it():
    listing = rules.describe()
    assert [t["kind"] for t in listing] == [*rules.TEMPLATES, "custom"]
    assert [t["custom"] for t in listing] == [False] * 7 + [True]
    custom = listing[-1]
    assert custom["label"] == "직접 구성" and custom["params"] == []
    assert custom["needs_prev"] is None                          # 조건에 따라 다르다 — 미리 말할 수 없다(False 가 아니다)
    assert len(custom["notes"]) == 2 and any("시행" in n for n in custom["notes"]) and any("값이 없는" in n for n in custom["notes"])


# ── ⑺ 규칙의 글 ─────────────────────────────────────────────────────────────────────────
def test_the_text_reads_like_the_condition_rows():
    assert rules.text_of(rules.build("vwap_cross", {"bars_below": 3})) == (
        "진입 조건: 종가 상향 돌파 VWAP 그리고 직전 3봉 동안(종가 < VWAP) · 청산 조건: 종가 < VWAP")
    assert rules.text_of(rules.build("volatility_breakout", {"k": 0.5})) == (
        "미리 건 매수 가격: 당일 시가 + (0.5 × (전일 고가 − 전일 저가))")
    mine = {"entry": op("and", {"op": "time_between", "from": "0930", "to": "1450"}, op("gt", I("close"), I("sma")),
                        op("ge", I("volume"), op("mul", C(2), I("vol_avg"))), op("cross_up", I("rsi"), C(30))),
            "exit": op("or", op("lt", I("close"), I("bb_lower", k=2.5)), op("not", op("le", I("rsi"), C(70))))}
    assert rules.text_of(rules.build("custom", mine)) == (
        "진입 조건: 시각 09:30~14:50 그리고 종가 > 이동평균(20봉) 그리고 거래량 ≥ (2 × 직전 평균 거래량(20봉)) 그리고 RSI(14봉) 상향 돌파 30"
        " · 청산 조건: 종가 < 볼린저 하단(20봉, 2.5배) 또는 아님(RSI(14봉) ≤ 70)")


def test_nested_groups_and_conditional_values_are_bracketed():
    nested = rules.build("custom", {"entry": op("or", op("and", ABOVE, BELOW), BELOW),
                                    "entry_stop": op("where", op("and", ABOVE, BELOW), I("high"))})
    assert rules.text_of(nested) == ("진입 조건: (종가 > 이동평균(20봉) 그리고 종가 < VWAP) 또는 종가 < VWAP"
                                     " · 미리 건 매수 가격: (종가 > 이동평균(20봉) 그리고 종가 < VWAP) 충족 시 고가")
    flat = rules.build("custom", {"entry": op("or", ABOVE, BELOW, BELOW)})
    assert rules.text_of(flat) == "진입 조건: 종가 > 이동평균(20봉) 또는 종가 < VWAP 또는 종가 < VWAP"


def test_different_trees_never_share_a_text():
    seen: dict[str, str] = {}
    for tree in TREES:
        slot = "entry" if expr.validate(tree) == "bool" else "entry_stop"
        form = rules.resolve("custom", {slot: tree})
        text = rules.text_of(rules.build("custom", form))
        assert "—" not in text
        assert seen.setdefault(text, expr.canonical(form)) == expr.canonical(form), text
    assert len(seen) > 290


def test_n_bars_back_reads_as_a_phrase_and_brackets_a_calculation():
    spec = rules.build("custom", {"entry": op("gt", I("high"), op("ago", I("day_high"), bars=1)),
                                  "entry_stop": op("ago", op("sub", I("close"), I("open")), bars=3),
                                  "exit": op("cross_down", I("macd"), I("macd_signal"))})
    assert rules.text_of(spec) == ("진입 조건: 고가 > 1봉 전 당일 고가 · 미리 건 매수 가격: 3봉 전 (종가 − 시가) · "
                                   "청산 조건: MACD(12봉, 26봉) 하향 돌파 MACD 신호선(12봉, 26봉, 9봉)")
    # 어디에 '전'이 붙었는지에 따라 글이 다르다
    a = rules.text_of(rules.build("custom", {"entry_stop": op("add", op("ago", I("close"), bars=1), C(10))}))
    b = rules.text_of(rules.build("custom", {"entry_stop": op("ago", op("add", I("close"), C(10)), bars=1)}))
    assert (a, b) == ("미리 건 매수 가격: 1봉 전 종가 + 10", "미리 건 매수 가격: 1봉 전 (종가 + 10)")


def test_n_bars_back_keeps_its_bars_in_the_one_form_and_refuses_what_it_does_not_know():
    out = rules.resolve("custom", {"entry": op("gt", I("close"), op("ago", I("ema"), bars=2))})["entry"]
    assert out["args"][1] == {"op": "ago", "args": [{"ind": "ema", "n": 20}], "bars": 2}
    assert rules.resolve("custom", {"entry": out}) == {"entry": out}        # 한 번 더 풀어도 같다
    two = rules.resolve("custom", {"entry": op("gt", I("close"), op("ago", I("ema"), bars=3))})["entry"]
    assert expr.canonical(two) != expr.canonical(out)                       # 봉 수가 다르면 다른 설정(다른 시행)이다
    assert refused({"entry": op("gt", I("close"), op("ago", I("close"), bars=2, shift=1))}).code == "unknown_key"
    err = refused({"exit": op("gt", I("close"), op("ago", I("close"), bars=0)), "entry": ABOVE})
    assert (err.code, err.slot) == ("bad_bars", "exit")


def test_the_notes_say_that_carried_indicators_restart_each_day__only_when_one_is_used():
    """앞 봉의 값을 이어 쓰는 지표는 그날 첫 봉부터 다시 계산한다 — 차트 도구의 값과 다르다는 것을 쓰는 규칙에만 말한다(짝)."""
    said = "그날의 첫 봉부터 다시 계산합니다"
    assert not any(said in n for n in rules.notes_of(rules.build("custom", {"entry": ABOVE})))
    for name in ("ema", "macd", "macd_signal", "macd_hist", "atr", "rsi"):
        notes = rules.notes_of(rules.build("custom", {"entry": op("gt", I("close"), I(name))}))
        assert sum(said in n for n in notes) == 1, name
    deep = rules.build("custom", {"entry": ABOVE, "exit": op("lt", I("close"), op("ago", op("add", I("ema"), C(1)), bars=1))})
    assert any(said in n for n in rules.notes_of(deep))                     # 깊이 묻혀도 · 어느 자리든
    by_kind = {kind: any(said in n for n in rules.notes_of(rules.build(kind, None))) for kind in rules.TEMPLATES}
    assert [kind for kind, has in by_kind.items() if has] == ["rsi_reversal"]    # 틀 가운데는 RSI 를 쓰는 것 하나뿐이다
    assert all(n.endswith("니다.") and "—" not in n for n in rules.notes_of(deep))


def test_the_notes_say_that_the_days_high_and_low_include_the_bar__only_when_one_is_used():
    said = "당일 고가와 당일 저가는 그 봉을 포함합니다"
    assert not any(said in n for n in rules.notes_of(rules.build("custom", {"entry": ABOVE})))
    for name in ("day_high", "day_low"):
        notes = rules.notes_of(rules.build("custom", {"entry": op("gt", I("close"), op("ago", I(name), bars=1))}))
        assert sum(said in n for n in notes) == 1 and all(n.endswith("니다.") and "—" not in n for n in notes), name
    assert not any(said in n for n in rules.notes_of(rules.build("custom", {"entry": op("gt", I("close"), I("day_open"))})))


def test_the_notes_say_what_the_trees_need():
    plain = rules.notes_of(rules.build("custom", {"entry": ABOVE}))
    with_prev = rules.notes_of(rules.build("custom", {"entry": op("gt", I("close"), I("prev_high"))}))
    assert len(plain) == 1 and "그날의 봉" in plain[0]
    assert len(with_prev) == 2 and "전일 값은 원주가" in with_prev[1]
    assert all(n.endswith("니다.") and "—" not in n for n in with_prev)


def test_the_notes_say_that_held_before_does_not_look_at_the_bar_itself__only_when_it_is_used():
    """'직전 M봉 동안 계속'은 ★그 봉을 보지 않는다★(앞 봉들만 — 인과). 쓰는 규칙에만 그 말이 붙는다(짝) — 깊이 묻혀 있어도, 어느 자리에 있어도."""
    held = {"op": "held_before", "bars": 3, "args": [ABOVE]}
    said = "‘직전 M봉 동안 계속’은 그 봉을 포함하지 않습니다. 앞선 M개 봉에서 모두 충족했는지 봅니다."
    assert said in rules.notes_of(rules.build("custom", {"entry": held}))
    assert said not in rules.notes_of(rules.build("custom", {"entry": ABOVE}))
    assert said not in rules.notes_of(rules.build("custom", {"entry": op("not", ABOVE), "exit": BELOW}))
    deep = op("and", BELOW, op("not", op("or", ABOVE, held)))
    assert said in rules.notes_of(rules.build("custom", {"entry": ABOVE, "exit": deep}))
    priced = {"op": "where", "args": [held, I("day_open")]}
    assert said in rules.notes_of(rules.build("custom", {"entry_stop": priced}))
    both = rules.notes_of(rules.build("custom", {"entry": op("and", held, op("gt", I("close"), I("prev_high")))}))
    assert len(both) == 3 and len(set(both)) == 3                               # 덥히기 · 전일 값 · 직전 M봉 — 한 번씩
    # 그 말은 사실이다 — 다섯째 봉(종가 1)은 조건에 어긋나지만 답은 참이고(앞의 셋만 본다), 그 봉이 창에 드는 여섯째 봉은 거짓이다.
    close = np.array([10.0, 11.0, 12.0, 13.0, 1.0, 14.0])
    time = np.array([f"09{m:02d}00" for m in range(len(close))])
    session = Session("005930", "2026-03-04", time, close, close, close, close, np.ones(len(close)), "kis", None, "KOSPI", "stock", None)
    fired = expr.evaluate({"op": "held_before", "bars": 3, "args": [op("gt", I("close"), {"const": 5.0})]}, session)
    assert fired.tolist() == [False, False, False, True, True, False]


def test_rule_text_reads_a_stored_rule_or_says_why_it_cannot():
    kept = {"kind": "custom", "params": rules.resolve("custom", {"entry": ABOVE})}
    assert rules.rule_text(kept) == {"rule_text": "진입 조건: 종가 > 이동평균(20봉)", "rule_text_reason": None}
    template = rules.rule_text({"kind": "rsi_reversal", "params": {"n": 14, "oversold": 30.0, "overbought": 70.0}})
    assert template == {"rule_text": "진입 조건: RSI(14봉) 상향 돌파 30 · 청산 조건: RSI(14봉) > 70", "rule_text_reason": None}
    for broken in (None, {}, {"kind": "macd_cross", "params": {}}, {"kind": "custom", "params": {"entry": "x"}},
                   {"kind": "custom"}, "custom"):
        said = rules.rule_text(broken)
        assert said["rule_text"] is None and said["rule_text_reason"].endswith("니다."), broken
