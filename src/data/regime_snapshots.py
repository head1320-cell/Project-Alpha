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
# regime / recommended_mode 는 후행 추가 열이다(Phase 4a).
# ★ALTER 성공 여부를 반드시 확인한다★ — 권한 등으로 ALTER 가 실패했는데 이후 SELECT 가
# 그 열을 참조하면 스냅샷 조회가 통째로 깨진다(수정 전보다 나쁨).
# backtest_runs.py:104~122 가 heartbeat_at 에 대해 같은 이유로 쓰는 패턴을 따른다.
_has_regime_cols = False
# MES 승격 열(M1-S)도 같은 이유로 성공 여부를 따로 들고 있는다 — regime 열과 **독립적으로**
# 붙거나 안 붙으므로, 하나의 플래그로 뭉치면 조회 열 목록이 어긋난다.
_has_mes_cols = False

# MES 스키마 버전 — indicators/models 의 모양이 바뀌면 올린다.
MES_VERSION = 1

# 국면 판정 모델 버전 — 축·확률 산출 로직이 바뀌면 올린다(과거 스냅샷과 구분하기 위해).
MODEL_VERSION = "regime-axes-v1"
ENGINE_VERSION = "aas-pit-v1"


class LookAheadError(ValueError):
    """as_of 이후 공표된 관측치를 스냅샷에 넣으려 할 때. 저장 전에 막는다."""


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure_table(engine) -> None:
    global _inited, _has_regime_cols, _has_mes_cols
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
            "explanation TEXT, "
            "regime VARCHAR(40), "
            "recommended_mode VARCHAR(20))"
        ))
        c.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_rgs_asof_created ON {_TABLE} (as_of, created_at)"
        ))

    # 이미 운영 중인 DB에는 테이블이 있으므로 ALTER 로 붙인다.
    # 두 단계(붙이기 + 실제로 쓸 수 있는지 SELECT 확인)는 `schema_add_columns` 로 모았다 —
    # M1 에서 세 테이블에 같은 일을 하게 되므로 패턴을 복사하지 않는다.
    from src.data.schema_add_columns import add_columns

    _has_regime_cols = add_columns(
        engine, _TABLE,
        [("regime", "VARCHAR(40)"), ("recommended_mode", "VARCHAR(20)")],
        label="regime_snapshots.regime/recommended_mode(국면 라벨)",
    )

    # ── MacroEvidenceSnapshot 승격 (M1-S) ────────────────────────────────────
    # ★ID 공간을 늘리지 않는다★ `rgs_*` 가 계속 유일한 스냅샷 ID 다. 런·ContextStrip·
    # `?snapshot=` 브리지·스펙이 전부 그 ID 를 참조하므로, 새 `mes_*` 테이블을 만들면
    # "어느 ID 를 붙였는가" 를 모든 소비자가 다시 물어야 한다. 여기에 열만 붙인다.
    _has_mes_cols = add_columns(
        engine, _TABLE,
        [("indicators", "TEXT"), ("models", "TEXT"),
         ("capability_level", "VARCHAR(8)"), ("capability_reason", "TEXT"),
         ("mes_version", "INTEGER")],
        label="regime_snapshots.MES(지표·모델·능력 레벨)",
    )

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
    regime: str | None = None,
    recommended_mode: str | None = None,
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
        cols = ("snapshot_id, created_at, as_of, growth_axis, inflation_axis, "
                "phase_probabilities, stress_score, confidence, observations, "
                "data_status, research_usage, model_version, engine_version, code_version, explanation")
        vals = (":sid, :ts, :asof, :g, :i, :probs, :stress, :conf, :obs, "
                ":status, :usage, :mver, :ever, :cver, :expl")
        if _has_regime_cols:
            cols += ", regime, recommended_mode"
            vals += ", :regime, :mode"
        with engine.begin() as c:
            c.execute(text(f"INSERT INTO {_TABLE} ({cols}) VALUES ({vals})"), {
                "sid": sid, "ts": time.time(), "asof": as_of,
                "g": growth_axis, "i": inflation_axis,
                "probs": json.dumps(phase_probabilities, ensure_ascii=False),
                "stress": stress_score, "conf": confidence,
                "obs": json.dumps([o.to_dict() for o in observations],
                                  ensure_ascii=False, default=str),
                "status": status.value, "usage": usage.value,
                "mver": MODEL_VERSION, "ever": ENGINE_VERSION, "cver": code_version(),
                "expl": explanation,
                **({"regime": regime, "mode": recommended_mode} if _has_regime_cols else {}),
            })
        return sid
    except Exception as e:  # noqa: BLE001
        logger.warning("regime snapshot 저장 실패: %s", e)
        return None


