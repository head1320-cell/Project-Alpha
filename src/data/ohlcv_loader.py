"""
OHLCV Loader — Screener V3 백테스트 데이터 공급
==========================================================================
백테스트의 데이터 공급원을 일원화. 우선순위:

  1) PostgreSQL daily_prices (이미 적재된 경우 — 가장 빠름)
  2) KIS 실시간 일봉 (KIS_USE_MOCK=0 + 키 → 실데이터, 자동 DB 적재)
  3) Deterministic mock (키 없을 때 — 개발/데모)

★ 핵심: 백테스트는 load_ohlcv_unified()만 호출하면
  환경에 따라 최선의 데이터를 자동 선택. 코드 무수정으로 mock↔실데이터 전환.

ingest_to_db(): KIS 일봉을 DB에 적재 (배치 사전 로딩용).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _mock_ohlcv_df(ticker: str, start_date: str, end_date: str):
    """deterministic mock OHLCV DataFrame (date index)."""
    import random

    import pandas as pd
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except Exception:
        end = datetime.now()
        start = end - timedelta(days=365)
    max(30, (end - start).days)

    seed = sum(ord(c) for c in ticker)
    rng = random.Random(seed)
    # 지수(KOSPI 등)는 시장 전체 — 개별주보다 변동성 낮고 완만한 우상향
    _code = ticker.replace(".KS", "").replace(".KQ", "").upper()
    is_index = _code in ("KOSPI", "KOSDAQ", "^KS11", "^KQ11", "KS11", "KQ11", "KS200")
    if is_index:
        base = 2500  # 코스피 지수 수준
        drift = rng.uniform(0.0001, 0.0004)   # 완만한 상승
        vol = 0.008                            # 일변동성 ~0.8% (개별주의 절반)
    else:
        base = 10000 + (seed % 90) * 1000
        drift = rng.uniform(-0.0005, 0.0012)
        vol = 0.018

    dates, closes = [], []
    px = base
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # 평일만
            px = max(100, px * (1 + drift + rng.gauss(0, vol)))
            dates.append(cur)
            closes.append(px)
        cur += timedelta(days=1)

    rows = {"open": [], "high": [], "low": [], "close": closes, "volume": []}
    base_vol = 100000 + (seed % 50) * 50000
    prev = closes[0] if closes else base
    for px in closes:
        spread = px * rng.uniform(0.005, 0.02)
        rows["open"].append(px - spread * rng.uniform(-0.3, 0.3))
        rows["high"].append(px + spread * rng.uniform(0.3, 1.0))
        rows["low"].append(px - spread * rng.uniform(0.3, 1.0))
        rows["volume"].append(base_vol * (1 + abs(px / prev - 1) * 8) * rng.uniform(0.6, 1.5))
        prev = px

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="date"))
    return df


def _kis_ohlcv_df(ticker: str, start_date: str, end_date: str):
    """KIS 실시간 일봉 → DataFrame (date index). 실패 시 None."""
    if os.getenv("KIS_USE_MOCK", "1") == "1":
        return None
    try:
        import pandas as pd

        from src.execution.kis_client import get_kis_client
        client = get_kis_client()
        if type(client).__name__ == "MockKISClient":
            return None
        # 기간 → 일수 환산
        try:
            days = (datetime.strptime(end_date, "%Y-%m-%d")
                    - datetime.strptime(start_date, "%Y-%m-%d")).days
        except Exception:
            days = 365
        # 상한을 크게(기본 5000≈20년) — get_daily_ohlcv가 페이지네이션으로 장기 역사를 채운다.
        # 요청 기간이 길수록 콜이 늘지만(콜드시), 적재 후엔 DB 히트라 무관.
        _max = int(os.getenv("KIS_OHLCV_MAX_DAYS", "5000") or 5000)
        days = max(60, min(days + 10, _max))
        rows = client.get_daily_ohlcv(ticker, days=days)
        if not rows or len(rows) < 20:
            return None
        df = pd.DataFrame(rows)
        # date 파싱 (YYYYMMDD)
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date")
        df = df[["open", "high", "low", "close", "volume"]]
        # 기간 필터
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        return df if not df.empty else None
    except Exception as e:
        logger.debug(f"KIS 일봉 조회 실패 ({ticker}): {e}")
        return None


def _db_ohlcv_df(ticker: str, start_date: str, end_date: str):
    """PostgreSQL daily_prices → DataFrame. 비어있으면 빈 df."""
    try:
        from src.kis_backtest_engine import load_ohlcv
        return load_ohlcv(ticker, start_date, end_date)
    except Exception:
        import pandas as pd
        return pd.DataFrame()


def load_ohlcv_unified(ticker: str, start_date: str, end_date: str,
                       prefer: str = "auto"):
    """
    백테스트용 OHLCV 통합 로더.

    prefer:
      "auto"  — DB → KIS → mock (운영 권장)
      "db"    — DB만
      "kis"   — KIS만 (실시간)
      "mock"  — mock만 (테스트)

    Returns: DataFrame(date index, open/high/low/close/volume) | 빈 df
    """
    import pandas as pd
    code = ticker.replace(".KS", "").replace(".KQ", "")

    if prefer == "mock":
        return _mock_ohlcv_df(code, start_date, end_date)
    if prefer == "db":
        return _db_ohlcv_df(code, start_date, end_date)
    if prefer == "kis":
        df = _kis_ohlcv_df(code, start_date, end_date)
        return df if df is not None else pd.DataFrame()

    # auto: DB → KIS → mock
    df = _db_ohlcv_df(code, start_date, end_date)
    if df is not None and not df.empty and len(df) >= 20:
        return df

    df = _kis_ohlcv_df(code, start_date, end_date)
    if df is not None and not df.empty:
        # KIS 성공 시 DB 적재 (다음 백테스트 가속)
        try:
            ingest_df_to_db(code, df)
        except Exception:
            pass
        return df

    # 최종 fallback: mock
    logger.info(f"OHLCV mock fallback: {code} (DB/KIS 모두 미가용)")
    return _mock_ohlcv_df(code, start_date, end_date)


def ingest_df_to_db(ticker: str, df) -> int:
    """DataFrame을 daily_prices에 UPSERT. Returns 적재 행 수."""
    try:
        from sqlalchemy import text

        from src.database import get_engine
    except Exception:
        return 0
    engine = get_engine()
    if engine is None or df is None or df.empty:
        return 0

    code = ticker.replace(".KS", "").replace(".KQ", "")
    rows = []
    for dt, r in df.iterrows():
        rows.append({
            "ticker": code,
            "trade_date": dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r.get("volume", 0)),
        })
    if not rows:
        return 0

    upsert = text("""
        INSERT INTO daily_prices (ticker, trade_date, "open", high, low, close, volume)
        VALUES (:ticker, :trade_date, :open, :high, :low, :close, :volume)
        ON CONFLICT (ticker, trade_date) DO UPDATE
          SET "open"=EXCLUDED."open", high=EXCLUDED.high, low=EXCLUDED.low,
              close=EXCLUDED.close, volume=EXCLUDED.volume
    """)
    try:
        with engine.begin() as conn:
            conn.execute(upsert, rows)
        return len(rows)
    except Exception as e:
        logger.warning(f"daily_prices 적재 실패 ({code}): {e}")
        return 0


def ingest_to_db(tickers: list, days: int = 400) -> dict:
    """
    여러 종목의 KIS 일봉을 DB에 사전 적재 (배치).
    백테스트 전 한 번 돌리면 이후 백테스트가 DB에서 빠르게 읽음.

    Returns: {ticker: 적재행수}
    """
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    result = {}
    for t in tickers:
        df = _kis_ohlcv_df(t, start, end)
        if df is not None and not df.empty:
            result[t] = ingest_df_to_db(t, df)
        else:
            result[t] = 0
    total = sum(result.values())
    logger.info(f"OHLCV 배치 적재: {len([v for v in result.values() if v])}종목, {total}행")
    return result


def _covered_ticker_set(engine, start_date: str, min_rows: int = 60) -> set:
    """start_date 이전까지 이미 적재된 ticker 집합 (사전적재 재개·중복 스킵용).

    날짜 기준(MIN(trade_date) <= start_date)이라 '장기 심화'를 지원한다 — 얕게만(최근 N개월)
    적재된 종목은 covered 가 아니므로 다시 '깊게' 받는다. (상장이 start_date 이후인 종목은
    full 역사를 받아도 covered 판정이 안 돼 매 실행 재수집될 수 있으나, 콜 수가 적어 저비용.)"""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT ticker FROM daily_prices GROUP BY ticker "
                     "HAVING MIN(trade_date) <= :sd AND COUNT(*) >= :m"),
                {"sd": start_date, "m": int(min_rows)},
            ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def prewarm_ohlcv(tickers: list, days: int = 3650, workers: int | None = None,
                  skip_existing: bool = True, min_rows: int = 60) -> dict:
    """여러 종목의 KIS 일봉을 daily_prices에 '병렬'로 사전 적재 (백테스터 DB 1순위 가속).

    - 병렬: 스레드 안전 KIS 클라이언트 + 전역 RateLimiter(≤18/s)로 안전. 네트워크 지연만 파이프라인.
    - skip_existing: 이미 min_rows 이상 적재된 종목은 KIS 호출 자체를 스킵(재개 가능·증분).
    - mock 모드·키 없음이면 _kis_ohlcv_df 가 None → 전부 0행(no-op). 안전.

    Returns: {"requested": n, "skipped": n, "loaded": n_종목, "rows": 총행수}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    uniq = [t for t in dict.fromkeys(tickers) if t]
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")

    skip: set = set()
    if skip_existing:
        try:
            from src.database import get_engine
            eng = get_engine()
            if eng is not None:
                skip = _covered_ticker_set(eng, start, min_rows)
        except Exception:
            skip = set()
    todo = [t for t in uniq if t not in skip]

    # 토큰 1회 프리워밍 (병렬 호출 전 — 동시 토큰 발급 경쟁 회피)
    try:
        from src.execution.kis_client import get_kis_client
        c = get_kis_client()
        if hasattr(c, "prewarm_token"):
            c.prewarm_token()
    except Exception:
        pass

    if workers is None:
        workers = max(1, min(int(os.getenv("OHLCV_PREWARM_WORKERS", "8") or 8), 24))

    def _one(t: str):
        try:
            df = _kis_ohlcv_df(t, start, end)
        except Exception:
            df = None
        if df is not None and not df.empty:
            try:
                return ingest_df_to_db(t, df)
            except Exception:
                return 0
        return 0

    loaded = 0
    rows = 0
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_one, t) for t in todo]
            for fut in as_completed(futs):
                try:
                    n = fut.result()
                except Exception:
                    n = 0
                if n:
                    loaded += 1
                    rows += n
    out = {"requested": len(uniq), "skipped": len(uniq) - len(todo), "loaded": loaded, "rows": rows}
    logger.info(f"OHLCV 사전적재(병렬): {out}")
    return out
