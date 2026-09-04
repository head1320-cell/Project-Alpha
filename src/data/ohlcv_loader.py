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
        # ★구간을 알려준다★ 예전에는 `days`(달력일)만 넘겨서, 클라이언트가 그것을
        # 영업일 행 목표로 오해해 필요량의 1.52배를 받고 오늘부터 거슬러 긁었다.
        # 상한(`KIS_OHLCV_MAX_DAYS`)에 걸려 `days` 가 줄었으면 구간을 그대로
        # 넘기면 안 된다 — 상한을 무력화하게 된다. 그때만 예전 경로를 쓴다.
        _capped = days >= _max
        rows = client.get_daily_ohlcv(
            ticker, days=days,
            start_date=None if _capped else start_date,
            end_date=None if _capped else end_date)
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


class OhlcvStoreError(Exception):
    """가격 저장소(DB) 접근 실패 — '적재된 적 없음'과 구분해야 하는 일시적 오류.

    ★없음과 못 읽음은 다르다★ 이 경로는 예외를 전부 삼켜 **빈 프레임**을 돌려줬고,
    그래서 DB 장애와 "이 종목은 적재된 적이 없다" 가 같은 답이 됐다. 상류가
    "실데이터 없음" 이라고 단언하는 순간 그것이 거짓일 수 있었다.

    `backtest_runs.BacktestStoreError` 와 같은 어휘다 — 새 규약을 만들지 않는다.
    """


def _db_ohlcv_df(ticker: str, start_date: str, end_date: str, strict: bool = False):
    """PostgreSQL daily_prices → DataFrame. 비어있으면 빈 df.

    strict=False(기본, 기존 호출부 보호): DB 오류를 빈 프레임으로 삼킴.
    strict=True: `OhlcvStoreError` 로 올려 '적재 없음'과 구분.
    """
    try:
        from src.kis_backtest_engine import load_ohlcv
        return load_ohlcv(ticker, start_date, end_date)
    except Exception as e:
        if strict:
            raise OhlcvStoreError(str(e)) from e
        import pandas as pd
        return pd.DataFrame()


#: 요청 구간의 양 끝에서 이만큼(달력일)까지는 "덮은 것" 으로 본다.
#: 거래일이 아닌 날(주말·공휴일·상장 전)로 시작·종료하는 요청이 흔하고, 종목마다
#: 상장일이 다르다 — 하루 어긋났다고 KIS 를 다시 부르면 콜만 태운다.
_COVERAGE_SLACK_DAYS = 10


def _coverage(df, start_date: str, end_date: str) -> tuple[bool, str | None]:
    """적재분이 요청 구간을 덮는가 — (ok, 사유).

    ★예전에는 이 판정이 아예 없었다★ 채택 조건이 `len(df) >= 20` **행 개수뿐**
    이라, 2023–2026 을 요청했는데 DB 에 2023–2024 만 있으면 ~250행으로 통과해
    **잘린 시계열이 조용히 백테스트로 흘러갔다.**

    ★미상은 '덮었다' 가 아니다★ 판정에 필요한 것을 못 읽으면 `False` + 사유다.
    """
    import pandas as pd
    if df is None or len(df) == 0:
        return False, "적재분이 없습니다."
    try:
        lo, hi = pd.Timestamp(df.index.min()), pd.Timestamp(df.index.max())
        # 슬랙은 **안쪽으로** 준다 — 적재분이 요청 시작보다 조금 늦게 시작하거나
        # 조금 일찍 끝나는 것은 허용한다(주말·공휴일·상장일 차이).
        want_lo = pd.Timestamp(start_date) + pd.Timedelta(days=_COVERAGE_SLACK_DAYS)
        want_hi = pd.Timestamp(end_date) - pd.Timedelta(days=_COVERAGE_SLACK_DAYS)
    except (TypeError, ValueError) as e:
        return False, f"커버리지를 판정할 수 없습니다(날짜 해석 실패: {e})."
    gaps = []
    if lo > want_lo:
        gaps.append(f"시작 {lo.date()} > 요청 {start_date}")
    if hi < want_hi:
        gaps.append(f"끝 {hi.date()} < 요청 {end_date}")
    if gaps:
        return False, "적재 구간이 요청을 덮지 못합니다 — " + " · ".join(gaps)
    return True, None


