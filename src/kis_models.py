"""
ORM Models — KIS-Sourced Market Data
======================================
Core tables populated by the KIS data sync worker.

Tables:
  - stocks:       metadata (ticker, name, market, sector)
  - daily_prices: OHLCV + trading value, composite PK on (ticker, trade_date)
"""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.sql import func

from src.database_async import AsyncBase


class Stock(AsyncBase):
    """
    Stock metadata table.
    Populated from the KIS ticker master file (~2,500 KOSPI+KOSDAQ tickers).
    """
    __tablename__ = "stocks"

    ticker = Column(String(12), primary_key=True)  # e.g. "005930"
    name = Column(String(128), nullable=False)
    market = Column(String(16))       # KOSPI / KOSDAQ / KONEX
    sector = Column(String(64))
    industry = Column(String(128))

    # Reference fields
    listed_shares = Column(BigInteger)
    currency = Column(String(8), default="KRW")
    is_active = Column(Integer, default=1)  # 0=delisted

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_stocks_market", "market"),
        Index("ix_stocks_sector", "sector"),
    )

    def __repr__(self):
        return f"<Stock {self.ticker}:{self.name}>"


class DailyPrice(AsyncBase):
    """
    Daily OHLCV time-series.
    Composite PK on (ticker, trade_date) prevents duplicates.
    Indexed for time-range queries.
    """
    __tablename__ = "daily_prices"

    ticker = Column(String(12), nullable=False)
    trade_date = Column(Date, nullable=False)

    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger)
    trading_value = Column(BigInteger)  # 거래대금 (volume * price)

    # Adjusted close for corporate actions
    adj_close = Column(Float)

    # Cached computed indicators (updated by nightly job)
    rsi_14 = Column(Float)
    sma_20 = Column(Float)
    sma_60 = Column(Float)
    return_1d = Column(Float)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("ticker", "trade_date", name="pk_daily_prices"),
        Index("ix_daily_ticker_date", "ticker", "trade_date"),
        Index("ix_daily_date", "trade_date"),
    )

    def __repr__(self):
        return f"<DailyPrice {self.ticker} {self.trade_date} C={self.close}>"
