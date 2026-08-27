"""상장 상품 마스터 DB — ★파일 하나가 세 기능의 단일 장애점이었다★
==============================================================================
감사: [`데이터 추출 감사`](../../docs/specs/2026-08-26-data-extraction-audit.md) §3.3
관례: `krx_ingest.ensure_table` / `_get_engine` 과 같은 모양

## 왜 이 모듈이 생겼나

`kis_master_parser` 는 ISIN · 그룹코드 · 지수편입 · 업종 3단 · 상태 플래그를 충실히
뽑는다. 그런데 **산출물이 `master_flags_cache.json` 파일 하나**뿐이라, 그 파일이
없으면 아래가 **함께** 멈춘다:

    krx_mdc 투자자 플로우 백필      ← ISIN 이 조회 키
    constrained_opt.sector_groups_for ← {} 를 돌려준다(기존 결함)
    exposure_taxonomy 규칙 배정      ← no_master_flags

★이 환경이 바로 그 상태다★(실측 0건). 그래서 같은 내용을 DB 에도 둔다.

## ★파일이 진실이고, DB 는 사본이다★

읽기 순서는 **파일 → DB**다. 반대로 하면 스테일 DB 가 방금 받은 새 파일을 덮는다.
쓰기는 둘 다 시도하되 **DB 실패는 경고로 끝난다** — 파일이 성공했으면 성공이다.
그래서 파일이 있는 환경에서는 **동작이 이전과 완전히 같다.**

## 담지 않는 것

★없는 값을 만들지 않는다★ 파서가 못 뽑은 필드는 `None`/빈 문자열 그대로 저장한다.
`isin_of()` 는 없으면 `None` 이고, 그것이 "조회 키가 없다" 는 정직한 답이다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "instrument_master"
#: 이 스키마의 판본. 컬럼이 바뀌면 올린다.
MASTER_SCHEMA_VERSION = "2026.1"
#: 어디서 온 마스터인가 — 나중에 다른 출처가 생기면 구분된다.
SOURCE_KIS_MASTER = "kis_master"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    ticker        VARCHAR(12) PRIMARY KEY,
    isin          VARCHAR(12),
    name          TEXT,
    market        VARCHAR(8),
    group_code    VARCHAR(4),
    is_etf        BOOLEAN,
    is_kospi200   BOOLEAN,
    is_kosdaq150  BOOLEAN,
    cap_size      VARCHAR(8),
    sector_code   VARCHAR(8),
    sector_mid    VARCHAR(8),
    sector_sub    VARCHAR(8),
    is_managed    BOOLEAN,
    alert_code    VARCHAR(4),
    is_halted     BOOLEAN,
    market_cap    FLOAT,
    as_of         TEXT,
    source        VARCHAR(16)
)
"""

_UPSERT = f"""
INSERT INTO {TABLE}
    (ticker, isin, name, market, group_code, is_etf, is_kospi200, is_kosdaq150,
     cap_size, sector_code, sector_mid, sector_sub, is_managed, alert_code,
     is_halted, market_cap, as_of, source)
VALUES
    (:ticker, :isin, :name, :market, :group_code, :is_etf, :is_kospi200,
     :is_kosdaq150, :cap_size, :sector_code, :sector_mid, :sector_sub,
     :is_managed, :alert_code, :is_halted, :market_cap, :as_of, :source)
ON CONFLICT (ticker) DO UPDATE SET
    isin=EXCLUDED.isin, name=EXCLUDED.name, market=EXCLUDED.market,
    group_code=EXCLUDED.group_code, is_etf=EXCLUDED.is_etf,
    is_kospi200=EXCLUDED.is_kospi200, is_kosdaq150=EXCLUDED.is_kosdaq150,
    cap_size=EXCLUDED.cap_size, sector_code=EXCLUDED.sector_code,
    sector_mid=EXCLUDED.sector_mid, sector_sub=EXCLUDED.sector_sub,
    is_managed=EXCLUDED.is_managed, alert_code=EXCLUDED.alert_code,
    is_halted=EXCLUDED.is_halted, market_cap=EXCLUDED.market_cap,
    as_of=EXCLUDED.as_of, source=EXCLUDED.source
"""

