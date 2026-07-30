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
#: 버전별 **내용**을 불변으로 보관하는 동반 테이블 (Phase 7).
_VTABLE = "timing_rule_set_versions"
_inited = False

# ★version 은 반드시 맨 끝★ — 중간에 넣으면 _row 의 위치 인덱스가 전부 밀린다.
_BASE_COLS = "set_id, created_at, updated_at, name, market, rules, gate, notes"

# version 은 후행 추가 열이다. ALTER 성공 여부를 확인하고, 실패하면 버전 기능만 끈다
# (무조건 SELECT 하면 규칙 세트 조회 전체가 깨져서 수정 전보다 나빠진다).
# backtest_runs.py:104~122 가 heartbeat_at 에 대해 같은 이유로 쓰는 패턴을 따른다.
_has_version = False


def _cols() -> str:
    return f"{_BASE_COLS}, version" if _has_version else _BASE_COLS


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure(engine) -> None:
    global _inited, _has_version
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
        # 버전 이력 — (set_id, version) 이 키. 한 번 쓰인 행은 갱신하지 않는다.
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_VTABLE} ("
            "set_id VARCHAR(40), version INTEGER, created_at DOUBLE PRECISION, "
            "name TEXT, market VARCHAR(8), rules TEXT, gate TEXT, notes TEXT, "
            "PRIMARY KEY (set_id, version))"
        ))
    # SQLite 는 ADD COLUMN IF NOT EXISTS 가 없어 "이미 있음" 도 예외로 온다 → 삼킨다.
    try:
        with engine.begin() as c:
            c.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN version INTEGER"))
    except Exception:
        pass
    try:
        with engine.connect() as c:
            c.execute(text(f"SELECT version FROM {_TABLE} LIMIT 1"))
        _has_version = True
    except Exception as e:
        _has_version = False
        logger.warning(f"timing_rule_sets.version 사용 불가 — 버전 없이 동작: {e}")
    _inited = True


def _j(v, dflt):
    try:
        return json.loads(v) if v else dflt
    except Exception:
        return dflt


def _row(r) -> dict[str, Any]:
    out = {"set_id": r[0], "created_at": r[1], "updated_at": r[2], "name": r[3],
           "market": r[4], "rules": _j(r[5], []), "gate": _j(r[6], {}), "notes": r[7]}
    # 열이 없으면 None — 모르는 값을 1 로 지어내면 런의 재현성 ID 가 거짓이 된다.
    out["version"] = (r[8] if len(r) > 8 else None) if _has_version else None
    return out


def save_rule_set(name: str, market: str, rules: list[dict],
                  gate: dict | None = None, notes: str | None = None,
                  set_id: str | None = None) -> str | None:
    """규칙 세트 저장(신규) 또는 갱신(set_id 지정). 실패 시 None — 호출자가 정직 보고.

    갱신은 **버전을 올리고 그 시점 내용을 이력 테이블에 남긴다.** 제자리에서 덮어쓰기만 하면
    런이 기록한 rule version 으로 규칙을 복원할 수 없어 재현성 ID 라는 이름이 무의미해진다.
    """
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
                cur = c.execute(text(f"SELECT {_cols()} FROM {_TABLE} WHERE set_id=:id"),
                                {"id": set_id}).fetchone()
                if not cur:
                    return None     # 없는 세트를 갱신했다 — 이력도 남기지 않는다
                nxt = (_row(cur)["version"] or 1) + 1 if _has_version else None
                sql = (f"UPDATE {_TABLE} SET name=:name, market=:market, rules=:rules, "
                       "gate=:gate, notes=:notes, updated_at=:ts")
                args = {**payload, "ts": now, "id": set_id}
                if _has_version:
                    sql += ", version=:ver"
                    args["ver"] = nxt
                res = c.execute(text(sql + " WHERE set_id=:id"), args)
                if not res.rowcount:
                    return None
                if _has_version:
                    _write_version(c, set_id, nxt, now, payload)
            return set_id
        rid = f"tr_{int(now)}_{secrets.token_hex(3)}"
        with engine.begin() as c:
            if _has_version:
                c.execute(text(
                    f"INSERT INTO {_TABLE} ({_BASE_COLS}, version) VALUES "
                    "(:id, :ts, :ts, :name, :market, :rules, :gate, :notes, 1)"),
                    {**payload, "id": rid, "ts": now})
                _write_version(c, rid, 1, now, payload)
            else:
                c.execute(text(
                    f"INSERT INTO {_TABLE} ({_BASE_COLS}) VALUES "
                    "(:id, :ts, :ts, :name, :market, :rules, :gate, :notes)"),
                    {**payload, "id": rid, "ts": now})
        return rid
    except Exception as e:
        logger.warning(f"timing rule set 저장 실패: {e}")
        return None


def _write_version(c, set_id: str, version: int, ts: float, payload: dict) -> None:
    """이력 1행 기록. 이력 실패가 저장 자체를 막지는 않는다(세트는 이미 유효하다)."""
    from sqlalchemy import text
    try:
        c.execute(text(
            f"INSERT INTO {_VTABLE} (set_id, version, created_at, name, market, rules, gate, notes) "
            "VALUES (:id, :ver, :ts, :name, :market, :rules, :gate, :notes)"),
            {**payload, "id": set_id, "ver": version, "ts": ts})
    except Exception as e:
        logger.warning(f"timing rule set 버전 이력 기록 실패 ({set_id} v{version}): {e}")


def get_rule_set_version(set_id: str, version: int) -> dict | None:
    """특정 버전의 **당시 내용**. 없으면 None.

    ★없는 버전에 최신본을 돌려주지 않는다★ — 조용히 다른 규칙으로 런을 복원하는 것은
    복원이 아니라 위조다. 모르면 모른다고 답한다.
    """
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(
                "SELECT set_id, version, created_at, name, market, rules, gate, notes "
                f"FROM {_VTABLE} WHERE set_id=:id AND version=:ver"),
                {"id": set_id, "ver": int(version)}).fetchone()
        if not r:
            return None
        return {"set_id": r[0], "version": r[1], "created_at": r[2], "name": r[3],
                "market": r[4], "rules": _j(r[5], []), "gate": _j(r[6], {}), "notes": r[7]}
    except Exception as e:
        logger.warning(f"timing rule set 버전 조회 실패: {e}")
        return None


def list_rule_set_versions(set_id: str) -> list[dict]:
    """이 세트의 버전 이력(오름차순)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT version, created_at, name FROM {_VTABLE} "
                "WHERE set_id=:id ORDER BY version ASC"), {"id": set_id}).fetchall()
        return [{"version": r[0], "created_at": r[1], "name": r[2]} for r in rows]
    except Exception as e:
        logger.warning(f"timing rule set 버전 목록 실패: {e}")
        return []


def get_rule_set(set_id: str) -> dict | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {_cols()} FROM {_TABLE} WHERE set_id=:id"),
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
                f"SELECT {_cols()} FROM {_TABLE} ORDER BY updated_at DESC LIMIT :l"),
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
            # 이력도 함께 — 고아 이력이 남으면 삭제가 삭제가 아니고, 같은 set_id 가
            # 재발급될 경우 남의 과거 버전을 자기 이력으로 물려받는다.
            c.execute(text(f"DELETE FROM {_VTABLE} WHERE set_id=:id"), {"id": set_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"timing rule set 삭제 실패: {e}")
        return False
