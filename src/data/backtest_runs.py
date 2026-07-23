"""BacktestRun 영속 저장 — 백테스트 실행의 durable 도메인 객체 (Backtest Run Workflow)
==============================================================================
`configure → create BacktestRun → loading page → results page`의 상태 소스.
브라우저 새로고침·직접 URL 방문·일시적 네트워크 단절에도 백엔드(DB)에서 실행 상태를
복구한다 (in-memory React state에 의존하지 않음).

상태 모델(스펙):
  draft → queued → validating → loading_data → simulating → calculating_metrics →
  persisting_results → completed
종료 상태: failed · cancelled · expired (재시도는 새 run 생성 — 실행 이력은 불변).

research_runs / execution_store 와 동일한 방어적 raw-SQL idiom (DB 선택적, 실패 시 None).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "backtest_runs"
_inited = False

STATUSES = (
    "draft", "queued", "validating", "loading_data", "simulating",
    "calculating_metrics", "persisting_results", "completed",
    "failed", "cancelled", "expired",
)
# 진행 단계 순서(로딩 페이지 타임라인 + 진행률 힌트)
STAGE_ORDER = (
    "queued", "validating", "loading_data", "simulating",
    "calculating_metrics", "persisting_results", "completed",
)
TERMINAL = ("completed", "failed", "cancelled", "expired")

_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"queued", "cancelled"},
    "queued": {"validating", "failed", "cancelled"},
    "validating": {"loading_data", "failed", "cancelled"},
    "loading_data": {"simulating", "failed", "cancelled"},
    "simulating": {"calculating_metrics", "failed", "cancelled"},
    "calculating_metrics": {"persisting_results", "failed", "cancelled"},
    "persisting_results": {"completed", "failed", "cancelled"},
    "completed": {"expired"},
    "failed": set(), "cancelled": set(), "expired": set(),
}

# run_id 이후에 진행률 힌트로 쓰는 단계별 대략 진행률 (backend가 실제 진행을 못 줄 때만)
_STAGE_PCT = {
    "queued": 2, "validating": 8, "loading_data": 20, "simulating": 60,
    "calculating_metrics": 85, "persisting_results": 95, "completed": 100,
}

_COLS = ("run_id, created_at, started_at, completed_at, requested_by, strategy_name, "
         "status, progress_percent, current_stage, status_message, input_snapshot, "
         "parameter_snapshot, data_snapshot_id, engine_version, result_version, "
         "error_code, error_message, correlation_id, is_mock_data, is_pit_verified, result")


def engine_version() -> str:
    return os.getenv("BACKTEST_ENGINE_VERSION") or os.getenv("GIT_SHA") or "dev"


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
            "run_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, started_at DOUBLE PRECISION, completed_at DOUBLE PRECISION, "
            "requested_by VARCHAR(60), strategy_name TEXT, status VARCHAR(24), "
            "progress_percent DOUBLE PRECISION, current_stage VARCHAR(24), status_message TEXT, "
            "input_snapshot TEXT, parameter_snapshot TEXT, data_snapshot_id VARCHAR(60), "
            "engine_version VARCHAR(60), result_version VARCHAR(20), "
            "error_code VARCHAR(60), error_message TEXT, correlation_id VARCHAR(40), "
            "is_mock_data INTEGER, is_pit_verified INTEGER, result TEXT)"
        ))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_btr_created ON {_TABLE} (created_at)"))
    _inited = True


def _new_run_id() -> str:
    return f"bt_{int(time.time())}_{secrets.token_hex(4)}"


def _row(r, full: bool) -> dict[str, Any]:
    d = {
        "run_id": r[0], "created_at": r[1], "started_at": r[2], "completed_at": r[3],
        "requested_by": r[4], "strategy_name": r[5], "status": r[6],
        "progress_percent": r[7], "current_stage": r[8], "status_message": r[9],
        "data_snapshot_id": r[12], "engine_version": r[13], "result_version": r[14],
        "error_code": r[15], "error_message": r[16], "correlation_id": r[17],
        "is_mock_data": bool(r[18]) if r[18] is not None else None,
        "is_pit_verified": bool(r[19]) if r[19] is not None else None,
    }
    if full:
        for key, idx in (("input_snapshot", 10), ("parameter_snapshot", 11), ("result", 20)):
            try:
                d[key] = json.loads(r[idx]) if r[idx] else None
            except Exception:
                d[key] = None
    return d


def create_run(strategy_name: str, input_snapshot: dict,
               parameter_snapshot: dict | None = None, requested_by: str = "user",
               correlation_id: str | None = None, is_mock_data: bool | None = None,
               is_pit_verified: bool | None = None,
               data_snapshot_id: str | None = None) -> str | None:
    """새 실행을 queued 상태로 영속화. 성공 시 run_id, DB 미가용 시 None(호출자 정직 보고)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        rid = _new_run_id()
        now = time.time()
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} ({_COLS}) VALUES "
                "(:id, :ca, NULL, NULL, :by, :nm, 'queued', 2, 'queued', :msg, :inp, :par, "
                ":dsid, :ev, :rv, NULL, NULL, :cid, :mock, :pit, NULL)"),
                {"id": rid, "ca": now, "by": requested_by, "nm": strategy_name,
                 "msg": "대기열에 등록됨",
                 "inp": json.dumps(input_snapshot, ensure_ascii=False, default=str),
                 "par": json.dumps(parameter_snapshot or {}, ensure_ascii=False, default=str),
                 "dsid": data_snapshot_id, "ev": engine_version(), "rv": "1",
                 "cid": correlation_id or rid,
                 "mock": None if is_mock_data is None else int(is_mock_data),
                 "pit": None if is_pit_verified is None else int(is_pit_verified)})
        return rid
    except Exception as e:
        logger.warning(f"backtest run 생성 실패: {e}")
        return None


