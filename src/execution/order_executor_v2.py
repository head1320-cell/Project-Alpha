"""
Order Executor v2 — Production Hardened
==============================================
기존 OrderExecutor (Stage 13 기본)을 production 강화.

추가 통합:
  · BrokerReconciler — 매 주문 전 sync_with_broker() 자동 호출
  · OrderStateMachine — 상태 전이를 명시적으로 관리
  · KISGatewayClient — 모든 KIS 호출이 priority queue 통과
  · Notifier — 주요 이벤트 자동 알림

기존 OrderExecutor와 인터페이스 호환. execute_signal() 의 내부 흐름만 강화.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text

from src.execution.order_executor import ExecutionMode, OrderExecutor

logger = logging.getLogger(__name__)


class ProductionOrderExecutor(OrderExecutor):
    """
    Production-grade 실행 엔진.

    추가 매개변수:
        reconciler:        BrokerReconciler 인스턴스
        order_tracker:     OrderStateMachine 인스턴스
        notifier:          Notifier 인스턴스
        require_fresh_sync: True면 매 주문 전 sync 강제

    Usage:
        executor = ProductionOrderExecutor(
            engine=engine,
            kis_client=gateway_client,   # KISGatewayClient
            risk_gateway=risk_gw,
            audit_trail=audit,
            kill_switch=kill_switch,
            reconciler=reconciler,
            order_tracker=tracker,
            notifier=notifier,
            mode=ExecutionMode.SHADOW,
            require_fresh_sync=True,
        )

        result = executor.execute_signal(signal)
    """

    def __init__(
        self,
        engine, kis_client, risk_gateway, audit_trail, kill_switch,
        reconciler=None, order_tracker=None, notifier=None,
        require_fresh_sync: bool = True,
        mode: str = ExecutionMode.SHADOW,
    ):
        super().__init__(
            engine=engine, kis_client=kis_client,
            risk_gateway=risk_gateway, audit_trail=audit_trail,
            kill_switch=kill_switch, mode=mode,
        )
        self.reconciler = reconciler
        self.tracker = order_tracker
        self.notifier = notifier
        self.require_fresh_sync = require_fresh_sync

    # ─────────────────────────────────────────────────────────────────────
    # 핵심 — execute_signal 강화
    # ─────────────────────────────────────────────────────────────────────

    def execute_signal(
        self,
        signal: dict,
        account_state: dict | None = None,
        regime_state: dict | None = None,
    ) -> dict:
        """
        강화된 주문 실행:
          1. Reconciler — fresh broker sync 보장
          2. 기존 5-layer safety
          3. State machine으로 상태 전이
          4. Notification dispatch
        """
        # ── Step 0: Reconciler 강제 sync (PRE-ORDER) ─────────────────
        if self.require_fresh_sync and self.reconciler \
            and self.state.mode in (ExecutionMode.PAPER, ExecutionMode.LIVE):
            try:
                sync_result = self.reconciler.ensure_synced(reason="pre_order")
                if sync_result.severity == "CRITICAL":
                    return self._reject_with_message(
                        signal,
                        reason="reconciliation_critical_drift",
                        message=f"Broker drift CRITICAL — 주문 차단 "
                                f"(cash_drift={sync_result.cash_drift_krw:+,.0f}, "
                                f"ghosts={sync_result.ghost_positions}, "
                                f"missing={sync_result.missing_positions})",
                    )
                # Sync 후 account_state는 최신 KIS 잔고로 자동 갱신됨
                account_state = self._fetch_account_state()
            except Exception as e:
                logger.error(f"Pre-order reconciliation 실패: {e}")
                # Reconciler 실패는 거부 사유로 간주 (안전)
                return self._reject_with_message(
                    signal,
                    reason="reconciliation_failed",
                    message=f"Broker sync 실패 — 주문 차단: {e}",
                )

        # ── Step 1+: 기존 흐름 ───────────────────────────────────────
        result = super().execute_signal(signal, account_state, regime_state)

        # ── Post-execute: 알림 디스패치 ──────────────────────────────
        self._notify_execution_result(signal, result)

        return result

    # ─────────────────────────────────────────────────────────────────────
    # 상태 전이 — Tracker 사용
    # ─────────────────────────────────────────────────────────────────────

    def _update_order_submitted(self, client_order_id, kis_resp):
        """기존 메서드를 override해서 tracker 사용."""
        if self.tracker:
            from src.engine.order_tracker import OrderState
            self.tracker.transition(
                client_order_id=client_order_id,
                new_state=OrderState.SUBMITTED,
                reason="KIS 전송 완료",
                metadata={"kis_order_no": kis_resp.get("kis_order_no")},
            )
            # tracker가 kis_order_id 업데이트 안 했을 경우 보강
            try:
                with self.engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE live_orders
                        SET kis_order_org_no = COALESCE(kis_order_org_no, :kog)
                        WHERE client_order_id = :coid
                    """), {
                        "coid": client_order_id,
                        "kog":  kis_resp.get("kis_order_id"),
                    })
            except Exception:
                pass
        else:
            super()._update_order_submitted(client_order_id, kis_resp)

    # ─────────────────────────────────────────────────────────────────────
    # Mode change — Notification
    # ─────────────────────────────────────────────────────────────────────

    def set_mode(self, new_mode: str, actor: str = "user",
                  confirm_token: str | None = None) -> dict:
        result = super().set_mode(new_mode, actor, confirm_token)

        if self.notifier:
            try:
                if new_mode == ExecutionMode.LIVE:
                    self.notifier.critical(
                        title="⚡ LIVE Trading 활성화",
                        message=f"실거래 모드 진입 by {actor}. 모든 주문은 실제 자금.",
                        context={"changed_at": result["changed_at"]},
                    )
                elif new_mode == ExecutionMode.SHADOW:
                    self.notifier.info(
                        title="SHADOW 모드",
                        message=f"신호 기록만 by {actor}",
                    )
                else:
                    self.notifier.warn(
                        title=f"실행 모드 → {new_mode}",
                        message=f"by {actor}",
                    )
            except Exception:
                pass
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _reject_with_message(self, signal, reason, message) -> dict:
        """
        Reconciliation 실패 등 사전 거부를 audit + DB 기록.
        """
        client_order_id = f"CO-{uuid.uuid4().hex[:14]}"

        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO live_orders (
                        client_order_id, strategy_id, execution_mode,
                        ticker, side, quantity, price,
                        status, reason_code, error_message
                    ) VALUES (
                        :coid, :sid, :mode, :tk, :sd, :qty, :pr,
                        'REJECTED', :rc, :em
                    )
                """), {
                    "coid": client_order_id, "sid": signal.get("strategy_id"),
                    "mode": self.state.mode,
                    "tk": signal["ticker"], "sd": signal["side"],
                    "qty": signal["quantity"], "pr": signal.get("price"),
                    "rc": reason[:40], "em": message,
                })
        except Exception:
            pass

        if self.notifier:
            try:
                self.notifier.warn(
                    title="주문 사전 거부",
                    message=f"{signal['ticker']} {signal['side']} {signal['quantity']}주",
                    context={"reason": reason, "detail": message},
                )
            except Exception:
                pass

        from src.execution.audit_trail import EventCategory, EventType, Severity
        if self.audit:
            try:
                self.audit.log(
                    event_type=EventType.ORDER_REJECTED,
                    category=EventCategory.ORDER,
                    severity=Severity.WARN,
                    strategy_id=signal.get("strategy_id"),
                    client_order_id=client_order_id,
                    ticker=signal["ticker"],
                    reason_code=reason,
                    context={"order": signal, "detail": message},
                    message=message,
                )
            except Exception:
                pass

        return {
            "client_order_id": client_order_id,
            "status":          "REJECTED",
            "mode":            self.state.mode,
            "reason":          reason,
            "message":         message,
            "audit_ids":       [],
        }

    def _notify_execution_result(self, signal: dict, result: dict):
        """주문 결과를 알림으로 전파."""
        if not self.notifier:
            return
        try:
            ctx = {
                "order_id":  result.get("client_order_id", "")[:20],
                "mode":      result.get("mode"),
                "ticker":    signal["ticker"],
                "side":      signal["side"],
                "quantity":  signal["quantity"],
            }

            status = result.get("status")
            if status == "REJECTED":
                self.notifier.warn(
                    title="주문 거부",
                    message=result.get("message") or result.get("reason", ""),
                    context=ctx,
                )
            elif status == "FAILED":
                self.notifier.critical(
                    title="주문 실패",
                    message=str(result.get("error", "API error")),
                    context=ctx,
                )
            elif status == "SUBMITTED" and result.get("mode") == ExecutionMode.LIVE:
                self.notifier.info(
                    title="⚡ LIVE 주문 발주",
                    message=f"{signal['side']} {signal['ticker']} {signal['quantity']}주",
                    context=ctx,
                )
        except Exception as e:
            logger.error(f"Execution notification 실패: {e}")
