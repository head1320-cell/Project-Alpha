"""ResearchRun 영속 저장 — 연구 결과의 재현성 단위 (Full Expansion Directive P1)
==============================================================================
"단순히 포트폴리오가 아니라 연구 실행(run)을 저장한다": 모든 중요한 결과가
run_id · 입력 파라미터 · 데이터 스냅샷 요약 · 코드 버전 · 생성 시각을 보존해
나중에 재조회·비교·재실행할 수 있게 한다.

설계 (기존 관례 재사용):
  · 테이블 research_runs — snapshot_db와 동일한 방어적 raw-SQL idiom.
    DB 미가용 시 조용히 실패(None/빈 목록) — 앱은 계속 동작(정직 보고는 API가).
  · inputs/outputs/snapshot 은 JSON 직렬화 TEXT. outputs 는 "재계산 가능한 큰
    산출물(프론티어 클라우드·MC bins)"을 제외한 요약만 저장 — 재현은 inputs 재실행으로.
  · run_id = "rr_" + 시각 + 난수 hex (충돌 무시 가능 수준).
  · code_version: GIT_SHA > APP_VERSION 환경변수 > "dev" (정직 — 서버가 스탬프).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "research_runs"
_inited = False

# run 종류 (자유 문자열이지만 표준 값을 상수로 — 프론트와 계약)
KIND_ANALYZE = "allocation_analyze"
KIND_FACTOR = "factor_portfolio"
KIND_TIMING = "timing"
KIND_STRESS = "stress"


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
            "run_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, "
            "kind VARCHAR(40), "
            "name TEXT, "
            "inputs TEXT, "
            "outputs TEXT, "
            "snapshot TEXT, "
            "code_version VARCHAR(60), "
            "parent_run_id VARCHAR(40), "
            "note TEXT)"
        ))
        c.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_rr_kind_created ON {_TABLE} (kind, created_at)"
        ))
    _inited = True


def code_version() -> str:
    return os.getenv("GIT_SHA") or os.getenv("APP_VERSION") or "dev"


def _new_run_id() -> str:
    return f"rr_{int(time.time())}_{secrets.token_hex(4)}"


def record_run(kind: str, inputs: dict[str, Any], outputs: dict[str, Any],
               snapshot: dict[str, Any] | None = None, name: str | None = None,
               parent_run_id: str | None = None, note: str | None = None) -> str | None:
    """연구 실행을 영속화. 성공 시 run_id, DB 미가용 시 None (호출자가 정직 보고)."""
    rid = _new_run_id()
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} (run_id, created_at, kind, name, inputs, outputs, "
                "snapshot, code_version, parent_run_id, note) "
                "VALUES (:rid, :ts, :kind, :name, :inp, :out, :snap, :ver, :parent, :note)"
            ), {
                "rid": rid, "ts": time.time(), "kind": kind, "name": name,
                "inp": json.dumps(inputs, ensure_ascii=False, default=str),
                "out": json.dumps(outputs, ensure_ascii=False, default=str),
                "snap": json.dumps(snapshot or {}, ensure_ascii=False, default=str),
                "ver": code_version(), "parent": parent_run_id, "note": note,
            })
        return rid
    except Exception as e:
        logger.warning(f"research run 기록 실패: {e}")
        return None


def _row_to_dict(row, full: bool) -> dict[str, Any]:
    d = {
        "run_id": row[0], "created_at": row[1], "kind": row[2], "name": row[3],
        "code_version": row[7], "parent_run_id": row[8], "note": row[9],
    }
    try:
        d["snapshot"] = json.loads(row[6]) if row[6] else {}
    except Exception:
        d["snapshot"] = {}
    if full:
        for key, idx in (("inputs", 4), ("outputs", 5)):
            try:
                d[key] = json.loads(row[idx]) if row[idx] else {}
            except Exception:
                d[key] = {}
    return d


def get_run(run_id: str) -> dict[str, Any] | None:
    """단건 전체 조회 (inputs/outputs 포함)."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            row = c.execute(text(
                f"SELECT run_id, created_at, kind, name, inputs, outputs, snapshot, "
                f"code_version, parent_run_id, note FROM {_TABLE} WHERE run_id = :rid"
            ), {"rid": run_id}).fetchone()
        return _row_to_dict(row, full=True) if row else None
    except Exception as e:
        logger.warning(f"research run 조회 실패: {e}")
        return None


def list_runs(kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """목록 (요약 — inputs/outputs 제외, snapshot 포함). 최신순."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        q = (f"SELECT run_id, created_at, kind, name, inputs, outputs, snapshot, "
             f"code_version, parent_run_id, note FROM {_TABLE} ")
        params: dict[str, Any] = {"lim": max(1, min(int(limit), 200))}
        if kind:
            q += "WHERE kind = :kind "
            params["kind"] = kind
        q += "ORDER BY created_at DESC LIMIT :lim"
        with engine.connect() as c:
            rows = c.execute(text(q), params).fetchall()
        return [_row_to_dict(r, full=False) for r in rows]
    except Exception as e:
        logger.warning(f"research run 목록 실패: {e}")
        return []


def delete_run(run_id: str) -> bool:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE run_id = :rid"), {"rid": run_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"research run 삭제 실패: {e}")
        return False
