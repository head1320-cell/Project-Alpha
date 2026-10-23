"""Research Journal — 의사결정 품질 데이터베이스 (Full Expansion P5)
==============================================================================
지시서: "저널은 메모장이 아니라 의사결정 품질 DB. 각 항목은 ResearchRun·알파 버전·
슬리브 버전·최적화 설정·시나리오팩·실행계획·승인자·실제 결과 및 Attribution에
연결된다." Attribution과 저널은 같은 run_id로 연결(§8 검증 항목).

필수 기록: 그 시점의 테제 · 데이터/모델 버전 · 핵심 반론 · 내린 결정 · 포지션 변경
이유 · 성공/실패 원인 · 다음 실험 · 사후 회고 · "결과는 좋았지만 결정은 나빴나 vs
결과는 나빴지만 결정은 합리적이었나" 별도 평가.

research_runs / execution_store 와 동일한 방어적 raw-SQL idiom (DB 선택적).
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "journal_entries"
_inited = False

# 의사결정 품질 자기평가 (지시서: 결과 vs 결정의 정오를 분리)
DECISION_QUALITY = ("good_outcome_good_process", "good_outcome_bad_process",
                    "bad_outcome_good_process", "bad_outcome_bad_process", "too_early")

_COLS = ("entry_id, created_at, updated_at, run_id, title, links, record, "
         "decision_quality, review, attribution")


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
            "entry_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION, "
            "run_id VARCHAR(40), title TEXT, links TEXT, record TEXT, "
            "decision_quality VARCHAR(40), review TEXT, attribution TEXT)"
        ))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_journal_run ON {_TABLE} (run_id)"))
    _inited = True


def _row(r) -> dict[str, Any]:
    d = {"entry_id": r[0], "created_at": r[1], "updated_at": r[2], "run_id": r[3],
         "title": r[4], "decision_quality": r[7], "review": r[8]}
    for key, idx in (("links", 5), ("record", 6), ("attribution", 9)):
        try:
            d[key] = json.loads(r[idx]) if r[idx] else ({} if key != "attribution" else None)
        except Exception:
            d[key] = {} if key != "attribution" else None
    return d


def create_entry(title: str, run_id: str | None = None, links: dict | None = None,
                 record: dict | None = None, decision_quality: str | None = None,
                 attribution: dict | None = None) -> str | None:
    """저널 항목 생성. links = {alpha_version, sleeve_version, opt_settings, scenario_pack,
    execution_plan_id, approvers, ...}. record = {thesis, data_model_versions,
    counter_arguments, decision, reason_change, cause, next_experiment, postmortem}."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        eid = f"jr_{int(time.time())}_{secrets.token_hex(4)}"
        now = time.time()
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} ({_COLS}) VALUES "
                "(:id, :ts, :ts, :rid, :ti, :lk, :rec, :dq, NULL, :attr)"),
                {"id": eid, "ts": now, "rid": run_id, "ti": title,
                 "lk": json.dumps(links or {}, ensure_ascii=False, default=str),
                 "rec": json.dumps(record or {}, ensure_ascii=False, default=str),
                 "dq": decision_quality if decision_quality in DECISION_QUALITY else None,
                 "attr": json.dumps(attribution, ensure_ascii=False, default=str) if attribution else None})
        return eid
    except Exception as e:
        logger.warning(f"journal 생성 실패: {e}")
        return None


def get_entry(entry_id: str) -> dict | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {_COLS} FROM {_TABLE} WHERE entry_id = :id"),
                          {"id": entry_id}).fetchone()
        return _row(r) if r else None
    except Exception as e:
        logger.warning(f"journal 조회 실패: {e}")
        return None


def get_by_run(run_id: str) -> dict | None:
    """run_id로 연결된 저널 항목 (Attribution ↔ Journal 연결의 핵심)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(
                f"SELECT {_COLS} FROM {_TABLE} WHERE run_id = :rid ORDER BY created_at DESC LIMIT 1"),
                {"rid": run_id}).fetchone()
        return _row(r) if r else None
    except Exception as e:
        logger.warning(f"journal run 조회 실패: {e}")
        return None


def list_entries(limit: int = 50) -> list[dict]:
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
        logger.warning(f"journal 목록 실패: {e}")
        return []


def update_review(entry_id: str, review: str | None = None,
                  decision_quality: str | None = None) -> dict:
    """사후 회고·의사결정 품질 평가 갱신 (결과가 나온 뒤 편집)."""
    e = get_entry(entry_id)
    if e is None:
        return {"ok": False, "reason": "항목을 찾을 수 없습니다."}
    try:
        engine = _engine()
        from sqlalchemy import text
        now = time.time()
        dq = decision_quality if decision_quality in DECISION_QUALITY else e.get("decision_quality")
        rv = review if review is not None else e.get("review")
        with engine.begin() as c:
            c.execute(text(
                f"UPDATE {_TABLE} SET review = :rv, decision_quality = :dq, updated_at = :ts "
                "WHERE entry_id = :id"),
                {"rv": rv, "dq": dq, "ts": now, "id": entry_id})
        return {"ok": True, "entry": get_entry(entry_id)}
    except Exception as ex:
        logger.warning(f"journal review 갱신 실패: {ex}")
        return {"ok": False, "reason": "DB 오류."}


def delete_entry(entry_id: str) -> bool:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE entry_id = :id"), {"id": entry_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"journal 삭제 실패: {e}")
        return False