def attach_evidence(snapshot_id: str, *, indicators: dict[str, Any],
                    models: dict[str, Any], capability_level: str,
                    capability_reason: str | None) -> bool:
    """스냅샷을 **MacroEvidenceSnapshot 으로 승격**한다 (M1-S).

    스냅샷 자체는 계속 불변이다 — 이 함수는 **생성 직후 한 번** 증거를 채우는 경로이지
    나중에 값을 바꾸는 경로가 아니다. 이미 채워진 스냅샷을 다시 채우려 하면 False 를
    돌려 거부한다: 증거가 사후에 바뀌면 "그 결정을 내릴 때 무엇을 보고 있었는가" 라는
    질문에 답할 수 없게 되고, 그게 스냅샷이 존재하는 유일한 이유다.

    Returns:
        True  — 채웠다.
        False — 열이 없거나(구 DB), 대상이 없거나, **이미 채워져 있다**.
    """
    engine = _engine()
    _ensure_table(engine)
    if not _has_mes_cols:
        logger.warning("MES 열이 없어 증거를 붙이지 못했습니다: %s", snapshot_id)
        return False
    from sqlalchemy import text
    with engine.begin() as c:
        # ★이미 채워졌으면 덮지 않는다★ — WHERE 절이 그 불변식을 DB 레벨에서 강제한다.
        res = c.execute(text(
            f"UPDATE {_TABLE} SET indicators = :ind, models = :mod, "
            "capability_level = :lvl, capability_reason = :rsn, mes_version = :ver "
            "WHERE snapshot_id = :sid AND (indicators IS NULL OR indicators = '')"
        ), {"ind": json.dumps(indicators, ensure_ascii=False, default=str),
            "mod": json.dumps(models, ensure_ascii=False, default=str),
            "lvl": capability_level, "rsn": capability_reason,
            "ver": MES_VERSION, "sid": snapshot_id})
    return bool(res.rowcount)


_BASE_COL_LIST = ["snapshot_id", "created_at", "as_of", "growth_axis", "inflation_axis",
                  "phase_probabilities", "stress_score", "confidence", "observations",
                  "data_status", "research_usage", "model_version", "engine_version",
                  "code_version", "explanation"]
_REGIME_COL_LIST = ["regime", "recommended_mode"]
_MES_COL_LIST = ["indicators", "models", "capability_level", "capability_reason", "mes_version"]


def _col_list() -> list[str]:
    """실제로 SELECT 할 열 이름.

    ★위치 인덱스를 손으로 세지 않는다 (M1-S)★ 예전에는 `row[15]`/`row[16]` 처럼 상수로
    읽었고, "새 열은 끝에만 붙여라" 는 주석이 그 취약함을 지키고 있었다. 그런데 이제
    후행 블록이 **둘**(regime · MES)이고 각각 독립적으로 붙거나 안 붙는다 —
    regime 이 없고 MES 만 있으면 손으로 센 인덱스는 전부 두 칸 밀린다.
    이름 목록에서 인덱스를 파생시키면 그 함정이 구조적으로 사라진다.
    """
    cols = list(_BASE_COL_LIST)
    if _has_regime_cols:
        cols += _REGIME_COL_LIST
    if _has_mes_cols:
        cols += _MES_COL_LIST
    return cols


def _cols() -> str:
    return ", ".join(_col_list())


def _row_to_dict(row, *, full: bool) -> dict[str, Any]:
    def _j(raw, default):
        try:
            return json.loads(raw) if raw else default
        except Exception:
            return default

    names = _col_list()
    g = dict(zip(names, row, strict=False))

    d: dict[str, Any] = {
        "snapshot_id": g.get("snapshot_id"), "created_at": g.get("created_at"),
        "as_of": g.get("as_of"),
        "growth_axis": g.get("growth_axis"), "inflation_axis": g.get("inflation_axis"),
        "phase_probabilities": _j(g.get("phase_probabilities"), {}),
        "stress_score": g.get("stress_score"), "confidence": g.get("confidence"),
        "data_status": g.get("data_status"), "research_usage": g.get("research_usage"),
        "model_version": g.get("model_version"), "engine_version": g.get("engine_version"),
        "code_version": g.get("code_version"), "explanation": g.get("explanation"),
        # 후행 추가 열 — 없으면 None(있는 척하지 않는다)
        "regime": g.get("regime"), "recommended_mode": g.get("recommended_mode"),
        # ── MES (M1-S) ──
        # ★`indicators` 는 값이 없어도 키가 있는 것이 계약이다★ 여기서 `{}` 로 두는 것은
        # "아직 MES 로 만들어지지 않은 스냅샷" 이라는 뜻이고, 지표별 미가용은 그 안에
        # `{available:false, reason}` 로 들어간다. 둘은 다른 사실이다.
        "indicators": _j(g.get("indicators"), {}),
        "models": _j(g.get("models"), {}),
        "capability_level": g.get("capability_level"),
        "capability_reason": g.get("capability_reason"),
        "mes_version": g.get("mes_version"),
    }
    # 목록에서는 관측치 배열을 빼고 개수만 (payload 비대 방지) — 단건은 전부 준다.
    if full:
        d["observations"] = _j(g.get("observations"), [])
    else:
        d["observation_count"] = len(_j(g.get("observations"), []))
    return d


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            row = c.execute(text(f"SELECT {_cols()} FROM {_TABLE} WHERE snapshot_id = :sid"),
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
                text(f"SELECT {_cols()} FROM {_TABLE} ORDER BY created_at DESC, snapshot_id DESC LIMIT :lim"),
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
