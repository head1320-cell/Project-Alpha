"""
Kill Switch — 비상 정지 시스템
====================================
모든 trading 활동을 즉시 중단. 가장 중요한 안전장치.

발동 트리거:
  · MANUAL    — 사용자 버튼 클릭
  · AUTO_DD   — 누적 drawdown -10% 초과
  · AUTO_RISK — Stage 9 systemic_risk_score = PANIC (>85)
  · AUTO_API  — KIS API 연속 실패 (circuit breaker)
  · AUTO_CB   — Daily loss -5% 초과 (intraday circuit breaker)

발동 시 액션:
  ① 모든 신규 주문 거부 (executor에 lock)
  ② 미체결 주문 일괄 취소 (KIS cancel API 호출)
  ③ (옵션) 포지션 청산
       · gradual: 시장가 분할 매도 (5분 간격)
       · immediate: 시장가 즉시 전량
       · hold: 미체결만 취소, 포지션 유지
  ④ Slack/Email 알림 (옵션)
  ⑤ Audit trail CRITICAL 기록
  ⑥ live_kill_events 테이블에 영구 기록

해제:
  · 사용자가 명시적으로 resolve 호출 (수동 해제만)
  · resolved_at + resolved_by + resolution_notes 기록
  · 자동 해제 없음 (안전을 위해)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class KillSwitchConfig:
    auto_dd_threshold:        float = 0.10   # 누적 -10%
    auto_intraday_loss:       float = 0.05   # 일중 -5%
    auto_risk_score:          float = 85.0   # PANIC 임계값
    api_failure_threshold:    int = 5

    default_liquidation_mode: str = "hold"   # gradual | immediate | hold
    notification_enabled:     bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# KillSwitch
# ═══════════════════════════════════════════════════════════════════════════════

class KillSwitch:
    """
    Trading 시스템 비상 정지.

    Usage:
        ks = KillSwitch(engine, audit_trail, config=KillSwitchConfig())

        # 수동 발동
        event = ks.trigger(
            source="manual",
            reason="사용자 직접 정지",
            equity=100_000_000,
            kis_client=client,
            liquidation_mode="hold",
        )

        # 자동 발동 (모니터링 루프에서 호출)
        if ks.should_auto_trigger(account_state, regime_state):
            ks.trigger(source="auto_dd", reason="drawdown 한도 초과", ...)

        # 상태 확인
        if ks.is_active():
            # 모든 주문 거부

        # 해제
        ks.resolve(resolved_by="admin", notes="시장 안정화 확인")
    """

    def __init__(self, engine, audit_trail=None, config: KillSwitchConfig | None = None):
        self.engine = engine
        self.audit = audit_trail
        self.config = config or KillSwitchConfig()
        self._cached_active: bool | None = None

    # ─────────────────────────────────────────────────────────────────────
    # 상태 확인
    # ─────────────────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        """현재 kill switch 활성 여부."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT COUNT(*) AS cnt FROM live_kill_events
                    WHERE resolved_at IS NULL
                """)).fetchone()
                return (row._mapping["cnt"] if row else 0) > 0
        except Exception as e:
            logger.error(f"Kill switch 상태 조회 실패: {e}")
            return True   # 안전: 조회 실패 시 active 가정

    def active_event(self) -> dict | None:
        """현재 미해결 kill 이벤트 (있다면)."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT * FROM live_kill_events
                    WHERE resolved_at IS NULL
                    ORDER BY triggered_at DESC LIMIT 1
                """)).fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.error(f"Kill event 조회 실패: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────
    # 자동 발동 트리거 검사
    # ─────────────────────────────────────────────────────────────────────

    def should_auto_trigger(
        self,
        account_state: dict,
        regime_state: dict | None = None,
    ) -> tuple[str, str] | None:
        """
        자동 발동 조건 검사. 발동 필요 시 (source, reason) 튜플 반환.
        """
        if self.is_active():
            return None  # 이미 발동된 상태

        # 1. 누적 drawdown
        cumul_dd = abs(account_state.get("cumulative_dd_pct", 0) or 0)
        if cumul_dd >= self.config.auto_dd_threshold:
            return ("auto_dd",
                     f"누적 drawdown 한도 초과 ({cumul_dd:.1%} >= {self.config.auto_dd_threshold:.0%})")

        # 2. 일중 손실
        intraday = abs(account_state.get("current_drawdown_pct", 0) or 0)
        if intraday >= self.config.auto_intraday_loss:
            return ("auto_cb",
                     f"일중 손실 한도 초과 ({intraday:.1%} >= {self.config.auto_intraday_loss:.0%})")

        # 3. Systemic risk PANIC
        if regime_state:
            risk_score = regime_state.get("systemic_risk_score", 0) or 0
            if risk_score >= self.config.auto_risk_score:
                return ("auto_risk",
                         f"PANIC 국면 감지 (risk_score={risk_score:.0f})")

        # 4. API 실패율 (외부에서 주입)
        api_failures = account_state.get("api_failure_count", 0)
        if api_failures >= self.config.api_failure_threshold:
            return ("auto_api",
                     f"KIS API 연속 실패 ({api_failures}회)")

        return None

    # ─────────────────────────────────────────────────────────────────────
    # 발동
    # ─────────────────────────────────────────────────────────────────────

    def trigger(
        self,
        source: str,
        reason: str,
        equity: float = 0,
        dd_pct: float = 0,
        regime: str | None = None,
        kis_client=None,
        liquidation_mode: str | None = None,
    ) -> dict:
        """
        Kill switch 발동.

        Args:
            source:           manual | auto_dd | auto_cb | auto_risk | auto_api
            reason:           발동 사유 (자유 텍스트)
            equity:           발동 시점 자산
            dd_pct:           발동 시점 drawdown
            regime:           발동 시점 regime
            kis_client:       KIS API 클라이언트 (미체결 취소용)
            liquidation_mode: gradual | immediate | hold

        Returns:
            event 정보 dict
        """
        if self.is_active():
            logger.warning("Kill switch 이미 발동 중 — 중복 trigger 무시")
            return self.active_event() or {}

        event_id = f"KILL-{uuid.uuid4().hex[:12]}"
        liq_mode = liquidation_mode or self.config.default_liquidation_mode

        # 1. DB 이벤트 기록
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO live_kill_events (
                        event_id, trigger_source, trigger_reason,
                        equity_at_trigger, dd_at_trigger, regime_at_trigger,
                        liquidation_mode
                    ) VALUES (
                        :eid, :ts, :tr, :eq, :dd, :rg, :lm
                    )
                """), {
                    "eid": event_id, "ts": source, "tr": reason,
                    "eq": equity, "dd": dd_pct, "rg": regime, "lm": liq_mode,
                })
        except Exception as e:
            logger.error(f"Kill event DB 기록 실패: {e}")

        # 2. Audit trail CRITICAL 기록
        if self.audit:
            self.audit.log_kill_switch(event_id, source, reason, equity, dd_pct)

        logger.critical(f"🚨 KILL SWITCH ACTIVATED — {source}: {reason}")

        # 3. 미체결 주문 취소
        cancelled_count = 0
        if kis_client:
            cancelled_count = self._cancel_open_orders(kis_client)

        # 4. 청산 (옵션)
        positions_closed = 0
        krw_recovered = 0
        if liq_mode in ("immediate", "gradual") and kis_client:
            positions_closed, krw_recovered = self._liquidate_positions(
                kis_client, mode=liq_mode,
            )

        # 5. 통계 업데이트
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE live_kill_events
                    SET n_orders_cancelled = :nc,
                        n_positions_closed = :np,
                        krw_recovered = :kr
                    WHERE event_id = :eid
                """), {
                    "nc": cancelled_count, "np": positions_closed,
                    "kr": krw_recovered, "eid": event_id,
                })
        except Exception:
            pass

        # 6. 알림 (placeholder — Slack/Email 통합 가능)
        if self.config.notification_enabled:
            self._send_notification(event_id, source, reason, equity, dd_pct)

        return {
            "event_id":             event_id,
            "triggered_at":         datetime.now().isoformat(),
            "trigger_source":       source,
            "trigger_reason":       reason,
            "equity_at_trigger":    equity,
            "dd_at_trigger":        dd_pct,
            "liquidation_mode":     liq_mode,
            "n_orders_cancelled":   cancelled_count,
            "n_positions_closed":   positions_closed,
            "krw_recovered":        krw_recovered,
        }

    # ─────────────────────────────────────────────────────────────────────
    # 해제
    # ─────────────────────────────────────────────────────────────────────

    def resolve(self, resolved_by: str, notes: str = "") -> dict:
        """Kill switch 수동 해제."""
        event = self.active_event()
        if not event:
            return {"status": "no_active_event"}

        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE live_kill_events
                    SET resolved_at = CURRENT_TIMESTAMP,
                        resolved_by = :rb,
                        resolution_notes = :rn
                    WHERE event_id = :eid
                """), {
                    "rb": resolved_by, "rn": notes, "eid": event["event_id"],
                })
        except Exception as e:
            logger.error(f"Kill 해제 실패: {e}")
            return {"status": "db_error", "error": str(e)}

        # Audit
        if self.audit:
            from src.execution.audit_trail import EventCategory, EventType, Severity
            self.audit.log(
                event_type=EventType.KILL_SWITCH_RESOLVED,
                category=EventCategory.EMERGENCY,
                severity=Severity.CRITICAL,
                actor=resolved_by,
                context={"event_id": event["event_id"], "notes": notes},
                message=f"Kill switch 해제: {notes or '사유 없음'}",
            )

        logger.warning(f"Kill switch 해제: event {event['event_id']} by {resolved_by}")
        return {
            "status":      "resolved",
            "event_id":    event["event_id"],
            "resolved_by": resolved_by,
            "notes":       notes,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Internal: 미체결 취소
    # ─────────────────────────────────────────────────────────────────────

    def _cancel_open_orders(self, kis_client) -> int:
        """모든 미체결 주문 일괄 취소."""
        cancelled = 0
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT client_order_id, kis_order_id, kis_order_org_no,
                           filled_quantity, quantity
                    FROM live_orders
                    WHERE status IN ('PENDING', 'SUBMITTED', 'PARTIAL_FILL')
                """)).fetchall()

            for r in rows:
                m = r._mapping
                remaining = (m["quantity"] or 0) - (m["filled_quantity"] or 0)
                if remaining <= 0 or not m["kis_order_id"]:
                    continue
                try:
                    kis_client.cancel_order(
                        kis_order_id=m["kis_order_org_no"] or m["kis_order_id"],
                        kis_order_no=m["kis_order_id"],
                        cancel_qty=remaining,
                    )
                    # 상태 업데이트
                    with self.engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE live_orders
                            SET status = 'CANCELLED', cancelled_at = CURRENT_TIMESTAMP,
                                reason_code = 'kill_switch'
                            WHERE client_order_id = :coid
                        """), {"coid": m["client_order_id"]})
                    cancelled += 1
                except Exception as e:
                    logger.error(f"주문 취소 실패 ({m['client_order_id']}): {e}")
        except Exception as e:
            logger.error(f"미체결 조회 실패: {e}")

        return cancelled

    # ─────────────────────────────────────────────────────────────────────
    # Internal: 청산
    # ─────────────────────────────────────────────────────────────────────

    def _liquidate_positions(self, kis_client, mode: str = "gradual") -> tuple[int, float]:
        """
        보유 포지션 청산.

        gradual: 큰 포지션부터 분할 매도 (시장 충격 최소화)
        immediate: 시장가 즉시 전량 매도
        """
        n_closed = 0
        krw_recovered = 0.0

        try:
            balance = kis_client.get_balance()
            positions = balance.get("positions", [])

            for pos in positions:
                ticker = pos["ticker"]
                qty = pos["quantity"]
                if qty <= 0:
                    continue

                if mode == "immediate":
                    # 즉시 시장가
                    try:
                        kis_client.place_order(
                            ticker=ticker, side="SELL", quantity=qty,
                            order_type="MARKET",
                        )
                        n_closed += 1
                        krw_recovered += pos.get("eval_amount", 0)
                        logger.warning(f"비상 청산: {ticker} {qty}주 시장가 (event)")
                    except Exception as e:
                        logger.error(f"청산 실패 ({ticker}): {e}")

                elif mode == "gradual":
                    # 5분할 — 실제 구현은 백그라운드 task로 (간이 구현: 1/5만 즉시)
                    portion = max(1, qty // 5)
                    try:
                        kis_client.place_order(
                            ticker=ticker, side="SELL", quantity=portion,
                            order_type="MARKET",
                        )
                        n_closed += 1
                        krw_recovered += portion * pos["current_price"]
                        logger.warning(
                            f"점진 청산 1/5: {ticker} {portion}/{qty}주 "
                            f"(추가 4회 분할 매도 필요)"
                        )
                    except Exception as e:
                        logger.error(f"점진 청산 실패 ({ticker}): {e}")

        except Exception as e:
            logger.error(f"청산 절차 실패: {e}")

        return n_closed, krw_recovered

    # ─────────────────────────────────────────────────────────────────────
    # Internal: 알림
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _send_notification(event_id: str, source: str, reason: str,
                            equity: float, dd_pct: float):
        """Slack/Email 알림 (현재는 로깅만, 추후 webhook 통합)."""
        msg = (
            f"🚨 KILL SWITCH ACTIVATED\n"
            f"Event: {event_id}\n"
            f"Source: {source}\n"
            f"Reason: {reason}\n"
            f"Equity: {equity:,.0f}원\n"
            f"Drawdown: {dd_pct:.2%}\n"
            f"Time: {datetime.now().isoformat()}"
        )
        logger.critical(msg)
        # TODO: webhook integration
        #   requests.post(SLACK_WEBHOOK_URL, json={"text": msg})