def get_run(run_id: str) -> dict | None:
    return _fetch(run_id, full=True)


def get_status(run_id: str) -> dict | None:
    """폴링용 경량 상태 (스냅샷·result 제외)."""
    return _fetch(run_id, full=False)


def _fetch(run_id: str, full: bool) -> dict | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {_COLS} FROM {_TABLE} WHERE run_id = :id"),
                          {"id": run_id}).fetchone()
        return _row(r, full=full) if r else None
    except Exception as e:
        logger.warning(f"backtest run 조회 실패: {e}")
        return None


def list_runs(limit: int = 30) -> list[dict]:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT {_COLS} FROM {_TABLE} ORDER BY created_at DESC LIMIT :l"),
                {"l": max(1, min(int(limit), 100))}).fetchall()
        return [_row(r, full=False) for r in rows]
    except Exception as e:
        logger.warning(f"backtest run 목록 실패: {e}")
        return []


def can_transition(cur: str, to: str) -> bool:
    return to in _TRANSITIONS.get(cur, set())


def transition(run_id: str, to_status: str, message: str | None = None,
               progress: float | None = None) -> dict:
    """상태 전이(불법 전이 거부). 진행 단계 진입 시 started_at 스탬프 + 진행률 힌트."""
    if to_status not in STATUSES:
        return {"ok": False, "reason": f"알 수 없는 상태: {to_status}"}
    p = get_status(run_id)
    if p is None:
        return {"ok": False, "reason": "실행을 찾을 수 없습니다."}
    cur = p["status"]
    if not can_transition(cur, to_status):
        return {"ok": False,
                "reason": f"{cur} → {to_status} 전이 불가 (허용: {sorted(_TRANSITIONS.get(cur, set())) or '없음(종료)'})"}
    try:
        engine = _engine()
        from sqlalchemy import text
        now = time.time()
        pct = progress if progress is not None else _STAGE_PCT.get(to_status, p.get("progress_percent") or 0)
        sets = ["status = :s", "current_stage = :s", "progress_percent = :pct", "status_message = :msg"]
        params = {"s": to_status, "pct": pct,
                  "msg": message or _default_msg(to_status), "id": run_id}
        if cur == "queued" and to_status == "validating":
            sets.append("started_at = :sa"); params["sa"] = now
        if to_status in TERMINAL:
            sets.append("completed_at = :co"); params["co"] = now
        with engine.begin() as c:
            c.execute(text(f"UPDATE {_TABLE} SET {', '.join(sets)} WHERE run_id = :id"), params)
        return {"ok": True, "status": to_status}
    except Exception as e:
        logger.warning(f"backtest transition 실패: {e}")
        return {"ok": False, "reason": "DB 오류로 전이 실패."}


def advance(run_id: str, to_status: str, message: str | None = None,
            progress: float | None = None) -> dict:
    """현재 단계에서 to_status까지 STAGE_ORDER를 따라 순차 전이(이미 지난 단계는 스킵).
    백그라운드 워커가 어떤 진행 이벤트가 오든 목표 단계에 안전히 도달하게 한다."""
    p = get_status(run_id)
    if p is None:
        return {"ok": False, "reason": "실행을 찾을 수 없습니다."}
    if p["status"] in TERMINAL:
        return {"ok": False, "reason": f"종료 상태({p['status']})."}
    if to_status not in STAGE_ORDER or p["status"] not in STAGE_ORDER:
        return transition(run_id, to_status, message, progress)
    ci, ti = STAGE_ORDER.index(p["status"]), STAGE_ORDER.index(to_status)
    if ti <= ci:   # 이미 도달/초과 — 진행률·메시지만 갱신
        if progress is not None or message is not None:
            update_progress(run_id, progress if progress is not None else (p["progress_percent"] or 0), message)
        return {"ok": True}
    r = {"ok": True}
    for i in range(ci + 1, ti + 1):
        last = i == ti
        r = transition(run_id, STAGE_ORDER[i], message if last else None, progress if last else None)
        if not r["ok"]:
            return r
    return r


