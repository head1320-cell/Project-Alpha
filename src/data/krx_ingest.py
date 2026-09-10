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
#: ★출처 컬럼★ 같은 테이블에 writer 가 둘이라(KRX 전종목 백필 · KIS 온디맨드)
#: 어느 경로로 들어온 행인지 알 수 없었다. `rebuild_adj_close` 가 두 경로를
#: 다르게 다뤄야 하므로(KIS 행에는 `return_1d` 가 없다) 행에 기록이 필요하다.
#: ★기존 행은 NULL 로 남긴다★ — 소급 추정하지 않는다. NULL = "모른다" 는 사실이다.
SOURCE_KRX = "krx"
SOURCE_KIS = "kis"

# ── ★가격 정의(basis)★ `close` 가 무엇인지는 행마다 다르다 ──────────────────
#: `close` 컬럼에 **두 정의**가 섞여 있다:
#:
#:     source='krx' → 원주가   (`krx_client` 독스트링: "시세는 원주가(수정주가 아님)")
#:     source='kis' → 수정주가 (`kis_client.DAILY_ADJ_PRC_FLAG="0"` 로 요청)
#:
#: 소스 경계를 넘는 티커의 `close` 계열에는 **정의 점프**가 생긴다 — 기업행위
#: 점프가 아니라 **누적 수정계수 전체**여서, 분할 이력이 있으면 수십 배가 된다.
#: 그런데 정본 로더가 고르는 것이 바로 이 `close` 다.
#:
#: ★기존 행은 NULL 로 남긴다★ — `source` 와 같은 원칙. NULL = "모른다" 는 사실이다.
BASIS_RAW = "raw"
BASIS_ADJUSTED = "adjusted"

#: 후행 추가 컬럼 `(이름, DDL)`. ★넷 다 `_UPSERT` 가 쓴다★ — 하나라도 못 붙으면
#: 적재가 **전량** 실패하고, `source`·`price_basis` 는 `price_quality._fetch` 도
#: 읽으므로 가격 품질 보고가 통째로 `unavailable` 이 된다(사유는 "daily_prices
#: 조회 실패" 라는 엉뚱한 곳을 가리킨다). 그래서 **컬럼별로** 확인한다.
_MIGRATE_COLUMNS = (("mktcap", "FLOAT"), ("list_shares", "FLOAT"),
                    ("source", "VARCHAR(8)"), ("price_basis", "VARCHAR(8)"))

_UPSERT = """
INSERT INTO daily_prices
    (ticker, trade_date, "open", high, low, close, volume, trading_value, return_1d,
     mktcap, list_shares, source, price_basis)
VALUES
    (:ticker, :trade_date, :open, :high, :low, :close, :volume, :trading_value, :fluc_rt,
     :mktcap, :list_shares, :source, :price_basis)
ON CONFLICT (ticker, trade_date) DO UPDATE SET
    "open"=EXCLUDED."open", high=EXCLUDED.high, low=EXCLUDED.low,
    close=EXCLUDED.close, volume=EXCLUDED.volume,
    trading_value=EXCLUDED.trading_value, return_1d=EXCLUDED.return_1d,
    mktcap=EXCLUDED.mktcap, list_shares=EXCLUDED.list_shares,
    source=EXCLUDED.source, price_basis=EXCLUDED.price_basis
"""


def _get_engine(engine=None):
    if engine is not None:
        return engine
    from src.database import get_engine
    return get_engine()


#: ★생성 순서와 무관하게 같은 인덱스가 되게 한다★
#:
#: 이 테이블을 선언하는 곳이 둘이다 — 여기의 raw DDL 과 `kis_models.DailyPrice`.
#: 기동은 `create_all` 을 먼저 부르지만(`startup/lifecycle.py`), CLI 백필로 DB 를
#: 먼저 만드는 것도 정상 경로다. `create_all(checkfirst=True)` 는 **이미 있는
#: 테이블을 통째로 건너뛰므로 그 인덱스도 만들지 않는다** — 컬럼은 아래 `ALTER`
#: 가 치유했지만 인덱스는 치유되지 않아, 같은 제품의 두 DB 가 성능 특성이
#: 달랐다(실측).
#:
#: `trade_date` 단독 인덱스가 필요한 이유 — `universe_select.tickers_asof` /
#: `top_mktcap_asof` 는 ticker 술어가 없어 PK `(ticker, trade_date)` 의 선두
#: 컬럼이 안 걸린다. 그 둘이 이 테이블에서 **PK 로 답할 수 없는 유일한 축**이다.
_ENSURE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_daily_date ON daily_prices (trade_date)",
)


