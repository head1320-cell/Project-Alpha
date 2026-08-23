"""
Stage 13 Routes Extension — Production Hardening 추가 엔드포인트
====================================================================
기존 stage13_routes.py에 다음을 추가:

  Reconciler:
    POST /reconcile/sync          — 수동 동기화 트리거
    GET  /reconcile/status        — 마지막 sync 상태
    GET  /reconcile/history       — 동기화 이력
    POST /reconcile/periodic/start
    POST /reconcile/periodic/stop

  KIS Gateway:
    GET  /gateway/stats           — 큐 깊이, 우선순위 분포, P95 wait

  Order State Machine:
    POST /orders/cleanup-eod      — 장 마감 미체결 정리
    GET  /orders/state-distribution
    GET  /orders/active           — 활성 주문 목록

  Notifier:
    POST /notifier/test           — 테스트 메시지 발송
    GET  /notifier/stats          — 큐, 발송 통계

사용:
  from src.api.stage13_routes import router as stage13_router
  from src.api.stage13_extensions import router as stage13_ext_router

  app.include_router(stage13_router)
  app.include_router(stage13_ext_router)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/live", tags=["live-trading-extensions"])


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton 접근 — production 모듈들
# ═══════════════════════════════════════════════════════════════════════════════

_PRODUCTION_MODULES = {}


def get_production_modules():
    """Stage 13 production 모듈 lazy 초기화."""
    if _PRODUCTION_MODULES:
        return _PRODUCTION_MODULES

    try:
        import os

        from src.api.kis_gateway import GatewayConfig, KISGateway
        from src.api.stage13_routes import get_executor
        from src.engine.order_tracker import OrderStateMachine
        from src.engine.reconciler import BrokerReconciler, ReconcilerConfig
        from src.utils.notifier import Notifier

        executor = get_executor()

        # Notifier (singleton)
        notifier = Notifier.get_default()

        # KIS Gateway — KISClient를 래핑
        gateway = KISGateway(
            kis_client=executor.kis,
            config=GatewayConfig(
                calls_per_second=float(os.getenv("KIS_RATE_LIMIT", "18")),
            ),
            notifier=notifier,
        )
        gateway.start()

        # Order Tracker
        tracker = OrderStateMachine(
            engine=executor.engine,
            audit_trail=executor.audit,
            notifier=notifier,
        )

        # Reconciler
        reconciler = BrokerReconciler(
            engine=executor.engine,
            kis_client=executor.kis,
            audit_trail=executor.audit,
            notifier=notifier,
            kill_switch=executor.kill_switch,
            config=ReconcilerConfig(),
        )

        _PRODUCTION_MODULES.update({
            "executor":    executor,
            "gateway":     gateway,
            "tracker":     tracker,
            "reconciler":  reconciler,
            "notifier":    notifier,
        })
    except Exception as e:
        logger.error(f"Production 모듈 초기화 실패: {e}", exc_info=True)
        raise

    return _PRODUCTION_MODULES


# ═══════════════════════════════════════════════════════════════════════════════
# Reconciler
# ═══════════════════════════════════════════════════════════════════════════════

class SyncRequest(BaseModel):
    reason: str = Field(default="manual", min_length=1)


@router.post("/reconcile/sync")
def reconcile_sync(req: SyncRequest):
    """수동 동기화 트리거."""
    try:
        mods = get_production_modules()
        result = mods["reconciler"].sync_with_broker(reason=req.reason)
        return {
            "sync_id":           result.sync_id,
            "success":           result.success,
            "severity":          result.severity,
            "cash_drift_krw":    result.cash_drift_krw,
            "cash_drift_pct":    result.cash_drift_pct,
            "n_position_diffs":  len(result.position_diffs),
            "ghost_positions":   result.ghost_positions,
            "missing_positions": result.missing_positions,
            "actions_taken":     result.actions_taken,
            "error":             result.error,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/reconcile/status")
def reconcile_status():
    """마지막 sync 상태 + periodic 실행 여부."""
    try:
        mods = get_production_modules()
        return mods["reconciler"].get_status()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/reconcile/history")
def reconcile_history(limit: int = Query(50, le=200)):
    """최근 reconciliation 이력."""
    try:
        mods = get_production_modules()
        history = mods["reconciler"].recent_history(limit=limit)
        return {"count": len(history), "history": history}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/reconcile/periodic/start")
def reconcile_periodic_start():
    """주기적 sync 백그라운드 시작."""
    try:
        mods = get_production_modules()
        mods["reconciler"].start_periodic_sync()
        return {"status": "started"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/reconcile/periodic/stop")
def reconcile_periodic_stop():
    try:
        mods = get_production_modules()
        mods["reconciler"].stop_periodic_sync()
        return {"status": "stopped"}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# KIS Gateway Stats
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/gateway/stats")
def gateway_stats():
    """KIS API 호출 큐 + 통계."""
    try:
        mods = get_production_modules()
        return mods["gateway"].get_stats()
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Order State Machine
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/orders/active")
def orders_active():
    """현재 체결 대기 중 주문 (PENDING/SUBMITTED/ACCEPTED/PARTIAL_FILL)."""
    try:
        mods = get_production_modules()
        active = mods["tracker"].list_active_orders()
        return {"count": len(active), "orders": active}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/orders/state-distribution")
def orders_state_distribution():
    """전체 주문의 상태 분포."""
    try:
        mods = get_production_modules()
        return {"distribution": mods["tracker"].state_distribution()}
    except Exception as e:
        raise HTTPException(500, str(e))


class CleanupRequest(BaseModel):
    policy: str = Field(default="conservative_cancel",
                          pattern="^(conservative_cancel|aggressive_fill|hold)$")
    force:  bool = Field(default=False)


@router.post("/orders/cleanup-eod")
def orders_cleanup_eod(req: CleanupRequest):
    """장 마감 전 미체결 정리."""
    try:
        mods = get_production_modules()
        return mods["tracker"].cleanup_market_close(
            kis_client=mods["executor"].kis,
            policy=req.policy,
            force=req.force,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Notifier
# ═══════════════════════════════════════════════════════════════════════════════

class TestNotifyRequest(BaseModel):
    severity: str = Field(default="INFO", pattern="^(INFO|WARN|CRITICAL)$")
    title:    str = Field(default="Test Notification")
    message:  str = Field(default="알림 시스템 테스트 메시지")


@router.post("/notifier/test")
def notifier_test(req: TestNotifyRequest):
    """등급별 테스트 알림 발송."""
    try:
        mods = get_production_modules()
        notifier = mods["notifier"]
        sev_method = {
            "CRITICAL": notifier.critical,
            "WARN":     notifier.warn,
            "INFO":     notifier.info,
        }[req.severity]
        sev_method(title=req.title, message=req.message,
                    context={"test": True, "via": "API"})
        return {"sent": True, "severity": req.severity}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/notifier/stats")
def notifier_stats():
    """알림 큐 + 발송 통계."""
    try:
        mods = get_production_modules()
        return mods["notifier"].get_stats()
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Health Check — 모든 production 모듈 상태 통합
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/health")
def live_health():
    """Stage 13 production 시스템 종합 상태."""
    try:
        mods = get_production_modules()
        gateway_stats = mods["gateway"].get_stats()
        notifier_stats = mods["notifier"].get_stats()
        recon_status = mods["reconciler"].get_status()
        state_dist = mods["tracker"].state_distribution()
        kill_active = mods["executor"].kill_switch.is_active()

        critical_issues = []
        if kill_active:
            critical_issues.append("kill_switch_active")
        if gateway_stats.get("circuit_state") == "OPEN":
            critical_issues.append("kis_circuit_open")
        if recon_status.get("last_severity") == "CRITICAL":
            critical_issues.append("broker_drift_critical")
        if not notifier_stats.get("worker_alive"):
            critical_issues.append("notifier_worker_dead")

        health = "HEALTHY"
        if critical_issues:
            health = "CRITICAL"
        elif recon_status.get("last_severity") == "WARN":
            health = "DEGRADED"

        return {
            "health":              health,
            "critical_issues":     critical_issues,
            "execution_mode":      mods["executor"].state.mode,
            "kill_switch_active":  kill_active,
            "gateway": {
                "queue_size":      gateway_stats.get("queue_size"),
                "circuit_state":   gateway_stats.get("circuit_state"),
                "total_executed":  gateway_stats.get("total_executed"),
                "avg_wait_ms":     gateway_stats.get("avg_wait_ms"),
            },
            "reconciler": {
                "last_severity":   recon_status.get("last_severity"),
                "last_sync_at":    recon_status.get("last_sync_at"),
                "periodic_running": recon_status.get("periodic_running"),
            },
            "order_states":        state_dist,
            "notifier": {
                "worker_alive":    notifier_stats.get("worker_alive"),
                "total_sent":      notifier_stats.get("total_sent"),
                "slack_configured": notifier_stats.get("slack_configured"),
            },
        }
    except Exception as e:
        return {"health": "UNKNOWN", "error": str(e)}
