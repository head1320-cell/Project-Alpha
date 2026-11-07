"""AQ3 — 두 생산자가 ★관측을 싣는다★ (동작 0줄)

`should_auto_trigger` 는 한 줄도 바뀌지 않는다. 바뀌는 것은 `account_state` 에
**재료가 도착하는가**뿐이다.

★기존 계약을 깨지 않는다★(`tests/test_kill_switch_honesty.py`):

    키가 **없거나 `None`** 이면 미상 → 발동하지 않고 `unverified` 에 뜬다
    **측정된 `0`** 은 임계 0 에서도 발동한다

그래서 ★미상일 때 `api_failure_count` 를 0 으로 채우지 않는다★ — 채우면 그
계약이 조용히 무너진다.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.domain.api_health import (  # noqa: E402
    BREAKER_CLOSED,
    BREAKER_OPEN,
    SOURCE_BROKER,
    SOURCE_MOCK,
    SOURCE_NO_CLIENT,
)
from src.execution.api_failure_probe import observe_into  # noqa: E402
from src.execution.live_schemas import init_live_trading_schema  # noqa: E402


class _Breaker:
    def __init__(self, failure_count=0, state="CLOSED"):
        self.failure_count = failure_count
        self.state = state


class _BrokerClient:
    """breaker 를 단 브로커 클라이언트 — 실물 `KISClient` 와 같은 모양."""

    def __init__(self, breaker=None, balance=None, raises=False):
        self.circuit_breaker = breaker or _Breaker()
        self._balance = balance or {"evaluated_total": 1_000_000,
                                    "cash_krw": 500_000, "positions": []}
        self._raises = raises

    def get_balance(self):
        if self._raises:
            raise RuntimeError("KIS 조회 실패(테스트)")
        return dict(self._balance)


# ── ★관측일 때만 숫자 키가 생긴다★ ──────────────────────────────────────

def test_a_broker_reading_puts_the_count_into_the_state():
    state = observe_into({}, _BrokerClient(_Breaker(failure_count=4)))
    assert state["api_failure_count"] == 4
    assert state["api_failure_observation"]["source"] == SOURCE_BROKER


def test_a_mock_reading_leaves_the_count_key_absent():
    """★이 프로그램의 핵심 계약★ — 미상을 0 으로 채우면 킬스위치가 속는다."""
    from src.execution.kis_client import MockKISClient
    state = observe_into({}, MockKISClient())
    assert "api_failure_count" not in state
    obs = state["api_failure_observation"]
    assert obs["source"] == SOURCE_MOCK and obs["reason"]


def test_a_measured_zero_does_reach_the_state():
    """★짝★ — 잰 0 은 관측이므로 키가 생긴다."""
    state = observe_into({}, _BrokerClient(_Breaker(failure_count=0)))
    assert state["api_failure_count"] == 0


def test_the_observation_is_always_present_even_when_unobserved():
    """★재지 못했다는 사실도 기록이다★ — 블록은 언제나 실린다."""
    from src.execution.kis_client import MockKISClient
    assert observe_into({}, MockKISClient())["api_failure_observation"]


def test_observe_into_does_not_discard_existing_keys():
    state = observe_into({"equity_krw": 1}, _BrokerClient(_Breaker(1)))
    assert state["equity_krw"] == 1 and state["api_failure_count"] == 1


# ── 킬스위치가 실제로 그 재료로 판정한다 ─────────────────────────────────

def test_the_kill_switch_arms_on_a_broker_reading():
    """★실물 — `auto_api` 가 처음으로 무장된다★ (판정 코드는 0줄 바뀌었다)"""
    from src.execution.kill_switch import KillSwitch, KillSwitchConfig
    ks = KillSwitch(engine=None, audit_trail=None, config=KillSwitchConfig())
    state = observe_into({"cumulative_dd_pct": None, "current_drawdown_pct": None},
                         _BrokerClient(_Breaker(failure_count=0)))
    assert not any("auto_api" in u for u in ks.unverified_checks(state, None))


def test_the_kill_switch_fires_at_the_threshold():
    """연속 실패가 임계에 닿으면 `auto_api` 가 발동 대상이 된다."""
    from src.execution.kill_switch import KillSwitch, KillSwitchConfig

    class _NeverActive(KillSwitch):
        def is_active(self):
            return False

    ks = _NeverActive(engine=None, audit_trail=None, config=KillSwitchConfig())
    state = observe_into({}, _BrokerClient(
        _Breaker(failure_count=ks.config.api_failure_threshold)))
    hit = ks.should_auto_trigger(state, None)
    assert hit is not None and hit[0] == "auto_api"


def test_the_kill_switch_stays_unverified_on_a_mock_reading():
    """★짝★ — mock 환경에서는 무장되지 않는다(합성값으로 켜지 않는다)."""
    from src.execution.kill_switch import KillSwitch, KillSwitchConfig
    from src.execution.kis_client import MockKISClient
    ks = KillSwitch(engine=None, audit_trail=None, config=KillSwitchConfig())
    state = observe_into({}, MockKISClient())
    assert any("auto_api" in u for u in ks.unverified_checks(state, None))


# ── 생산자 ① 주문 경로 ────────────────────────────────────────────────────

def _executor(kis):
    from src.execution.audit_trail import AuditTrail
    from src.execution.kill_switch import KillSwitch
    from src.execution.order_executor import OrderExecutor
    from src.execution.risk_gateway import RiskGateway
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return OrderExecutor(engine=eng, kis_client=kis,
                         risk_gateway=RiskGateway(eng),
                         audit_trail=AuditTrail(eng),
                         kill_switch=KillSwitch(eng, None))


def test_the_order_path_carries_the_observation():
    state = _executor(_BrokerClient(_Breaker(failure_count=2)))._fetch_account_state()
    assert state["api_failure_count"] == 2
    assert state["api_failure_observation"]["breaker_state"] == BREAKER_CLOSED


def test_the_order_path_carries_it_even_when_the_balance_call_fails():
    """★조회가 실패한 순간이야말로 이 숫자가 가장 필요한 때다★

    예전 실패 분기는 드로다운만 `None` + 사유로 돌려줬다. KIS 가 죽어서 실패한
    것이라면 그 실패는 방금 breaker 에 기록됐고, 그 값을 싣지 않으면 `auto_api`
    는 **정작 장애 중에** 미상으로 남는다.
    """
    kis = _BrokerClient(_Breaker(failure_count=5, state="OPEN"), raises=True)
    state = _executor(kis)._fetch_account_state()
    assert state["equity_krw"] is None          # 기존 계약(조회 실패 ≠ 잔고 0)
    assert state["api_failure_count"] == 5
    assert state["api_failure_observation"]["breaker_state"] == BREAKER_OPEN
    assert state["api_failure_observation"]["blocking"] is True


def test_the_order_path_with_a_mock_client_has_no_count():
    from src.execution.kis_client import MockKISClient
    state = _executor(MockKISClient())._fetch_account_state()
    assert "api_failure_count" not in state
    assert state["api_failure_observation"]["source"] == SOURCE_MOCK


# ── 생산자 ② 감시 루프 ────────────────────────────────────────────────────

def test_the_monitor_carries_the_observation_without_a_client(monkeypatch):
    """★감시는 브로커를 만들지 않는다★(AI 의 경계) — 없으면 `no_client` 다."""
    import src.execution.kis_client as kc
    from src.startup.lifecycle import _monitor_account_state
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    state = _monitor_account_state()
    assert "api_failure_count" not in state
    assert state["api_failure_observation"]["source"] == SOURCE_NO_CLIENT


def test_the_monitor_reads_an_existing_singleton(monkeypatch):
    """★짝★ — 싱글턴이 이미 있으면 읽는다(만들지는 않는다)."""
    import src.execution.kis_client as kc
    from src.startup.lifecycle import _monitor_account_state
    monkeypatch.setattr(kc, "_kis_singleton", _BrokerClient(_Breaker(3)),
                        raising=False)
    assert _monitor_account_state()["api_failure_count"] == 3


@pytest.mark.parametrize("producer", ["order", "monitor"])
def test_both_producers_use_the_same_helper(producer):
    """★두 벌로 만들지 않았다★ — 한쪽만 고쳐도 조용해지는 것을 막는다."""
    import ast
    import pathlib
    rel = ("src/execution/order_executor.py" if producer == "order"
           else "src/startup/lifecycle.py")
    tree = ast.parse(pathlib.Path(rel).read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "observe_into" in called, rel
