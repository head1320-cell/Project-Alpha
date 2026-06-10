"""
Audit Trail — 모든 실거래 의사결정의 감사 로그
==================================================
실거래 시스템의 핵심 요구사항: "왜 그 주문이 발주되었는지" 사후 추적.

기록 대상:
  · Signal 수신 (전략 신호 발생)
  · Risk Check 결과 (승인/거부 + 사유)
  · Order Submitted (KIS 전송)
  · Order Filled (체결)
  · Order Cancelled / Rejected
  · Kill Switch 발동
  · 모드 변경 (SHADOW/PAPER/LIVE)
  · Daily reset

심각도 분류:
  · INFO    — 정상 흐름
  · WARN    — 경고 (예: market impact > 50bp)
  · ERROR   — 에러 (예: API 호출 실패)
  · CRITICAL — 시스템 중대 (예: kill switch, 한도 초과)

조회:
  · 시간 범위
  · 심각도
  · 이벤트 타입
  · 전략/주문 ID
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Event Types
# ═══════════════════════════════════════════════════════════════════════════════

class EventType:
    """이벤트 타입 상수."""
    # Signal
    SIGNAL_RECEIVED       = "SIGNAL_RECEIVED"
    SIGNAL_FILTERED       = "SIGNAL_FILTERED"

    # Risk
    RISK_CHECK_APPROVED   = "RISK_CHECK_APPROVED"
    RISK_CHECK_REJECTED   = "RISK_CHECK_REJECTED"
    RISK_CHECK_WARNING    = "RISK_CHECK_WARNING"

    # Order lifecycle
    ORDER_SUBMITTED       = "ORDER_SUBMITTED"
    ORDER_ACCEPTED        = "ORDER_ACCEPTED"
    ORDER_FILLED          = "ORDER_FILLED"
    ORDER_PARTIAL_FILL    = "ORDER_PARTIAL_FILL"
    ORDER_CANCELLED       = "ORDER_CANCELLED"
    ORDER_REJECTED        = "ORDER_REJECTED"
    ORDER_FAILED          = "ORDER_FAILED"

    # Mode
    MODE_CHANGED          = "MODE_CHANGED"

    # Kill switch
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    KILL_SWITCH_RESOLVED  = "KILL_SWITCH_RESOLVED"

    # System
    SYSTEM_START          = "SYSTEM_START"
    SYSTEM_STOP           = "SYSTEM_STOP"
    DAILY_RESET           = "DAILY_RESET"
    DAILY_SUMMARY         = "DAILY_SUMMARY"


class EventCategory:
    SIGNAL    = "SIGNAL"
    RISK      = "RISK"
    ORDER     = "ORDER"
    EXECUTION = "EXECUTION"
    SYSTEM    = "SYSTEM"
    EMERGENCY = "EMERGENCY"


class Severity:
    INFO     = "INFO"
    WARN     = "WARN"
    ERROR    = "ERROR"
    CRITICAL = "CRITICAL"


# ═══════════════════════════════════════════════════════════════════════════════
# AuditTrail
# ═══════════════════════════════════════════════════════════════════════════════

class AuditTrail:
    """
    실거래 감사 로그 관리자.

    Usage:
        audit = AuditTrail(engine)

        # 이벤트 기록
        audit_id = audit.log(
            event_type=EventType.RISK_CHECK_APPROVED,
            category=EventCategory.RISK,
            severity=Severity.INFO,
            strategy_id=1,
            client_order_id="CO-abc123",
            ticker="005930",
            decision="APPROVED",
            risk_tier="tier_2",
            reason_code="all_checks_passed",
            context={"checks": [...], "warnings": []},
            message="모든 위험 검증 통과",
        )

        # 조회
        events = audit.query(
            start=datetime.now() - timedelta(hours=1),
            severity_min=Severity.WARN,
        )
    """

    def __init__(self, engine):
        self.engine = engine

    # ─────────────────────────────────────────────────────────────────────
    # 기록
    # ─────────────────────────────────────────────────────────────────────

    def log(
        self,
        event_type: str,
        category: str = EventCategory.SYSTEM,
        severity: str = Severity.INFO,
        strategy_id: int | None = None,
        client_order_id: str | None = None,
        ticker: str | None = None,
        decision: str | None = None,
        risk_tier: str | None = None,
        reason_code: str | None = None,
        context: dict | None = None,
        actor: str = "system",
        message: str | None = None,
    ) -> str:
        """단일 audit 이벤트 기록. 반환: audit_id."""
        audit_id = f"AUD-{uuid.uuid4().hex[:12]}"

        # context를 안전하게 JSON 직렬화
        try:
            context_json = json.dumps(context, default=str) if context else None
        except Exception as e:
            logger.warning(f"context 직렬화 실패: {e}")
            context_json = json.dumps({"error": str(e)})

        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO live_audit_trail (
                        audit_id, event_type, event_category, severity,
                        strategy_id, client_order_id, ticker,
                        decision, risk_tier, reason_code,
                        context_json, actor, message
                    ) VALUES (
                        :aid, :et, :ec, :sv,
                        :sid, :coid, :tk,
                        :dec, :rt, :rc,
                        :cj, :ac, :msg
                    )
                """), {
                    "aid": audit_id, "et": event_type, "ec": category, "sv": severity,
                    "sid": strategy_id, "coid": client_order_id, "tk": ticker,
                    "dec": decision, "rt": risk_tier, "rc": reason_code,
                    "cj": context_json, "ac": actor, "msg": message,
                })

            # 중요 이벤트는 표준 로거에도 기록
            if severity in (Severity.ERROR, Severity.CRITICAL):
                logger.error(f"[AUDIT {severity}] {event_type}: {message}")
            elif severity == Severity.WARN:
                logger.warning(f"[AUDIT WARN] {event_type}: {message}")
        except Exception as e:
            logger.error(f"Audit log 실패: {e}")

        return audit_id

    # ─────────────────────────────────────────────────────────────────────
    # 편의 메서드 (자주 쓰는 이벤트)
    # ─────────────────────────────────────────────────────────────────────

    def log_signal(self, strategy_id: int, ticker: str, side: str, quantity: int,
                    source: str = "stage11", context: dict | None = None) -> str:
        return self.log(
            event_type=EventType.SIGNAL_RECEIVED,
            category=EventCategory.SIGNAL,
            severity=Severity.INFO,
            strategy_id=strategy_id, ticker=ticker,
            context={"side": side, "quantity": quantity, "source": source, **(context or {})},
            message=f"신호 수신: {side} {ticker} {quantity}주 (sid={strategy_id})",
        )

    def log_risk_decision(self, check_result, order: dict) -> str:
        """RiskCheckResult를 받아서 audit 기록."""
        if check_result.approved:
            return self.log(
                event_type=EventType.RISK_CHECK_APPROVED,
                category=EventCategory.RISK,
                severity=Severity.WARN if check_result.warnings else Severity.INFO,
                strategy_id=order.get("strategy_id"),
                ticker=order.get("ticker"),
                decision="APPROVED",
                reason_code="all_checks_passed",
                context={
                    "check_id": check_result.check_id,
                    "checks_passed": check_result.checks_passed,
                    "warnings": check_result.warnings,
                    "metadata": check_result.metadata,
                    "order": order,
                },
                message=f"위험 검증 통과 ({len(check_result.checks_passed)}/10), "
                        f"경고 {len(check_result.warnings)}건",
            )
        else:
            return self.log(
                event_type=EventType.RISK_CHECK_REJECTED,
                category=EventCategory.RISK,
                severity=Severity.WARN,
                strategy_id=order.get("strategy_id"),
                ticker=order.get("ticker"),
                decision="REJECTED",
                reason_code="risk_check_failed",
                context={
                    "check_id": check_result.check_id,
                    "tier_failures": check_result.tier_failures,
                    "order": order,
                },
                message=check_result.rejected_reason or "위험 검증 거부",
            )

    def log_order_submitted(self, client_order_id: str, order: dict,
                              kis_response: dict | None = None) -> str:
        return self.log(
            event_type=EventType.ORDER_SUBMITTED,
            category=EventCategory.ORDER,
            severity=Severity.INFO,
            strategy_id=order.get("strategy_id"),
            client_order_id=client_order_id,
            ticker=order["ticker"],
            decision="SUBMITTED",
            context={
                "side": order["side"], "quantity": order["quantity"],
                "price": order.get("price"),
                "order_type": order.get("order_type", "MARKET"),
                "kis_response": kis_response,
            },
            message=f"주문 발주: {order['side']} {order['ticker']} {order['quantity']}주",
        )

    def log_order_filled(self, client_order_id: str, fill_qty: int,
                           fill_price: float, ticker: str) -> str:
        return self.log(
            event_type=EventType.ORDER_FILLED,
            category=EventCategory.EXECUTION,
            severity=Severity.INFO,
            client_order_id=client_order_id, ticker=ticker,
            decision="FILLED",
            context={"fill_quantity": fill_qty, "fill_price": fill_price,
                      "fill_value_krw": fill_qty * fill_price},
            message=f"체결: {ticker} {fill_qty}주 @ {fill_price:,.0f}원",
        )

    def log_kill_switch(self, event_id: str, trigger_source: str, reason: str,
                          equity: float, dd_pct: float) -> str:
        return self.log(
            event_type=EventType.KILL_SWITCH_TRIGGERED,
            category=EventCategory.EMERGENCY,
            severity=Severity.CRITICAL,
            actor=trigger_source,
            reason_code="kill_switch",
            context={
                "event_id": event_id, "equity_krw": equity,
                "drawdown_pct": dd_pct,
            },
            message=f"🚨 Kill switch 발동: {reason}",
        )

    def log_mode_change(self, old_mode: str, new_mode: str, actor: str = "user") -> str:
        return self.log(
            event_type=EventType.MODE_CHANGED,
            category=EventCategory.SYSTEM,
            severity=Severity.WARN if new_mode == "LIVE" else Severity.INFO,
            actor=actor,
            decision=new_mode,
            context={"from": old_mode, "to": new_mode},
            message=f"실행 모드 전환: {old_mode} → {new_mode}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # 조회
    # ─────────────────────────────────────────────────────────────────────

    def query(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        event_type: str | None = None,
        severity_min: str | None = None,
        category: str | None = None,
        strategy_id: int | None = None,
        client_order_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """조건 조회."""
        severity_levels = {"INFO": 0, "WARN": 1, "ERROR": 2, "CRITICAL": 3}

        sql = "SELECT * FROM live_audit_trail WHERE 1=1"
        params: dict = {}

        if start:
            sql += " AND timestamp >= :start"; params["start"] = start
        if end:
            sql += " AND timestamp <= :end"; params["end"] = end
        if event_type:
            sql += " AND event_type = :et"; params["et"] = event_type
        if category:
            sql += " AND event_category = :cat"; params["cat"] = category
        if strategy_id is not None:
            sql += " AND strategy_id = :sid"; params["sid"] = strategy_id
        if client_order_id:
            sql += " AND client_order_id = :coid"; params["coid"] = client_order_id
        if severity_min:
            min_lvl = severity_levels.get(severity_min, 0)
            ok_sev = [k for k, v in severity_levels.items() if v >= min_lvl]
            placeholders = ",".join(f":s{i}" for i in range(len(ok_sev)))
            sql += f" AND severity IN ({placeholders})"
            for i, s in enumerate(ok_sev):
                params[f"s{i}"] = s

        sql += " ORDER BY timestamp DESC LIMIT :limit"
        params["limit"] = limit

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text(sql), params).fetchall()
            results = []
            for r in rows:
                d = dict(r._mapping)
                # context_json → dict
                if d.get("context_json"):
                    try:
                        d["context"] = json.loads(d["context_json"])
                    except Exception:
                        pass
                    d.pop("context_json", None)
                results.append(d)
            return results
        except Exception as e:
            logger.error(f"Audit query 실패: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # 통계
    # ─────────────────────────────────────────────────────────────────────

    def daily_summary(self, date: str | None = None) -> dict:
        """단일 거래일 audit 요약."""
        if date is None:
            date = datetime.now().date().isoformat()

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT event_type, event_category, severity, COUNT(*) AS cnt
                    FROM live_audit_trail
                    WHERE date(timestamp) = :d
                    GROUP BY event_type, event_category, severity
                    ORDER BY cnt DESC
                """), {"d": date}).fetchall()

                summary = {
                    "date": date,
                    "total_events": 0,
                    "by_severity": {"INFO": 0, "WARN": 0, "ERROR": 0, "CRITICAL": 0},
                    "by_category": {},
                    "by_event_type": {},
                }
                for r in rows:
                    m = r._mapping
                    cnt = m["cnt"]
                    summary["total_events"] += cnt
                    summary["by_severity"][m["severity"]] = \
                        summary["by_severity"].get(m["severity"], 0) + cnt
                    summary["by_category"][m["event_category"]] = \
                        summary["by_category"].get(m["event_category"], 0) + cnt
                    summary["by_event_type"][m["event_type"]] = \
                        summary["by_event_type"].get(m["event_type"], 0) + cnt
                return summary
        except Exception as e:
            return {"date": date, "error": str(e)}
