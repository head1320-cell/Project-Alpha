"""AF — 킬스위치가 ★자기 상태를 정직하게 말한다★.

셋을 고정한다:

  ① `gradual` 은 1/5 만 팔면서 **청산 완료로 보고했다** — 감사 테이블
     `live_kill_events.n_positions_closed` 까지 그 거짓이 갔다.
  ② `auto_api` 가 `미상` 을 `0` 으로 읽어 **구조적으로 발동할 수 없었고**,
     `unverified_checks()` 목록에도 없어 **못 재고 있다는 사실조차** 보이지 않았다.
  ③ 무엇이 무장됐는지 아는 것은 백그라운드 데몬뿐이고 운영자는 몰랐다.

★주문 로직은 바꾸지 않는다★ — 여전히 1/5 을 판다. 바뀌는 것은 **무엇을 팔았다고
말하는가**뿐이다.
"""
from __future__ import annotations

import pytest

from src.execution.kill_switch import KillSwitch, KillSwitchConfig


class _FakeKIS:
    """결정론적 가짜 브로커. ★`pytest.skip` 에 기대지 않는다★(AE 의 교훈)."""

    def __init__(self, positions: list[dict] | None = None, fail: set[str] | None = None):
        self._positions = positions if positions is not None else [
            {"ticker": "005930", "quantity": 100, "eval_amount": 7_000_000,
             "current_price": 70_000},
        ]
        self._fail = fail or set()
        self.orders: list[dict] = []

    def get_balance(self) -> dict:
        return {"positions": list(self._positions)}

    def place_order(self, ticker: str, side: str, quantity: int, order_type: str):
        if ticker in self._fail:
            raise RuntimeError("브로커 거부(테스트)")
        self.orders.append({"ticker": ticker, "side": side, "quantity": quantity})
        return {"order_no": f"T-{len(self.orders)}"}


@pytest.fixture()
def ks(monkeypatch) -> KillSwitch:
    """엔진·감사 없이 판정 로직만 — 청산은 DB 를 타지 않는다.

    ★`is_active()` 를 명시적으로 False 로 고정한다★ — `engine=None` 이면 조회가
    실패해 페일세이프로 `True` 가 나오고(의도된 동작), 그러면 `should_auto_trigger`
    가 *"이미 발동 중"* 으로 **무조건 `None`** 을 돌려준다. 그대로 두면
    "발동하지 않는다" 계열 테스트가 **엉뚱한 이유로 통과**한다.
    """
    switch = KillSwitch(engine=None, audit_trail=None, config=KillSwitchConfig())
    monkeypatch.setattr(switch, "is_active", lambda: False)
    return switch


def test_the_failsafe_still_treats_a_db_failure_as_active():
    """★페일세이프를 없애지 않았다★ — 위 fixture 가 가린 동작을 여기서 고정한다."""
    broken = KillSwitch(engine=None, audit_trail=None, config=KillSwitchConfig())
    assert broken.is_active() is True
    # 이미 발동 중으로 보므로 자동 트리거는 돌지 않는다.
    assert broken.should_auto_trigger({"api_failure_count": 999}, None) is None


# ── ① ★gradual 이 청산됐다고 말하지 않는다★ ─────────────────────────────

def test_gradual_does_not_count_a_partial_sale_as_closed(ks):
    """★이 파일의 핵심★ — 1/5 만 판 포지션은 청산된 것이 아니다."""
    kis = _FakeKIS()
    out = ks._liquidate_positions(kis, mode="gradual")
    assert out["closed"] == 0, "부분 매도를 청산으로 셌다"


def test_gradual_records_the_remaining_quantity_and_a_reason(ks):
    out = ks._liquidate_positions(_FakeKIS(), mode="gradual")
    assert len(out["partial"]) == 1
    row = out["partial"][0]
    assert row["ticker"] == "005930"
    assert row["sold_qty"] == 20        # 100 // 5
    assert row["remaining_qty"] == 80   # ★남은 80% 가 숫자로 보인다★
    assert row["reason"], "부분 매도에 사유가 없다"


def test_gradual_is_reported_as_incomplete(ks):
    out = ks._liquidate_positions(_FakeKIS(), mode="gradual")
    assert out["complete"] is False
    assert out["note"], "미완료인데 사유가 없다"


def test_immediate_does_close_the_position(ks):
    """★짝★ — 언제나 partial 로 접는 구현을 배제한다."""
    out = ks._liquidate_positions(_FakeKIS(), mode="immediate")
    assert out["closed"] == 1
    assert out["partial"] == []
    assert out["complete"] is True


def test_no_positions_is_complete_not_incomplete(ks):
    """★짝★ — 언제나 complete=False 를 내는 구현을 배제한다."""
    out = ks._liquidate_positions(_FakeKIS(positions=[]), mode="gradual")
    assert out["complete"] is True
    assert out["closed"] == 0 and out["partial"] == []


def test_a_rejected_order_goes_to_failed_with_a_reason(ks):
    """실패는 청산도 부분 매도도 아니다 — 세 번째 상태다."""
    kis = _FakeKIS(fail={"005930"})
    out = ks._liquidate_positions(kis, mode="immediate")
    assert out["closed"] == 0
    assert out["partial"] == []
    assert len(out["failed"]) == 1
    assert out["failed"][0]["reason"]
    assert out["complete"] is False


# ── ★주문 로직은 바뀌지 않았다★ ─────────────────────────────────────────

def test_gradual_still_sells_exactly_one_fifth(ks):
    """★불변★ — 회계만 고쳤다. 파는 수량이 바뀌면 그것은 다른 작업이다."""
    kis = _FakeKIS()
    ks._liquidate_positions(kis, mode="gradual")
    assert [o["quantity"] for o in kis.orders] == [20]


