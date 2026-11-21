"""계좌마다 Stage13 실행기 하나 (BV6)
==============================================================================
사용자가 연결한 증권 계좌(BV3·BV4)로 SHADOW/PAPER 주문을 낸다. 운영자 실행기(`stage13_routes.get_executor`)와
같은 부품을 쓰되, 클라이언트는 그 계좌 것(`get_kis_client(account_id=…)`)이고 주문·감사·비상 정지는 `account_id`
로 갈린다(BV6a — `live_schemas.account_scope`).

## ★모드는 메모리에만 있다 — 재시작하면 SHADOW★

운영자 실행기와 같은 규칙이다. DB 에서 모드를 되살리지 않는다(주문이 다시 나가는 길을 조용히 열지 않는다).

## ★소유권은 여기서 보지 않는다★

이 함수는 계좌 id 를 받는 내부 통로다. 경로(`broker_account_routes`)가 먼저 본인 계좌인지 본다.
"""
from __future__ import annotations

import threading

from src.data.mock_gate import mock_allowed
from src.database import get_sync_engine
from src.execution.audit_trail import AuditTrail
from src.execution.kill_switch import KillSwitch, KillSwitchConfig
from src.execution.kis_client import get_kis_client
from src.execution.order_executor import ExecutionMode, OrderExecutor
from src.execution.risk_gateway import RiskGateway, RiskLimits

_executors: dict[str, OrderExecutor] = {}
_lock = threading.Lock()


def get_account_executor(account_id: str) -> OrderExecutor:
    """그 계좌의 실행기. 없으면 SHADOW 로 만든다(같은 계좌 = 같은 실행기)."""
    with _lock:
        ex = _executors.get(account_id)
        if ex is None:
            ex = _build(account_id)
            _executors[account_id] = ex
        return ex


def evict_account_executor(account_id: str) -> None:
    """계좌를 지우면 실행기도 버린다(모드·상태가 남지 않게)."""
    with _lock:
        _executors.pop(account_id, None)


def _build(account_id: str) -> OrderExecutor:
    kis = get_kis_client(account_id=account_id)
    engine = get_sync_engine()
    audit = AuditTrail(engine, account_id=account_id)
    return OrderExecutor(
        engine=engine, kis_client=kis,
        risk_gateway=RiskGateway(engine, limits=RiskLimits(), universe=set(),
                                 bypass_market_hours=mock_allowed()),
        audit_trail=audit,
        kill_switch=KillSwitch(engine, audit, KillSwitchConfig(), account_id=account_id),
        mode=ExecutionMode.SHADOW, account_id=account_id,
    )
