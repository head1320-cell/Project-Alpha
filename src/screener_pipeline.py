"""
Async Market Data Pipeline
============================
Background worker that refreshes market snapshot tables every 5 minutes.

Memory-safe design for e2-micro (1GB):
  - Fetches data asset-by-asset, not all at once
  - Bulk inserts using SQLAlchemy core (no ORM object accumulation)
  - 'replace' strategy: TRUNCATE then bulk INSERT

Data sources — ★운영에서는 합성 스냅샷을 만들지 않는다★ (2026-11-14 · 감사 `docs/specs/2026-11-13-market-snapshot-synthetic-audit.md` §7):
  - mock(`mock_gate.mock_allowed()`): 난수 고정 합성 행(주식 28 · FICC 267) — 출처 라벨 `is_mock: True` 가 붙는다.
  - 운영 · 주식: `MARKET_PIPELINE_USE_YFINANCE` 를 켰을 때 ★받은 행만★. 꺼져 있거나 하나도 못 받으면 빈 결과 + 사유(합성 대체 없음).
  - 운영 · FICC: 실데이터 원천이 코드에 없다 → 늘 빈 결과 + 사유.
  빈 결과는 표를 ★비운다★(예전 버전이 써 둔 합성 행이 남지 않게). 읽는 쪽(레거시 라우트)은 `snapshot_origin()` 한 곳에 묻는다.
"""

import asyncio
import logging
import math
import os
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text

logger = logging.getLogger(__name__)


# Refresh interval (seconds) — 5 minutes per spec
REFRESH_INTERVAL_SEC = 300

# yfinance is heavily rate-limited (HTTP 429) from cloud IPs and is NOT required
# for the Korean screener (which uses its own KIS/DART/mock data path). Default
# OFF → 운영에서는 주식 스냅샷이 비어 있다(사유 `feed_off`) — 합성 행으로 채우지 않는다.
# Opt in with MARKET_PIPELINE_USE_YFINANCE=1.
USE_YFINANCE = os.getenv("MARKET_PIPELINE_USE_YFINANCE", "0").strip().lower() in ("1", "true", "yes", "on")

#: 출처 사유 문장 — 응답에 그대로 실린다(합니다체 · 개발자 낱말·환경변수 이름 없음 — 용어집 §6).
SNAPSHOT_SYNTHETIC = "합성 데이터 모드의 시장 스냅샷입니다 — 실제 시세·재무가 아닙니다."
SNAPSHOT_FEED_OFF = "시장 스냅샷의 실데이터 수집이 꺼져 있어 값이 없습니다."
SNAPSHOT_DOWNLOAD_FAILED = "시장 스냅샷의 시세를 내려받지 못해 값이 없습니다."
SNAPSHOT_NO_FEED = "채권·외환·옵션 스냅샷은 실데이터 원천이 연결돼 있지 않아 값이 없습니다."
SNAPSHOT_NOT_REFRESHED = "시장 스냅샷을 아직 갱신하지 못해 값이 없습니다."

#: universe → 이 프로세스가 표에 마지막으로 ★써넣는 데 성공한★ 스냅샷의 출처. 프로세스 로컬이다(`uvicorn --workers 1` — CLAUDE.md §6).
_WRITTEN: dict[str, dict] = {}


def _origin(source: str | None, *, reason: str | None = None, message: str | None = None, **extra) -> dict:
    """스냅샷의 출처 라벨 — `source` 는 `"synthetic"`(합성) · `"yahoo"`(받은 실데이터) · `None`(값 없음 + 사유)."""
    return {"available": source is not None, "source": source, "is_mock": source == "synthetic",
            "reason": reason, "message": message, **extra}


def snapshot_origin(universe: str) -> dict:
    """그 표를 ★내도 되는지★와 출처 라벨 — 읽는 쪽이 묻는 한 곳.

    mock 은 합성 라벨로 낸다. 운영은 ★이 프로세스가 실데이터로 써넣은 표만★ 낸다 — 써넣은 적이 없거나(갱신 전·갱신 실패)
    기록이 합성이면 `available: False` + 사유다(표에 예전 합성 행이 남아 있어도 내지 않는다).
    """
    from src.data.mock_gate import mock_allowed
    if mock_allowed():
        return _origin("synthetic", message=SNAPSHOT_SYNTHETIC)
    written = _WRITTEN.get(universe)
    if written is None or written["is_mock"]:
        return _origin(None, reason="not_refreshed", message=SNAPSHOT_NOT_REFRESHED)
    return dict(written)


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


