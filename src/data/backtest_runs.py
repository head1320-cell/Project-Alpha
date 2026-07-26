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
# heartbeat_at 컬럼 사용 가능 여부 (_ensure가 실측으로 확정) — 마이그레이션이 막힌 배포에서도
# 진행률 기록이 깨지지 않도록, 이 플래그가 False면 하트비트 절만 빼고 동일하게 동작한다.
_has_heartbeat = False

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
# 폴링용 좁은 투영 — `result`(완료 시 수 MB까지 자라는 TEXT blob)를 제외한다. 1초 주기로
# 도는 status 폴링이 결과 전체를 매번 실어 나르면 커넥션 점유가 길어져, 정작 실행 중인
# 워커의 진행 기록과 커넥션 풀(pool_size=5 + overflow=10)을 두고 경합한다.
# _row(full=False)가 인덱스 0..19만 읽으므로 마지막 컬럼만 떼면 매핑은 그대로 유효하다.
_STATUS_COLS = _COLS.rsplit(",", 1)[0]

# 하트비트가 이 시간 이상 끊긴 비종료 실행은 고아로 판정(컨테이너 재시작 등으로 워커
# 스레드가 사라진 경우). 진행 이벤트 간격보다 넉넉해야 정상 실행을 죽이지 않는다.
ORPHAN_SILENCE_SEC = 900.0


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
    # 하트비트 컬럼(후행 추가) — 이미 운영 중인 DB에는 테이블이 존재하므로 ALTER로 붙인다.
    # SQLite는 ADD COLUMN에 IF NOT EXISTS를 지원하지 않아 "이미 있음"도 예외로 오므로 삼킨다.
    # _COLS에는 넣지 않는다 — 넣으면 _row의 위치 인덱스가 전부 밀린다.
    global _has_heartbeat
    try:
        with engine.begin() as c:
            c.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN heartbeat_at DOUBLE PRECISION"))
    except Exception:
        pass
    # ★실제로 붙었는지 확인★ — 권한 등으로 ALTER가 실패했는데 이후 쿼리가 이 컬럼을
    # 참조하면 진행률 기록이 통째로 깨진다(수정 전보다 나쁨). 없으면 하트비트 기능만
    # 끄고 나머지는 그대로 동작시킨다(고아 정리는 created_at 폴백으로 계속 가능).
    try:
        with engine.connect() as c:
            c.execute(text(f"SELECT heartbeat_at FROM {_TABLE} LIMIT 1"))
        _has_heartbeat = True
    except Exception as e:
        _has_heartbeat = False
        logger.warning(f"backtest_runs.heartbeat_at 사용 불가 — 하트비트 없이 동작: {e}")
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


class BacktestStoreError(Exception):
    """저장소(DB) 접근 실패 — '실행 없음(None)'과 구분해야 하는 일시적 오류.

    API 계층이 이걸 잡아 404(진짜 없음)가 아닌 503(일시적 오류)으로 응답하면, 프론트 로딩
    페이지가 '만료된 링크'로 오인해 폴링을 포기하지 않고 재시도할 수 있다.
    """


def get_run(run_id: str, strict: bool = False) -> dict | None:
    return _fetch(run_id, full=True, strict=strict)


def get_status(run_id: str, strict: bool = False) -> dict | None:
    """폴링용 경량 상태 (스냅샷·result 제외).

    strict=False(기본, 내부 전이 로직용): DB 오류를 None으로 삼킴(방어적).
    strict=True(API 엔드포인트용): DB 오류를 BacktestStoreError로 올려 404와 구분.
    """
    return _fetch(run_id, full=False, strict=strict)


def _fetch(run_id: str, full: bool, strict: bool = False) -> dict | None:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        cols = _COLS if full else _STATUS_COLS
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {cols} FROM {_TABLE} WHERE run_id = :id"),
                          {"id": run_id}).fetchone()
        return _row(r, full=full) if r else None
    except Exception as e:
        logger.warning(f"backtest run 조회 실패: {e}")
        if strict:
            raise BacktestStoreError(str(e)) from e
        return None


def list_runs(limit: int = 30) -> list[dict]:
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT {_STATUS_COLS} FROM {_TABLE} ORDER BY created_at DESC LIMIT :l"),
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
        sets = ["status = :s", "current_stage = :s", "progress_percent = :pct",
                "status_message = :msg"]
        params = {"s": to_status, "pct": pct,
                  "msg": message or _default_msg(to_status), "id": run_id}
        if _has_heartbeat:
            sets.append("heartbeat_at = :hb"); params["hb"] = now
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
        return {"ok": False, "reason": "실행을 찾을 수 없습니다.", "missing": True}
    if p["status"] in TERMINAL:
        # 호출자(워커)가 별도 get_status 없이 취소를 감지할 수 있게 플래그로 알린다 —
        # 진행 이벤트마다 커넥션을 한 번이라도 덜 잡기 위함.
        return {"ok": False, "reason": f"종료 상태({p['status']}).",
                "terminal": True, "cancelled": p["status"] == "cancelled"}
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
        if _has_heartbeat:
            sets.append("heartbeat_at = :hb"); params["hb"] = time.time()
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


