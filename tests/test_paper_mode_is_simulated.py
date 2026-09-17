"""★PAPER 모드가 실주문을 내지 못하게 한다★ (Y1-①)

## 실측한 결함

`order_executor._execute_paper()` 는 `self.kis.place_order(...)` 를 **클라이언트가
무엇인지 확인하지 않고** 불렀다. 클라이언트는 셋 중 하나일 수 있다:

    MockKISClient                      가상 — 안전
    KISClient(creds.is_paper=True)     KIS 모의투자 엔드포인트 — 안전
    KISClient(creds.is_paper=False)    ★실거래 엔드포인트★

즉 `KIS_USE_MOCK=0` + `KIS_IS_PAPER=0` 이면 **PAPER 모드가 실주문을 냈다**.
`ExecutionMode.PAPER` 라는 이름이 보장하는 것이 아무것도 없었던 것이다.

CLAUDE.md §6 최우선 불변식(실거래 안전)과 애드덤 1번 요구(PAPER 기본)를 동시에
어긴다. ★이름이 아니라 클라이언트가 판정 근거다.★

## ★모르면 거부로 기운다★

판정할 수 없는 클라이언트(테스트 더블·새 어댑터)를 "모의겠지" 로 읽지 않는다.
안전 판정에서 미상은 통과가 아니다.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.execution.client_realism import (  # noqa: E402
    REASON_KIS_PAPER,
    REASON_KIS_REAL,
    REASON_MOCK,
    REASON_UNKNOWN,
    client_is_simulated,
)
from src.execution.live_schemas import init_live_trading_schema  # noqa: E402
from src.execution.order_executor import (  # noqa: E402
    ExecutionMode,
    ExecutorState,
    OrderExecutor,
)


# ── 클라이언트 더블 ────────────────────────────────────────────────────
class _Creds:
    def __init__(self, is_paper: bool):
        self.is_paper = is_paper


class _RealKIS:
    """실거래 엔드포인트를 쓰는 클라이언트. ★부르면 안 된다.★"""

    def __init__(self, is_paper: bool = False):
        self.creds = _Creds(is_paper)
        self.called = 0

    def place_order(self, **kw):
        self.called += 1
        return {"kis_order_no": "REAL-0001"}


class _UnknownClient:
    """판정할 수 없는 어댑터 — `creds` 도 없고 Mock 도 아니다."""

    def __init__(self):
        self.called = 0

    def place_order(self, **kw):
        self.called += 1
        return {"kis_order_no": "X"}


def _mock_client():
    from src.execution.kis_client import MockKISClient
    return MockKISClient()


# ═══════════════════════════════════════════════════════════════════════════
# 판정 함수
# ═══════════════════════════════════════════════════════════════════════════

def test_a_mock_client_is_simulated():
    ok, reason = client_is_simulated(_mock_client())
    assert ok is True and reason == REASON_MOCK


def test_a_kis_paper_client_is_simulated():
    """★모의투자 엔드포인트는 허용한다★ — 그것이 PAPER 의 본래 뜻이다."""
    ok, reason = client_is_simulated(_RealKIS(is_paper=True))
    assert ok is True and reason == REASON_KIS_PAPER


def test_a_kis_real_client_is_not_simulated():
    ok, reason = client_is_simulated(_RealKIS(is_paper=False))
    assert ok is False and reason == REASON_KIS_REAL


def test_an_unjudgeable_client_leans_to_refuse():
    """★미상은 통과가 아니다★"""
    ok, reason = client_is_simulated(_UnknownClient())
    assert ok is False
    assert reason.startswith(REASON_UNKNOWN)
    assert "_UnknownClient" in reason, "★무엇을 못 알아봤는지 말해야 한다★"


def test_a_none_client_leans_to_refuse():
    ok, reason = client_is_simulated(None)
    assert ok is False and reason


# ═══════════════════════════════════════════════════════════════════════════
# `_execute_paper` — 주문이 실제로 나가는가
# ═══════════════════════════════════════════════════════════════════════════

class _FakeAudit:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)
        return "AUD-fake"

    def log_order_submitted(self, *a, **kw):
        self.events.append({"event_type": "ORDER_SUBMITTED"})
        return "AUD-sub"


def _executor(client):
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    ex = OrderExecutor.__new__(OrderExecutor)
    ex.kis = client
    ex.engine = eng
    ex.audit = _FakeAudit()
    ex.state = ExecutorState(mode=ExecutionMode.PAPER)
    return ex


def _order_row(ex, coid) -> dict:
    with ex.engine.connect() as c:
        row = c.execute(text(
            "SELECT status, reason_code FROM live_orders WHERE client_order_id = :c"),
            {"c": coid}).fetchone()
    return dict(row._mapping) if row else {}


def _seed(ex, coid="CO-test"):
    with ex.engine.begin() as c:
        c.execute(text(
            "INSERT INTO live_orders (client_order_id, ticker, side, quantity, "
            "order_type, status, execution_mode) VALUES (:c,'005930','BUY',10,"
            "'MARKET','PENDING','PAPER')"), {"c": coid})
    return coid


_SIGNAL = {"ticker": "005930", "side": "BUY", "quantity": 10, "order_type": "MARKET"}


def test_paper_with_a_real_client_places_no_order():
    """★이 파일이 존재하는 이유★"""
    client = _RealKIS(is_paper=False)
    ex = _executor(client)
    coid = _seed(ex)

    res = ex._execute_paper(coid, _SIGNAL, [])

    assert client.called == 0, "★PAPER 모드에서 실주문이 나갔다★"
    assert res["status"] == "REJECTED", res
    assert "paper_mode_real_client" in str(res), res
    assert REASON_KIS_REAL in str(res), "★사유가 실려야 한다★"
    assert _order_row(ex, coid)["status"] == "REJECTED"


def test_paper_with_a_mock_client_still_proceeds():
    """★짝★ 안전한 클라이언트는 전과 같이 진행한다(항상-거부 구현 배제)."""
    ex = _executor(_mock_client())
    coid = _seed(ex)
    res = ex._execute_paper(coid, _SIGNAL, [])
    assert res["status"] == "SUBMITTED", res
    assert res["mode"] == ExecutionMode.PAPER


def test_paper_with_a_kis_paper_client_still_proceeds():
    """★짝★ 모의투자 엔드포인트도 진행한다."""
    client = _RealKIS(is_paper=True)
    ex = _executor(client)
    coid = _seed(ex)
    res = ex._execute_paper(coid, _SIGNAL, [])
    assert client.called == 1
    assert res["status"] == "SUBMITTED", res


def test_paper_with_an_unjudgeable_client_places_no_order():
    client = _UnknownClient()
    ex = _executor(client)
    coid = _seed(ex)
    res = ex._execute_paper(coid, _SIGNAL, [])
    assert client.called == 0
    assert res["status"] == "REJECTED"


# ═══════════════════════════════════════════════════════════════════════════
# ★건드리지 않은 경로★ — SHADOW·LIVE 는 전과 같다 (골든)
# ═══════════════════════════════════════════════════════════════════════════

def test_shadow_never_calls_the_broker_regardless_of_client():
    client = _RealKIS(is_paper=False)
    ex = _executor(client)
    coid = _seed(ex)
    res = ex._execute_shadow(coid, _SIGNAL, [])
    assert client.called == 0
    assert res["status"] == "SHADOW_LOGGED"


def test_live_is_not_blocked_by_the_paper_guard():
    """★LIVE 는 확인 토큰이 이미 지킨다★ — 여기에 가드를 더하면 LIVE 가 죽는다."""
    import inspect

    from src.execution import order_executor as oe
    src = inspect.getsource(oe.OrderExecutor._execute_live)
    assert "client_is_simulated" not in src, \
        "★LIVE 경로에 PAPER 가드가 들어갔다 — 실거래가 영영 막힌다★"


# ═══════════════════════════════════════════════════════════════════════════
# ★가드를 달다가 드러난 결함★ — 거부가 DB 에 반영되지 않았다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_rejection_after_the_pending_insert_is_recorded():
    """`_reject_order` 는 INSERT 만 했다 — 행이 이미 있으면 UNIQUE 충돌이 나고
    그 예외를 삼켜 ★DB 는 `PENDING`, 호출자는 `REJECTED`★ 가 됐다."""
    ex = _executor(_RealKIS(is_paper=False))
    coid = _seed(ex)
    res = ex._reject_order(coid, _SIGNAL, "some_reason", "사유", [])
    assert res["status"] == "REJECTED"
    row = _order_row(ex, coid)
    assert row["status"] == "REJECTED", "★거부가 DB 에 남지 않았다★"
    assert row["reason_code"] == "some_reason"


def test_a_rejection_before_any_row_still_inserts():
    """★짝★ 발주 이전 단계의 거부는 전과 같이 행을 만든다."""
    ex = _executor(_mock_client())
    res = ex._reject_order("CO-fresh", _SIGNAL, "kill_switch_active", "차단", [])
    assert res["status"] == "REJECTED"
    assert _order_row(ex, "CO-fresh")["status"] == "REJECTED"
