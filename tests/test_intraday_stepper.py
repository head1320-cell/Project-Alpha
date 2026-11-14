"""걸음 엔진 — 하루를 봉이 닫힐 때마다 다시 돌려 ★새로 생긴 체결 줄만★ 낸다 (W5b · 구현 계획 §2)

가동기(규칙 가동)의 뼈대다. 이 파일이 거는 성질은 하나다:

    ★걸음마다 낸 체결의 이어 붙임 = 그 하루를 한 번에 돌린 체결★ (줄 단위 · 순서까지)

이것이 깨지면 기록 전용 가동의 가상 체결이 백테스트와 달라진다 — 설계 §3 이 "다르면 결함"이라고 못 박은 것이다.

함께 거는 것:
  · 끝나지 않은 하루(`Day.final=False`)는 마지막 봉에서 강제로 청산하지 않는다 — 걸음마다 가짜 청산이 생기면 보유 한도가 걸린
    설정에서 ★다른 종목의 가짜 진입★까지 만든다(손으로 만든 표본)
  · `final` 의 기본값은 지금 동작이다(강제 청산) — 기존 결과가 바뀌지 않는다
  · 다시 돌린 결과가 이미 낸 줄과 다르면 조용히 덮지 않고 거절한다(`not_monotone`)
  · 시각이 뒤로 가거나 같은 시각을 두 번 주면 거절 · 끝난 뒤의 걸음은 거절 · 봉이 없는 시각은 빈 목록
"""
from __future__ import annotations

import numpy as np
import pytest

from src.engine.intraday import rules as templates
from src.engine.intraday import stepper as stepper_mod
from src.engine.intraday.simulator import CostAssumptions, Day, PositionRules, RuleSpec, simulate
from src.engine.intraday.stepper import StepError, Stepper
from src.engine.intraday.types import PrevDay, Session
from tests.test_intraday_simulator import DATE, RULES, SETUPS, C, I, _random_session, op, sess

COSTS = CostAssumptions(None, 1, 0.2)


def _drop(s: Session, gone: range) -> Session:
    """그 자리의 봉을 없앤다(거래가 없어 봉이 없는 분) — 종목마다 시각이 어긋난 하루를 만든다."""
    keep = np.array([i not in gone for i in range(len(s.time))])
    return Session(s.ticker, s.date, s.time[keep], s.open[keep], s.high[keep], s.low[keep], s.close[keep], s.volume[keep], s.source,
                   s.prev, s.market, s.instrument, s.name)


def _labels(*sessions: Session) -> list[str]:
    return sorted({str(t) for s in sessions for t in s.time})


def _walk(day: Day, rule, position, costs=COSTS, labels=None) -> tuple[list[dict], Stepper]:
    st = Stepper(day, rule, position, costs, rules=RULES)
    out: list[dict] = []
    for label in labels if labels is not None else _labels(*day.sessions.values()):
        out += st.step(label)
    out += st.finish()
    return out, st


def _batch(day: Day, rule, position, costs=COSTS) -> list[dict]:
    return simulate([day], rule, position, costs, rules=RULES)["fills"]


def _day(*sessions: Session) -> Day:
    return Day(DATE, {s.ticker: s for s in sessions})


# ── 성질: 걸음의 이어 붙임 = 한 번에 돌린 하루 ─────────────────────────────────────

@pytest.mark.parametrize("setup", range(len(SETUPS)))
def test_stepping_through_a_day_emits_exactly_the_batch_fills(setup):
    rule, position = SETUPS[setup]
    total = 0
    for seed in range(6):
        a = _random_session(seed, "000660")
        b = _drop(_random_session(seed + 100, "005930"), range(20 + seed, 31 + seed))     # 열한 분 동안 봉이 없는 종목
        day = _day(a, b)
        walked, st = _walk(day, rule, position)
        batch = _batch(day, rule, position)
        assert walked == batch, (setup, seed)
        assert st.fills == batch and len(st.events) == len(batch)
        total += len(batch)
    assert total > 0, "이 설정은 체결을 하나도 내지 않았다 — 공허한 성질 시험이다"