def touch_progress(run_id: str, progress: float, message: str | None = None) -> str:
    """진행률 갱신의 단일 쿼리 핫패스 — 커넥션 체크아웃 1회.

    워커는 진행 이벤트마다 (취소 확인 SELECT + advance의 SELECT + UPDATE) 3회를 잡고 있었다.
    이미 진입한 단계 안에서의 세부 진행은 조건부 UPDATE 한 번이면 충분하다:
    종료 상태(취소 포함)면 WHERE에 걸려 rowcount 0 → 호출자가 그때만 상태를 확인하면 된다.

    반환: "updated"(정상) · "blocked"(없거나 종료 상태 — 호출자가 확인) · "error"(DB 오류)
    """
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        sets = ["progress_percent = :p"]
        params: dict[str, Any] = {"p": max(0.0, min(100.0, float(progress))), "id": run_id}
        if _has_heartbeat:
            sets.append("heartbeat_at = :hb"); params["hb"] = time.time()
        if message is not None:
            sets.append("status_message = :m"); params["m"] = message
        placeholders = ", ".join(f":t{i}" for i in range(len(TERMINAL)))
        params.update({f"t{i}": s for i, s in enumerate(TERMINAL)})
        with engine.begin() as c:
            res = c.execute(text(
                f"UPDATE {_TABLE} SET {', '.join(sets)} "
                f"WHERE run_id = :id AND status NOT IN ({placeholders})"), params)
        return "updated" if res.rowcount else "blocked"
    except Exception as e:
        logger.warning(f"backtest progress 갱신 실패: {e}")
        return "error"


def heartbeat(run_id: str) -> None:
    """살아있음 표시만 갱신(진행률 변화가 없는 긴 구간용)."""
    try:
        engine = _engine()
        _ensure(engine)
        if not _has_heartbeat:
            return
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text(f"UPDATE {_TABLE} SET heartbeat_at = :hb WHERE run_id = :id"),
                      {"hb": time.time(), "id": run_id})
    except Exception as e:
        logger.debug(f"backtest heartbeat 실패: {e}")


def sweep_orphaned(max_silence_sec: float = ORPHAN_SILENCE_SEC) -> int:
    """고아 실행 정리 — 워커 스레드가 사라졌는데 비종료로 남은 행을 failed로 확정.

    실행 워커는 daemon 스레드라 컨테이너 재시작·배포 시 정리 없이 사라진다. 그러면 그 행은
    영원히 `loading_data` 같은 비종료 상태로 남고, 결과 페이지는 끝나지 않는 실행을 계속
    보여준다. 기동 시 한 번 훑어 하트비트가 끊긴 것만 정직한 사유와 함께 종료 처리한다.
    (하트비트가 아직 없는 구버전 행은 created_at을 대신 본다.)

    반환: 정리된 행 수.
    """
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        cutoff = time.time() - max(60.0, float(max_silence_sec))
        placeholders = ", ".join(f":t{i}" for i in range(len(TERMINAL)))
        params: dict[str, Any] = {f"t{i}": s for i, s in enumerate(TERMINAL)}
        params.update({"cut": cutoff, "co": time.time()})
        # 하트비트 컬럼이 없는 배포에서는 created_at만으로 판정(기능 축소, 동작 유지)
        age = "COALESCE(heartbeat_at, created_at)" if _has_heartbeat else "created_at"
        with engine.begin() as c:
            res = c.execute(text(
                f"UPDATE {_TABLE} SET status='failed', current_stage='failed', "
                "status_message='중단됨', error_code='worker_lost', "
                "error_message='서버가 재시작되어 이 실행의 워커가 중단되었습니다. "
                "다시 실행해 주세요.', completed_at=:co "
                f"WHERE status NOT IN ({placeholders}) AND {age} < :cut"), params)
        n = int(res.rowcount or 0)
        if n:
            logger.warning(f"고아 backtest run {n}건을 failed로 정리(워커 유실)")
        return n
    except Exception as e:
        logger.warning(f"backtest 고아 정리 실패: {e}")
        return 0


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
    """취소 — 비종료 상태에서만.

    실패 사유를 구분해 돌려준다(예전엔 셋 다 뭉뚱그려 409가 됐다):
    missing=실행 없음(404) · store_error=DB 오류(503) · terminal=이미 종료(409).
    """
    try:
        p = get_status(run_id, strict=True)
    except BacktestStoreError as e:
        return {"ok": False, "reason": "실행 저장소(DB)에 접근할 수 없습니다.",
                "store_error": True, "detail": str(e)}
    if p is None:
        return {"ok": False, "reason": "실행을 찾을 수 없습니다.", "missing": True}
    if p["status"] in TERMINAL:
        return {"ok": False, "reason": f"이미 종료 상태({p['status']}) — 취소 불가.",
                "terminal": True}
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
        return {"ok": False, "reason": "DB 오류.", "store_error": True}


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
