"""Stage 11 DB Schema — multibacktest_runs / daily / strategy_daily."""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


MULTIBACKTEST_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS multibacktest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_name VARCHAR(100),
        strategy_ids TEXT NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        initial_capital REAL NOT NULL,
        allocation_method VARCHAR(30) NOT NULL,
        rebalance_policy VARCHAR(30) DEFAULT 'monthly',
        netting_enabled INTEGER DEFAULT 1,
        macro_overlay_enabled INTEGER DEFAULT 1,
        commission_rate REAL DEFAULT 0.00015,
        slippage_rate REAL DEFAULT 0.0005,
        total_return_pct REAL, annualized_return_pct REAL,
        sharpe_ratio REAL, max_drawdown_pct REAL, calmar_ratio REAL,
        netting_total_savings REAL, total_trades INTEGER,
        total_turnover_pct REAL, n_rebalances INTEGER, n_trading_days INTEGER,
        config_json TEXT, status VARCHAR(20) DEFAULT 'pending',
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP, duration_seconds REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mbr_created ON multibacktest_runs(created_at)",
    """
    CREATE TABLE IF NOT EXISTS multibacktest_daily (
        run_id INTEGER NOT NULL, trade_date DATE NOT NULL,
        portfolio_equity REAL, portfolio_return REAL,
        cumulative_return REAL, drawdown_pct REAL,
        regime VARCHAR(20), systemic_risk REAL,
        growth_signal REAL, inflation_signal REAL,
        allocation_effect REAL DEFAULT 0, selection_effect REAL DEFAULT 0,
        macro_effect REAL DEFAULT 0, netting_effect REAL DEFAULT 0, cost_effect REAL DEFAULT 0,
        num_strategies_active INTEGER, num_trades INTEGER DEFAULT 0,
        turnover_pct REAL DEFAULT 0, netting_savings REAL DEFAULT 0,
        rebalanced INTEGER DEFAULT 0,
        PRIMARY KEY (run_id, trade_date),
        FOREIGN KEY (run_id) REFERENCES multibacktest_runs(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mbd_run ON multibacktest_daily(run_id)",
    """
    CREATE TABLE IF NOT EXISTS multibacktest_strategy_daily (
        run_id INTEGER NOT NULL, trade_date DATE NOT NULL, strategy_id INTEGER NOT NULL,
        weight REAL, base_weight REAL, macro_adjustment REAL DEFAULT 0,
        strategy_return REAL, contribution REAL,
        PRIMARY KEY (run_id, trade_date, strategy_id),
        FOREIGN KEY (run_id) REFERENCES multibacktest_runs(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mbsd_run ON multibacktest_strategy_daily(run_id)",
]


def init_multibacktest_schema(engine) -> int:
    count = 0
    with engine.begin() as conn:
        for ddl in MULTIBACKTEST_SCHEMA_DDL:
            try:
                conn.execute(text(ddl)); count += 1
            except Exception as e:
                logger.warning(f"DDL failed: {e}")
    return count