def _with_prev(s: Session, close: float) -> Session:
    return Session(s.ticker, s.date, s.time, s.open, s.high, s.low, s.close, s.volume, s.source,
                   PrevDay(close, close + 80.0, close - 80.0, "minute"), s.market, s.instrument, s.name)


#: 틀마다 ★체결이 실제로 나는★ 매개변수와 전일 종가 — 기본값으로는 임의 표본에서 한 줄도 나지 않는 틀이 있다(갭 2% · 거래량 3배).
#: 나무의 꼴은 같고 상수만 다르다. 한 줄도 나지 않으면 성질이 공허하므로 아래 시험이 그것을 실패로 본다.
TEMPLATE_CASES = [
    ("opening_range_breakout", {"minutes": 10}, None),
    ("vwap_cross", {}, None),
    ("volatility_breakout", {"k": 0.3}, None),
    ("gap", {"direction": "follow", "gap_pct": 0.5, "minutes": 5}, 9_900.0),       # 시가가 전일 종가보다 1% 위
    ("gap", {"direction": "fade", "gap_pct": 0.5}, 10_200.0),                      # 시가가 전일 종가보다 2% 아래
    ("volume_surge", {"bars": 3, "multiple": 1.5}, None),
    ("rsi_reversal", {"n": 5}, None),
    ("bollinger", {"direction": "revert", "n": 10, "k": 1.5}, None),
    ("bollinger", {"direction": "breakout", "n": 10, "k": 1.5}, None),
]


def test_the_template_cases_cover_every_template():
    assert {kind for kind, _, _ in TEMPLATE_CASES} == set(templates.TEMPLATES)


@pytest.mark.parametrize("kind, params, prev_close", TEMPLATE_CASES, ids=[f"{k}-{i}" for i, (k, _, _) in enumerate(TEMPLATE_CASES)])
def test_every_rule_template_steps_to_its_batch_fills(kind, params, prev_close):
    rule = templates.build(kind, params)
    position = PositionRules(amount=1_000_000, stop_pct=0.5, target_pct=0.8, max_entries_per_ticker=3, max_open_positions=1)
    total = 0
    for seed in range(8):
        a = _random_session(seed, "000660", n=120)
        b = _drop(_random_session(seed + 50, "005930", n=120), range(40, 52))
        if prev_close is not None:
            a, b = _with_prev(a, prev_close), _with_prev(b, prev_close)
        day = _day(a, b)
        walked, _ = _walk(day, rule, position)
        assert walked == _batch(day, rule, position), (kind, seed)
        total += len(walked)
    assert total > 0, f"틀 {kind}{params} 은 이 표본에서 체결을 하나도 내지 않았다 — 표본을 바꿔야 성질이 걸린다"


def test_a_step_returns_only_the_rows_that_are_new():
    rule, position = SETUPS[0]
    day = _day(_random_session(1, "000660"))
    st = Stepper(day, rule, position, COSTS, rules=RULES)
    seen = 0
    for label in _labels(*day.sessions.values()):
        new = st.step(label)
        assert st.fills[seen:] == new
        assert all(f["executed_at"].endswith(f"{label[:2]}:{label[2:4]}:{label[4:6]}") for f in new)   # 새 줄은 그 봉의 것이다
        seen += len(new)
    assert seen > 0


# ── 끝나지 않은 하루 ──────────────────────────────────────────────────────────

ENTER = RuleSpec(entry=op("cross_up", I("close"), C(10_050)))            # 들어가면 스스로 나오지 않는다
HOLD = PositionRules(amount=1_000_000)
ROWS = [("090000", 10_000, 10_020, 9_990, 10_000, 1_000), ("090100", 10_000, 10_060, 10_000, 10_060, 1_000),
        ("090200", 10_070, 10_100, 10_060, 10_090, 1_000), ("090300", 10_090, 10_120, 10_080, 10_110, 1_000),
        ("090400", 10_110, 10_130, 10_100, 10_120, 1_000)]


def test_the_default_day_is_final_and_still_closes_on_its_last_bar():
    assert Day(DATE, {}).final is True
    out = simulate([_day(sess(ROWS[:3]))], ENTER, HOLD, COSTS, rules=RULES)
    assert [e["kind"] for e in out["events"]] == ["entry_signal", "session_end"]


