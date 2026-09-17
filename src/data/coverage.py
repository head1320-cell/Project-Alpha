"""적재 커버리지 — ★"적재됐다" 와 "충분히 적재됐다" 는 다르다★

`db-status` 는 테이블별 **전체 행 수**만 낸다. 그래서 `1종목 × 40행` 과
`2,700종목 × 40행` 이 같은 종류의 사실로 보인다. 정작 물어야 하는 것은
**"내 유니버스의 몇 %가 내 백테스트 기간을 덮는가"** 이고, 그것이 "백테스트가 왜
빈약한가" 에 답한다.

★무겁다 — 그래서 온디맨드다★ `daily_prices` 는 수백만 행이다. 기존 코드가 종목
수를 `pg_stats` 추정치로 쓰는 이유가 그것이다(`data_routes.py`, 미확정은 `None` —
"0 금지"). 그 규율을 그대로 따른다:

  · 탭을 여는 것만으로는 돌지 않는다 — 호출해야 집계한다
  · 결과는 TTL 캐시(질문마다 별도 항목 — 기간이 다르면 답도 다르다)
  · ★못 재면 `None` + 사유★ `0종목` 은 "재봤더니 없다" 는 하지 않은 진술이다
"""
from __future__ import annotations

import logging
import time
from typing import Any

from src.data.ingest_registry import get as _dataset

logger = logging.getLogger(__name__)

#: 커버리지 판정 — 적재분이 요청 구간의 양 끝을 이만큼(달력일) 안쪽까지 덮으면 OK.
#: `ohlcv_loader._COVERAGE_SLACK_DAYS` 와 같은 취지다(주말·공휴일·상장일 차이).
_SLACK_DAYS = 10

_TTL_SEC = 600.0
_cache: dict[tuple, tuple[float, dict]] = {}

#: 종목 축이 있는 데이터셋만 종목별 커버리지를 낼 수 있다. 매크로는 시계열이라
#: 종목 개념이 없다 — 거기에 종목 수를 지어내면 안 된다.
_TICKER_COLUMN = {
    "daily_prices": "ticker",
    "factor_snapshot": "stock_code",
    "financials_history": "ticker",
    "investor_flows": "ticker",
    "instrument_master": "ticker",
}


def clear_cache() -> None:
    _cache.clear()


def _engine():
    from src.database import get_engine
    return get_engine()


def _count_coverage(table: str, col: str, start: str, end: str,
                    where: str | None) -> tuple[int, int]:
    """(전체 종목 수, 구간을 덮는 종목 수) — 실측."""
    import datetime as _dt

    from sqlalchemy import text

    def _shift(d: str, days: int) -> str:
        return (_dt.date.fromisoformat(d) + _dt.timedelta(days=days)).isoformat()

    extra = f" AND ({where})" if where else ""
    sql = text(
        f"SELECT COUNT(*) FROM ("  # noqa: S608 — table/col 은 레지스트리 화이트리스트
        f"  SELECT {col} AS tk, MIN(trade_date) AS lo, MAX(trade_date) AS hi"
        f"  FROM {table} WHERE 1=1{extra} GROUP BY {col}) s")
    sql_cov = text(
        f"SELECT COUNT(*) FROM ("  # noqa: S608
        f"  SELECT {col} AS tk, MIN(trade_date) AS lo, MAX(trade_date) AS hi"
        f"  FROM {table} WHERE 1=1{extra} GROUP BY {col}) s"
        f" WHERE s.lo <= :lo AND s.hi >= :hi")
    with _engine().connect() as c:
        total = int(c.execute(sql).scalar() or 0)
        covering = int(c.execute(sql_cov, {"lo": _shift(start, _SLACK_DAYS),
                                           "hi": _shift(end, -_SLACK_DAYS)}).scalar() or 0)
    return total, covering


def ticker_coverage(key: str, *, start: str, end: str) -> dict[str, Any]:
    """`key` 데이터셋에서 `start~end` 를 덮는 종목이 몇 개인가.

    ★모르는 키는 거절한다★ — 레지스트리에 없으면 `KeyError`.
    """
    d = _dataset(key)                       # 등록되지 않은 대상이면 여기서 KeyError
    ck = (key, start, end)
    hit = _cache.get(ck)
    if hit and (time.time() - hit[0]) < _TTL_SEC:
        return hit[1]

    base = {"key": key, "label": d.label, "table": d.table,
            "start": start, "end": end,
            "tickers_total": None, "tickers_covering": None,
            "measured": False, "reason": None}

    col = _TICKER_COLUMN.get(d.table)
    if col is None:
        base["reason"] = (
            f"{d.label} 은 종목 축이 없는 데이터셋입니다(시계열). "
            "종목별 커버리지를 낼 수 없습니다.")
        _cache[ck] = (time.time(), base)
        return base

    try:
        total, covering = _count_coverage(d.table, col, start, end, d.slice_sql)
    except Exception as e:  # noqa: BLE001
        # ★0 이 아니라 미상이다★ "재봤더니 없다" 는 하지 않은 진술이다.
        logger.warning(f"커버리지 집계 실패 [{key}]: {e}")
        base["reason"] = f"커버리지를 집계할 수 없습니다: {e}"
        return base                          # 실패는 캐시하지 않는다 — 재시도 가능

    base.update(tickers_total=total, tickers_covering=covering, measured=True,
                covering_pct=(round(covering / total * 100, 1) if total else None))
    _cache[ck] = (time.time(), base)
    return base
