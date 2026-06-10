"""
DB-Backed Data Fetcher
=======================
KIS strategy_builder/core/data_fetcher.py 의 PostgreSQL 어댑터 버전.

원본은 KIS Open API를 직접 호출하지만,
이 모듈은 우리 플랫폼의 daily_prices 테이블에서 읽어옵니다.
(nightly sync로 채워진 캐시 → 전략 시뮬레이션에 최적)

인터페이스: get_daily_prices(), get_current_price() 함수명 동일 유지.
전략 클래스들이 이 모듈을 import하므로 서명을 바꾸지 않습니다.
"""

import logging
from datetime import date as _date
from datetime import timedelta

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _get_engine():
    """Lazy import — avoids circular dependency at module load time."""
    try:
        # For sync access we use the sync engine
        from src.database import get_engine
        return get_engine()
    except Exception:
        return None


def _get_sync_engine():
    try:
        from src.database import get_engine
        return get_engine()
    except Exception:
        return None


def get_daily_prices(
    stock_code: str,
    days: int = 100,
    env_dv: str = "real",   # ignored — kept for interface compat
) -> pd.DataFrame:
    """
    일봉 데이터를 DB에서 조회하여 정규화된 DataFrame 반환.

    원본(data_fetcher.py) 시그니처와 동일.
    반환 컬럼: date, open, high, low, close, volume

    Args:
        stock_code: 종목코드 (6자리 또는 .KS 접미사 포함)
        days:       조회 기간 (일)
        env_dv:     무시 (호환용)

    Returns:
        DataFrame — 비어있으면 전략이 HOLD 반환
    """
    engine = _get_sync_engine()
    if engine is None:
        logger.warning(f"DB unavailable for {stock_code}")
        return pd.DataFrame()

    try:
        # daily_prices는 ticker 컬럼을 6자리 코드로 저장
        ticker = stock_code.replace(".KS", "").replace(".KQ", "")
        since = (_date.today() - timedelta(days=days + 10)).isoformat()

        sql = text("""
            SELECT trade_date as date,
                   "open", high, low, close, volume
            FROM daily_prices
            WHERE ticker = :ticker
              AND trade_date >= :since
            ORDER BY trade_date ASC
            LIMIT :limit
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {
                "ticker": ticker,
                "since": since,
                "limit": days + 10,
            })
            rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = df["date"].astype(str).str.replace("-", "")

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df.tail(days).reset_index(drop=True)

    except Exception as e:
        logger.error(f"get_daily_prices error ({stock_code}): {e}")
        return pd.DataFrame()


def get_current_price(
    stock_code: str,
    env_dv: str = "real",
) -> dict:
    """
    최신 종가를 DB에서 조회 (현재가 근사값).

    실시간이 아니라 마지막 저장된 일봉 종가를 반환합니다.
    실시간이 필요하면 KISClient.get_current_price()를 직접 사용하세요.

    Returns:
        dict: price, high, low, volume, change_rate, w52_high, w52_low
    """
    engine = _get_sync_engine()
    if engine is None:
        return {}

    ticker = stock_code.replace(".KS", "").replace(".KQ", "")
    try:
        # 최신 2일치 + 52주 최고/저
        sql = text("""
            SELECT trade_date, "open", high, low, close, volume
            FROM daily_prices
            WHERE ticker = :ticker
            ORDER BY trade_date DESC
            LIMIT 2
        """)
        w52_sql = text("""
            SELECT MAX(high) as w52_high, MIN(low) as w52_low
            FROM daily_prices
            WHERE ticker = :ticker
              AND trade_date >= :since
        """)

        since = (_date.today() - timedelta(days=252)).isoformat()
        with engine.connect() as conn:
            rows = conn.execute(sql, {"ticker": ticker}).fetchall()
            w52 = conn.execute(w52_sql, {"ticker": ticker, "since": since}).fetchone()

        if not rows:
            return {}

        latest = rows[0]
        change_rate = 0.0
        if len(rows) >= 2:
            prev_close = float(rows[1][4])
            curr_close = float(latest[4])
            if prev_close:
                change_rate = (curr_close - prev_close) / prev_close * 100

        return {
            "price": int(latest[4]),
            "change": int(float(latest[4]) - float(rows[1][4])) if len(rows) >= 2 else 0,
            "change_rate": round(change_rate, 2),
            "high": int(latest[2]),
            "low": int(latest[3]),
            "volume": int(latest[5]),
            "w52_high": int(w52[0]) if w52 and w52[0] else 0,
            "w52_low": int(w52[1]) if w52 and w52[1] else 0,
        }

    except Exception as e:
        logger.error(f"get_current_price error ({stock_code}): {e}")
        return {}
