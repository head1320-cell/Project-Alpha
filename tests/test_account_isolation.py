"""BV6a — ★계좌 기록은 계좌끼리, 운영자와도 섞이지 않는다★.

BV6 은 사용자가 자기 증권 계좌로 SHADOW/PAPER 주문을 낸다. 실행기는 Stage13 `OrderExecutor` 를 계좌마다 하나 쓰는데,
주문·감사·킬스위치 표(`live_orders`·`live_audit_trail`·`live_kill_events`)는 하나다. 그래서:

  ① 운영자 표면(로그인만 있으면 열림 — `/live/orders`·`/orders/active`·`state-distribution`·`/audit`·`/kill-switch/events`)에
     계좌 주문·감사가 보이지 않는다 — 안 그러면 alice 의 주문이 아무 로그인 사용자에게 보인다.  짝: 운영자 기록은 보인다
  ② 하루 회전(위험 한도의 재료)은 자기 계좌 것만 센다
  ③ 계좌 A 비상 정지 → A 만 막힘 · B·운영자는 아님 · ★운영자(전역) 정지는 모든 계좌를 막는다★
  ④ A 의 정지는 A 의 미체결만 A 클라이언트로 취소한다(B·운영자 주문 그대로, B 클라이언트 호출 0)
  ⑤ 계좌 실행기는 운영자 에쿼티 이력을 쓰지 않는다 — 드로다운 미상 + 사유
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.execution.audit_trail import AuditTrail
from src.execution.kill_switch import KillSwitch, KillSwitchConfig
from src.execution.kis_client import MockKISClient
from src.execution.order_executor import ExecutionMode, OrderExecutor
from src.execution.risk_gateway import RiskGateway, RiskLimits

_SECRET = "account-isolation-test-secret-0123456789"
_SIG = {"strategy_id": 1, "ticker": "005930", "side": "BUY", "quantity": 1,
        "price": 71000.0, "order_type": "LIMIT"}


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    import src.data.backtest_runs as br
    monkeypatch.setattr(br, "_inited", False)   # 임시 DB 에서 만든 표 메모가 뒤 테스트로 새지 않게
    dbmod.reset_session()
    dbmod.init_db()
    import src.api.stage13_extensions as ext
    import src.api.stage13_routes as stage13
    import src.execution.kis_client as kc
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(ext, "_PRODUCTION_MODULES", {}, raising=False)

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        c.post("/api/v1/live/init-schema", headers=_admin(c))
        yield c

    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _admin(client) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login",
                      json={"username": "admin", "password": "frm123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _account_executor(account_id: str, kis=None, mode=ExecutionMode.PAPER) -> OrderExecutor:
    engine = dbmod.get_sync_engine()
    audit = AuditTrail(engine, account_id=account_id)
    return OrderExecutor(
        engine=engine, kis_client=kis or MockKISClient(),
        risk_gateway=RiskGateway(engine, limits=RiskLimits(), universe=set(), bypass_market_hours=True),
        audit_trail=audit, kill_switch=KillSwitch(engine, audit, KillSwitchConfig(), account_id=account_id),
        mode=mode, account_id=account_id)


def _tracker():
    """`/orders/active`·`/orders/state-distribution` 의 원천. 그 두 경로는 지금 `/orders/{client_order_id}` 에 가려
    닿지 않는다(경로 순서 — 별도 결함) — 그래서 같은 함수를 직접 부른다."""
    from src.engine.order_tracker import OrderStateMachine
    return OrderStateMachine(dbmod.get_sync_engine())


def _operator(client):
    import src.api.stage13_routes as stage13
    ex = stage13.get_executor()
    ex.set_mode(ExecutionMode.PAPER, actor="test")
    return ex


# ── ① 운영자 표면에 계좌 기록이 보이지 않는다 ──────────────────────────────

def test_account_orders_do_not_appear_on_operator_surfaces(client):
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    out = a.execute_signal(dict(_SIG), actor="alice")
    assert out["status"] == "SUBMITTED", out
    h = _admin(client)
    coid = out["client_order_id"]
    assert coid not in client.get("/api/v1/live/orders", headers=h).text
    assert coid not in str(_tracker().list_active_orders())
    assert _tracker().state_distribution() == {}
    audit = client.get("/api/v1/live/audit", headers=h).json()["events"]
    assert not any(e.get("actor") == "alice" for e in audit), "계좌 감사가 운영자 감사에 섞였다"


def test_operator_orders_still_appear_on_operator_surfaces(client):
    """★짝★ — 운영자 화면을 통째로 비우는 구현을 배제한다."""
    out = _operator(client).execute_signal(dict(_SIG), actor="admin")
    h = _admin(client)
    assert out["client_order_id"] in client.get("/api/v1/live/orders", headers=h).text
    assert out["client_order_id"] in str(_tracker().list_active_orders())
    assert _tracker().state_distribution()
    assert any(e.get("actor") == "admin" for e in client.get("/api/v1/live/audit", headers=h).json()["events"])


def test_an_account_sees_only_its_own_orders(client):
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    b = _account_executor("ba_bbbbbbbbbbbbbbbb")
    oa = a.execute_signal(dict(_SIG))["client_order_id"]
    ob = b.execute_signal(dict(_SIG))["client_order_id"]
    op = _operator(client).execute_signal(dict(_SIG))["client_order_id"]
    assert [o["client_order_id"] for o in a.list_orders()] == [oa]
    assert a.get_order(ob) is None and a.get_order(op) is None
    assert a.get_order(oa) is not None
    assert a.cancel_order(ob)["status"] == "not_found"


# ── ② 하루 회전은 자기 것만 ────────────────────────────────────────────────

def test_daily_turnover_counts_only_the_same_account(client):
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    _operator(client).execute_signal(dict(_SIG))
    assert a._fetch_account_state()["daily_turnover_krw"] == 0
    a.execute_signal(dict(_SIG))
    assert a._fetch_account_state()["daily_turnover_krw"] == pytest.approx(71000.0)


# ── ③ 비상 정지의 범위 ─────────────────────────────────────────────────────

def test_an_account_kill_stops_only_that_account(client):
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    b = _account_executor("ba_bbbbbbbbbbbbbbbb")
    op = _operator(client)
    a.kill_switch.trigger(source="manual", reason="A 만 멈춤", kis_client=a.kis, liquidation_mode="hold")
    assert a.kill_switch.is_active() is True
    assert b.kill_switch.is_active() is False
    assert op.kill_switch.is_active() is False
    assert a.execute_signal(dict(_SIG))["status"] == "REJECTED"
    assert b.execute_signal(dict(_SIG))["status"] == "SUBMITTED"


def test_the_operator_kill_stops_every_account(client):
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    op = _operator(client)
    op.kill_switch.trigger(source="manual", reason="전체 멈춤", kis_client=op.kis, liquidation_mode="hold")
    assert a.kill_switch.is_active() is True
    assert a.execute_signal(dict(_SIG))["status"] == "REJECTED"


def test_an_account_resolves_only_its_own_kill(client):
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    op = _operator(client)
    op.kill_switch.trigger(source="manual", reason="전체 멈춤", kis_client=op.kis, liquidation_mode="hold")
    assert a.kill_switch.resolve("alice")["status"] == "no_active_event"
    assert op.kill_switch.is_active() is True, "계좌가 운영자 정지를 풀었다"


# ── ④ 정지는 자기 미체결만 자기 클라이언트로 ───────────────────────────────

def _recording() -> MockKISClient:
    """취소 호출을 세는 mock — PAPER 가드가 클래스 이름으로 모의를 알아보므로 하위 클래스를 쓰지 않는다."""
    client = MockKISClient()
    client.cancelled = []
    client.cancel_order = lambda **k: client.cancelled.append(k.get("kis_order_no")) or {"msg": "ok"}
    return client


def test_an_account_kill_cancels_only_its_own_open_orders(client):
    ka, kb = _recording(), _recording()
    a = _account_executor("ba_aaaaaaaaaaaaaaaa", kis=ka)
    b = _account_executor("ba_bbbbbbbbbbbbbbbb", kis=kb)
    oa = a.execute_signal(dict(_SIG))["client_order_id"]
    ob = b.execute_signal(dict(_SIG))["client_order_id"]
    a.kill_switch.trigger(source="manual", reason="A 정지", kis_client=ka, liquidation_mode="hold")
    assert kb.cancelled == [], "A 의 정지가 B 클라이언트를 불렀다"
    assert a.get_order(oa)["status"] == "CANCELLED"
    assert b.get_order(ob)["status"] == "SUBMITTED"


# ── ⑤ 계좌 실행기는 운영자 에쿼티 이력을 쓰지 않는다 ─────────────────────────

def test_an_account_executor_does_not_borrow_the_operator_drawdown(client):
    state = _account_executor("ba_aaaaaaaaaaaaaaaa")._fetch_account_state()
    assert state["current_drawdown_pct"] is None
    assert "계좌" in (state["drawdown_reason"] or "")


def test_the_operator_executor_still_reads_its_history(client):
    """★짝★ — 운영자 경로의 드로다운 사유가 계좌 사유로 바뀌지 않았다."""
    state = _operator(client)._fetch_account_state()
    assert "계좌별" not in (state.get("drawdown_reason") or "")


def test_account_kill_events_do_not_appear_on_the_operator_list(client):
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    a.kill_switch.trigger(source="manual", reason="A 만 멈춤", kis_client=a.kis, liquidation_mode="hold")
    events = client.get("/api/v1/live/kill-switch/events", headers=_admin(client)).json()["events"]
    assert events == [], "계좌 정지가 운영자 정지 이력에 섞였다"


def test_an_account_that_stops_itself_during_a_global_stop_stays_stopped(client):
    """계좌가 운영자 전역 정지 중에 스스로 멈추면, 전역이 풀려도 계좌는 멈춘 채다."""
    a = _account_executor("ba_aaaaaaaaaaaaaaaa")
    op = _operator(client)
    op.kill_switch.trigger(source="manual", reason="전체 멈춤", kis_client=op.kis, liquidation_mode="hold")
    a.kill_switch.trigger(source="manual", reason="나도 멈춤", kis_client=a.kis, liquidation_mode="hold")
    op.kill_switch.resolve("admin")
    assert op.kill_switch.is_active() is False
    assert a.kill_switch.is_active() is True
