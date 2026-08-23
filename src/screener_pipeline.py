"""
Async Market Data Pipeline
============================
Background worker that refreshes market snapshot tables every 5 minutes.

Memory-safe design for e2-micro (1GB):
  - Fetches data asset-by-asset, not all at once
  - Bulk inserts using SQLAlchemy core (no ORM object accumulation)
  - 'replace' strategy: TRUNCATE then bulk INSERT

Data sources (with graceful fallback to mock data):
  - yfinance: equity fundamentals + technicals
  - Mock generator: FICC (bonds, options, FX)
"""

import asyncio
import logging
import math
import os
from datetime import datetime

import numpy as np
from sqlalchemy import text

logger = logging.getLogger(__name__)


# Refresh interval (seconds) — 5 minutes per spec
REFRESH_INTERVAL_SEC = 300

# yfinance is heavily rate-limited (HTTP 429) from cloud IPs and is NOT required
# for the Korean screener (which uses its own KIS/DART/mock data path). Default
# OFF → use the deterministic mock snapshot, which keeps the FICC tables
# populated without spamming the logs. Opt in with MARKET_PIPELINE_USE_YFINANCE=1.
USE_YFINANCE = os.getenv("MARKET_PIPELINE_USE_YFINANCE", "0").strip().lower() in ("1", "true", "yes", "on")

# Curated ticker lists — small enough for e2-micro
EQUITY_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "WMT", "PG", "UNH", "HD", "MA", "BAC", "DIS", "KO",
    "005930.KS", "000660.KS", "035420.KS", "005380.KS", "051910.KS",
    "035720.KS", "068270.KS", "207940.KS", "000270.KS", "105560.KS",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2a: Equity Snapshot Builder
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_float(v, default=None):
    """Safely convert value to float, handling None/NaN."""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


async def fetch_equity_snapshot() -> list[dict]:
    """
    Fetch equity factor data.

    Attempts yfinance; falls back to deterministic mock data on any failure.
    Returns list of dicts ready for bulk insert.
    """
    rows = []
    if not USE_YFINANCE:
        # Default path: skip the rate-limited external feed entirely.
        logger.info("Equity snapshot: using deterministic mock (MARKET_PIPELINE_USE_YFINANCE off)")
        return _generate_mock_equity_data()
    try:
        import pandas as pd
        import yfinance as yf

        # Fetch in small batches to avoid memory spikes
        batch_size = 5
        for i in range(0, len(EQUITY_TICKERS), batch_size):
            batch = EQUITY_TICKERS[i:i+batch_size]
            try:
                hist = yf.download(
                    batch, period="1y", progress=False,
                    group_by="ticker", threads=False,
                )

                for ticker in batch:
                    try:
                        # Get info (fast_info is lighter than .info)
                        t = yf.Ticker(ticker)
                        fast = t.fast_info
                        info = {}
                        try:
                            info = t.info or {}
                        except Exception:
                            pass

                        # Extract history for momentum + RSI
                        if isinstance(hist.columns, pd.MultiIndex):
                            tick_hist = hist[ticker] if ticker in hist.columns.get_level_values(0) else None
                        else:
                            tick_hist = hist

                        if tick_hist is None or tick_hist.empty:
                            continue

                        close = tick_hist["Close"].dropna()
                        if len(close) < 20:
                            continue

                        # RSI
                        delta = close.diff()
                        gain = delta.where(delta > 0, 0).rolling(14).mean()
                        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                        rs = gain / loss.replace(0, float("nan"))
                        rsi = float(100 - 100 / (1 + rs.iloc[-1])) if not math.isnan(rs.iloc[-1]) else 50

                        # Returns
                        r12m = float(close.iloc[-1] / close.iloc[0] - 1) * 100 \
                            if len(close) > 200 else 0
                        r3m = float(close.iloc[-1] / close.iloc[-63] - 1) * 100 \
                            if len(close) > 63 else 0

                        # Volatility
                        vol_ann = float(close.pct_change().std() * math.sqrt(252) * 100)

                        # Market cap
                        try:
                            mcap = float(fast.market_cap) / 1e9 if fast.market_cap else None
                        except Exception:
                            mcap = None

                        rows.append({
                            "ticker": ticker,
                            "name": info.get("shortName", ticker),
                            "sector": info.get("sector", "Unknown"),
                            "currency": info.get("currency", "USD"),
                            "price": _safe_float(close.iloc[-1]),
                            "volume": _safe_float(tick_hist["Volume"].iloc[-1]),
                            "market_cap": mcap,
                            "per": _safe_float(info.get("trailingPE")),
                            "pbr": _safe_float(info.get("priceToBook")),
                            "dividend_yield": _safe_float(info.get("dividendYield"),
                                                           default=0) * 100
                                if info.get("dividendYield") else 0,
                            "roe": _safe_float(info.get("returnOnEquity"), default=0) * 100
                                if info.get("returnOnEquity") else _safe_float(info.get("returnOnEquity")),
                            "roa": _safe_float(info.get("returnOnAssets"), default=0) * 100
                                if info.get("returnOnAssets") else _safe_float(info.get("returnOnAssets")),
                            "debt_equity": _safe_float(info.get("debtToEquity"), default=0) / 100
                                if info.get("debtToEquity") else None,
                            "rsi": round(rsi, 2),
                            "macd": 0,  # placeholder
                            "return_12m": round(r12m, 2),
                            "return_3m": round(r3m, 2),
                            "beta": _safe_float(info.get("beta")),
                            "volatility_annual": round(vol_ann, 2),
                            "updated_at": datetime.utcnow(),
                        })

                    except Exception as e:
                        logger.warning(f"Failed to process {ticker}: {e}")

            except Exception as e:
                logger.warning(f"Batch download failed: {e}")

            # Yield to event loop between batches
            await asyncio.sleep(0.1)

    except ImportError:
        logger.warning("yfinance unavailable, using mock equity data")

    # Fallback: generate mock data if yfinance returned nothing
    if not rows:
        rows = _generate_mock_equity_data()

    return rows


