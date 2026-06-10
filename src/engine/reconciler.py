"""
Broker Reconciliation — 로컬 ↔ KIS 동기화
=============================================
실거래의 가장 큰 위험: 로컬 캐시와 실제 브로커 잔고의 불일치.
원인: 부분 체결 누락, KIS 시스템 점검, 네트워크 단절, 다른 클라이언트 거래 등.

본 모듈은 **KIS를 진실의 원천**으로 삼고 로컬 데이터를 강제 보정.

핵심 기능:
  ① sync_with_broker() — 매 주문 전 동기화 + 차이 감지
  ② periodic_sync() — 백그라운드 주기 동기화 (5분)
  ③ drift_history — 차이 발생 이력 영구 기록
  ④ critical drift → kill switch 자동 발동

차이(Drift) 종류:
  · cash_drift_krw     — 예수금 불일치
  · position_drift_qty — 종목별 수량 불일치 (보유 누락 또는 과다)
  · position_drift_avg — 평균 매입가 불일치
  · ghost_position     — KIS에 있지만 로컬에 없는 종목
  · missing_position   — 로컬에 있지만 KIS에 없는 종목

임계값 초과 시 액션:
  · cash drift > 임계값 → CRITICAL audit + 알림
  · position ghost/missing → CRITICAL → kill switch 자동 trigger
  · 누적 drift > 5건 → kill switch
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ReconcilerConfig:
    """동기화 정책 + 임계값."""
    cash_drift_warn_krw:        float = 100_000        # 10만원
    cash_drift_critical_krw:    float = 1_000_000     # 100만원
    cash_drift_pct_critical:    float = 0.01          # 자산 대비 1%

    qty_drift_warn:             int = 1               # 1주 차이도 경고
    qty_drift_critical:         int = 10              # 10주 차이 → critical

    auto_kill_on_ghost:         bool = True
    auto_kill_on_missing:       bool = True
    auto_kill_on_critical_drift_count: int = 3        # 누적 3건이면 kill

    periodic_sync_seconds:      int = 300             # 5분
    pre_order_sync_required:    bool = True
    pre_order_sync_max_age_sec: float = 30.0


@dataclass
class PositionDiff:
    """단일 종목 차이."""
    ticker:         str
    kis_quantity:   int
    local_quantity: int
    quantity_diff:  int
    kis_avg_price:  float
    local_avg_price: float
    severity:       str       # OK | WARN | CRITICAL


@dataclass
class ReconciliationResult:
    """단일 동기화 결과."""
    sync_id:            str
    timestamp:          datetime
    success:            bool

    kis_cash_krw:       float = 0
    local_cash_krw:     float = 0
    cash_drift_krw:     float = 0
    cash_drift_pct:     float = 0
    cash_severity:      str = "OK"

    kis_equity_krw:     float = 0
    local_equity_krw:   float = 0

    position_diffs:     list = field(default_factory=list)
    ghost_positions:    list = field(default_factory=list)
    missing_positions:  list = field(default_factory=list)

    actions_taken:      list = field(default_factory=list)
    severity:           str = "OK"
    error:              str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# BrokerReconciler
# ═══════════════════════════════════════════════════════════════════════════════

class BrokerReconciler:
    """
    Broker (KIS) ↔ 로컬 DB 동기화 관리자.

    Usage:
        reconciler = BrokerReconciler(
            engine=engine, kis_client=kis_client,
            audit_trail=audit, notifier=notifier,
            kill_switch=kill_switch,
            config=ReconcilerConfig(),
        )

        # 주문 전 강제 동기화
        result = reconciler.sync_with_broker(reason="pre_order")
        if result.severity == "CRITICAL":
            return  # 발주 차단

        # 백그라운드 주기 sync 시작
        reconciler.start_periodic_sync()

        # 마지막 sync 상태 조회
        status = reconciler.get_status()
    """

    def __init__(
        self,
        engine,
        kis_client,
        audit_trail=None,
        notifier=None,
        kill_switch=None,
        config: ReconcilerConfig | None = None,
    ):
        self.engine = engine
        self.kis = kis_client
        self.audit = audit_trail
        self.notifier = notifier
        self.kill_switch = kill_switch
        self.config = config or ReconcilerConfig()

        self._last_sync: ReconciliationResult | None = None
        self._critical_drift_count = 0

        # 백그라운드 sync 관리
        self._periodic_thread = None
        self._stop_event = None

        # 초기화: 테이블 생성
        self._ensure_schema()

    # ─────────────────────────────────────────────────────────────────────
    # 스키마
    # ─────────────────────────────────────────────────────────────────────

    def _ensure_schema(self):
        ddls = [
            """
            CREATE TABLE IF NOT EXISTS reconciliation_history (
                sync_id        VARCHAR(40) PRIMARY KEY,
                timestamp      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason         VARCHAR(40),
                success        INTEGER,
                severity       VARCHAR(10),

                kis_cash_krw       REAL,
                local_cash_krw     REAL,
                cash_drift_krw     REAL,
                cash_drift_pct     REAL,

                kis_equity_krw     REAL,
                local_equity_krw   REAL,

                n_position_diffs   INTEGER DEFAULT 0,
                n_ghost_positions  INTEGER DEFAULT 0,
                n_missing_positions INTEGER DEFAULT 0,

                actions_taken_json TEXT,
                diffs_json         TEXT,
                error              TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_recon_ts ON reconciliation_history(timestamp)",
            "CREATE INDEX IF NOT EXISTS ix_recon_severity ON reconciliation_history(severity)",
            """
            CREATE TABLE IF NOT EXISTS local_portfolio_state (
                ticker         VARCHAR(20) PRIMARY KEY,
                quantity       INTEGER NOT NULL DEFAULT 0,
                avg_price      REAL DEFAULT 0,
                last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source         VARCHAR(20) DEFAULT 'kis'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS local_account_state (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                cash_krw       REAL DEFAULT 0,
                equity_krw     REAL DEFAULT 0,
                stock_value    REAL DEFAULT 0,
                last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ]
        try:
            with self.engine.begin() as conn:
                for ddl in ddls:
                    try:
                        conn.execute(text(ddl))
                    except Exception as e:
                        logger.debug(f"DDL skip: {e}")
        except Exception as e:
            logger.error(f"Reconciler 스키마 초기화 실패: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # 핵심: sync_with_broker
    # ─────────────────────────────────────────────────────────────────────

    def sync_with_broker(self, reason: str = "manual") -> ReconciliationResult:
        """
        KIS 잔고 조회 → 로컬 비교 → 차이 분석 → 로컬 강제 보정 + audit.

        이 메서드가 가장 중요. 모든 외부 호출은 try/except 안.
        """
        sync_id = f"RECON-{uuid.uuid4().hex[:12]}"
        result = ReconciliationResult(
            sync_id=sync_id,
            timestamp=datetime.now(),
            success=False,
        )

        # ── 1. KIS 잔고 조회 (방어적) ────────────────────────────────
        kis_balance = None
        try:
            kis_balance = self.kis.get_balance()
        except Exception as e:
            result.error = f"KIS 잔고 조회 실패: {e}"
            result.severity = "CRITICAL"
            logger.error(result.error)
            self._notify_critical(
                "Reconciliation 실패",
                f"KIS get_balance() 호출 실패: {e}",
            )
            self._persist_result(result, reason)
            return result

        if not kis_balance:
            result.error = "KIS 응답 비어있음"
            result.severity = "CRITICAL"
            self._persist_result(result, reason)
            return result

        # ── 2. 로컬 상태 조회 (방어적) ──────────────────────────────
        try:
            local_cash, local_positions = self._fetch_local_state()
        except Exception as e:
            result.error = f"로컬 상태 조회 실패: {e}"
            result.severity = "WARN"
            local_cash = 0
            local_positions = {}
            logger.warning(result.error)

        # ── 3. Cash drift 분석 ──────────────────────────────────────
        result.kis_cash_krw = float(kis_balance.get("cash_krw") or 0)
        result.local_cash_krw = local_cash
        result.cash_drift_krw = result.kis_cash_krw - local_cash
        result.kis_equity_krw = float(kis_balance.get("evaluated_total") or 0)
        result.local_equity_krw = float(local_cash) + sum(
            p.get("eval_amount", 0) for p in local_positions.values()
        )

        equity = max(result.kis_equity_krw, 1)
        result.cash_drift_pct = abs(result.cash_drift_krw) / equity

        if abs(result.cash_drift_krw) >= self.config.cash_drift_critical_krw \
            or result.cash_drift_pct >= self.config.cash_drift_pct_critical:
            result.cash_severity = "CRITICAL"
        elif abs(result.cash_drift_krw) >= self.config.cash_drift_warn_krw:
            result.cash_severity = "WARN"
        else:
            result.cash_severity = "OK"

        # ── 4. Position diffs ────────────────────────────────────────
        kis_positions = {
            p["ticker"]: p
            for p in kis_balance.get("positions", [])
            if p.get("quantity", 0) != 0
        }
        all_tickers = set(kis_positions.keys()) | set(local_positions.keys())

        for ticker in sorted(all_tickers):
            kp = kis_positions.get(ticker)
            lp = local_positions.get(ticker)

            kis_qty = int(kp["quantity"]) if kp else 0
            kis_avg = float(kp["avg_price"]) if kp else 0
            loc_qty = int(lp["quantity"]) if lp else 0
            loc_avg = float(lp.get("avg_price", 0)) if lp else 0

            qty_diff = kis_qty - loc_qty

            # 차이 분류
            if kp is None and lp is not None:
                # KIS에 없는데 로컬에 있음 (Missing)
                result.missing_positions.append(ticker)
                severity = "CRITICAL"
            elif kp is not None and lp is None:
                # KIS에 있는데 로컬에 없음 (Ghost)
                result.ghost_positions.append(ticker)
                severity = "CRITICAL"
            elif abs(qty_diff) >= self.config.qty_drift_critical:
                severity = "CRITICAL"
            elif abs(qty_diff) >= self.config.qty_drift_warn:
                severity = "WARN"
            else:
                severity = "OK"

            if severity != "OK":
                result.position_diffs.append(PositionDiff(
                    ticker=ticker,
                    kis_quantity=kis_qty,
                    local_quantity=loc_qty,
                    quantity_diff=qty_diff,
                    kis_avg_price=kis_avg,
                    local_avg_price=loc_avg,
                    severity=severity,
                ))

        # ── 5. Severity 종합 ────────────────────────────────────────
        any_critical = (
            result.cash_severity == "CRITICAL"
            or any(d.severity == "CRITICAL" for d in result.position_diffs)
            or len(result.ghost_positions) > 0
            or len(result.missing_positions) > 0
        )
        any_warn = (
            result.cash_severity == "WARN"
            or any(d.severity == "WARN" for d in result.position_diffs)
        )
        result.severity = "CRITICAL" if any_critical else ("WARN" if any_warn else "OK")
        result.success = True

        # ── 6. 로컬 상태 강제 업데이트 (KIS = 진실의 원천) ────────────
        try:
            self._force_update_local(kis_balance)
            result.actions_taken.append("local_state_overwritten_from_kis")
        except Exception as e:
            logger.error(f"로컬 강제 업데이트 실패: {e}")
            result.actions_taken.append(f"local_update_failed: {e}")

        # ── 7. CRITICAL 발생 시 액션 ─────────────────────────────────
        if any_critical:
            self._critical_drift_count += 1
            result.actions_taken.append(f"critical_drift_count={self._critical_drift_count}")

            # Audit + Notification
            msg = self._format_drift_message(result)
            self._audit_critical(sync_id, result)
            self._notify_critical("Broker Drift Detected", msg)

            # Ghost / Missing 시 자동 kill switch
            if result.ghost_positions and self.config.auto_kill_on_ghost:
                self._trigger_kill(
                    source="auto_reconciler_ghost",
                    reason=f"Ghost positions detected: {result.ghost_positions}",
                    equity=result.kis_equity_krw,
                )
                result.actions_taken.append("kill_switch_triggered_ghost")

            elif result.missing_positions and self.config.auto_kill_on_missing:
                self._trigger_kill(
                    source="auto_reconciler_missing",
                    reason=f"Missing positions detected: {result.missing_positions}",
                    equity=result.kis_equity_krw,
                )
                result.actions_taken.append("kill_switch_triggered_missing")

            # 누적 critical drift 임계값 도달 시 kill switch
            elif self._critical_drift_count >= self.config.auto_kill_on_critical_drift_count:
                self._trigger_kill(
                    source="auto_reconciler_count",
                    reason=f"Critical drift 누적 {self._critical_drift_count}회 발생",
                    equity=result.kis_equity_krw,
                )
                result.actions_taken.append("kill_switch_triggered_count")
        else:
            # 정상 동기화 — 카운터 리셋
            if self._critical_drift_count > 0:
                self._critical_drift_count = max(0, self._critical_drift_count - 1)

            if any_warn:
                self._notify_warn(
                    "Broker Drift Warning",
                    self._format_drift_message(result),
                )

        # ── 8. DB 영구 기록 ─────────────────────────────────────────
        self._persist_result(result, reason)
        self._last_sync = result

        return result

    # ─────────────────────────────────────────────────────────────────────
    # 사전 검증 헬퍼 — 주문 발주 직전 호출
    # ─────────────────────────────────────────────────────────────────────

    def is_sync_fresh(self) -> bool:
        """마지막 sync가 임계 시간 내인지."""
        if not self._last_sync:
            return False
        age = (datetime.now() - self._last_sync.timestamp).total_seconds()
        return age <= self.config.pre_order_sync_max_age_sec

    def ensure_synced(self, reason: str = "pre_order") -> ReconciliationResult:
        """fresh sync 보장 — 오래되었으면 강제 sync."""
        if self.is_sync_fresh() and self._last_sync:
            return self._last_sync
        return self.sync_with_broker(reason=reason)

    # ─────────────────────────────────────────────────────────────────────
    # 주기적 sync (백그라운드)
    # ─────────────────────────────────────────────────────────────────────

    def start_periodic_sync(self):
        """백그라운드 주기 동기화 시작."""
        import threading
        if self._periodic_thread:
            return
        self._stop_event = threading.Event()
        self._periodic_thread = threading.Thread(
            target=self._periodic_loop, name="ReconcilerPeriodic", daemon=True,
        )
        self._periodic_thread.start()
        logger.info(f"Periodic reconciliation 시작 ({self.config.periodic_sync_seconds}s)")

    def stop_periodic_sync(self):
        if self._stop_event:
            self._stop_event.set()
        self._periodic_thread = None

    def _periodic_loop(self):
        while not (self._stop_event and self._stop_event.is_set()):
            try:
                self.sync_with_broker(reason="periodic")
            except Exception as e:
                logger.error(f"Periodic sync 예외: {e}", exc_info=True)
            # sleep with periodic stop checks
            for _ in range(self.config.periodic_sync_seconds):
                if self._stop_event and self._stop_event.is_set():
                    break
                import time as _t
                _t.sleep(1)

    # ─────────────────────────────────────────────────────────────────────
    # 조회
    # ─────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """현재 동기화 상태."""
        last = self._last_sync
        return {
            "last_sync_id":      last.sync_id if last else None,
            "last_sync_at":      last.timestamp.isoformat() if last else None,
            "last_severity":     last.severity if last else None,
            "is_fresh":          self.is_sync_fresh(),
            "critical_drift_count": self._critical_drift_count,
            "periodic_running":  self._periodic_thread is not None
                                  and self._periodic_thread.is_alive(),
        }

    def recent_history(self, limit: int = 50) -> list[dict]:
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT sync_id, timestamp, reason, severity, success,
                           kis_cash_krw, local_cash_krw, cash_drift_krw,
                           cash_drift_pct, n_position_diffs,
                           n_ghost_positions, n_missing_positions
                    FROM reconciliation_history
                    ORDER BY timestamp DESC LIMIT :lim
                """), {"lim": limit}).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception as e:
            logger.error(f"History 조회 실패: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # 내부: 로컬 상태 조회 / 업데이트
    # ─────────────────────────────────────────────────────────────────────

    def _fetch_local_state(self) -> tuple[float, dict]:
        """로컬 DB의 cash + positions 조회."""
        cash = 0.0
        positions = {}
        try:
            with self.engine.connect() as conn:
                # Cash
                row = conn.execute(text(
                    "SELECT cash_krw FROM local_account_state WHERE id = 1"
                )).fetchone()
                if row:
                    cash = float(row._mapping["cash_krw"] or 0)

                # Positions
                rows = conn.execute(text(
                    "SELECT ticker, quantity, avg_price FROM local_portfolio_state "
                    "WHERE quantity != 0"
                )).fetchall()
                for r in rows:
                    m = r._mapping
                    positions[m["ticker"]] = {
                        "quantity":   int(m["quantity"] or 0),
                        "avg_price":  float(m["avg_price"] or 0),
                        "eval_amount": int(m["quantity"] or 0) * float(m["avg_price"] or 0),
                    }
        except Exception as e:
            logger.error(f"Local state 조회 실패: {e}")
        return cash, positions

    def _force_update_local(self, kis_balance: dict):
        """KIS 결과로 로컬 강제 덮어쓰기."""
        with self.engine.begin() as conn:
            # Cash
            conn.execute(text("""
                INSERT OR REPLACE INTO local_account_state
                (id, cash_krw, equity_krw, stock_value, last_synced_at)
                VALUES (1, :c, :e, :s, CURRENT_TIMESTAMP)
            """), {
                "c": kis_balance.get("cash_krw", 0),
                "e": kis_balance.get("evaluated_total", 0),
                "s": kis_balance.get("stock_value", 0),
            })

            # 모든 기존 positions 삭제 후 KIS 데이터 재삽입
            conn.execute(text("DELETE FROM local_portfolio_state"))
            for pos in kis_balance.get("positions", []):
                if pos.get("quantity", 0) == 0:
                    continue
                conn.execute(text("""
                    INSERT INTO local_portfolio_state
                    (ticker, quantity, avg_price, last_synced_at, source)
                    VALUES (:t, :q, :p, CURRENT_TIMESTAMP, 'kis_sync')
                """), {
                    "t": pos["ticker"],
                    "q": pos["quantity"],
                    "p": pos.get("avg_price", 0),
                })

    # ─────────────────────────────────────────────────────────────────────
    # 내부: persist + audit + notify
    # ─────────────────────────────────────────────────────────────────────

    def _persist_result(self, result: ReconciliationResult, reason: str):
        import json
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO reconciliation_history (
                        sync_id, reason, success, severity,
                        kis_cash_krw, local_cash_krw, cash_drift_krw, cash_drift_pct,
                        kis_equity_krw, local_equity_krw,
                        n_position_diffs, n_ghost_positions, n_missing_positions,
                        actions_taken_json, diffs_json, error
                    ) VALUES (
                        :sid, :rs, :sc, :sv,
                        :kc, :lc, :cd, :cp,
                        :ke, :le,
                        :npd, :ngh, :nms,
                        :at, :dj, :er
                    )
                """), {
                    "sid": result.sync_id, "rs": reason,
                    "sc": int(result.success), "sv": result.severity,
                    "kc": result.kis_cash_krw, "lc": result.local_cash_krw,
                    "cd": result.cash_drift_krw, "cp": result.cash_drift_pct,
                    "ke": result.kis_equity_krw, "le": result.local_equity_krw,
                    "npd": len(result.position_diffs),
                    "ngh": len(result.ghost_positions),
                    "nms": len(result.missing_positions),
                    "at": json.dumps(result.actions_taken),
                    "dj": json.dumps([d.__dict__ for d in result.position_diffs],
                                       default=str),
                    "er": result.error,
                })
        except Exception as e:
            logger.error(f"Reconciliation persist 실패: {e}")

    def _audit_critical(self, sync_id: str, result: ReconciliationResult):
        if not self.audit:
            return
        try:
            from src.execution.audit_trail import EventCategory, Severity
            self.audit.log(
                event_type="BROKER_DRIFT_CRITICAL",
                category=EventCategory.SYSTEM,
                severity=Severity.CRITICAL,
                reason_code="broker_drift",
                context={
                    "sync_id":           sync_id,
                    "cash_drift_krw":    result.cash_drift_krw,
                    "ghost_positions":   result.ghost_positions,
                    "missing_positions": result.missing_positions,
                    "n_position_diffs":  len(result.position_diffs),
                },
                message=self._format_drift_message(result),
            )
        except Exception as e:
            logger.error(f"Audit 기록 실패: {e}")

    @staticmethod
    def _format_drift_message(result: ReconciliationResult) -> str:
        parts = []
        if result.cash_severity != "OK":
            parts.append(
                f"Cash drift: {result.cash_drift_krw:+,.0f}원 "
                f"({result.cash_drift_pct:.2%})"
            )
        if result.ghost_positions:
            parts.append(f"Ghost: {', '.join(result.ghost_positions[:3])}")
        if result.missing_positions:
            parts.append(f"Missing: {', '.join(result.missing_positions[:3])}")
        if result.position_diffs:
            critical = [d for d in result.position_diffs if d.severity == "CRITICAL"]
            if critical:
                ticker_diffs = ", ".join(
                    f"{d.ticker}({d.quantity_diff:+d}주)" for d in critical[:3]
                )
                parts.append(f"Quantity drift: {ticker_diffs}")
        return " | ".join(parts) if parts else "정상 동기화"

    def _trigger_kill(self, source: str, reason: str, equity: float):
        if not self.kill_switch:
            return
        try:
            self.kill_switch.trigger(
                source=source, reason=reason,
                equity=equity, kis_client=self.kis,
                liquidation_mode="hold",
            )
        except Exception as e:
            logger.error(f"Kill switch trigger 실패: {e}")

    def _notify_critical(self, title: str, message: str):
        if self.notifier:
            try:
                self.notifier.critical(title, message)
            except Exception as e:
                logger.error(f"Notification 실패: {e}")

    def _notify_warn(self, title: str, message: str):
        if self.notifier:
            try:
                self.notifier.warn(title, message)
            except Exception as e:
                logger.error(f"Notification 실패: {e}")