def _run_index_ddl(engine, sql: str) -> None:
    """인덱스 DDL 1건. ★분리해 둔 이유는 실패를 테스트에서 주입하기 위해서다★"""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(sql))


def ensure_table(engine) -> None:
    """daily_prices 없으면 생성 + 신규 컬럼(mktcap 등)·인덱스 마이그레이션."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL))
    # ★붙였다고 믿지 않는다★ `add_columns` 가 붙이고 **실제로 쓸 수 있는지**
    # 확인해 준다. 컬럼별로 부르는 것은 `company_snapshots` 의 선례다 — 통짜로
    # 부르면 "넷 중 하나가 없다" 만 알고 **어느 것인지** 모른다.
    from src.data.schema_add_columns import add_columns
    missing = [c for c, ddl in _MIGRATE_COLUMNS
               if not add_columns(engine, "daily_prices", [(c, ddl)],
                                  label="daily_prices")]
    if missing:
        logger.warning("daily_prices 컬럼을 쓸 수 없습니다: %s — 적재(UPSERT)가 "
                       "전량 실패하고 가격 품질 보고도 불가합니다. DB 권한·스키마를 "
                       "확인하세요.", ", ".join(missing))
    for sql in _ENSURE_INDEXES:
        # ★컬럼 ALTER 와 달리 삼키지 않는다★ `IF NOT EXISTS` 라 "이미 있음" 은
        # 예외가 아니다 — 여기서 예외가 나면 **진짜 실패**이고, 조용히 넘기면
        # 횡단면 조회가 풀스캔으로 남은 것을 아무도 모른다
        # (`schema_add_columns` 가 적어 둔 함정과 같은 부류).
        try:
            _run_index_ddl(engine, sql)
        except Exception as e:  # noqa: BLE001
            logger.warning("daily_prices 인덱스 생성 실패 — 횡단면 조회가 풀스캔으로 "
                           "남습니다: %s: %s (%s)", type(e).__name__, e, sql)


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
        "source": SOURCE_KRX,
        # ★KRX 시세는 원주가다★ 수정종가는 `return_1d` 체인으로 역산한다.
        "price_basis": BASIS_RAW,
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


#: KRX 등락률의 결측 센티넬. `-99.0` 이하는 값이 아니라 "없음" 표시다.
_RETURN_SENTINEL = -99.0


def _usable_return(r) -> bool:
    """체인 한 걸음에 쓸 수 있는 등락률인가.

    ★앵커 선택과 링크 판정이 **같은 규칙**을 써야 한다★ 둘이 갈라지면 앵커를
    세워 놓고 첫 걸음에서 끊기는 오늘의 결함이 다른 모양으로 되살아난다.
    """
    return r is not None and float(r) > _RETURN_SENTINEL


def rebuild_adj_close(engine=None, tickers: list[str] | None = None) -> int:
    """등락률(return_1d) 체인으로 adj_close 역산 재구성. 갱신 행 수 반환.

    최신일 adj=close 기준으로 과거로: adj[t-1] = adj[t] / (1 + r[t]/100).
    등락률은 (분할·증자 조정된) 기준가 대비라 corporate action 점프가 제거된다.

    ★등락률 결측 봉에서 체인이 **끊긴다** — 추정하지 않는다★

    예전에는 `adj[i] = adj[i+1] × (close_i/close_next)` 로 폴백했다. 그런데
    `return_1d` 가 없다는 것은 **그날 기업행위가 있었는지 모른다**는 뜻이고,
    없었다면 원주가 비율이 맞지만 있었다면 틀린다 — 구분할 방법이 없다.
    그 폴백은 **이 함수가 제거하려던 바로 그 점프를 다시 집어넣었다.**

    지금은 처음 비는 지점에서 체인을 끊고 **그 아래를 전부 `NULL`** 로 둔다.
    ★커버리지가 떨어지는 것이 요점이다★ — 조용히 틀린 값이 정직한 빈칸이 된다.
    얼마나 떨어졌는지는 `price_quality.adj_close_coverage()` 가 이름으로 낸다.

    ## ★앵커는 "체인을 이어갈 수 있는 가장 최신 행" 이다★

    예전에는 앵커를 **무조건 최신 봉**에 놓았다. 그런데 `ohlcv_loader` 가 넣는 KIS
    행에는 `return_1d` 가 없어서, 그런 행이 최신 봉이면 체인이 **첫 걸음에서** 끊기고
    그 아래가 전부 `NULL` 이 됐다 — 아래 행들의 등락률 체인은 멀쩡한데도.

    실측(5행 KRX + KIS 최신봉 1개): **5행 조정 → 1행 조정.** 되살릴 수 있는 역사를
    통째로 버렸다. 그리고 `load_ohlcv_unified` 와 `prewarm_ohlcv` 가 최신 KIS 봉을
    적재하므로 ★그것이 운영의 기본 상태였다.★

    `adj[i] = adj[i+1] / (1 + return_1d[i+1]/100)` 이므로 **앵커 자신에게
    `return_1d` 가 있어야** 아래로 한 걸음이라도 갈 수 있다. 없는 행에 앵커를 놓는
    것은 정의상 무의미하다. 그래서 앵커를 그런 행 중 가장 최신으로 옮기고, 그보다
    **위(더 최신)** 는 `NULL` 로 둔다.

    ★`price_basis` 를 보지 않는다★ "basis 가 `adjusted` 면 앵커 금지" 로도 짤 수
    있었지만 버렸다 — (1) `source`·`price_basis` 는 최근에 생긴 컬럼이라 레거시 행이
    전부 `NULL` 이고, basis 로 고르면 그 배포가 앵커를 전부 잃는다. (2) 그 규칙은
    *"KIS 는 수정주가를 준다"* 라는 **아직 검증되지 않은** 가정에 기댄다
    (`price_quality.basis_overlap_check()` 참조). `return_1d` 규칙은 그 가정과
    무관하게 옳다.

    ★등락률이 하나도 없는 티커는 앵커가 없어 전량 `NULL` 이다★ 예전에는 최신 봉
    한 칸이 채워졌다. 그 값이 거짓이었던 것은 아니다 — `adj(최신)=close(최신)` 는
    정규화 관례이고 구성상 참이다. 다만 **그 한 점으로는 수익률을 하나도 계산할 수
    없고**, 그 한 점 때문에 상태가 `chain_broken`("그 구간 재적재")으로 잡혀
    **틀린 조치**를 안내했다. 진실은 `raw`/`no_return_data` — "KRX 데이터가 아예 없다".

    Returns:
        갱신 행 수(`adj_close` 를 실제로 채운 행). 끊겨서 NULL 로 만든 행은
        세지 않는다.
    """
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
            adj: list[float | None] = [None] * n
            # ★앵커: `return_1d` 를 쓸 수 있는 가장 최신 행★ 그 위는 NULL 로 남는다.
            # 앵커에 등락률이 없으면 아래로 한 걸음도 갈 수 없다(위 독스트링).
            anchor = next((i for i in range(n - 1, -1, -1)
                           if _usable_return(rows[i][2])), None)
            if anchor is None:
                # 등락률이 하나도 없다 — 앵커를 세울 근거가 없다. 전량 NULL.
                payload = [{"adj": None, "t": tk, "d": str(rows[i][0])[:10]}
                           for i in range(n)]
                for j in range(0, n, _CHUNK):
                    conn.execute(upd, payload[j:j + _CHUNK])
                continue
            adj[anchor] = float(rows[anchor][1])     # adj = close (정규화 관례)
            for i in range(anchor - 1, -1, -1):
                if not _usable_return(rows[i + 1][2]):
                    break                             # ★체인이 끊긴다 — 아래는 NULL★
                r_next = rows[i + 1][2]
                prev = adj[i + 1]
                if prev is None:
                    break
                adj[i] = prev / (1.0 + float(r_next) / 100.0)
            payload = [{"adj": None if adj[i] is None else round(adj[i], 4),
                        "t": tk, "d": str(rows[i][0])[:10]} for i in range(n)]
            for j in range(0, n, _CHUNK):
                conn.execute(upd, payload[j:j + _CHUNK])
            updated += sum(1 for v in adj if v is not None)
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
