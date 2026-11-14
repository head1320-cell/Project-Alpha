"""규칙 틀 일곱 — 매개변수를 받아 표현식 나무를 만든다 (분봉 백테스트 설계 §7.1 · W4c c1).

틀마다 손으로 만든 하루에서 "신호가 나는 봉 / 안 나는 봉"의 짝을 건다. 틀은 나무를 만들 뿐이고 계산은 `expr` 가 한다 —
그래서 여기서 보는 것은 ★틀의 뜻이 설계의 문장과 같은가★ 다. 모든 틀은 앞보기 성질 시험을 지난다.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.engine.intraday import expr, rules, simulator
from src.engine.intraday.types import PrevDay, Session


def sess(rows, prev=None) -> Session:
    """rows: (open, high, low, close, volume) — 시각은 09:00 부터 1분씩."""
    o, h, low, c, v = zip(*rows)
    time = np.array([f"09{m:02d}00" for m in range(len(rows))])
    return Session("005930", "2026-03-04", time, np.array(o, float), np.array(h, float), np.array(low, float),
                   np.array(c, float), np.array(v, float), "kis", prev, "KOSPI", "stock", None)


def flat(closes, volume=10) -> Session:
    return sess([(c, c, c, c, volume) for c in closes])


def fires(tree, s) -> list[int]:
    return [i for i, x in enumerate(expr.evaluate(tree, s)) if x]


# ── 시가 범위 돌파 ─────────────────────────────────────────────────────────────────────
WINDOW = [(100, 102, 99, 101, 10), (101, 103, 100, 102, 10), (102, 104, 101, 103, 10)]      # 3분 창 — 고가 104


def orb(**params):
    return rules.build("opening_range_breakout", {"minutes": 3, **params})


def test_orb_fires_on_the_first_close_above_the_range_after_the_window():
    later = sess([*WINDOW, (103, 104, 102, 103, 10), (103, 106, 103, 105, 10), (105, 107, 104, 106, 10)])
    assert fires(orb().entry, later) == [4]                 # 09:03 종가 103 은 104 아래 · 09:04 종가 105 가 넘었다 · 09:05 는 이미 위


def test_orb_fires_on_the_very_first_bar_after_the_window_if_it_closes_above():
    at_once = sess([*WINDOW, (103, 106, 103, 105, 10), (105, 107, 104, 106, 10)])
    assert fires(orb().entry, at_once) == [3]


def test_orb_never_fires_inside_the_window_or_without_a_break():
    inside = sess([(100, 102, 99, 101, 10), (101, 250, 100, 240, 10), (102, 104, 101, 103, 10), (103, 104, 102, 103, 10)])
    assert fires(orb().entry, inside) == []                 # 창 안의 급등은 범위를 만들 뿐이다(고가 250) · 그 뒤로는 넘지 못했다
    assert orb().exit is None and orb().entry_stop is None


# ── VWAP 상향 돌파 ─────────────────────────────────────────────────────────────────────
def test_vwap_cross_needs_the_bars_below_first():
    # 종가 100 90 90 90 100 · VWAP(누적 평균) 100 95 93.3 92.5 94 → 봉 1~3 이 아래 · 봉 4 가 올라섰다
    s = flat([100, 90, 90, 90, 100])
    assert fires(rules.build("vwap_cross", {"bars_below": 2}).entry, s) == [4]
    assert fires(rules.build("vwap_cross", {"bars_below": 4}).entry, s) == []           # 봉 0 은 아래가 아니었다
    assert fires(rules.build("vwap_cross", {"bars_below": 2}).exit, s) == [1, 2, 3]     # 청산 조건: 종가가 VWAP 아래


# ── 변동성 돌파 ───────────────────────────────────────────────────────────────────────
def test_volatility_breakout_is_a_resting_buy_at_open_plus_k_times_yesterdays_range():
    prev = PrevDay(close=100.0, high=110.0, low=100.0, basis="daily")
    spec = rules.build("volatility_breakout", {"k": 0.5})
    assert spec.entry is None and spec.exit is None
    assert list(expr.evaluate(spec.entry_stop, sess([(100, 101, 99, 100, 10)] * 3, prev))) == [105.0, 105.0, 105.0]
    assert all(math.isnan(x) for x in expr.evaluate(spec.entry_stop, sess([(100, 101, 99, 100, 10)] * 3)))   # 전일 값이 없다


# ── 갭 ───────────────────────────────────────────────────────────────────────────────
PREV = PrevDay(close=100.0, high=101.0, low=99.0, basis="daily")


def test_gap_follow_is_the_range_breakout_on_days_that_gapped_up_enough():
    up = [(103, 104, 103, 103.5, 10), (103.5, 104.5, 103, 104, 10), (104, 105, 103, 104, 10), (104, 106, 104, 105.5, 10)]
    small = [(101, 104, 101, 103.5, 10), *up[1:]]
    spec = rules.build("gap", {"direction": "follow", "gap_pct": 2.0, "minutes": 3})
    assert fires(spec.entry, sess(up, PREV)) == [3]         # 시가 103 ≥ 102 · 창 고가 105 를 09:03 종가 105.5 가 넘었다
    assert fires(spec.entry, sess(small, PREV)) == []       # 시가 101 — 갭이 2% 에 못 미친다
    assert fires(spec.entry, sess(up)) == []                # 전일 종가를 모른다


def test_gap_fade_buys_when_a_gapped_down_day_closes_back_above_its_open():
    down = [(97, 97, 95.5, 96, 10), (96, 97, 96, 96.5, 10), (96.5, 98.5, 96.5, 98, 10), (98, 99, 97.5, 98.5, 10)]
    shallow = [(99, 99, 95.5, 96, 10), (96, 97, 96, 96.5, 10), (96.5, 100, 96.5, 99.5, 10)]
    spec = rules.build("gap", {"direction": "fade", "gap_pct": 2.0})
    assert fires(spec.entry, sess(down, PREV)) == [2]       # 시가 97 ≤ 98 · 09:02 종가 98 이 시가 97 을 넘어섰다
    assert fires(spec.entry, sess(shallow, PREV)) == []     # 시가 99 — 갭이 2% 에 못 미친다


# ── 거래량 급증 ───────────────────────────────────────────────────────────────────────
def surge(last):
    return sess([(100, 101, 99, 100, 10), (100, 101, 99, 100.5, 10), (100.5, 101, 100, 100.5, 10), last])


def test_volume_surge_needs_volume_a_rising_bar_and_a_new_high_close():
    spec = rules.build("volume_surge", {"bars": 3, "multiple": 2.0})
    assert fires(spec.entry, surge((100.5, 102, 100.5, 101.5, 30))) == [3]              # 30 ≥ 2 × 평균 10 · 양봉 · 종가 신고
    assert fires(spec.entry, surge((100.5, 102, 100.5, 101.5, 19))) == []               # 거래량 부족
    assert fires(spec.entry, surge((102, 102, 100.5, 101.5, 30))) == []                 # 음봉(시가 102 > 종가)
    assert fires(spec.entry, surge((100, 100.5, 100, 100.4, 30))) == []                 # 종가가 직전 최고 종가 100.5 를 못 넘었다


# ── RSI ──────────────────────────────────────────────────────────────────────────────
def test_rsi_buys_the_cross_back_above_oversold_and_exits_above_overbought():
    # 종가 100 99 98 97 → RSI(3)=0 · +2 → 50(30 을 올라섰다) · +3 → 76.5(70 위)
    s = flat([100, 99, 98, 97, 99, 102])
    spec = rules.build("rsi_reversal", {"n": 3, "oversold": 30, "overbought": 70})
    assert fires(spec.entry, s) == [4] and fires(spec.exit, s) == [5]


def test_rsi_bounds_must_leave_room_between_them():
    with pytest.raises(rules.RuleError) as err:
        rules.build("rsi_reversal", {"oversold": 45, "overbought": 40})
    assert err.value.code == "param_out_of_range"


# ── 볼린저 밴드 ───────────────────────────────────────────────────────────────────────
def test_bollinger_revert_buys_the_close_back_inside_the_lower_band():
    # 종가 100×5, 90, 96 (n=5 · k=1)
    #   봉 5: 창 100·100·100·100·90 → 평균 98 · 모표준편차 sqrt(80/5)=4 → 하단 94 > 종가 90 (밴드 아래)
    #   봉 6: 창 100·100·100·90·96 → 평균 97.2 · 편차 sqrt(76.8/5)=3.919 → 하단 93.28 < 종가 96 (다시 안으로)
    s = flat([100, 100, 100, 100, 100, 90, 96])
    spec = rules.build("bollinger", {"direction": "revert", "n": 5, "k": 1.0})
    assert fires(spec.entry, s) == [6]
    assert fires(spec.exit, s) == [4]                       # 청산 조건(종가 ≥ 중심선): 봉 4 뿐 — 봉 6 은 96 < 97.2


def test_bollinger_breakout_buys_the_close_above_the_upper_band():
    # 종가 100×5, 110, 101 → 봉 5: 평균 102 · 편차 4 → 상단 106 < 종가 110 · 봉 6: 평균 102.2 > 종가 101
    s = flat([100, 100, 100, 100, 100, 110, 101])
    spec = rules.build("bollinger", {"direction": "breakout", "n": 5, "k": 1.0})
    assert fires(spec.entry, s) == [5]
    assert fires(spec.exit, s) == [6]                       # 청산 조건: 종가가 중심선 아래


def test_bollinger_needs_at_least_five_bars_in_its_window():
    with pytest.raises(rules.RuleError) as err:
        rules.build("bollinger", {"n": 3})
    assert err.value.code == "param_out_of_range"


# ── 등록부 · 검증 ─────────────────────────────────────────────────────────────────────
def test_there_are_seven_templates_and_each_builds_with_its_defaults():
    assert set(rules.TEMPLATES) == {"opening_range_breakout", "vwap_cross", "volatility_breakout", "gap", "volume_surge",
                                    "rsi_reversal", "bollinger"}
    for kind in rules.TEMPLATES:
        spec = rules.build(kind, {})
        simulator.validate(spec, simulator.PositionRules(amount=1_000_000), simulator.CostAssumptions())


@pytest.mark.parametrize("kind, params, code", [
    ("macd_cross", {}, "unknown_kind"),
    ("opening_range_breakout", {"window": 5}, "unknown_param"),
    ("opening_range_breakout", {"minutes": 0}, "param_out_of_range"),
    ("opening_range_breakout", {"minutes": 2.5}, "param_not_integer"),
    ("opening_range_breakout", {"minutes": "30"}, "param_not_number"),
    ("volatility_breakout", {"k": 1.5}, "param_out_of_range"),
    ("volatility_breakout", {"k": True}, "param_not_number"),
    ("gap", {"direction": "sideways"}, "bad_choice"),
    ("bollinger", {"direction": 1}, "bad_choice"),
])
def test_a_bad_template_or_parameter_is_refused_with_a_reason(kind, params, code):
    with pytest.raises(rules.RuleError) as err:
        rules.build(kind, params)
    assert err.value.code == code


def test_resolve_fills_defaults_and_gives_one_canonical_setting():
    assert rules.resolve("opening_range_breakout", {}) == {"minutes": 30}
    assert rules.resolve("gap", {"gap_pct": 3}) == {"direction": "follow", "gap_pct": 3.0, "minutes": 15}
    assert rules.resolve("bollinger", {"k": 2}) == rules.resolve("bollinger", {"k": 2.0, "n": 20, "direction": "revert"})


def test_describe_tells_the_screen_everything_it_needs_and_speaks_in_sentences():
    listing = rules.describe()
    assert [t["kind"] for t in listing] == list(rules.TEMPLATES)
    for t in listing:
        assert t["label"] and isinstance(t["needs_prev"], bool) and t["summary"].endswith("니다.")
        assert all(note.endswith("니다.") and "—" not in note for note in t["notes"])
        for p in t["params"]:
            assert p["key"] and p["label"] and p["type"] in ("int", "float", "choice")
            if p["type"] == "choice":
                assert p["default"] in [c["value"] for c in p["choices"]] and all(c["label"] for c in p["choices"])
            else:
                assert p["min"] <= p["default"] <= p["max"]
    by_kind = {t["kind"]: t for t in listing}
    assert {k for k, t in by_kind.items() if t["needs_prev"]} == {"volatility_breakout", "gap"}
    assert any("다음 날" in n for n in by_kind["volatility_breakout"]["notes"])        # 널리 알려진 꼴과 다르다는 것을 말한다


def test_needs_prev_matches_what_the_built_trees_actually_use():
    for kind, template in rules.TEMPLATES.items():
        for params in ({}, *[{c.key: v} for c in template.params if isinstance(c, rules.Choice) for v in c.values]):
            spec = rules.build(kind, params)
            uses = any(expr.uses_prev(t) for t in (spec.entry, spec.entry_stop, spec.exit) if t is not None)
            assert uses == template.needs_prev, (kind, params)


# ── 성질: 앞보기 0 ─────────────────────────────────────────────────────────────────────
def _random_session(seed: int, n: int = 70) -> Session:
    rng = np.random.default_rng(seed)
    close = 10_000 + np.cumsum(rng.integers(-8, 9, n)) * 10.0
    open_ = np.concatenate([[close[0] + 150], close[:-1]])
    rows = [(o, max(o, c) + rng.integers(0, 4) * 10.0, min(o, c) - rng.integers(0, 4) * 10.0, c, float(rng.integers(0, 3_000)))
            for o, c in zip(open_, close)]
    return sess(rows, PrevDay(close=float(open_[0] - 300), high=float(open_[0] - 100), low=float(open_[0] - 400), basis="minute"))


def _cut(s: Session, k: int) -> Session:
    return Session(s.ticker, s.date, s.time[:k], s.open[:k], s.high[:k], s.low[:k], s.close[:k], s.volume[:k], s.source,
                   s.prev, s.market, s.instrument, s.name)


ALL_SETTINGS = [(kind, params) for kind, template in rules.TEMPLATES.items()
                for params in ({}, *[{c.key: v} for c in template.params if isinstance(c, rules.Choice) for v in c.values])]


@pytest.mark.parametrize("kind, params", ALL_SETTINGS, ids=[f"{k}:{p}" for k, p in ALL_SETTINGS])
def test_no_template_looks_ahead(kind, params):
    small = {"minutes": 5, "bars_below": 2, "bars": 5, "n": 5, "gap_pct": 1.0, "multiple": 1.5}
    spec = rules.build(kind, {**{k: v for k, v in small.items() if k in {p.key for p in rules.TEMPLATES[kind].params}}, **params})
    for seed in range(4):
        full_session = _random_session(seed)
        for tree in (t for t in (spec.entry, spec.entry_stop, spec.exit) if t is not None):
            full = expr.evaluate(tree, full_session)
            for k in (1, 6, 19, 40, 69):
                assert np.array_equal(expr.evaluate(tree, _cut(full_session, k)), full[:k], equal_nan=True), (kind, seed, k)