async def fetch_equity_snapshot() -> tuple[list[dict], dict]:
    """
    Fetch equity factor data — `(rows, origin)`: 행과 그 출처 라벨을 ★함께★ 돌려준다.

    mock → 합성 행(야후를 켜 두었어도 나가지 않는다). 운영 → 야후를 켰을 때 받은 행만 —
    꺼져 있거나 하나도 못 받으면 `[]` + 사유다(★합성 행으로 대신하지 않는다★). 판정은 `mock_allowed()` 하나.
    """
    rows = []
    from src.data.mock_gate import mock_allowed
    if mock_allowed():
        return _generate_mock_equity_data(), _origin("synthetic", message=SNAPSHOT_SYNTHETIC)
    if not USE_YFINANCE:
        return [], _origin(None, reason="feed_off", message=SNAPSHOT_FEED_OFF)
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
                            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
                        })

                    except Exception as e:
                        logger.warning(f"Failed to process {ticker}: {e}")

            except Exception as e:
                logger.warning(f"Batch download failed: {e}")

            # Yield to event loop between batches
            await asyncio.sleep(0.1)

    except ImportError:
        logger.warning("yfinance unavailable — equity snapshot stays empty")

    if not rows:
        return [], _origin(None, reason="download_failed", message=SNAPSHOT_DOWNLOAD_FAILED)
    return rows, _origin("yahoo", requested=len(EQUITY_TICKERS), received=len(rows))


def _generate_mock_equity_data() -> list[dict]:
    """Deterministic mock equity data — ★mock 게이트 안에서만★ 부른다(`fetch_equity_snapshot`)."""
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
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        })
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2b: FICC Snapshot Builder
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_ficc_snapshot() -> tuple[list[dict], dict]:
    """
    FICC snapshot data (bonds, options, FX) — `(rows, origin)`.

    실데이터 원천이 코드에 없다(plug in a real feed — Bloomberg API, Refinitiv). 그래서 운영은 늘 `[]` + 사유이고,
    mock 만 난수 고정 합성 행을 만든다.
    """
    from src.data.mock_gate import mock_allowed
    if not mock_allowed():
        return [], _origin(None, reason="no_feed", message=SNAPSHOT_NO_FEED)
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
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
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
                        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
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
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        })

    return rows, _origin("synthetic", message=SNAPSHOT_SYNTHETIC)


# ═══════════════════════════════════════════════════════════════════════════════
# DB Refresh: TRUNCATE + Bulk INSERT (memory-safe)
# ═══════════════════════════════════════════════════════════════════════════════

def _bulk_refresh_table(engine, table_name: str, rows: list[dict]):
    """
    Memory-safe refresh: TRUNCATE then bulk INSERT in chunks.
    Uses SQLAlchemy core — no ORM objects accumulated in memory.

    ★빈 `rows` 도 표를 비운다★ — 스냅샷은 '이번 갱신의 결과'다. 건드리지 않고 돌아가면 예전에 써 둔 행(합성 포함)이 남는다.
    """
    CHUNK_SIZE = 50  # small to stay within 1GB limit

    with engine.begin() as conn:
        # TRUNCATE (PostgreSQL) or DELETE (SQLite)
        try:
            conn.execute(text(f"TRUNCATE TABLE {table_name}"))
        except Exception:
            conn.execute(text(f"DELETE FROM {table_name}"))

        if not rows:
            logger.info(f"No rows for {table_name} — table left empty")
            return 0

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
    start = datetime.now(timezone.utc).replace(tzinfo=None)

    # 출처 기록(`_WRITTEN`)은 ★써넣기가 성공한 뒤에만★ 고친다 — 실패하면 표가 그대로이므로 기록도 그대로여야 한다.
    try:
        eq_rows, eq_origin = await fetch_equity_snapshot()
        eq_count = _bulk_refresh_table(engine, "market_snapshot_equity", eq_rows)
        _WRITTEN["equity"] = eq_origin
    except Exception as e:
        logger.error(f"Equity refresh failed: {e}")
        eq_count = 0

    try:
        ficc_rows, ficc_origin = await fetch_ficc_snapshot()
        ficc_count = _bulk_refresh_table(engine, "market_snapshot_ficc", ficc_rows)
        _WRITTEN["ficc"] = ficc_origin
    except Exception as e:
        logger.error(f"FICC refresh failed: {e}")
        ficc_count = 0

    elapsed = (datetime.now(timezone.utc).replace(tzinfo=None) - start).total_seconds()
    result = {
        "equity_rows": eq_count,
        "ficc_rows": ficc_count,
        "elapsed_sec": round(elapsed, 2),
        "completed_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "snapshot": {"equity": snapshot_origin("equity"), "ficc": snapshot_origin("ficc")},
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
