"""
Stage 13 API Routes — Live Trading
=========================================
11개 엔드포인트:
  · POST /init-schema            — 스키마 초기화
  · POST /orders/submit          — 단일 신호 → 검증 → 실행
  · GET  /orders                 — 주문 목록
  · GET  /orders/{coid}          — 단일 주문 상세 + 체결
  · DELETE /orders/{coid}        — 주문 취소
  · GET  /balance                — KIS 잔고 조회
  · POST /mode                   — 실행 모드 변경 (SHADOW/PAPER/LIVE)
  · GET  /mode                   — 현재 모드
  · POST /kill-switch/trigger    — Kill switch 수동 발동
  · POST /kill-switch/resolve    — Kill switch 해제
  · GET  /kill-switch/events     — Kill 이벤트 이력
  · GET  /audit                  — 감사 로그 조회 (filters)
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/live", tags=["live-trading"])


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton (간이) — 실제로는 의존성 주입이나 캐시 사용 권장
# ═══════════════════════════════════════════════════════════════════════════════

_EXECUTOR = None


def get_executor():
    """Lazy 초기화 executor 인스턴스."""
    global _EXECUTOR
    if _EXECUTOR is not None:
        return _EXECUTOR

    from src.database import get_sync_engine
    from src.execution.audit_trail import AuditTrail
    from src.execution.kill_switch import KillSwitch, KillSwitchConfig
    from src.execution.kis_client import KISClient, KISCredentials, MockKISClient
    from src.execution.order_executor import ExecutionMode, OrderExecutor
    from src.execution.risk_gateway import RiskGateway, RiskLimits

    engine = get_sync_engine()

    # KIS client 선택
    use_mock = os.getenv("KIS_USE_MOCK", "1") == "1"
    if use_mock:
        kis = MockKISClient(initial_cash=100_000_000)
    else:
        kis = KISClient(KISCredentials(
            app_key=os.environ["KIS_APP_KEY"],
            app_secret=os.environ["KIS_APP_SECRET"],
            account_no=os.environ["KIS_ACCOUNT_NO"],
            account_prdt=os.getenv("KIS_ACCOUNT_PRDT", "01"),
            is_paper=os.getenv("KIS_IS_PAPER", "1") == "1",
        ))

    audit = AuditTrail(engine)
    kill_switch = KillSwitch(engine, audit, KillSwitchConfig())
    risk_gw = RiskGateway(
        engine,
        limits=RiskLimits(),
        universe=set(),  # 운영 시 종목 화이트리스트 주입
        bypass_market_hours=bool(use_mock),
    )

    _EXECUTOR = OrderExecutor(
        engine=engine, kis_client=kis,
        risk_gateway=risk_gw, audit_trail=audit,
        kill_switch=kill_switch,
        mode=ExecutionMode.SHADOW,
    )
    return _EXECUTOR


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 스키마 초기화
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/init-schema")
def live_init_schema():
    """live_* 5개 테이블 생성."""
    try:
        from src.database import get_sync_engine
        from src.execution.live_schemas import init_live_trading_schema
        n = init_live_trading_schema(get_sync_engine())
        return {"status": "OK", "ddls_executed": n}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 주문 발주 + 조회 + 취소
# ═══════════════════════════════════════════════════════════════════════════════

class SignalRequest(BaseModel):
    strategy_id: int
    ticker:      str = Field(..., min_length=4, max_length=10)
    side:        str = Field(..., pattern="^(BUY|SELL)$")
    quantity:    int = Field(..., gt=0)
    price:       float | None = None
    order_type:  str = Field(default="MARKET", pattern="^(MARKET|LIMIT)$")
    source:      str = Field(default="manual")


@router.post("/orders/submit")
def live_submit_order(req: SignalRequest):
    """신호 → 위험 검증 → 모드 라우팅 → 실행."""
    try:
        executor = get_executor()
        return executor.execute_signal(req.model_dump())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/orders")
def live_list_orders(
    status: str | None = None,
    strategy_id: int | None = None,
    ticker: str | None = None,
    limit: int = Query(100, le=500),
):
    try:
        executor = get_executor()
        orders = executor.list_orders(status, strategy_id, ticker, limit)
        return {"count": len(orders), "orders": orders}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/orders/{client_order_id}")
def live_get_order(client_order_id: str):
    try:
        executor = get_executor()
        order = executor.get_order(client_order_id)
        if not order:
            raise HTTPException(404, "주문 없음")
        return order
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/orders/{client_order_id}")
def live_cancel_order(client_order_id: str, actor: str = "user"):
    try:
        executor = get_executor()
        return executor.cancel_order(client_order_id, actor)
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 계좌 + 잔고
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/balance")
def live_balance():
    """KIS 잔고 + 평가 + 보유 종목."""
    try:
        executor = get_executor()
        return executor.kis.get_balance()
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 실행 모드 (SHADOW/PAPER/LIVE)
# ═══════════════════════════════════════════════════════════════════════════════

class ModeChangeRequest(BaseModel):
    mode:          str = Field(..., pattern="^(SHADOW|PAPER|LIVE)$")
    actor:         str = Field(default="user")
    confirm_token: str | None = None


@router.post("/mode")
def live_set_mode(req: ModeChangeRequest):
    """⚠ LIVE 진입은 confirm_token='EXPLICIT_LIVE_CONFIRMED' 필요."""
    try:
        executor = get_executor()
        return executor.set_mode(req.mode, req.actor, req.confirm_token)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/mode")
def live_get_mode():
    try:
        executor = get_executor()
        return {
            "mode": executor.state.mode,
            "started_at":         executor.state.started_at.isoformat() if executor.state.started_at else None,
            "last_mode_change":   executor.state.last_mode_change.isoformat() if executor.state.last_mode_change else None,
            "changed_by":         executor.state.changed_by,
            "enabled_strategies": list(executor.state.enabled_strategies),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Kill Switch
# ═══════════════════════════════════════════════════════════════════════════════

class KillTriggerRequest(BaseModel):
    reason:           str = Field(..., min_length=4)
    liquidation_mode: str = Field(default="hold", pattern="^(hold|gradual|immediate)$")
    actor:            str = Field(default="user")


@router.post("/kill-switch/trigger")
def live_kill_trigger(req: KillTriggerRequest):
    """🚨 비상 정지."""
    try:
        executor = get_executor()
        balance = executor.kis.get_balance()
        return executor.kill_switch.trigger(
            source=f"manual_{req.actor}",
            reason=req.reason,
            equity=balance.get("evaluated_total", 0),
            kis_client=executor.kis,
            liquidation_mode=req.liquidation_mode,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


class KillResolveRequest(BaseModel):
    resolved_by: str = Field(..., min_length=1)
    notes:       str = Field(default="")


@router.post("/kill-switch/resolve")
def live_kill_resolve(req: KillResolveRequest):
    try:
        executor = get_executor()
        return executor.kill_switch.resolve(req.resolved_by, req.notes)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/kill-switch/status")
def live_kill_status():
    try:
        executor = get_executor()
        return {
            "is_active": executor.kill_switch.is_active(),
            "active_event": executor.kill_switch.active_event(),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/kill-switch/events")
def live_kill_events(limit: int = Query(50, le=200)):
    try:
        from sqlalchemy import text

        from src.database import get_sync_engine
        with get_sync_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT * FROM live_kill_events
                ORDER BY triggered_at DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        return {"count": len(rows), "events": [dict(r._mapping) for r in rows]}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Audit Trail 조회
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/audit")
def live_audit(
    event_type:     str | None = None,
    category:       str | None = None,
    severity_min:   str | None = None,
    strategy_id:    int | None = None,
    client_order_id: str | None = None,
    limit:          int = Query(100, le=500),
):
    """감사 로그 조회 (다중 필터)."""
    try:
        executor = get_executor()
        events = executor.audit.query(
            event_type=event_type, category=category,
            severity_min=severity_min,
            strategy_id=strategy_id, client_order_id=client_order_id,
            limit=limit,
        )
        return {"count": len(events), "events": events}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/audit/summary")
def live_audit_summary(date: str | None = None):
    """단일 거래일 audit 요약."""
    try:
        executor = get_executor()
        return executor.audit.daily_summary(date)
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Daily P&L
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/daily-pnl")
def live_daily_pnl(limit: int = Query(30, le=365)):
    """일별 P&L 이력."""
    try:
        from sqlalchemy import text

        from src.database import get_sync_engine
        with get_sync_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT * FROM live_daily_pnl
                ORDER BY trade_date DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        return {"count": len(rows), "pnl_history": [dict(r._mapping) for r in rows]}
    except Exception as e:
        raise HTTPException(500, str(e))
