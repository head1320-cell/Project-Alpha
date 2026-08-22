"""사용자 정의 시나리오 팩 영속 저장 (스펙 §5 `user-authored`, Phase 10a).

Phase 9 는 인라인 실행만 배달했다 — 요청에 팩 정의를 실어 보내면 돌아가지만 저장되지 않아,
같은 충격을 다시 쓰려면 매번 다시 적어야 했고 런에 적힌 팩 신원이 **어디에도 존재하지 않는**
상태가 될 수 있었다. 이 모듈이 그 구멍을 메운다.

`timing_rules.py` 의 idiom 을 **그대로** 따른다(방어적 raw-SQL · `_TABLE`+`_VTABLE` ·
후행 `version` 열 + 실패 시 버전 기능만 끄기 · `_row` 위치 매핑). 베끼는 것이 의도다 —
"DB 가 degraded 여도 죽지 않는다" 는 이 저장소의 관례이고, 여기서 새로 발명하면 장애 모드가
하나 더 늘어난다.

★신원은 두 축이다★
- `version` (정수) — 개정 **순서**. 어느 것이 나중인지 말한다.
- `content_hash` — 충격 **정의**. 무엇이 바뀌었는지 말한다.
둘 중 하나로는 부족하다. 버전만 있으면 "v3 과 v4 가 실제로 다른가" 를 알 수 없고, 해시만
있으면 순서를 알 수 없다. `timing_rule_sets`(버전)와 `scenario_packs`(해시)의 선례를 둘 다 잇는다.

★`market_shock` 이라는 이름을 쓴다★
`timing_rule_sets.market` 은 "kr"/"us" 이지만 시나리오 팩의 `market` 은 **시장 기본충격(%)**
이다. 같은 이름을 두 테이블에 두면 조인하거나 훑어보는 사람이 반드시 한 번은 헷갈린다.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "scenario_packs"
#: 버전별 **내용**을 불변으로 보관하는 동반 테이블.
_VTABLE = "scenario_pack_versions"
_inited = False

# ★version 은 반드시 맨 끝★ — 중간에 넣으면 _row 의 위치 인덱스가 전부 밀린다.
_BASE_COLS = ("pack_id, created_at, updated_at, label, description, "
              "market_shock, factors, assumptions, notes, content_hash")

# version 은 후행 추가 열이다. ALTER 성공 여부를 확인하고, 실패하면 버전 기능만 끈다
# (무조건 SELECT 하면 팩 조회 전체가 깨져서 수정 전보다 나빠진다).
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
            "pack_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION, "
            "label TEXT, description TEXT, market_shock DOUBLE PRECISION, "
            "factors TEXT, assumptions TEXT, notes TEXT, content_hash VARCHAR(16))"
        ))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_sp_created ON {_TABLE} (created_at)"))
        # 버전 이력 — (pack_id, version) 이 키. 한 번 쓰인 행은 갱신하지 않는다.
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_VTABLE} ("
            "pack_id VARCHAR(40), version INTEGER, created_at DOUBLE PRECISION, "
            "label TEXT, description TEXT, market_shock DOUBLE PRECISION, "
            "factors TEXT, assumptions TEXT, notes TEXT, content_hash VARCHAR(16), "
            "PRIMARY KEY (pack_id, version))"
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
        logger.warning(f"scenario_packs.version 사용 불가 — 버전 없이 동작: {e}")
    _inited = True


def _j(v, dflt):
    try:
        return json.loads(v) if v else dflt
    except Exception:
        return dflt


def _row(r) -> dict[str, Any]:
    out = {"pack_id": r[0], "created_at": r[1], "updated_at": r[2], "label": r[3],
           "description": r[4], "market": r[5], "factors": _j(r[6], {}),
           "assumptions": _j(r[7], {}), "notes": r[8], "content_hash": r[9]}
    # 열이 없으면 None — 모르는 값을 1 로 지어내면 런의 재현성 ID 가 거짓이 된다.
    out["version"] = (r[10] if len(r) > 10 else None) if _has_version else None
    return out


def _payload(spec: dict) -> dict:
    """저장 payload. ★`model_type` 은 여기에 없다★

    사용자 정의 팩은 **언제나** 가정 충격이다. 저장 경로에서 클라이언트 값을 받아 두면
    Phase 9 가 실행 경로에서 막은 구멍이 저장 경로로 되살아난다 — 그리고 저장된 거짓말은
    인라인 요청과 달리 계속 남는다.
    """
    from src.engine.scenario_packs import content_hash

    market = float(spec.get("market") or 0.0)
    factors = dict(spec.get("factors") or {})
    assumptions = dict(spec.get("assumptions") or {})
    return {
        "label": str(spec.get("label") or "사용자 정의 시나리오")[:200],
        "description": str(spec.get("description") or "")[:1000],
        "market_shock": market,
        "factors": json.dumps(factors, ensure_ascii=False, default=str),
        "assumptions": json.dumps(assumptions, ensure_ascii=False, default=str),
        "notes": str(spec.get("notes") or "")[:2000],
        # 등록된 팩과 **같은 함수**로 계산한다 — 두 벌이 되면 저장 팩과 코드 팩의 신원 규칙이
        # 갈라지고, 그때부터 두 해시는 비교할 수 없는 값이 된다.
        "content_hash": content_hash({"market": market, "factors": factors,
                                      "assumptions": assumptions}),
    }


def save_pack(spec: dict, pack_id: str | None = None) -> str | None:
    """팩 저장(신규) 또는 갱신(pack_id 지정). 실패 시 None — 호출자가 정직 보고.

    갱신은 **버전을 올리고 그 시점 내용을 이력 테이블에 남긴다.** 제자리 덮어쓰기만 하면
    런이 기록한 팩 버전으로 충격을 복원할 수 없어 재현성 ID 라는 이름이 무의미해진다.
    """
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        now = time.time()
        payload = _payload(spec)
        if pack_id:
            with engine.begin() as c:
                cur = c.execute(text(f"SELECT {_cols()} FROM {_TABLE} WHERE pack_id=:id"),
                                {"id": pack_id}).fetchone()
                if not cur:
                    return None     # 없는 팩을 갱신했다 — 이력도 남기지 않는다
                nxt = (_row(cur)["version"] or 1) + 1 if _has_version else None
                sql = (f"UPDATE {_TABLE} SET label=:label, description=:description, "
                       "market_shock=:market_shock, factors=:factors, "
                       "assumptions=:assumptions, notes=:notes, "
                       "content_hash=:content_hash, updated_at=:ts")
                args = {**payload, "ts": now, "id": pack_id}
                if _has_version:
                    sql += ", version=:ver"
                    args["ver"] = nxt
                res = c.execute(text(sql + " WHERE pack_id=:id"), args)
                if not res.rowcount:
                    return None
                if _has_version:
                    _write_version(c, pack_id, nxt, now, payload)
            return pack_id
        rid = f"sp_{int(now)}_{secrets.token_hex(3)}"
        with engine.begin() as c:
            if _has_version:
                c.execute(text(
                    f"INSERT INTO {_TABLE} ({_BASE_COLS}, version) VALUES "
                    "(:id, :ts, :ts, :label, :description, :market_shock, :factors, "
                    ":assumptions, :notes, :content_hash, 1)"),
                    {**payload, "id": rid, "ts": now})
                _write_version(c, rid, 1, now, payload)
            else:
                c.execute(text(
                    f"INSERT INTO {_TABLE} ({_BASE_COLS}) VALUES "
                    "(:id, :ts, :ts, :label, :description, :market_shock, :factors, "
                    ":assumptions, :notes, :content_hash)"),
                    {**payload, "id": rid, "ts": now})
        return rid
    except Exception as e:
        logger.warning(f"시나리오 팩 저장 실패: {e}")
        return None


def _write_version(c, pack_id: str, version: int, ts: float, payload: dict) -> None:
    """이력 1행 기록. 이력 실패가 저장 자체를 막지는 않는다(팩은 이미 유효하다)."""
    from sqlalchemy import text
    try:
        c.execute(text(
            f"INSERT INTO {_VTABLE} (pack_id, version, created_at, label, description, "
            "market_shock, factors, assumptions, notes, content_hash) "
            "VALUES (:id, :ver, :ts, :label, :description, :market_shock, :factors, "
            ":assumptions, :notes, :content_hash)"),
            {**payload, "id": pack_id, "ver": version, "ts": ts})
    except Exception as e:
        logger.warning(f"시나리오 팩 버전 이력 기록 실패 ({pack_id} v{version}): {e}")


def get_pack(pack_id: str) -> dict | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {_cols()} FROM {_TABLE} WHERE pack_id=:id"),
                          {"id": pack_id}).fetchone()
        return _row(r) if r else None
    except Exception as e:
        logger.warning(f"시나리오 팩 조회 실패: {e}")
        return None


def list_packs(limit: int = 50) -> list[dict]:
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
        logger.warning(f"시나리오 팩 목록 실패: {e}")
        return []


def list_pack_versions(pack_id: str) -> list[dict]:
    """이 팩의 버전 이력(오름차순). 해시를 함께 실어 **무엇이 바뀌었는지**도 보이게 한다."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT version, created_at, label, content_hash FROM {_VTABLE} "
                "WHERE pack_id=:id ORDER BY version ASC"), {"id": pack_id}).fetchall()
        return [{"version": r[0], "created_at": r[1], "label": r[2], "content_hash": r[3]}
                for r in rows]
    except Exception as e:
        logger.warning(f"시나리오 팩 버전 목록 실패: {e}")
        return []


