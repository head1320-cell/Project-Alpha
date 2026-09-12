"""미상 드로다운을 ★소비자가 미상으로 부른다★ (P1-a 소비자측)

`drawdown.py` 가 `None` 을 만들어도 소비자가 `or 0` 으로 뭉개면 아무것도 달라지지
않는다. 이 파일이 못 박는 것:

    ★게이트웨이는 "통과" 라고 적지 않고 "확인 못 함" 이라고 적는다.★
    ★킬스위치는 못 본 항목을 이름으로 말한다.★
    ★그러면서 통과/차단 판정은 한 건도 바뀌지 않는다.★

마지막 줄이 핵심이다 — 안전 판정을 바꾸는 것은 CLAUDE.md §6 최우선 불변식 영역이라
이번 작업의 범위 밖이다. 라벨만 더한다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.execution.kill_switch import KillSwitch, KillSwitchConfig  # noqa: E402
from src.execution.risk_gateway import RiskGateway, RiskLimits  # noqa: E402

_ORDER = {"ticker": "005930", "side": "BUY", "quantity": 10, "price": 70_000,
          "strategy_id": 1}


def _state(**over) -> dict:
    base = {
        "equity_krw": 100_000_000, "cash_krw": 50_000_000,
        "positions": {}, "daily_turnover_krw": 0,
        "current_drawdown_pct": None, "cumulative_dd_pct": None,
        "drawdown_reason": "no_equity_history",
    }
    base.update(over)
    return base


def _gw() -> RiskGateway:
    return RiskGateway(engine=None, limits=RiskLimits(),
                       universe={"005930"}, bypass_market_hours=True)


# ═══════════════════════════════════════════════════════════════════════════
# ④ 게이트웨이 — 미상은 `checks_unverified`, 판정은 불변
# ═══════════════════════════════════════════════════════════════════════════

def test_unknown_drawdown_is_not_reported_as_passed():
    res = _gw().check(_ORDER, _state())
    assert "circuit_breaker" not in res.checks_passed, \
        "★확인하지 못한 것을 '통과' 라고 적었다★"
    joined = " ".join(res.checks_unverified)
    assert "circuit_breaker" in joined and "no_equity_history" in joined, res.checks_unverified


def test_the_verdict_is_unchanged_when_drawdown_is_unknown():
    """★골든★ 라벨을 더한 것이지 판정을 바꾼 것이 아니다."""
    res = _gw().check(_ORDER, _state())
    assert res.approved is True
    assert res.tier_failures == []
    assert res.rejected_reason is None


def test_a_known_drawdown_still_reports_passed():
    """★짝★ 알 때는 전과 똑같이 `checks_passed` 다(항상-unverified 구현 배제)."""
    res = _gw().check(_ORDER, _state(current_drawdown_pct=0.01, cumulative_dd_pct=0.02,
                                     drawdown_reason=None))
    assert "circuit_breaker" in res.checks_passed
    assert res.checks_unverified == []


def test_a_breaching_drawdown_still_rejects():
    """★라벨 추가가 탐지를 죽이지 않았다★ — 한도를 넘으면 여전히 거부."""
    res = _gw().check(_ORDER, _state(current_drawdown_pct=0.09, cumulative_dd_pct=0.02,
                                     drawdown_reason=None))
    assert res.approved is False
    assert any("일중 손실" in f for f in res.tier_failures), res.tier_failures


# ═══════════════════════════════════════════════════════════════════════════
# ⑤⑥ 킬스위치 — 못 본 것을 말하되, 볼 수 있으면 여전히 발동
# ═══════════════════════════════════════════════════════════════════════════

class _NeverActive(KillSwitch):
    """`is_active()` 는 DB 를 읽는다 — 여기서는 판정 로직만 본다."""

    def __init__(self):
        super().__init__(engine=None, audit_trail=None, config=KillSwitchConfig())

    def is_active(self) -> bool:
        return False


def test_unverified_checks_names_what_it_could_not_see():
    ks = _NeverActive()
    unv = ks.unverified_checks(_state(), regime_state=None)
    joined = " ".join(unv)
    assert "auto_dd" in joined and "auto_cb" in joined, unv
    assert "no_equity_history" in joined, "★사유가 실려야 한다★"
    assert "auto_risk" in joined, "국면 상태가 없으면 그것도 미상이다"


def test_unknown_drawdown_does_not_trigger():
    assert _NeverActive().should_auto_trigger(_state(), None) is None


def test_a_breaching_drawdown_still_triggers():
    """★짝★ 알 수 있으면 전과 똑같이 발동한다."""
    hit = _NeverActive().should_auto_trigger(
        _state(cumulative_dd_pct=0.20, current_drawdown_pct=0.0, drawdown_reason=None), None)
    assert hit is not None and hit[0] == "auto_dd", hit


def test_nothing_is_unverified_when_everything_is_known():
    """★짝★ 다 알면 미상 목록이 비어 있다."""
    unv = _NeverActive().unverified_checks(
        _state(current_drawdown_pct=0.01, cumulative_dd_pct=0.02, drawdown_reason=None),
        regime_state={"systemic_risk_score": 10})
    assert unv == (), unv


def test_api_failure_check_is_unaffected():
    """건드리지 않은 판정은 그대로다."""
    hit = _NeverActive().should_auto_trigger(_state(api_failure_count=9), None)
    assert hit is not None and hit[0] == "auto_api", hit


# ═══════════════════════════════════════════════════════════════════════════
# ③ 계좌 상태 생산자 — 0 을 만들지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def _live_engine():
    """실행 스키마만 올린 인메모리 DB — 브로커 없이 상태 생산자를 부른다."""
    from sqlalchemy import create_engine

    from src.execution.live_schemas import init_live_trading_schema
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return eng


def test_account_state_carries_none_and_a_reason():
    from src.execution import order_executor as oe

    class _FakeKIS:
        def get_balance(self):
            return {"evaluated_total": 100_000_000, "cash_krw": 10_000_000, "positions": []}

    ex = oe.OrderExecutor.__new__(oe.OrderExecutor)   # __init__ 우회(브로커 불필요)
    ex.kis = _FakeKIS()
    ex.engine = _live_engine()
    st = ex._fetch_account_state()
    assert st["current_drawdown_pct"] is None
    assert st["cumulative_dd_pct"] is None
    assert st["drawdown_reason"], "★사유 없는 미상은 금지★"
    assert st["equity_krw"] == 100_000_000, "드로다운만 미상이지 잔고는 실제 값이다"


def test_a_balance_failure_is_not_reported_as_zero_equity():
    from src.execution import order_executor as oe

    class _BoomKIS:
        def get_balance(self):
            raise RuntimeError("KIS 응답 없음")

    ex = oe.OrderExecutor.__new__(oe.OrderExecutor)
    ex.kis = _BoomKIS()
    ex.engine = _live_engine()
    st = ex._fetch_account_state()
    assert st["equity_krw"] is None, "★조회 실패와 '잔고 0' 은 다른 사실이다★"
    assert st["cash_krw"] is None
    assert "KIS 응답 없음" in (st.get("state_reason") or ""), st.get("state_reason")


@pytest.mark.parametrize("field", ["current_drawdown_pct", "cumulative_dd_pct"])
def test_the_hardcoded_zero_is_gone_from_the_source(field):
    """★소스 텍스트가 아니라 동작을 본다★ — 다만 이 상수만은 되돌아오기 쉬워 못 박는다."""
    import inspect

    from src.execution import order_executor as oe
    src = inspect.getsource(oe.OrderExecutor._fetch_account_state)
    assert f'"{field}":  0' not in src and f'"{field}": 0' not in src, \
        f"{field} 가 다시 0 으로 하드코딩됐다"


# ═══════════════════════════════════════════════════════════════════════════
# ★페일-클로즈드★ — 상태를 모르면 통과시키지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_an_unknown_account_state_is_rejected_not_crashed():
    """★예전에는 `equity_krw=0` 덕에 '우연히' 거부됐다.★

    `None` 으로 바꾸면서 곱셈이 터질 수 있었다 — 크래시는 거부가 아니다.
    결과는 전과 같아야 한다: **거부**, 다만 사유가 있는 거부.
    """
    res = _gw().check(_ORDER, _state(equity_krw=None, cash_krw=None,
                                     state_reason="fetch_failed: KIS 응답 없음"))
    assert res.approved is False
    assert any("계좌 상태 미상" in f for f in res.tier_failures), res.tier_failures
    assert any("KIS 응답 없음" in f for f in res.tier_failures), "★사유가 실려야 한다★"


def test_a_known_account_state_still_passes_tier1():
    """★짝★ 알 때는 전과 같이 진행한다(항상-거부 구현 배제)."""
    res = _gw().check(_ORDER, _state(current_drawdown_pct=0.0, cumulative_dd_pct=0.0,
                                     drawdown_reason=None))
    assert res.approved is True, res.tier_failures
