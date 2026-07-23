"""실행 계획 영속 + 승인 워크플로 + 감사 로그 (Full Expansion P4)
==============================================================================
주문 상태 모델 (지시서):
  draft → reviewed → approved → paper_submitted → partially_filled →
  filled → cancelled → rejected → reconciled
브로커 연결 전에는 paper_submitted 이후 상태를 자동 시뮬레이션하지 않는다.
partially_filled/filled/reconciled는 수동 체결 입력으로만 진입.

pre-trade가 block이면 approved로 전이 불가(§4). 모든 상태 변경은 감사 로그에 기록.
research_runs와 동일한 방어적 raw-SQL idiom.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "execution_plans"
_inited = False

STATUSES = ("draft", "reviewed", "approved", "paper_submitted",
            "partially_filled", "filled", "cancelled", "rejected", "reconciled")

# 허용 전이 — 자동 진행은 paper_submitted까지. 이후는 수동 체결/취소만.
_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"reviewed", "cancelled"},
    "reviewed": {"approved", "draft", "rejected", "cancelled"},
    "approved": {"paper_submitted", "cancelled", "rejected"},
    "paper_submitted": {"partially_filled", "filled", "cancelled", "rejected"},
    "partially_filled": {"filled", "cancelled", "reconciled"},
    "filled": {"reconciled"},
    "cancelled": set(), "rejected": set(), "reconciled": set(),
}


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
            "plan_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION, "
            "name TEXT, status VARCHAR(20), run_id VARCHAR(40), "
            "plan TEXT, pretrade TEXT, fills TEXT, audit TEXT)"
        ))
    _inited = True


def _row(r, full: bool) -> dict[str, Any]:
    d = {"plan_id": r[0], "created_at": r[1], "updated_at": r[2],
         "name": r[3], "status": r[4], "run_id": r[5]}
    for key, idx in (("audit", 9),):
        try:
            d[key] = json.loads(r[idx]) if r[idx] else []
        except Exception:
            d[key] = []
    if full:
        for key, idx in (("plan", 6), ("pretrade", 7), ("fills", 8)):
            try:
                d[key] = json.loads(r[idx]) if r[idx] else None
            except Exception:
                d[key] = None
    return d


_COLS = "plan_id, created_at, updated_at, name, status, run_id, plan, pretrade, fills, audit"


def create_plan(name: str, plan: dict, pretrade: dict,
                run_id: str | None = None) -> str | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        pid = f"ep_{int(time.time())}_{secrets.token_hex(4)}"
        now = time.time()
        audit = [{"ts": now, "action": "created", "status": "draft",
                  "detail": f"{plan.get('summary', {}).get('n_orders', 0)}건 주문"}]
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} ({_COLS}) VALUES "
                "(:id, :ts, :ts, :nm, 'draft', :rid, :pl, :pt, NULL, :au)"),
                {"id": pid, "ts": now, "nm": name, "rid": run_id,
                 "pl": json.dumps(plan, ensure_ascii=False, default=str),
                 "pt": json.dumps(pretrade, ensure_ascii=False, default=str),
                 "au": json.dumps(audit, ensure_ascii=False)})
        return pid
    except Exception as e:
        logger.warning(f"execution plan 생성 실패: {e}")
        return None


def get_plan(plan_id: str) -> dict | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {_COLS} FROM {_TABLE} WHERE plan_id = :id"),
                          {"id": plan_id}).fetchone()
        return _row(r, full=True) if r else None
    except Exception as e:
        logger.warning(f"execution plan 조회 실패: {e}")
        return None


def list_plans(limit: int = 30) -> list[dict]:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT {_COLS} FROM {_TABLE} ORDER BY updated_at DESC LIMIT :l"),
                {"l": max(1, min(int(limit), 100))}).fetchall()
        return [_row(r, full=False) for r in rows]
    except Exception as e:
        logger.warning(f"execution plan 목록 실패: {e}")
        return []


def transition(plan_id: str, to_status: str, actor: str = "user",
               note: str = "") -> dict:
    """상태 전이 — 요건 미충족 시 정직 사유. approved는 pre-trade block 없을 때만."""
    if to_status not in STATUSES:
        return {"ok": False, "reason": f"알 수 없는 상태: {to_status}"}
    p = get_plan(plan_id)
    if p is None:
        return {"ok": False, "reason": "계획을 찾을 수 없습니다."}
    cur = p["status"]
    if to_status not in _TRANSITIONS.get(cur, set()):
        return {"ok": False,
                "reason": f"{cur} → {to_status} 전이 불가 (허용: {sorted(_TRANSITIONS.get(cur, set())) or '없음(종료 상태)'})"}
    if to_status == "approved":
        pt = p.get("pretrade") or {}
        if not pt.get("can_approve", False):
            return {"ok": False, "reason": "pre-trade가 block 상태 — 승인 불가 (지시서 §4). block 항목을 해소하세요."}
    try:
        engine = _engine()
        from sqlalchemy import text
        now = time.time()
        audit = p.get("audit", []) + [{"ts": now, "action": "transition",
                                       "from": cur, "status": to_status,
                                       "actor": actor, "note": note}]
        with engine.begin() as c:
            c.execute(text(
                f"UPDATE {_TABLE} SET status = :s, updated_at = :ts, audit = :au WHERE plan_id = :id"),
                {"s": to_status, "ts": now,
                 "au": json.dumps(audit, ensure_ascii=False), "id": plan_id})
        return {"ok": True, "plan": get_plan(plan_id)}
    except Exception as e:
        logger.warning(f"execution transition 실패: {e}")
        return {"ok": False, "reason": "DB 오류로 전이 실패."}


def record_fills(plan_id: str, fills: list[dict], actor: str = "user") -> dict:
    """수동 체결 결과 입력 — partially_filled/filled로 진입(자동 시뮬 아님)."""
    p = get_plan(plan_id)
    if p is None:
        return {"ok": False, "reason": "계획을 찾을 수 없습니다."}
    if p["status"] not in ("paper_submitted", "partially_filled"):
        return {"ok": False, "reason": f"{p['status']} 상태에선 체결 입력 불가 (paper_submitted 이후만)."}
    n_orders = len((p.get("plan") or {}).get("orders", []))
    filled_all = len(fills) >= n_orders and all(f.get("filled_qty", 0) > 0 for f in fills)
    to = "filled" if filled_all else "partially_filled"
    try:
        engine = _engine()
        from sqlalchemy import text
        now = time.time()
        audit = p.get("audit", []) + [{"ts": now, "action": "fills",
                                       "status": to, "actor": actor,
                                       "detail": f"{len(fills)}건 체결 입력"}]
        with engine.begin() as c:
            c.execute(text(
                f"UPDATE {_TABLE} SET status = :s, fills = :f, updated_at = :ts, audit = :au "
                "WHERE plan_id = :id"),
                {"s": to, "f": json.dumps(fills, ensure_ascii=False, default=str),
                 "ts": now, "au": json.dumps(audit, ensure_ascii=False), "id": plan_id})
        return {"ok": True, "plan": get_plan(plan_id)}
    except Exception as e:
        logger.warning(f"체결 입력 실패: {e}")
        return {"ok": False, "reason": "DB 오류."}


def find_by_run(run_id: str) -> dict | None:
    """run_id로 연결된 최신 실행계획 전체 (Attribution의 체결·비용 연결용)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(
                f"SELECT {_COLS} FROM {_TABLE} WHERE run_id = :rid ORDER BY updated_at DESC LIMIT 1"),
                {"rid": run_id}).fetchone()
        return _row(r, full=True) if r else None
    except Exception as e:
        logger.warning(f"execution plan run 조회 실패: {e}")
        return None


def delete_plan(plan_id: str) -> bool:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE plan_id = :id"), {"id": plan_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"execution plan 삭제 실패: {e}")
        return False