#: 파일 캐시(`stock_master.save_master_flags`)의 필드 → 컬럼. 순서가 계약이다.
_FIELDS = ("isin", "name", "market", "group_code", "is_etf", "is_kospi200",
           "is_kosdaq150", "cap_size", "sector_code", "sector_mid", "sector_sub",
           "is_managed", "alert_code", "is_halted")

_CHUNK = 500


def _engine(engine=None):
    if engine is not None:
        return engine
    try:
        from src.database import get_engine
        return get_engine()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"엔진을 얻지 못했습니다: {e}")
        return None


def ensure_table(engine=None) -> bool:
    """테이블 보장. 성공 여부를 돌려준다(예외를 위로 던지지 않는다)."""
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None:
        return False
    try:
        with eng.begin() as conn:
            conn.execute(text(_DDL))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{TABLE} 생성 실패: {e}")
        return False


def save(flags: dict[str, dict], *, as_of: str | None = None, engine=None) -> int:
    """`{ticker: flags}` → DB. 저장 행 수. ★실패해도 예외를 던지지 않는다★

    호출자(`stock_master.save_master_flags`)에게 파일이 진실이므로, DB 실패가
    마스터 갱신 전체를 실패로 만들면 안 된다.
    """
    from sqlalchemy import text
    if not flags:
        return 0
    eng = _engine(engine)
    if eng is None or not ensure_table(eng):
        return 0

    stamp = as_of or _today()
    payload = []
    for ticker, f in flags.items():
        row: dict[str, Any] = {"ticker": str(ticker), "as_of": stamp,
                               "source": SOURCE_KIS_MASTER}
        for k in _FIELDS:
            row[k] = f.get(k)
        # 파일 캐시는 `market_cap_억` 이라는 이름을 쓴다 — 컬럼명과 다르다.
        row["market_cap"] = f.get("market_cap_억")
        payload.append(row)

    try:
        stmt = text(_UPSERT)
        with eng.begin() as conn:
            for i in range(0, len(payload), _CHUNK):
                conn.execute(stmt, payload[i:i + _CHUNK])
        return len(payload)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{TABLE} 적재 실패: {e}")
        return 0


def load(engine=None) -> dict[str, dict]:
    """DB → `{ticker: flags}`. ★파일 캐시와 **같은 모양**으로 돌려준다★

    모양이 다르면 소비자가 두 갈래 코드를 갖게 되고, 그중 하나만 고쳐지는 날이 온다.
    """
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None:
        return {}
    cols = ", ".join(("ticker", *_FIELDS, "market_cap"))
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(f"SELECT {cols} FROM {TABLE}")).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{TABLE} 조회 실패: {e}")
        return {}

    out: dict[str, dict] = {}
    for r in rows:
        ticker = str(r[0])
        f = dict(zip(_FIELDS, r[1:1 + len(_FIELDS)], strict=True))
        for b in ("is_etf", "is_kospi200", "is_kosdaq150", "is_managed", "is_halted"):
            f[b] = bool(f[b])           # sqlite 는 0/1 로 돌려준다
        f["market_cap_억"] = r[1 + len(_FIELDS)]
        out[ticker] = f
    return out


def isin_of(ticker: str, engine=None) -> str | None:
    """티커 → ISIN. ★없으면 `None` — 합성하지 않는다★

    `krx_mdc` 의 조회 키다. 가짜 ISIN 을 만들면 조회가 조용히 빈 결과를 낸다.
    """
    from src.data.stock_master import load_master_flags
    f = (load_master_flags() or {}).get(str(ticker))
    isin = (f or {}).get("isin")
    return isin if isin else None


def _today() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")
