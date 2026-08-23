"""KRX 일별 전종목 백필 → daily_prices (젠포트식 사전 적재)
==========================================================================
KRX OpenAPI는 날짜 기준(basDd 1콜 = 그날 전종목)이라 종목별 로더 체인이 아니라
이 배치가 DB를 채우고, 백테스트는 DB(ohlcv_loader 1순위)에서 읽는다.

  · 재개 가능: 이미 전종목 적재된 날짜(행 수 ≥ 100)는 건너뜀 — 쿼터 분할 실행 안전
  · 지수(KOSPI/KOSDAQ)도 ticker="KOSPI"/"KOSDAQ" 행으로 적재 → 벤치마크·마켓타이밍 실데이터
  · 수정종가: KRX 시세는 원주가 → 등락률(return_1d에 보존) 체인으로 adj_close 역산 재구성
    (기준가 대비 등락률이라 분할·증자일에도 -50% 가짜 점프가 없음)

실행 (사용자 환경, KRX_API_KEY 필요):
    python -m src.data.krx_ingest --start 2015-01-01
    python -m src.data.krx_ingest --start 2024-01-01 --end 2024-12-31 --max-days 30
소요: 10년 ≈ 2,470거래일 × 2시장 ≈ 5,000콜 ≈ 50분 (0.6초 간격).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_CHUNK = 500          # bulk upsert 청크
_FULL_DAY_MIN_ROWS = 100  # 이 행 수 이상이면 "그날 전종목 적재 완료"로 간주(재개 판단)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker        VARCHAR(12) NOT NULL,
    trade_date    DATE        NOT NULL,
    "open"        FLOAT,
    high          FLOAT,
    low           FLOAT,
    close         FLOAT       NOT NULL,
    volume        BIGINT,
    trading_value BIGINT,
    adj_close     FLOAT,
    rsi_14        FLOAT,
    sma_20        FLOAT,
    sma_60        FLOAT,
    return_1d     FLOAT,
    mktcap        FLOAT,
    list_shares   FLOAT,
    PRIMARY KEY (ticker, trade_date)
)
"""

# 기존 테이블 마이그레이션용 — CREATE IF NOT EXISTS는 기존 테이블을 안 바꾸므로
# ALTER를 시도하고 "이미 있음" 류 에러는 무시 (PG/SQLite 공통 안전)
_MIGRATE_COLUMNS = ("mktcap FLOAT", "list_shares FLOAT")

_UPSERT = """
INSERT INTO daily_prices
    (ticker, trade_date, "open", high, low, close, volume, trading_value, return_1d,
     mktcap, list_shares)
VALUES
    (:ticker, :trade_date, :open, :high, :low, :close, :volume, :trading_value, :fluc_rt,
     :mktcap, :list_shares)
ON CONFLICT (ticker, trade_date) DO UPDATE SET
    "open"=EXCLUDED."open", high=EXCLUDED.high, low=EXCLUDED.low,
    close=EXCLUDED.close, volume=EXCLUDED.volume,
    trading_value=EXCLUDED.trading_value, return_1d=EXCLUDED.return_1d,
    mktcap=EXCLUDED.mktcap, list_shares=EXCLUDED.list_shares
"""


def _get_engine(engine=None):
    if engine is not None:
        return engine
    from src.database import get_engine
    return get_engine()


def ensure_table(engine) -> None:
    """daily_prices 없으면 생성 + 신규 컬럼(mktcap 등) 마이그레이션."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL))
    for col in _MIGRATE_COLUMNS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE daily_prices ADD COLUMN {col}"))
        except Exception:
            pass  # 이미 존재 — 정상


def bulk_upsert(engine, rows: list[dict]) -> int:
    """정규화 행(parse_stock_rows 출력) bulk UPSERT. 적재 행 수 반환."""
    if not rows:
        return 0
    from sqlalchemy import text
    payload = [{
        "ticker": r["ticker"], "trade_date": r["date"],
        "open": r.get("open"), "high": r.get("high"), "low": r.get("low"),
        "close": r["close"], "volume": r.get("volume") or 0,
        "trading_value": r.get("trading_value") or 0,
        "fluc_rt": r.get("fluc_rt"),
        "mktcap": r.get("mktcap"),
        "list_shares": r.get("shares"),
    } for r in rows]
    stmt = text(_UPSERT)
    with engine.begin() as conn:
        for i in range(0, len(payload), _CHUNK):
            conn.execute(stmt, payload[i:i + _CHUNK])
    return len(payload)


def loaded_dates(engine, min_rows: int = _FULL_DAY_MIN_ROWS) -> set[str]:
    """전종목 적재가 끝난 날짜 집합 (YYYY-MM-DD) — 재개 판단용."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            res = conn.execute(text(
                "SELECT trade_date, COUNT(*) AS c FROM daily_prices "
                "GROUP BY trade_date HAVING COUNT(*) >= :m"), {"m": min_rows})
            return {str(row[0])[:10] for row in res}
    except Exception:
        return set()


