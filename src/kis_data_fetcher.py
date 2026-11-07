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
from contextvars import ContextVar
from datetime import date as _date
from datetime import timedelta

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 백테스트 봉 컨텍스트 (P0-1)
# ─────────────────────────────────────────────────────────────────────────────
# ★왜 ContextVar 인가★
# 예전에는 백테스트 엔진이 이 모듈의 `get_daily_prices`/`get_current_price` 를 **전역
# 대입으로 덮어썼다**(`kis_backtest_engine._generate_signal_as_of`). 되돌릴 값을
# "진입 시점의 전역" 에서 읽었기 때문에, 두 실행이 겹치면 서로의 람다를 '원본' 으로
# 저장하고 복원했다. 실측 결과 두 실행이 **정상 종료한 뒤에도 전역이 오염된 채**
# 남았고(`scripts/bench_backtest.py --race`), 그 프로세스의 이후 모든 조회가 완료된
# 실행의 얼어붙은 DataFrame 을 받았다. 오류는 한 건도 나지 않았다 — 조용히 틀렸다.
#
# ContextVar 는 **스레드마다 별개**이고 `set()` 이 준 토큰으로 정확히 복원된다.
# 교차 오염과 영구 누수가 규율이 아니라 **구조로** 막힌다.
#
# ★한계를 여기 적어 둔다★
# 컨텍스트는 **밀어 넣은 그 스레드**에서만 보인다. 지금 시뮬레이션 루프는 순차라
# (`BacktestEngine.run()` 단일 스레드) 성립한다. 나중에 신호 생성을 스레드풀로
# 병렬화하면 컨텍스트가 따라가지 않고 **조용히 라이브 DB 경로로 떨어진다** — 그러면
# 슬라이스가 아닌 전체 이력이 돌아와 룩어헤드가 된다.
#
# "컨텍스트가 없으면 예외" 로 막고 싶어지지만 **막으면 안 된다**: `uvicorn --workers 1`
# 이라 백테스트가 도는 동안 들어온 **라이브 신호 요청**이 같은 프로세스의 같은 함수를
# 부른다. 프로세스 전역 플래그로 거부하면 프로덕션 요청이 깨진다. 진짜 해법은
# 실행을 별도 프로세스로 빼는 것(P0-2)이다.
# ═══════════════════════════════════════════════════════════════════════════════

_BAR_CONTEXT: ContextVar[tuple | None] = ContextVar("kis_bar_context", default=None)


def push_bar_context(bars, price_info):
    """이 스레드의 조회를 `bars`/`price_info` 로 고정하고 복원용 토큰을 돌려준다."""
    return _BAR_CONTEXT.set((bars, price_info))


def pop_bar_context(token) -> None:
    """`push_bar_context` 가 준 토큰으로 **정확히 이전 상태**로 되돌린다.

    `set(None)` 이 아니라 `reset(token)` 이어야 중첩 호출이 안전하다.
    """
    _BAR_CONTEXT.reset(token)


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
    # 백테스트 봉 컨텍스트가 있으면 그것이 진실이다(위 블록 참조).
    _ctx = _BAR_CONTEXT.get()
    if _ctx is not None:
        return _ctx[0]
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
    _ctx = _BAR_CONTEXT.get()
    if _ctx is not None:
        return _ctx[1]
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
