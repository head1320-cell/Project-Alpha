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

    # ★`updated_at` 을 뺐다★ 읽는 곳이 없고, 이 테이블의 **지배적 writer** 는
    # ORM 이 아니라 `krx_ingest.bulk_upsert`(raw SQL)다. 그쪽은 이 컬럼을
    # 갱신하지 않으므로, 두면 "갱신되지 않는 `updated_at`" 이라는 **그럴듯한
    # 거짓 필드**가 된다. 그리고 raw DDL 에는 애초에 없어서, 어느 쪽이 테이블을
    # 먼저 만들었느냐에 따라 컬럼이 있다 없다 했다(실측).
    # ★기존 DB 의 컬럼을 DROP 하지는 않는다★ — 비어 있을 뿐 해가 없다.

    __table_args__ = (
        PrimaryKeyConstraint("ticker", "trade_date", name="pk_daily_prices"),
        # ★`ix_daily_ticker_date` 를 뺐다★ PK 와 컬럼·순서가 완전히 같아 조회에
        # 아무것도 더해 주지 않고 **쓰기 비용만** 냈다(최대 테이블이다).
        # ★기존 DB 의 것을 DROP 하지는 않는다★ — 저장소에 인덱스 삭제
        # 마이그레이션 선례가 없다. 새 DB 에 더 만들지 않을 뿐이다.
        #
        # `ix_daily_date` 는 `krx_ingest._ENSURE_INDEXES` 도 만든다 — 생성
        # 순서와 무관하게 같은 스키마가 되도록 **양쪽에** 둔다.
        Index("ix_daily_date", "trade_date"),
    )

    def __repr__(self):
        return f"<DailyPrice {self.ticker} {self.trade_date} C={self.close}>"
