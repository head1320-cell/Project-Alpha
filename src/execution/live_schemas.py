"""
Stage 13 — Live Trading DB Schemas
======================================
5개 테이블:
  ① live_orders        — 발주 기록 (주문 의도)
  ② live_fills         — 체결 기록 (실제 체결)
  ③ live_audit_trail   — 모든 의사결정 감사 로그
  ④ live_daily_pnl     — 일별 P&L 누적
  ⑤ live_kill_events   — Kill switch 발동 기록

설계 원칙:
  · 모든 행에 audit_id 또는 reason_code 기록 (감사 추적)
  · 주문 ID는 client 측 (live_orders.id) + KIS 측 (kis_order_id) 이중 보관
  · 체결은 한 주문에 N개 가능 (partial fills)
  · 일별 P&L은 mark-to-market + realized 분리
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


LIVE_TRADING_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS live_orders (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        client_order_id    VARCHAR(40) UNIQUE NOT NULL,
        kis_order_id       VARCHAR(40),
        kis_order_org_no   VARCHAR(20),

        strategy_id        INTEGER,
        signal_source      VARCHAR(30),
        execution_mode     VARCHAR(10) NOT NULL,

        ticker             VARCHAR(20) NOT NULL,
        side               VARCHAR(10) NOT NULL,
        order_type         VARCHAR(20) DEFAULT 'MARKET',
        quantity           INTEGER NOT NULL,
        price              REAL,

        status             VARCHAR(20) DEFAULT 'PENDING',
        submitted_at       TIMESTAMP,
        first_fill_at      TIMESTAMP,
        completed_at       TIMESTAMP,
        cancelled_at       TIMESTAMP,

        filled_quantity    INTEGER DEFAULT 0,
        avg_fill_price     REAL,
        commission_krw     REAL DEFAULT 0,
        tax_krw            REAL DEFAULT 0,

        risk_check_id      VARCHAR(40),
        expected_slippage_bps REAL,
        actual_slippage_bps REAL,
        market_impact_estimate_krw REAL,

        reason_code        VARCHAR(40),
        notes              TEXT,
        error_message      TEXT,

        created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at         TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lo_status ON live_orders(status)",
    "CREATE INDEX IF NOT EXISTS ix_lo_strategy ON live_orders(strategy_id)",
    "CREATE INDEX IF NOT EXISTS ix_lo_ticker ON live_orders(ticker)",
    "CREATE INDEX IF NOT EXISTS ix_lo_created ON live_orders(created_at)",
    """
    CREATE TABLE IF NOT EXISTS live_fills (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        client_order_id    VARCHAR(40) NOT NULL,
        kis_fill_id        VARCHAR(40),

        fill_quantity      INTEGER NOT NULL,
        fill_price         REAL NOT NULL,
        fill_value_krw     REAL NOT NULL,
        commission_krw     REAL DEFAULT 0,

        filled_at          TIMESTAMP NOT NULL,
        recorded_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (client_order_id) REFERENCES live_orders(client_order_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lf_order ON live_fills(client_order_id)",
    """
    CREATE TABLE IF NOT EXISTS live_audit_trail (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_id           VARCHAR(40) UNIQUE NOT NULL,
        event_type         VARCHAR(40) NOT NULL,
        event_category     VARCHAR(20) NOT NULL,

        strategy_id        INTEGER,
        client_order_id    VARCHAR(40),
        ticker             VARCHAR(20),

        decision           VARCHAR(20),
        risk_tier          VARCHAR(10),
        reason_code        VARCHAR(40),

        context_json       TEXT,
        actor              VARCHAR(50) DEFAULT 'system',
        severity           VARCHAR(10) DEFAULT 'INFO',
        message            TEXT,

        timestamp          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lat_event ON live_audit_trail(event_type)",
    "CREATE INDEX IF NOT EXISTS ix_lat_ts ON live_audit_trail(timestamp)",
    "CREATE INDEX IF NOT EXISTS ix_lat_severity ON live_audit_trail(severity)",
    """
    CREATE TABLE IF NOT EXISTS live_daily_pnl (
        trade_date         DATE PRIMARY KEY,
        execution_mode     VARCHAR(10),

        starting_equity_krw REAL,
        ending_equity_krw   REAL,
        realized_pnl_krw    REAL DEFAULT 0,
        unrealized_pnl_krw  REAL DEFAULT 0,
        daily_return_pct    REAL DEFAULT 0,
        cumulative_return_pct REAL DEFAULT 0,
        max_drawdown_pct    REAL DEFAULT 0,

        n_orders           INTEGER DEFAULT 0,
        n_fills            INTEGER DEFAULT 0,
        n_cancellations    INTEGER DEFAULT 0,
        n_rejections       INTEGER DEFAULT 0,
        gross_turnover_krw REAL DEFAULT 0,
        total_commission_krw REAL DEFAULT 0,
        total_tax_krw      REAL DEFAULT 0,

        regime             VARCHAR(20),
        systemic_risk      REAL,

        kill_switch_active INTEGER DEFAULT 0,
        circuit_breaker_active INTEGER DEFAULT 0,

        updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS live_kill_events (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id           VARCHAR(40) UNIQUE NOT NULL,
        triggered_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        trigger_source     VARCHAR(40) NOT NULL,
        trigger_reason     TEXT NOT NULL,

        equity_at_trigger  REAL,
        dd_at_trigger      REAL,
        regime_at_trigger  VARCHAR(20),

        liquidation_mode   VARCHAR(20),
        n_orders_cancelled INTEGER DEFAULT 0,
        n_positions_closed INTEGER DEFAULT 0,
        krw_recovered      REAL DEFAULT 0,

        resolved_at        TIMESTAMP,
        resolved_by        VARCHAR(50),
        resolution_notes   TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lke_ts ON live_kill_events(triggered_at)",
]


def init_live_trading_schema(engine) -> int:
    """5개 live_* 테이블 생성."""
    count = 0
    with engine.begin() as conn:
        for ddl in LIVE_TRADING_SCHEMA_DDL:
            try:
                conn.execute(text(ddl)); count += 1
            except Exception as e:
                logger.warning(f"DDL failed: {e}")
    return count