def update_progress(run_id: str, progress: float, message: str | None = None,
                    stage: str | None = None) -> bool:
    """상태 변경 없이 진행률/메시지만 갱신 (시뮬레이션 루프의 세부 진행)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        sets = ["progress_percent = :p"]
        params: dict[str, Any] = {"p": max(0.0, min(100.0, float(progress))), "id": run_id}
        if message is not None:
            sets.append("status_message = :m"); params["m"] = message
        if stage is not None:
            sets.append("current_stage = :st"); params["st"] = stage
        with engine.begin() as c:
            res = c.execute(text(f"UPDATE {_TABLE} SET {', '.join(sets)} WHERE run_id = :id"), params)
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"backtest progress 갱신 실패: {e}")
        return False


def set_result(run_id: str, result: dict, is_mock_data: bool | None = None,
               is_pit_verified: bool | None = None) -> dict:
    """결과 저장 + completed. persisting_results → completed 전이를 겸함."""
    p = get_status(run_id)
    if p is None:
        return {"ok": False, "reason": "실행을 찾을 수 없습니다."}
    if p["status"] not in ("persisting_results", "calculating_metrics", "simulating"):
        return {"ok": False, "reason": f"{p['status']} 상태에선 결과 저장 불가."}
    try:
        engine = _engine()
        from sqlalchemy import text
        now = time.time()
        sets = ["status = 'completed'", "current_stage = 'completed'", "progress_percent = 100",
                "status_message = '완료', completed_at = :co", "result = :res"]
        params = {"co": now, "res": json.dumps(result, ensure_ascii=False, default=str), "id": run_id}
        if is_mock_data is not None:
            sets.append("is_mock_data = :mk"); params["mk"] = int(is_mock_data)
        if is_pit_verified is not None:
            sets.append("is_pit_verified = :pit"); params["pit"] = int(is_pit_verified)
        with engine.begin() as c:
            c.execute(text(f"UPDATE {_TABLE} SET {', '.join(sets)} WHERE run_id = :id"), params)
        return {"ok": True}
    except Exception as e:
        logger.warning(f"backtest 결과 저장 실패: {e}")
        return {"ok": False, "reason": "DB 오류."}


def set_error(run_id: str, error_code: str, error_message: str) -> dict:
    """실패 처리 — 어떤 비종료 상태에서든 failed로. 민감정보는 담지 말 것(호출자 책임)."""
    p = get_status(run_id)
    if p is None:
        return {"ok": False, "reason": "실행을 찾을 수 없습니다."}
    if p["status"] in TERMINAL:
        return {"ok": False, "reason": f"이미 종료 상태({p['status']})."}
    try:
        engine = _engine()
        from sqlalchemy import text
        now = time.time()
        with engine.begin() as c:
            c.execute(text(
                f"UPDATE {_TABLE} SET status='failed', current_stage='failed', "
                "status_message='실패', error_code=:ec, error_message=:em, completed_at=:co "
                "WHERE run_id = :id"),
                {"ec": error_code, "em": error_message, "co": now, "id": run_id})
        return {"ok": True}
    except Exception as e:
        logger.warning(f"backtest 오류 기록 실패: {e}")
        return {"ok": False, "reason": "DB 오류."}


def cancel(run_id: str) -> dict:
    """취소 — 비종료 상태에서만."""
    p = get_status(run_id)
    if p is None:
        return {"ok": False, "reason": "실행을 찾을 수 없습니다."}
    if p["status"] in TERMINAL:
        return {"ok": False, "reason": f"이미 종료 상태({p['status']}) — 취소 불가."}
    try:
        engine = _engine()
        from sqlalchemy import text
        now = time.time()
        with engine.begin() as c:
            c.execute(text(
                f"UPDATE {_TABLE} SET status='cancelled', current_stage='cancelled', "
                "status_message='취소됨', completed_at=:co WHERE run_id = :id"),
                {"co": now, "id": run_id})
        return {"ok": True}
    except Exception as e:
        logger.warning(f"backtest 취소 실패: {e}")
        return {"ok": False, "reason": "DB 오류."}


def delete_run(run_id: str) -> bool:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE run_id = :id"), {"id": run_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"backtest run 삭제 실패: {e}")
        return False


def _default_msg(status: str) -> str:
    return {
        "validating": "전략 설정 검증 중",
        "loading_data": "시점(PIT) 데이터 로딩 중",
        "simulating": "주문·체결 시뮬레이션 중",
        "calculating_metrics": "성과·리스크 지표 계산 중",
        "persisting_results": "재현 가능한 결과 저장 중",
        "completed": "완료",
        "failed": "실패", "cancelled": "취소됨", "expired": "만료됨",
    }.get(status, status)