def _tag(df, code: str, source: str | None = None) -> None:
    """`df.attrs` 에 **이 가격이 무엇인지** 를 붙인다 — `source`·`adj_status`·`price_basis`.

    ★`attrs` 는 **편의**이지 권위가 아니다★ pandas 연산에서 `attrs` 보존은
    보장되지 않는다(슬라이스·merge·groupby 에서 사라질 수 있다). 게이트를 세울
    때는 `price_quality.price_usage()` / `assert_prices_backtest_eligible()` 을
    **직접 호출**할 것. 이 태그는 `attrs["source"]` 와 같은 성격의 힌트다.

    ★그리고 이 함수는 숫자를 바꾸지 않는다★ 컬럼을 더하지도 빼지도 않는다 —
    전환(`close → adj_close`)은 별개 결정이다.

    ★이전 판의 이 독스트링은 *"`close` 는 그대로 원주가"* 라고 적었다 — 틀렸다.★
    `close` 가 원주가인 것은 **KRX 가 적재한 행**뿐이고, KIS 경로는 수정주가로
    요청해 받은 값을 같은 컬럼에 넣는다(`kis_client.DAILY_ADJ_PRC_FLAG`). 즉
    `close` 는 하나의 값이 아니다 — 행별 정의는 `daily_prices.price_basis` 에 있고
    `price_quality.adj_close_coverage()` 의 `basis_consistency` 가 혼합을 보고한다.

    ★그래서 `price_basis` 를 함께 싣는다★ `adj_status` 하나로는 **혼합**을 말할 수
    없다. `close` 가 원주가 행과 수정주가 행을 함께 담고 있으면 그 계열로 계산한
    수익률은 정의가 섞인 수익률이고, 조용히 넘기면 아무도 모른다.

    ★판정이 터져도 가격은 돌려준다★ 태그는 편의이지 게이트가 아니므로 실패를
    df 를 죽이는 데 쓰지 않는다 — 아는 것만 남기고 나머지는 비운다.
    """
    if df is None:
        return
    if source is not None:
        df.attrs["source"] = source
    try:
        from src.data.price_quality import adj_status_of
        df.attrs["adj_status"] = adj_status_of(code)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"adj_status 태깅 실패({code}): {e}")
    try:
        from src.data.price_quality import adj_close_coverage
        df.attrs["price_basis"] = (adj_close_coverage(tickers=[code])
                                   or {}).get("basis_consistency")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"price_basis 태깅 실패({code}): {e}")


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

    # ★명시 prefer 도 태깅한다★ 예전에는 `auto` 만, 그것도 DB/KIS 가 성공했을
    # 때만 했다. 경로마다 태깅이 다르면 그 비대칭 자체가 함정이다 — `prefer="db"`
    # 를 쓰는 소비자가 basis 라벨 없이 혼합된 `close` 를 받는다.
    if prefer == "mock":
        df = _mock_ohlcv_df(code, start_date, end_date)
        _tag(df, code, "mock")
        return df
    if prefer == "db":
        df = _db_ohlcv_df(code, start_date, end_date)
        _tag(df, code, "db")
        return df if df is not None else pd.DataFrame()
    if prefer == "kis":
        # ★빈 결과에도 출처는 말한다★ `_kis_ohlcv_df` 는 실패 시 `None` 이라
        # 여기서 빈 df 로 바꾼 **뒤에** 태깅해야 호출자가 "kis 에서 왔고 없었다"
        # 를 알 수 있다. 안 그러면 이 경로만 태그가 비어 비대칭이 남는다.
        df = _kis_ohlcv_df(code, start_date, end_date)
        if df is None:
            df = pd.DataFrame()
        _tag(df, code, "kis")
        return df

    # auto: DB → KIS → mock
    db_error = None
    try:
        df = _db_ohlcv_df(code, start_date, end_date, strict=True)
    except OhlcvStoreError as e:
        # ★없음과 못 읽음을 구분한다★ 장애면 아래 KIS 폴백은 그대로 타되,
        # 그 사실을 라벨로 남겨 "실데이터 없음" 으로 오독되지 않게 한다.
        logger.warning(f"가격 저장소 조회 실패 ({code}): {e}")
        db_error, df = str(e), None

    db_ok = df is not None and not df.empty and len(df) >= 20
    cov_ok, cov_why = _coverage(df, start_date, end_date) if db_ok else (False, None)

    if db_ok and cov_ok:
        _tag(df, code, "db")        # 실데이터(적재 DB) — 구간을 덮는다
        df.attrs["coverage_ok"] = True
        df.attrs["coverage_reason"] = None
        if db_error:
            df.attrs["db_error"] = db_error
        return df

    # ★부분 커버면 KIS 로 보강을 시도한다★ 예전에는 묻지도 않고 잘린 채 넘겼다.
    df_kis = _kis_ohlcv_df(code, start_date, end_date)
    if db_ok and (df_kis is None or df_kis.empty):
        # 보강 실패 — 정책은 그대로(있는 데이터로 돈다) 다만 **사실을 싣는다**.
        _tag(df, code, "db")
        df.attrs["coverage_ok"] = False
        df.attrs["coverage_reason"] = cov_why
        if db_error:
            df.attrs["db_error"] = db_error
        return df

    df = df_kis
    if df is not None and not df.empty:
        # KIS 성공 시 DB 적재 (다음 백테스트 가속)
        try:
            ingest_df_to_db(code, df)
        except Exception:
            pass
        _tag(df, code, "kis")       # 실데이터(KIS 실시간)
        # ★모든 분기가 같은 키를 낸다★ 소비자가 분기마다 다른 모양을 만나면
        # "라벨이 없다" 와 "덮었다" 를 구별할 수 없다.
        _ok, _why = _coverage(df, start_date, end_date)
        df.attrs["coverage_ok"] = _ok
        df.attrs["coverage_reason"] = _why
        if db_error:
            df.attrs["db_error"] = db_error
        return df

    # 최종 fallback: mock 모드만 합성, 운영선 빈 df(정직 — 실데이터 없음)
    from src.data.mock_gate import mock_allowed
    if mock_allowed():
        logger.info(f"OHLCV mock fallback: {code} (DB/KIS 모두 미가용)")
        df = _mock_ohlcv_df(code, start_date, end_date)
        _tag(df, code, "mock")
        df.attrs["coverage_ok"] = False
        df.attrs["coverage_reason"] = "합성 데이터입니다(실데이터 아님)."
        if db_error:
            df.attrs["db_error"] = db_error
        return df
    logger.info(f"OHLCV 미가용(실데이터 없음, 합성 금지): {code}")
    empty = pd.DataFrame()
    empty.attrs["coverage_ok"] = False
    empty.attrs["coverage_reason"] = "실데이터가 없습니다(합성 금지)."
    if db_error:
        empty.attrs["db_error"] = db_error
    return empty