def _generate_mock_equity_data() -> list[dict]:
    """Deterministic mock equity data fallback."""
    np.random.seed(42)
    sectors = ["Technology", "Financial", "Consumer", "Healthcare",
                "Industrial", "Energy"]
    rows = []
    for i, t in enumerate(EQUITY_TICKERS):
        rows.append({
            "ticker": t,
            "name": f"{t} Corp",
            "sector": sectors[i % len(sectors)],
            "currency": "KRW" if ".KS" in t else "USD",
            "price": round(float(np.random.lognormal(4.5, 0.5)), 2),
            "volume": float(np.random.lognormal(15, 1)),
            "market_cap": round(float(np.random.lognormal(4, 1.2)), 1),
            "per": round(float(np.random.lognormal(2.8, 0.4)), 2),
            "pbr": round(float(np.random.lognormal(0.5, 0.5)), 2),
            "dividend_yield": round(float(np.random.exponential(2.0)), 2),
            "roe": round(float(np.random.normal(15, 10)), 2),
            "roa": round(float(np.random.normal(7, 5)), 2),
            "debt_equity": round(float(np.random.exponential(0.8)), 2),
            "rsi": round(float(np.random.normal(50, 15)), 1),
            "macd": round(float(np.random.normal(0, 2)), 3),
            "return_12m": round(float(np.random.normal(12, 30)), 2),
            "return_3m": round(float(np.random.normal(3, 15)), 2),
            "beta": round(float(np.random.normal(1.0, 0.4)), 2),
            "volatility_annual": round(float(np.random.normal(25, 10)), 2),
            "updated_at": datetime.utcnow(),
        })
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2b: FICC Snapshot Builder
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_ficc_snapshot() -> list[dict]:
    """
    Generate FICC snapshot data (bonds, options, FX).

    Uses deterministic mock data — plug in a real feed (Bloomberg API,
    Refinitiv) by replacing this function.
    """
    np.random.seed(42)
    rows = []

    # Bonds
    bond_tickers = ["US10Y", "US30Y", "US2Y", "US5Y", "KR10Y", "KR3Y",
                     "DE10Y", "JP10Y", "UK10Y",
                     "AAPL 2030", "MSFT 2028", "KOGAS 2027", "SK 2026",
                     "TLT", "IEF", "SHY", "HYG", "LQD"]
    for t in bond_tickers:
        mat = float(np.random.uniform(0.5, 30))
        rows.append({
            "ticker": t, "asset_type": "bond", "currency": "USD",
            "price": round(float(np.random.uniform(85, 110)), 2),
            "ytm": round(float(np.random.uniform(2, 8)), 3),
            "duration": round(mat * np.random.uniform(0.7, 1.0), 2),
            "convexity": round(float(np.random.uniform(5, 200)), 1),
            "credit_spread_bps": round(float(np.random.exponential(120)), 0),
            "maturity_years": round(mat, 2),
            "rating_score": int(np.random.choice(range(8, 23))),
            # Options fields NULL
            "delta": None, "gamma": None, "theta": None, "vega": None,
            "implied_volatility": None, "iv_rank": None,
            "dte_days": None, "moneyness": None, "open_interest": None,
            # FX fields NULL
            "daily_vol": None, "carry_annual": None, "momentum_12m": None,
            "ppp_deviation": None, "real_rate_diff": None,
            "updated_at": datetime.utcnow(),
        })

    # Options
    opt_underlyings = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "BTC-USD"]
    for u in opt_underlyings:
        for otype in ["C", "P"]:
            for moneyness in [0.85, 0.95, 1.0, 1.05, 1.15]:
                for dte in [15, 30, 60, 90]:
                    delta_base = 0.5 if otype == "C" else -0.5
                    delta = delta_base * (1 + (moneyness - 1) * 2)
                    delta = float(np.clip(delta, -0.99, 0.99))
                    rows.append({
                        "ticker": f"{u} {moneyness:.2f}x{dte}d {otype}",
                        "asset_type": "option", "currency": "USD",
                        "price": round(float(np.random.uniform(1, 30)), 2),
                        # Bond fields NULL
                        "ytm": None, "duration": None, "convexity": None,
                        "credit_spread_bps": None, "maturity_years": None,
                        "rating_score": None,
                        # Options
                        "delta": round(delta, 3),
                        "gamma": round(float(np.random.uniform(0.01, 0.08)), 4),
                        "theta": round(float(-np.random.uniform(0.02, 0.20)), 4),
                        "vega": round(float(np.random.uniform(5, 30)), 2),
                        "implied_volatility": round(float(np.random.normal(28, 12)), 2),
                        "iv_rank": round(float(np.random.uniform(10, 95)), 1),
                        "dte_days": dte,
                        "moneyness": moneyness,
                        "open_interest": int(np.random.exponential(5000)),
                        # FX fields NULL
                        "daily_vol": None, "carry_annual": None, "momentum_12m": None,
                        "ppp_deviation": None, "real_rate_diff": None,
                        "updated_at": datetime.utcnow(),
                    })

    # FX
    fx_pairs = ["EURUSD", "USDJPY", "GBPUSD", "USDKRW", "USDCNH",
                 "AUDUSD", "USDCHF", "NZDUSD", "USDMXN"]
    for p in fx_pairs:
        rows.append({
            "ticker": p, "asset_type": "fx", "currency": "USD",
            "price": round(float(np.random.uniform(0.5, 1500)), 4),
            # Bond NULL
            "ytm": None, "duration": None, "convexity": None,
            "credit_spread_bps": None, "maturity_years": None,
            "rating_score": None,
            # Options NULL
            "delta": None, "gamma": None, "theta": None, "vega": None,
            "implied_volatility": None, "iv_rank": None,
            "dte_days": None, "moneyness": None, "open_interest": None,
            # FX
            "daily_vol": round(float(np.random.uniform(0.3, 1.5)), 3),
            "carry_annual": round(float(np.random.normal(1, 4)), 2),
            "momentum_12m": round(float(np.random.normal(0, 8)), 2),
            "ppp_deviation": round(float(np.random.normal(0, 15)), 2),
            "real_rate_diff": round(float(np.random.normal(0, 3)), 2),
            "updated_at": datetime.utcnow(),
        })

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# DB Refresh: TRUNCATE + Bulk INSERT (memory-safe)
# ═══════════════════════════════════════════════════════════════════════════════