def _weekdays(start: str, end: str):
    d = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    while d <= e:
        if d.weekday() < 5:
            yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)


def backfill(start: str, end: str | None = None,
             markets: tuple = ("KOSPI", "KOSDAQ"), include_index: bool = True,
             skip_existing: bool = True, max_days: int | None = None,
             full_day_min_rows: int = _FULL_DAY_MIN_ROWS,
             engine=None, client=None) -> dict:
    """기간 백필. 휴장·API 실패일은 빈 응답으로 동일하게 보이므로 empty로 집계(정직)."""
    from src.data.krx_client import KRXClient
    client = client or KRXClient()
    if not client.is_configured:
        return {"error": True, "message": "KRX_API_KEY 미설정 — .env에 키를 넣고 실행하세요"}

    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_table(engine)

    end = end or datetime.now().strftime("%Y-%m-%d")
    done = loaded_dates(engine, min_rows=full_day_min_rows) if skip_existing else set()
    stats = {"days_requested": 0, "days_loaded": 0, "days_skipped": 0,
             "days_empty": 0, "rows": 0, "index_rows": 0}

    for day in _weekdays(start, end):
        if max_days is not None and stats["days_loaded"] >= max_days:
            break
        stats["days_requested"] += 1
        if day in done:
            stats["days_skipped"] += 1
            continue

        rows: list[dict] = []
        for m in markets:
            rows += client.get_daily_all(m, day)
        if not rows:
            stats["days_empty"] += 1  # 휴장 또는 호출 실패 — 구분 불가, 재실행 시 재시도됨
            continue
        stats["rows"] += bulk_upsert(engine, rows)

        if include_index:
            idx_rows = []
            for m in markets:
                idx = client.get_index_daily(m, day)
                if idx:
                    idx_rows.append({**idx, "ticker": m, "trading_value": 0.0})
            stats["index_rows"] += bulk_upsert(engine, idx_rows)

        stats["days_loaded"] += 1
        if stats["days_loaded"] % 20 == 0:
            logger.info(f"KRX backfill 진행: {day}까지 {stats['days_loaded']}일 / {stats['rows']:,}행")

    return stats


def index_loaded_dates(engine) -> set[str]:
    """지수(KOSPI/KOSDAQ) 행이 이미 있는 날짜 — backfill_index skip 판정용."""
    from sqlalchemy import text
    engine = _get_engine(engine)
    if engine is None:
        return set()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT trade_date FROM daily_prices "
                "WHERE ticker IN ('KOSPI','KOSDAQ')")).fetchall()
        return {str(r[0])[:10] for r in rows}
    except Exception:
        return set()


def backfill_index(start: str, end: str | None = None,
                   markets: tuple = ("KOSPI", "KOSDAQ"), skip_existing: bool = True,
                   max_days: int | None = None, engine=None, client=None) -> dict:
    """지수(KOSPI/KOSDAQ) 전용 백필 — ★주식 done-set과 독립★.
    기존 backfill은 주식이 적재된 날을 통째로 skip(line: day in done) → 그날의 지수는 영영
    안 채워지던 버그를 분리. 지수 보유 날짜(index_loaded_dates) 기준으로만 skip."""
    from src.data.krx_client import KRXClient
    client = client or KRXClient()
    if not client.is_configured:
        return {"error": True, "message": "KRX_API_KEY 미설정"}
    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_table(engine)

    end = end or datetime.now().strftime("%Y-%m-%d")
    done = index_loaded_dates(engine) if skip_existing else set()
    stats = {"days_requested": 0, "index_rows": 0, "days_skipped": 0, "days_empty": 0}

    for day in _weekdays(start, end):
        if max_days is not None and (stats["days_requested"] - stats["days_skipped"]) >= max_days:
            break
        stats["days_requested"] += 1
        if day in done:
            stats["days_skipped"] += 1
            continue
        idx_rows = []
        for m in markets:
            try:
                idx = client.get_index_daily(m, day)
            except Exception:
                idx = None
            if idx:
                idx_rows.append({**idx, "ticker": m, "trading_value": 0.0})
        if not idx_rows:
            stats["days_empty"] += 1
            continue
        stats["index_rows"] += bulk_upsert(engine, idx_rows)
    return stats


