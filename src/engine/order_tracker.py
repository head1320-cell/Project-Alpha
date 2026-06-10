"""
Order State Machine — 주문 상태 전이 + 미체결 정리
======================================================
주문은 명시적인 상태 머신을 따른다. 잘못된 전이는 거부.

상태:
  PENDING       — 생성, 발주 전
  SUBMITTED     — KIS 전송 완료
  ACCEPTED      — KIS 수락 (체결 대기)
  PARTIAL_FILL  — 일부 체결
  FILLED        — 전량 체결
  CANCELLED     — 취소
  REJECTED      — KIS 거부
  EXPIRED       — 시간 초과 (장 마감 등)
  FAILED        — 네트워크/시스템 오류

유효 전이:
  PENDING → SUBMITTED, REJECTED, FAILED
  SUBMITTED → ACCEPTED, REJECTED, FAILED, CANCELLED
  ACCEPTED → PARTIAL_FILL, FILLED, CANCELLED, EXPIRED
  PARTIAL_FILL → FILLED, CANCELLED, EXPIRED
  (terminal): FILLED, CANCELLED, REJECTED, EXPIRED, FAILED

장 마감 처리 (15:20 동시호가 진입 전):
  · LIMIT 미체결 → 시장가 정정 (force_fill) 또는 취소
  · 정책: aggressive_fill | conservative_cancel | hold
  · Audit + Notification

방어적 프로그래밍:
  · 모든 상태 변경은 DB transaction
  · 잘못된 전이는 명시적 ValueError
  · State 캐시 동기화 보장
  · 종료 처리 idempotent
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import text

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
MARKET_CLOSE_CUTOFF = dtime(15, 15)    # 15:15 이후 미체결 정리 시작
SINGLE_PRICE_AUCTION_START = dtime(15, 20)


# ═══════════════════════════════════════════════════════════════════════════════
# State definitions
# ═══════════════════════════════════════════════════════════════════════════════

class OrderState:
    PENDING       = "PENDING"
    SUBMITTED     = "SUBMITTED"
    ACCEPTED      = "ACCEPTED"
    PARTIAL_FILL  = "PARTIAL_FILL"
    FILLED        = "FILLED"
    CANCELLED     = "CANCELLED"
    REJECTED      = "REJECTED"
    EXPIRED       = "EXPIRED"
    FAILED        = "FAILED"
    SHADOW_LOGGED = "SHADOW_LOGGED"

    TERMINAL = {FILLED, CANCELLED, REJECTED, EXPIRED, FAILED, SHADOW_LOGGED}
    ACTIVE   = {PENDING, SUBMITTED, ACCEPTED, PARTIAL_FILL}


# 유효한 상태 전이 그래프
VALID_TRANSITIONS: dict[str, set[str]] = {
    OrderState.PENDING:       {OrderState.SUBMITTED, OrderState.REJECTED,
                                OrderState.FAILED, OrderState.SHADOW_LOGGED},
    OrderState.SUBMITTED:     {OrderState.ACCEPTED, OrderState.PARTIAL_FILL,
                                OrderState.FILLED, OrderState.REJECTED,
                                OrderState.FAILED, OrderState.CANCELLED},
    OrderState.ACCEPTED:      {OrderState.PARTIAL_FILL, OrderState.FILLED,
                                OrderState.CANCELLED, OrderState.EXPIRED,
                                OrderState.FAILED},
    OrderState.PARTIAL_FILL:  {OrderState.FILLED, OrderState.CANCELLED,
                                OrderState.EXPIRED, OrderState.FAILED},
    # Terminal states — 전이 불가
    OrderState.FILLED:        set(),
    OrderState.CANCELLED:     set(),
    OrderState.REJECTED:      set(),
    OrderState.EXPIRED:       set(),
    OrderState.FAILED:        set(),
    OrderState.SHADOW_LOGGED: set(),
}


@dataclass
class TransitionResult:
    """상태 전이 결과."""
    success:        bool
    from_state:     str
    to_state:       str
    client_order_id: str
    reason:         str | None = None
    error:          str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# OrderTracker
# ═══════════════════════════════════════════════════════════════════════════════

class OrderStateMachine:
    """
    명시적 주문 상태 전이 관리자.

    Usage:
        tracker = OrderStateMachine(engine, audit_trail, notifier)

        # 상태 전이
        r = tracker.transition(
            client_order_id="CO-abc123",
            new_state=OrderState.SUBMITTED,
            reason="KIS 발주 완료",
            metadata={"kis_order_no": "..."},
        )

        # 체결 기록
        tracker.record_fill(
            client_order_id="CO-abc123",
            fill_quantity=50, fill_price=70000,
        )

        # 장 마감 정리
        cleanup_result = tracker.cleanup_market_close(
            kis_client=kis,
            policy="conservative_cancel",
        )

        # 활성 주문 조회
        active = tracker.list_active_orders()
    """

    def __init__(self, engine, audit_trail=None, notifier=None):
        self.engine = engine
        self.audit = audit_trail
        self.notifier = notifier

    # ─────────────────────────────────────────────────────────────────────
    # 핵심: 상태 전이
    # ─────────────────────────────────────────────────────────────────────

    def transition(
        self,
        client_order_id: str,
        new_state: str,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> TransitionResult:
        """
        주문 상태 변경. 유효 전이만 허용.

        잘못된 전이 시도는 거부 + audit ERROR 기록.
        """
        # 현재 상태 조회
        current = self._get_current_state(client_order_id)
        if current is None:
            return TransitionResult(
                success=False,
                from_state="UNKNOWN", to_state=new_state,
                client_order_id=client_order_id,
                error="주문 미존재",
            )

        # 전이 유효성 검사
        if new_state == current:
            return TransitionResult(
                success=True,
                from_state=current, to_state=new_state,
                client_order_id=client_order_id,
                reason="동일 상태 (no-op)",
            )

        if new_state not in VALID_TRANSITIONS.get(current, set()):
            self._audit_invalid_transition(client_order_id, current, new_state, reason)
            return TransitionResult(
                success=False,
                from_state=current, to_state=new_state,
                client_order_id=client_order_id,
                error=f"유효하지 않은 전이: {current} → {new_state}",
            )

        # DB 업데이트
        try:
            self._update_state_db(client_order_id, new_state, reason, metadata)
        except Exception as e:
            logger.error(f"상태 업데이트 실패 ({client_order_id}): {e}")
            return TransitionResult(
                success=False,
                from_state=current, to_state=new_state,
                client_order_id=client_order_id,
                error=str(e),
            )

        # Audit + Notification
        self._audit_transition(client_order_id, current, new_state, reason, metadata)
        self._notify_transition(client_order_id, current, new_state)

        return TransitionResult(
            success=True,
            from_state=current, to_state=new_state,
            client_order_id=client_order_id,
            reason=reason,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 체결 기록
    # ─────────────────────────────────────────────────────────────────────

    def record_fill(
        self,
        client_order_id: str,
        fill_quantity: int,
        fill_price: float,
        kis_fill_id: str | None = None,
        commission_krw: float = 0,
    ) -> dict:
        """
        체결 기록 + 누적 체결량 따라 자동 상태 전이.
        """
        if fill_quantity <= 0 or fill_price <= 0:
            return {"success": False, "error": "fill_quantity > 0, fill_price > 0 필요"}

        try:
            # 1. live_fills 기록
            fill_value = fill_quantity * fill_price
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO live_fills (
                        client_order_id, kis_fill_id, fill_quantity, fill_price,
                        fill_value_krw, commission_krw, filled_at
                    ) VALUES (
                        :coid, :kfid, :fq, :fp, :fv, :cm, CURRENT_TIMESTAMP
                    )
                """), {
                    "coid": client_order_id, "kfid": kis_fill_id,
                    "fq": fill_quantity, "fp": fill_price,
                    "fv": fill_value, "cm": commission_krw,
                })

                # 2. live_orders 누적 업데이트
                conn.execute(text("""
                    UPDATE live_orders
                    SET filled_quantity = COALESCE(filled_quantity, 0) + :fq,
                        avg_fill_price = CASE
                            WHEN COALESCE(filled_quantity, 0) = 0 THEN :fp
                            ELSE (COALESCE(avg_fill_price, 0) * COALESCE(filled_quantity, 0) + :fp * :fq)
                                  / (COALESCE(filled_quantity, 0) + :fq)
                        END,
                        commission_krw = COALESCE(commission_krw, 0) + :cm,
                        first_fill_at = COALESCE(first_fill_at, CURRENT_TIMESTAMP),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE client_order_id = :coid
                """), {
                    "coid": client_order_id, "fq": fill_quantity,
                    "fp": fill_price, "cm": commission_krw,
                })
        except Exception as e:
            logger.error(f"Fill 기록 실패: {e}")
            return {"success": False, "error": str(e)}

        # 3. 누적량 확인 → 자동 전이
        with self.engine.connect() as conn:
            row = conn.execute(text(
                "SELECT quantity, filled_quantity, status FROM live_orders "
                "WHERE client_order_id = :coid"
            ), {"coid": client_order_id}).fetchone()

        if row:
            m = row._mapping
            total_qty = int(m["quantity"] or 0)
            filled_qty = int(m["filled_quantity"] or 0)
            current_state = m["status"]

            if filled_qty >= total_qty:
                new_state = OrderState.FILLED
            else:
                new_state = OrderState.PARTIAL_FILL

            if current_state != new_state:
                self.transition(
                    client_order_id, new_state,
                    reason=f"누적 체결 {filled_qty}/{total_qty}",
                    metadata={"fill_qty": fill_quantity, "fill_price": fill_price},
                )

            # 알림 (체결)
            if self.notifier:
                try:
                    sev_method = self.notifier.info
                    msg = (
                        f"{m.get('ticker', '?')} {fill_quantity}주 @ {fill_price:,.0f}원"
                    )
                    if new_state == OrderState.FILLED:
                        sev_method = self.notifier.info
                        msg = f"전량 체결: {msg}"
                    sev_method(title="체결", message=msg,
                                context={"order_id": client_order_id})
                except Exception:
                    pass

        return {
            "success": True,
            "client_order_id": client_order_id,
            "fill_quantity": fill_quantity,
            "fill_price": fill_price,
            "fill_value_krw": fill_value,
        }

    # ─────────────────────────────────────────────────────────────────────
    # 장 마감 미체결 정리
    # ─────────────────────────────────────────────────────────────────────

    def cleanup_market_close(
        self,
        kis_client,
        policy: str = "conservative_cancel",
        force: bool = False,
    ) -> dict:
        """
        장 마감 전 미체결 주문 정리.

        policy:
          · conservative_cancel — 모든 미체결 취소 (안전, 기본)
          · aggressive_fill     — 시장가로 정정 시도 (즉시 체결)
          · hold                — 그대로 두기 (다음 영업일)

        force=False면 15:15 이후에만 실행.
        """
        now = datetime.now(KST).time()
        if not force and now < MARKET_CLOSE_CUTOFF:
            return {
                "executed": False,
                "reason": f"장 마감 정리 시간 미도래 ({now} < {MARKET_CLOSE_CUTOFF})",
            }

        # 활성 주문 조회
        active_orders = self.list_active_orders()
        if not active_orders:
            return {"executed": True, "policy": policy, "n_processed": 0,
                     "n_cancelled": 0, "n_force_filled": 0}

        n_cancelled = 0
        n_force_filled = 0
        n_failed = 0
        details = []

        for order in active_orders:
            coid = order["client_order_id"]
            ticker = order["ticker"]
            side = order["side"]
            remaining = int(order.get("quantity", 0) or 0) - \
                         int(order.get("filled_quantity", 0) or 0)
            if remaining <= 0:
                continue

            try:
                if policy == "conservative_cancel":
                    kis_client.cancel_order(
                        kis_order_id=order.get("kis_order_org_no") or order.get("kis_order_id") or "0",
                        kis_order_no=order.get("kis_order_id") or "0",
                        cancel_qty=remaining,
                    )
                    self.transition(
                        coid, OrderState.CANCELLED,
                        reason="장 마감 자동 정리",
                        metadata={"policy": policy, "remaining_qty": remaining},
                    )
                    n_cancelled += 1
                    details.append({"coid": coid, "action": "cancelled",
                                     "qty": remaining})

                elif policy == "aggressive_fill":
                    # 기존 미체결 취소 후 시장가 재발주
                    try:
                        kis_client.cancel_order(
                            kis_order_id=order.get("kis_order_org_no") or "0",
                            kis_order_no=order.get("kis_order_id") or "0",
                            cancel_qty=remaining,
                        )
                        # 시장가로 즉시 체결 시도
                        new_resp = kis_client.place_order(
                            ticker=ticker, side=side,
                            quantity=remaining, order_type="MARKET",
                        )
                        self.transition(
                            coid, OrderState.CANCELLED,
                            reason="장 마감 시장가 정정 - 원 주문 취소",
                        )
                        n_force_filled += 1
                        details.append({
                            "coid": coid, "action": "force_filled",
                            "new_kis_order": new_resp.get("kis_order_no"),
                            "qty": remaining,
                        })
                    except Exception as e:
                        n_failed += 1
                        details.append({"coid": coid, "action": "failed", "error": str(e)})

                else:  # hold
                    details.append({"coid": coid, "action": "held",
                                     "qty": remaining})

            except Exception as e:
                n_failed += 1
                logger.error(f"장 마감 정리 실패 ({coid}): {e}")
                details.append({"coid": coid, "action": "failed", "error": str(e)})

        # Audit + Notification
        result = {
            "executed":       True,
            "policy":         policy,
            "n_processed":    len(active_orders),
            "n_cancelled":    n_cancelled,
            "n_force_filled": n_force_filled,
            "n_failed":       n_failed,
            "details":        details,
        }

        if self.audit:
            try:
                from src.execution.audit_trail import EventCategory, Severity
                sev = Severity.WARN if n_failed > 0 else Severity.INFO
                self.audit.log(
                    event_type="MARKET_CLOSE_CLEANUP",
                    category=EventCategory.SYSTEM,
                    severity=sev,
                    context=result,
                    message=f"장 마감 정리 ({policy}): cancelled={n_cancelled}, "
                            f"force_filled={n_force_filled}, failed={n_failed}",
                )
            except Exception:
                pass

        if self.notifier and (n_cancelled + n_force_filled + n_failed) > 0:
            try:
                self.notifier.warn(
                    title="장 마감 미체결 정리",
                    message=f"{policy} 정책 적용 — "
                            f"취소 {n_cancelled} · 정정 {n_force_filled} · 실패 {n_failed}",
                    context={"n_processed": len(active_orders)},
                )
            except Exception:
                pass

        return result

    # ─────────────────────────────────────────────────────────────────────
    # 조회
    # ─────────────────────────────────────────────────────────────────────

    def list_active_orders(self) -> list[dict]:
        """체결 대기 중인 모든 주문."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text(f"""
                    SELECT * FROM live_orders
                    WHERE status IN ({','.join(repr(s) for s in OrderState.ACTIVE)})
                    ORDER BY created_at DESC
                """)).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception as e:
            logger.error(f"Active orders 조회 실패: {e}")
            return []

    def state_distribution(self) -> dict:
        """현재 모든 주문의 상태 분포."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT status, COUNT(*) AS cnt FROM live_orders
                    GROUP BY status
                """)).fetchall()
            return {r._mapping["status"]: r._mapping["cnt"] for r in rows}
        except Exception:
            return {}

    # ─────────────────────────────────────────────────────────────────────
    # 내부
    # ─────────────────────────────────────────────────────────────────────

    def _get_current_state(self, client_order_id: str) -> str | None:
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT status FROM live_orders WHERE client_order_id = :coid"
                ), {"coid": client_order_id}).fetchone()
                return row._mapping["status"] if row else None
        except Exception as e:
            logger.error(f"_get_current_state 실패: {e}")
            return None

    def _update_state_db(
        self, coid: str, new_state: str,
        reason: str | None, metadata: dict | None,
    ):
        # 상태별 timestamp 컬럼 매핑
        ts_col_map = {
            OrderState.SUBMITTED: "submitted_at",
            OrderState.CANCELLED: "cancelled_at",
            OrderState.FILLED:    "completed_at",
            OrderState.EXPIRED:   "completed_at",
        }
        ts_col = ts_col_map.get(new_state)

        sql = """
            UPDATE live_orders
            SET status = :st, updated_at = CURRENT_TIMESTAMP
        """
        params = {"st": new_state, "coid": coid}

        if ts_col:
            sql += f", {ts_col} = CURRENT_TIMESTAMP"

        if reason:
            sql += ", reason_code = :rc"
            params["rc"] = reason[:40]

        if metadata and metadata.get("kis_order_no"):
            sql += ", kis_order_id = COALESCE(kis_order_id, :koid)"
            params["koid"] = metadata["kis_order_no"]

        sql += " WHERE client_order_id = :coid"

        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def _audit_transition(self, coid, from_state, to_state, reason, metadata):
        if not self.audit:
            return
        try:
            from src.execution.audit_trail import EventCategory, EventType, Severity
            ev_map = {
                OrderState.SUBMITTED: EventType.ORDER_SUBMITTED,
                OrderState.FILLED:    EventType.ORDER_FILLED,
                OrderState.PARTIAL_FILL: EventType.ORDER_PARTIAL_FILL,
                OrderState.CANCELLED: EventType.ORDER_CANCELLED,
                OrderState.REJECTED:  EventType.ORDER_REJECTED,
                OrderState.EXPIRED:   "ORDER_EXPIRED",
                OrderState.FAILED:    EventType.ORDER_FAILED,
            }
            event_type = ev_map.get(to_state, "STATE_TRANSITION")

            sev = Severity.WARN if to_state in (
                OrderState.REJECTED, OrderState.FAILED, OrderState.EXPIRED,
            ) else Severity.INFO

            self.audit.log(
                event_type=event_type, category=EventCategory.ORDER,
                severity=sev, client_order_id=coid,
                decision=to_state,
                context={"from_state": from_state, "to_state": to_state,
                          "metadata": metadata or {}},
                message=reason or f"{from_state} → {to_state}",
            )
        except Exception as e:
            logger.error(f"Audit transition 실패: {e}")

    def _audit_invalid_transition(self, coid, from_state, to_state, reason):
        if not self.audit:
            return
        try:
            from src.execution.audit_trail import EventCategory, Severity
            self.audit.log(
                event_type="INVALID_STATE_TRANSITION",
                category=EventCategory.SYSTEM,
                severity=Severity.ERROR,
                client_order_id=coid,
                context={"from_state": from_state, "to_state": to_state,
                          "reason": reason},
                message=f"⚠ 유효하지 않은 상태 전이: {from_state} → {to_state}",
            )
        except Exception:
            pass

    def _notify_transition(self, coid, from_state, to_state):
        """중요 상태 전이만 알림."""
        if not self.notifier:
            return
        try:
            if to_state == OrderState.REJECTED:
                self.notifier.warn(
                    "주문 거부", f"{coid}: {from_state} → REJECTED",
                )
            elif to_state == OrderState.FAILED:
                self.notifier.critical(
                    "주문 실패", f"{coid}: {from_state} → FAILED",
                )
            elif to_state == OrderState.EXPIRED:
                self.notifier.warn(
                    "주문 만료", f"{coid}: 장 마감으로 만료",
                )
        except Exception:
            pass
