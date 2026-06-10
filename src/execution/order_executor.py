"""
Order Executor — 실거래 핵심 통합 엔진
=========================================
모든 신호를 받아서 검증 → 라우팅 → 실행 → 기록까지 책임지는 중앙 엔진.

3단계 실행 모드:
  · SHADOW   — 신호 audit만 기록, 주문 X (모니터링용)
  · PAPER    — KIS 모의투자 또는 Mock client로 가상 체결
  · LIVE     — 실거래 (실제 돈 ⚠)

주문 생명주기:
  PENDING       — 신호 수신, 미발주
  RISK_CHECK    — 위험 검증 중
  REJECTED      — 위험 검증 거부
  SUBMITTED     — KIS 전송 완료
  PARTIAL_FILL  — 부분 체결
  FILLED        — 전량 체결
  CANCELLED     — 취소
  FAILED        — API 오류 등

모든 단계가 audit_trail에 기록되며, kill switch가 활성화되면 모든 신규 주문 거부.
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

class ExecutionMode:
    SHADOW = "SHADOW"
    PAPER  = "PAPER"
    LIVE   = "LIVE"
    ALL    = ("SHADOW", "PAPER", "LIVE")


@dataclass
class ExecutorState:
    """현재 executor 상태."""
    mode:              str = ExecutionMode.SHADOW
    started_at:        datetime | None = None
    enabled_strategies: set = None    # 활성 전략 ID 집합 (None=전체)
    last_mode_change:  datetime | None = None
    changed_by:        str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# OrderExecutor
# ═══════════════════════════════════════════════════════════════════════════════

class OrderExecutor:
    """
    실거래 통합 실행 엔진.

    Usage:
        executor = OrderExecutor(
            engine=engine,
            kis_client=kis_client,
            risk_gateway=risk_gw,
            audit_trail=audit,
            kill_switch=ks,
            mode=ExecutionMode.SHADOW,    # 시작은 안전하게 SHADOW
        )

        # 신호 수신 → 실행
        result = executor.execute_signal(
            signal={
                "strategy_id": 1,
                "ticker":      "005930",
                "side":        "BUY",
                "quantity":    100,
                "price":       70000,
                "order_type":  "LIMIT",
            },
        )

        # 모드 전환
        executor.set_mode(ExecutionMode.PAPER, actor="admin")
        executor.set_mode(ExecutionMode.LIVE, actor="admin",
                           confirm_token="EXPLICIT_LIVE_CONFIRMED")
    """

    def __init__(
        self,
        engine,
        kis_client,
        risk_gateway,
        audit_trail,
        kill_switch,
        mode: str = ExecutionMode.SHADOW,
    ):
        self.engine = engine
        self.kis = kis_client
        self.risk = risk_gateway
        self.audit = audit_trail
        self.kill_switch = kill_switch
        self.state = ExecutorState(
            mode=mode,
            started_at=datetime.now(),
            enabled_strategies=set(),
        )

    # ═════════════════════════════════════════════════════════════════════
    # 핵심: 신호 실행
    # ═════════════════════════════════════════════════════════════════════

    def execute_signal(
        self,
        signal: dict,
        account_state: dict | None = None,
        regime_state: dict | None = None,
    ) -> dict:
        """
        신호 → 위험 검증 → 모드 라우팅 → 실행 → 기록.

        Returns:
            {
              "client_order_id": str,
              "status":          PENDING|SUBMITTED|FILLED|REJECTED|FAILED,
              "audit_ids":       [...]
              "kis_response":    {...} or None
              "reason":          str (rejected/failed 시)
            }
        """
        client_order_id = f"CO-{uuid.uuid4().hex[:14]}"
        audit_ids = []

        # ── 1. Signal audit ─────────────────────────────────────────────
        sig_audit = self.audit.log_signal(
            strategy_id=signal.get("strategy_id"),
            ticker=signal["ticker"], side=signal["side"],
            quantity=signal["quantity"],
            context={"price": signal.get("price"),
                      "order_type": signal.get("order_type"),
                      "mode": self.state.mode},
        )
        audit_ids.append(sig_audit)

        # ── 2. Kill switch 우선 확인 ─────────────────────────────────
        if self.kill_switch.is_active():
            return self._reject_order(
                client_order_id, signal,
                reason="kill_switch_active",
                message="Kill switch 활성 — 모든 거래 차단됨",
                audit_ids=audit_ids,
            )

        # ── 3. 전략 활성화 확인 ─────────────────────────────────────
        if self.state.enabled_strategies and \
            signal.get("strategy_id") not in self.state.enabled_strategies:
            return self._reject_order(
                client_order_id, signal,
                reason="strategy_disabled",
                message=f"전략 {signal.get('strategy_id')} 비활성화 상태",
                audit_ids=audit_ids,
            )

        # ── 4. 사전 검증 (Risk Gateway) ────────────────────────────────
        if account_state is None:
            account_state = self._fetch_account_state()

        risk_result = self.risk.check(signal, account_state, regime_state)
        risk_audit = self.audit.log_risk_decision(risk_result, signal)
        audit_ids.append(risk_audit)

        if not risk_result.approved:
            return self._reject_order(
                client_order_id, signal,
                reason="risk_check_failed",
                message=risk_result.rejected_reason or "위험 검증 실패",
                audit_ids=audit_ids,
                check_id=risk_result.check_id,
            )

        # ── 5. DB에 PENDING 주문 INSERT ─────────────────────────────────
        self._insert_pending_order(client_order_id, signal, risk_result)

        # ── 6. 모드 라우팅 ───────────────────────────────────────────
        mode = self.state.mode
        if mode == ExecutionMode.SHADOW:
            return self._execute_shadow(client_order_id, signal, audit_ids)
        elif mode == ExecutionMode.PAPER:
            return self._execute_paper(client_order_id, signal, audit_ids)
        elif mode == ExecutionMode.LIVE:
            return self._execute_live(client_order_id, signal, audit_ids)
        else:
            return self._reject_order(
                client_order_id, signal,
                reason="unknown_mode", message=f"알 수 없는 모드: {mode}",
                audit_ids=audit_ids,
            )

    # ═════════════════════════════════════════════════════════════════════
    # 모드별 실행
    # ═════════════════════════════════════════════════════════════════════

    def _execute_shadow(self, client_order_id, signal, audit_ids) -> dict:
        """SHADOW: 신호만 기록, 주문 발송 X."""
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE live_orders
                SET status = 'SHADOW_LOGGED', updated_at = CURRENT_TIMESTAMP,
                    notes = 'SHADOW mode — 주문 미발송'
                WHERE client_order_id = :coid
            """), {"coid": client_order_id})

        return {
            "client_order_id": client_order_id,
            "status":          "SHADOW_LOGGED",
            "mode":            ExecutionMode.SHADOW,
            "audit_ids":       audit_ids,
            "message":         "SHADOW mode — 주문 발송하지 않음 (신호만 기록)",
        }

    def _execute_paper(self, client_order_id, signal, audit_ids) -> dict:
        """PAPER: KIS 모의투자 또는 MockKISClient로 가상 거래."""
        try:
            kis_resp = self.kis.place_order(
                ticker=signal["ticker"], side=signal["side"],
                quantity=signal["quantity"],
                order_type=signal.get("order_type", "MARKET"),
                price=signal.get("price"),
            )

            order_audit = self.audit.log_order_submitted(
                client_order_id, signal, kis_resp,
            )
            audit_ids.append(order_audit)

            self._update_order_submitted(client_order_id, kis_resp)

            return {
                "client_order_id": client_order_id,
                "status":          "SUBMITTED",
                "mode":            ExecutionMode.PAPER,
                "kis_order_id":    kis_resp.get("kis_order_no"),
                "kis_response":    kis_resp,
                "audit_ids":       audit_ids,
                "message":         "PAPER mode — KIS 모의투자 발주 완료",
            }
        except Exception as e:
            return self._fail_order(
                client_order_id, signal, str(e), audit_ids,
                mode=ExecutionMode.PAPER,
            )

    def _execute_live(self, client_order_id, signal, audit_ids) -> dict:
        """LIVE: 실거래 ⚠"""
        # 한 번 더 안전 체크
        if self.kill_switch.is_active():
            return self._reject_order(
                client_order_id, signal,
                reason="kill_switch_race",
                message="Kill switch가 검증 후 발동됨 — 발주 차단",
                audit_ids=audit_ids,
            )

        try:
            logger.warning(
                f"⚡ LIVE 주문: {signal['side']} {signal['ticker']} "
                f"{signal['quantity']}주 (CO={client_order_id})"
            )

            kis_resp = self.kis.place_order(
                ticker=signal["ticker"], side=signal["side"],
                quantity=signal["quantity"],
                order_type=signal.get("order_type", "MARKET"),
                price=signal.get("price"),
            )

            order_audit = self.audit.log_order_submitted(
                client_order_id, signal, kis_resp,
            )
            audit_ids.append(order_audit)

            self._update_order_submitted(client_order_id, kis_resp)

            return {
                "client_order_id": client_order_id,
                "status":          "SUBMITTED",
                "mode":            ExecutionMode.LIVE,
                "kis_order_id":    kis_resp.get("kis_order_no"),
                "kis_response":    kis_resp,
                "audit_ids":       audit_ids,
                "message":         "⚡ LIVE 주문 발주 완료",
            }
        except Exception as e:
            return self._fail_order(
                client_order_id, signal, str(e), audit_ids,
                mode=ExecutionMode.LIVE,
            )

    # ═════════════════════════════════════════════════════════════════════
    # 모드 전환
    # ═════════════════════════════════════════════════════════════════════

    def set_mode(self, new_mode: str, actor: str = "user",
                  confirm_token: str | None = None) -> dict:
        """
        실행 모드 변경. LIVE 진입에는 명시적 confirm_token 필요.
        """
        if new_mode not in ExecutionMode.ALL:
            raise ValueError(f"알 수 없는 모드: {new_mode}")

        old_mode = self.state.mode

        # LIVE 진입에는 명시적 토큰 필수
        if new_mode == ExecutionMode.LIVE:
            if confirm_token != "EXPLICIT_LIVE_CONFIRMED":
                raise ValueError(
                    "LIVE 모드 진입은 confirm_token='EXPLICIT_LIVE_CONFIRMED' 필요"
                )

        self.state.mode = new_mode
        self.state.last_mode_change = datetime.now()
        self.state.changed_by = actor

        self.audit.log_mode_change(old_mode, new_mode, actor)

        logger.warning(
            f"실행 모드 전환: {old_mode} → {new_mode} by {actor}"
        )

        return {
            "old_mode": old_mode, "new_mode": new_mode,
            "changed_at": self.state.last_mode_change.isoformat(),
            "changed_by": actor,
        }

    def enable_strategy(self, strategy_id: int):
        self.state.enabled_strategies.add(strategy_id)

    def disable_strategy(self, strategy_id: int):
        self.state.enabled_strategies.discard(strategy_id)

    # ═════════════════════════════════════════════════════════════════════
    # 조회
    # ═════════════════════════════════════════════════════════════════════

    def list_orders(
        self,
        status: str | None = None,
        strategy_id: int | None = None,
        ticker: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM live_orders WHERE 1=1"
        params: dict = {}
        if status:
            sql += " AND status = :st"; params["st"] = status
        if strategy_id:
            sql += " AND strategy_id = :sid"; params["sid"] = strategy_id
        if ticker:
            sql += " AND ticker = :tk"; params["tk"] = ticker
        sql += " ORDER BY created_at DESC LIMIT :lim"
        params["lim"] = limit

        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_order(self, client_order_id: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text(
                "SELECT * FROM live_orders WHERE client_order_id = :coid"
            ), {"coid": client_order_id}).fetchone()
            if not row:
                return None
            order = dict(row._mapping)

            # 체결 정보도 함께
            fills = conn.execute(text(
                "SELECT * FROM live_fills WHERE client_order_id = :coid ORDER BY filled_at"
            ), {"coid": client_order_id}).fetchall()
            order["fills"] = [dict(f._mapping) for f in fills]
        return order

    def cancel_order(self, client_order_id: str, actor: str = "user") -> dict:
        order = self.get_order(client_order_id)
        if not order:
            return {"status": "not_found"}
        if order["status"] not in ("PENDING", "SUBMITTED", "PARTIAL_FILL"):
            return {"status": "not_cancellable", "current": order["status"]}

        try:
            self.kis.cancel_order(
                kis_order_id=order["kis_order_org_no"] or order["kis_order_id"] or "0",
                kis_order_no=order["kis_order_id"] or "0",
                cancel_qty=(order["quantity"] or 0) - (order["filled_quantity"] or 0),
            )
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE live_orders SET status = 'CANCELLED',
                        cancelled_at = CURRENT_TIMESTAMP,
                        reason_code = 'user_cancel'
                    WHERE client_order_id = :coid
                """), {"coid": client_order_id})

            from src.execution.audit_trail import EventCategory, EventType, Severity
            self.audit.log(
                event_type=EventType.ORDER_CANCELLED,
                category=EventCategory.ORDER, severity=Severity.INFO,
                client_order_id=client_order_id, actor=actor,
                ticker=order["ticker"],
                message=f"주문 취소: {order['ticker']} by {actor}",
            )
            return {"status": "cancelled"}
        except Exception as e:
            return {"status": "cancel_failed", "error": str(e)}

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════

    def _fetch_account_state(self) -> dict:
        """KIS 잔고 + 오늘 거래량 통계 조회."""
        try:
            balance = self.kis.get_balance()

            # 오늘 turnover
            with self.engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT COALESCE(SUM(quantity * COALESCE(avg_fill_price, price, 0)), 0) AS turnover
                    FROM live_orders
                    WHERE date(created_at) = date('now')
                      AND status IN ('FILLED', 'PARTIAL_FILL', 'SUBMITTED')
                """)).fetchone()
                daily_turnover = float(row._mapping["turnover"]) if row else 0

            positions = {
                p["ticker"]: {
                    "ticker":      p["ticker"],
                    "quantity":    p["quantity"],
                    "eval_amount": p["eval_amount"],
                    "avg_price":   p["avg_price"],
                }
                for p in balance.get("positions", [])
            }

            return {
                "equity_krw":            balance.get("evaluated_total", 0),
                "cash_krw":              balance.get("cash_krw", 0),
                "positions":             positions,
                "daily_turnover_krw":    daily_turnover,
                "current_drawdown_pct":  0,    # TODO: live monitor에서 계산
                "cumulative_dd_pct":     0,    # TODO: live monitor에서 계산
            }
        except Exception as e:
            logger.error(f"Account state fetch 실패: {e}")
            return {
                "equity_krw": 0, "cash_krw": 0,
                "positions": {}, "daily_turnover_krw": 0,
                "current_drawdown_pct": 0, "cumulative_dd_pct": 0,
            }

    def _insert_pending_order(self, client_order_id, signal, risk_result):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO live_orders (
                        client_order_id, strategy_id, signal_source, execution_mode,
                        ticker, side, order_type, quantity, price,
                        status, risk_check_id, expected_slippage_bps,
                        market_impact_estimate_krw, reason_code
                    ) VALUES (
                        :coid, :sid, :src, :mode,
                        :tk, :sd, :ot, :qty, :pr,
                        'PENDING', :rcid, :sl, :mi, :rc
                    )
                """), {
                    "coid": client_order_id,
                    "sid":  signal.get("strategy_id"),
                    "src":  signal.get("source", "stage11"),
                    "mode": self.state.mode,
                    "tk":   signal["ticker"], "sd": signal["side"],
                    "ot":   signal.get("order_type", "MARKET"),
                    "qty":  signal["quantity"], "pr": signal.get("price"),
                    "rcid": risk_result.check_id,
                    "sl":   risk_result.metadata.get("market_impact_bps"),
                    "mi":   None,
                    "rc":   "approved",
                })
        except Exception as e:
            logger.error(f"PENDING 주문 INSERT 실패: {e}")

    def _update_order_submitted(self, client_order_id, kis_resp):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE live_orders
                    SET status = 'SUBMITTED', submitted_at = CURRENT_TIMESTAMP,
                        kis_order_id = :koid, kis_order_org_no = :kog,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE client_order_id = :coid
                """), {
                    "coid": client_order_id,
                    "koid": kis_resp.get("kis_order_no"),
                    "kog":  kis_resp.get("kis_order_id"),
                })
        except Exception as e:
            logger.error(f"SUBMITTED 상태 업데이트 실패: {e}")

    def _reject_order(self, client_order_id, signal, reason, message, audit_ids,
                       check_id=None):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO live_orders (
                        client_order_id, strategy_id, execution_mode,
                        ticker, side, quantity, price,
                        status, reason_code, error_message, risk_check_id
                    ) VALUES (
                        :coid, :sid, :mode, :tk, :sd, :qty, :pr,
                        'REJECTED', :rc, :em, :rcid
                    )
                """), {
                    "coid": client_order_id,
                    "sid":  signal.get("strategy_id"),
                    "mode": self.state.mode,
                    "tk":   signal["ticker"], "sd": signal["side"],
                    "qty":  signal["quantity"], "pr": signal.get("price"),
                    "rc":   reason, "em": message,
                    "rcid": check_id,
                })
        except Exception:
            pass

        return {
            "client_order_id": client_order_id,
            "status":          "REJECTED",
            "mode":            self.state.mode,
            "reason":          reason,
            "message":         message,
            "audit_ids":       audit_ids,
        }

    def _fail_order(self, client_order_id, signal, error, audit_ids, mode):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE live_orders
                    SET status = 'FAILED', error_message = :em,
                        reason_code = 'api_error',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE client_order_id = :coid
                """), {"coid": client_order_id, "em": error})
        except Exception:
            pass

        from src.execution.audit_trail import EventCategory, EventType, Severity
        fail_audit = self.audit.log(
            event_type=EventType.ORDER_FAILED,
            category=EventCategory.EXECUTION,
            severity=Severity.ERROR,
            client_order_id=client_order_id,
            ticker=signal["ticker"],
            reason_code="api_error",
            context={"error": error},
            message=f"주문 실패: {error}",
        )
        audit_ids.append(fail_audit)

        return {
            "client_order_id": client_order_id,
            "status":          "FAILED",
            "mode":            mode,
            "error":           error,
            "audit_ids":       audit_ids,
        }
