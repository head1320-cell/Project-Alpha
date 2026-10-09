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
        updated_at         TIMESTAMP,

        -- 사용자 증권 계좌(BV6). NULL = 운영자 `.env` 계좌.
        account_id         VARCHAR(32)
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

        timestamp          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        account_id         VARCHAR(32)
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
        -- ★이 수치가 시장에서 왔나 지어낸 것인가★ (AI)
        -- `execution_mode` 와 **다른 축**이다: SHADOW 로 돌면서 실제 잔고를 읽을
        -- 수도, PAPER 로 돌면서 mock 을 읽을 수도 있다. 어휘는
        -- `src/domain/equity_observation.py` 가 갖는다.
        equity_source      VARCHAR(16),
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

        actions_json       TEXT,

        resolved_at        TIMESTAMP,
        resolved_by        VARCHAR(50),
        resolution_notes   TEXT,
        account_id         VARCHAR(32)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lke_ts ON live_kill_events(triggered_at)",
]


#: 브로커 체결 재생을 막는 유일 인덱스. ★테이블 생성과 분리한다★ —
#: 기존 DB 에 이미 중복 행이 있으면 생성이 **실패해야** 하고, 그 실패는
#: 조용히 넘어가면 안 된다(`schema_add_columns` 가 세운 "검증하는 마이그레이션" 규율).
FILL_DEDUP_INDEX = "ux_live_fills_kis_id"
_FILL_DEDUP_DDL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {FILL_DEDUP_INDEX} "
    "ON live_fills(kis_fill_id)"
)


def ensure_fill_dedup_index(engine) -> tuple[bool, str | None]:
    """`(붙었는가, 사유)`. ★실패를 성공처럼 돌려주지 않는다.★

    `kis_fill_id` 가 `NULL` 인 행은 UNIQUE 가 막지 않는다(SQLite·PostgreSQL 공통).
    수동 체결 입력을 막지 않기 위해 의도한 것이고, 그만큼 ★수동 경로의 중복은
    이 가드가 잡지 못한다★ — 지어낸 키로 채우지 않는다.
    """
    from sqlalchemy import text as _text
    try:
        with engine.begin() as conn:
            conn.execute(_text(_FILL_DEDUP_DDL))
        return True, None
    except Exception as e:                               # noqa: BLE001
        reason = (f"{FILL_DEDUP_INDEX} 생성 실패 — 기존 `live_fills` 에 같은 "
                  f"`kis_fill_id` 가 둘 이상일 수 있습니다: {e}")
        logger.error(reason)
        return False, reason


#: ★이미 만들어진 DB 에 붙이는 칸★ — `CREATE TABLE IF NOT EXISTS` 는 기존 표를
#: 고치지 않으므로, 운영 DB 는 이 경로로만 컬럼을 얻는다(W1 이 세운 관용구).
_EQUITY_SOURCE_COLS = [("equity_source", "VARCHAR(16)")]

#: ★발동이 **무엇을 했는가**★ — 같은 이유로 기존 DB 에는 이 경로로만 붙는다(AP4).
_KILL_ACTION_COLS = [("actions_json", "TEXT")]

#: ★어느 계좌의 기록인가★(BV6) — NULL 은 운영자 `.env` 계좌. 기존 DB 에는 이 경로로만 붙는다.
_ACCOUNT_COLS = [("account_id", "VARCHAR(32)")]
ACCOUNT_TABLES = ("live_orders", "live_audit_trail", "live_kill_events")


def account_scope(account_id: str | None) -> tuple[str, dict]:
    """`(SQL 조건, 인자)` — 그 계좌의 행만. ★운영자(`None`)는 계좌 행을 보지 않는다★(BV6)."""
    if account_id is None:
        return "account_id IS NULL", {}
    return "account_id = :acct", {"acct": account_id}


def init_live_trading_schema(engine) -> int:
    """5개 live_* 테이블 생성 + ★기존 표에 빠진 칸 덧붙이기★."""
    count = 0
    with engine.begin() as conn:
        for ddl in LIVE_TRADING_SCHEMA_DDL:
            try:
                conn.execute(text(ddl)); count += 1
            except Exception as e:
                logger.warning(f"DDL failed: {e}")
    # ★못 붙어도 죽지 않는다★ — `add_columns` 가 **실제로 쓸 수 있는지** 확인해
    # bool 을 돌려주고, 못 쓰면 드로다운이 `no_equity_source_column` 으로 남는다
    # (안전한 쪽). 여기서 예외를 올리면 스키마 초기화 전체가 무너진다.
    try:
        from src.data.schema_add_columns import add_columns
        add_columns(engine, "live_daily_pnl", _EQUITY_SOURCE_COLS,
                    label="에쿼티 출처(AI)")
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"equity_source 컬럼 추가 실패(그 칸 없이 동작): {e}")
    try:
        from src.data.schema_add_columns import add_columns
        add_columns(engine, "live_kill_events", _KILL_ACTION_COLS,
                    label="킬스위치 조치 기록(AP)")
    except Exception as e:                                   # noqa: BLE001
        # ★못 붙어도 발동은 성립한다★ — 조치 기록만 남지 않는다.
        logger.warning(f"actions_json 컬럼 추가 실패(그 칸 없이 동작): {e}")
    from src.data.schema_add_columns import add_columns
    for table in ACCOUNT_TABLES:
        # ★실패를 삼키지 않는다★ — 이 칸이 없으면 계좌 기록과 운영자 기록이 섞인다(BV6).
        if not add_columns(engine, table, _ACCOUNT_COLS, label="계좌 구분(BV6)"):
            raise RuntimeError(f"{table}.account_id 를 붙이지 못했습니다 — 계좌 기록과 운영자 기록을 가를 수 없어 "
                               "실거래 표를 쓰지 않습니다.")
    return count