def test_an_unfinished_day_does_not_close_the_position_on_its_last_bar():
    s = sess(ROWS[:3])
    open_ended = simulate([Day(DATE, {s.ticker: s}, final=False)], ENTER, HOLD, COSTS, rules=RULES)
    closed = simulate([Day(DATE, {s.ticker: s})], ENTER, HOLD, COSTS, rules=RULES)
    assert [e["kind"] for e in open_ended["events"]] == ["entry_signal"]
    assert open_ended["fills"] == closed["fills"][:1]                   # 진입 줄은 한 글자도 다르지 않다


def test_a_signal_on_the_last_bar_so_far_fills_on_the_next_step():
    """신호 봉이 '지금까지의 마지막 봉'인 걸음에서는 체결이 없고, 다음 걸음에서 그 다음 봉의 시가에 체결된다."""
    day = _day(sess(ROWS))
    st = Stepper(day, ENTER, HOLD, COSTS, rules=RULES)
    assert st.step("090000") == [] and st.step("090100") == []          # 09:01 봉이 신호 봉이다(종가가 10,050 을 넘었다)
    new = st.step("090200")
    assert [(f["side"], f["executed_at"], f["price"]) for f in new] == [("buy", f"{DATE} 09:02:00", 10_080.0)]   # 다음 봉 시가 + 한 틱


def test_no_session_end_row_appears_before_the_day_is_finished():
    day = _day(sess(ROWS))
    st = Stepper(day, ENTER, HOLD, COSTS, rules=RULES)
    for label in ("090000", "090100", "090200", "090300", "090400"):
        st.step(label)
        assert "session_end" not in st.events
    last = st.finish()
    assert st.events == ["entry_signal", "session_end"]
    assert [(f["side"], f["executed_at"], f["price"]) for f in last] == [("sell", f"{DATE} 09:04:00", 10_110.0)]   # 마지막 봉 종가 − 한 틱


def test_a_gap_in_one_tickers_bars_does_not_free_its_slot_for_another():
    """★가짜 청산이 가짜 진입을 만드는 표본★ — 보유 한도 1. A 는 09:02 에 들어가고 09:03 ~ 09:07 에는 봉이 없다.
    B 는 09:04 봉이 신호 봉이라 09:05 에 들어가려 한다. 한 번에 돌리면 A 가 아직 들고 있어 B 는 막힌다.
    걸음마다 '마지막 봉이면 청산'을 하면 09:05 의 걸음에서 A 가 09:02 에 청산된 것처럼 보여 B 가 들어간다."""
    a = sess([ROWS[0], ROWS[1], ROWS[2], ("090800", 10_090, 10_100, 10_080, 10_090, 1_000)], ticker="000660")
    b = sess([("090000", 10_000, 10_010, 9_990, 10_000, 1_000), ("090300", 10_000, 10_020, 9_990, 10_010, 1_000),
              ("090400", 10_020, 10_070, 10_010, 10_060, 1_000), ("090500", 10_070, 10_090, 10_060, 10_080, 1_000),
              ("090600", 10_080, 10_090, 10_070, 10_080, 1_000)], ticker="005930")
    position = PositionRules(amount=1_000_000, max_open_positions=1)
    day = _day(a, b)
    batch = simulate([day], ENTER, position, COSTS, rules=RULES)
    assert [(f["symbol"], f["side"]) for f in batch["fills"]] == [("000660", "buy"), ("000660", "sell")]   # B 는 한 번도 들어가지 못했다
    assert batch["assumptions"].get("entry_blocked_max_open") == 1
    walked, st = _walk(day, ENTER, position)
    assert walked == batch["fills"]
    assert [f["symbol"] for f in st.fills] == ["000660", "000660"]


# ── 거절 ────────────────────────────────────────────────────────────────────

def test_time_cannot_stand_still_or_run_backwards():
    st = Stepper(_day(sess(ROWS)), ENTER, HOLD, COSTS, rules=RULES)
    st.step("090100")
    for bad in ("090100", "090000"):
        with pytest.raises(StepError) as e:
            st.step(bad)
        assert e.value.code == "out_of_order"
    assert st.step("090200")                                            # 거절은 상태를 망가뜨리지 않는다