def rebuild_adj_close(engine=None, tickers: list[str] | None = None) -> int:
    """등락률(return_1d) 체인으로 adj_close 역산 재구성. 갱신 행 수 반환.

    최신일 adj=close 기준으로 과거로: adj[t-1] = adj[t] / (1 + r[t]/100).
    등락률은 (분할·증자 조정된) 기준가 대비라 corporate action 점프가 제거된다.
    등락률 결측 봉은 원주가 비율로 폴백."""
    from sqlalchemy import text
    engine = _get_engine(engine)
    if engine is None:
        return 0

    with engine.connect() as conn:
        if tickers is None:
            tickers = [r[0] for r in conn.execute(text("SELECT DISTINCT ticker FROM daily_prices"))]

    updated = 0
    upd = text("UPDATE daily_prices SET adj_close=:adj WHERE ticker=:t AND trade_date=:d")
    for tk in tickers:
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT trade_date, close, return_1d FROM daily_prices "
                "WHERE ticker=:t ORDER BY trade_date ASC"), {"t": tk}).fetchall()
            if not rows:
                continue
            n = len(rows)
            adj = [0.0] * n
            adj[n - 1] = float(rows[n - 1][1])
            for i in range(n - 2, -1, -1):
                close_i, close_next = float(rows[i][1]), float(rows[i + 1][1])
                r_next = rows[i + 1][2]
                if r_next is not None and float(r_next) > -99.0:
                    adj[i] = adj[i + 1] / (1.0 + float(r_next) / 100.0)
                else:
                    adj[i] = adj[i + 1] * (close_i / close_next) if close_next else adj[i + 1]
            payload = [{"adj": round(adj[i], 4), "t": tk, "d": str(rows[i][0])[:10]} for i in range(n)]
            for j in range(0, n, _CHUNK):
                conn.execute(upd, payload[j:j + _CHUNK])
            updated += n
    return updated


def auto_backfill(loop: bool = False) -> dict:
    """startup용 자동 백필 — env 설정·키 게이트. 키 없으면 즉시 no-op(현행 불변).

    env:
      KRX_AUTOBACKFILL  (기본 "1", "0"이면 비활성)
      KRX_BACKFILL_START(기본 "2010-01-04" — KRX 제공 최초)
      KRX_BACKFILL_MAX_DAYS(기본 0=무제한 — 데몬이라 비차단)
      KRX_REFRESH_SEC   (loop=True 증분 주기, 기본 12h)
    loop=True → 초기 백필 후 주기적으로 최신일까지 증분(skip_existing이 과거를 건너뜀).
    """
    import os
    import time
    if os.getenv("KRX_AUTOBACKFILL", "1") == "0":
        return {"skipped": "KRX_AUTOBACKFILL=0"}
    try:
        from src.data.krx_client import KRXClient
        if not KRXClient().is_configured:
            return {"skipped": "KRX_API_KEY 미설정 — 백필 건너뜀"}
    except Exception as e:
        return {"skipped": f"krx_client 로드 실패: {e}"}

    start = os.getenv("KRX_BACKFILL_START", "2010-01-04")  # KRX 제공 최초(2010)부터 — 깊은 역사
    try:
        max_days = int(os.getenv("KRX_BACKFILL_MAX_DAYS", "0")) or None
    except ValueError:
        max_days = None

    def _run_once() -> dict:
        end = datetime.now().strftime("%Y-%m-%d")
        stats = backfill(start=start, end=end, max_days=max_days, skip_existing=True)
        # 지수(KOSPI/KOSDAQ) 독립 백필 — 주식 done-set과 무관(이미 적재된 날도 지수 채움)
        try:
            stats["index_backfill"] = backfill_index(start=start, end=end)
        except Exception as e:
            logger.warning(f"지수 백필 실패: {e}")
        if not stats.get("error") and stats.get("rows"):
            try:
                stats["adj_rows"] = rebuild_adj_close()
            except Exception as e:
                logger.warning(f"adj_close 재구성 실패: {e}")
        logger.info(f"KRX 자동 백필: {stats}")
        return stats

    stats = _run_once()
    if loop:
        period = max(3600, int(os.getenv("KRX_REFRESH_SEC", str(12 * 3600)) or 0))
        while True:
            time.sleep(period)
            try:
                _run_once()
            except Exception as e:
                logger.warning(f"KRX 증분 백필 실패: {e}")
    return stats


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="KRX 일별 전종목 백필 → daily_prices")
    ap.add_argument("--start", required=True, help="시작일 YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="종료일 (기본 오늘)")
    ap.add_argument("--markets", default="KOSPI,KOSDAQ")
    ap.add_argument("--no-index", action="store_true", help="지수 적재 생략")
    ap.add_argument("--no-adj", action="store_true", help="수정종가 재구성 생략")
    ap.add_argument("--max-days", type=int, default=None, help="이번 실행 최대 적재 일수 (쿼터 분할)")
    ap.add_argument("--force", action="store_true", help="적재된 날짜도 다시 받기")
    args = ap.parse_args()

    stats = backfill(
        start=args.start, end=args.end,
        markets=tuple(m.strip().upper() for m in args.markets.split(",") if m.strip()),
        include_index=not args.no_index, skip_existing=not args.force,
        max_days=args.max_days,
    )
    print(f"백필 결과: {stats}")
    if not stats.get("error") and not args.no_adj and stats.get("rows"):
        n = rebuild_adj_close()
        print(f"수정종가(adj_close) 재구성: {n:,}행")


if __name__ == "__main__":
    main()
