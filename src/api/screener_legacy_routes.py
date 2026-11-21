"""레거시 스크리너 (SQL 기반) — 신규는 src/api/screener_routes.py — main_api.py에서 분리(경로·동작 불변).

S2(2026-11-19 받은 결정 '그 문 하나만 걷어 낸다'): 스냅샷 표의 행을 그대로 돌려주던 `POST /screener` 를 걷어 냈다 — 화면 호출 0
(감사 `docs/specs/2026-11-13-market-snapshot-synthetic-audit.md` §3). 남은 문 넷(`GET /screener/factors` · `POST /screener/refresh` ·
`GET /screener/status` · `GET /api/v1/screener/stocks`)은 그대로다. 그 문만 쓰던 `screener_sql.build_screener_sql` 은 지우지 않았다(보고만).
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text as _sql_text

from src.screener_pipeline import refresh_all_snapshots, snapshot_origin
from src.screener_sql import ALLOWED_FACTORS

logger = logging.getLogger("api.screener_legacy")
router = APIRouter(tags=["screener_legacy"])


@router.get("/screener/factors")
def get_screener_factors():
    """Return allowed factors per universe (whitelist)."""
    return {k: sorted(v) for k, v in ALLOWED_FACTORS.items()}

@router.post("/screener/refresh")
async def manual_refresh_screener():
    """Manually trigger a snapshot refresh (admin endpoint)."""
    try:
        from src.database import get_engine
        engine = get_engine()
        result = await refresh_all_snapshots(engine)
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

def _iso(v) -> str | None:
    """갱신 시각 — sqlite 는 시각을 문자열로 돌려준다(그대로 `.isoformat()` 을 부르면 500 이었다)."""
    if not v:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


@router.get("/screener/status")
def screener_status():
    """Return row counts + latest update timestamps."""
    try:
        from src.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            eq_count = conn.execute(
                _sql_text("SELECT COUNT(*) FROM market_snapshot_equity")
            ).scalar()
            ficc_count = conn.execute(
                _sql_text("SELECT COUNT(*) FROM market_snapshot_ficc")
            ).scalar()
            try:
                eq_updated = conn.execute(
                    _sql_text("SELECT MAX(updated_at) FROM market_snapshot_equity")
                ).scalar()
            except Exception:
                eq_updated = None
            try:
                ficc_updated = conn.execute(
                    _sql_text("SELECT MAX(updated_at) FROM market_snapshot_ficc")
                ).scalar()
            except Exception:
                ficc_updated = None
        return {
            "equity_rows": eq_count or 0,
            "ficc_rows": ficc_count or 0,
            "equity_updated_at": _iso(eq_updated),
            "ficc_updated_at": _iso(ficc_updated),
            "snapshot": {"equity": snapshot_origin("equity"), "ficc": snapshot_origin("ficc")},
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.get("/api/v1/screener/stocks")
async def v1_screener_stocks(
    min_price: float | None = None,
    max_price: float | None = None,
    min_volume: int | None = None,
    market: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """
    Fast screener query joining stocks with their latest daily price.
    Runs entirely in SQL — no Pandas, no KIS calls.
    """
    try:
        from src.database_async import async_session_scope

        # Raw SQL for a single efficient query with LATERAL JOIN-equivalent
        sql = """
            SELECT s.ticker, s.name, s.market, s.sector,
                   dp.close, dp.volume, dp.trade_date, dp.trading_value
            FROM stocks s
            LEFT JOIN LATERAL (
                SELECT close, volume, trade_date, trading_value
                FROM daily_prices
                WHERE ticker = s.ticker
                ORDER BY trade_date DESC
                LIMIT 1
            ) dp ON TRUE
            WHERE s.is_active = 1
        """
        params = {}
        if market:
            sql += " AND s.market = :market"
            params["market"] = market.upper()
        if min_price is not None:
            sql += " AND dp.close >= :min_price"
            params["min_price"] = min_price
        if max_price is not None:
            sql += " AND dp.close <= :max_price"
            params["max_price"] = max_price
        if min_volume is not None:
            sql += " AND dp.volume >= :min_volume"
            params["min_volume"] = min_volume
        sql += f" ORDER BY dp.trading_value DESC NULLS LAST LIMIT {int(limit)}"

        async with async_session_scope() as session:
            result = await session.execute(_sql_text(sql), params)
            rows = [dict(r._mapping) for r in result.fetchall()]
            for row in rows:
                for k, v in list(row.items()):
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()

        return {"count": len(rows), "results": rows}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
