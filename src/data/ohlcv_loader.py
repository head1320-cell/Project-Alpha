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
from functools import lru_cache

logger = logging.getLogger(__name__)


#: mock 시계열의 고정 기점. ★모든 창이 같은 지점에서 출발한다★ — 이것이
#: "같은 날짜 = 같은 값" 을 만든다. 역사 시나리오(hist_2008_gfc)보다 앞이어야 한다.
_MOCK_EPOCH = datetime(2000, 1, 3)


@lru_cache(maxsize=4096)
def _mock_walk(ticker: str, through_ordinal: int) -> tuple:
    """기점부터 `through` 까지의 전체 경로 — ★창과 무관하게 한 벌만 존재한다★

    ★이 함수가 있는 이유 (실측)★ 예전 구현은 요청 **창의 시작점**에서 난수 보행을
    시작했다. 시드는 종목명에만 의존했으므로 같은 난수열이 다른 날짜에 붙었다:

        2024-06-03 종가 = 40,311.88   (2022 시작 창에서 조회)
        2024-06-03 종가 = 33,623.99   (2023 시작 창에서 조회)   ← 같은 날, 20% 차이

    가격이 **날짜가 아니라 창 안의 위치**에 붙어 있었다는 뜻이다. 그래서 `as_of`
    를 과거로 옮겨도 마지막 종가가 똑같이 나왔고 — mock 이 기본값인 개발·테스트
    환경에서 **모든 PIT/as_of 단언이 무의미**했다(alpha-lab 의 as_of 짝 단언이
    이것을 잡고 있었다).

    기점부터 만들고 잘라 쓰면 앞부분이 항상 같으므로 창이 달라도 값이 같다.
    `through` 를 연 단위로 올려 캐시가 맞도록 한다 — 하루 차이로 재생성하지 않는다.
    """
    import random
    seed = sum(ord(c) for c in ticker)
    rng = random.Random(seed)
    _code = ticker.replace(".KS", "").replace(".KQ", "").upper()
    is_index = _code in ("KOSPI", "KOSDAQ", "^KS11", "^KQ11", "KS11", "KQ11", "KS200")
    if is_index:
        base, drift, vol = 2500, rng.uniform(0.0001, 0.0004), 0.008
    else:
        base, drift, vol = 10000 + (seed % 90) * 1000, rng.uniform(-0.0005, 0.0012), 0.018

    through = datetime.fromordinal(through_ordinal)
    dates, closes = [], []
    px, cur = base, _MOCK_EPOCH
    while cur <= through:
        if cur.weekday() < 5:
            px = max(100, px * (1 + drift + rng.gauss(0, vol)))
            dates.append(cur)
            closes.append(px)
        cur += timedelta(days=1)
    return tuple(dates), tuple(closes), seed


