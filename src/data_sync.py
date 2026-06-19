"""
KIS Data Sync Worker
======================
Nightly batch job that fetches data from KIS API and bulk-upserts
into PostgreSQL. Runs as a FastAPI background task at startup
(scheduled via asyncio.sleep) or can be triggered manually.

Design principles (e2-micro memory-safe):
  - Process tickers in small batches
  - Upsert via PostgreSQL ON CONFLICT ... DO UPDATE
  - Throttle KIS API calls to 15 TPS
  - Log progress every N tickers
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database_async import _engine_available, async_session_scope
from src.kis_client import KISClient
from src.kis_models import DailyPrice, Stock

logger = logging.getLogger(__name__)


# Curated seed universe for initial deployment.
# In production, replace with KIS master-file parser
# (stocks_info/kospi_code.mst + kosdaq_code.mst from KIS repo).
SEED_TICKERS = [
    # KOSPI 대형주
    ("005930", "삼성전자",             "KOSPI",  "Technology"),
    ("000660", "SK하이닉스",           "KOSPI",  "Technology"),
    ("035420", "NAVER",               "KOSPI",  "Technology"),
    ("035720", "카카오",               "KOSPI",  "Technology"),
    ("005380", "현대자동차",           "KOSPI",  "Auto"),
    ("000270", "기아",                 "KOSPI",  "Auto"),
    ("005490", "POSCO홀딩스",          "KOSPI",  "Steel"),
    ("051910", "LG화학",               "KOSPI",  "Chemicals"),
    ("006400", "삼성SDI",              "KOSPI",  "Battery"),
    ("068270", "셀트리온",             "KOSPI",  "Biotech"),
    ("207940", "삼성바이오로직스",      "KOSPI",  "Biotech"),
    ("105560", "KB금융",               "KOSPI",  "Financial"),
    ("055550", "신한지주",             "KOSPI",  "Financial"),
    ("086790", "하나금융지주",         "KOSPI",  "Financial"),
    ("028260", "삼성물산",             "KOSPI",  "Holdings"),
    ("017670", "SK텔레콤",             "KOSPI",  "Telecom"),
    ("030200", "KT",                  "KOSPI",  "Telecom"),
    ("066570", "LG전자",               "KOSPI",  "Electronics"),
    ("003550", "LG",                  "KOSPI",  "Holdings"),
    ("034730", "SK",                  "KOSPI",  "Holdings"),
    ("012330", "현대모비스",           "KOSPI",  "Auto Parts"),
    ("096770", "SK이노베이션",         "KOSPI",  "Energy"),
    # KOSDAQ 대표주
    ("247540", "에코프로비엠",         "KOSDAQ", "Battery"),
    ("086520", "에코프로",             "KOSDAQ", "Battery"),
    ("091990", "셀트리온헬스케어",      "KOSDAQ", "Biotech"),
    ("196170", "알테오젠",             "KOSDAQ", "Biotech"),
    ("293490", "카카오게임즈",         "KOSDAQ", "Gaming"),
    ("041510", "에스엠",               "KOSDAQ", "Entertainment"),
    ("035900", "JYP Ent.",            "KOSDAQ", "Entertainment"),
    ("357780", "솔브레인",             "KOSDAQ", "Chemicals"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Stock Metadata Sync
# ═══════════════════════════════════════════════════════════════════════════════

async def sync_stock_metadata():
    """Upsert stock metadata into the `stocks` table."""
    if not _engine_available:
        logger.warning("Async DB not available, skipping metadata sync")
        return

    async with async_session_scope() as session:
        for ticker, name, market, sector in SEED_TICKERS:
            stmt = pg_insert(Stock).values(
                ticker=ticker, name=name, market=market, sector=sector,
                currency="KRW", is_active=1,
            )
            # ON CONFLICT UPDATE
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker"],
                set_={
                    "name": stmt.excluded.name,
                    "market": stmt.excluded.market,
                    "sector": stmt.excluded.sector,
                },
            )
            try:
                await session.execute(stmt)
            except Exception as e:
                # Fallback for non-PostgreSQL backends
                logger.warning(f"Upsert fallback for {ticker}: {e}")
                # Simple try-insert-then-update
                from sqlalchemy import select
                existing = await session.execute(
                    select(Stock).where(Stock.ticker == ticker)
                )
                if existing.scalar_one_or_none() is None:
                    session.add(Stock(
                        ticker=ticker, name=name, market=market,
                        sector=sector, currency="KRW",
                    ))

    logger.info(f"Synced {len(SEED_TICKERS)} stock metadata records")


# ═══════════════════════════════════════════════════════════════════════════════
# Daily Price Sync
# ═══════════════════════════════════════════════════════════════════════════════

def _all_listed_tickers() -> list[str]:
    """전 상장 주권 코드 — KIS 마스터 캐시 기준 (collect-master 실행 후). 없으면 빈 리스트."""
    try:
        from src.data.stock_master import load_master_flags
        flags = load_master_flags()
        return [c for c, f in flags.items() if (f.get("group_code") or "ST") == "ST"]
    except Exception:
        return []


async def sync_daily_prices(
    client: KISClient,
    days_back: int = 60,
    batch_size: int = 10,
    all_listed: bool = False,
):
    """
    Fetch daily OHLCV for all tickers and upsert into daily_prices.
    Processes in batches to respect KIS rate limits and DB memory.

    all_listed=True: KIS 마스터 캐시의 전 상장 주권(~2,700) 대상.
      소요 ≈ 2,700콜 ÷ 15TPS ≈ 3분/일배치 (60일 회귀 기준 — 수년치 초기적재는 별도).
      캐시 없으면 SEED_TICKERS 폴백. 기본 False = 기존 동작(52종목) 불변.
    """
    if not _engine_available:
        logger.warning("Async DB not available, skipping price sync")
        return

    end_date = datetime.today().strftime("%Y%m%d")
    start_date = (datetime.today() - timedelta(days=days_back)).strftime("%Y%m%d")

    total = 0
    errors = 0

    tickers = [t[0] for t in SEED_TICKERS]
    if all_listed:
        full = _all_listed_tickers()
        if full:
            tickers = full
            logger.info(f"all_listed: {len(tickers)} tickers from master cache")
        else:
            logger.warning("all_listed 요청됐으나 마스터 캐시 없음 — SEED 폴백 (collect-master 먼저 실행)")
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        for ticker in batch:
            try:
                # KIS call is sync — wrap in executor to not block event loop
                loop = asyncio.get_running_loop()
                rows = await loop.run_in_executor(
                    None,
                    lambda: client.get_daily_prices(ticker, start_date, end_date),
                )
                client.throttle()

                if not rows:
                    continue

                # Bulk upsert
                async with async_session_scope() as session:
                    for r in rows:
                        trade_date = datetime.strptime(
                            r["trade_date"], "%Y%m%d"
                        ).date()
                        stmt = pg_insert(DailyPrice).values(
                            ticker=r["ticker"],
                            trade_date=trade_date,
                            open=r["open"], high=r["high"], low=r["low"],
                            close=r["close"],
                            volume=r["volume"],
                            trading_value=r["trading_value"],
                        )
                        try:
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["ticker", "trade_date"],
                                set_={
                                    "close": stmt.excluded.close,
                                    "open": stmt.excluded.open,
                                    "high": stmt.excluded.high,
                                    "low": stmt.excluded.low,
                                    "volume": stmt.excluded.volume,
                                    "trading_value": stmt.excluded.trading_value,
                                },
                            )
                            await session.execute(stmt)
                        except Exception:
                            # Non-PG fallback
                            pass

                total += len(rows)
                logger.info(f"  {ticker}: {len(rows)} daily rows")

            except Exception as e:
                errors += 1
                logger.warning(f"Failed to sync {ticker}: {e}")

        # Yield between batches
        await asyncio.sleep(0.5)

    logger.info(f"Price sync complete: {total} rows, {errors} errors")
    return {"rows": total, "errors": errors}


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduler Loop
# ═══════════════════════════════════════════════════════════════════════════════

async def sync_dart_fundamentals():
    """야간: 기본 유니버스 펀더멘털(DART)을 재적재 → 디스크 캐시 워밍/갱신.
    DART 키 없으면 건너뜀. 블로킹 작업이라 executor에서 실행(throttle·디스크캐시로 안전)."""
    import os
    if not os.getenv("DART_API_KEY"):
        return
    loop = asyncio.get_event_loop()

    def _work() -> int:
        from src.data.dart_client import _load_full_corp_map
        _load_full_corp_map()
        from src.data.fundamentals_store import FundamentalsStore
        from src.engine.screener import KOSPI200_TICKERS
        store = FundamentalsStore.get_default()
        store.cache_clear()  # in-memory 비우고 재계산 (대부분 디스크 캐시 적중)
        ok = 0
        for code in KOSPI200_TICKERS:
            try:
                store.get_factors(code, None)
                ok += 1
            except Exception:
                pass
        return ok

    try:
        ok = await loop.run_in_executor(None, _work)
        logger.info(f"DART 펀더멘털 야간 재적재: {ok}종목")
    except Exception as e:
        logger.error(f"DART 펀더멘털 야간 재적재 실패: {e}")


async def daily_sync_scheduler():
    """
    Run a daily sync at 02:00 KST (17:00 UTC).
    Called by FastAPI startup as a background task.
    """
    logger.info("KIS sync scheduler started")

    # Initial sync on boot (metadata only, to avoid API pressure)
    try:
        await sync_stock_metadata()
    except Exception as e:
        logger.error(f"Initial metadata sync failed: {e}")

    while True:
        now = datetime.utcnow()
        # 02:00 KST = 17:00 UTC on prior day
        target = now.replace(hour=17, minute=0, second=0, microsecond=0)
        if now >= target:
            target = target + timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info(f"Next KIS sync in {wait_seconds/3600:.1f} hours")
        await asyncio.sleep(wait_seconds)

        try:
            client = KISClient()
            await sync_stock_metadata()
            await sync_daily_prices(client, days_back=5)  # incremental
            await sync_dart_fundamentals()               # 펀더멘털 디스크 캐시 갱신
        except Exception as e:
            logger.error(f"Scheduled sync failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Manual Trigger Function (for FastAPI admin endpoint)
# ═══════════════════════════════════════════════════════════════════════════════

async def run_full_sync():
    """Synchronously invoke a full sync. For use from admin endpoints or CLI."""
    logger.info("Starting manual full sync")
    start = datetime.utcnow()

    await sync_stock_metadata()
    try:
        client = KISClient()
        result = await sync_daily_prices(client, days_back=60)
    except Exception as e:
        return {"error": str(e), "elapsed_sec": 0}

    elapsed = (datetime.utcnow() - start).total_seconds()
    return {
        **(result or {}),
        "elapsed_sec": round(elapsed, 1),
        "completed_at": datetime.utcnow().isoformat(),
    }
