"""
Persistent Factor Snapshot (DB) — 한국 펀더멘털·가격 팩터 영속 캐시
==========================================================================
문제: DART/KIS를 요청마다 종목별로 호출 → 느리고(throttle) 첫 화면이 수십 초,
      재시작하면 다시 처음부터. 디스크 캐시(dart_cache)는 원천 응답만 보관.

해결: 계산된 팩터(종목당 ~92개)를 DB 테이블에 적재(JSON) → 스크리너·분석이
      DB에서 한 번에 읽음(벌크). 야간 배치가 전 유니버스를 미리 채운다.
      → 사용자는 항상 워밍된 데이터를 즉시 읽고, 재시작·다중 워커에도 유지.

설계:
  · 테이블 factor_snapshot(cache_key, value(JSON), updated_at) — PK=cache_key.
  · 이식성: ON CONFLICT UPSERT (SQLite 3.24+/PostgreSQL 9.5+ 공통).
  · 모든 DB 연산은 방어적(try/except) — DB가 없거나 실패해도 앱은 in-memory로 동작.
  · enabled(): 실데이터 모드(DART 키 or KIS 실연동)에서만 켜짐 → mock/테스트는
    in-memory만 사용(DB 미오염, 테스트 무영향).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "factor_snapshot"
_inited = False


def enabled() -> bool:
    """영속 캐시 사용 여부. 명시 토글 > 실데이터 모드 자동감지."""
    flag = os.getenv("SNAPSHOT_DB", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    # auto: 실데이터 모드일 때만 (DART 키 또는 KIS 실연동)
    return bool(os.getenv("DART_API_KEY")) or os.getenv("KIS_USE_MOCK", "1").strip() == "0"


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure_table(engine) -> None:
    global _inited
    if _inited:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "cache_key VARCHAR(80) PRIMARY KEY, "
            "value TEXT, "
            "updated_at DOUBLE PRECISION)"
        ))
    _inited = True


def bulk_read(keys: list[str], max_age_sec: float) -> dict[str, Any]:
    """여러 키를 한 번에 조회 (스크리너 벌크). 신선한 항목만 {key: value}."""
    if not keys:
        return {}
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        out: dict[str, Any] = {}
        cutoff = time.time() - max_age_sec
        with engine.connect() as c:
            for i in range(0, len(keys), 400):  # IN 절 길이 제한 회피
                chunk = keys[i:i + 400]
                ph = ",".join(f":k{j}" for j in range(len(chunk)))
                params: dict[str, Any] = {f"k{j}": k for j, k in enumerate(chunk)}
                params["cut"] = cutoff
                rows = c.execute(text(
                    f"SELECT cache_key, value FROM {_TABLE} "
                    f"WHERE updated_at >= :cut AND cache_key IN ({ph})"
                ), params)
                for k, v in rows:
                    try:
                        out[k] = json.loads(v)
                    except Exception:
                        pass
        return out
    except Exception as e:
        logger.warning(f"snapshot bulk_read 실패: {e}")
        return {}


def write_many(items: dict[str, Any]) -> int:
    """여러 (key→value)를 UPSERT (배치 적재용)."""
    if not items:
        return 0
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        now = time.time()
        sql = text(
            f"INSERT INTO {_TABLE} (cache_key, value, updated_at) VALUES (:k, :v, :t) "
            "ON CONFLICT (cache_key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
        )
        rows = [{"k": k, "v": json.dumps(v, ensure_ascii=False), "t": now} for k, v in items.items()]
        with engine.begin() as c:
            for i in range(0, len(rows), 200):
                c.execute(sql, rows[i:i + 200])
        return len(rows)
    except Exception as e:
        logger.warning(f"snapshot write_many 실패: {e}")
        return 0


def write(key: str, value: Any) -> None:
    """단건 write-through."""
    write_many({key: value})


def count() -> int:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            return int(c.execute(text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar() or 0)
    except Exception:
        return 0


def sample_factors(limit: int = 500) -> list[dict]:
    """factor_snapshot에서 종목별 팩터(펀더멘털+가격) 표본을 병합해 반환.
    기업분석 퍼센타일 계산의 분포로 사용 — 라이브 130종목 재계산 대신 DB에서 즉시.
    적재된 게 없으면 빈 리스트(호출측이 라이브 폴백)."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        merged: dict[str, dict] = {}
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT cache_key, value FROM {_TABLE} "
                "WHERE cache_key LIKE 'ffl:%' OR cache_key LIKE 'price_factors:%' "
                "LIMIT :lim"
            ), {"lim": limit * 2})
            for k, v in rows:
                try:
                    code = k.split(":", 1)[1]
                    d = merged.setdefault(code, {"stock_code": code})
                    payload = json.loads(v)
                    for fk, fv in payload.items():
                        if not fk.startswith("_"):
                            d[fk] = fv
                except Exception:
                    pass
        return list(merged.values())[:limit]
    except Exception as e:
        logger.warning(f"sample_factors 실패: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Batch ingestion — 전 유니버스 팩터를 DB에 적재
# ═══════════════════════════════════════════════════════════════════════════════

def ingest_universe(universe: str = "kospi200") -> dict:
    """유니버스 종목의 펀더멘털+가격 팩터를 계산해 DB에 적재.
    실데이터 모드면 DART/KIS 실호출(throttle·디스크캐시) → DB write-through.
    스토어의 get_factors가 PERSIST로 자동 write하므로 호출만 하면 적재됨."""
    from src.data.fundamentals_store import FundamentalsStore
    from src.data.price_factors_store import PriceFactorsStore
    from src.engine.screener import resolve_universe

    codes = resolve_universe(universe)
    fstore = FundamentalsStore.get_default()
    pstore = PriceFactorsStore.get_default()
    ok = 0
    for code in codes:
        try:
            fstore.get_factors(code)
            pstore.get_factors(code)
            ok += 1
        except Exception:
            pass
    result = {"universe": universe, "ingested": ok, "total": len(codes), "db_rows": count()}
    logger.info(f"factor_snapshot 적재 완료: {result}")
    return result