def test_immediate_still_sells_the_whole_position(ks):
    kis = _FakeKIS()
    ks._liquidate_positions(kis, mode="immediate")
    assert [o["quantity"] for o in kis.orders] == [100]


def test_a_tiny_position_still_sells_at_least_one_share(ks):
    """`max(1, qty // 5)` 관용구 보존 — 4주면 1주를 판다."""
    kis = _FakeKIS(positions=[{"ticker": "A", "quantity": 4, "eval_amount": 1000,
                               "current_price": 250}])
    out = ks._liquidate_positions(kis, mode="gradual")
    assert kis.orders[0]["quantity"] == 1
    assert out["partial"][0]["remaining_qty"] == 3


# ── ② ★auto_api 의 미상을 0 으로 읽지 않는다★ ─────────────────────────

def test_an_absent_api_failure_count_does_not_fire(ks):
    """★핵심★ — 아무도 기록하지 않는 값을 0 으로 읽어 '정상' 이라 하지 않는다."""
    assert ks.should_auto_trigger({}, None) is None


def test_an_absent_api_failure_count_is_reported_as_unverified(ks):
    """★그리고 못 재고 있다는 사실이 보인다★ — P1-a 가 drawdown 에 한 것과 같다."""
    unverified = ks.unverified_checks({}, None)
    assert any("auto_api" in u for u in unverified), unverified
    assert any("기록" in u for u in unverified if "auto_api" in u)


def test_a_high_api_failure_count_does_fire(ks):
    """★짝★ — 항상-미상 구현을 배제한다."""
    out = ks.should_auto_trigger(
        {"api_failure_count": ks.config.api_failure_threshold}, None)
    assert out is not None and out[0] == "auto_api"


def test_an_absent_count_is_not_read_as_zero_even_at_a_zero_threshold(ks):
    """★변이 h 를 죽인다★ — `.get(…, 0)` 과 `is not None` 을 가르는 유일한 관측점.

    임계가 0 이면 `.get(…, 0)` 판본은 **재지도 않은 값으로 킬스위치를 발동시킨다**.
    미상을 건너뛰는 판본은 발동하지 않는다. 임계 0 은 인위적이지만, 두 구현이
    **실제로 다르게 동작하는 자리**가 여기뿐이다.
    """
    ks.config.api_failure_threshold = 0
    assert ks.should_auto_trigger({}, None) is None, "미상을 0 으로 읽어 발동했다"


def test_a_measured_zero_does_fire_at_a_zero_threshold(ks):
    """★짝★ — 미상은 건너뛰지만 **측정된 0** 은 임계 검사를 실제로 받는다."""
    ks.config.api_failure_threshold = 0
    out = ks.should_auto_trigger({"api_failure_count": 0}, None)
    assert out is not None and out[0] == "auto_api"


def test_a_low_api_failure_count_neither_fires_nor_is_unverified(ks):
    """★짝★ — 0 은 '측정된 0' 이다. 미상과 다르다."""
    state = {"api_failure_count": 0}
    assert ks.should_auto_trigger(state, None) is None
    assert not any("auto_api" in u for u in ks.unverified_checks(state, None))


# ── ③ ★무엇이 무장됐나★ ────────────────────────────────────────────────

_ALL_TRIGGERS = {"auto_dd", "auto_cb", "auto_risk", "auto_api"}


def test_an_empty_state_leaves_every_trigger_inoperable(ks):
    out = ks.trigger_readiness({}, None)
    assert {t["trigger"] for t in out["inoperable"]} == _ALL_TRIGGERS
    assert out["armed"] == []
    assert all(t["reason"] for t in out["inoperable"]), "사유 없는 불능"


def test_a_complete_state_arms_every_trigger(ks):
    """★짝★ — 항상-inoperable 구현을 배제한다."""
    out = ks.trigger_readiness(
        {"cumulative_dd_pct": -0.01, "current_drawdown_pct": -0.005,
         "api_failure_count": 0},
        {"systemic_risk_score": 10})
    assert {t["trigger"] for t in out["armed"]} == _ALL_TRIGGERS
    assert out["inoperable"] == []


def test_armed_and_inoperable_cover_every_trigger(ks):
    """★전수★ — 트리거 하나가 어느 목록에도 없으면 조용히 사라진 것이다."""
    for state, regime in [
        ({}, None),
        ({"cumulative_dd_pct": -0.01}, None),
        ({"api_failure_count": 3}, {"systemic_risk_score": 5}),
    ]:
        out = ks.trigger_readiness(state, regime)
        covered = {t["trigger"] for t in out["armed"]} | {
            t["trigger"] for t in out["inoperable"]}
        assert covered == _ALL_TRIGGERS, f"{state}: {covered}"


def test_the_summary_counts_both_sides(ks):
    out = ks.trigger_readiness({"api_failure_count": 0}, None)
    assert "1" in out["summary"] and "3" in out["summary"], out["summary"]


def test_readiness_is_built_on_unverified_checks_not_a_second_judgement(ks):
    """★같은 사실을 두 곳에서 판정하지 않는다★ — 불능 목록이 미검증과 일치한다."""
    state, regime = {"cumulative_dd_pct": -0.02}, None
    unverified = ks.unverified_checks(state, regime)
    inoperable = {t["trigger"] for t in ks.trigger_readiness(state, regime)["inoperable"]}
    named_in_unverified = {u.split(":")[0] for u in unverified}
    assert inoperable == named_in_unverified