def test_nothing_steps_after_the_day_is_finished():
    st = Stepper(_day(sess(ROWS)), ENTER, HOLD, COSTS, rules=RULES)
    st.step("090400")
    st.finish()
    for call in (lambda: st.step("090500"), st.finish):
        with pytest.raises(StepError) as e:
            call()
        assert e.value.code == "finished"


def test_a_time_without_bars_emits_nothing_and_a_day_never_stepped_finishes_empty():
    st = Stepper(_day(sess(ROWS)), ENTER, HOLD, COSTS, rules=RULES)
    assert st.step("085900") == []                                       # 장 시작 전
    assert Stepper(_day(sess(ROWS)), ENTER, HOLD, COSTS, rules=RULES).finish() == []


def test_a_rerun_that_disagrees_with_what_was_already_emitted_is_refused_not_overwritten(monkeypatch):
    st = Stepper(_day(sess(ROWS)), ENTER, HOLD, COSTS, rules=RULES)
    st.step("090200")
    assert len(st.fills) == 1
    real = stepper_mod.simulate

    def drifting(days, *a, **kw):
        out = real(days, *a, **kw)
        out["fills"][0] = {**out["fills"][0], "price": out["fills"][0]["price"] + 10}     # 앞에서 낸 줄이 달라졌다
        return out

    monkeypatch.setattr(stepper_mod, "simulate", drifting)
    with pytest.raises(StepError) as e:
        st.step("090300")
    assert e.value.code == "not_monotone" and len(st.fills) == 1          # 이미 낸 줄을 고치지 않았다
    # 거절은 시각을 먹지 않는다 — 같은 봉을 다시 주면 다시 본다(뒤로 간 시각이라고 하지 않는다)
    with pytest.raises(StepError) as again:
        st.step("090300")
    assert again.value.code == "not_monotone"
    monkeypatch.setattr(stepper_mod, "simulate", real)
    assert st.step("090300") == [] and len(st.fills) == 1


def test_rows_handed_out_are_copies_and_changing_them_does_not_change_what_was_emitted():
    st = Stepper(_day(sess(ROWS)), ENTER, HOLD, COSTS, rules=RULES)
    new = st.step("090200")
    kept = dict(st.fills[0])
    new[0]["price"] = 1.0                                                # 받은 쪽이 고쳐도
    assert st.fills[0] == kept                                           # 낸 기록은 그대로다
    assert st.step("090300") == []                                       # 다음 걸음이 그것 때문에 어긋나지 않는다


def test_an_invalid_setting_is_refused_when_the_stepper_is_made_not_at_the_first_bar():
    from src.engine.intraday.simulator import SimError
    with pytest.raises(SimError):
        Stepper(_day(sess(ROWS)), RuleSpec(), HOLD, COSTS, rules=RULES)   # 진입 조건이 없다


def test_the_stepper_carries_the_days_own_notes_into_every_rerun():
    """봉을 준비한 쪽이 건너뛴 종목과 '장 운영 시간이 다른 날' 표시는 걸음마다 그대로 간다 — 그런 날은 한 줄도 내지 않는다."""
    s = sess(ROWS)
    shifted = Day(DATE, {s.ticker: s}, shifted=True)
    walked, _ = _walk(shifted, ENTER, HOLD, labels=[r[0] for r in ROWS])
    assert walked == [] == simulate([shifted], ENTER, HOLD, COSTS, rules=RULES)["fills"]


def test_previous_day_values_survive_the_cut():
    prev = PrevDay(close=10_000.0, high=10_100.0, low=9_900.0, basis="minute")
    rule = RuleSpec(entry_stop=op("add", I("day_open"), op("mul", C(0.5), op("sub", I("prev_high"), I("prev_low")))))
    day = _day(sess(ROWS, prev=prev))
    walked, _ = _walk(day, rule, PositionRules(amount=1_000_000))
    assert walked == _batch(day, rule, PositionRules(amount=1_000_000)) and walked