def _bulk_refresh_table(engine, table_name: str, rows: list[dict]):
    """
    Memory-safe refresh: TRUNCATE then bulk INSERT in chunks.
    Uses SQLAlchemy core — no ORM objects accumulated in memory.
    """
    if not rows:
        logger.warning(f"No rows to insert into {table_name}")
        return 0

    CHUNK_SIZE = 50  # small to stay within 1GB limit

    with engine.begin() as conn:
        # TRUNCATE (PostgreSQL) or DELETE (SQLite)
        try:
            conn.execute(text(f"TRUNCATE TABLE {table_name}"))
        except Exception:
            conn.execute(text(f"DELETE FROM {table_name}"))

        # Determine columns from first row (all rows must have same keys)
        cols = list(rows[0].keys())
        cols_sql = ", ".join(cols)
        placeholders = ", ".join(f":{c}" for c in cols)
        insert_sql = text(f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders})")

        inserted = 0
        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i:i+CHUNK_SIZE]
            conn.execute(insert_sql, chunk)
            inserted += len(chunk)

    return inserted


async def refresh_all_snapshots(engine) -> dict:
    """Refresh both equity and FICC snapshot tables."""
    logger.info("Starting market snapshot refresh...")
    start = datetime.utcnow()

    try:
        eq_rows = await fetch_equity_snapshot()
        eq_count = _bulk_refresh_table(engine, "market_snapshot_equity", eq_rows)
    except Exception as e:
        logger.error(f"Equity refresh failed: {e}")
        eq_count = 0

    try:
        ficc_rows = await fetch_ficc_snapshot()
        ficc_count = _bulk_refresh_table(engine, "market_snapshot_ficc", ficc_rows)
    except Exception as e:
        logger.error(f"FICC refresh failed: {e}")
        ficc_count = 0

    elapsed = (datetime.utcnow() - start).total_seconds()
    result = {
        "equity_rows": eq_count,
        "ficc_rows": ficc_count,
        "elapsed_sec": round(elapsed, 2),
        "completed_at": datetime.utcnow().isoformat(),
    }
    logger.info(f"Snapshot refresh complete: {result}")
    return result


async def update_market_cache_loop(engine):
    """Background task: refresh snapshots every 5 minutes."""
    # Initial load
    try:
        await refresh_all_snapshots(engine)
    except Exception as e:
        logger.error(f"Initial snapshot failed: {e}")

    while True:
        await asyncio.sleep(REFRESH_INTERVAL_SEC)
        try:
            await refresh_all_snapshots(engine)
        except Exception as e:
            logger.error(f"Scheduled snapshot failed: {e}")
