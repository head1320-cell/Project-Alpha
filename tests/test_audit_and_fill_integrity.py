"""감사 기록과 체결 기록의 ★정직성★ (Y1-② · Y1-③)

## ② 감사 기록이 실패해도 `audit_id` 를 돌려줬다

`AuditTrail.log()` 는 INSERT 를 `try/except` 로 감싸고, 실패해도 **미리 만들어 둔
`audit_id` 를 그대로 반환**했다. 그래서 DB 장애 중에 낸 주문의 응답에는
★아무것도 가리키지 않는 감사 ID★ 가 실렸다. 사유 없는 폴백 금지(CLAUDE.md §4)에
정면으로 어긋나고, 감사 추적이 가장 필요한 순간에 거짓말을 한다.

## ③ `live_fills.kis_fill_id` 에 유일 제약이 없었다

같은 브로커 체결을 두 번 기록하면 `live_orders.filled_quantity` 가 이중계산되고
`avg_fill_price` 가 오염된다. 브로커 재조회·재시도는 정상 운영이므로 **재생은
일어난다**. 멱등이 아니면 장부가 틀어진다.

(ST1, 2026-10-15) 체결을 기록하던 `engine/order_tracker.record_fill` 은 부르는 곳 없는 Stage 13 운영 감시층이라
지웠다 — 남은 방어는 인덱스(`ensure_fill_dedup_index`)와 그 결과를 숨기지 않는 스키마 경로다.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.execution.audit_trail import AuditTrail  # noqa: E402
from src.execution.live_schemas import (  # noqa: E402
    FILL_DEDUP_INDEX,
    ensure_fill_dedup_index,
    init_live_trading_schema,
)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return eng


# ═══════════════════════════════════════════════════════════════════════════
# ② 감사 — ★실패하면 id 를 주지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_successful_log_returns_an_id(engine):
    """★짝★ 정상일 때는 전과 같이 id 를 준다(항상-None 구현 배제)."""
    aid = AuditTrail(engine).log(event_type="X", message="정상")
    assert aid and aid.startswith("AUD-")
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM live_audit_trail")).scalar() == 1


def test_a_failed_log_returns_none_not_a_fabricated_id():
    class _Boom:
        def begin(self):
            raise RuntimeError("DB 폭발")

    assert AuditTrail(_Boom()).log(event_type="X", message="실패") is None


def test_a_failed_log_is_logged_at_error(caplog):
    class _Boom:
        def begin(self):
            raise RuntimeError("DB 폭발")

    import logging
    with caplog.at_level(logging.ERROR):
        AuditTrail(_Boom()).log(event_type="X", message="실패")
    assert any("DB 폭발" in r.message for r in caplog.records), caplog.text


def test_the_convenience_writers_propagate_none():
    """`log_signal` 등도 위조하지 않는다."""
    class _Boom:
        def begin(self):
            raise RuntimeError("x")

    a = AuditTrail(_Boom())
    assert a.log_signal(strategy_id=1, ticker="005930", side="BUY", quantity=1) is None


def test_the_executor_does_not_append_a_none_audit_id(engine):
    """★호출부가 `None` 을 목록에 넣지 않는다★"""
    from src.execution.order_executor import ExecutionMode, ExecutorState, OrderExecutor

    class _NullAudit:
        def log(self, **kw):
            return None

        def log_order_submitted(self, *a, **kw):
            return None

    from src.execution.kis_client import MockKISClient
    ex = OrderExecutor.__new__(OrderExecutor)
    ex.kis, ex.engine, ex.audit = MockKISClient(), engine, _NullAudit()
    ex.state = ExecutorState(mode=ExecutionMode.PAPER)
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO live_orders (client_order_id, ticker, side, quantity, "
            "order_type, status, execution_mode) VALUES ('CO-a','005930','BUY',1,"
            "'MARKET','PENDING','PAPER')"))

    res = ex._execute_paper("CO-a", {"ticker": "005930", "side": "BUY", "quantity": 1}, [])
    assert None not in res["audit_ids"], "★`None` 이 감사 ID 목록에 들어갔다★"
    assert res.get("audit_failed") is True, "★기록 실패를 결과가 말하지 않는다★"


# ═══════════════════════════════════════════════════════════════════════════
# ③ 체결 — ★재생해도 두 번 세지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def _order(eng, coid="CO-f", qty=100):
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO live_orders (client_order_id, ticker, side, quantity, "
            "order_type, status, execution_mode) VALUES (:c,'005930','BUY',:q,"
            "'MARKET','SUBMITTED','PAPER')"), {"c": coid, "q": qty})
    return coid


def test_the_dedup_index_is_created(engine):
    ok, reason = ensure_fill_dedup_index(engine)
    assert ok is True, reason
    with engine.connect() as c:
        names = [r[0] for r in c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index'"))]
    assert FILL_DEDUP_INDEX in names, names





def test_a_duplicate_row_makes_index_creation_report_not_lie(engine):
    """★조용히 성공하지 않는다★ — 이미 중복이 있으면 사유와 함께 실패를 말한다."""
    coid = _order(engine)
    with engine.begin() as c:
        for _ in range(2):
            c.execute(text(
                "INSERT INTO live_fills (client_order_id, kis_fill_id, fill_quantity, "
                "fill_price, fill_value_krw, filled_at) "
                "VALUES (:c,'DUP',1,1,1,CURRENT_TIMESTAMP)"), {"c": coid})
    ok, reason = ensure_fill_dedup_index(engine)
    assert ok is False
    assert reason and len(reason) > 10, reason


def test_the_schema_route_reports_the_dedup_index():
    """★인덱스 생성 결과가 응답에 실린다★ — 조용히 성공처럼 보이지 않는다."""
    import inspect

    from src.api import stage13_routes
    src = inspect.getsource(stage13_routes.live_init_schema)
    assert "ensure_fill_dedup_index" in src, "★프로덕션 경로가 인덱스를 만들지 않는다★"
    assert "fill_dedup_index" in src and "fill_dedup_reason" in src

