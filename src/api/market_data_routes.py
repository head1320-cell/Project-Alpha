"""종목 목록·가격 시계열 — main_api.py에서 분리(경로·동작 불변).
"""

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("api.market_data")
router = APIRouter(tags=["market_data"])


@router.get("/api/v1/stocks")
async def v1_list_stocks(
    market: str | None = Query(None, description="KOSPI / KOSDAQ"),
    sector: str | None = Query(None),
    search: str | None = Query(None, description="name or ticker substring"),
    limit: int = Query(200, ge=1, le=1000),
):
    """List stocks from the DB. Fast — no external API calls."""
    try:
        from sqlalchemy import or_, select

        from src.database_async import async_session_scope
        from src.kis_models import Stock

        async with async_session_scope() as session:
            stmt = select(Stock).where(Stock.is_active == 1)
            if market:
                stmt = stmt.where(Stock.market == market.upper())
            if sector:
                stmt = stmt.where(Stock.sector == sector)
            if search:
                pat = f"%{search}%"
                stmt = stmt.where(or_(Stock.name.like(pat), Stock.ticker.like(pat)))
            stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            stocks = result.scalars().all()

            return {
                "count": len(stocks),
                "stocks": [
                    {
                        "ticker": s.ticker,
                        "name": s.name,
                        "market": s.market,
                        "sector": s.sector,
                    }
                    for s in stocks
                ],
            }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.get("/api/v1/prices/{ticker}")
async def v1_get_prices(
    ticker: str,
    days: int = Query(60, ge=1, le=500),
):
    """일별 OHLCV — DB→KIS(온디맨드)→mock 통합 로더. KIS 성공 시 DB에 적재(다음부턴 즉시).
    리스크 지표·가격차트가 미적재 종목에서도 동작하게 함."""
    try:
        import asyncio
        from datetime import datetime, timedelta

        from src.data.ohlcv_loader import load_ohlcv_unified

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=int(days * 1.7) + 40)).strftime("%Y-%m-%d")
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, lambda: load_ohlcv_unified(ticker, start, end, "auto"))
        if df is None or df.empty:
            return {"ticker": ticker, "count": 0, "prices": []}
        df = df.tail(days)

        def _f(v):
            try:
                return float(v)
            except Exception:
                return None

        prices = []
        for idx, r in df.iterrows():
            dt = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            prices.append({
                "date": dt,
                "open": _f(r.get("open")), "high": _f(r.get("high")), "low": _f(r.get("low")),
                "close": _f(r.get("close")), "volume": _f(r.get("volume")),
                "trading_value": _f(r.get("trading_value")) if "trading_value" in r else None,
            })
        return {"ticker": ticker, "count": len(prices), "prices": prices}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
