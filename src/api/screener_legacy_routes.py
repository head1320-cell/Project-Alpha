"""레거시 스크리너 (SQL 기반) — 신규는 src/api/screener_routes.py — main_api.py에서 분리(경로·동작 불변).
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text as _sql_text

from src.api.legacy_schemas import (
    ScreenerRequest,
)
from src.screener_pipeline import refresh_all_snapshots, snapshot_origin
from src.screener_sql import ALLOWED_FACTORS, build_screener_sql

logger = logging.getLogger("api.screener_legacy")
router = APIRouter(tags=["screener_legacy"])


@router.post("/screener")
def run_screener(req: ScreenerRequest):
    """
    Execute a screener query entirely in PostgreSQL.

    The client sends alphabet-labeled conditions and a logic expression like
    `(A AND B) OR C`. The server whitelists fields/operators, builds a
    parameterized WHERE clause, and executes it against the snapshot tables.

    All filtering runs in the DB engine. No Pandas, no in-memory aggregation.
    """
    try:
        sql, params = build_screener_sql(
            universe=req.universe,
            conditions=req.conditions,
            logic_expression=req.logic_expression,
            sort_by=req.sort_by,
            limit=req.limit,
        )
    except ValueError as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(status_code=400, detail=f"입력 오류: {e}")

    # ★출처 게이트★(2026-11-14) — 운영은 이 프로세스가 실데이터로 써넣은 표만 낸다. 아니면 표를 읽지 않고 0건 + 사유
    # (표에 예전 합성 행이 남아 있어도). mock 은 내되 `snapshot.is_mock` 이 붙는다.
    origin = snapshot_origin(req.universe)
    if not origin["available"]:
        return {"universe": req.universe, "count": 0, "results": [], "sql": sql, "snapshot": origin}

    try:
        from src.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(_sql_text(sql), params)
            rows = [dict(r._mapping) for r in result.fetchall()]
            # Serialize datetime fields
            for row in rows:
                for k, v in list(row.items()):
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    return {
        "universe": req.universe,
        "count": len(rows),
        "results": rows,
        "sql": sql,  # for debugging / transparency
        "snapshot": origin,
    }

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
