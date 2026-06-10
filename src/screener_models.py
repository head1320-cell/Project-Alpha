"""
Market Snapshot Tables
========================
Cache tables for the Market Screener API.

Designed for DB-side filtering (no Pandas in-memory) to respect
e2-micro's 1GB memory limit. All queries run in PostgreSQL.

Tables:
  - market_snapshot_equity: stocks with fundamental + technical factors
  - market_snapshot_ficc:   bonds, FX, options with relevant Greeks/yields
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Market Snapshot Tables
# ═══════════════════════════════════════════════════════════════════════════════

class MarketSnapshotEquity(Base):
    """
    Equity snapshot for screening. Truncated & reloaded every 5 minutes
    by the async background worker.

    Columns are carefully chosen — every factor here is an allowed
    target of the SQL builder's whitelist.
    """
    __tablename__ = "market_snapshot_equity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(32), nullable=False, index=True)
    name = Column(String(128))
    sector = Column(String(64))
    currency = Column(String(8))

    # Price / volume
    price = Column(Float)
    volume = Column(Float)
    market_cap = Column(Float)  # in billions USD

    # Value factors
    per = Column(Float)
    pbr = Column(Float)
    dividend_yield = Column(Float)

    # Quality factors
    roe = Column(Float)
    roa = Column(Float)
    debt_equity = Column(Float)

    # Momentum / technical
    rsi = Column(Float)
    macd = Column(Float)
    return_12m = Column(Float)
    return_3m = Column(Float)

    # Risk
    beta = Column(Float)
    volatility_annual = Column(Float)

    updated_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_equity_per_roe", "per", "roe"),
        Index("ix_equity_mcap", "market_cap"),
    )


class MarketSnapshotFICC(Base):
    """
    FICC snapshot: bonds, FX, options.
    One table with asset_type discriminator keeps the query surface simple.
    """
    __tablename__ = "market_snapshot_ficc"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(64), nullable=False, index=True)
    asset_type = Column(String(16), nullable=False, index=True)  # bond / fx / option
    currency = Column(String(8))

    # Common
    price = Column(Float)

    # Bond fields
    ytm = Column(Float)
    duration = Column(Float)
    convexity = Column(Float)
    credit_spread_bps = Column(Float)
    maturity_years = Column(Float)
    rating_score = Column(Integer)  # 22=AAA, 14=BBB, 4=CCC

    # Option fields (Greeks + vol)
    delta = Column(Float)
    gamma = Column(Float)
    theta = Column(Float)
    vega = Column(Float)
    implied_volatility = Column(Float)
    iv_rank = Column(Float)
    dte_days = Column(Integer)
    moneyness = Column(Float)
    open_interest = Column(Integer)

    # FX fields
    daily_vol = Column(Float)
    carry_annual = Column(Float)
    momentum_12m = Column(Float)
    ppp_deviation = Column(Float)
    real_rate_diff = Column(Float)

    updated_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_ficc_type_ticker", "asset_type", "ticker"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Table Bootstrap
# ═══════════════════════════════════════════════════════════════════════════════

def init_screener_tables(engine):
    """Create the snapshot tables if missing. Safe to call multiple times."""
    Base.metadata.create_all(engine)


def drop_screener_tables(engine):
    """Drop snapshot tables — used for 'replace' style refresh."""
    Base.metadata.drop_all(engine)


# ═══════════════════════════════════════════════════════════════════════════════
# Factor Whitelists (exported for SQL builder)
# ═══════════════════════════════════════════════════════════════════════════════

EQUITY_FACTORS = {
    "price", "volume", "market_cap",
    "per", "pbr", "dividend_yield",
    "roe", "roa", "debt_equity",
    "rsi", "macd", "return_12m", "return_3m",
    "beta", "volatility_annual",
}

FICC_FACTORS = {
    "price", "ytm", "duration", "convexity", "credit_spread_bps",
    "maturity_years", "rating_score",
    "delta", "gamma", "theta", "vega", "implied_volatility",
    "iv_rank", "dte_days", "moneyness", "open_interest",
    "daily_vol", "carry_annual", "momentum_12m",
    "ppp_deviation", "real_rate_diff",
}

ALLOWED_FACTORS = {
    "equity": EQUITY_FACTORS,
    "ficc": FICC_FACTORS,
}

TABLE_NAMES = {
    "equity": "market_snapshot_equity",
    "ficc": "market_snapshot_ficc",
}
