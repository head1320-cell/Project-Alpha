"""RegimeSnapshot 영속 저장 — 매크로 국면의 **불변·버전화된** 스냅샷.

메우는 구멍
──────────────────────────────────────────────────────────────────────────────
지금까지 매크로 → AAS 전달은 `AllocationProvider.loadedStrategy`, 즉 ID·버전·시각이
없는 휘발성 브라우저 메모리 객체였다. 새로고침하면 사라지고, 과거 리서치를 오늘의
국면 분류로 채점하는 것을 막을 방법이 없었다. AAS 는 이제 스냅샷을 **ID 로 참조**한다.

설계 (research_runs.py / timing_rules.py 의 방어적 raw-SQL idiom 재사용):
  · 테이블 regime_snapshots — DB 미가용 시 조용히 None/[] (앱은 계속 동작, 정직 보고는 API가)
  · 관측치는 맨 숫자가 아니라 **MacroObservation 신원 그대로** JSON 보존.
    공표시각·빈티지가 없으면 재현이 성립하지 않는다.
  · snapshot_id = "rgs_" + 시각 + 난수 hex

불변식
──────────────────────────────────────────────────────────────────────────────
1. **불변** — 갱신 경로를 제공하지 않는다. 같은 as_of 라도 새 스냅샷이 만들어진다.
   (국면 판정이 바뀌었다면 그것은 새로운 사실이지 기존 기록의 수정이 아니다.)
2. **PIT** — as_of 이후에 공표된 관측치가 섞이면 저장 전에 LookAheadError 로 거부한다.
   경고 후 진행이 아니다.
3. **usage 전파** — 빈티지 없는 시리즈가 하나라도 있으면 스냅샷 전체가 forward_only.
   과거 시뮬레이션에서 조용히 쓰이는 것을 막기 위해 가장 보수적인 값으로 떨어뜨린다.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any

from src.data.pit_macro import DataStatus, MacroObservation, ResearchUsage

logger = logging.getLogger(__name__)

_TABLE = "regime_snapshots"
_inited = False

# 국면 판정 모델 버전 — 축·확률 산출 로직이 바뀌면 올린다(과거 스냅샷과 구분하기 위해).
MODEL_VERSION = "regime-axes-v1"
ENGINE_VERSION = "aas-pit-v1"


class LookAheadError(ValueError):
    """as_of 이후 공표된 관측치를 스냅샷에 넣으려 할 때. 저장 전에 막는다."""


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
            "snapshot_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, "
            "as_of VARCHAR(32), "
            "growth_axis DOUBLE PRECISION, "
            "inflation_axis DOUBLE PRECISION, "
            "phase_probabilities TEXT, "
            "stress_score DOUBLE PRECISION, "
            "confidence DOUBLE PRECISION, "
            "observations TEXT, "
            "data_status VARCHAR(20), "
            "research_usage VARCHAR(24), "
            "model_version VARCHAR(40), "
            "engine_version VARCHAR(40), "
            "code_version VARCHAR(60), "
            "explanation TEXT)"
        ))
        c.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_rgs_asof_created ON {_TABLE} (as_of, created_at)"
        ))
    _inited = True


def code_version() -> str:
    return os.getenv("GIT_SHA") or os.getenv("APP_VERSION") or "dev"


def _new_id() -> str:
    return f"rgs_{int(time.time())}_{secrets.token_hex(4)}"


def _assert_pit(as_of: str, observations: list[MacroObservation]) -> None:
    """as_of 이후 공표분을 저장 **전에** 거부. 어떤 시리즈·언제인지 이름으로 지목한다."""
    late = [o for o in observations if o.release_timestamp and o.release_timestamp > as_of]
    if late:
        detail = ", ".join(f"{o.series_id}@{o.release_timestamp}" for o in late)
        raise LookAheadError(
            f"as_of={as_of} 이후에 공표된 관측치가 포함되어 있습니다: {detail}. "
            "그 시점에 알 수 없던 값이므로 스냅샷에 넣을 수 없습니다."
        )


def _derive_usage(observations: list[MacroObservation]) -> ResearchUsage:
    """가장 약한 고리를 따른다 — 빈티지 없는 시리즈가 하나라도 있으면 forward_only."""
    if not observations:
        return ResearchUsage.UNAVAILABLE
    if any(not o.vintage_id for o in observations):
        return ResearchUsage.FORWARD_ONLY
    return ResearchUsage.BACKTEST_ELIGIBLE


def _derive_status(observations: list[MacroObservation]) -> DataStatus:
    if not observations:
        return DataStatus.UNAVAILABLE
    statuses = {o.data_status for o in observations}
    for weak in (DataStatus.UNAVAILABLE, DataStatus.MOCK, DataStatus.PARTIAL,
                 DataStatus.STALE, DataStatus.DELAYED):
        if weak in statuses:
            return weak
    return DataStatus.REAL


def create_snapshot(
    *,
    as_of: str,
    observations: list[MacroObservation],
    growth_axis: float,
    inflation_axis: float,
    phase_probabilities: dict[str, float],
    stress_score: float,
    confidence: float,
    explanation: str = "",
) -> str | None:
    """불변 스냅샷을 만든다. 성공 시 snapshot_id, DB 미가용 시 None.

    LookAheadError 는 삼키지 않는다 — 데이터 정합성 위반은 조용히 넘어갈 일이 아니다.
    """
    _assert_pit(as_of, observations)          # 저장 전 게이트

    sid = _new_id()
    usage = _derive_usage(observations)
    status = _derive_status(observations)
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} (snapshot_id, created_at, as_of, growth_axis, "
                "inflation_axis, phase_probabilities, stress_score, confidence, observations, "
                "data_status, research_usage, model_version, engine_version, code_version, explanation) "
                "VALUES (:sid, :ts, :asof, :g, :i, :probs, :stress, :conf, :obs, "
                ":status, :usage, :mver, :ever, :cver, :expl)"
            ), {
                "sid": sid, "ts": time.time(), "asof": as_of,
                "g": growth_axis, "i": inflation_axis,
                "probs": json.dumps(phase_probabilities, ensure_ascii=False),
                "stress": stress_score, "conf": confidence,
                "obs": json.dumps([o.to_dict() for o in observations],
                                  ensure_ascii=False, default=str),
                "status": status.value, "usage": usage.value,
                "mver": MODEL_VERSION, "ever": ENGINE_VERSION, "cver": code_version(),
                "expl": explanation,
            })
        return sid
    except Exception as e:  # noqa: BLE001
        logger.warning("regime snapshot 저장 실패: %s", e)
        return None


_COLS = ("snapshot_id, created_at, as_of, growth_axis, inflation_axis, phase_probabilities, "
         "stress_score, confidence, observations, data_status, research_usage, "
         "model_version, engine_version, code_version, explanation")


def _row_to_dict(row, *, full: bool) -> dict[str, Any]:
    def _j(raw, default):
        try:
            return json.loads(raw) if raw else default
        except Exception:
            return default

    d: dict[str, Any] = {
        "snapshot_id": row[0], "created_at": row[1], "as_of": row[2],
        "growth_axis": row[3], "inflation_axis": row[4],
        "phase_probabilities": _j(row[5], {}),
        "stress_score": row[6], "confidence": row[7],
        "data_status": row[9], "research_usage": row[10],
        "model_version": row[11], "engine_version": row[12], "code_version": row[13],
        "explanation": row[14],
    }
    # 목록에서는 관측치 배열을 빼고 개수만 (payload 비대 방지) — 단건은 전부 준다.
    if full:
        d["observations"] = _j(row[8], [])
    else:
        d["observation_count"] = len(_j(row[8], []))
    return d


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            row = c.execute(text(f"SELECT {_COLS} FROM {_TABLE} WHERE snapshot_id = :sid"),
                            {"sid": snapshot_id}).fetchone()
        return _row_to_dict(row, full=True) if row else None
    except Exception as e:  # noqa: BLE001
        logger.warning("regime snapshot 조회 실패: %s", e)
        return None


def list_snapshots(limit: int = 50) -> list[dict[str, Any]]:
    """최신순 요약 목록 (관측치 배열 제외 — 개수만)."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(
                text(f"SELECT {_COLS} FROM {_TABLE} ORDER BY created_at DESC, snapshot_id DESC LIMIT :lim"),
                {"lim": max(1, min(int(limit), 200))},
            ).fetchall()
        return [_row_to_dict(r, full=False) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("regime snapshot 목록 실패: %s", e)
        return []


def delete_snapshot(snapshot_id: str) -> bool:
    """오기재 정리용. 내용 수정이 아니라 삭제만 허용한다(불변식 유지)."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE snapshot_id = :sid"),
                            {"sid": snapshot_id})
        return bool(res.rowcount)
    except Exception as e:  # noqa: BLE001
        logger.warning("regime snapshot 삭제 실패: %s", e)
        return False