#: ★스키마 확인은 프로세스당 1회면 된다★
#: `ensure_table` 은 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` × 4 를
#: **각각 별도 트랜잭션**으로 실행한다(`krx_ingest._MIGRATE_COLUMNS`). 그것을 종목마다
#: 부르면 콜드 200종목에 **1,000 트랜잭션**이 순수 낭비다(Postgres 는 실패한 ALTER 가
#: 트랜잭션을 어보트시켜 롤백까지 돈다).
#: 관용구는 새로 만들지 않는다 — `backtest_runs._inited`·`execution_store._inited` 등
#: 이 저장소의 스토어 6곳이 이미 쓰는 모양 그대로다.
_schema_inited = False


def _ensure_daily_prices_schema(engine) -> None:
    global _schema_inited
    if _schema_inited:
        return
    try:
        from src.data.krx_ingest import ensure_table
        ensure_table(engine)
        _schema_inited = True
    except Exception as e:  # noqa: BLE001
        # ★성공했을 때만 플래그를 세운다★ 실패를 기억하면 이후 write-back 이 전부
        # 스키마 없이 돌아 조용히 실패한다.
        logger.warning(f"daily_prices 스키마 확인 실패: {e}")


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
    _ensure_daily_prices_schema(engine)

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
    # ★가격 정의를 함께 적는다★ 이 경로가 넣는 `close` 는 KRX 가 넣는 `close` 와
    # **다른 값**이다(KIS 는 수정주가로 요청, KRX 는 원주가). 컬럼 하나에 두 정의가
    # 섞이면 소스 경계에서 계열이 점프하는데, 행에 정의가 없으면 그 사실을 잴 수 없다.
    #
    # ★`DAILY_PRICE_BASIS` 는 `kis_client` 에서 읽는다★ 여기에 `"adjusted"` 를 베껴
    # 적으면, 누가 `FID_ORG_ADJ_PRC` 를 뒤집었을 때 DB 는 조용히 거짓을 적게 된다.
    from src.data.krx_ingest import SOURCE_KIS
    from src.execution.kis_client import DAILY_PRICE_BASIS
    upsert = text("""
        INSERT INTO daily_prices (ticker, trade_date, "open", high, low, close, volume,
                                  source, price_basis)
        VALUES (:ticker, :trade_date, :open, :high, :low, :close, :volume, :source,
                :price_basis)
        ON CONFLICT (ticker, trade_date) DO UPDATE
          SET "open"=EXCLUDED."open", high=EXCLUDED.high, low=EXCLUDED.low,
              close=EXCLUDED.close, volume=EXCLUDED.volume, source=EXCLUDED.source,
              price_basis=EXCLUDED.price_basis
    """)
    for r in rows:
        r["source"] = SOURCE_KIS
        r["price_basis"] = DAILY_PRICE_BASIS
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
