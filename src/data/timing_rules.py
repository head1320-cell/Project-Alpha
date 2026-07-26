"""TimingRule 영속 저장 — 사용자가 구성한 마켓타이밍 규칙 세트.

AAS TIMING 팩터 창에서 조립한 규칙(팩터 + 실행/리스크 컨텍스트)을 저장·재사용한다.
research_runs / backtest_runs 와 동일한 방어적 raw-SQL idiom (DB 선택적, 실패 시 None/[]).

한 행 = 규칙 세트 1건: 여러 TimingRule(팩터) + 게이트 설정(브레드스·자산군·오버레이 등).
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "timing_rule_sets"
_inited = False

_COLS = "set_id, created_at, updated_at, name, market, rules, gate, notes"


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure(engine) -> None:
    global _inited
    if _inited:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "set_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION, "
            "name TEXT, market VARCHAR(8), rules TEXT, gate TEXT, notes TEXT)"
        ))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_trs_created ON {_TABLE} (created_at)"))
    _inited = True


def _row(r) -> dict[str, Any]:
    def _j(v, dflt):
        try:
            return json.loads(v) if v else dflt
        except Exception:
            return dflt
    return {"set_id": r[0], "created_at": r[1], "updated_at": r[2], "name": r[3],
            "market": r[4], "rules": _j(r[5], []), "gate": _j(r[6], {}), "notes": r[7]}


def save_rule_set(name: str, market: str, rules: list[dict],
                  gate: dict | None = None, notes: str | None = None,
                  set_id: str | None = None) -> str | None:
    """규칙 세트 저장(신규) 또는 갱신(set_id 지정). 실패 시 None — 호출자가 정직 보고."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        now = time.time()
        payload = {
            "name": name[:200], "market": market,
            "rules": json.dumps(rules, ensure_ascii=False, default=str),
            "gate": json.dumps(gate or {}, ensure_ascii=False, default=str),
            "notes": (notes or "")[:2000],
        }
        if set_id:
            with engine.begin() as c:
                res = c.execute(text(
                    f"UPDATE {_TABLE} SET name=:name, market=:market, rules=:rules, "
                    "gate=:gate, notes=:notes, updated_at=:ts WHERE set_id=:id"),
                    {**payload, "ts": now, "id": set_id})
            return set_id if res.rowcount else None
        rid = f"tr_{int(now)}_{secrets.token_hex(3)}"
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} ({_COLS}) VALUES "
                "(:id, :ts, :ts, :name, :market, :rules, :gate, :notes)"),
                {**payload, "id": rid, "ts": now})
        return rid
    except Exception as e:
        logger.warning(f"timing rule set 저장 실패: {e}")
        return None


def get_rule_set(set_id: str) -> dict | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {_COLS} FROM {_TABLE} WHERE set_id=:id"),
                          {"id": set_id}).fetchone()
        return _row(r) if r else None
    except Exception as e:
        logger.warning(f"timing rule set 조회 실패: {e}")
        return None


def list_rule_sets(limit: int = 50) -> list[dict]:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT {_COLS} FROM {_TABLE} ORDER BY updated_at DESC LIMIT :l"),
                {"l": max(1, min(int(limit), 200))}).fetchall()
        return [_row(r) for r in rows]
    except Exception as e:
        logger.warning(f"timing rule set 목록 실패: {e}")
        return []


def delete_rule_set(set_id: str) -> bool:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE set_id=:id"), {"id": set_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"timing rule set 삭제 실패: {e}")
        return False