def _mock_ohlcv_df(ticker: str, start_date: str, end_date: str):
    """deterministic mock OHLCV DataFrame (date index).

    ★같은 날짜는 어느 창에서 조회해도 같은 값이다★ — 이것이 없으면 `as_of` 가
    결과를 바꾸는지 잴 수 없고, PIT 단언이 전부 통과하면서 아무것도 지키지 않는다.
    """
    import random

    import pandas as pd
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except Exception:
        end = datetime.now()
        start = end - timedelta(days=365)
    if end < _MOCK_EPOCH:
        return pd.DataFrame({"open": [], "high": [], "low": [], "close": [], "volume": []},
                            index=pd.DatetimeIndex([], name="date"))

    # 연말까지 만들어 두고 잘라 쓴다 — 접두부가 같으므로 어떤 창에서든 값이 같다.
    horizon = datetime(end.year, 12, 31)
    all_dates, all_closes, seed = _mock_walk(ticker, horizon.toordinal())
    keep = [i for i, d in enumerate(all_dates) if start <= d <= end]
    dates = [all_dates[i] for i in keep]
    closes = [all_closes[i] for i in keep]

    # OHLC·거래량의 잡음은 **날짜에서** 뽑는다 — 위치에서 뽑으면 종가와 같은
    # 결함이 되살아난다(창이 달라지면 같은 날의 시가·거래량이 달라진다).
    def _noise(d: datetime) -> random.Random:
        return random.Random((seed << 20) ^ d.toordinal())
    rows = {"open": [], "high": [], "low": [], "close": list(closes), "volume": []}
    base_vol = 100000 + (seed % 50) * 50000
    prev = closes[0] if closes else 10000.0
    for d, px in zip(dates, closes):
        r = _noise(d)
        spread = px * r.uniform(0.005, 0.02)
        rows["open"].append(px - spread * r.uniform(-0.3, 0.3))
        rows["high"].append(px + spread * r.uniform(0.3, 1.0))
        rows["low"].append(px - spread * r.uniform(0.3, 1.0))
        rows["volume"].append(base_vol * (1 + abs(px / prev - 1) * 8) * r.uniform(0.6, 1.5))
        prev = px

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="date"))
    df.attrs["source"] = "mock"   # 데이터 출처 태그(정직성 — 합성 시계열)
    return df


def _kis_ohlcv_df(ticker: str, start_date: str, end_date: str):
    """KIS 실시간 일봉 → DataFrame (date index). 실패 시 None."""
    from src.data.mock_gate import mock_allowed
    if mock_allowed():
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
        df.attrs["source"] = "db"   # 실데이터(적재 DB)
        return df

    df = _kis_ohlcv_df(code, start_date, end_date)
    if df is not None and not df.empty:
        # KIS 성공 시 DB 적재 (다음 백테스트 가속)
        try:
            ingest_df_to_db(code, df)
        except Exception:
            pass
        df.attrs["source"] = "kis"  # 실데이터(KIS 실시간)
        return df

    # 최종 fallback: mock 모드만 합성, 운영선 빈 df(정직 — 실데이터 없음)
    from src.data.mock_gate import mock_allowed
    if mock_allowed():
        logger.info(f"OHLCV mock fallback: {code} (DB/KIS 모두 미가용)")
        return _mock_ohlcv_df(code, start_date, end_date)
    logger.info(f"OHLCV 미가용(실데이터 없음, 합성 금지): {code}")
    return pd.DataFrame()


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

    # ★스키마를 먼저 맞춘다★ 이 경로는 예전에 `ensure_table` 을 부르지 않았다.
    # `source` 컬럼이 생기면서, 기존 테이블에 그 컬럼이 없는 배포에서는 INSERT 가
    # 조용히 실패했을 것이다(아래 except 가 경고만 남긴다). `ensure_table` 이
    # ALTER 를 시도하고 "이미 있음" 은 무시하므로 반복 호출이 안전하다.
    try:
        from src.data.krx_ingest import ensure_table
        ensure_table(engine)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"daily_prices 스키마 확인 실패: {e}")

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

    # ★출처를 남긴다★ 이 경로는 `return_1d`(KRX 등락률)를 쓰지 않으므로
    # `rebuild_adj_close` 의 체인이 여기서 끊긴다. 어느 행이 그런지 알 수 있어야
    # `price_quality.adj_close_coverage()` 가 그 사실을 보고할 수 있다.
    from src.data.krx_ingest import SOURCE_KIS
    upsert = text("""
        INSERT INTO daily_prices (ticker, trade_date, "open", high, low, close, volume,
                                  source)
        VALUES (:ticker, :trade_date, :open, :high, :low, :close, :volume, :source)
        ON CONFLICT (ticker, trade_date) DO UPDATE
          SET "open"=EXCLUDED."open", high=EXCLUDED.high, low=EXCLUDED.low,
              close=EXCLUDED.close, volume=EXCLUDED.volume, source=EXCLUDED.source
    """)
    for r in rows:
        r["source"] = SOURCE_KIS
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