def get_pack_version(pack_id: str, version: int) -> dict | None:
    """특정 버전의 **당시 내용**. 없으면 None.

    ★없는 버전에 최신본을 돌려주지 않는다★ — 조용히 다른 충격으로 런을 복원하는 것은
    복원이 아니라 위조다. 모르면 모른다고 답한다(`get_rule_set_version` 과 같은 규칙).
    """
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(
                "SELECT pack_id, version, created_at, label, description, market_shock, "
                f"factors, assumptions, notes, content_hash FROM {_VTABLE} "
                "WHERE pack_id=:id AND version=:ver"),
                {"id": pack_id, "ver": int(version)}).fetchone()
        if not r:
            return None
        return {"pack_id": r[0], "version": r[1], "created_at": r[2], "label": r[3],
                "description": r[4], "market": r[5], "factors": _j(r[6], {}),
                "assumptions": _j(r[7], {}), "notes": r[8], "content_hash": r[9]}
    except Exception as e:
        logger.warning(f"시나리오 팩 버전 조회 실패: {e}")
        return None


def delete_pack(pack_id: str) -> bool:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE pack_id=:id"), {"id": pack_id})
            # 이력도 함께 — 고아 이력이 남으면 삭제가 삭제가 아니고, 같은 pack_id 가
            # 재발급될 경우 남의 과거 버전을 자기 이력으로 물려받는다.
            c.execute(text(f"DELETE FROM {_VTABLE} WHERE pack_id=:id"), {"id": pack_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"시나리오 팩 삭제 실패: {e}")
        return False
